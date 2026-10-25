"""
RSSM (Recurrent State-Space Model) Minimal Simulation Prototype
===============================================================
A self-contained, mathematically rigorous implementation of the RSSM
dynamics used in PlaNet and Dreamer (V1/V2/V3).

Demonstrates:
1. Deterministic state recurrence (GRU transition) h_t = f(h_{t-1}, z_{t-1}, a_{t-1})
2. Stochastic latent state inference (Prior vs Posterior)
3. Latent imagination rollouts (Open-loop multi-step prediction)
4. Empirical measurement of Compounding Error as a function of planning horizon T
"""

import json
import math
import os
import sys
import numpy as np
import matplotlib.pyplot as plt

# Ensure reproducible random seed
np.random.seed(42)

def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -15.0, 15.0)))

def relu(x):
    return np.maximum(0.0, x)

class MinimalGRUCell:
    """Pure NumPy Implementation of a standard GRU Cell."""
    def __init__(self, input_dim, hidden_dim):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        
        # Weight initialization (Glorot / Xavier)
        scale_ih = 1.0 / math.sqrt(input_dim)
        scale_hh = 1.0 / math.sqrt(hidden_dim)
        
        self.W_ih = np.random.uniform(-scale_ih, scale_ih, (3 * hidden_dim, input_dim))
        self.W_hh = np.random.uniform(-scale_hh, scale_hh, (3 * hidden_dim, hidden_dim))
        self.b_ih = np.zeros(3 * hidden_dim)
        self.b_hh = np.zeros(3 * hidden_dim)
        
    def __call__(self, x, h):
        """
        x: [input_dim]
        h: [hidden_dim]
        returns: h_next: [hidden_dim]
        """
        gates_x = np.dot(self.W_ih, x) + self.b_ih
        gates_h = np.dot(self.W_hh, h) + self.b_hh
        
        H = self.hidden_dim
        r_gate = sigmoid(gates_x[0:H] + gates_h[0:H])
        z_gate = sigmoid(gates_x[H:2*H] + gates_h[H:2*H])
        n_gate = np.tanh(gates_x[2*H:3*H] + r_gate * gates_h[2*H:3*H])
        
        h_next = (1.0 - z_gate) * n_gate + z_gate * h
        return h_next

class RecurrentStateSpaceModel:
    """
    RSSM combining deterministic recurrence h_t with stochastic latents z_t.
    s_t = (h_t, z_t)
    """
    def __init__(self, action_dim=4, stoch_dim=32, deter_dim=128, obs_dim=64):
        self.action_dim = action_dim
        self.stoch_dim = stoch_dim
        self.deter_dim = deter_dim
        self.obs_dim = obs_dim
        
        # Deterministic GRU cell
        self.cell = MinimalGRUCell(input_dim=stoch_dim + action_dim, hidden_dim=deter_dim)
        
        # Prior network p(z_t | h_t): h_t -> (mean, std)
        self.W_prior_mean = np.random.randn(stoch_dim, deter_dim) * 0.05
        self.b_prior_mean = np.zeros(stoch_dim)
        self.W_prior_std = np.random.randn(stoch_dim, deter_dim) * 0.05
        self.b_prior_std = np.zeros(stoch_dim)
        
        # Posterior network q(z_t | h_t, obs_feat): [h_t, obs] -> (mean, std)
        self.W_post_mean = np.random.randn(stoch_dim, deter_dim + obs_dim) * 0.05
        self.b_post_mean = np.zeros(stoch_dim)
        self.W_post_std = np.random.randn(stoch_dim, deter_dim + obs_dim) * 0.05
        self.b_post_std = np.zeros(stoch_dim)
        
        # Observation decoder: [h_t, z_t] -> obs_reconstruction
        self.W_dec = np.random.randn(obs_dim, deter_dim + stoch_dim) * 0.05
        self.b_dec = np.zeros(obs_dim)

    def init_state(self):
        """Initial state for rollout."""
        h_0 = np.zeros(self.deter_dim)
        z_0 = np.zeros(self.stoch_dim)
        return h_0, z_0

    def compute_prior(self, h):
        """p(z_t | h_t)"""
        mean = np.dot(self.W_prior_mean, h) + self.b_prior_mean
        std = np.exp(np.clip(np.dot(self.W_prior_std, h) + self.b_prior_std, -2.0, 2.0))
        return mean, std

    def compute_posterior(self, h, obs_feat):
        """q(z_t | h_t, x_t)"""
        inp = np.concatenate([h, obs_feat])
        mean = np.dot(self.W_post_mean, inp) + self.b_post_mean
        std = np.exp(np.clip(np.dot(self.W_post_std, inp) + self.b_post_std, -2.0, 2.0))
        return mean, std

    def observe_step(self, prev_h, prev_z, action, obs_feat):
        """Single closed-loop step updating state with ground-truth observation."""
        inp = np.concatenate([prev_z, action])
        h_t = self.cell(inp, prev_h)
        post_mean, post_std = self.compute_posterior(h_t, obs_feat)
        prior_mean, prior_std = self.compute_prior(h_t)
        
        # Sample stochastic latent from posterior using reparameterization
        eps = np.random.randn(self.stoch_dim)
        z_t = post_mean + post_std * eps
        
        # Calculate KL Divergence between posterior and prior
        kl = np.sum(np.log(prior_std / post_std) + (post_std**2 + (post_mean - prior_mean)**2) / (2.0 * prior_std**2) - 0.5)
        return h_t, z_t, kl

    def imagine_step(self, prev_h, prev_z, action):
        """Single open-loop step (imagination) relying purely on prior."""
        inp = np.concatenate([prev_z, action])
        h_t = self.cell(inp, prev_h)
        prior_mean, prior_std = self.compute_prior(h_t)
        
        # Sample stochastic latent from internal prior
        eps = np.random.randn(self.stoch_dim)
        z_t = prior_mean + prior_std * eps
        return h_t, z_t

    def decode_obs(self, h, z):
        """Reconstruct observation from combined latent state."""
        feat = np.concatenate([h, z])
        return np.dot(self.W_dec, feat) + self.b_dec

def simulate_environment_dynamics(T=40, obs_dim=64, action_dim=4):
    """
    Simulates a ground-truth physical trajectory under continuous control.
    Generates non-linear physics transitions with harmonic oscillations.
    """
    obs_seq = []
    action_seq = []
    
    cur_obs = np.sin(np.linspace(0, 4*np.pi, obs_dim))
    
    for t in range(T):
        act = np.random.uniform(-1.0, 1.0, action_dim)
        # Physical dynamic shift + non-linear interaction
        drift = 0.15 * np.cos(np.linspace(0, 2*np.pi, obs_dim) * (t + 1))
        ctrl_effect = 0.05 * np.tile(act, obs_dim // action_dim)
        cur_obs = np.tanh(cur_obs * 0.95 + drift + ctrl_effect) + 0.02 * np.random.randn(obs_dim)
        
        obs_seq.append(cur_obs)
        action_seq.append(act)
        
    return np.array(obs_seq), np.array(action_seq)

def evaluate_compounding_error(rssm, obs_seq, action_seq, max_horizon=35):
    """
    Evaluates compounding error:
    Compares Closed-Loop Tracking (Filter with observations) vs
    Open-Loop Imagination (Brain rollout without observations)
    as horizon T expands.
    """
    total_steps = len(obs_seq)
    warmup_steps = 5
    
    # 1. Warm-up closed-loop filtering
    h, z = rssm.init_state()
    for t in range(warmup_steps):
        h, z, _ = rssm.observe_step(h, z, action_seq[t], obs_seq[t])
        
    # Baseline: continue closed-loop tracking with ground-truth
    closed_loop_errors = []
    h_closed, z_closed = np.copy(h), np.copy(z)
    
    # Branch 2: Open-loop pure latent imagination from warmup state
    open_loop_errors = []
    h_open, z_open = np.copy(h), np.copy(z)
    
    steps_to_eval = min(max_horizon, total_steps - warmup_steps)
    
    for k in range(steps_to_eval):
        t_idx = warmup_steps + k
        act = action_seq[t_idx]
        true_obs = obs_seq[t_idx]
        
        # Closed-loop step
        h_closed, z_closed, _ = rssm.observe_step(h_closed, z_closed, act, true_obs)
        pred_obs_closed = rssm.decode_obs(h_closed, z_closed)
        err_closed = float(np.mean((true_obs - pred_obs_closed)**2))
        closed_loop_errors.append(err_closed)
        
        # Open-loop imagination step (pure prior rollout)
        h_open, z_open = rssm.imagine_step(h_open, z_open, act)
        pred_obs_open = rssm.decode_obs(h_open, z_open)
        err_open = float(np.mean((true_obs - pred_obs_open)**2))
        open_loop_errors.append(err_open)
        
    return closed_loop_errors, open_loop_errors

def main():
    print("=" * 70)
    print(">>> Initializing Recurrent State-Space Model (RSSM) Prototype")
    print("=" * 70)
    
    rssm = RecurrentStateSpaceModel(action_dim=4, stoch_dim=32, deter_dim=128, obs_dim=64)
    print(f"[*] RSSM Instantiated:")
    print(f"    - Deterministic Hidden Dimension (h_t): {rssm.deter_dim}")
    print(f"    - Stochastic Latent Dimension (z_t)   : {rssm.stoch_dim}")
    print(f"    - Observation State Space (x_t)       : {rssm.obs_dim}")
    print(f"    - Control Action Space (a_t)          : {rssm.action_dim}")
    
    # Generate continuous physical trajectory
    T = 40
    print(f"\n[*] Generating Synthetic Physics Trajectory (Horizon T={T})...")
    obs_seq, action_seq = simulate_environment_dynamics(T=T, obs_dim=64, action_dim=4)
    
    # Warmup and test rollouts
    print("[*] Running Closed-Loop Filtering vs Open-Loop Latent Imagination...")
    closed_errs, open_errs = evaluate_compounding_error(rssm, obs_seq, action_seq, max_horizon=30)
    
    horizons = list(range(1, len(closed_errs) + 1))
    
    print("\n[+] Compounding Error Measurement Results:")
    print(f"{'Horizon (T)':^12} | {'Closed-Loop Error (MSE)':^24} | {'Open-Loop Imagination Error (MSE)':^32}")
    print("-" * 75)
    for h_step in [1, 5, 10, 15, 20, 25, 30]:
        idx = h_step - 1
        print(f"{h_step:^12} | {closed_errs[idx]:^24.5f} | {open_errs[idx]:^32.5f}")
        
    # Save metrics to JSON
    output_dir = os.path.dirname(os.path.abspath(__file__))
    metrics_path = os.path.join(output_dir, "simulation_metrics.json")
    
    metrics = {
        "description": "RSSM Latent Imagination Compounding Error Benchmark",
        "horizon_steps": horizons,
        "closed_loop_mse": closed_errs,
        "open_loop_imagination_mse": open_errs,
        "divergence_ratio_t30": open_errs[-1] / max(closed_errs[-1], 1e-6)
    }
    
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"\n[+] Saved metrics log to: {metrics_path}")
    
    # Generate visualization plot
    plt.figure(figsize=(10, 6))
    plt.plot(horizons, open_errs, 'r-o', linewidth=2.5, label='Open-Loop Imagination (No Obs Feedback)')
    plt.plot(horizons, closed_errs, 'b--s', linewidth=2.0, label='Closed-Loop Filtering (With Observations)')
    
    plt.title("RSSM Compounding Error Drift vs Planning Horizon", fontsize=14, fontweight='bold')
    plt.xlabel("Rollout Horizon Steps (T)", fontsize=12)
    plt.ylabel("Mean Squared Error (State Drift)", fontsize=12)
    plt.grid(True, linestyle=':', alpha=0.6)
    plt.legend(fontsize=11)
    
    plot_path = os.path.join(output_dir, "rssm_compounding_error.png")
    plt.tight_layout()
    plt.savefig(plot_path, dpi=200)
    plt.close()
    print(f"[+] Generated visualization plot: {plot_path}")
    print("\n>>> RSSM Simulation Prototype Completed Successfully! <<<")

if __name__ == "__main__":
    main()
