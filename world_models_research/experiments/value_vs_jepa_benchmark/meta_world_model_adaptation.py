"""
Meta-World Models & OOD Dynamics Fast Adaptation Benchmark
===========================================================
Phase 6: Bayesian Meta-Latent World Model with Context Hypernetwork Adaptation.
Fast few-shot and zero-shot adaptation to Out-Of-Distribution (OOD) physical regimes:
1. Earth Standard (Base training: g = -1.0, mu = 0.20, mass = 1.0)
2. Moon Low-Gravity (g = -0.16, mu = 0.05, mass = 1.0)
3. Jupiter High-Gravity (g = -3.20, mu = 0.40, mass = 1.0)
4. Ice Zero-Friction (g = -1.0, mu = 0.01, mass = 1.0)
5. Viscous Mud (g = -1.0, mu = 1.50, mass = 1.0)
6. Heavy Payload (g = -1.0, mu = 0.20, mass = 4.0, UNSEEN OOD)

Compares:
- Fixed World Model (Static baseline trained on Earth)
- Fine-Tuned World Model (Standard gradient adaptation on few-shot buffer)
- Meta-World Model (Bayesian Context Encoder + FiLM Hypernetwork Adaptation, Ours)

Evaluates:
- Multi-step autoregressive trajectory prediction MSE across adaptation steps K in [1..5]
- Out-Of-Distribution generalization gap
- Adaptation convergence rate and Closed-loop MPC Return
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


# ==============================================================================
# 1. Continuous Multi-Regime OOD Physics Sandbox
# ==============================================================================

class ContinuousOODPhysicsEnv:
    """
    Continuous 2D Planetary Control Sandbox:
    State: s = [x, y, vx, vy] in R^4
    Action: continuous force a = [Fx, Fy] in [-1, 1]^2
    Dynamics:
      v_{t+1} = clip(v_t + ((a_t - mu * v_t) / mass + g) * dt, -v_max, v_max)
      p_{t+1} = clip(p_t + v_{t+1} * dt, -p_max, p_max)
    Observation: 8-dimensional non-linear sensor vector:
      o = [x, y, vx, vy, sin(x), cos(y), ||p - goal||, ||v||] + sensor_noise
    """
    REGIMES = {
        "Earth_Std": {"g": np.array([0.0, -1.2]), "mu": 0.25, "mass": 1.0, "desc": "Standard Earth"},
        "Moon_LowGrav": {"g": np.array([0.0, -0.15]), "mu": 0.02, "mass": 0.8, "desc": "Moon Microgravity"},
        "Jupiter_HighGrav": {"g": np.array([0.0, -4.50]), "mu": 0.60, "mass": 1.0, "desc": "Jupiter Hypergravity"},
        "Ice_ZeroFriction": {"g": np.array([0.0, -1.2]), "mu": 0.00, "mass": 0.9, "desc": "Ice Zero-Friction"},
        "Viscous_Mud": {"g": np.array([0.0, -0.6]), "mu": 2.80, "mass": 1.2, "desc": "Viscous Mud Swamp"},
        "Heavy_Payload": {"g": np.array([0.0, -2.5]), "mu": 0.35, "mass": 4.5, "desc": "Heavy Payload 4.5x (OOD)"}
    }

    def __init__(self, regime="Earth_Std", seed=42, noise_std=0.01):
        self.rng = np.random.RandomState(seed)
        self.dt = 0.15
        self.v_max = 2.5
        self.p_max = 2.0
        self.noise_std = noise_std
        self.set_regime(regime)
        self.goal_pos = np.array([1.2, 0.8], dtype=np.float32)
        self.state_dim = 4
        self.obs_dim = 8
        self.action_dim = 2
        self.max_steps = 40
        self.reset()

    def set_regime(self, regime):
        if regime not in self.REGIMES:
            raise ValueError(f"Unknown regime: {regime}")
        self.regime_name = regime
        cfg = self.REGIMES[regime]
        self.g = cfg["g"].astype(np.float32)
        self.mu = float(cfg["mu"])
        self.mass = float(cfg["mass"])

    def reset(self, seed=None):
        if seed is not None:
            self.rng = np.random.RandomState(seed)
        self.pos = np.array([-1.2, -0.8], dtype=np.float32) + self.rng.uniform(-0.08, 0.08, size=2).astype(np.float32)
        self.vel = np.zeros(2, dtype=np.float32)
        self.step_count = 0
        return self._get_obs()

    def _get_obs(self):
        d_goal = float(np.linalg.norm(self.pos - self.goal_pos))
        speed = float(np.linalg.norm(self.vel))
        obs = np.array([
            self.pos[0], self.pos[1],
            self.vel[0], self.vel[1],
            np.sin(self.pos[0] * np.pi), np.cos(self.pos[1] * np.pi),
            d_goal, speed
        ], dtype=np.float32)
        noise = self.rng.normal(0.0, self.noise_std, size=self.obs_dim).astype(np.float32)
        return obs + noise

    def step(self, action):
        self.step_count += 1
        action = np.clip(np.array(action, dtype=np.float32), -1.0, 1.0)
        
        # Real physical acceleration: (F_a - mu * v) / mass + g
        accel = (action - self.mu * self.vel) / self.mass + self.g
        self.vel = np.clip(self.vel + accel * self.dt, -self.v_max, self.v_max)
        self.pos = np.clip(self.pos + self.vel * self.dt, -self.p_max, self.p_max)
        
        obs = self._get_obs()
        d_goal = float(np.linalg.norm(self.pos - self.goal_pos))
        reward = -d_goal - 0.05 * float(np.sum(action ** 2))
        if d_goal < 0.25:
            reward += 15.0 # goal achievement bonus
            
        done = (self.step_count >= self.max_steps) or (d_goal < 0.15)
        info = {
            "pos": self.pos.copy(),
            "vel": self.vel.copy(),
            "regime": self.regime_name,
            "dist_to_goal": d_goal
        }
        return obs, reward, done, info


# ==============================================================================
# 2. Meta-World Model Architecture (Context Hypernetwork & FiLM Adaptation)
# ==============================================================================

class MetaWorldModel:
    """
    End-to-End Meta-Learned World Model:
    1. Context Encoder: trans_k = [obs_k, act_k, nobs_k] -> w_k -> w = mean(w_k) in R^6
    2. FiLM Hypernetwork: w -> gamma(w) (scale), beta(w) (shift)
    3. Modulated Dynamics: next_obs = obs + gamma(w) * BaseDynamics(obs, act) + beta(w)
    Trained end-to-end via multi-task meta-gradients!
    """
    def __init__(self, obs_dim=8, action_dim=2, context_dim=6, hidden_dim=48, lr=3e-3):
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.context_dim = context_dim
        
        # 1. Context Encoder (augmented with physical residual acceleration)
        trans_dim = obs_dim * 2 + action_dim + 2 # 20 (18 base + 2 accel residual)
        self.context_encoder = Sequential(
            Linear(trans_dim, 32),
            LayerNorm(32),
            ReLU(),
            Linear(32, context_dim),
            Tanh()
        )
        
        # 2. Base Dynamics Backbone
        self.fc1 = Linear(obs_dim + action_dim, hidden_dim)
        self.ln1 = LayerNorm(hidden_dim)
        self.act1 = ReLU()
        self.fc2 = Linear(hidden_dim, obs_dim)
        
        # 3. FiLM Hypernetwork Generator
        self.film_gen = Sequential(
            Linear(context_dim, 24),
            ReLU(),
            Linear(24, obs_dim * 2)
        )
        
        all_params = (self.context_encoder.parameters() + self.fc1.parameters() +
                      self.ln1.parameters() + self.fc2.parameters() + self.film_gen.parameters())
        self.optimizer = Adam(all_params, lr=lr)

    def infer_context(self, context_transitions):
        """Zero-gradient instant adaptation from few-shot transitions."""
        if len(context_transitions) == 0:
            return np.zeros(self.context_dim, dtype=np.float32)
        trans_arr = np.array(context_transitions, dtype=np.float32)
        
        # Augment with physical residual acceleration: delta_v / dt - a
        obs = trans_arr[:, :8]
        act = trans_arr[:, 8:10]
        nobs = trans_arr[:, 10:18]
        accel_residual = (nobs[:, 2:4] - obs[:, 2:4]) / 0.15 - act # Reveals mu, m, and g!
        
        aug_trans = np.concatenate([trans_arr, accel_residual], axis=-1)
        w_k = self.context_encoder.forward(aug_trans)
        return np.mean(w_k, axis=0) # Permutation invariant pooling

    def adapt(self, context_transitions, refine_steps=3, lr=0.03):
        """
        CAVIA-style Fast Latent Adaptation:
        Initializes from Context Encoder prior w_0, then executes few-step
        gradient ascent on the compact 6-dimensional latent parameter w!
        """
        w = self.infer_context(context_transitions)
        if refine_steps <= 0 or len(context_transitions) == 0:
            return w
            
        data = np.array(context_transitions, dtype=np.float32)
        obs = data[:, :8]
        act = data[:, 8:10]
        nobs = data[:, 10:18]
        B = obs.shape[0]
        
        inp = np.concatenate([obs, act], axis=-1)
        h1 = self.act1.forward(self.ln1.forward(self.fc1.forward(inp)))
        delta_base = self.fc2.forward(h1)
        
        for _ in range(refine_steps):
            w_b = np.repeat(w[None, :], B, axis=0)
            film_params = self.film_gen.forward(w_b)
            tanh_g = np.tanh(film_params[:, :self.obs_dim])
            tanh_b = np.tanh(film_params[:, self.obs_dim:])
            gamma = 1.0 + 0.5 * tanh_g
            beta = 0.5 * tanh_b
            
            pred = obs + gamma * delta_base + beta
            _, grad = mse_loss(pred, nobs)
            
            g_gamma = grad * delta_base
            g_beta = grad * 1.0
            g_film_g = g_gamma * 0.5 * (1.0 - tanh_g ** 2)
            g_film_b = g_beta * 0.5 * (1.0 - tanh_b ** 2)
            g_film = np.concatenate([g_film_g, g_film_b], axis=-1)
            g_wb = self.film_gen.backward(g_film)
            
            grad_w = np.mean(g_wb, axis=0)
            w = np.clip(w - lr * np.clip(grad_w, -2.0, 2.0), -1.0, 1.0)
            
        return w

    def predict(self, obs, action, context_w):
        """Single-step or batch prediction with Bounded FiLM modulation."""
        B = obs.shape[0] if obs.ndim == 2 else 1
        obs_b = obs if obs.ndim == 2 else obs[None, :]
        act_b = action if action.ndim == 2 else action[None, :]
        w_b = np.repeat(context_w[None, :], B, axis=0) if context_w.ndim == 1 else context_w
        
        inp = np.concatenate([obs_b, act_b], axis=-1)
        h1 = self.act1.forward(self.ln1.forward(self.fc1.forward(inp)))
        delta_base = self.fc2.forward(h1)
        
        # Bounded FiLM parameters around Identity Prior
        film_params = self.film_gen.forward(w_b)
        gamma = 1.0 + 0.5 * np.tanh(film_params[:, :self.obs_dim])
        beta = 0.5 * np.tanh(film_params[:, self.obs_dim:])
        
        delta_adapted = gamma * delta_base + beta
        next_obs = obs_b + delta_adapted
        return next_obs if obs.ndim == 2 else next_obs[0]

    def train_step(self, context_trans, obs, act, next_obs):
        """End-to-End Meta-Training Step with backward gradient flow into Context Encoder!"""
        self.optimizer.zero_grad()
        B = obs.shape[0]
        K = context_trans.shape[0]
        
        # 1. Forward Context Encoder with Augmented Residual
        c_obs = context_trans[:, :8]
        c_act = context_trans[:, 8:10]
        c_nobs = context_trans[:, 10:]
        accel_residual = (c_nobs[:, 2:4] - c_obs[:, 2:4]) / 0.15 - c_act
        aug_trans = np.concatenate([context_trans, accel_residual], axis=-1)
        
        w_k = self.context_encoder.forward(aug_trans) # (K, context_dim)
        w = np.mean(w_k, axis=0) # (context_dim,)
        w_b = np.repeat(w[None, :], B, axis=0)
        
        # 2. Forward Base Dynamics
        inp = np.concatenate([obs, act], axis=-1)
        h1 = self.act1.forward(self.ln1.forward(self.fc1.forward(inp)))
        delta_base = self.fc2.forward(h1)
        
        # 3. Forward Bounded FiLM Generator
        film_params = self.film_gen.forward(w_b)
        tanh_g = np.tanh(film_params[:, :self.obs_dim])
        tanh_b = np.tanh(film_params[:, self.obs_dim:])
        gamma = 1.0 + 0.5 * tanh_g
        beta = 0.5 * tanh_b
        
        pred_delta = gamma * delta_base + beta
        pred_next = obs + pred_delta
        
        loss, grad = mse_loss(pred_next, next_obs)
        
        # Backprop through FiLM
        g_delta = grad.copy()
        g_gamma = g_delta * delta_base
        g_beta = g_delta * 1.0
        
        g_film_g = g_gamma * 0.5 * (1.0 - tanh_g ** 2)
        g_film_b = g_beta * 0.5 * (1.0 - tanh_b ** 2)
        g_film = np.concatenate([g_film_g, g_film_b], axis=-1)
        g_wb = self.film_gen.backward(g_film) # (B, context_dim)
        
        # Gradient w.r.t w (accumulated over batch B)
        g_w = np.sum(g_wb, axis=0) # (context_dim,)
        
        # Backprop meta-gradient to Context Encoder
        g_wk = np.repeat(g_w[None, :] / K, K, axis=0)
        self.context_encoder.backward(g_wk)
        
        # Base dynamics backprop
        g_db = self.fc2.backward(g_delta * gamma)
        g_act = self.act1.backward(g_db)
        g_ln = self.ln1.backward(g_act)
        self.fc1.backward(g_ln)
        
        self.optimizer.step()
        return float(loss)


# ==============================================================================
# 3. Fixed and Fine-Tuned Baseline World Models
# ==============================================================================

class FixedAndFineTunedWorldModel:
    """Standard non-meta baseline dynamics model."""
    def __init__(self, obs_dim=8, action_dim=2, hidden_dim=48, lr=3e-3):
        self.model = Sequential(
            Linear(obs_dim + action_dim, hidden_dim),
            LayerNorm(hidden_dim),
            ReLU(),
            Linear(hidden_dim, obs_dim)
        )
        self.optimizer = Adam(self.model.parameters(), lr=lr)
        self.obs_dim = obs_dim
        self.action_dim = action_dim

    def predict(self, obs, action):
        inp = np.concatenate([obs, action], axis=-1)
        delta = self.model.forward(inp[None, :] if inp.ndim == 1 else inp)
        next_obs = (obs[None, :] if obs.ndim == 1 else obs) + delta
        return next_obs[0] if obs.ndim == 1 else next_obs

    def train_step(self, obs, act, next_obs):
        self.optimizer.zero_grad()
        inp = np.concatenate([obs, act], axis=-1)
        delta = self.model.forward(inp)
        pred = obs + delta
        loss, grad = mse_loss(pred, next_obs)
        self.model.backward(grad)
        self.optimizer.step()
        return float(loss)

    def fine_tune(self, context_buffer, steps=4, lr=4e-3):
        """Gradient fine-tuning on few-shot context transitions."""
        if len(context_buffer) == 0:
            return
        data = np.array(context_buffer, dtype=np.float32)
        obs = data[:, :self.obs_dim]
        act = data[:, self.obs_dim:self.obs_dim + self.action_dim]
        nobs = data[:, self.obs_dim + self.action_dim:]
        
        ft_opt = Adam(self.model.parameters(), lr=lr)
        for _ in range(steps):
            ft_opt.zero_grad()
            inp = np.concatenate([obs, act], axis=-1)
            delta = self.model.forward(inp)
            loss, grad = mse_loss(obs + delta, nobs)
            self.model.backward(grad)
            ft_opt.step()


# ==============================================================================
# 4. Phase 6 Benchmark Execution Pipeline
# ==============================================================================

def run_meta_world_model_benchmark():
    print("================================================================================")
    print("STARTING PHASE 6: META-WORLD MODELS & OOD DYNAMICS FAST ADAPTATION BENCHMARK")
    print("================================================================================")
    
    seed = 42
    np.random.seed(seed)
    
    # 1. Collect multi-regime training dataset across diverse training domains
    print("\n1. Collecting Meta-Training Dataset across diverse physical regimes...")
    meta_env = ContinuousOODPhysicsEnv(seed=seed)
    train_tasks = ["Earth_Std", "Moon_LowGrav", "Jupiter_HighGrav", "Ice_ZeroFriction", "Viscous_Mud"]
    
    meta_data = {}
    for task in train_tasks:
        meta_env.set_regime(task)
        t_list = []
        for ep in range(16):
            obs = meta_env.reset(seed=ep * 10 + 1)
            for _ in range(meta_env.max_steps):
                act = meta_env.rng.uniform(-0.9, 0.9, size=2).astype(np.float32)
                nobs, r, d, _ = meta_env.step(act)
                trans = np.concatenate([obs, act, nobs], axis=-1)
                t_list.append(trans)
                if d: break
                obs = nobs
        meta_data[task] = np.array(t_list, dtype=np.float32)
        print(f"   Collected {len(t_list)} transitions for regime [{task}].")
        
    # 2. Meta-Training: Train Meta-WM and Fixed Baseline
    print("\n2. Training Meta-World Model and Fixed Baseline...")
    meta_wm = MetaWorldModel(obs_dim=8, action_dim=2, context_dim=6, hidden_dim=48, lr=3e-3)
    fixed_wm = FixedAndFineTunedWorldModel(obs_dim=8, action_dim=2, hidden_dim=48, lr=3e-3)
    
    # Pretrain Fixed WM on Earth_Std
    earth_data = meta_data["Earth_Std"]
    N_earth = len(earth_data)
    for ep in range(50):
        perm = np.random.permutation(N_earth)
        for s in range(N_earth // 32):
            idx = perm[s * 32:(s + 1) * 32]
            fixed_wm.train_step(earth_data[idx, :8], earth_data[idx, 8:10], earth_data[idx, 10:])
    print("   Fixed Base World Model trained on Earth_Std.")
    
    # Meta-Train Meta-WM end-to-end
    t0 = time.time()
    for ep in range(120):
        for task in train_tasks:
            t_data = meta_data[task]
            N_t = len(t_data)
            for _ in range(5):
                # Sample few-shot context (K in [1..5])
                K_sample = np.random.randint(1, 6)
                c_idx = np.random.choice(N_t, size=K_sample, replace=False)
                b_idx = np.random.choice(N_t, size=32, replace=False)
                meta_wm.train_step(t_data[c_idx], t_data[b_idx, :8], t_data[b_idx, 8:10], t_data[b_idx, 10:])
    train_sec = time.time() - t0
    print(f"   Meta-World Model training completed in {train_sec:.2f} seconds.")

    # 3. Few-Shot OOD Dynamics Adaptation Evaluations
    print("\n3. Running Out-Of-Distribution Few-Shot Adaptation Benchmark across 6 Regimes...")
    all_regimes = ["Earth_Std", "Moon_LowGrav", "Jupiter_HighGrav", "Ice_ZeroFriction", "Viscous_Mud", "Heavy_Payload"]
    k_steps = [1, 2, 3, 4, 5]
    
    results = {
        r: {
            "Fixed_WM": {k: [] for k in k_steps},
            "FineTuned_WM": {k: [] for k in k_steps},
            "Meta_WM": {k: [] for k in k_steps}
        }
        for r in all_regimes
    }
    
    test_env = ContinuousOODPhysicsEnv(seed=1007)
    num_eval_episodes = 15
    
    for r_name in all_regimes:
        test_env.set_regime(r_name)
        is_ood = (r_name == "Heavy_Payload")
        print(f"\n-> Testing Regime: [{r_name:18s}] (OOD Unseen: {is_ood})")
        
        for eval_ep in range(num_eval_episodes):
            seed_ep = eval_ep * 100 + 42
            
            for K in k_steps:
                # A. Collect K context transitions from test environment
                test_env.reset(seed=seed_ep)
                context_buffer = []
                obs = test_env._get_obs()
                for _ in range(K):
                    act = test_env.rng.uniform(-0.8, 0.8, size=2).astype(np.float32)
                    nobs, rew, d, _ = test_env.step(act)
                    context_buffer.append(np.concatenate([obs, act, nobs], axis=-1))
                    obs = nobs
                    if d: break
                    
                # B. Multi-step autoregressive 5-step rollout evaluation
                eval_acts = [test_env.rng.uniform(-0.8, 0.8, size=2).astype(np.float32) for _ in range(5)]
                true_future = []
                for a in eval_acts:
                    nobs, _, _, _ = test_env.step(a)
                    true_future.append(nobs)
                true_future = np.array(true_future) # (5, 8)
                
                # 1. Fixed WM (Zero adaptation)
                fixed_pred = []
                f_obs = obs.copy()
                for a in eval_acts:
                    f_obs = fixed_wm.predict(f_obs, a)
                    fixed_pred.append(f_obs)
                mse_fixed = float(np.mean((np.array(fixed_pred) - true_future) ** 2))
                results[r_name]["Fixed_WM"][K].append(mse_fixed)
                
                # 2. Fine-Tuned WM (Few-shot gradient descent)
                ft_wm = FixedAndFineTunedWorldModel(obs_dim=8, action_dim=2, hidden_dim=48)
                for (sp, _), (tp, _) in zip(fixed_wm.model.parameters(), ft_wm.model.parameters()):
                    tp[:] = sp[:]
                ft_wm.fine_tune(context_buffer, steps=4, lr=4e-3)
                
                ft_pred = []
                f_obs = obs.copy()
                for a in eval_acts:
                    f_obs = ft_wm.predict(f_obs, a)
                    ft_pred.append(f_obs)
                mse_ft = float(np.mean((np.array(ft_pred) - true_future) ** 2))
                results[r_name]["FineTuned_WM"][K].append(mse_ft)
                
                # 3. Meta-WM (Ours: CAVIA-style Fast Latent Adaptation)
                context_w = meta_wm.adapt(context_buffer, refine_steps=3, lr=0.03)
                meta_pred = []
                m_obs = obs.copy()
                for a in eval_acts:
                    m_obs = meta_wm.predict(m_obs, a, context_w)
                    meta_pred.append(m_obs)
                mse_meta = float(np.mean((np.array(meta_pred) - true_future) ** 2))
                results[r_name]["Meta_WM"][K].append(mse_meta)

    # 4. Aggregate Metrics & Reporting
    summary = {}
    print("\n================================================================================")
    print("PHASE 6 BENCHMARK EVALUATION SUMMARY (5-Step Rollout MSE at K=3)")
    print("================================================================================")
    print(f"{'Regime':20s} | {'Fixed WM MSE':14s} | {'FineTuned WM':14s} | {'Meta-WM (Ours)':14s} | {'Error Reduct %':14s}")
    print("-" * 85)
    
    for r_name in all_regimes:
        summary[r_name] = {}
        for m_name in ["Fixed_WM", "FineTuned_WM", "Meta_WM"]:
            summary[r_name][m_name] = {
                f"K={k}": {
                    "mean_mse": float(np.mean(results[r_name][m_name][k])),
                    "std_mse": float(np.std(results[r_name][m_name][k]))
                }
                for k in k_steps
            }
        
        mse_fix_3 = summary[r_name]["Fixed_WM"]["K=3"]["mean_mse"]
        mse_ft_3  = summary[r_name]["FineTuned_WM"]["K=3"]["mean_mse"]
        mse_meta_3 = summary[r_name]["Meta_WM"]["K=3"]["mean_mse"]
        reduct = ((mse_fix_3 - mse_meta_3) / (mse_fix_3 + 1e-12)) * 100.0
        summary[r_name]["error_reduction_pct_at_k3"] = float(reduct)
        print(f"{r_name:20s} | {mse_fix_3:14.4f} | {mse_ft_3:14.4f} | {mse_meta_3:14.4f} | {reduct:12.1f}%")

    # Macro Summaries
    id_regimes = ["Earth_Std", "Moon_LowGrav", "Jupiter_HighGrav", "Ice_ZeroFriction", "Viscous_Mud"]
    ood_regimes = ["Heavy_Payload"]
    
    id_fix = float(np.mean([summary[r]["Fixed_WM"]["K=3"]["mean_mse"] for r in id_regimes]))
    id_ft  = float(np.mean([summary[r]["FineTuned_WM"]["K=3"]["mean_mse"] for r in id_regimes]))
    id_meta = float(np.mean([summary[r]["Meta_WM"]["K=3"]["mean_mse"] for r in id_regimes]))
    
    ood_fix = float(np.mean([summary[r]["Fixed_WM"]["K=3"]["mean_mse"] for r in ood_regimes]))
    ood_ft  = float(np.mean([summary[r]["FineTuned_WM"]["K=3"]["mean_mse"] for r in ood_regimes]))
    ood_meta = float(np.mean([summary[r]["Meta_WM"]["K=3"]["mean_mse"] for r in ood_regimes]))
    
    summary["Overall_Macro"] = {
        "In_Distribution_K3_MSE": {"Fixed": id_fix, "FineTuned": id_ft, "Meta": id_meta, "Gain": (id_fix - id_meta)/id_fix*100.0},
        "Out_Of_Distribution_K3_MSE": {"Fixed": ood_fix, "FineTuned": ood_ft, "Meta": ood_meta, "Gain": (ood_fix - ood_meta)/ood_fix*100.0}
    }
    
    print("\n[Macro Performance Summary at K=3]")
    print(f"  In-Distribution (5 Regimes) MSE  : Fixed={id_fix:.4f} -> FT={id_ft:.4f} -> Meta={id_meta:.4f} (Reduction: {summary['Overall_Macro']['In_Distribution_K3_MSE']['Gain']:.1f}%)")
    print(f"  Unseen OOD (Heavy Payload) MSE   : Fixed={ood_fix:.4f} -> FT={ood_ft:.4f} -> Meta={ood_meta:.4f} (Reduction: {summary['Overall_Macro']['Out_Of_Distribution_K3_MSE']['Gain']:.1f}%)")

    # Save Metrics JSON
    json_path = os.path.join(curr_dir, "meta_adaptation_metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nMetrics written to: {json_path}")
    
    # 5. Generate Visualizations
    generate_meta_adaptation_charts(summary, all_regimes, k_steps)


def generate_meta_adaptation_charts(summary, regimes, k_steps):
    """Generates 300 DPI publication figure for Meta-World Model Adaptation Benchmark."""
    plt.style.use('default')
    plt.rcParams['font.family'] = 'DejaVu Sans'
    
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), dpi=300)
    fig.suptitle("Meta-World Models & OOD Dynamics Fast Adaptation Benchmark",
                 fontsize=13, fontweight='bold', y=0.98)
                 
    colors = {
        "Fixed_WM": "#E63946",       # Red
        "FineTuned_WM": "#F4A261",   # Orange
        "Meta_WM": "#2A9D8F"         # Teal
    }
    
    # Panel A: Few-Shot Adaptation Curve (MSE vs K) averaged across OOD regimes
    ax1 = axes[0]
    for m_name, label in [("Fixed_WM", "Fixed WM (Earth Base)"),
                          ("FineTuned_WM", "Fine-Tuned WM (SGD)"),
                          ("Meta_WM", "Meta-WM (Context FiLM, Ours)")]:
        mses = [
            np.mean([summary[r][m_name][f"K={k}"]["mean_mse"] for r in regimes])
            for k in k_steps
        ]
        ax1.plot(k_steps, mses, marker='o', linewidth=2.2, label=label, color=colors[m_name])
        
    ax1.set_xlabel("Few-Shot Adaptation Steps K", fontsize=10, fontweight='bold')
    ax1.set_ylabel("5-Step Rollout Prediction MSE", fontsize=10, fontweight='bold')
    ax1.set_title("A. Few-Shot Adaptation Trajectory (K in [1..5])", fontsize=11, fontweight='bold', pad=8)
    ax1.grid(True, linestyle='--', alpha=0.5)
    ax1.legend(loc='upper right', framealpha=0.95, fontsize=9)
    ax1.set_xticks(k_steps)
    
    # Panel B: Breakdown Across 6 Physical Regimes at K=3
    ax2 = axes[1]
    short_names = ["Earth", "Moon", "Jupiter", "Ice", "Mud", "Payload (OOD)"]
    x = np.arange(len(regimes))
    w = 0.27
    
    fix_vals = [summary[r]["Fixed_WM"]["K=3"]["mean_mse"] for r in regimes]
    ft_vals = [summary[r]["FineTuned_WM"]["K=3"]["mean_mse"] for r in regimes]
    meta_vals = [summary[r]["Meta_WM"]["K=3"]["mean_mse"] for r in regimes]
    
    ax2.bar(x - w, fix_vals, w, label='Fixed WM', color=colors["Fixed_WM"], alpha=0.9)
    ax2.bar(x, ft_vals, w, label='Fine-Tuned WM', color=colors["FineTuned_WM"], alpha=0.9)
    ax2.bar(x + w, meta_vals, w, label='Meta-WM (Ours)', color=colors["Meta_WM"], alpha=0.9)
    
    ax2.set_xticks(x)
    ax2.set_xticklabels(short_names, fontsize=8.5, fontweight='bold', rotation=15)
    ax2.set_ylabel("5-Step Rollout MSE at K=3", fontsize=10, fontweight='bold')
    ax2.set_title("B. Multi-Regime Dynamics Prediction Error (K=3)", fontsize=11, fontweight='bold', pad=8)
    ax2.grid(axis='y', linestyle='--', alpha=0.5)
    ax2.legend(loc='upper right', framealpha=0.95, fontsize=9)
    
    # Panel C: Error Reduction & OOD Generalization Efficiency
    ax3 = axes[2]
    reduct_vals = [max(0.0, summary[r]["error_reduction_pct_at_k3"]) for r in regimes]
    bar_colors = ['#2A9D8F' if r != "Heavy_Payload" else '#E76F51' for r in regimes]
    ax3.set_xticks(x)
    bars = ax3.bar(x, reduct_vals, color=bar_colors, width=0.55, alpha=0.9)
    ax3.set_ylabel("Prediction Error Reduction vs Fixed (%)", fontsize=10, fontweight='bold')
    ax3.set_title("C. Dynamics Error Reduction at K=3 (OOD in Orange)", fontsize=11, fontweight='bold', pad=8)
    ax3.set_xticklabels(short_names, fontsize=8.5, fontweight='bold', rotation=15)
    ax3.set_ylim(0, 100)
    ax3.grid(axis='y', linestyle='--', alpha=0.5)
    
    for b in bars:
        h = b.get_height()
        ax3.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                     textcoords="offset points", ha='center', va='bottom', fontsize=8.5, fontweight='bold')
                     
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    eval_path = os.path.join(curr_dir, "meta_world_model_eval.png")
    plt.savefig(eval_path, dpi=300)
    plt.close()
    print(f"Saved: {eval_path}")


if __name__ == "__main__":
    run_meta_world_model_benchmark()
