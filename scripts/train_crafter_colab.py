"""Crafter 100k Steps PPO Training Script for Google Colab / Remote GPU.

This script is self-contained:
1. Automatically verifies and installs dependencies (crafter, stable-baselines3, shimmy).
2. Verifies GPU/CUDA availability.
3. Sets up Crafter environment with Recorder.
4. Trains PPO for 100,000 steps using CnnPolicy.
5. Saves model weights and training statistics.
"""

import argparse
import os
import subprocess
import sys
import time

def ensure_dependencies():
    packages = ["crafter", "stable-baselines3", "shimmy"]
    for pkg in packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            print(f"[Setup] Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])

ensure_dependencies()

import torch
import shimmy
import crafter
import stable_baselines3
from stable_baselines3 import PPO


def main():
    default_steps = int(os.environ.get("CRAFTER_STEPS", "100000"))
    default_outdir = os.environ.get("CRAFTER_OUTDIR", "./output/crafter_ppo_100k")
    default_model = os.environ.get("CRAFTER_MODEL_NAME", "crafter_ppo_100k.zip")

    parser = argparse.ArgumentParser(description="Train Crafter with PPO on Colab")
    parser.add_argument("--steps", type=int, default=default_steps, help="Total training steps")
    parser.add_argument("--outdir", type=str, default=default_outdir, help="Output directory")
    parser.add_argument("--model-name", type=str, default=default_model, help="Model checkpoint filename")
    args, _ = parser.parse_known_args()

    os.makedirs(args.outdir, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("=" * 60)
    print(f"[Crafter Colab Runner] Training Started")
    print(f"Device: {device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU'})")
    print(f"Steps:  {args.steps:,}")
    print(f"Output: {args.outdir}")
    print("=" * 60)

    # 1. 创建 Crafter 环境与记录器并添加 Gymnasium 兼容层
    raw_env = crafter.Env()
    raw_env = crafter.Recorder(
        raw_env,
        args.outdir,
        save_stats=True,
        save_episode=False,
        save_video=False,
    )
    env = shimmy.GymV21CompatibilityV0(env=raw_env)

    # 2. 构建 PPO 智能体
    start_time = time.time()
    n_steps = min(2048, max(64, args.steps))
    batch_size = min(64, n_steps)
    model = PPO(
        policy="CnnPolicy",
        env=env,
        verbose=1,
        device=device,
        learning_rate=3e-4,
        n_steps=n_steps,
        batch_size=batch_size,
        n_epochs=10,
    )

    # 3. 开始训练
    print(f"[Training] Learning for {args.steps:,} timesteps...")
    model.learn(total_timesteps=args.steps)
    elapsed = time.time() - start_time
    print(f"[Training] Finished in {elapsed / 60:.2f} minutes.")

    # 4. 保存模型与统计
    model_path = os.path.join(args.outdir, args.model_name)
    model.save(model_path)
    print(f"[Output] Model saved successfully to: {model_path}")
    print(f"[Output] Stats saved to: {args.outdir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
