"""Crafter 训练指标解析与评估报告脚本 (零外部依赖兼容设计).

读取 output/crafter_dreamerv3_100k/metrics.jsonl 并输出:
1. 终端训练指标看板 (步数、平均得分、存活步长、成就达成情况)
2. (可选) Matplotlib 曲线图
"""

import json
from pathlib import Path


def analyze(logdir: Path = Path("e:/code/Crafter/output/crafter_dreamerv3_100k")):
    metrics_file = logdir / "metrics.jsonl"
    if not metrics_file.exists():
        print(f"[错误] 未在 {logdir} 找到 metrics.jsonl 日志文件！")
        return

    records = []
    with open(metrics_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue

    if not records:
        print("[警告] metrics.jsonl 中未发现有效数据行。")
        return

    print("\n" + "=" * 65)
    print(" 🎮 Crafter DreamerV3 训练成果分析报告")
    print("=" * 65)
    print(f"有效评估记录:       {len(records)} 条")
    last_row = records[-1]
    last_step = int(last_row.get("step", 0))
    score = last_row.get("episode/score", last_row.get("score", 0.0))
    length = last_row.get("episode/length", last_row.get("length", 0.0))

    print(f"最新训练步数:       {last_step:,} steps")
    print(f"最终平均得分:       {score:.2f}")
    print(f"平均存活时长:       {length:.1f} steps")

    print("\n📊 历史步数与得分变化追踪:")
    print(f"  {'Step':<10} | {'Score':<10} | {'Survival Length':<15}")
    print("  " + "-" * 42)
    for r in records:
        step_val = r.get("step", 0)
        s_val = r.get("episode/score", r.get("score", 0.0))
        l_val = r.get("episode/length", r.get("length", 0.0))
        print(f"  {step_val:<10} | {s_val:<10.2f} | {l_val:<15.1f}")

    # 提取成就达成率
    achievements = {}
    for k, v in last_row.items():
        if "achievement" in k.lower():
            ach_name = k.split("/")[-1].replace("achievement_", "")
            achievements[ach_name] = float(v)

    if achievements:
        print("\n🏆 Crafter 22 项生存成就达成概况:")
        unlocked_count = 0
        for name, prob in sorted(achievements.items(), key=lambda x: -x[1]):
            status = "✅" if prob > 0.05 else "⬜"
            if prob > 0.05:
                unlocked_count += 1
            print(f"  {status} {name:<22}: {prob * 100:5.1f}%")
        print(f"\n🎉 累计解锁关键成就项: {unlocked_count} / {len(achievements)}")

    # 尝试绘制图表
    try:
        import matplotlib.pyplot as plt

        steps = [r.get("step", 0) for r in records]
        scores = [r.get("episode/score", r.get("score", 0.0)) for r in records]
        lengths = [r.get("episode/length", r.get("length", 0.0)) for r in records]

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        axes[0].plot(steps, scores, color="#2563EB", marker="o", linewidth=2, label="Score")
        axes[0].set_title("Crafter Score Progress", fontsize=13, fontweight="bold")
        axes[0].set_xlabel("Environment Steps")
        axes[0].set_ylabel("Score")
        axes[0].grid(True, linestyle="--", alpha=0.5)
        axes[0].legend()

        axes[1].plot(steps, lengths, color="#10B981", marker="s", linewidth=2, label="Length")
        axes[1].set_title("Survival Episode Length", fontsize=13, fontweight="bold")
        axes[1].set_xlabel("Environment Steps")
        axes[1].set_ylabel("Steps")
        axes[1].grid(True, linestyle="--", alpha=0.5)
        axes[1].legend()

        plt.tight_layout()
        out_plot = logdir / "evaluation_plot.png"
        plt.savefig(out_plot, dpi=200)
        print(f"\n📈 评估分析可视化图表已生成: {out_plot}")
    except ImportError:
        pass

    print("=" * 65 + "\n")


if __name__ == "__main__":
    analyze()
