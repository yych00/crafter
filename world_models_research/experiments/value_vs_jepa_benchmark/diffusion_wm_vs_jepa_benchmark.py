"""
Diffusion World Models vs JEPA Decision Making Benchmark
========================================================
Comparative study between Diffusion World Models (e.g. DIAMOND, IRIS)
and Non-Generative Predictive Architectures (JEPA, Value-Equivalent MuZero).

Evaluates:
- Reverse Denoising Sampling Budgets (DDIM 2, 5, 10, 20 steps) vs 1-Step JEPA / MuZero
- Action Sampling Latency & Decision FPS (ms/step)
- Environmental Rollout Visual Fidelity (PSNR in dB, MSE)
- Closed-Loop Model Predictive Control (MPC) Cumulative Returns
- Pareto Frontier: Computational Throughput vs Visual Quality vs Task Reward
"""

import os
import sys
import time
import json
import numpy as np
import matplotlib.pyplot as plt

curr_dir = os.path.dirname(os.path.abspath(__file__))
if curr_dir not in sys.path:
    sys.path.append(curr_dir)

from composite_env import CompositeDistractorEnv
from nn_core import Linear, LayerNorm, ReLU, Tanh, Sequential, Adam, mse_loss, one_hot
from models import ReconstructionWM, ValueEquivalentWM, JepaWM


# ==============================================================================
# 1. Micro Denoising Diffusion Implicit Model (DDIM) World Model in NumPy
# ==============================================================================

class DiffusionWorldModel:
    """
    Continuous Diffusion World Model for Environment Dynamics (DIAMOND-style).
    Models p(o_{t+1} | o_t, a_t) via score-matching / noise prediction epsilon_theta.
    Supports flexible DDIM reverse sampling with 2, 5, 10, 20 steps.
    """
    def __init__(self, obs_dim=256, action_dim=5, hidden_dim=64, num_train_timesteps=50, lr=2e-3):
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.num_train_timesteps = num_train_timesteps
        
        # Linear Variance Schedule (beta_1 = 1e-4 to beta_T = 0.04)
        self.betas = np.linspace(1e-4, 0.04, num_train_timesteps, dtype=np.float32)
        self.alphas = 1.0 - self.betas
        self.alphas_cumprod = np.cumprod(self.alphas)
        
        # Time embedding dimension = 16
        self.time_embed_dim = 16
        
        # Denoising Network: takes [x_tau (256), time_embed (16), obs_t (256), a_vec (5)] -> epsilon (256)
        in_dim = obs_dim + self.time_embed_dim + obs_dim + action_dim
        self.denoise_net = Sequential(
            Linear(in_dim, hidden_dim * 2),
            LayerNorm(hidden_dim * 2),
            ReLU(),
            Linear(hidden_dim * 2, hidden_dim * 2),
            LayerNorm(hidden_dim * 2),
            ReLU(),
            Linear(hidden_dim * 2, obs_dim)
        )
        
        # Reward Prediction Head from generated next observation
        self.reward_head = Sequential(
            Linear(obs_dim, 32),
            ReLU(),
            Linear(32, 1)
        )
        
        all_params = self.denoise_net.parameters() + self.reward_head.parameters()
        self.optimizer = Adam(all_params, lr=lr)

    def _get_timestep_embedding(self, timesteps):
        """Sinusoidal positional embedding for diffusion timestep tau."""
        B = timesteps.shape[0]
        half_dim = self.time_embed_dim // 2
        emb_scale = np.log(10000.0) / (half_dim - 1)
        freqs = np.exp(-emb_scale * np.arange(half_dim, dtype=np.float32))
        args = timesteps[:, None] * freqs[None, :]
        embedding = np.concatenate([np.sin(args), np.cos(args)], axis=-1)
        return embedding.astype(np.float32)

    def train_step(self, obs_t, actions, rewards, obs_tp1):
        self.optimizer.zero_grad()
        B = obs_t.shape[0]
        a_vec = one_hot(actions, self.action_dim)
        
        # 1. Sample random timesteps tau in [0, T-1]
        tau = np.random.randint(0, self.num_train_timesteps, size=B)
        tau_embed = self._get_timestep_embedding(tau)
        
        # 2. Sample Gaussian noise epsilon
        noise = np.random.randn(*obs_tp1.shape).astype(np.float32)
        
        # 3. Add noise to target obs_tp1 according to schedule
        alpha_bar_t = self.alphas_cumprod[tau][:, None]
        x_noisy = np.sqrt(alpha_bar_t) * obs_tp1 + np.sqrt(1.0 - alpha_bar_t) * noise
        
        # 4. Predict noise epsilon_pred
        inp = np.concatenate([x_noisy, tau_embed, obs_t, a_vec], axis=-1)
        eps_pred = self.denoise_net.forward(inp)
        
        loss_diff, grad_diff = mse_loss(eps_pred, noise)
        
        # 5. Reward loss
        r_pred = self.reward_head.forward(obs_tp1)
        loss_rew, grad_rew = mse_loss(r_pred, rewards[:, None])
        
        # Backward
        grad_inp = self.denoise_net.backward(grad_diff)
        self.reward_head.backward(grad_rew)
        self.optimizer.step()
        
        return float(loss_diff + loss_rew)

    def sample_ddim(self, obs_t, actions, num_ddim_steps=5):
        """
        Fast DDIM reverse sampling with specified number of steps (e.g. 2, 5, 10, 20).
        Generates predicted next observation hat{o}_{t+1} and predicted reward.
        """
        B = obs_t.shape[0]
        a_vec = one_hot(actions, self.action_dim) if actions.ndim == 1 else actions
        
        # Subsequence of timesteps
        step_indices = np.linspace(0, self.num_train_timesteps - 1, num_ddim_steps, dtype=int)
        
        # Start from pure Gaussian noise x_T
        x_tau = np.random.randn(B, self.obs_dim).astype(np.float32)
        
        # Reverse sampling loop
        for i in reversed(range(len(step_indices))):
            t_curr = step_indices[i]
            tau_arr = np.full(B, t_curr, dtype=np.int32)
            tau_emb = self._get_timestep_embedding(tau_arr)
            
            # Predict noise
            inp = np.concatenate([x_tau, tau_emb, obs_t, a_vec], axis=-1)
            eps_pred = self.denoise_net.forward(inp)
            
            alpha_bar_curr = self.alphas_cumprod[t_curr]
            
            # Predict original x_0
            x_0_pred = (x_tau - np.sqrt(1.0 - alpha_bar_curr) * eps_pred) / (np.sqrt(alpha_bar_curr) + 1e-12)
            x_0_pred = np.clip(x_0_pred, 0.0, 1.0) # image clamp
            
            if i > 0:
                t_prev = step_indices[i - 1]
                alpha_bar_prev = self.alphas_cumprod[t_prev]
                # Deterministic DDIM trajectory (eta = 0)
                dir_xt = np.sqrt(1.0 - alpha_bar_prev) * eps_pred
                x_tau = np.sqrt(alpha_bar_prev) * x_0_pred + dir_xt
            else:
                x_tau = x_0_pred
                
        # Final predicted next observation & reward
        obs_pred_tp1 = np.clip(x_tau, 0.0, 1.0)
        r_pred = self.reward_head.forward(obs_pred_tp1).squeeze(-1)
        return obs_pred_tp1, r_pred


# ==============================================================================
# 2. Benchmarking Controller and Metrics Engine
# ==============================================================================

def compute_psnr(img_true, img_pred):
    """Calculates Peak Signal-to-Noise Ratio (PSNR in dB)."""
    mse = np.mean((img_true - img_pred) ** 2)
    if mse < 1e-12:
        return 50.0
    max_val = 1.0
    return float(10.0 * np.log10((max_val ** 2) / mse))


def evaluate_diffusion_mpc(diff_model, env, num_ddim_steps=5, num_episodes=5,
                           horizon=3, num_candidates=12):
    """
    Closed-loop Model Predictive Control using Diffusion World Model.
    Unrolls candidate action sequences via DDIM reverse sampling.
    """
    total_returns = []
    latencies = []
    
    for ep in range(num_episodes):
        obs, _ = env.reset(seed=ep * 100 + 42)
        ep_ret = 0.0
        
        for t in range(env.max_steps):
            t0 = time.perf_counter()
            
            # Candidate sequences (num_candidates, horizon)
            candidate_seqs = np.random.randint(0, env.action_dim, size=(num_candidates, horizon))
            for a_i in range(env.action_dim):
                candidate_seqs[a_i] = a_i
                
            obs_batch = np.repeat(obs[None, :], num_candidates, axis=0)
            cum_rewards = np.zeros(num_candidates, dtype=np.float32)
            gamma = 0.95
            
            # Rollout in generative space using DDIM
            curr_obs_sim = obs_batch
            for k in range(horizon):
                acts = candidate_seqs[:, k]
                curr_obs_sim, r_pred = diff_model.sample_ddim(curr_obs_sim, acts, num_ddim_steps=num_ddim_steps)
                cum_rewards += (gamma ** k) * r_pred
                
            best_act = int(candidate_seqs[np.argmax(cum_rewards), 0])
            step_latency_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(step_latency_ms)
            
            obs, rew, done, _ = env.step(best_act)
            ep_ret += rew
            if done:
                break
                
        total_returns.append(ep_ret)
        
    return float(np.mean(total_returns)), float(np.mean(latencies))


def evaluate_jepa_mpc(jepa_model, env, num_episodes=5, horizon=3, num_candidates=12):
    """1-Step Feedforward Latent MPC using Foundation JEPA."""
    total_returns = []
    latencies = []
    
    for ep in range(num_episodes):
        obs, _ = env.reset(seed=ep * 100 + 42)
        ep_ret = 0.0
        
        for t in range(env.max_steps):
            t0 = time.perf_counter()
            
            candidate_seqs = np.random.randint(0, env.action_dim, size=(num_candidates, horizon))
            for a_i in range(env.action_dim):
                candidate_seqs[a_i] = a_i
                
            z_root = jepa_model.encode(obs[None, :])
            z_batch = np.repeat(z_root, num_candidates, axis=0)
            cum_rewards = np.zeros(num_candidates, dtype=np.float32)
            gamma = 0.95
            
            # 1-Step Feedforward transition in latent space
            curr_z = z_batch
            for k in range(horizon):
                acts = candidate_seqs[:, k]
                curr_z, r_pred = jepa_model.predict_next(curr_z, acts)
                cum_rewards += (gamma ** k) * r_pred
                
            best_act = int(candidate_seqs[np.argmax(cum_rewards), 0])
            step_latency_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(step_latency_ms)
            
            obs, rew, done, _ = env.step(best_act)
            ep_ret += rew
            if done:
                break
                
        total_returns.append(ep_ret)
        
    return float(np.mean(total_returns)), float(np.mean(latencies))


def evaluate_muzero_mpc(muzero_model, env, num_episodes=5, horizon=3, num_candidates=12):
    """1-Step Feedforward Value-Equivalent MPC using MuZero dynamics."""
    total_returns = []
    latencies = []
    
    for ep in range(num_episodes):
        obs, _ = env.reset(seed=ep * 100 + 42)
        ep_ret = 0.0
        
        for t in range(env.max_steps):
            t0 = time.perf_counter()
            
            candidate_seqs = np.random.randint(0, env.action_dim, size=(num_candidates, horizon))
            for a_i in range(env.action_dim):
                candidate_seqs[a_i] = a_i
                
            s_root = muzero_model.encode(obs[None, :])
            s_batch = np.repeat(s_root, num_candidates, axis=0)
            cum_rewards = np.zeros(num_candidates, dtype=np.float32)
            gamma = 0.95
            
            curr_s = s_batch
            for k in range(horizon):
                acts = candidate_seqs[:, k]
                curr_s, r_pred = muzero_model.predict_next(curr_s, acts)
                cum_rewards += (gamma ** k) * r_pred
                
            best_act = int(candidate_seqs[np.argmax(cum_rewards), 0])
            step_latency_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(step_latency_ms)
            
            obs, rew, done, _ = env.step(best_act)
            ep_ret += rew
            if done:
                break
                
        total_returns.append(ep_ret)
        
    return float(np.mean(total_returns)), float(np.mean(latencies))


# ==============================================================================
# 3. Main Benchmark Execution Pipeline
# ==============================================================================

def run_diffusion_benchmark():
    print("================================================================================")
    print("STARTING BENCHMARK: DIFFUSION WORLD MODELS (DIAMOND/IRIS) vs JEPA vs MUZERO")
    print("================================================================================")
    
    noise_ratio = 0.35
    seed = 42
    np.random.seed(seed)
    
    env = CompositeDistractorEnv(grid_size=16, noise_ratio=noise_ratio, seed=seed)
    test_env = CompositeDistractorEnv(grid_size=16, noise_ratio=noise_ratio, seed=seed + 100)
    
    # 1. Collect Interactive Dataset
    print("\n1. Collecting interactive environment dataset...")
    obs_list, act_list, rew_list, nobs_list = [], [], [], []
    obs, _ = env.reset()
    for _ in range(800):
        a = np.random.randint(0, env.action_dim)
        nobs, r, d, _ = env.step(a)
        obs_list.append(obs)
        act_list.append(a)
        rew_list.append(r)
        nobs_list.append(nobs)
        obs = env.reset()[0] if d else nobs
        
    train_data = {
        "obs": np.array(obs_list, dtype=np.float32),
        "actions": np.array(act_list, dtype=np.int32),
        "rewards": np.array(rew_list, dtype=np.float32),
        "next_obs": np.array(nobs_list, dtype=np.float32)
    }
    
    # Pre-calculate returns for MuZero
    gamma = 0.95
    returns = np.zeros_like(train_data["rewards"])
    running = 0.0
    for t in reversed(range(len(returns))):
        running = train_data["rewards"][t] + gamma * running
        returns[t] = running
    train_data["values"] = returns
    train_data["next_values"] = np.roll(returns, -1)
    train_data["next_values"][-1] = 0.0
    
    # 2. Train Models
    print("\n2. Training Models:")
    print("  -> Training Continuous Diffusion World Model (DIAMOND prototype)...")
    diff_model = DiffusionWorldModel(obs_dim=256, action_dim=5, hidden_dim=64, num_train_timesteps=50, lr=2e-3)
    
    batch_size = 32
    N = len(train_data["obs"])
    steps = N // batch_size
    t0 = time.time()
    for ep in range(120):
        perm = np.random.permutation(N)
        for s in range(steps):
            idx = perm[s * batch_size:(s + 1) * batch_size]
            diff_model.train_step(train_data["obs"][idx], train_data["actions"][idx],
                                  train_data["rewards"][idx], train_data["next_obs"][idx])
    diff_train_time = time.time() - t0
    print(f"     Diffusion WM training completed in {diff_train_time:.2f}s")
    
    print("  -> Training Foundation JEPA (V-JEPA prototype)...")
    jepa_model = JepaWM(obs_dim=256, latent_dim=32, action_dim=5, lr=2e-3, ema_tau=0.98)
    t0 = time.time()
    for ep in range(120):
        perm = np.random.permutation(N)
        for s in range(steps):
            idx = perm[s * batch_size:(s + 1) * batch_size]
            jepa_model.train_step(train_data["obs"][idx], train_data["actions"][idx],
                                  train_data["rewards"][idx], train_data["next_obs"][idx])
    jepa_train_time = time.time() - t0
    print(f"     JEPA training completed in {jepa_train_time:.2f}s")
    
    print("  -> Training Value-Equivalent MuZero...")
    muzero_model = ValueEquivalentWM(obs_dim=256, latent_dim=32, action_dim=5, lr=2e-3)
    t0 = time.time()
    for ep in range(120):
        perm = np.random.permutation(N)
        for s in range(steps):
            idx = perm[s * batch_size:(s + 1) * batch_size]
            muzero_model.train_step(train_data["obs"][idx], train_data["actions"][idx],
                                    train_data["rewards"][idx], train_data["next_obs"][idx],
                                    train_data["values"][idx], train_data["next_values"][idx],
                                    train_data["actions"][idx])
    muzero_train_time = time.time() - t0
    print(f"     MuZero training completed in {muzero_train_time:.2f}s")
    
    # --------------------------------------------------------------------------
    # 3. Evaluate Environmental Reconstruction Fidelity (PSNR)
    # --------------------------------------------------------------------------
    print("\n3. Evaluating Rollout Visual Fidelity (PSNR in dB)...")
    test_sample_n = 50
    test_obs = train_data["obs"][:test_sample_n]
    test_acts = train_data["actions"][:test_sample_n]
    test_true_nobs = train_data["next_obs"][:test_sample_n]
    
    ddim_steps_list = [2, 5, 10, 20]
    psnr_scores = {}
    
    for s_step in ddim_steps_list:
        gen_obs, _ = diff_model.sample_ddim(test_obs, test_acts, num_ddim_steps=s_step)
        psnr_val = np.mean([compute_psnr(test_true_nobs[i], gen_obs[i]) for i in range(test_sample_n)])
        psnr_scores[f"DDIM_{s_step}"] = float(psnr_val)
        print(f"  Diffusion (DDIM-{s_step:2d} steps) | Environmental Rollout PSNR: {psnr_val:5.2f} dB")
        
    # JEPA and MuZero are Decoder-Free (Non-generative: infinite or NA PSNR, represented as abstract latent)
    psnr_scores["JEPA"] = 0.0 # Non-generative by design
    psnr_scores["MuZero"] = 0.0 # Non-generative by design
    
    # --------------------------------------------------------------------------
    # 4. Closed-Loop MPC Control Benchmark & Latency Evaluation
    # --------------------------------------------------------------------------
    print("\n4. Running Closed-Loop Action MPC Benchmark across Reverse Compute Budgets...")
    mpc_results = {}
    
    # Test Diffusion at different DDIM budgets
    for s_step in ddim_steps_list:
        print(f"  Evaluating Diffusion WM (DDIM-{s_step} steps)...")
        avg_ret, avg_lat = evaluate_diffusion_mpc(diff_model, test_env, num_ddim_steps=s_step,
                                                   num_episodes=4, horizon=3, num_candidates=12)
        fps = 1000.0 / max(0.01, avg_lat)
        mpc_results[f"Diffusion_DDIM_{s_step}"] = {
            "return": avg_ret,
            "latency_ms": avg_lat,
            "fps": fps,
            "psnr_db": psnr_scores[f"DDIM_{s_step}"],
            "num_steps": s_step,
            "type": "Generative Diffusion"
        }
        print(f"    -> Return: {avg_ret:6.2f} | Latency: {avg_lat:6.2f} ms | Decision FPS: {fps:5.1f}")
        
    # Test JEPA 1-step feedforward
    print("  Evaluating Foundation JEPA (1-step Latent Feedforward)...")
    jepa_ret, jepa_lat = evaluate_jepa_mpc(jepa_model, test_env, num_episodes=4, horizon=3, num_candidates=12)
    jepa_fps = 1000.0 / max(0.01, jepa_lat)
    mpc_results["JEPA_1Step"] = {
        "return": jepa_ret,
        "latency_ms": jepa_lat,
        "fps": jepa_fps,
        "psnr_db": 0.0,
        "num_steps": 1,
        "type": "Abstract Feature WM"
    }
    print(f"    -> Return: {jepa_ret:6.2f} | Latency: {jepa_lat:6.2f} ms | Decision FPS: {jepa_fps:5.1f}")
    
    # Test MuZero 1-step feedforward
    print("  Evaluating Value-Equivalent MuZero (1-step Latent Feedforward)...")
    mu_ret, mu_lat = evaluate_muzero_mpc(muzero_model, test_env, num_episodes=4, horizon=3, num_candidates=12)
    mu_fps = 1000.0 / max(0.01, mu_lat)
    mpc_results["MuZero_1Step"] = {
        "return": mu_ret,
        "latency_ms": mu_lat,
        "fps": mu_fps,
        "psnr_db": 0.0,
        "num_steps": 1,
        "type": "Value-Equivalent WM"
    }
    print(f"    -> Return: {mu_ret:6.2f} | Latency: {mu_lat:6.2f} ms | Decision FPS: {mu_fps:5.1f}")
    
    # Save Metrics JSON
    benchmark_metrics = {
        "training_times": {
            "Diffusion_WM": diff_train_time,
            "JEPA": jepa_train_time,
            "MuZero": muzero_train_time
        },
        "visual_fidelity_psnr": psnr_scores,
        "mpc_evaluations": mpc_results
    }
    
    json_path = os.path.join(curr_dir, "diffusion_vs_jepa_metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_metrics, f, indent=2, ensure_ascii=False)
    print(f"\nMetrics written to: {json_path}")
    
    # 5. Generate Visualizations
    generate_diffusion_charts(benchmark_metrics)


def generate_diffusion_charts(metrics):
    """Generates two publication-grade figures for Diffusion vs JEPA benchmark."""
    plt.style.use('default')
    plt.rcParams['font.family'] = 'DejaVu Sans'
    
    mpc = metrics["mpc_evaluations"]
    
    # --------------------------------------------------------------------------
    # Figure 1: Pareto Frontier & Compute vs Policy Return (2 Panels)
    # --------------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), dpi=300)
    fig.suptitle("Diffusion World Models vs Non-Generative JEPA/MuZero: Compute-Control Pareto Frontier",
                 fontsize=13, fontweight='bold', y=0.98)
                 
    # Panel A: Latency vs Return (Pareto Frontier)
    ax1 = axes[0]
    
    # Diffusion points
    ddim_keys = ["Diffusion_DDIM_2", "Diffusion_DDIM_5", "Diffusion_DDIM_10", "Diffusion_DDIM_20"]
    diff_lat = [mpc[k]["latency_ms"] for k in ddim_keys]
    diff_ret = [mpc[k]["return"] for k in ddim_keys]
    steps_label = [2, 5, 10, 20]
    
    ax1.plot(diff_lat, diff_ret, marker='o', color='#E63946', linewidth=2.2, label='Diffusion WM (DDIM steps)', markersize=8)
    for i, txt in enumerate(steps_label):
        ax1.annotate(f"DDIM-{txt}", (diff_lat[i], diff_ret[i]), textcoords="offset points", xytext=(0, 8),
                     ha='center', fontsize=9, fontweight='bold', color='#E63946')
                     
    # Non-generative points
    ax1.scatter([mpc["JEPA_1Step"]["latency_ms"]], [mpc["JEPA_1Step"]["return"]], color='#2A9D8F',
                s=160, marker='D', label='Foundation JEPA (1-step forward)', zorder=5)
    ax1.annotate("JEPA (1-Step)\nUltra-Fast", (mpc["JEPA_1Step"]["latency_ms"], mpc["JEPA_1Step"]["return"]),
                 textcoords="offset points", xytext=(20, -10), ha='left', fontsize=9.5, fontweight='bold', color='#2A9D8F')
                 
    ax1.scatter([mpc["MuZero_1Step"]["latency_ms"]], [mpc["MuZero_1Step"]["return"]], color='#E76F51',
                s=160, marker='s', label='MuZero (1-step forward)', zorder=5)
    ax1.annotate("MuZero (1-Step)", (mpc["MuZero_1Step"]["latency_ms"], mpc["MuZero_1Step"]["return"]),
                 textcoords="offset points", xytext=(20, 5), ha='left', fontsize=9.5, fontweight='bold', color='#E76F51')
                 
    ax1.set_xlabel("Decision Step Latency (ms) [Log Scale]", fontsize=10, fontweight='bold')
    ax1.set_ylabel("Closed-Loop MPC Return", fontsize=10, fontweight='bold')
    ax1.set_xscale('log')
    ax1.set_title("A. Latency vs Return Pareto Trade-Off (Left-Top is Optimal)", fontsize=11, fontweight='bold', pad=8)
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend(loc='lower left', framealpha=0.95, fontsize=9)
    
    # Panel B: Decision Throughput (FPS) Comparison Bar Chart
    ax2 = axes[1]
    all_keys = ["Diffusion_DDIM_20", "Diffusion_DDIM_10", "Diffusion_DDIM_5", "Diffusion_DDIM_2", "MuZero_1Step", "JEPA_1Step"]
    display_names = ["Diffusion\n(DDIM-20)", "Diffusion\n(DDIM-10)", "Diffusion\n(DDIM-5)", "Diffusion\n(DDIM-2)", "MuZero\n(1-Step)", "JEPA\n(1-Step)"]
    fps_vals = [mpc[k]["fps"] for k in all_keys]
    bar_colors = ['#B7094C', '#C72C41', '#E63946', '#F4A261', '#E76F51', '#2A9D8F']
    
    bars = ax2.bar(display_names, fps_vals, color=bar_colors, width=0.55, alpha=0.9)
    ax2.set_ylabel("Decision Throughput (Control Frequency FPS)", fontsize=10, fontweight='bold')
    ax2.set_title("B. Closed-Loop Real-Time Control Frequency (FPS)", fontsize=11, fontweight='bold', pad=8)
    ax2.grid(axis='y', linestyle='--', alpha=0.6)
    
    for b in bars:
        h = b.get_height()
        ax2.annotate(f"{h:.1f} FPS", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                     textcoords="offset points", ha='center', va='bottom', fontsize=8.5, fontweight='bold')
                     
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    pareto_path = os.path.join(curr_dir, "diffusion_vs_jepa_pareto_frontier.png")
    plt.savefig(pareto_path, dpi=300)
    plt.close()
    print(f"Saved: {pareto_path}")
    
    # --------------------------------------------------------------------------
    # Figure 2: Denoising Steps Trade-off Curve (Visual Fidelity vs Compute Cost)
    # --------------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), dpi=300)
    fig.suptitle("Diffusion Denoising Horizon Analysis: Visual Quality (PSNR) vs Computational Penalty",
                 fontsize=13, fontweight='bold', y=0.98)
                 
    steps_arr = [2, 5, 10, 20]
    psnr_arr = [metrics["visual_fidelity_psnr"][f"DDIM_{s}"] for s in steps_arr]
    lat_arr = [mpc[f"Diffusion_DDIM_{s}"]["latency_ms"] for s in steps_arr]
    
    # Panel 1: PSNR vs Steps
    ax3 = axes[0]
    ax3.plot(steps_arr, psnr_arr, marker='o', color='#457B9D', linewidth=2.4, markersize=8)
    ax3.set_title("A. Image Rollout PSNR vs DDIM Sampling Steps", fontsize=11, fontweight='bold', pad=8)
    ax3.set_xlabel("Number of DDIM Reverse Denoising Steps", fontsize=10, fontweight='bold')
    ax3.set_ylabel("Peak Signal-to-Noise Ratio (PSNR dB)", fontsize=10, fontweight='bold')
    ax3.set_xticks(steps_arr)
    ax3.grid(True, linestyle="--", alpha=0.6)
    for i, s in enumerate(steps_arr):
        ax3.annotate(f"{psnr_arr[i]:.2f} dB", (s, psnr_arr[i]), textcoords="offset points", xytext=(0, 6),
                     ha='center', fontsize=9, fontweight='bold')
                     
    # Panel 2: Latency Cost vs Steps
    ax4 = axes[1]
    ax4.plot(steps_arr, lat_arr, marker='s', color='#E63946', linewidth=2.4, markersize=8, label='Diffusion WM Latency')
    ax4.axhline(mpc["JEPA_1Step"]["latency_ms"], color='#2A9D8F', linestyle='--', linewidth=2.0, label='JEPA 1-Step Latency Baseline')
    ax4.axhline(mpc["MuZero_1Step"]["latency_ms"], color='#E76F51', linestyle=':', linewidth=2.0, label='MuZero 1-Step Latency Baseline')
    
    ax4.set_title("B. Single-Step MPC Planning Latency vs Steps", fontsize=11, fontweight='bold', pad=8)
    ax4.set_xlabel("Number of DDIM Reverse Denoising Steps", fontsize=10, fontweight='bold')
    ax4.set_ylabel("Decision Latency per Step (ms)", fontsize=10, fontweight='bold')
    ax4.set_xticks(steps_arr)
    ax4.grid(True, linestyle="--", alpha=0.6)
    ax4.legend(loc='upper left', framealpha=0.95, fontsize=9)
    
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    tradeoff_path = os.path.join(curr_dir, "denoising_steps_tradeoff_curve.png")
    plt.savefig(tradeoff_path, dpi=300)
    plt.close()
    print(f"Saved: {tradeoff_path}")


if __name__ == "__main__":
    run_diffusion_benchmark()
