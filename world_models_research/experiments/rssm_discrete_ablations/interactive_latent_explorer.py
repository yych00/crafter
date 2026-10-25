"""
Interactive Latent Explorer & DreamerV3 Two-Hot / Percentile Normalization Engine
================================================================================
Extracts and serializes high-resolution time-series data of 32x32 discrete One-Hot
latent representations, Two-Hot reward/value categorical encoding, and percentile
normalization across physical transitions.

Outputs:
- latent_step_visualization.json: Detailed step-by-step activations, prob heatmaps,
  and state trajectories for interactive frontend visualizers.
"""

import os
import sys
import json
import math
import numpy as np

# Import base modules from existing engine
from rssm_dynamics_engine import (
    HybridNonlinearPhysicsEnv,
    DiscreteCategoricalRSSM,
    symlog,
    symexp,
    softmax
)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# DreamerV3 Two-Hot Categorical Representation
# ---------------------------------------------------------------------------

class TwoHotCategoricalDistribution:
    """
    DreamerV3 Two-Hot Categorical Value/Reward Distribution.
    Discretizes continuous scalar space into B symlog-spaced bins:
    b_k = symexp(linspace(symlog(v_min), symlog(v_max), B))
    Encodes any scalar y into a two-hot target distribution over adjacent bins b_k <= y <= b_{k+1}
    with linear weights:
    w_k = (b_{k+1} - y) / (b_{k+1} - b_k)
    w_{k+1} = (y - b_k) / (b_{k+1} - b_k)
    Loss is cross-entropy: L = -sum_i p_i^target * ln(q_i)
    Gradient dL/d(logit_i) = q_i - p_i^target in [-1, 1], guaranteeing absolute gradient boundedness!
    """
    def __init__(self, num_bins=255, v_min=-20.0, v_max=20.0):
        self.num_bins = num_bins
        self.v_min = v_min
        self.v_max = v_max
        
        # Symlog-spaced bin centers
        sym_min = symlog(v_min)
        sym_max = symlog(v_max)
        self.bin_centers_symlog = np.linspace(sym_min, sym_max, num_bins)
        self.bin_centers = symexp(self.bin_centers_symlog)

    def encode(self, y):
        """
        Encodes scalar target y into Two-Hot probability distribution of size B.
        Returns target vector p in Delta_{B-1} such that sum_k p_k * b_k == y.
        """
        # Clamp to bin bounds
        y_clamped = np.clip(y, self.bin_centers[0], self.bin_centers[-1])
        
        # Binary search for interval b_k <= y_clamped <= b_{k+1}
        idx = np.searchsorted(self.bin_centers, y_clamped)
        if idx == 0:
            target = np.zeros(self.num_bins)
            target[0] = 1.0
            return target
        if idx >= self.num_bins:
            target = np.zeros(self.num_bins)
            target[-1] = 1.0
            return target
            
        k = idx - 1
        b_low = self.bin_centers[k]
        b_high = self.bin_centers[k + 1]
        
        # Linear interpolation weights
        denom = max(b_high - b_low, 1e-8)
        w_high = (y_clamped - b_low) / denom
        w_low = (b_high - y_clamped) / denom
        
        target = np.zeros(self.num_bins)
        target[k] = w_low
        target[k + 1] = w_high
        return target

    def decode(self, logits):
        """
        Computes expected scalar value from logits:
        E[y] = sum_k q_k * b_k, where q = softmax(logits).
        """
        probs = softmax(logits)
        expected_val = float(np.sum(probs * self.bin_centers))
        return expected_val, probs

    def loss_and_gradient(self, logits, y_target):
        """
        Categorical cross-entropy loss and exact analytical gradient:
        L = - sum p_i^target * ln(q_i)
        dL / d(logits_i) = q_i - p_i^target  in [-1.0, 1.0]!
        """
        target_dist = self.encode(y_target)
        probs = softmax(logits)
        eps = 1e-12
        loss = -float(np.sum(target_dist * np.log(np.clip(probs, eps, 1.0))))
        grad_logits = probs - target_dist
        return loss, grad_logits, target_dist, probs

# ---------------------------------------------------------------------------
# DreamerV3 Percentile Normalization
# ---------------------------------------------------------------------------

class PercentileNormalizer:
    """
    DreamerV3 Return / Value Percentile Normalizer.
    Maintains running 5th percentile P_5 and 95th percentile P_95 via EMA.
    Normalizes advantages or returns:
    R_norm = (R - P_5) / max(P_95 - P_5, 1.0)
    Provides complete scale-invariance across diverse reward scales without hyperparameter tuning.
    """
    def __init__(self, low_pct=5.0, high_pct=95.0, decay=0.99):
        self.low_pct = low_pct
        self.high_pct = high_pct
        self.decay = decay
        self.p_low = 0.0
        self.p_high = 1.0
        self.initialized = False
        self.history = []

    def update(self, return_batch):
        """Update running percentiles with a new batch of returns."""
        self.history.extend(return_batch)
        if len(self.history) > 500:
            self.history = self.history[-500:] # Keep recent window
            
        cur_low = float(np.percentile(self.history, self.low_pct))
        cur_high = float(np.percentile(self.history, self.high_pct))
        
        if not self.initialized:
            self.p_low = cur_low
            self.p_high = cur_high
            self.initialized = True
        else:
            self.p_low = self.decay * self.p_low + (1.0 - self.decay) * cur_low
            self.p_high = self.decay * self.p_high + (1.0 - self.decay) * cur_high

    def normalize(self, val):
        """Scale return into robust scale-free range."""
        scale = max(self.p_high - self.p_low, 1.0)
        return (val - self.p_low) / scale

    def get_scale(self):
        return max(self.p_high - self.p_low, 1.0)

# ---------------------------------------------------------------------------
# Interactive Latent Explorer & Data Serializer
# ---------------------------------------------------------------------------

def run_latent_exploration(num_steps=30, seed=42):
    print("=" * 80)
    print(">>> INTERACTIVE LATENT EXPLORER (DreamerV3 Two-Hot & Percentile Normalization)")
    print(">>> Generating 32x32 One-Hot Latent Trajectories & Two-Hot Probability Dynamics")
    print("=" * 80)
    
    env = HybridNonlinearPhysicsEnv(seed=seed)
    rssm = DiscreteCategoricalRSSM(obs_dim=16, action_dim=2, deter_dim=128, num_vars=32, num_classes=32, seed=seed)
    
    # Pre-train RSSM for 20 episodes to obtain structured representations
    print("[*] Calibrating 32x32 discrete RSSM on hybrid physics environment...")
    for ep in range(20):
        obs_seq, act_seq, rew_seq, reg_seq = env.rollout_trajectory(horizon=25)
        h, z = rssm.init_state()
        for t in range(len(act_seq)):
            h, z, sdata = rssm.observe_step(h, z, act_seq[t], obs_seq[t+1])
            rssm.train_step_sgd(sdata, obs_seq[t+1], kl_balance_alpha=0.8, lr=0.002)

    # Initialize Two-Hot encoder & Percentile normalizer
    two_hot = TwoHotCategoricalDistribution(num_bins=64, v_min=-50.0, v_max=50.0)
    normalizer = PercentileNormalizer(low_pct=5.0, high_pct=95.0, decay=0.95)
    
    # Collect returns for normalizer warm-up
    warmup_returns = [float(np.random.normal(1.0, 5.0)) for _ in range(50)]
    warmup_returns.extend([100.0, 500.0, -10.0]) # Add heavy-tailed outliers
    normalizer.update(warmup_returns)
    
    # Run test rollout trajectory and record step-by-step tensor diagnostics
    print(f"[*] Executing detailed {num_steps}-step latent trace rollout...")
    obs, _ = env.reset()
    h, z = rssm.init_state()
    
    steps_data = []
    regime_names = {
        0: "Free Flight (Ballistic)",
        1: "Ground Friction (Coulomb)",
        2: "Wall Impact Rebound",
        3: "Central Obstacle Scatter (High Shock)"
    }
    
    # Project 128-D h_t to 2D using random fixed projection matrix for visualization
    rng_proj = np.random.RandomState(1234)
    pca_matrix = rng_proj.randn(128, 2)
    pca_matrix, _ = np.linalg.qr(pca_matrix) # Orthonormal basis
    
    accumulated_return = 0.0
    
    for t in range(num_steps):
        act = np.clip(env.rng.normal(0.0, 0.6, 2), -1.0, 1.0)
        next_obs, rew, regime = env.step(act)
        accumulated_return += rew
        
        # Update percentile normalizer
        normalizer.update([rew])
        norm_return = normalizer.normalize(accumulated_return)
        
        # Observe step
        h, z, sdata = rssm.observe_step(h, z, act, next_obs)
        
        # Reshape 32x32 categorical variables
        probs_32x32 = sdata['post_probs'].reshape(32, 32)
        one_hot_32x32 = sdata['z_t'].reshape(32, 32)
        active_indices = np.argmax(one_hot_32x32, axis=-1).tolist()
        
        # Compute entropy per variable
        eps = 1e-12
        entropy_per_var = (-np.sum(probs_32x32 * np.log(np.clip(probs_32x32, eps, 1.0)), axis=-1)).tolist()
        
        # Compute KL per variable
        prior_probs_32x32 = sdata['prior_probs'].reshape(32, 32)
        kl_per_var = (np.sum(probs_32x32 * (np.log(np.clip(probs_32x32, eps, 1.0)) - np.log(np.clip(prior_probs_32x32, eps, 1.0))), axis=-1)).tolist()
        
        # Two-hot representation of reward
        reward_target_dist = two_hot.encode(rew)
        simulated_reward_logits = np.random.randn(two_hot.num_bins) * 0.1
        # Give higher logits near target bin for realistic visualization
        simulated_reward_logits += reward_target_dist * 2.0
        exp_reward_val, pred_reward_probs = two_hot.decode(simulated_reward_logits)
        ce_loss, ce_grad, _, _ = two_hot.loss_and_gradient(simulated_reward_logits, rew)
        
        # 2D projection of deterministic hidden state h_t
        h_2d = np.dot(h, pca_matrix).tolist()
        
        step_record = {
            "step": t,
            "regime": int(regime),
            "regime_name": regime_names.get(int(regime), "Unknown"),
            "action": [round(float(a), 4) for a in act],
            "observation": [round(float(o), 4) for o in next_obs],
            "pred_observation": [round(float(p), 4) for p in sdata['pred_obs']],
            "recon_mse": round(float(sdata['recon_loss']), 6),
            "total_kl": round(float(sdata['kl']), 4),
            "mean_entropy": round(float(sdata['entropy']) / 32.0, 4),
            "deterministic_state_2d": [round(float(coord), 4) for coord in h_2d],
            "stochastic_latent": {
                "active_categories": active_indices, # 32 integer indices in [0, 31]
                "entropy_per_variable": [round(float(e), 4) for e in entropy_per_var],
                "kl_per_variable": [round(float(k), 4) for k in kl_per_var],
                "probabilities_sample_var0": [round(float(p), 4) for p in probs_32x32[0]], # First variable distribution
                "probabilities_sample_var1": [round(float(p), 4) for p in probs_32x32[1]],
                "one_hot_matrix_sparsity": round(float(np.mean(one_hot_32x32)), 6) # Strictly 1/32 = 0.03125
            },
            "reward_dynamics": {
                "raw_reward": round(float(rew), 4),
                "accumulated_return": round(float(accumulated_return), 4),
                "percentile_normalized_return": round(float(norm_return), 4),
                "running_percentiles": {
                    "p5": round(float(normalizer.p_low), 4),
                    "p95": round(float(normalizer.p_high), 4),
                    "scale": round(float(normalizer.get_scale()), 4)
                },
                "two_hot_encoding": {
                    "target_active_bins": np.where(reward_target_dist > 0.0)[0].tolist(),
                    "target_weights": [round(float(w), 4) for w in reward_target_dist[reward_target_dist > 0.0]],
                    "expected_decoded_reward": round(float(exp_reward_val), 4),
                    "cross_entropy_loss": round(float(ce_loss), 4),
                    "max_gradient_norm": round(float(np.max(np.abs(ce_grad))), 4) # Strictly <= 1.0!
                }
            }
        }
        steps_data.append(step_record)
        
    # Serialize comprehensive JSON
    output_payload = {
        "metadata": {
            "title": "DreamerV3 Interactive 32x32 Discrete Latent & Two-Hot Explorer",
            "num_steps": num_steps,
            "latent_dimensions": "32 categorical variables x 32 classes = 1024 flat units",
            "reward_two_hot_bins": two_hot.num_bins,
            "symlog_range": [two_hot.v_min, two_hot.v_max]
        },
        "two_hot_bin_centers": [round(float(b), 4) for b in two_hot.bin_centers],
        "trajectory": steps_data
    }
    
    json_path = os.path.join(OUTPUT_DIR, "latent_step_visualization.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2)
    print(f"\n[+] Successfully exported interactive latent visualization dataset: {json_path}")
    
    # ---------------------------------------------------------------------------
    # Numerical Demonstration: Two-Hot Bounded Gradients vs MSE Explosions
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print(">>> NUMERICAL STABILITY PROOF: Two-Hot Cross Entropy vs Linear MSE")
    print("=" * 70)
    print(f"{'Target Scalar (y)':^18} | {'Linear MSE Grad':^18} | {'Two-Hot CE Max Grad':^22} | {'Bounded?':^10}")
    print("-" * 75)
    test_scalars = [0.01, 1.0, 10.0, 100.0, 1000.0, 10000.0]
    for y_test in test_scalars:
        # Prediction with standard initialization bias (e.g. 0.0)
        mse_grad = 0.0 - y_test # d(0.5*(y_hat - y)^2)/dy_hat = -y_test
        logits_init = np.zeros(two_hot.num_bins)
        _, ce_g, _, _ = two_hot.loss_and_gradient(logits_init, y_test)
        max_ce_g = float(np.max(np.abs(ce_g)))
        bounded_str = "YES (<=1.0)" if max_ce_g <= 1.0 else "NO"
        print(f"{y_test:^18.2f} | {abs(mse_grad):^18.2f} | {max_ce_g:^22.4f} | {bounded_str:^10}")
        
    print("=" * 75)
    return output_payload

if __name__ == "__main__":
    run_latent_exploration(num_steps=30, seed=42)
