"""
Hierarchical JEPA-MuZero Unified World Model Prototype
======================================================
Architecture:
- Layer 1 (Bottom): JEPA Self-Supervised Latent Spatiotemporal Encoder
  Filters high-entropy, unpredictable pixel-level noise via VICReg + EMA temporal prediction.
- Layer 2 (Top): MuZero Value-Equivalent Dynamics & Latent MCTS Planner
  Maps JEPA features to value-equivalent manifold and executes fast Latent MCTS tree search.

Comparative Closed-Loop Evaluation under 80% Extreme Visual Noise:
1. Pure Reconstruction VAE-RSSM (with Shooting/MPC planner)
2. Pure End-to-End MuZero (direct pixel-to-value end-to-end representation)
3. Hierarchical JEPA-MuZero Unified World Model (JEPA Layer 1 + MuZero MCTS Layer 2)
"""

import os
import sys
import time
import json
import numpy as np

curr_dir = os.path.dirname(os.path.abspath(__file__))
if curr_dir not in sys.path:
    sys.path.append(curr_dir)

from composite_env import CompositeDistractorEnv
from nn_core import (
    Linear, LayerNorm, ReLU, Tanh, Sequential, Adam,
    copy_parameters, ema_update, one_hot, mse_loss,
    softmax_cross_entropy, vicreg_loss
)
from models import ReconstructionWM, ValueEquivalentWM, JepaWM


# ==============================================================================
# 1. Pure NumPy Latent Monte Carlo Tree Search (MCTS) Node & Planner
# ==============================================================================

class MCTSNode:
    def __init__(self, state, prior_prob=1.0):
        self.state = state # latent state vector (1, d_s)
        self.prior_prob = prior_prob
        self.visit_count = 0
        self.total_value = 0.0
        self.children = {} # action -> MCTSNode
        self.reward = 0.0
        self.is_expanded = False

    def value(self):
        if self.visit_count == 0:
            return 0.0
        return self.total_value / self.visit_count


class LatentMCTSPlanner:
    def __init__(self, dynamics_fn, prediction_fn, action_dim=5, num_simulations=25,
                 c_puct=1.5, gamma=0.95):
        """
        dynamics_fn: s, a -> s_next, r_pred
        prediction_fn: s -> v_pred, pi_logits
        """
        self.dynamics_fn = dynamics_fn
        self.prediction_fn = prediction_fn
        self.action_dim = action_dim
        self.num_simulations = num_simulations
        self.c_puct = c_puct
        self.gamma = gamma

    def plan(self, root_state, temperature=0.0):
        """
        Executes MCTS in latent space starting from root_state.
        Returns selected best action, action probabilities, and root value estimate.
        """
        # 1. Initialize root node
        root = MCTSNode(root_state)
        v_root, logits_root = self.prediction_fn(root_state)
        # Softmax prior
        exp_logits = np.exp(logits_root - np.max(logits_root))
        priors = exp_logits / (np.sum(exp_logits) + 1e-12)
        priors = priors.flatten()
        
        # Expand root
        for a in range(self.action_dim):
            s_next, r_pred = self.dynamics_fn(root_state, np.array([a]))
            child = MCTSNode(s_next, prior_prob=float(priors[a]))
            child.reward = float(np.asarray(r_pred).item())
            root.children[a] = child
        root.is_expanded = True
        
        # 2. Run Simulations
        for _ in range(self.num_simulations):
            node = root
            search_path = [node]
            actions_taken = []
            
            # Selection
            while node.is_expanded and len(node.children) > 0:
                best_action = -1
                best_score = -1e9
                total_visits = sum(child.visit_count for child in node.children.values())
                
                for a, child in node.children.items():
                    # PUCT formula
                    q_val = child.value()
                    u_val = self.c_puct * child.prior_prob * (np.sqrt(total_visits + 1e-8) / (1.0 + child.visit_count))
                    score = q_val + u_val
                    if score > best_score:
                        best_score = score
                        best_action = a
                        
                actions_taken.append(best_action)
                node = node.children[best_action]
                search_path.append(node)
                
            # Expansion & Evaluation of leaf
            v_leaf, logits_leaf = self.prediction_fn(node.state)
            leaf_v = float(np.asarray(v_leaf).item())
            
            if not node.is_expanded:
                exp_l = np.exp(logits_leaf - np.max(logits_leaf))
                leaf_priors = (exp_l / (np.sum(exp_l) + 1e-12)).flatten()
                for a in range(self.action_dim):
                    s_nxt, r_nxt = self.dynamics_fn(node.state, np.array([a]))
                    c_node = MCTSNode(s_nxt, prior_prob=float(leaf_priors[a]))
                    c_node.reward = float(np.asarray(r_nxt).item())
                    node.children[a] = c_node
                node.is_expanded = True
                
            # Backpropagation
            # Cumulative discounted return backwards along path
            running_value = leaf_v
            for p_node in reversed(search_path):
                running_value = p_node.reward + self.gamma * running_value
                p_node.visit_count += 1
                p_node.total_value += running_value
                
        # 3. Action selection
        visits = np.array([root.children[a].visit_count for a in range(self.action_dim)], dtype=np.float32)
        if temperature == 0.0 or np.sum(visits) == 0:
            best_act = int(np.argmax(visits))
            probs = np.zeros(self.action_dim, dtype=np.float32)
            probs[best_act] = 1.0
        else:
            v_temp = visits ** (1.0 / temperature)
            probs = v_temp / (np.sum(v_temp) + 1e-12)
            best_act = int(np.random.choice(self.action_dim, p=probs))
            
        return best_act, probs, float(root.value())


# ==============================================================================
# 2. Hierarchical JEPA-MuZero Unified World Model Architecture
# ==============================================================================

class HierarchicalJEPAMuZeroWM:
    """
    Two-Tier World Model:
    Layer 1: Self-supervised JEPA context encoder f_theta and EMA target encoder.
    Layer 2: MuZero value-equivalent dynamics g_psi & prediction f_phi.
    """
    def __init__(self, obs_dim=256, jepa_dim=32, muzero_dim=24, action_dim=5, lr=2e-3, ema_tau=0.98):
        self.obs_dim = obs_dim
        self.jepa_dim = jepa_dim
        self.muzero_dim = muzero_dim
        self.action_dim = action_dim
        self.ema_tau = ema_tau
        
        # ----------------------------------------------------------------------
        # Layer 1: JEPA Spatiotemporal Feature Encoder (Self-Supervised)
        # ----------------------------------------------------------------------
        self.jepa_context_enc = Sequential(
            Linear(obs_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, jepa_dim),
            Tanh()
        )
        self.jepa_target_enc = Sequential(
            Linear(obs_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, jepa_dim),
            Tanh()
        )
        copy_parameters(self.jepa_context_enc.parameters(), self.jepa_target_enc.parameters())
        
        # JEPA Latent Predictor
        self.jepa_predictor = Sequential(
            Linear(jepa_dim + action_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, jepa_dim),
            Tanh()
        )
        
        # Layer 1 Optimizer
        jepa_params = self.jepa_context_enc.parameters() + self.jepa_predictor.parameters()
        self.jepa_optimizer = Adam(jepa_params, lr=lr)
        
        # ----------------------------------------------------------------------
        # Layer 2: MuZero Value-Equivalent Dynamics & Prediction on JEPA Latents
        # ----------------------------------------------------------------------
        # Projection from JEPA features to value-equivalent state s
        self.muzero_proj = Sequential(
            Linear(jepa_dim, 48),
            LayerNorm(48),
            ReLU(),
            Linear(48, muzero_dim),
            Tanh()
        )
        
        # Latent Dynamics: (s_t, a_t) -> (s_{t+1}, r_{t+1})
        self.muzero_dynamics = Sequential(
            Linear(muzero_dim + action_dim, 48),
            LayerNorm(48),
            ReLU(),
            Linear(48, muzero_dim),
            Tanh()
        )
        self.muzero_reward = Sequential(
            Linear(muzero_dim, 24),
            ReLU(),
            Linear(24, 1)
        )
        
        # Prediction Network: s_t -> (v_t, pi_logits)
        self.muzero_value = Sequential(
            Linear(muzero_dim, 24),
            ReLU(),
            Linear(24, 1)
        )
        self.muzero_policy = Sequential(
            Linear(muzero_dim, 24),
            ReLU(),
            Linear(24, action_dim)
        )
        
        muzero_params = (
            self.muzero_proj.parameters() +
            self.muzero_dynamics.parameters() +
            self.muzero_reward.parameters() +
            self.muzero_value.parameters() +
            self.muzero_policy.parameters()
        )
        self.muzero_optimizer = Adam(muzero_params, lr=lr)
        
    def encode_jepa(self, obs):
        """Passes raw observation through Layer 1 JEPA encoder."""
        return self.jepa_context_enc.forward(obs)
        
    def encode_state(self, obs):
        """End-to-end mapping from raw observation to Layer 2 MuZero state s."""
        z = self.encode_jepa(obs)
        return self.muzero_proj.forward(z)
        
    def dynamics_step(self, s, action):
        """Layer 2 Latent transition: s, a -> s_next, r_pred"""
        if action.ndim == 1:
            a_vec = one_hot(action, self.action_dim)
        else:
            a_vec = action
        inp = np.concatenate([s, a_vec], axis=-1)
        s_next = self.muzero_dynamics.forward(inp)
        r_pred = self.muzero_reward.forward(s_next).squeeze(-1)
        return s_next, r_pred
        
    def predict_value_policy(self, s):
        """Layer 2 Prediction: s -> v_pred, pi_logits"""
        v = self.muzero_value.forward(s).squeeze(-1)
        pi = self.muzero_policy.forward(s)
        return v, pi
        
    def train_jepa_step(self, obs_t, actions, obs_tp1, lambda_pred=1.0, lambda_vicreg=0.25):
        """Step 1: Train Layer 1 JEPA with VICReg anti-collapse."""
        self.jepa_optimizer.zero_grad()
        B = obs_t.shape[0]
        a_vec = one_hot(actions, self.action_dim)
        
        z_t = self.jepa_context_enc.forward(obs_t)
        z_tp1_target = self.jepa_target_enc.forward(obs_tp1)
        
        # Predictor
        inp_pred = np.concatenate([z_t, a_vec], axis=-1)
        z_pred_tp1 = self.jepa_predictor.forward(inp_pred)
        
        loss_pred, grad_pred = mse_loss(z_pred_tp1, z_tp1_target)
        var_loss, cov_loss, grad_vicreg = vicreg_loss(z_t, gamma=1.0)
        vicreg_total = var_loss + cov_loss
        
        # Backprop
        grad_inp_pred = self.jepa_predictor.backward(lambda_pred * grad_pred)
        grad_zt_from_pred = grad_inp_pred[:, :self.jepa_dim]
        
        grad_zt_total = grad_zt_from_pred + lambda_vicreg * grad_vicreg
        self.jepa_context_enc.backward(grad_zt_total)
        
        self.jepa_optimizer.step()
        ema_update(self.jepa_context_enc.parameters(), self.jepa_target_enc.parameters(), tau=self.ema_tau)
        
        return float(loss_pred + lambda_vicreg * vicreg_total)
        
    def train_muzero_step(self, obs_t, actions, rewards, obs_tp1, values_t, values_tp1, target_actions,
                          lambda_rew=1.5, lambda_val=0.5, lambda_pol=0.5):
        """Step 2: Train Layer 2 MuZero on top of frozen / detached JEPA features."""
        self.muzero_optimizer.zero_grad()
        B = obs_t.shape[0]
        a_vec = one_hot(actions, self.action_dim)
        
        # Extract features from Layer 1 (detached)
        z_t = self.jepa_context_enc.forward(obs_t)
        
        # Project to Layer 2 state s_t
        s_t = self.muzero_proj.forward(z_t)
        
        # Predictions at s_t
        v_t = self.muzero_value.forward(s_t)
        pi_logits = self.muzero_policy.forward(s_t)
        
        loss_val_t, grad_vt = mse_loss(v_t, values_t[:, None])
        loss_pol, grad_pol, _ = softmax_cross_entropy(pi_logits, target_actions)
        
        # Transition
        inp_dyn = np.concatenate([s_t, a_vec], axis=-1)
        s_pred_tp1 = self.muzero_dynamics.forward(inp_dyn)
        
        r_pred = self.muzero_reward.forward(s_pred_tp1)
        v_tp1 = self.muzero_value.forward(s_pred_tp1)
        
        loss_rew, grad_rew = mse_loss(r_pred, rewards[:, None])
        loss_val_tp1, grad_vtp1 = mse_loss(v_tp1, values_tp1[:, None])
        
        total_loss = (
            lambda_rew * loss_rew +
            lambda_val * (loss_val_t + loss_val_tp1) +
            lambda_pol * loss_pol
        )
        
        # Backprop through s_{t+1}
        grad_s_rew = self.muzero_reward.backward(lambda_rew * grad_rew)
        grad_s_vtp1 = self.muzero_value.backward(lambda_val * grad_vtp1)
        grad_stp1_total = grad_s_rew + grad_s_vtp1
        
        # Dynamics backward
        grad_inp_dyn = self.muzero_dynamics.backward(grad_stp1_total)
        grad_st_from_dyn = grad_inp_dyn[:, :self.muzero_dim]
        
        # Root predictions backward
        grad_st_from_vt = self.muzero_value.backward(lambda_val * grad_vt)
        grad_st_from_pol = self.muzero_policy.backward(lambda_pol * grad_pol)
        
        grad_st_total = grad_st_from_dyn + grad_st_from_vt + grad_st_from_pol
        self.muzero_proj.backward(grad_st_total)
        
        self.muzero_optimizer.step()
        return float(total_loss)
        
    def get_mcts_planner(self, num_simulations=25, c_puct=1.5):
        """Constructs a ready-to-run Latent MCTS planner on this model."""
        return LatentMCTSPlanner(
            dynamics_fn=self.dynamics_step,
            prediction_fn=self.predict_value_policy,
            action_dim=self.action_dim,
            num_simulations=num_simulations,
            c_puct=c_puct
        )


# ==============================================================================
# 3. Data Collection and Probe Evaluation Functions
# ==============================================================================

def get_expert_action(env):
    """Greedy momentum-aware teacher policy."""
    pos = env.agent_pos
    vel = env.agent_vel
    tgt = env.target_pos
    best_act = 0
    best_dist = 999.0
    for a_idx, act_vec in enumerate(env.action_vectors):
        next_vel = 0.80 * vel + act_vec
        next_pos = np.clip(pos + next_vel, -1.0, 1.0)
        dist = np.linalg.norm(next_pos - tgt)
        if dist < best_dist:
            best_dist = dist
            best_act = a_idx
    return best_act


def collect_dataset(env, num_steps=800, epsilon=0.25):
    """Collects transitions with Monte Carlo discounted returns."""
    obs_list, act_list, rew_list, next_obs_list, state_list = [], [], [], [], []
    obs, state = env.reset()
    for _ in range(num_steps):
        if np.random.rand() < epsilon:
            action = np.random.randint(0, env.action_dim)
        else:
            action = get_expert_action(env)
        next_obs, rew, done, info = env.step(action)
        obs_list.append(obs)
        act_list.append(action)
        rew_list.append(rew)
        next_obs_list.append(next_obs)
        state_list.append(state)
        if done:
            obs, state = env.reset()
        else:
            obs = next_obs
            state = info["true_state"]
            
    rewards = np.array(rew_list, dtype=np.float32)
    gamma = 0.95
    returns = np.zeros_like(rewards)
    running_return = 0.0
    for t in reversed(range(len(rewards))):
        running_return = rewards[t] + gamma * running_return
        returns[t] = running_return
        
    data = {
        "obs": np.array(obs_list, dtype=np.float32),
        "actions": np.array(act_list, dtype=np.int32),
        "rewards": rewards,
        "next_obs": np.array(next_obs_list, dtype=np.float32),
        "values": returns,
        "next_values": np.roll(returns, -1),
        "states": np.array(state_list, dtype=np.float32)
    }
    data["next_values"][-1] = 0.0
    return data


def linear_probe_r2(latent, target):
    """Calculates R^2 linear probe from latent to ground truth state."""
    N, D = latent.shape
    X = np.concatenate([latent, np.ones((N, 1), dtype=np.float32)], axis=-1)
    Y = target[:, None] if target.ndim == 1 else target
    reg = 1e-3 * np.eye(X.shape[1], dtype=np.float32)
    try:
        W = np.linalg.solve(X.T @ X + reg, X.T @ Y)
        Y_pred = X @ W
        var_y = np.var(Y, axis=0) + 1e-8
        mse_y = np.mean((Y - Y_pred) ** 2, axis=0)
        r2 = np.maximum(0.0, 1.0 - (mse_y / var_y))
        return float(np.mean(r2))
    except Exception:
        return 0.0


# ==============================================================================
# 4. Closed-Loop Adversarial Benchmark Runner at 80% Noise
# ==============================================================================

def evaluate_closed_loop_agent(agent_type, model, env, num_episodes=8):
    """
    Evaluates closed-loop policy performance in the environment under 80% noise.
    Measures:
    - Average Episode Return
    - Target Capture Rate (% of steps inside capture zone)
    - Decision Latency (milliseconds per step)
    """
    total_returns = []
    capture_rates = []
    step_latencies = []
    
    if agent_type == "Hierarchical_JEPA_MuZero":
        planner = model.get_mcts_planner(num_simulations=20, c_puct=1.5)
    elif agent_type == "Pure_MuZero":
        # Pure MuZero MCTS planner
        def dyn_fn(s, a):
            return model.predict_next(s, a)
        def pred_fn(s):
            return model.predict_value_policy(s)
        planner = LatentMCTSPlanner(dyn_fn, pred_fn, action_dim=env.action_dim, num_simulations=20, c_puct=1.5)
    else: # Pure Reconstruction VAE-RSSM (Shooting MPC)
        planner = None
        
    for ep in range(num_episodes):
        obs, _ = env.reset(seed=ep * 200 + 77)
        ep_ret = 0.0
        captured_count = 0
        
        for t in range(env.max_steps):
            t_start = time.perf_counter()
            
            if agent_type == "Hierarchical_JEPA_MuZero":
                # Encode obs -> s_0
                s_0 = model.encode_state(obs[None, :])
                action, _, _ = planner.plan(s_0, temperature=0.0)
            elif agent_type == "Pure_MuZero":
                s_0 = model.encode(obs[None, :])
                action, _, _ = planner.plan(s_0, temperature=0.0)
            else: # Reconstruction VAE-RSSM (Shooting MPC with 16 rollouts, horizon 3)
                z_root = model.encode(obs[None, :])
                candidate_seqs = np.random.randint(0, env.action_dim, size=(16, 3))
                for a_i in range(env.action_dim):
                    candidate_seqs[a_i] = a_i
                z_batch = np.repeat(z_root, 16, axis=0)
                cum_rew = np.zeros(16, dtype=np.float32)
                for k in range(3):
                    acts = candidate_seqs[:, k]
                    z_batch, r_pred = model.predict_next(z_batch, acts)
                    cum_rew += (0.95 ** k) * r_pred
                action = int(candidate_seqs[np.argmax(cum_rew), 0])
                
            latency_ms = (time.perf_counter() - t_start) * 1000.0
            step_latencies.append(latency_ms)
            
            next_obs, rew, done, info = env.step(action)
            ep_ret += rew
            if info["captured"]:
                captured_count += 1
            if done:
                break
            obs = next_obs
            
        total_returns.append(ep_ret)
        capture_rates.append(captured_count / env.max_steps)
        
    avg_return = float(np.mean(total_returns))
    avg_capture = float(np.mean(capture_rates))
    avg_latency = float(np.mean(step_latencies))
    return avg_return, avg_capture, avg_latency


def run_phase2_benchmark():
    """
    Executes Phase 2 Adversarial Stress Test under Noise Ratio = 80%.
    Tracks learning curves across training checkpoints (Epochs 0, 30, 60, 90, 120, 150).
    """
    print("================================================================================")
    print("PHASE 2: HIERARCHICAL JEPA-MUZERO UNIFIED WORLD MODEL BENCHMARK (NOISE = 80%)")
    print("================================================================================")
    
    noise_ratio = 0.80
    seed = 42
    np.random.seed(seed)
    
    train_env = CompositeDistractorEnv(grid_size=16, noise_ratio=noise_ratio, seed=seed)
    test_env = CompositeDistractorEnv(grid_size=16, noise_ratio=noise_ratio, seed=seed + 1001)
    
    # Collect Training & Testing Datasets
    print("Collecting interactive trajectories under 80% noise...")
    train_data = collect_dataset(train_env, num_steps=1000, epsilon=0.30)
    test_data = collect_dataset(test_env, num_steps=400, epsilon=0.20)
    
    obs_dim = 256
    action_dim = 5
    
    # 1. Instantiate 3 Competing World Models
    print("Initializing architectures:")
    print("  [1] Pure Reconstruction WM (VAE-RSSM)")
    model_recon = ReconstructionWM(obs_dim=obs_dim, latent_dim=32, action_dim=action_dim, lr=2e-3)
    
    print("  [2] Pure End-to-End MuZero")
    model_muzero = ValueEquivalentWM(obs_dim=obs_dim, latent_dim=32, action_dim=action_dim, lr=2e-3)
    
    print("  [3] Hierarchical JEPA-MuZero Unified World Model")
    model_hybrid = HierarchicalJEPAMuZeroWM(obs_dim=obs_dim, jepa_dim=32, muzero_dim=24, action_dim=action_dim, lr=2e-3)
    
    # Training Loop with periodic evaluation checkpoints
    eval_checkpoints = [0, 30, 60, 90, 120, 150]
    batch_size = 32
    N = len(train_data["obs"])
    steps_per_epoch = N // batch_size
    
    # Metrics Tracker
    tracking_data = {
        "checkpoints": eval_checkpoints,
        "Reconstruction": {"returns": [], "capture_rates": [], "task_r2": [], "train_time": 0.0},
        "Pure_MuZero": {"returns": [], "capture_rates": [], "task_r2": [], "train_time": 0.0},
        "Hierarchical_JEPA_MuZero": {"returns": [], "capture_rates": [], "task_r2": [], "train_time": 0.0}
    }
    
    print("\n--- Starting Training & Periodic Checkpoint Evaluation ---")
    start_train_time = time.time()
    
    for epoch in range(151):
        # 1. Evaluate at checkpoints
        if epoch in eval_checkpoints:
            print(f"\n[Checkpoint Epoch {epoch:3d} / 150] Evaluating Closed-Loop Performance under 80% Noise...")
            
            # Recon Evaluation
            r_ret, r_cap, r_lat = evaluate_closed_loop_agent("Pure_Reconstruction", model_recon, test_env, num_episodes=5)
            r_latents = model_recon.encode(test_data["obs"])
            r_r2 = linear_probe_r2(r_latents, test_data["states"])
            tracking_data["Reconstruction"]["returns"].append(r_ret)
            tracking_data["Reconstruction"]["capture_rates"].append(r_cap)
            tracking_data["Reconstruction"]["task_r2"].append(r_r2)
            print(f"  * Reconstruction WM      | Return: {r_ret:6.2f} | Capture Rate: {r_cap*100:4.1f}% | Task R2: {r_r2:.3f}")
            
            # Pure MuZero Evaluation
            m_ret, m_cap, m_lat = evaluate_closed_loop_agent("Pure_MuZero", model_muzero, test_env, num_episodes=5)
            m_latents = model_muzero.encode(test_data["obs"])
            m_r2 = linear_probe_r2(m_latents, test_data["states"])
            tracking_data["Pure_MuZero"]["returns"].append(m_ret)
            tracking_data["Pure_MuZero"]["capture_rates"].append(m_cap)
            tracking_data["Pure_MuZero"]["task_r2"].append(m_r2)
            print(f"  * Pure End-to-End MuZero | Return: {m_ret:6.2f} | Capture Rate: {m_cap*100:4.1f}% | Task R2: {m_r2:.3f}")
            
            # Hierarchical JEPA-MuZero Evaluation
            h_ret, h_cap, h_lat = evaluate_closed_loop_agent("Hierarchical_JEPA_MuZero", model_hybrid, test_env, num_episodes=5)
            h_latents = model_hybrid.encode_state(test_data["obs"])
            h_r2 = linear_probe_r2(h_latents, test_data["states"])
            tracking_data["Hierarchical_JEPA_MuZero"]["returns"].append(h_ret)
            tracking_data["Hierarchical_JEPA_MuZero"]["capture_rates"].append(h_cap)
            tracking_data["Hierarchical_JEPA_MuZero"]["task_r2"].append(h_r2)
            print(f"  * Hierarchical JEPA-MZ   | Return: {h_ret:6.2f} | Capture Rate: {h_cap*100:4.1f}% | Task R2: {h_r2:.3f} | Latency: {h_lat:.2f}ms")
            
        if epoch == 150:
            break
            
        # 2. Train One Epoch for all 3 models
        perm = np.random.permutation(N)
        for s in range(steps_per_epoch):
            batch_idx = perm[s * batch_size:(s + 1) * batch_size]
            b_obs = train_data["obs"][batch_idx]
            b_act = train_data["actions"][batch_idx]
            b_rew = train_data["rewards"][batch_idx]
            b_nobs = train_data["next_obs"][batch_idx]
            b_val = train_data["values"][batch_idx]
            b_nval = train_data["next_values"][batch_idx]
            
            # Train Recon
            t0 = time.time()
            model_recon.train_step(b_obs, b_act, b_rew, b_nobs, lambda_recon=1.0, lambda_dyn=1.0, lambda_rew=1.5)
            tracking_data["Reconstruction"]["train_time"] += (time.time() - t0)
            
            # Train Pure MuZero
            t0 = time.time()
            model_muzero.train_step(b_obs, b_act, b_rew, b_nobs, b_val, b_nval, b_act, lambda_rew=1.5, lambda_val=0.5, lambda_pol=0.5)
            tracking_data["Pure_MuZero"]["train_time"] += (time.time() - t0)
            
            # Train Hierarchical JEPA-MuZero (2-tier training)
            t0 = time.time()
            model_hybrid.train_jepa_step(b_obs, b_act, b_nobs, lambda_pred=1.0, lambda_vicreg=0.25)
            model_hybrid.train_muzero_step(b_obs, b_act, b_rew, b_nobs, b_val, b_nval, b_act, lambda_rew=1.5, lambda_val=0.5, lambda_pol=0.5)
            tracking_data["Hierarchical_JEPA_MuZero"]["train_time"] += (time.time() - t0)
            
    total_duration = time.time() - start_train_time
    print(f"\nPhase 2 Benchmark completed in {total_duration:.2f} seconds.")
    
    # 3. Final In-Depth Latency & MCTS Benchmark (100 steps)
    print("\nMeasuring MCTS Search Latency & Throughput...")
    _, _, lat_hybrid = evaluate_closed_loop_agent("Hierarchical_JEPA_MuZero", model_hybrid, test_env, num_episodes=3)
    _, _, lat_muzero = evaluate_closed_loop_agent("Pure_MuZero", model_muzero, test_env, num_episodes=3)
    _, _, lat_recon = evaluate_closed_loop_agent("Pure_Reconstruction", model_recon, test_env, num_episodes=3)
    
    final_comparison = {
        "Reconstruction": {
            "final_return": tracking_data["Reconstruction"]["returns"][-1],
            "final_capture_rate": tracking_data["Reconstruction"]["capture_rates"][-1],
            "final_task_r2": tracking_data["Reconstruction"]["task_r2"][-1],
            "step_latency_ms": lat_recon,
            "total_train_sec": tracking_data["Reconstruction"]["train_time"]
        },
        "Pure_MuZero": {
            "final_return": tracking_data["Pure_MuZero"]["returns"][-1],
            "final_capture_rate": tracking_data["Pure_MuZero"]["capture_rates"][-1],
            "final_task_r2": tracking_data["Pure_MuZero"]["task_r2"][-1],
            "step_latency_ms": lat_muzero,
            "total_train_sec": tracking_data["Pure_MuZero"]["train_time"]
        },
        "Hierarchical_JEPA_MuZero": {
            "final_return": tracking_data["Hierarchical_JEPA_MuZero"]["returns"][-1],
            "final_capture_rate": tracking_data["Hierarchical_JEPA_MuZero"]["capture_rates"][-1],
            "final_task_r2": tracking_data["Hierarchical_JEPA_MuZero"]["task_r2"][-1],
            "step_latency_ms": lat_hybrid,
            "total_train_sec": tracking_data["Hierarchical_JEPA_MuZero"]["train_time"]
        }
    }
    
    # Save Metrics JSON
    json_path = os.path.join(curr_dir, "hierarchical_hybrid_metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "noise_ratio": noise_ratio,
            "learning_trajectories": tracking_data,
            "final_comparison": final_comparison,
            "total_benchmark_time_sec": total_duration
        }, f, indent=2, ensure_ascii=False)
    print(f"Metrics written to: {json_path}")
    
    # 4. Generate Visualizations
    generate_hybrid_charts(tracking_data, final_comparison)


def generate_hybrid_charts(trajectories, final_metrics):
    """Generates two publication-grade comparison figures for Phase 2."""
    import matplotlib.pyplot as plt
    plt.style.use('default')
    plt.rcParams['font.family'] = 'DejaVu Sans'
    
    colors = {
        "Reconstruction": "#E63946",            # Red
        "Pure_MuZero": "#E76F51",               # Coral / Orange
        "Hierarchical_JEPA_MuZero": "#2A9D8F"   # Teal / Emerald
    }
    labels = {
        "Reconstruction": "Pure Reconstruction (VAE-RSSM)",
        "Pure_MuZero": "Pure End-to-End MuZero",
        "Hierarchical_JEPA_MuZero": "Hierarchical JEPA-MuZero (Proposed)"
    }
    markers = {"Reconstruction": "o", "Pure_MuZero": "s", "Hierarchical_JEPA_MuZero": "D"}
    
    epochs = trajectories["checkpoints"]
    
    # ----------------------------------------------------
    # Figure 1: Planning Learning Curves over Epochs (2 Panels)
    # ----------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), dpi=300)
    fig.suptitle("Phase 2 Adversarial Benchmark: Learning Dynamics Under 80% Visual Distraction",
                 fontsize=13, fontweight='bold', y=0.98)
    
    # Panel A: Cumulative Episode Return
    ax1 = axes[0]
    for k in ["Reconstruction", "Pure_MuZero", "Hierarchical_JEPA_MuZero"]:
        ax1.plot(epochs, trajectories[k]["returns"], marker=markers[k], color=colors[k],
                 label=labels[k], linewidth=2.4, markersize=7)
    ax1.set_title("A. Closed-Loop Evaluation Return Progression", fontsize=11, fontweight='bold', pad=8)
    ax1.set_xlabel("Training Epochs", fontsize=10, fontweight='bold')
    ax1.set_ylabel("Average Episode Return", fontsize=10, fontweight='bold')
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend(loc="lower right", framealpha=0.95, fontsize=9.5)
    
    # Panel B: Target Capture Success Rate (%)
    ax2 = axes[1]
    for k in ["Reconstruction", "Pure_MuZero", "Hierarchical_JEPA_MuZero"]:
        rates = [r * 100 for r in trajectories[k]["capture_rates"]]
        ax2.plot(epochs, rates, marker=markers[k], color=colors[k],
                 label=labels[k], linewidth=2.4, markersize=7)
    ax2.set_title("B. Target Capture Success Rate (% Time in Goal Zone)", fontsize=11, fontweight='bold', pad=8)
    ax2.set_xlabel("Training Epochs", fontsize=10, fontweight='bold')
    ax2.set_ylabel("Capture Success Rate (%)", fontsize=10, fontweight='bold')
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.legend(loc="upper left", framealpha=0.95, fontsize=9.5)
    
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    curve_path = os.path.join(curr_dir, "hierarchical_hybrid_planning_curve.png")
    plt.savefig(curve_path, dpi=300)
    plt.close()
    print(f"Saved: {curve_path}")
    
    # ----------------------------------------------------
    # Figure 2: Comprehensive Multi-Metric Comparison (3 Panels)
    # ----------------------------------------------------
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=300)
    fig.suptitle("Hierarchical Unified Architecture vs Baselines under 80% Noise",
                 fontsize=13, fontweight='bold', y=0.98)
                 
    models_key = ["Reconstruction", "Pure_MuZero", "Hierarchical_JEPA_MuZero"]
    names = ["Reconstruction\n(VAE-RSSM)", "Pure End-to-End\nMuZero", "Hierarchical\nJEPA-MuZero"]
    bar_colors = [colors[k] for k in models_key]
    
    # Panel 1: Final Capture Success Rate
    ax1 = axes[0]
    cap_vals = [final_metrics[k]["final_capture_rate"] * 100 for k in models_key]
    bars1 = ax1.bar(names, cap_vals, color=bar_colors, alpha=0.88, width=0.55)
    ax1.set_title("A. Target Capture Rate (%)", fontsize=11, fontweight='bold', pad=8)
    ax1.set_ylabel("Success Rate (%)", fontsize=10, fontweight='bold')
    ax1.grid(axis='y', linestyle='--', alpha=0.6)
    for b in bars1:
        h = b.get_height()
        ax1.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                     textcoords="offset points", ha='center', va='bottom', fontsize=10, fontweight='bold')
                     
    # Panel 2: Latent Task Probe R^2 Score
    ax2 = axes[1]
    r2_vals = [final_metrics[k]["final_task_r2"] for k in models_key]
    bars2 = ax2.bar(names, r2_vals, color=bar_colors, alpha=0.88, width=0.55)
    ax2.set_title("B. Task Representation Probe R^2", fontsize=11, fontweight='bold', pad=8)
    ax2.set_ylabel("Linear Probe R^2", fontsize=10, fontweight='bold')
    ax2.set_ylim(0.0, 0.6)
    ax2.grid(axis='y', linestyle='--', alpha=0.6)
    for b in bars2:
        h = b.get_height()
        ax2.annotate(f"{h:.3f}", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                     textcoords="offset points", ha='center', va='bottom', fontsize=10, fontweight='bold')
                     
    # Panel 3: Step Inference / Planning Latency (ms)
    ax3 = axes[2]
    lat_vals = [final_metrics[k]["step_latency_ms"] for k in models_key]
    bars3 = ax3.bar(names, lat_vals, color=bar_colors, alpha=0.88, width=0.55)
    ax3.set_title("C. Decision Latency per Step (ms)", fontsize=11, fontweight='bold', pad=8)
    ax3.set_ylabel("Latency (milliseconds)", fontsize=10, fontweight='bold')
    ax3.grid(axis='y', linestyle='--', alpha=0.6)
    for b in bars3:
        h = b.get_height()
        ax3.annotate(f"{h:.2f}ms", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                     textcoords="offset points", ha='center', va='bottom', fontsize=10, fontweight='bold')
                     
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    comp_path = os.path.join(curr_dir, "hybrid_vs_baseline_comparison.png")
    plt.savefig(comp_path, dpi=300)
    plt.close()
    print(f"Saved: {comp_path}")


if __name__ == "__main__":
    run_phase2_benchmark()
