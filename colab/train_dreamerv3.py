"""Crafter DreamerV3 100k Steps 训练脚本 (专为 Google Colab 与远程 GPU 环境设计).

功能特点:
1. 自动环境检查: 检测 GPU / CUDA、JAX 设备、Python 版本。
2. 自动拉取与补齐依赖: 自动克隆官方 danijar/dreamerv3 仓库，并安装所缺依赖。
3. 显存优化保护: 针对 Colab T4/V100/A100 优化 JAX 显存分配策略，防止 OOM。
4. 规范参数配置: 默认应用 Crafter 专属预设，精准执行 100k 环境步 (100,000 steps)。
5. 结果汇总与打包: 训练结束后自动提取关键指标 (得分、存活步长、成就解锁率) 并打包权重日志。
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def log_header(msg: str):
    print("\n" + "=" * 65)
    print(f" [DreamerV3 Colab Runner] {msg}")
    print("=" * 65 + "\n")


def check_and_setup_gpu():
    """检查 GPU 并优化 JAX 显存分配设置."""
    os.environ["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"
    os.environ["XLA_PYTHON_CLIENT_MEM_FRACTION"] = "0.85"
    os.environ["TF_FORCE_GPU_ALLOW_GROWTH"] = "true"

    try:
        import jax

        devices = jax.devices()
        gpu_devices = [d for d in devices if d.platform == "gpu"]
        if gpu_devices:
            print(f"[GPU 检测] 成功检测到 JAX GPU 设备: {gpu_devices}")
            return True
        else:
            print(f"[警告] 未检测到 GPU，当前 JAX 设备: {devices}")
            return False
    except ImportError:
        print("[GPU 检测] JAX 尚未安装，将在依赖安装阶段自动配置...")
        return None


def ensure_repository(repo_dir: Path):
    """确保官方 dreamerv3 仓库已就绪."""
    if (repo_dir / "dreamerv3" / "main.py").exists():
        print(f"[仓库] 已检测到 DreamerV3 仓库: {repo_dir}")
        return

    print(f"[仓库] 正在克隆官方 danijar/dreamerv3 到 {repo_dir}...")
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["git", "clone", "https://github.com/danijar/dreamerv3.git", str(repo_dir)]
    )
    print("[仓库] 克隆完成。")


def ensure_dependencies(repo_dir: Path):
    """自动检查并补全 Crafter 和 DreamerV3 核心运行时依赖."""
    log_header("检查并安装运行依赖")

    # 1. 精准依赖列表 (过滤掉 requirements.txt 中死锁旧版 CUDA 与 Atari 的冲突项)
    needed_pkgs = [
        ("crafter", "crafter"),
        ("elements", "elements>=3.19.1"),
        ("portal", "portal>=3.5.0"),
        ("ninjax", "ninjax>=3.5.1"),
        ("optax", "optax"),
        ("chex", "chex"),
        ("einops", "einops"),
        ("scope", "scope>=0.4.4"),
        ("ruamel.yaml", "ruamel.yaml"),
        ("matplotlib", "matplotlib"),
        ("pandas", "pandas"),
    ]

    for import_name, install_name in needed_pkgs:
        try:
            __import__(import_name.split(".")[0])
            print(f"[依赖就绪] {import_name}: 已存在")
        except ImportError:
            print(f"[依赖安装] 正在安装 {install_name}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", install_name])

    # 2. 检查 JAX 运行状态
    try:
        import jax
        print(f"[依赖就绪] jax: 已就绪 (设备: {jax.devices()})")
    except ImportError:
        print("[依赖安装] 正在安装 jax 与 optax...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "jax", "optax"])


def apply_jax_compatibility_patches(repo_dir: Path):
    """为新版 JAX (0.4.34+) 与运行环境自动注入兼容补丁."""
    log_header("应用 JAX 与环境版本自适应兼容补丁")

    # 1. 为 dreamerv3/main.py 注入 JAX 全局 Monkey Patch 与 ScopeOutput 容错
    main_file = repo_dir / "dreamerv3" / "main.py"
    if main_file.exists():
        content = main_file.read_text(encoding="utf-8")
        patch_marker = "# === JAX COMPATIBILITY MONKEY PATCH ==="
        if patch_marker not in content:
            patch_code = f"""{patch_marker}
try:
    import jax
    _orig_jax_jit = jax.jit
    def _compat_jax_jit(fun=None, *args, **kwargs):
        if not args:
            return _orig_jax_jit(fun, **kwargs)
        pos_names = ['in_shardings', 'out_shardings', 'static_argnums', 'static_argnames', 'donate_argnums']
        for val, name in zip(args, pos_names):
            if val is not None and name not in kwargs:
                if name != 'static_argnames':
                    kwargs[name] = val
        return _orig_jax_jit(fun, **kwargs)
    jax.jit = _compat_jax_jit
    print("[JAX 兼容层] 已激活新版 JAX 关键字参数自适应补丁")
except Exception as e:
    print(f"[JAX 兼容层警告] 补丁注入异常: {{e}}")
# =======================================
"""
            content = patch_code + "\n" + content
            print("[代码补丁] 成功为 dreamerv3/main.py 注入 JAX jit 全局兼容补丁！")

        main_file.write_text(content, encoding="utf-8")

    # 2. 源码级修复 embodied/jax/transform.py
    transform_file = repo_dir / "embodied" / "jax" / "transform.py"
    if transform_file.exists():
        t_content = transform_file.read_text(encoding="utf-8")
        replacements = [
            (
                "fn = jax.jit(fn, arg_shardings, params_sharding, static_argnums, None)",
                "fn = jax.jit(fn, in_shardings=arg_shardings, out_shardings=params_sharding, static_argnums=static_argnums)",
            ),
            (
                "fn = jax.jit(fn, in_shardings, out_shardings, static_argnums, None, donate)",
                "fn = jax.jit(fn, in_shardings=in_shardings, out_shardings=out_shardings, static_argnums=static_argnums, donate_argnums=donate)",
            ),
        ]
        modified = False
        for old, new in replacements:
            if old in t_content:
                t_content = t_content.replace(old, new)
                modified = True
        if modified:
            transform_file.write_text(t_content, encoding="utf-8")
            print("[代码补丁] 成功修复 embodied/jax/transform.py 位置传参！")

    # 3. 源码级修复 embodied/jax/internal.py
    internal_file = repo_dir / "embodied" / "jax" / "internal.py"
    if internal_file.exists():
        i_content = internal_file.read_text(encoding="utf-8")
        replacements = [
            (
                "gather_fn = jax.jit(lambda x: x, (original,), mirrored).lower(inspec)",
                "gather_fn = jax.jit(lambda x: x, in_shardings=(original,), out_shardings=mirrored).lower(inspec)",
            ),
            (
                "shard_fn = jax.jit(lambda x: x, (mirrored,), original).lower(inspec)",
                "shard_fn = jax.jit(lambda x: x, in_shardings=(mirrored,), out_shardings=original).lower(inspec)",
            ),
            (
                "'--xla_gpu_enable_triton_softmax_fusion=false',",
                "# '--xla_gpu_enable_triton_softmax_fusion=false',",
            ),
            (
                "'--xla_gpu_graph_level=0',",
                "# '--xla_gpu_graph_level=0',",
            ),
        ]
        modified = False
        for old, new in replacements:
            if old in i_content:
                i_content = i_content.replace(old, new)
                modified = True
        if modified:
            internal_file.write_text(i_content, encoding="utf-8")
            print("[代码补丁] 成功修复 embodied/jax/internal.py 位置传参！")


def summarize_results(logdir: Path):
    """提取训练指标并输出 Crafter 成绩单."""
    log_header("训练指标评估与成绩汇总")
    metrics_files = list(logdir.glob("**/metrics.jsonl"))
    if not metrics_files:
        print(f"[提示] 未在 {logdir} 找到 metrics.jsonl，请检查日志目录。")
        return

    latest_metrics_file = metrics_files[0]
    records = []
    with open(latest_metrics_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not records:
        print("[提示] 暂无有效指标记录。")
        return

    last_record = records[-1]
    step = last_record.get("step", "未知")
    score = last_record.get("episode/score", last_record.get("score", "N/A"))
    length = last_record.get("episode/length", last_record.get("length", "N/A"))

    print(f"📊 最终训练步数: {step}")
    print(f"🏆 最终平均得分: {score}")
    print(f"⏱️ 平均存活时长: {length} 步")

    # 提取 Crafter 成就达成情况
    achievements = {}
    for k, v in last_record.items():
        if "achievement" in k.lower():
            ach_name = k.split("/")[-1].replace("achievement_", "")
            achievements[ach_name] = v

    if achievements:
        print("\n🎯 Crafter 成就达成概览:")
        unlocked = 0
        for name, rate in sorted(achievements.items(), key=lambda x: -float(x[1])):
            rate_val = float(rate)
            status = "✅" if rate_val > 0.05 else "⬜"
            if rate_val > 0.05:
                unlocked += 1
            print(f"  {status} {name:<22}: {rate_val * 100:5.1f}%")
        print(f"\n🎉 累计解锁成就项: {unlocked} / {len(achievements)}")


def package_outputs(outdir: Path, zip_name: str = "crafter_dreamerv3_100k.zip"):
    """将输出日志与检查点打包成 zip."""
    log_header("打包模型检查点与日志")
    zip_path = outdir.parent / zip_name
    print(f"[打包] 正在将 {outdir} 压缩打包为 {zip_path}...")
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", str(outdir))
    
    # 确保 /content 根目录也有一份，方便下载
    root_zip = Path("/content") / zip_name
    if zip_path != root_zip:
        try:
            shutil.copyfile(zip_path, root_zip)
        except Exception:
            pass

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"[打包完成] 文件生成: {zip_path} ({size_mb:.2f} MB)")
    return zip_path


def main():
    default_steps = int(os.environ.get("DREAMER_STEPS", "100000"))
    default_outdir = os.environ.get("DREAMER_OUTDIR", "/content/output/crafter_dreamerv3_100k")
    default_repo_dir = os.environ.get("DREAMER_REPO_DIR", "/content/dreamerv3")
    default_size = os.environ.get("DREAMER_SIZE", "size12m")
    default_train_ratio = int(os.environ.get("DREAMER_TRAIN_RATIO", "512"))

    parser = argparse.ArgumentParser(description="Crafter DreamerV3 100k Training on Colab")
    parser.add_argument("--steps", type=int, default=default_steps, help="总训练步数 (默认: 100000)")
    parser.add_argument("--size", type=str, default=default_size, choices=["size1m", "size12m", "size50m", "none"], help="模型规模预设 (推荐: size12m)")
    parser.add_argument("--train-ratio", type=int, default=default_train_ratio, help="训练与环境采样比率 (默认: 512)")
    parser.add_argument("--outdir", type=str, default=default_outdir, help="训练输出保存路径")
    parser.add_argument("--repo-dir", type=str, default=default_repo_dir, help="DreamerV3 源码存放路径")
    parser.add_argument("--log-every", type=int, default=30, help="日志记录间隔(秒)")
    parser.add_argument("--save-every", type=int, default=300, help="模型保存间隔(秒)")
    args, unknown = parser.parse_known_args()

    outdir = Path(args.outdir)
    repo_dir = Path(args.repo_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 检查是否存在历史进度 (断点续训检测)
    current_step = 0
    metrics_file = outdir / "metrics.jsonl"
    if metrics_file.exists():
        try:
            with open(metrics_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        current_step = int(record.get("step", current_step))
        except Exception:
            pass

    if current_step > 0:
        print(f"\n[断点续训] 检测到已有历史检查点: {current_step:,} steps")
        if args.steps <= current_step:
            new_target = current_step + 100000
            print(f"[警告] 设定步数 ({args.steps:,}) <= 当前已完成步数 ({current_step:,})！")
            print(f"[自动递增] 目标总步数已自动调整为: {new_target:,} steps")
            args.steps = new_target
        print(f"[断点续训] 本次预计增量训练: {args.steps - current_step:,} 步 (至总步数 {args.steps:,})\n")

    log_header("Crafter DreamerV3 训练启动")
    print(f"目标总步数 (Steps):    {args.steps:,}")
    print(f"网络规模 (Model Size): {args.size}")
    print(f"训练比率 (Train Ratio):{args.train_ratio}")
    print(f"输出目录 (OutDir):     {outdir}")
    print(f"源码目录 (RepoDir):    {repo_dir}")

    # 1. 设置与检测 GPU
    check_and_setup_gpu()

    # 2. 准备官方代码仓库与依赖
    ensure_repository(repo_dir)
    ensure_dependencies(repo_dir)
    apply_jax_compatibility_patches(repo_dir)

    # 3. 构造 DreamerV3 启动命令
    # 官方配置链式语法: --configs crafter size12m
    configs = ["crafter"]
    if args.size != "none":
        configs.append(args.size)

    cmd = [
        sys.executable,
        str(repo_dir / "dreamerv3" / "main.py"),
        "--configs",
        *configs,
        "--task",
        "crafter_reward",
        "--logdir",
        str(outdir),
        "--run.steps",
        str(args.steps),
        "--run.train_ratio",
        str(args.train_ratio),
        "--run.log_every",
        str(args.log_every),
        "--run.save_every",
        str(args.save_every),
        "--jax.prealloc",
        "False",
    ]

    print(f"[执行命令] {' '.join(cmd)}\n")

    # 4. 执行训练进程
    start_time = time.time()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_dir) + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("XLA_FLAGS", None)

    process = subprocess.Popen(
        cmd,
        cwd=str(repo_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    try:
        for line in iter(process.stdout.readline, ""):
            print(line, end="", flush=True)
        process.stdout.close()
        return_code = process.wait()
    except KeyboardInterrupt:
        print("\n[中断] 接收到用户中断信号，正在终止训练进程...")
        process.terminate()
        return_code = process.wait()

    elapsed = time.time() - start_time
    print(f"\n[训练状态] 训练结束，耗时: {elapsed / 60:.2f} 分钟 (返回码: {return_code})")

    # 5. 分析指标与打包
    summarize_results(outdir)
    package_outputs(outdir)


if __name__ == "__main__":
    main()
