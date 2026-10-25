"""
Cross-Embodiment Foundation World Models Benchmark
=================================================
Systematic evaluation of Foundation World Models across multi-embodiment physical domains:
1. Quadruped Robot (四足机器狗): Ground contact, foot-fall momentum, periodic gait
2. 7-DoF Manipulator Arm (7-DoF 机械臂): 3D reaching kinematics, object manipulation
3. Quadrotor UAV (四旋翼无人机): 3D aerial aerodynamics, turbulent wind drift

Pre-training & Zero-Shot Transfer Protocols:
- Anchor Pre-training across diverse multi-embodiment physical interaction data.
- Zero-Shot transfer to held-out, out-of-distribution physical dynamic regimes:
  * Held-Out Domain 1: Heavy-Load High-Inertia Manipulator (Kinematic payload shift)
  * Held-Out Domain 2: High-Turbulence Dynamic Quadrotor (Extreme aerodynamic shear)
  * Held-Out Domain 3: Low-Friction Slip Quadruped (Contact slip dynamics)

Compares:
1. Reconstruction Foundation Model (VAE-RSSM)
2. Task-Specific Value-Equivalent Model (MuZero)
3. Foundation JEPA (V-JEPA / Spatiotemporal Feature World Model)
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

from nn_core import Linear, LayerNorm, ReLU, Tanh, Sequential, Adam, mse_loss
from models import ReconstructionWM, ValueEquivalentWM, JepaWM


# ==============================================================================
# 1. Multi-Embodiment Physics & Vision Sandbox
# ==============================================================================

class PhysicalEmbodimentEnv:
    def __init__(self, embodiment="quadruped", dynamic_shift=False, noise_ratio=0.30, seed=42):
        """
        dynamic_shift: If True, activates out-of-distribution physical parameters
                       (e.g., 2.5x mass inertia, turbulent wind shear, surface slip).
        """
        self.embodiment = embodiment.lower()
        self.dynamic_shift = dynamic_shift
        self.noise_ratio = noise_ratio
        self.rng = np.random.RandomState(seed)
        self.grid_size = 16
        self.action_dim = 5
        self.reset()

    def reset(self, seed=None):
        if seed is not None:
            self.rng = np.random.RandomState(seed)
        self.step_count = 0
        self.max_steps = 50

        if self.embodiment == "quadruped":
            # State: [x, y, vx, vy, cos(theta), sin(theta)]
            self.pos = self.rng.uniform(-0.5, 0.5, size=2).astype(np.float32)
            self.vel = np.zeros(2, dtype=np.float32)
            self.theta = float(self.rng.uniform(-np.pi, np.pi))
            self.target = self.rng.uniform(-0.7, 0.7, size=2).astype(np.float32)
            # Physical friction parameter
            self.friction = 0.50 if self.dynamic_shift else 0.82

        elif self.embodiment == "manipulator":
            # State: [ee_x, ee_y, ee_z, vx, vy, vz]
            self.ee_pos = np.array([0.0, 0.0, 0.4], dtype=np.float32)
            self.ee_vel = np.zeros(3, dtype=np.float32)
            self.target = self.rng.uniform(-0.6, 0.6, size=3).astype(np.float32)
            self.target[2] = self.rng.uniform(0.2, 0.7)
            # Physical inertia parameter (heavy payload causes sluggish response)
            self.inertia_damping = 0.55 if self.dynamic_shift else 0.80

        elif self.embodiment == "quadrotor":
            # State: [x, y, z, vx, vy, vz]
            self.pos = self.rng.uniform(-0.4, 0.4, size=3).astype(np.float32)
            self.pos[2] = 0.5
            self.vel = np.zeros(3, dtype=np.float32)
            self.target = self.rng.uniform(-0.6, 0.6, size=3).astype(np.float32)
            self.target[2] = self.rng.uniform(0.3, 0.8)
            # Physical turbulence multiplier
            self.wind_strength = 0.25 if self.dynamic_shift else 0.05

        return self._render_obs(), self.get_true_state()

    def get_true_state(self):
        """Returns normalized 6-dim physical state."""
        if self.embodiment == "quadruped":
            return np.concatenate([self.pos, self.vel, [np.cos(self.theta), np.sin(self.theta)]]).astype(np.float32)
        elif self.embodiment == "manipulator":
            return np.concatenate([self.ee_pos, self.ee_vel]).astype(np.float32)
        elif self.embodiment == "quadrotor":
            return np.concatenate([self.pos, self.vel]).astype(np.float32)

    def step(self, action):
        self.step_count += 1

        if self.embodiment == "quadruped":
            # Discrete gait commands
            accel = np.zeros(2, dtype=np.float32)
            if action == 0: accel = 0.12 * np.array([np.cos(self.theta), np.sin(self.theta)])
            elif action == 1: accel = 0.22 * np.array([np.cos(self.theta), np.sin(self.theta)])
            elif action == 2: self.theta += 0.25
            elif action == 3: self.theta -= 0.25
            elif action == 4: self.vel *= 0.5
            self.vel = self.friction * self.vel + accel
            self.pos = np.clip(self.pos + self.vel, -1.0, 1.0)
            dist = float(np.linalg.norm(self.pos - self.target))
            reward = -dist + (1.5 if dist < 0.25 else 0.0)

        elif self.embodiment == "manipulator":
            # Cartesian delta commands
            delta = np.zeros(3, dtype=np.float32)
            if action == 0: delta[0] = 0.12
            elif action == 1: delta[0] = -0.12
            elif action == 2: delta[1] = 0.12
            elif action == 3: delta[1] = -0.12
            elif action == 4: delta[2] = 0.10 if self.ee_pos[2] < self.target[2] else -0.10
            self.ee_vel = self.inertia_damping * self.ee_vel + delta
            self.ee_pos = np.clip(self.ee_pos + self.ee_vel, -1.0, 1.0)
            dist = float(np.linalg.norm(self.ee_pos - self.target))
            reward = -dist + (2.0 if dist < 0.20 else 0.0)

        elif self.embodiment == "quadrotor":
            thrust = np.zeros(3, dtype=np.float32)
            if action == 0: thrust[2] = 0.18
            elif action == 1: thrust[2] = -0.18
            elif action == 2: thrust[:2] = [0.12, 0.0]
            elif action == 3: thrust[:2] = [-0.10, 0.10]
            elif action == 4: thrust[:2] = [0.10, -0.10]
            wind_perturb = self.rng.normal(0, self.wind_strength, size=3).astype(np.float32)
            self.vel = 0.82 * self.vel + thrust + wind_perturb
            self.pos = np.clip(self.pos + self.vel, -1.0, 1.0)
            dist = float(np.linalg.norm(self.pos - self.target))
            reward = -dist + (1.8 if dist < 0.25 else 0.0)

        done = (self.step_count >= self.max_steps)
        info = {"dist": dist, "true_state": self.get_true_state()}
        return self._render_obs(), reward, done, info

    def _render_obs(self):
        """Renders 16x16 visual image with core geometry + noise."""
        H = W = self.grid_size
        xs = np.linspace(-1.0, 1.0, W)
        ys = np.linspace(1.0, -1.0, H)
        gx, gy = np.meshgrid(xs, ys)

        canvas = np.zeros((H, W), dtype=np.float32)

        if self.embodiment == "quadruped":
            # Grid + robot body + target
            grid = 0.15 * (np.sin(gx * 8) > 0.8).astype(np.float32)
            d_rob = (gx - self.pos[0])**2 + (gy - self.pos[1])**2
            rob = 0.9 * np.exp(-d_rob / (2.0 * (0.22**2)))
            d_tgt = (gx - self.target[0])**2 + (gy - self.target[1])**2
            tgt = 0.5 * np.exp(-d_tgt / (2.0 * (0.16**2)))
            canvas = grid + rob + tgt

        elif self.embodiment == "manipulator":
            # Workspace boundary + arm line + EE blob + object target
            table = 0.20 * ((gx > -0.7) & (gx < 0.7) & (gy > -0.7) & (gy < 0.7)).astype(np.float32)
            d_ee = (gx - self.ee_pos[0])**2 + (gy - self.ee_pos[1])**2
            ee = 0.95 * np.exp(-d_ee / (2.0 * (0.20**2)))
            d_tgt = (gx - self.target[0])**2 + (gy - self.target[1])**2
            tgt = 0.6 * np.exp(-d_tgt / (2.0 * (0.15**2)))
            canvas = table + ee + tgt

        elif self.embodiment == "quadrotor":
            # Horizon line + drone blob + waypoint target
            horizon = 0.25 * np.exp(-(gy - 0.2 * self.pos[2])**2 / 0.1)
            d_drone = (gx - self.pos[0])**2 + (gy - self.pos[1])**2
            drone = 0.85 * np.exp(-d_drone / (2.0 * (0.18**2)))
            d_wpt = (gx - self.target[0])**2 + (gy - self.target[1])**2
            wpt = 0.55 * np.exp(-d_wpt / (2.0 * (0.15**2)))
            canvas = horizon + drone + wpt

        # Distractor noise
        white_noise = self.rng.uniform(0.0, 1.0, size=(H, W)).astype(np.float32)
        obs = (1.0 - self.noise_ratio) * np.clip(canvas, 0.0, 1.0) + self.noise_ratio * white_noise
        return obs.flatten().astype(np.float32)


# ==============================================================================
# 2. Data Collection and Robust Ridge Probe Evaluator
# ==============================================================================

def collect_transitions(env, num_steps=600):
    obs_list, act_list, rew_list, nobs_list, state_list = [], [], [], [], []
    obs, state = env.reset()
    for _ in range(num_steps):
        act = np.random.randint(0, env.action_dim)
        nobs, rew, done, info = env.step(act)
        obs_list.append(obs)
        act_list.append(act)
        rew_list.append(rew)
        nobs_list.append(nobs)
        state_list.append(info["true_state"])
        if done:
            obs, state = env.reset()
        else:
            obs = nobs
            state = info["true_state"]

    rewards = np.array(rew_list, dtype=np.float32)
    gamma = 0.95
    returns = np.zeros_like(rewards)
    running = 0.0
    for t in reversed(range(len(rewards))):
        running = rewards[t] + gamma * running
        returns[t] = running

    return {
        "obs": np.array(obs_list, dtype=np.float32),
        "actions": np.array(act_list, dtype=np.int32),
        "rewards": rewards,
        "next_obs": np.array(nobs_list, dtype=np.float32),
        "values": returns,
        "next_values": np.roll(returns, -1),
        "states": np.array(state_list, dtype=np.float32)
    }


def normalized_ridge_probe(features_train, targets_train, features_test, targets_test, alpha=1.0):
    """
    Standardizes features and fits ridge regression with adaptive regularizer.
    Returns test R^2 score.
    """
    # Feature standardization
    mean_feat = np.mean(features_train, axis=0, keepdims=True)
    std_feat = np.std(features_train, axis=0, keepdims=True) + 1e-5
    X_tr_norm = (features_train - mean_feat) / std_feat
    X_te_norm = (features_test - mean_feat) / std_feat

    N_tr = X_tr_norm.shape[0]
    X_tr = np.concatenate([X_tr_norm, np.ones((N_tr, 1), dtype=np.float32)], axis=-1)
    N_te = X_te_norm.shape[0]
    X_te = np.concatenate([X_te_norm, np.ones((N_te, 1), dtype=np.float32)], axis=-1)

    Y_tr = targets_train[:, None] if targets_train.ndim == 1 else targets_train
    Y_te = targets_test[:, None] if targets_test.ndim == 1 else targets_test

    D = X_tr.shape[1]
    reg = alpha * np.eye(D, dtype=np.float32)
    reg[-1, -1] = 0.0 # do not penalize bias

    try:
        W = np.linalg.solve(X_tr.T @ X_tr + reg, X_tr.T @ Y_tr)
        Y_pred = X_te @ W
        var_y = np.var(Y_te, axis=0) + 1e-8
        mse_y = np.mean((Y_te - Y_pred) ** 2, axis=0)
        r2 = np.maximum(0.0, 1.0 - (mse_y / var_y))
        return float(np.mean(r2))
    except Exception:
        return 0.0


# ==============================================================================
# 3. Benchmark Pipeline Execution
# ==============================================================================

def run_foundation_generalization_benchmark():
    print("================================================================================")
    print("PHASE 3: CROSS-EMBODIMENT FOUNDATION WORLD MODELS GENERALIZATION BENCHMARK")
    print("================================================================================")

    # 1. Foundation Pre-training across Multi-Embodiment Mixture
    print("\n1. Pre-training Foundation Models on Diverse Multi-Embodiment Base (Quadruped + Arm)...")
    env_quad = PhysicalEmbodimentEnv("quadruped", dynamic_shift=False, seed=42)
    env_arm = PhysicalEmbodimentEnv("manipulator", dynamic_shift=False, seed=43)

    data_quad = collect_transitions(env_quad, num_steps=600)
    data_arm = collect_transitions(env_arm, num_steps=600)

    # Combined Foundation Pretraining Dataset
    foundation_obs = np.concatenate([data_quad["obs"], data_arm["obs"]], axis=0)
    foundation_act = np.concatenate([data_quad["actions"], data_arm["actions"]], axis=0)
    foundation_rew = np.concatenate([data_quad["rewards"], data_arm["rewards"]], axis=0)
    foundation_nobs = np.concatenate([data_quad["next_obs"], data_arm["next_obs"]], axis=0)
    foundation_val = np.concatenate([data_quad["values"], data_arm["values"]], axis=0)
    foundation_nval = np.concatenate([data_quad["next_values"], data_arm["next_values"]], axis=0)

    obs_dim = 256
    latent_dim = 32
    action_dim = 5
    batch_size = 32
    num_epochs = 100

    # Instantiate the 3 Paradigms
    model_recon = ReconstructionWM(obs_dim=obs_dim, latent_dim=latent_dim, action_dim=action_dim, lr=2e-3)
    model_muzero = ValueEquivalentWM(obs_dim=obs_dim, latent_dim=latent_dim, action_dim=action_dim, lr=2e-3)
    model_jepa = JepaWM(obs_dim=obs_dim, latent_dim=latent_dim, action_dim=action_dim, lr=2e-3, ema_tau=0.98)

    t0 = time.time()
    N = len(foundation_obs)
    steps = N // batch_size
    for ep in range(num_epochs):
        perm = np.random.permutation(N)
        for s in range(steps):
            idx = perm[s * batch_size:(s + 1) * batch_size]
            b_obs = foundation_obs[idx]
            b_act = foundation_act[idx]
            b_rew = foundation_rew[idx]
            b_nobs = foundation_nobs[idx]
            b_val = foundation_val[idx]
            b_nval = foundation_nval[idx]

            model_recon.train_step(b_obs, b_act, b_rew, b_nobs)
            model_muzero.train_step(b_obs, b_act, b_rew, b_nobs, b_val, b_nval, b_act)
            model_jepa.train_step(b_obs, b_act, b_rew, b_nobs)

    pretrain_time = time.time() - t0
    print(f"Foundation Pre-training completed in {pretrain_time:.2f} seconds.")

    # 2. Benchmark Source Test Set (Quadruped Base)
    test_quad = collect_transitions(env_quad, num_steps=300)
    source_r2 = {
        "Reconstruction": normalized_ridge_probe(model_recon.encode(data_quad["obs"]), data_quad["states"],
                                                 model_recon.encode(test_quad["obs"]), test_quad["states"]),
        "Pure_MuZero": normalized_ridge_probe(model_muzero.encode(data_quad["obs"]), data_quad["states"],
                                              model_muzero.encode(test_quad["obs"]), test_quad["states"]),
        "Foundation_JEPA": normalized_ridge_probe(model_jepa.encode(data_quad["obs"]), data_quad["states"],
                                                  model_jepa.encode(test_quad["obs"]), test_quad["states"])
    }
    print("\nSource In-Distribution Baseline Probe R^2:")
    for k, v in source_r2.items():
        print(f"  * {k:18s}: {v:.3f}")

    # --------------------------------------------------------------------------
    # 3. Zero-Shot Transfer to Held-Out OOD Dynamic Regimes
    # --------------------------------------------------------------------------
    print("\n2. Evaluating Zero-Shot Generalization to Out-of-Distribution Dynamics...")
    held_out_domains = {
        "heavy_payload_arm": PhysicalEmbodimentEnv("manipulator", dynamic_shift=True, seed=888),
        "turbulent_drone": PhysicalEmbodimentEnv("quadrotor", dynamic_shift=True, seed=999),
        "slippery_quadruped": PhysicalEmbodimentEnv("quadruped", dynamic_shift=True, seed=777)
    }

    zero_shot_results = {}
    transfer_ratios = {}
    target_datasets = {}

    for domain_name, d_env in held_out_domains.items():
        d_train = collect_transitions(d_env, num_steps=500)
        d_test = collect_transitions(d_env, num_steps=300)
        target_datasets[domain_name] = (d_train, d_test)

        zs_r2 = {}
        for name, m in [("Reconstruction", model_recon), ("Pure_MuZero", model_muzero), ("Foundation_JEPA", model_jepa)]:
            f_tr = m.encode(d_train["obs"][:150]) # frozen feature probe
            f_te = m.encode(d_test["obs"])
            r2 = normalized_ridge_probe(f_tr, d_train["states"][:150], f_te, d_test["states"], alpha=1.0)
            zs_r2[name] = r2

        zero_shot_results[domain_name] = zs_r2
        transfer_ratios[domain_name] = {
            m_name: float(zs_r2[m_name] / max(0.01, source_r2[m_name])) for m_name in zs_r2
        }
        print(f"\n--- Held-Out Domain: [{domain_name.upper()}] ---")
        for m_name, val in zs_r2.items():
            print(f"  {m_name:18s} | Zero-Shot R^2: {val:.3f} | Transfer Retention: {transfer_ratios[domain_name][m_name]*100:.1f}%")

    # --------------------------------------------------------------------------
    # 4. Few-Shot Adaptation Curve on Turbulent Drone (Unseen Aerodynamic Dynamics)
    # --------------------------------------------------------------------------
    print("\n3. Testing Few-Shot Adaptation on Unseen Aerodynamic Quadrotor...")
    k_samples = [15, 30, 60, 120, 240]
    drone_train, drone_test = target_datasets["turbulent_drone"]
    few_shot_curves = {"k_samples": k_samples, "Reconstruction": [], "Pure_MuZero": [], "Foundation_JEPA": []}

    for k in k_samples:
        for name, m in [("Reconstruction", model_recon), ("Pure_MuZero", model_muzero), ("Foundation_JEPA", model_jepa)]:
            f_tr = m.encode(drone_train["obs"][:k])
            f_te = m.encode(drone_test["obs"])
            r2_k = normalized_ridge_probe(f_tr, drone_train["states"][:k], f_te, drone_test["states"], alpha=1.0)
            few_shot_curves[name].append(r2_k)

    # --------------------------------------------------------------------------
    # 5. Latent Space Effective Rank & Invariance Preservation
    # --------------------------------------------------------------------------
    drone_latents = {
        "Reconstruction": model_recon.encode(drone_test["obs"]),
        "Pure_MuZero": model_muzero.encode(drone_test["obs"]),
        "Foundation_JEPA": model_jepa.encode(drone_test["obs"])
    }
    latent_ranks = {}
    for name, lat in drone_latents.items():
        Z = lat - np.mean(lat, axis=0, keepdims=True)
        _, s_vals, _ = np.linalg.svd(Z, full_matrices=False)
        p = s_vals / (np.sum(s_vals) + 1e-12)
        eff_rank = float(np.exp(-np.sum(p * np.log(p + 1e-12))))
        latent_ranks[name] = eff_rank
        print(f"  Latent Effective Rank on Drone | {name:18s}: {eff_rank:.2f}")

    benchmark_summary = {
        "source_baseline_r2": source_r2,
        "zero_shot_generalization": zero_shot_results,
        "transfer_retention_ratios": transfer_ratios,
        "few_shot_adaptation_curves": few_shot_curves,
        "latent_effective_ranks": latent_ranks,
        "pretraining_time_sec": pretrain_time
    }

    # Save to JSON
    json_path = os.path.join(curr_dir, "open_world_generalization_metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_summary, f, indent=2, ensure_ascii=False)
    print(f"\nPhase 3 metrics successfully written to: {json_path}")

    # Generate Publication-Grade Visualizations
    generate_phase3_visualizations(benchmark_summary)


def generate_phase3_visualizations(metrics):
    """Generates the two required publication figures for Phase 3."""
    plt.style.use('default')
    plt.rcParams['font.family'] = 'DejaVu Sans'

    colors = {
        "Reconstruction": "#E63946",   # Red
        "Pure_MuZero": "#E76F51",      # Coral / Orange
        "Foundation_JEPA": "#2A9D8F"   # Teal / Emerald
    }
    markers = {"Reconstruction": "o", "Pure_MuZero": "s", "Foundation_JEPA": "D"}
    model_labels = {
        "Reconstruction": "Reconstruction WM (VAE-RSSM)",
        "Pure_MuZero": "Task-Specific MuZero",
        "Foundation_JEPA": "Foundation JEPA (V-JEPA)"
    }

    # --------------------------------------------------------------------------
    # Figure 1: Zero-Shot Transfer & Few-Shot Adaptation (2-Panel)
    # --------------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), dpi=300)
    fig.suptitle("Cross-Embodiment Open-World Foundation Generalization Benchmark",
                 fontsize=13, fontweight='bold', y=0.98)

    # Panel A: Zero-Shot Transfer R^2 Across 3 Held-Out Dynamic Domains
    ax1 = axes[0]
    domains = ["heavy_payload_arm", "turbulent_drone", "slippery_quadruped"]
    domain_labels = ["Heavy-Payload\nManipulator", "Turbulent 3D\nQuadrotor", "Low-Friction Slip\nQuadruped"]
    x = np.arange(len(domains))
    width = 0.25

    rects1 = ax1.bar(x - width, [metrics["zero_shot_generalization"][d]["Reconstruction"] for d in domains],
                     width, label=model_labels["Reconstruction"], color=colors["Reconstruction"], alpha=0.9)
    rects2 = ax1.bar(x, [metrics["zero_shot_generalization"][d]["Pure_MuZero"] for d in domains],
                     width, label=model_labels["Pure_MuZero"], color=colors["Pure_MuZero"], alpha=0.9)
    rects3 = ax1.bar(x + width, [metrics["zero_shot_generalization"][d]["Foundation_JEPA"] for d in domains],
                     width, label=model_labels["Foundation_JEPA"], color=colors["Foundation_JEPA"], alpha=0.9)

    ax1.set_ylabel("Zero-Shot Test Probe R^2 Score", fontsize=10, fontweight='bold')
    ax1.set_title("A. Zero-Shot Representation Probe R^2 across Held-Out Domains", fontsize=11, fontweight='bold', pad=8)
    ax1.set_xticks(x)
    ax1.set_xticklabels(domain_labels, fontsize=10, fontweight='bold')
    ax1.set_ylim(0, 0.65)
    ax1.grid(axis='y', linestyle='--', alpha=0.6)
    ax1.legend(loc="upper right", framealpha=0.95, fontsize=9)

    for bar_group in [rects1, rects2, rects3]:
        for b in bar_group:
            h = b.get_height()
            ax1.annotate(f"{h:.3f}", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                         textcoords="offset points", ha='center', va='bottom', fontsize=8.5, fontweight='bold')

    # Panel B: Few-Shot Adaptation Learning Curve on Unseen Drone
    ax2 = axes[1]
    k_vals = metrics["few_shot_adaptation_curves"]["k_samples"]
    for m in ["Reconstruction", "Pure_MuZero", "Foundation_JEPA"]:
        ax2.plot(k_vals, metrics["few_shot_adaptation_curves"][m], marker=markers[m], color=colors[m],
                 label=model_labels[m], linewidth=2.4, markersize=7)
    ax2.set_title("B. Few-Shot Adaptation Curve on Unseen Turbulent Drone", fontsize=11, fontweight='bold', pad=8)
    ax2.set_xlabel("Number of Demonstration Samples (K)", fontsize=10, fontweight='bold')
    ax2.set_ylabel("Test State Probe R^2 Score", fontsize=10, fontweight='bold')
    ax2.set_ylim(-0.02, 0.65)
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.legend(loc="lower right", framealpha=0.95, fontsize=9.5)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    adapt_path = os.path.join(curr_dir, "zero_shot_dynamics_adaptation.png")
    plt.savefig(adapt_path, dpi=300)
    plt.close()
    print(f"Saved: {adapt_path}")

    # --------------------------------------------------------------------------
    # Figure 2: Cross-Embodiment Transfer Radar Chart
    # --------------------------------------------------------------------------
    categories = [
        "In-Distribution Retention\n(Base Anchor R^2)",
        "Zero-Shot Arm Transfer\n(Heavy-Payload Manipulator)",
        "Zero-Shot Drone Transfer\n(Turbulent Quadrotor)",
        "Zero-Shot Quadruped Transfer\n(Low-Friction Slip)",
        "Few-Shot Sample Efficiency\n(R^2 at K=60)",
        "Latent Manifold Rank\n(Anti-Collapse Health)"
    ]
    N_cat = len(categories)
    angles = [n / float(N_cat) * 2 * np.pi for n in range(N_cat)]
    angles += angles[:1]

    radar_scores = {
        "Reconstruction": [
            metrics["source_baseline_r2"]["Reconstruction"] * 100,                                 # In-dist
            metrics["zero_shot_generalization"]["heavy_payload_arm"]["Reconstruction"] * 100,      # Arm
            metrics["zero_shot_generalization"]["turbulent_drone"]["Reconstruction"] * 100,        # Drone
            metrics["zero_shot_generalization"]["slippery_quadruped"]["Reconstruction"] * 100,     # Slip
            metrics["few_shot_adaptation_curves"]["Reconstruction"][2] * 100,                      # Few-shot
            (metrics["latent_effective_ranks"]["Reconstruction"] / 32.0) * 100                     # Rank
        ],
        "Pure_MuZero": [
            metrics["source_baseline_r2"]["Pure_MuZero"] * 100,                                    # In-dist
            metrics["zero_shot_generalization"]["heavy_payload_arm"]["Pure_MuZero"] * 100,         # Arm
            metrics["zero_shot_generalization"]["turbulent_drone"]["Pure_MuZero"] * 100,           # Drone
            metrics["zero_shot_generalization"]["slippery_quadruped"]["Pure_MuZero"] * 100,        # Slip
            metrics["few_shot_adaptation_curves"]["Pure_MuZero"][2] * 100,                         # Few-shot
            (metrics["latent_effective_ranks"]["Pure_MuZero"] / 32.0) * 100                        # Rank
        ],
        "Foundation_JEPA": [
            metrics["source_baseline_r2"]["Foundation_JEPA"] * 100,                                 # In-dist
            metrics["zero_shot_generalization"]["heavy_payload_arm"]["Foundation_JEPA"] * 100,     # Arm
            metrics["zero_shot_generalization"]["turbulent_drone"]["Foundation_JEPA"] * 100,       # Drone
            metrics["zero_shot_generalization"]["slippery_quadruped"]["Foundation_JEPA"] * 100,    # Slip
            metrics["few_shot_adaptation_curves"]["Foundation_JEPA"][2] * 100,                     # Few-shot
            (metrics["latent_effective_ranks"]["Foundation_JEPA"] / 32.0) * 100                    # Rank
        ]
    }

    fig, ax = plt.subplots(figsize=(8.5, 8.5), subplot_kw=dict(polar=True), dpi=300)
    plt.title("Cross-Embodiment Foundation Model Generalization Radar",
              fontsize=13, fontweight='bold', pad=28)

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    plt.xticks(angles[:-1], categories, fontsize=9.5, fontweight='bold')

    ax.set_rscale('linear')
    ax.set_rlabel_position(0)
    plt.yticks([20, 40, 60, 80, 100], ["20", "40", "60", "80", "100"], color="grey", size=8.5)
    plt.ylim(0, 105)

    for m in ["Reconstruction", "Pure_MuZero", "Foundation_JEPA"]:
        vals = radar_scores[m]
        vals_closed = vals + vals[:1]
        ax.plot(angles, vals_closed, linewidth=2.4, linestyle='solid', color=colors[m], label=model_labels[m])
        ax.fill(angles, vals_closed, color=colors[m], alpha=0.18)

    plt.legend(loc='upper right', bbox_to_anchor=(1.35, 1.12), framealpha=0.95, fontsize=9.5)
    plt.tight_layout()

    radar_path = os.path.join(curr_dir, "cross_embodiment_transfer_radar.png")
    plt.savefig(radar_path, dpi=300)
    plt.close()
    print(f"Saved: {radar_path}")


if __name__ == "__main__":
    run_foundation_generalization_benchmark()
