"""
RSSM Deep Ablation Experiment Suite
===================================
Executes three comprehensive ablation experiments:
1. Discrete Categorical RSSM (DreamerV2/V3 32x32 STE) vs Continuous Gaussian RSSM (PlaNet/DreamerV1)
   under hybrid non-linear jumpy physics dynamics.
2. KL Dynamic Balancing (alpha = 0.2, 0.5, 0.8): Mathematical mechanism of 'Prior Chasing Posterior'
   vs Posterior Collapse.
3. Symlog Transformation vs Traditional Linear vs Clipping Normalization under multi-scale rewards (10^-2 ~ 10^4).

Outputs:
- ablation_metrics.json
- discrete_vs_continuous_rssm.png
- kl_balance_ablation.png
- symlog_gradient_stability.png
"""

import os
import sys
import json
import time
import math
import numpy as np
import matplotlib.pyplot as plt

# Import RSSM dynamics engine
from rssm_dynamics_engine import (
    HybridNonlinearPhysicsEnv,
    ContinuousGaussianRSSM,
    DiscreteCategoricalRSSM,
    symlog,
    symexp,
    d_symlog,
    DenseLayer
)

# Set high-DPI publication styling
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
plt.rcParams['axes.edgecolor'] = '#333333'
plt.rcParams['axes.linewidth'] = 1.0
plt.rcParams['grid.color'] = '#e0e0e0'
plt.rcParams['grid.linestyle'] = '--'
plt.rcParams['grid.alpha'] = 0.7

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Helper: Evaluate Multi-Step Open-Loop Compounding Error
# ---------------------------------------------------------------------------

def evaluate_horizon_compounding_error(model, test_trajectories, max_horizon=30, warmup=5):
    """
    Evaluates compounding error:
    Warm-up model for 'warmup' steps with ground-truth observations,
    then rollout purely open-loop in latent space without observation feedback.
    Returns per-horizon average MSE.
    """
    horizon_mses = np.zeros(max_horizon)
    num_evals = len(test_trajectories)
    
    for obs_seq, act_seq, rew_seq, reg_seq in test_trajectories:
        T = min(len(act_seq), warmup + max_horizon)
        if T <= warmup:
            continue
            
        # 1. Warm-up closed-loop filtering
        h, z = model.init_state()
        for t in range(warmup):
            h, z, _ = model.observe_step(h, z, act_seq[t], obs_seq[t+1])
            
        # 2. Open-loop imagination rollout
        h_open, z_open = np.copy(h), np.copy(z)
        for step in range(max_horizon):
            t_idx = warmup + step
            if t_idx >= len(act_seq):
                break
            act = act_seq[t_idx]
            target_obs = obs_seq[t_idx + 1]
            h_open, z_open, pred_obs = model.imagine_step(h_open, z_open, act)
            mse = float(np.mean((pred_obs - target_obs) ** 2))
            horizon_mses[step] += mse
            
    horizon_mses /= num_evals
    return horizon_mses

# ---------------------------------------------------------------------------
# Experiment 1: Discrete Categorical vs Continuous Gaussian RSSM
# ---------------------------------------------------------------------------

def run_experiment_discrete_vs_continuous(num_episodes=70, horizon=35, seed=101):
    print("\n" + "=" * 75)
    print(">>> [Experiment 1/3] Discrete Categorical RSSM vs Continuous Gaussian RSSM")
    print("=" * 75)
    
    env = HybridNonlinearPhysicsEnv(seed=seed)
    
    # Generate fixed evaluation trajectories
    eval_trajectories = [env.rollout_trajectory(horizon=horizon) for _ in range(15)]
    
    # Instantiate models
    model_cont = ContinuousGaussianRSSM(obs_dim=16, action_dim=2, deter_dim=128, stoch_dim=32, seed=seed+1)
    model_disc = DiscreteCategoricalRSSM(obs_dim=16, action_dim=2, deter_dim=128, num_vars=32, num_classes=32, seed=seed+2)
    
    # Tracking metrics
    metrics = {
        "continuous": {
            "train_recon_mse": [],
            "train_kl": [],
            "train_entropy": [],
            "regime_recon_mse": {0: [], 1: [], 2: [], 3: []},
            "compounding_error": []
        },
        "discrete": {
            "train_recon_mse": [],
            "train_kl": [],
            "train_entropy": [],
            "regime_recon_mse": {0: [], 1: [], 2: [], 3: []},
            "compounding_error": []
        }
    }
    
    print(f"[*] Training both RSSMs on identical jumpy non-linear physics trajectories ({num_episodes} episodes)...")
    
    for ep in range(num_episodes):
        obs_seq, act_seq, rew_seq, reg_seq = env.rollout_trajectory(horizon=horizon)
        
        # 1. Train Continuous RSSM
        h_c, z_c = model_cont.init_state()
        ep_recon_c = []
        ep_kl_c = []
        ep_ent_c = []
        regime_errs_c = {0: [], 1: [], 2: [], 3: []}
        
        for t in range(len(act_seq)):
            h_c, z_c, sdata_c = model_cont.observe_step(h_c, z_c, act_seq[t], obs_seq[t+1])
            model_cont.train_step_sgd(sdata_c, obs_seq[t+1], kl_balance_alpha=0.8, lr=0.002)
            ep_recon_c.append(sdata_c['recon_loss'])
            ep_kl_c.append(sdata_c['kl'])
            ep_ent_c.append(sdata_c['entropy'])
            reg = reg_seq[t]
            regime_errs_c[reg].append(sdata_c['recon_loss'])
            
        metrics["continuous"]["train_recon_mse"].append(float(np.mean(ep_recon_c)))
        metrics["continuous"]["train_kl"].append(float(np.mean(ep_kl_c)))
        metrics["continuous"]["train_entropy"].append(float(np.mean(ep_ent_c)))
        for reg in range(4):
            val = float(np.mean(regime_errs_c[reg])) if len(regime_errs_c[reg]) > 0 else 0.0
            metrics["continuous"]["regime_recon_mse"][reg].append(val)
            
        # 2. Train Discrete Categorical RSSM
        h_d, z_d = model_disc.init_state()
        ep_recon_d = []
        ep_kl_d = []
        ep_ent_d = []
        regime_errs_d = {0: [], 1: [], 2: [], 3: []}
        
        for t in range(len(act_seq)):
            h_d, z_d, sdata_d = model_disc.observe_step(h_d, z_d, act_seq[t], obs_seq[t+1])
            model_disc.train_step_sgd(sdata_d, obs_seq[t+1], kl_balance_alpha=0.8, lr=0.002)
            ep_recon_d.append(sdata_d['recon_loss'])
            ep_kl_d.append(sdata_d['kl'])
            ep_ent_d.append(sdata_d['entropy'])
            reg = reg_seq[t]
            regime_errs_d[reg].append(sdata_d['recon_loss'])
            
        metrics["discrete"]["train_recon_mse"].append(float(np.mean(ep_recon_d)))
        metrics["discrete"]["train_kl"].append(float(np.mean(ep_kl_d)))
        metrics["discrete"]["train_entropy"].append(float(np.mean(ep_ent_d)))
        for reg in range(4):
            val = float(np.mean(regime_errs_d[reg])) if len(regime_errs_d[reg]) > 0 else 0.0
            metrics["discrete"]["regime_recon_mse"][reg].append(val)
            
        if (ep + 1) % 15 == 0 or ep == num_episodes - 1:
            print(f"    Episode {ep+1:02d}/{num_episodes:02d} | "
                  f"Cont Recon MSE: {metrics['continuous']['train_recon_mse'][-1]:.5f} | "
                  f"Disc Recon MSE: {metrics['discrete']['train_recon_mse'][-1]:.5f} | "
                  f"Cont KL: {metrics['continuous']['train_kl'][-1]:.3f} | "
                  f"Disc KL: {metrics['discrete']['train_kl'][-1]:.3f}")

    # Evaluate compounding error on test trajectories
    print("[*] Evaluating Open-Loop Imagination Compounding Error across planning horizons...")
    metrics["continuous"]["compounding_error"] = evaluate_horizon_compounding_error(
        model_cont, eval_trajectories, max_horizon=28, warmup=5
    ).tolist()
    metrics["discrete"]["compounding_error"] = evaluate_horizon_compounding_error(
        model_disc, eval_trajectories, max_horizon=28, warmup=5
    ).tolist()
    
    # Generate visualization plot
    plot_discrete_vs_continuous(metrics)
    return metrics

def plot_discrete_vs_continuous(metrics):
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    episodes = np.arange(1, len(metrics["continuous"]["train_recon_mse"]) + 1)
    
    # Subplot 1: Reconstruction MSE over training
    axs[0, 0].plot(episodes, metrics["continuous"]["train_recon_mse"], color='#e74c3c', label='Continuous Gaussian RSSM (DreamerV1)', lw=2.2)
    axs[0, 0].plot(episodes, metrics["discrete"]["train_recon_mse"], color='#2980b9', label='Discrete Categorical RSSM (32x32 STE)', lw=2.5)
    axs[0, 0].set_title("(a) Closed-Loop Observation Reconstruction MSE", fontsize=12, fontweight='bold')
    axs[0, 0].set_xlabel("Training Episodes", fontsize=10)
    axs[0, 0].set_ylabel("Reconstruction MSE", fontsize=10)
    axs[0, 0].set_yscale('log')
    axs[0, 0].grid(True)
    axs[0, 0].legend(loc='upper right', frameon=True)
    
    # Subplot 2: Compounding Error drift vs Planning Horizon
    horizons = np.arange(1, len(metrics["continuous"]["compounding_error"]) + 1)
    axs[0, 1].plot(horizons, metrics["continuous"]["compounding_error"], 'o-', color='#e74c3c', label='Continuous Gaussian (Rapid Drift)', lw=2.2, markersize=5)
    axs[0, 1].plot(horizons, metrics["discrete"]["compounding_error"], 's-', color='#2980b9', label='Discrete Categorical (Stable Rollout)', lw=2.5, markersize=5)
    axs[0, 1].set_title("(b) Open-Loop Imagination Compounding Error", fontsize=12, fontweight='bold')
    axs[0, 1].set_xlabel("Imagination Horizon Steps (H)", fontsize=10)
    axs[0, 1].set_ylabel("Rollout MSE (Deviation from Ground-Truth)", fontsize=10)
    axs[0, 1].grid(True)
    axs[0, 1].legend(loc='upper left', frameon=True)
    
    # Subplot 3: Latent Entropy dynamics
    axs[1, 0].plot(episodes, metrics["continuous"]["train_entropy"], color='#e67e22', label='Continuous Gaussian Entropy', lw=2.0)
    axs[1, 0].plot(episodes, metrics["discrete"]["train_entropy"], color='#16a085', label='Discrete Categorical Entropy', lw=2.0)
    axs[1, 0].set_title("(c) Latent State Information Entropy Dynamics", fontsize=12, fontweight='bold')
    axs[1, 0].set_xlabel("Training Episodes", fontsize=10)
    axs[1, 0].set_ylabel("Entropy (nats)", fontsize=10)
    axs[1, 0].grid(True)
    axs[1, 0].legend(loc='lower right', frameon=True)
    
    # Subplot 4: Regime-conditioned reconstruction MSE at final convergence
    regime_names = ["0: Free Flight", "1: Ground Friction", "2: Wall Impact", "3: Central Scatter"]
    cont_reg_final = [metrics["continuous"]["regime_recon_mse"][r][-1] for r in range(4)]
    disc_reg_final = [metrics["discrete"]["regime_recon_mse"][r][-1] for r in range(4)]
    
    x_indices = np.arange(len(regime_names))
    width = 0.35
    axs[1, 1].bar(x_indices - width/2, cont_reg_final, width, label='Continuous Gaussian', color='#e74c3c', alpha=0.85)
    axs[1, 1].bar(x_indices + width/2, disc_reg_final, width, label='Discrete Categorical', color='#2980b9', alpha=0.85)
    axs[1, 1].set_title("(d) Final Reconstruction MSE Across Physical Regimes", fontsize=12, fontweight='bold')
    axs[1, 1].set_xticks(x_indices)
    axs[1, 1].set_xticklabels(regime_names, rotation=15, ha='right', fontsize=9)
    axs[1, 1].set_ylabel("Regime MSE", fontsize=10)
    axs[1, 1].set_yscale('log')
    axs[1, 1].grid(True, axis='y')
    axs[1, 1].legend(loc='upper left', frameon=True)
    
    plt.tight_layout()
    fig_path = os.path.join(OUTPUT_DIR, "discrete_vs_continuous_rssm.png")
    plt.savefig(fig_path, dpi=300)
    plt.close()
    print(f"[+] Saved visualization: {fig_path}")

# ---------------------------------------------------------------------------
# Experiment 2: KL Dynamic Balancing (alpha = 0.2, 0.5, 0.8)
# ---------------------------------------------------------------------------

def run_experiment_kl_balancing(num_episodes=65, horizon=35, seed=202):
    print("\n" + "=" * 75)
    print(">>> [Experiment 2/3] KL Dynamic Balancing Ablation (alpha = 0.2, 0.5, 0.8)")
    print("=" * 75)
    
    env = HybridNonlinearPhysicsEnv(seed=seed)
    eval_trajectories = [env.rollout_trajectory(horizon=horizon) for _ in range(12)]
    
    alphas = [0.2, 0.5, 0.8]
    alpha_labels = {
        0.2: "alpha=0.2 (Posterior Pulled Fast, Risk of Collapse)",
        0.5: "alpha=0.5 (Symmetric KL Gradient, Standard VAE)",
        0.8: "alpha=0.8 (Prior Chasing Posterior, DreamerV2/V3 Default)"
    }
    
    models = {
        alpha: DiscreteCategoricalRSSM(obs_dim=16, action_dim=2, deter_dim=128, num_vars=32, num_classes=32, seed=seed+int(alpha*100))
        for alpha in alphas
    }
    
    metrics = {
        alpha: {
            "kl_div": [],
            "entropy": [],
            "recon_mse": [],
            "compounding_error": []
        }
        for alpha in alphas
    }
    
    print(f"[*] Training Discrete RSSM under KL balancing alphas {alphas} for {num_episodes} episodes...")
    
    for ep in range(num_episodes):
        obs_seq, act_seq, rew_seq, reg_seq = env.rollout_trajectory(horizon=horizon)
        
        for alpha in alphas:
            model = models[alpha]
            h, z = model.init_state()
            ep_kl = []
            ep_ent = []
            ep_recon = []
            
            for t in range(len(act_seq)):
                h, z, sdata = model.observe_step(h, z, act_seq[t], obs_seq[t+1])
                model.train_step_sgd(sdata, obs_seq[t+1], kl_balance_alpha=alpha, lr=0.002)
                ep_kl.append(sdata['kl'])
                ep_ent.append(sdata['entropy'])
                ep_recon.append(sdata['recon_loss'])
                
            metrics[alpha]["kl_div"].append(float(np.mean(ep_kl)))
            metrics[alpha]["entropy"].append(float(np.mean(ep_ent)))
            metrics[alpha]["recon_mse"].append(float(np.mean(ep_recon)))
            
        if (ep + 1) % 15 == 0 or ep == num_episodes - 1:
            print(f"    Episode {ep+1:02d}/{num_episodes:02d} | " + " | ".join(
                [f"a={a}: MSE={metrics[a]['recon_mse'][-1]:.4f}, Ent={metrics[a]['entropy'][-1]:.2f}, KL={metrics[a]['kl_div'][-1]:.3f}"
                 for a in alphas]
            ))
            
    # Evaluate compounding error for each alpha
    print("[*] Evaluating compounding error for each KL balance setting...")
    for alpha in alphas:
        metrics[alpha]["compounding_error"] = evaluate_horizon_compounding_error(
            models[alpha], eval_trajectories, max_horizon=28, warmup=5
        ).tolist()
        
    plot_kl_balancing(metrics)
    return metrics

def plot_kl_balancing(metrics):
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    episodes = np.arange(1, len(metrics[0.8]["recon_mse"]) + 1)
    
    colors = {0.2: '#e74c3c', 0.5: '#f39c12', 0.8: '#27ae60'}
    styles = {0.2: ':', 0.5: '--', 0.8: '-'}
    labels = {
        0.2: r'$\alpha=0.2$ (Posterior Over-Regularized)',
        0.5: r'$\alpha=0.5$ (Symmetric Balancing)',
        0.8: r'$\alpha=0.8$ (Prior Chasing Posterior)'
    }
    
    # Subplot 1: KL Divergence over training
    for a in [0.2, 0.5, 0.8]:
        axs[0, 0].plot(episodes, metrics[a]["kl_div"], color=colors[a], linestyle=styles[a], lw=2.3, label=labels[a])
    axs[0, 0].set_title(r"(a) Latent KL Divergence $\text{KL}(q(z|h,x) \parallel p(z|h))$", fontsize=12, fontweight='bold')
    axs[0, 0].set_xlabel("Training Episodes", fontsize=10)
    axs[0, 0].set_ylabel("KL Divergence (nats)", fontsize=10)
    axs[0, 0].grid(True)
    axs[0, 0].legend(loc='upper right', frameon=True)
    
    # Subplot 2: Posterior Entropy (Posterior collapse check)
    for a in [0.2, 0.5, 0.8]:
        axs[0, 1].plot(episodes, metrics[a]["entropy"], color=colors[a], linestyle=styles[a], lw=2.3, label=labels[a])
    axs[0, 1].set_title(r"(b) Posterior Latent Entropy $H(q)$ (Resistance to Collapse)", fontsize=12, fontweight='bold')
    axs[0, 1].set_xlabel("Training Episodes", fontsize=10)
    axs[0, 1].set_ylabel("Entropy (nats)", fontsize=10)
    axs[0, 1].grid(True)
    axs[0, 1].legend(loc='lower left', frameon=True)
    
    # Subplot 3: Reconstruction MSE over training
    for a in [0.2, 0.5, 0.8]:
        axs[1, 0].plot(episodes, metrics[a]["recon_mse"], color=colors[a], linestyle=styles[a], lw=2.3, label=labels[a])
    axs[1, 0].set_title("(c) Closed-Loop Reconstruction MSE", fontsize=12, fontweight='bold')
    axs[1, 0].set_xlabel("Training Episodes", fontsize=10)
    axs[1, 0].set_ylabel("Reconstruction MSE", fontsize=10)
    axs[1, 0].set_yscale('log')
    axs[1, 0].grid(True)
    axs[1, 0].legend(loc='upper right', frameon=True)
    
    # Subplot 4: Open-Loop Compounding Error vs Planning Horizon
    horizons = np.arange(1, len(metrics[0.8]["compounding_error"]) + 1)
    for a in [0.2, 0.5, 0.8]:
        axs[1, 1].plot(horizons, metrics[a]["compounding_error"], marker='o', markersize=4, color=colors[a], linestyle=styles[a], lw=2.0, label=labels[a])
    axs[1, 1].set_title("(d) Open-Loop Imagination Compounding Error Drift", fontsize=12, fontweight='bold')
    axs[1, 1].set_xlabel("Imagination Horizon Steps (H)", fontsize=10)
    axs[1, 1].set_ylabel("Rollout MSE", fontsize=10)
    axs[1, 1].grid(True)
    axs[1, 1].legend(loc='upper left', frameon=True)
    
    plt.tight_layout()
    fig_path = os.path.join(OUTPUT_DIR, "kl_balance_ablation.png")
    plt.savefig(fig_path, dpi=300)
    plt.close()
    print(f"[+] Saved visualization: {fig_path}")

# ---------------------------------------------------------------------------
# Experiment 3: Symlog vs Linear vs Clipping Normalization
# ---------------------------------------------------------------------------

def run_experiment_symlog_stability(seed=303):
    print("\n" + "=" * 75)
    print(">>> [Experiment 3/3] Symlog Transformation vs Linear vs Clipping Stability")
    print("=" * 75)
    
    # Value scales spanning multiple orders of magnitude: 10^-2 to 10^4
    value_magnitudes = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]
    num_samples_per_scale = 100
    clip_threshold = 50.0
    
    rng = np.random.RandomState(seed)
    
    methods = ['symlog', 'linear', 'clip']
    grad_norms = {m: [] for m in methods}
    grad_variances = {m: [] for m in methods}
    relative_errors = {m: [] for m in methods}
    effective_gradients = {m: [] for m in methods}
    
    print("[*] Simulating gradient backpropagation across 7 orders of value magnitude...")
    
    for val_scale in value_magnitudes:
        # Generate target values around this magnitude with noise
        true_values = rng.normal(val_scale, val_scale * 0.25, num_samples_per_scale)
        # Predictions with initialization bias (underestimating high targets)
        predicted_raw = rng.normal(val_scale * 0.7, val_scale * 0.2, num_samples_per_scale)
        
        # 1. Linear MSE: L = 0.5 * (y_hat - y)^2 => dL/dy_hat = (y_hat - y)
        linear_grads = predicted_raw - true_values
        linear_rel_err = np.abs(predicted_raw - true_values) / (np.abs(true_values) + 1e-6)
        
        grad_norms['linear'].append(float(np.mean(np.abs(linear_grads))))
        grad_variances['linear'].append(float(np.var(linear_grads)))
        relative_errors['linear'].append(float(np.mean(linear_rel_err)))
        
        # 2. Clipping MSE: y_clip = clip(y, -C, C) => gradient vanishes if clipped or saturates
        true_clipped = np.clip(true_values, -clip_threshold, clip_threshold)
        pred_clipped = np.clip(predicted_raw, -clip_threshold, clip_threshold)
        clip_grads = pred_clipped - true_clipped
        # If true_value was outside clip threshold, relative error in true space explodes
        clip_rel_err = np.abs(pred_clipped - true_values) / (np.abs(true_values) + 1e-6)
        
        grad_norms['clip'].append(float(np.mean(np.abs(clip_grads))))
        grad_variances['clip'].append(float(np.var(clip_grads)))
        relative_errors['clip'].append(float(np.mean(clip_rel_err)))
        
        # 3. Symlog: L = 0.5 * (symlog(y_hat) - symlog(y))^2
        # dL/dy_hat = (symlog(y_hat) - symlog(y)) * d_symlog(y_hat) = (symlog(y_hat) - symlog(y)) / (|y_hat| + 1)
        symlog_true = symlog(true_values)
        symlog_pred = symlog(predicted_raw)
        symlog_error = symlog_pred - symlog_true
        symlog_grads = symlog_error * d_symlog(predicted_raw)
        
        # Relative error after mapping back through symexp
        recovered_pred = symexp(symlog_pred)
        symlog_rel_err = np.abs(recovered_pred - true_values) / (np.abs(true_values) + 1e-6)
        
        grad_norms['symlog'].append(float(np.mean(np.abs(symlog_grads))))
        grad_variances['symlog'].append(float(np.var(symlog_grads)))
        relative_errors['symlog'].append(float(np.mean(symlog_rel_err)))
        
        print(f"    Magnitude {val_scale:8.2f} | "
              f"Grad Norms: Symlog={grad_norms['symlog'][-1]:.4f}, Clip={grad_norms['clip'][-1]:.4f}, Linear={grad_norms['linear'][-1]:.4f} | "
              f"Symlog RelErr={relative_errors['symlog'][-1]:.4f}")

    metrics = {
        "value_magnitudes": value_magnitudes,
        "grad_norms": grad_norms,
        "grad_variances": grad_variances,
        "relative_errors": relative_errors
    }
    
    plot_symlog_stability(metrics)
    return metrics

def plot_symlog_stability(metrics):
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    scales = metrics["value_magnitudes"]
    
    colors = {'symlog': '#27ae60', 'linear': '#e74c3c', 'clip': '#2980b9'}
    labels = {
        'symlog': r'Symlog $\text{sign}(x)\ln(|x|+1)$ (DreamerV3)',
        'linear': 'Linear MSE (Standard)',
        'clip': 'Clipping ($[-50, +50]$)'
    }
    markers = {'symlog': 'o-', 'linear': 's--', 'clip': '^:'}
    
    # Subplot 1: Gradient Norm across scales
    for m in ['symlog', 'clip', 'linear']:
        axs[0, 0].plot(scales, metrics["grad_norms"][m], markers[m], color=colors[m], label=labels[m], lw=2.2, markersize=6)
    axs[0, 0].set_title(r"(a) Parameter Gradient Norm $\Vert \nabla \mathcal{L} \Vert$ vs Target Scale", fontsize=12, fontweight='bold')
    axs[0, 0].set_xlabel("Target Value Magnitude (Order of Scale)", fontsize=10)
    axs[0, 0].set_ylabel("Mean Gradient Magnitude", fontsize=10)
    axs[0, 0].set_xscale('log')
    axs[0, 0].set_yscale('log')
    axs[0, 0].grid(True)
    axs[0, 0].legend(loc='upper left', frameon=True)
    
    # Subplot 2: Gradient Variance across batches
    for m in ['symlog', 'clip', 'linear']:
        axs[0, 1].plot(scales, metrics["grad_variances"][m], markers[m], color=colors[m], label=labels[m], lw=2.2, markersize=6)
    axs[0, 1].set_title("(b) Gradient Variance Across Mini-Batches", fontsize=12, fontweight='bold')
    axs[0, 1].set_xlabel("Target Value Magnitude", fontsize=10)
    axs[0, 1].set_ylabel(r"Gradient Variance $\text{Var}(\nabla \mathcal{L})$", fontsize=10)
    axs[0, 1].set_xscale('log')
    axs[0, 1].set_yscale('log')
    axs[0, 1].grid(True)
    axs[0, 1].legend(loc='upper left', frameon=True)
    
    # Subplot 3: Relative Prediction Error
    for m in ['symlog', 'clip', 'linear']:
        axs[1, 0].plot(scales, metrics["relative_errors"][m], markers[m], color=colors[m], label=labels[m], lw=2.2, markersize=6)
    axs[1, 0].set_title(r"(c) Relative Relative Error $\frac{|\hat{y}-y|}{|y|}$ Across Dynamic Ranges", fontsize=12, fontweight='bold')
    axs[1, 0].set_xlabel("Target Value Magnitude", fontsize=10)
    axs[1, 0].set_ylabel("Relative Error", fontsize=10)
    axs[1, 0].set_xscale('log')
    axs[1, 0].grid(True)
    axs[1, 0].legend(loc='upper right', frameon=True)
    
    # Subplot 4: Function Mapping Curve: x vs transformed value
    x_range = np.linspace(-1000, 1000, 2000)
    y_symlog = symlog(x_range)
    y_clip = np.clip(x_range, -50.0, 50.0)
    axs[1, 1].plot(x_range, y_symlog, color='#27ae60', lw=2.5, label='Symlog Mapping (Smooth Compression)')
    axs[1, 1].plot(x_range, y_clip, color='#2980b9', lw=2.0, linestyle='--', label='Clipping (Hard Saturation at +/- 50)')
    axs[1, 1].plot(x_range, np.sign(x_range)*np.sqrt(np.abs(x_range)), color='#8e44ad', lw=1.8, linestyle=':', label='Square Root (Unstable near 0)')
    axs[1, 1].set_title("(d) Dynamic Range Compression Curves", fontsize=12, fontweight='bold')
    axs[1, 1].set_xlabel("Input Value x", fontsize=10)
    axs[1, 1].set_ylabel("Transformed Value f(x)", fontsize=10)
    axs[1, 1].grid(True)
    axs[1, 1].legend(loc='upper left', frameon=True)
    
    plt.tight_layout()
    fig_path = os.path.join(OUTPUT_DIR, "symlog_gradient_stability.png")
    plt.savefig(fig_path, dpi=300)
    plt.close()
    print(f"[+] Saved visualization: {fig_path}")

# ---------------------------------------------------------------------------
# Main Execution Entrypoint
# ---------------------------------------------------------------------------

def main():
    start_time = time.time()
    print("=" * 80)
    print(">>> RSSM DEEP ABLATION EXPERIMENTAL SUITE")
    print(">>> Investigating Discrete Categorical STE, KL Balancing, & Symlog Dynamics")
    print("=" * 80)
    
    # 1. Run Discrete vs Continuous RSSM
    exp1_metrics = run_experiment_discrete_vs_continuous(num_episodes=70, horizon=35, seed=101)
    
    # 2. Run KL Balancing Ablation
    exp2_metrics = run_experiment_kl_balancing(num_episodes=65, horizon=35, seed=202)
    
    # 3. Run Symlog Stability
    exp3_metrics = run_experiment_symlog_stability(seed=303)
    
    # Compile comprehensive metrics dictionary
    total_metrics = {
        "metadata": {
            "suite_name": "RSSM Discrete Dynamics & Ablation Benchmark",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": round(time.time() - start_time, 2),
            "environment": "HybridNonlinearPhysicsEnv (16-D obs, 4 discrete regimes, multi-scale rewards)"
        },
        "experiment_1_discrete_vs_continuous": {
            "continuous_final_recon_mse": exp1_metrics["continuous"]["train_recon_mse"][-1],
            "discrete_final_recon_mse": exp1_metrics["discrete"]["train_recon_mse"][-1],
            "continuous_final_entropy": exp1_metrics["continuous"]["train_entropy"][-1],
            "discrete_final_entropy": exp1_metrics["discrete"]["train_entropy"][-1],
            "continuous_final_kl": exp1_metrics["continuous"]["train_kl"][-1],
            "discrete_final_kl": exp1_metrics["discrete"]["train_kl"][-1],
            "continuous_t28_compounding_mse": exp1_metrics["continuous"]["compounding_error"][-1],
            "discrete_t28_compounding_mse": exp1_metrics["discrete"]["compounding_error"][-1],
            "reconstruction_improvement_ratio": exp1_metrics["continuous"]["train_recon_mse"][-1] / max(exp1_metrics["discrete"]["train_recon_mse"][-1], 1e-6),
            "compounding_error_reduction_ratio": exp1_metrics["continuous"]["compounding_error"][-1] / max(exp1_metrics["discrete"]["compounding_error"][-1], 1e-6),
            "regime_final_mses": {
                "continuous": {r: exp1_metrics["continuous"]["regime_recon_mse"][r][-1] for r in range(4)},
                "discrete": {r: exp1_metrics["discrete"]["regime_recon_mse"][r][-1] for r in range(4)}
            }
        },
        "experiment_2_kl_balancing": {
            alpha: {
                "final_kl_div": exp2_metrics[alpha]["kl_div"][-1],
                "final_entropy": exp2_metrics[alpha]["entropy"][-1],
                "final_recon_mse": exp2_metrics[alpha]["recon_mse"][-1],
                "t28_compounding_mse": exp2_metrics[alpha]["compounding_error"][-1]
            }
            for alpha in [0.2, 0.5, 0.8]
        },
        "experiment_3_symlog_stability": {
            "value_magnitudes": exp3_metrics["value_magnitudes"],
            "grad_norm_summary": {
                m: {
                    "at_1e_minus_2": exp3_metrics["grad_norms"][m][0],
                    "at_1e_0": exp3_metrics["grad_norms"][m][2],
                    "at_1e_4": exp3_metrics["grad_norms"][m][-1],
                    "ratio_1e4_to_1e_minus_2": exp3_metrics["grad_norms"][m][-1] / max(exp3_metrics["grad_norms"][m][0], 1e-8)
                }
                for m in ['symlog', 'linear', 'clip']
            },
            "grad_variance_at_1e4": {
                m: exp3_metrics["grad_variances"][m][-1] for m in ['symlog', 'linear', 'clip']
            },
            "relative_error_at_1e4": {
                m: exp3_metrics["relative_errors"][m][-1] for m in ['symlog', 'linear', 'clip']
            }
        }
    }
    
    # Save to ablation_metrics.json
    metrics_path = os.path.join(OUTPUT_DIR, "ablation_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(total_metrics, f, indent=2)
    print(f"\n[+] Successfully saved consolidated metrics to: {metrics_path}")
    print(f"[+] Total execution time: {round(time.time() - start_time, 2)} seconds.")
    print("=" * 80)

if __name__ == "__main__":
    main()
