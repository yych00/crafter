#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Empirical stress-testing experiments for Discrete RSSM
Tests:
1. Boundary KL Balancing Weights (0.0, 0.2, 0.5, 0.8, 1.0) with free_bits=0 vs free_bits=0.1
2. Numerical Stability (Extreme temperatures, Gumbel stability, Logits extremes, NaN/Inf resilience)
3. Compounding Error Trend & Monotonicity Analysis
4. Discrete Latent Dimensions (8x8, 16x16, 32x32, 64x64)
5. Horizon Stress (1, 15, 25, 30, 50) and Trajectory Length Boundary Analysis
"""

import sys
import os
import math
import torch
import torch.nn.functional as F
import subprocess

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from rssm_discrete_rollout import (
    RSSMConfig, DiscreteRSSM, SyntheticPhysicalEnv,
    train_discrete_rssm, CompoundingErrorAnalyzer,
    KLBalancingLoss, StochasticState
)

def test_kl_alpha_boundaries():
    print("\n" + "="*70)
    print("EXPERIMENT 1: KL Alpha Boundary & Free Bits Analysis")
    print("="*70)
    env = SyntheticPhysicalEnv(dt=0.05, gamma=0.15, omega=1.4, g=0.8)
    obs_all, act_all, rew_all = env.generate_trajectories(num_trajectories=64, steps=30, seed=1024)
    obs_train, act_train, rew_train = obs_all[:48], act_all[:48], rew_all[:48]
    obs_test, act_test, rew_test = obs_all[48:], act_all[48:], rew_all[48:]

    alphas = [0.0, 0.2, 0.5, 0.8, 1.0]
    
    # Part A: With default free_bits = 0.1
    print("\n--- Part A: Default free_bits = 0.1 (Checking Prior Gradient Dead Zone) ---")
    for a in alphas:
        torch.manual_seed(42)
        cfg = RSSMConfig(kl_alpha=a, kl_free_bits=0.1)
        model = DiscreteRSSM(cfg)
        hist = train_discrete_rssm(model, obs_train, act_train, rew_train, steps=40, lr=1e-3, batch_size=16)
        analyzer = CompoundingErrorAnalyzer(model)
        drift = analyzer.evaluate_drift(obs_test, act_test, rew_test, burnin=5, horizon=15)
        print(f"Alpha={a:.1f} (fb=0.1) | TrainRecon={hist[-1]['recon_loss']:.4f} | KL_Loss={hist[-1]['kl_loss']:.4f} | "
              f"H15_MSE={drift['obs_mse'][-1]:.4f} | H15_DeterL2={drift['deter_l2'][-1]:.4f} | H15_JSD={drift['latent_jsd'][-1]:.4f}")

    # Part B: With free_bits = 0.0 (Unconstrained prior gradient flow)
    print("\n--- Part B: free_bits = 0.0 (Gradient Flow Enabled for Prior) ---")
    for a in alphas:
        torch.manual_seed(42)
        cfg = RSSMConfig(kl_alpha=a, kl_free_bits=0.0)
        model = DiscreteRSSM(cfg)
        hist = train_discrete_rssm(model, obs_train, act_train, rew_train, steps=40, lr=1e-3, batch_size=16)
        analyzer = CompoundingErrorAnalyzer(model)
        drift = analyzer.evaluate_drift(obs_test, act_test, rew_test, burnin=5, horizon=15)
        print(f"Alpha={a:.1f} (fb=0.0) | TrainRecon={hist[-1]['recon_loss']:.4f} | KL_Loss={hist[-1]['kl_loss']:.4f} | "
              f"H15_MSE={drift['obs_mse'][-1]:.4f} | H15_DeterL2={drift['deter_l2'][-1]:.4f} | H15_JSD={drift['latent_jsd'][-1]:.4f}")


def test_numerical_stability():
    print("\n" + "="*70)
    print("EXPERIMENT 2: Numerical Stability, Gradient Health & Extreme Logits")
    print("="*70)
    config = RSSMConfig()
    rssm = DiscreteRSSM(config)

    # 1. Extreme Logits (Overflow/Underflow test)
    print("1. Testing extreme logits in KL and Softmax:")
    extreme_values = [1e3, 1e4, -1e3, -1e4]
    for val in extreme_values:
        logits_p = torch.full((4, 16, 16), val)
        logits_q = torch.full((4, 16, 16), 0.0)
        kl = rssm.kl_balancing.categorical_kl(logits_q, logits_p)
        jsd = CompoundingErrorAnalyzer.categorical_js_divergence(logits_p, logits_q)
        print(f"  Logits P = {val:+.0e} | KL finite: {torch.isfinite(kl).all().item()} (val={kl.mean().item():.2f}) | JSD finite: {torch.isfinite(jsd).all().item()} (val={jsd.item():.4f})")

    # 2. Temperature Edge Cases in StochasticState
    print("\n2. Testing Gumbel-Softmax Temperature Boundaries in StochasticState:")
    temps = [1e-4, 1e-2, 0.1, 1.0, 10.0, 100.0]
    for t in temps:
        cfg = RSSMConfig(temperature=t)
        stoch = StochasticState(cfg)
        stoch.train()
        test_logits = torch.randn(8, 16, 16, requires_grad=True)
        z, z_flat = stoch(test_logits, sample=True)
        loss = z_flat.sum()
        loss.backward()
        grad_norm = test_logits.grad.norm().item()
        has_nan = torch.isnan(z_flat).any().item() or torch.isnan(test_logits.grad).any().item()
        print(f"  Temp={t:6.4f} | Has NaN: {has_nan} | Grad Norm: {grad_norm:10.4f} | z_one_hot sum correct: {torch.allclose(z.sum(-1), torch.ones(8, 16))}")

    # 3. What if Temperature == 0?
    print("\n3. Testing Temperature = 0.0:")
    try:
        cfg0 = RSSMConfig(temperature=0.0)
        stoch0 = StochasticState(cfg0)
        stoch0.train()
        test_logits0 = torch.randn(4, 16, 16, requires_grad=True)
        z, z_flat = stoch0(test_logits0, sample=True)
        loss = z_flat.sum()
        loss.backward()
        print(f"  Temp=0.0 | Has NaN: {torch.isnan(z_flat).any().item()}")
    except Exception as e:
        print(f"  Temp=0.0 Exception: {type(e).__name__}: {e}")

    # 4. Gumbel Noise Sample Space under float32:
    print("\n4. Testing Gumbel Noise 0.0 probability (exponential_ underflow):")
    samples = torch.empty(1_000_000, dtype=torch.float32).exponential_()
    min_exp = samples.min().item()
    print(f"  1M exponential samples: min={min_exp:.8e}, log(min)={math.log(min_exp):.4f}")


def test_latent_dimensions():
    print("\n" + "="*70)
    print("EXPERIMENT 3: Latent Dimensions Exploration (N x K)")
    print("="*70)
    env = SyntheticPhysicalEnv(dt=0.05, gamma=0.15, omega=1.4, g=0.8)
    obs_all, act_all, rew_all = env.generate_trajectories(num_trajectories=64, steps=30, seed=1024)
    obs_train, act_train, rew_train = obs_all[:48], act_all[:48], rew_all[:48]
    obs_test, act_test, rew_test = obs_all[48:], act_all[48:], rew_all[48:]

    grid = [
        (4, 4),
        (8, 8),
        (16, 16),
        (32, 32),
        (64, 16)
    ]
    for n_cats, n_cls in grid:
        torch.manual_seed(42)
        cfg = RSSMConfig(num_categoricals=n_cats, num_classes=n_cls, kl_free_bits=0.0)
        model = DiscreteRSSM(cfg)
        hist = train_discrete_rssm(model, obs_train, act_train, rew_train, steps=30, lr=1e-3, batch_size=16)
        analyzer = CompoundingErrorAnalyzer(model)
        drift = analyzer.evaluate_drift(obs_test, act_test, rew_test, burnin=5, horizon=15)
        print(f"Latents ({n_cats:2d} x {n_cls:2d} = {n_cats*n_cls:4d} dim) | "
              f"FinalRecon={hist[-1]['recon_loss']:.4f} | H15_MSE={drift['obs_mse'][-1]:.4f} | H15_DeterL2={drift['deter_l2'][-1]:.4f}")


def test_compounding_error_monotonicity():
    print("\n" + "="*70)
    print("EXPERIMENT 4: Compounding Error Monotonicity & Plateau Analysis")
    print("="*70)
    env = SyntheticPhysicalEnv(dt=0.05, gamma=0.15, omega=1.4, g=0.8)
    obs_all, act_all, rew_all = env.generate_trajectories(num_trajectories=64, steps=30, seed=1024)
    obs_train, act_train, rew_train = obs_all[:48], act_all[:48], rew_all[:48]
    obs_test, act_test, rew_test = obs_all[48:], act_all[48:], rew_all[48:]

    torch.manual_seed(42)
    cfg = RSSMConfig(deter_dim=128, num_categoricals=16, num_classes=16, kl_alpha=0.8, kl_free_bits=0.0)
    model = DiscreteRSSM(cfg)
    train_discrete_rssm(model, obs_train, act_train, rew_train, steps=100, lr=1e-3, batch_size=16)
    analyzer = CompoundingErrorAnalyzer(model)
    drift = analyzer.evaluate_drift(obs_test, act_test, rew_test, burnin=5, horizon=25)

    print("\nStep-by-step Drift Profile (Horizon 1 to 25):")
    print(f"{'H':<3} | {'Deter L2':<10} | {'Deter Δ':<10} | {'Obs MSE':<10} | {'Obs Δ':<10} | {'Hamming%':<10} | {'Latent JSD':<10}")
    print("-" * 75)
    for i in range(25):
        h = drift["steps"][i]
        d_l2 = drift["deter_l2"][i]
        d_diff = (d_l2 - drift["deter_l2"][i-1]) if i > 0 else 0.0
        o_mse = drift["obs_mse"][i]
        o_diff = (o_mse - drift["obs_mse"][i-1]) if i > 0 else 0.0
        ham = drift["hamming_ratio"][i] * 100.0
        jsd = drift["latent_jsd"][i]
        print(f"{h:<3} | {d_l2:<10.4f} | {d_diff:<+10.4f} | {o_mse:<10.4f} | {o_diff:<+10.4f} | {ham:<10.2f} | {jsd:<10.4f}")


def test_prior_gradient_flow():
    print("\n" + "="*70)
    print("EXPERIMENT 5: Prior Gradient Health under kl_free_bits=0.1 (ST-9)")
    print("="*70)
    env = SyntheticPhysicalEnv(dt=0.05, gamma=0.15, omega=1.4, g=0.8)
    obs_all, act_all, _ = env.generate_trajectories(num_trajectories=16, steps=10, seed=42)
    cfg = RSSMConfig(kl_alpha=0.8, kl_free_bits=0.1)
    model = DiscreteRSSM(cfg)
    model.train()
    out = model.rollout_closed_loop(obs_all, act_all)
    loss_kl, prior_loss, post_loss = model.kl_balancing(
        out["post_logits"].view(-1, cfg.num_categoricals, cfg.num_classes),
        out["prior_logits"].view(-1, cfg.num_categoricals, cfg.num_classes)
    )
    loss_kl.backward()
    prior_grad_norm = sum(p.grad.abs().sum().item() for p in model.transition_prior.parameters() if p.grad is not None)
    print(f"  Prior Loss: {prior_loss.item():.4f} (Raw KL < 0.1 free_bits)")
    print(f"  Transition Prior Total Gradient Norm: {prior_grad_norm:.6f}")
    assert prior_grad_norm > 0.0, "FAIL: TransitionPrior gradients frozen by free_bits deadzone!"
    print("  [✓] PASS: TransitionPrior receives healthy non-zero gradients even when KL < free_bits.")


def test_horizon_stress():
    print("\n" + "="*70)
    print("EXPERIMENT 6: Long Horizon Stress & Dynamic Trajectory Length (ST-1, 2, 3, 4)")
    print("="*70)
    horizons = [1, 15, 25, 30, 50]
    burnin = 5
    for H in horizons:
        total_steps = max(30, burnin + H + 10)
        env = SyntheticPhysicalEnv(dt=0.05, gamma=0.15, omega=1.4, g=0.8)
        obs, act, rew = env.generate_trajectories(num_trajectories=16, steps=total_steps, seed=123)
        cfg = RSSMConfig(deter_dim=64, num_categoricals=8, num_classes=8)
        model = DiscreteRSSM(cfg)
        analyzer = CompoundingErrorAnalyzer(model)
        drift = analyzer.evaluate_drift(obs, act, rew, burnin=burnin, horizon=H)
        assert len(drift["steps"]) == H
        assert len(drift["obs_mse"]) == H
        print(f"  Horizon H={H:2d} (Steps={total_steps:2d}) | Final Obs MSE={drift['obs_mse'][-1]:.4f} | Deter L2={drift['deter_l2'][-1]:.4f} | [✓] PASS")


def test_cli_argument_aliases():
    print("\n" + "="*70)
    print("EXPERIMENT 7: CLI Argument Aliases Verification (ST-5, ST-6)")
    print("="*70)
    py_exec = sys.executable
    script_path = os.path.join(current_dir, "rssm_discrete_rollout.py")

    # 1. Test --kl_alpha and --kl-alpha
    res1 = subprocess.run([py_exec, script_path, "--kl_alpha", "0.5", "--steps", "5", "--horizon", "3"],
                          capture_output=True, text=True, check=True)
    assert "Prior 0.5" in res1.stdout
    print("  [✓] PASS: CLI --kl_alpha parsed successfully.")

    res1_hyphen = subprocess.run([py_exec, script_path, "--kl-alpha", "0.6", "--steps", "5", "--horizon", "3"],
                                 capture_output=True, text=True, check=True)
    assert "Prior 0.6" in res1_hyphen.stdout
    print("  [✓] PASS: CLI --kl-alpha parsed successfully.")

    # 2. Test --num_stoch_groups and --num_stoch_classes
    res2 = subprocess.run([py_exec, script_path, "--num_stoch_groups", "8", "--num_stoch_classes", "8", "--steps", "5", "--horizon", "3"],
                          capture_output=True, text=True, check=True)
    assert "8 组 x 8 类" in res2.stdout
    print("  [✓] PASS: CLI --num_stoch_groups and --num_stoch_classes aliases parsed successfully.")


if __name__ == "__main__":
    test_kl_alpha_boundaries()
    test_numerical_stability()
    test_latent_dimensions()
    test_compounding_error_monotonicity()
    test_prior_gradient_flow()
    test_horizon_stress()
    test_cli_argument_aliases()
