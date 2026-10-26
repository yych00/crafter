"""Crafter DreamerV3 本地启动云端训练驱动脚本 (Local-to-Colab Orchestrator).

本脚本在本地计算机运行，通过本地 WSL 2 内置的 Colab CLI 全自动调用 Google Colab 云端 GPU 算力:
1. 在本地一键执行: python colab/run_on_colab.py
2. 自动拉起远端 GPU 算力实例 (默认 T4)
3. 远程自动部署环境并启动 Crafter DreamerV3 100k 训练
4. 实时在本地终端流式输出训练日志与进度
5. 训练结束自动将权重和指标下载到本地 output 目录
6. 自动关机释放实例，杜绝算力扣费泄露
"""

import argparse
import atexit
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 全局记录当前激活的 session，确保退出时清理
ACTIVE_SESSION = None


def log_step(step: str, title: str):
    print("\n" + "=" * 60)
    print(f" [{step}] {title}")
    print("=" * 60)


def run_command(cmd_list, check=True, capture_output=False, text=True):
    """跨平台执行命令 (Windows 下自动通过 WSL 路由到 Colab CLI)."""
    return subprocess.run(
        cmd_list,
        check=check,
        capture_output=capture_output,
        text=text,
        encoding="utf-8",
        errors="replace",
    )


def build_colab_cmd(sub_args: list) -> list:
    """构建调用 colab cli 的系统命令."""
    is_windows = platform.system() == "Windows"
    colab_bin = "~/.local/bin/colab"

    if is_windows:
        # 在 Windows 环境下通过 WSL 执行
        escaped_args = " ".join([f'"{a}"' if " " in a else a for a in sub_args])
        full_bash = f"{colab_bin} {escaped_args}"
        return ["wsl", "bash", "-c", full_bash]
    else:
        # 原生 Linux / WSL 内部执行
        real_bin = shutil.which("colab") or os.path.expanduser("~/.local/bin/colab")
        return [real_bin] + sub_args


def check_colab_cli():
    """检查本地 Colab CLI 工具链状态."""
    try:
        res = run_command(build_colab_cmd(["version"]), capture_output=True)
        if res.returncode == 0:
            version_str = res.stdout.strip()
            print(f"[环境检查] Colab CLI 状态正常: {version_str}")
            return True
    except Exception as e:
        print(f"[环境异常] 未能调用 Colab CLI: {e}")

    print("\n[错误] 本地未找到可用的 colab 命令！")
    print("请在 WSL 2 终端中运行以下命令安装:")
    print("  curl -LsSf https://astral.sh/uv/install.sh | sh")
    print("  ~/.local/bin/uv tool install google-colab-cli")
    print("并运行 'colab login' 完成授权。")
    return False


def stop_session(session_name: str = None):
    """安全释放销毁 Colab 实例."""
    global ACTIVE_SESSION
    target = session_name or ACTIVE_SESSION
    if not target:
        return

    print(f"\n[资源清理] 正在释放销毁 Colab 云端实例: {target}...")
    try:
        stop_cmd = ["stop"]
        if target != "default":
            stop_cmd.extend(["-s", target])
        run_command(build_colab_cmd(stop_cmd), check=False)
        print("[资源清理] 实例已安全释放销毁，算力计费已停止。")
    except Exception as e:
        print(f"[警告] 释放实例时发生异常: {e}")
    finally:
        ACTIVE_SESSION = None


def main():
    global ACTIVE_SESSION

    parser = argparse.ArgumentParser(
        description="Crafter DreamerV3: 本地一键调用 Google Colab 云端训练"
    )
    parser.add_argument("--steps", type=int, default=100000, help="训练交互步数 (默认: 100000)")
    parser.add_argument("--gpu", type=str, default="T4", help="云端 GPU 型号 (T4 / A100 / L4)")
    parser.add_argument("--size", type=str, default="size12m", help="模型规格 (size1m / size12m / size50m)")
    parser.add_argument("--train-ratio", type=int, default=512, help="训练复用比率 (默认: 512)")
    parser.add_argument(
        "--local-out",
        type=str,
        default="e:/code/Crafter/output/crafter_dreamerv3_100k",
        help="训练成果保存的本地目录",
    )
    args = parser.parse_known_args()[0]

    log_step("1/5", "检查本地与云端连接环境")
    if not check_colab_cli():
        sys.exit(1)

    local_out_dir = Path(args.local_out).resolve()
    local_out_dir.mkdir(parents=True, exist_ok=True)

    session_id = f"dreamer-crafter-{int(time.time())}"
    ACTIVE_SESSION = session_id
    atexit.register(stop_session)

    try:
        # 1. 申请云端 GPU 实例
        log_step("2/5", f"申请 Google Colab {args.gpu} GPU 算力实例")
        print(f"创建临时会话: {session_id} (GPU: {args.gpu})...")
        new_res = run_command(
            build_colab_cmd(["new", "--gpu", args.gpu, "-s", session_id]),
            check=True,
        )
        if new_res.returncode != 0:
            raise RuntimeError("创建云端会话失败，请确认是否已执行 colab login 登录。")
        print("[云端状态] GPU 实例申请成功并就绪！")

        # 2. 部署依赖环境
        log_step("3/5", "在云端自动部署 DreamerV3 源码与 Crafter 依赖")
        install_pkgs = [
            "crafter",
            "elements",
            "portal",
            "ninjax",
            "optax",
            "chex",
            "einops",
            "ruamel.yaml",
            "scope",
            "matplotlib",
            "pandas",
        ]
        print(f"[远端配置] 执行依赖安装: {' '.join(install_pkgs)}...")
        run_command(build_colab_cmd(["install", "-s", session_id] + install_pkgs), check=True)
        time.sleep(5)

        # 3. 运行远程训练
        log_step("4/5", f"启动云端训练任务 (目标 {args.steps:,} 步, 规格 {args.size})")
        worker_script_local = Path(__file__).parent / "train_dreamerv3.py"
        wsl_script_path = f"/mnt/{worker_script_local.drive[0].lower()}/{worker_script_local.as_posix()[3:]}"

        exec_full_cmd = build_colab_cmd([
            "exec",
            "-s", session_id,
            "-f", wsl_script_path,
            "--env", f"DREAMER_STEPS={args.steps}",
            "--env", f"DREAMER_SIZE={args.size}",
            "--env", f"DREAMER_TRAIN_RATIO={args.train_ratio}",
            "--timeout", "14400",
        ])
        print(f"[远端启动] 调用脚本: {wsl_script_path}")
        print("[日志流] 下方为云端训练的实时流式输出:\n" + "-" * 60)
        proc = subprocess.Popen(
            exec_full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        for line in iter(proc.stdout.readline, ""):
            print(line, end="", flush=True)
        proc.stdout.close()
        code = proc.wait()

        if code != 0:
            raise RuntimeError(f"云端训练异常终止，退出码: {code}")

        # 4. 下载训练产物到本地
        log_step("5/5", "自动同步远端训练成果至本地工作区")
        remote_zip = "/content/crafter_dreamerv3_100k.zip"
        remote_metrics = "/content/output/crafter_dreamerv3_100k/metrics.jsonl"
        local_zip = local_out_dir / "crafter_dreamerv3_100k.zip"
        local_metrics = local_out_dir / "metrics.jsonl"

        wsl_local_zip = f"/mnt/{local_zip.drive[0].lower()}/{local_zip.as_posix()[3:]}"
        wsl_local_metrics = f"/mnt/{local_metrics.drive[0].lower()}/{local_metrics.as_posix()[3:]}"

        print(f"[下载同步] 正在下载权重压缩包至: {local_zip}...")
        run_command(build_colab_cmd(["download", "-s", session_id, remote_zip, wsl_local_zip]), check=False)

        print(f"[下载同步] 正在下载评估日志至: {local_metrics}...")
        run_command(build_colab_cmd(["download", "-s", session_id, remote_metrics, wsl_local_metrics]), check=False)

        print("\n" + "=" * 60)
        print(" [SUCCESS] 训练全部完成！成果已安全存储于本地:")
        print(f" 目录路径: {local_out_dir}")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n[中断] 用户手动中断进程 (Ctrl+C)。")
    except Exception as e:
        print(f"\n\n[错误] 任务执行失败: {e}")
    finally:
        # 释放云端实例
        stop_session(session_id)


if __name__ == "__main__":
    main()
