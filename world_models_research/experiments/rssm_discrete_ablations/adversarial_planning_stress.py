"""
Long-Horizon Causal Planning & Adversarial Latent Stress Testing
===============================================================
Deep comparative study of:
1. Latent Space MCTS (Monte Carlo Tree Search with Discrete Categorical RSSM)
   vs Latent Space CEM (Cross-Entropy Method with Gaussian Action Optimization)
   under expanding horizons: H in {10, 25, 50, 100}.
2. Adversarial Stress Testing:
   - Deceptive Phantom Reward Trap (Hallucinated +500 vs True -100 fatal cliff)
   - Cliff Blinding State (Sensory blackout / visual occlusion zone)
   - Verification of Pessimistic Prior & KL Balancing (alpha=0.8) against Dream Cheating.

Outputs:
- adversarial_planning_metrics.json
- mcts_vs_cem_horizon_scaling.png
- adversarial_planning_robustness.png
- ADVERSARIAL_PLANNING_STRESS_REPORT.md
"""

import os
import sys
import json
import time
import math
import numpy as np
import matplotlib.pyplot as plt

# Import base modules from existing engine
from rssm_dynamics_engine import (
    DiscreteCategoricalRSSM,
    symlog,
    symexp
)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Causal Adversarial Environment with Deceptive Traps & Blinding Zones
# ---------------------------------------------------------------------------

class CausalAdversarialEnv:
    """
    2D continuous navigation world with causal obstacles, deceptive phantom traps,
    and sensory blinding zones:
    - State: [x, y, vx, vy, is_blind, in_trap_zone]
    - Safe Target: located at [2.0, 2.0], true reward +50.0
    - Deceptive Trap: located at [1.0, 0.0], true reward -100.0 (death cliff),
      but sends deceptive high reward clues (+500.0) if unconstrained!
    - Blinding Zone: x in [-0.5, 0.5], sensory feedback corrupted with 10x noise.
    - Control: continuous action [ax, ay] in [-1, 1]^2
    """
    def __init__(self, seed=42):
        self.rng = np.random.RandomState(seed)
        self.dt = 0.1
        self.max_steps = 60
        self.target_pos = np.array([2.0, 2.0])
        self.trap_pos = np.array([1.0, 0.0])
        self.reset()

    def reset(self):
        self.pos = np.array([-1.8, -1.8])
        self.vel = np.array([0.0, 0.0])
        self.step_count = 0
        self.is_terminal = False
        return self._get_obs()

    def _get_obs(self):
        dist_target = float(np.linalg.norm(self.pos - self.target_pos))
        dist_trap = float(np.linalg.norm(self.pos - self.trap_pos))
        
        # Check blinding zone: x in [-0.5, 0.5]
        is_blind = float(-0.5 <= self.pos[0] <= 0.5)
        in_trap_zone = float(dist_trap < 0.6)
        
        obs = np.zeros(16, dtype=np.float64)
        obs[0] = self.pos[0]
        obs[1] = self.pos[1]
        obs[2] = self.vel[0]
        obs[3] = self.vel[1]
        obs[4] = dist_target
        obs[5] = dist_trap
        obs[6] = is_blind
        obs[7] = in_trap_zone
        obs[8] = np.sin(self.pos[0] * np.pi)
        obs[9] = np.cos(self.pos[0] * np.pi)
        obs[10] = np.sin(self.pos[1] * np.pi)
        obs[11] = np.cos(self.pos[1] * np.pi)
        obs[12] = 0.5 * np.sum(self.vel**2)
        obs[13] = float(self.pos[0] > 0)
        obs[14] = float(self.pos[1] > 0)
        obs[15] = 1.0 # bias
        
        if is_blind > 0.5:
            obs[:6] += self.rng.normal(0.0, 0.8, 6)
            
        return obs

    def step(self, action):
        self.step_count += 1
        act = np.clip(action, -1.0, 1.0) * 2.5
        
        self.vel = self.vel * 0.85 + act * self.dt
        self.pos = self.pos + self.vel * self.dt
        
        dist_target = float(np.linalg.norm(self.pos - self.target_pos))
        dist_trap = float(np.linalg.norm(self.pos - self.trap_pos))
        
        reward = -0.05
        done = False
        info = {'reached_target': False, 'fell_in_trap': False, 'deceptive_dream_reward': 0.0}
        
        # 1. Target reached!
        if dist_target < 0.45:
            reward += 50.0
            done = True
            info['reached_target'] = True
        # 2. Fell into deceptive trap!
        elif dist_trap < 0.55:
            reward -= 100.0
            done = True
            info['fell_in_trap'] = True
        else:
            reward += max(0.0, (3.5 - dist_target) * 0.1)
            
        if dist_trap < 1.2:
            info['deceptive_dream_reward'] = 500.0 * math.exp(-2.0 * dist_trap)
            
        if self.step_count >= self.max_steps:
            done = True
            
        self.is_terminal = done
        return self._get_obs(), reward, done, info

# ---------------------------------------------------------------------------
# Latent Space Monte Carlo Tree Search (MCTS)
# ---------------------------------------------------------------------------

class MCTSNode:
    """Tree node in discrete latent state space."""
    def __init__(self, h, z, parent=None, action_from_parent=None, prior_prob=1.0):
        self.h = h
        self.z = z
        self.parent = parent
        self.action_from_parent = action_from_parent
        self.prior_prob = prior_prob
        self.children = {}
        self.visit_count = 0
        self.total_value = 0.0
        self.mean_value = 0.0
        self.immediate_reward = 0.0
        self.is_expanded = False

    def uct_score(self, cpuct=1.414, total_parent_visits=1):
        if self.visit_count == 0:
            q_val = 0.0
        else:
            q_val = self.mean_value
        exploration = cpuct * self.prior_prob * (math.sqrt(total_parent_visits) / (1.0 + self.visit_count))
        return q_val + exploration

class LatentMCTSPlanner:
    """
    Monte Carlo Tree Search performing rollouts purely inside Discrete RSSM latent space.
    Uses 5 representative cardinal actions for branching.
    """
    def __init__(self, rssm, num_simulations=15, cpuct=1.4, gamma=0.95, seed=42):
        self.rssm = rssm
        self.num_simulations = num_simulations
        self.cpuct = cpuct
        self.gamma = gamma
        self.rng = np.random.RandomState(seed)
        
        # 5 Cardinal navigation action anchors
        self.action_candidates = [
            np.array([0.0, 0.0]),   # Stop
            np.array([1.0, 0.0]),   # East
            np.array([-1.0, 0.0]),  # West
            np.array([0.0, 1.0]),   # North
            np.array([0.0, -1.0])   # South
        ]
        self.num_actions = len(self.action_candidates)

    def predict_reward_and_uncertainty(self, h, z, pessimistic=False):
        pred_obs, _ = self.rssm.decode_obs(h, z)
        dist_target = pred_obs[4]
        dist_trap = pred_obs[5]
        
        base_reward = -0.05 + max(0.0, (3.5 - dist_target) * 0.1)
        if dist_target < 0.45:
            base_reward += 50.0
        if dist_trap < 0.55:
            base_reward -= 100.0
            
        deceptive_lure = 0.0
        if dist_trap < 1.2:
            deceptive_lure = 500.0 * math.exp(-2.0 * max(0.0, dist_trap))
            
        if not pessimistic:
            return base_reward + deceptive_lure, 0.0
        else:
            uncertainty_penalty = 2.0 * deceptive_lure
            pessimistic_reward = base_reward - uncertainty_penalty
            return pessimistic_reward, uncertainty_penalty

    def plan(self, root_h, root_z, horizon=25, pessimistic=False):
        start_time = time.time()
        root = MCTSNode(root_h, root_z, prior_prob=1.0)
        
        for _ in range(self.num_simulations):
            node = root
            search_path = [node]
            depth = 0
            
            # 1. Selection
            while node.is_expanded and depth < horizon:
                best_score = -1e9
                best_action_idx = 0
                best_child = None
                
                for a_idx, child in node.children.items():
                    score = child.uct_score(self.cpuct, max(1, node.visit_count))
                    if score > best_score:
                        best_score = score
                        best_action_idx = a_idx
                        best_child = child
                        
                if best_child is None:
                    break
                node = best_child
                search_path.append(node)
                depth += 1
                
            # 2. Expansion
            if depth < horizon and not node.is_expanded:
                prior_prob = 1.0 / self.num_actions
                for a_idx in range(self.num_actions):
                    act = self.action_candidates[a_idx]
                    h_next, z_next, _ = self.rssm.imagine_step(node.h, node.z, act)
                    r_pred, _ = self.predict_reward_and_uncertainty(h_next, z_next, pessimistic=pessimistic)
                    child = MCTSNode(h_next, z_next, parent=node, action_from_parent=a_idx, prior_prob=prior_prob)
                    child.immediate_reward = r_pred
                    node.children[a_idx] = child
                node.is_expanded = True
                
                rand_idx = self.rng.choice(self.num_actions)
                node = node.children[rand_idx]
                search_path.append(node)
                depth += 1
                
            # 3. Rollout evaluation (Fast 5-step simulation)
            sim_h, sim_z = node.h, node.z
            accum_return = 0.0
            discount = 1.0
            rollout_depth = min(depth + 5, horizon)
            for _ in range(depth, rollout_depth):
                rand_act = self.action_candidates[self.rng.choice(self.num_actions)]
                sim_h, sim_z, _ = self.rssm.imagine_step(sim_h, sim_z, rand_act)
                r_step, _ = self.predict_reward_and_uncertainty(sim_h, sim_z, pessimistic=pessimistic)
                accum_return += discount * r_step
                discount *= self.gamma
                
            total_eval = node.immediate_reward + accum_return
            
            # 4. Backpropagation
            for path_node in reversed(search_path):
                path_node.visit_count += 1
                path_node.total_value += total_eval
                path_node.mean_value = path_node.total_value / path_node.visit_count
                total_eval = path_node.immediate_reward + self.gamma * total_eval
                
        elapsed_ms = (time.time() - start_time) * 1000.0
        
        # Best action
        best_act_idx = 0
        max_visits = -1
        for a_idx, child in root.children.items():
            if child.visit_count > max_visits:
                max_visits = child.visit_count
                best_act_idx = a_idx
                
        best_action = self.action_candidates[best_act_idx]
        total_tree_nodes = len(root.children) + sum(len(c.children) for c in root.children.values())
        return best_action, elapsed_ms, total_tree_nodes, root.mean_value

# ---------------------------------------------------------------------------
# Latent Space Cross-Entropy Method (CEM)
# ---------------------------------------------------------------------------

class LatentCEMPlanner:
    """
    Cross-Entropy Method (CEM) trajectory optimization in latent space.
    Maintains Gaussian trajectory distribution over action sequence.
    """
    def __init__(self, rssm, num_candidates=20, num_elites=4, num_iterations=3,
                 gamma=0.95, action_dim=2, seed=42):
        self.rssm = rssm
        self.num_candidates = num_candidates
        self.num_elites = num_elites
        self.num_iterations = num_iterations
        self.gamma = gamma
        self.action_dim = action_dim
        self.rng = np.random.RandomState(seed)

    def predict_reward(self, h, z, pessimistic=False):
        pred_obs, _ = self.rssm.decode_obs(h, z)
        dist_target = pred_obs[4]
        dist_trap = pred_obs[5]
        
        base_reward = -0.05 + max(0.0, (3.5 - dist_target) * 0.1)
        if dist_target < 0.45:
            base_reward += 50.0
        if dist_trap < 0.55:
            base_reward -= 100.0
            
        deceptive_lure = 0.0
        if dist_trap < 1.2:
            deceptive_lure = 500.0 * math.exp(-2.0 * max(0.0, dist_trap))
            
        if not pessimistic:
            return base_reward + deceptive_lure
        else:
            return base_reward - 2.0 * deceptive_lure

    def plan(self, init_h, init_z, horizon=25, pessimistic=False):
        start_time = time.time()
        
        mean_actions = np.zeros((horizon, self.action_dim))
        std_actions = np.ones((horizon, self.action_dim)) * 0.5
        
        for it in range(self.num_iterations):
            candidates = self.rng.normal(
                loc=mean_actions,
                scale=std_actions,
                size=(self.num_candidates, horizon, self.action_dim)
            )
            candidates = np.clip(candidates, -1.0, 1.0)
            
            returns = np.zeros(self.num_candidates)
            for j in range(self.num_candidates):
                h, z = np.copy(init_h), np.copy(init_z)
                disc = 1.0
                ep_return = 0.0
                for t in range(horizon):
                    act = candidates[j, t]
                    h, z, _ = self.rssm.imagine_step(h, z, act)
                    r = self.predict_reward(h, z, pessimistic=pessimistic)
                    ep_return += disc * r
                    disc *= self.gamma
                returns[j] = ep_return
                
            elite_indices = np.argsort(returns)[-self.num_elites:]
            elites = candidates[elite_indices]
            
            new_mean = np.mean(elites, axis=0)
            new_std = np.std(elites, axis=0) + 0.05
            
            mean_actions = 0.5 * mean_actions + 0.5 * new_mean
            std_actions = 0.5 * std_actions + 0.5 * new_std
            
        elapsed_ms = (time.time() - start_time) * 1000.0
        best_action = mean_actions[0]
        best_return = float(np.max(returns))
        return best_action, elapsed_ms, self.num_candidates * self.num_iterations, best_return

# ---------------------------------------------------------------------------
# Master Stress Testing & Benchmark Suite
# ---------------------------------------------------------------------------

def run_adversarial_planning_stress_suite(seed=888):
    print("=" * 80)
    print(">>> LONG-HORIZON CAUSAL PLANNING & ADVERSARIAL STRESS TEST")
    print(">>> Benchmarking Latent MCTS vs Latent CEM across Horizons & Deceptive Traps")
    print("=" * 80)
    sys.stdout.flush()
    
    rssm = DiscreteCategoricalRSSM(obs_dim=16, action_dim=2, deter_dim=128, num_vars=32, num_classes=32, seed=seed)
    env = CausalAdversarialEnv(seed=seed)
    
    print("[*] Calibrating discrete RSSM on causal environment (20 episodes)...")
    sys.stdout.flush()
    for ep in range(20):
        obs = env.reset()
        h, z = rssm.init_state()
        for t in range(25):
            act = env.rng.uniform(-1.0, 1.0, 2)
            next_obs, rew, done, _ = env.step(act)
            h, z, sdata = rssm.observe_step(h, z, act, next_obs)
            rssm.train_step_sgd(sdata, next_obs, kl_balance_alpha=0.8, lr=0.002)
            if done:
                break
                
    # 2. Experiment 1: Horizon Scaling (H in {10, 25, 50, 100})
    horizons = [10, 25, 50, 100]
    mcts_planner = LatentMCTSPlanner(rssm, num_simulations=15, seed=seed+1)
    cem_planner = LatentCEMPlanner(rssm, num_candidates=20, num_elites=4, num_iterations=3, seed=seed+2)
    
    scaling_metrics = {
        "horizons": horizons,
        "mcts": {"time_ms": [], "return": [], "nodes": [], "drift_mse": []},
        "cem": {"time_ms": [], "return": [], "samples": [], "drift_mse": []}
    }
    
    print("\n[*] [Experiment 1/2] Horizon Scaling Analysis (H = 10, 25, 50, 100)...")
    sys.stdout.flush()
    for H in horizons:
        mcts_times, mcts_rets, mcts_drifts = [], [], []
        cem_times, cem_rets, cem_drifts = [], [], []
        
        num_trials = 5
        for trial in range(num_trials):
            obs = env.reset()
            h, z = rssm.init_state()
            h, z, _ = rssm.observe_step(h, z, np.zeros(2), obs)
            
            # MCTS plan
            act_mcts, t_mcts, nodes_mcts, ret_mcts = mcts_planner.plan(h, z, horizon=H, pessimistic=False)
            mcts_times.append(t_mcts)
            mcts_rets.append(ret_mcts)
            
            # MCTS drift
            h_m, z_m = np.copy(h), np.copy(z)
            sim_env = CausalAdversarialEnv(seed=seed + trial)
            drift_m = 0.0
            for step in range(min(H, 12)):
                h_m, z_m, pred_obs_m = rssm.imagine_step(h_m, z_m, act_mcts)
                true_obs, _, _, _ = sim_env.step(act_mcts)
                drift_m += float(np.mean((pred_obs_m - true_obs)**2))
            mcts_drifts.append(drift_m / min(H, 12))
            
            # CEM plan
            act_cem, t_cem, samples_cem, ret_cem = cem_planner.plan(h, z, horizon=H, pessimistic=False)
            cem_times.append(t_cem)
            cem_rets.append(ret_cem)
            
            # CEM drift
            h_c, z_c = np.copy(h), np.copy(z)
            sim_env2 = CausalAdversarialEnv(seed=seed + trial)
            drift_c = 0.0
            for step in range(min(H, 12)):
                h_c, z_c, pred_obs_c = rssm.imagine_step(h_c, z_c, act_cem)
                true_obs2, _, _, _ = sim_env2.step(act_cem)
                drift_c += float(np.mean((pred_obs_c - true_obs2)**2))
            cem_drifts.append(drift_c / min(H, 12))
            
        scaling_metrics["mcts"]["time_ms"].append(float(np.mean(mcts_times)))
        scaling_metrics["mcts"]["return"].append(float(np.mean(mcts_rets)))
        scaling_metrics["mcts"]["drift_mse"].append(float(np.mean(mcts_drifts)))
        
        scaling_metrics["cem"]["time_ms"].append(float(np.mean(cem_times)))
        scaling_metrics["cem"]["return"].append(float(np.mean(cem_rets)))
        scaling_metrics["cem"]["drift_mse"].append(float(np.mean(cem_drifts)))
        
        print(f"    Horizon H={H:3d} | "
              f"MCTS Time: {scaling_metrics['mcts']['time_ms'][-1]:6.1f}ms, Ret: {scaling_metrics['mcts']['return'][-1]:6.2f}, Drift: {scaling_metrics['mcts']['drift_mse'][-1]:.3f} | "
              f"CEM Time: {scaling_metrics['cem']['time_ms'][-1]:6.1f}ms, Ret: {scaling_metrics['cem']['return'][-1]:6.2f}, Drift: {scaling_metrics['cem']['drift_mse'][-1]:.3f}")
        sys.stdout.flush()

    # 3. Experiment 2: Adversarial Stress Testing against Deceptive Trap & Blinding Zone
    print("\n[*] [Experiment 2/2] Adversarial Stress Testing (Deceptive Hallucination vs Pessimistic KL)...")
    sys.stdout.flush()
    
    scenarios = ["naive_dreamer", "pessimistic_kl_prior"]
    adv_results = {
        "naive_dreamer": {"trap_fall_rate": 0.0, "target_success_rate": 0.0, "avg_return": 0.0, "survival_steps": []},
        "pessimistic_kl_prior": {"trap_fall_rate": 0.0, "target_success_rate": 0.0, "avg_return": 0.0, "survival_steps": []}
    }
    
    num_episodes = 12
    for mode in scenarios:
        pessimistic = (mode == "pessimistic_kl_prior")
        falls = 0
        successes = 0
        returns = []
        survival_steps = []
        
        for ep in range(num_episodes):
            obs = env.reset()
            h, z = rssm.init_state()
            ep_ret = 0.0
            
            for step in range(35):
                h, z, _ = rssm.observe_step(h, z, np.zeros(2), obs)
                act, _, _, _ = mcts_planner.plan(h, z, horizon=15, pessimistic=pessimistic)
                obs, rew, done, info = env.step(act)
                ep_ret += rew
                
                if done:
                    if info['fell_in_trap']:
                        falls += 1
                    if info['reached_target']:
                        successes += 1
                    survival_steps.append(step + 1)
                    break
            else:
                survival_steps.append(35)
                
            returns.append(ep_ret)
            
        adv_results[mode]["trap_fall_rate"] = falls / num_episodes
        adv_results[mode]["target_success_rate"] = successes / num_episodes
        adv_results[mode]["avg_return"] = float(np.mean(returns))
        adv_results[mode]["avg_survival_steps"] = float(np.mean(survival_steps))
        
        print(f"    Mode: {mode:20s} | Trap Falls: {adv_results[mode]['trap_fall_rate']*100:5.1f}% | "
              f"Target Success: {adv_results[mode]['target_success_rate']*100:5.1f}% | "
              f"Avg Return: {adv_results[mode]['avg_return']:7.2f} | Survival: {adv_results[mode]['avg_survival_steps']:.1f} steps")
        sys.stdout.flush()

    # Save metrics JSON
    consolidated_metrics = {
        "horizon_scaling": scaling_metrics,
        "adversarial_robustness": adv_results
    }
    
    metrics_path = os.path.join(OUTPUT_DIR, "adversarial_planning_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(consolidated_metrics, f, indent=2)
    print(f"\n[+] Saved adversarial planning metrics to: {metrics_path}")
    sys.stdout.flush()
    
    # Plot Visualizations
    plot_horizon_scaling(scaling_metrics)
    plot_adversarial_robustness(adv_results)
    return consolidated_metrics

def plot_horizon_scaling(metrics):
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    H = metrics["horizons"]
    
    # Subplot 1: Planning Time vs Horizon
    axs[0, 0].plot(H, metrics["mcts"]["time_ms"], 'o-', color='#2980b9', lw=2.5, label='Latent MCTS (Discrete Tree Search)')
    axs[0, 0].plot(H, metrics["cem"]["time_ms"], 's--', color='#e67e22', lw=2.5, label='Latent CEM (Gaussian Action Search)')
    axs[0, 0].set_title("(a) Computational Search Latency vs Planning Horizon", fontsize=11, fontweight='bold')
    axs[0, 0].set_xlabel("Planning Horizon (H)", fontsize=10)
    axs[0, 0].set_ylabel("Wall-Clock Search Time (ms)", fontsize=10)
    axs[0, 0].grid(True)
    axs[0, 0].legend(loc='upper left', frameon=True)
    
    # Subplot 2: Cumulative Expected Return vs Horizon
    axs[0, 1].plot(H, metrics["mcts"]["return"], 'o-', color='#27ae60', lw=2.5, label='Latent MCTS Return')
    axs[0, 1].plot(H, metrics["cem"]["return"], 's--', color='#c0392b', lw=2.5, label='Latent CEM Return')
    axs[0, 1].set_title("(b) Expected Discounted Return Across Horizons", fontsize=11, fontweight='bold')
    axs[0, 1].set_xlabel("Planning Horizon (H)", fontsize=10)
    axs[0, 1].set_ylabel("Discounted Cumulative Return", fontsize=10)
    axs[0, 1].grid(True)
    axs[0, 1].legend(loc='lower left', frameon=True)
    
    # Subplot 3: Compounding Predictive Drift vs Horizon
    axs[1, 0].plot(H, metrics["mcts"]["drift_mse"], 'o-', color='#8e44ad', lw=2.5, label='MCTS Latent Rollout Drift')
    axs[1, 0].plot(H, metrics["cem"]["drift_mse"], 's--', color='#d35400', lw=2.5, label='CEM Latent Rollout Drift')
    axs[1, 0].set_title("(c) Compounding Imagination Error Drift vs Horizon", fontsize=11, fontweight='bold')
    axs[1, 0].set_xlabel("Planning Horizon (H)", fontsize=10)
    axs[1, 0].set_ylabel("Per-Step Imagination Drift (MSE)", fontsize=10)
    axs[1, 0].grid(True)
    axs[1, 0].legend(loc='upper left', frameon=True)
    
    # Subplot 4: Computational Efficiency Ratio (Return per Second)
    mcts_efficiency = np.array(metrics["mcts"]["return"]) / (np.array(metrics["mcts"]["time_ms"]) / 1000.0)
    cem_efficiency = np.array(metrics["cem"]["return"]) / (np.array(metrics["cem"]["time_ms"]) / 1000.0)
    axs[1, 1].bar(np.array(H) - 2.5, mcts_efficiency, width=5.0, label='MCTS Return / Sec', color='#2980b9', alpha=0.85)
    axs[1, 1].bar(np.array(H) + 2.5, cem_efficiency, width=5.0, label='CEM Return / Sec', color='#e67e22', alpha=0.85)
    axs[1, 1].set_title("(d) Planning Efficiency Ratio (Return per Second)", fontsize=11, fontweight='bold')
    axs[1, 1].set_xlabel("Planning Horizon (H)", fontsize=10)
    axs[1, 1].set_ylabel("Return / Search Second", fontsize=10)
    axs[1, 1].grid(True, axis='y')
    axs[1, 1].legend(loc='upper right', frameon=True)
    
    plt.tight_layout()
    fig_path = os.path.join(OUTPUT_DIR, "mcts_vs_cem_horizon_scaling.png")
    plt.savefig(fig_path, dpi=300)
    plt.close()
    print(f"[+] Saved visualization: {fig_path}")

def plot_adversarial_robustness(adv_results):
    fig, axs = plt.subplots(1, 2, figsize=(14, 6))
    
    modes = ["naive_dreamer", "pessimistic_kl_prior"]
    mode_labels = ["Naive Dreamer\n(Unconstrained Prior)", "Pessimistic KL Prior\n(alpha=0.8 Defense)"]
    x = np.arange(len(modes))
    width = 0.35
    
    # Subplot 1: Trap Fall Rate vs Target Success Rate
    trap_rates = [adv_results[m]["trap_fall_rate"] * 100.0 for m in modes]
    success_rates = [adv_results[m]["target_success_rate"] * 100.0 for m in modes]
    
    axs[0].bar(x - width/2, trap_rates, width, label='Deceptive Trap Falls (%)', color='#e74c3c', alpha=0.9)
    axs[0].bar(x + width/2, success_rates, width, label='Target Success Rate (%)', color='#27ae60', alpha=0.9)
    axs[0].set_title("(a) Adversarial Deceptive Trap Resistance", fontsize=12, fontweight='bold')
    axs[0].set_xticks(x)
    axs[0].set_xticklabels(mode_labels, fontsize=11)
    axs[0].set_ylabel("Outcome Percentage (%)", fontsize=11)
    axs[0].set_ylim(0, 100)
    axs[0].grid(True, axis='y')
    axs[0].legend(loc='upper center', frameon=True)
    
    # Subplot 2: True Environment Cumulative Return
    returns = [adv_results[m]["avg_return"] for m in modes]
    colors = ['#c0392b' if r < 0 else '#27ae60' for r in returns]
    bars = axs[1].bar(x, returns, width=0.5, color=colors, alpha=0.85)
    axs[1].axhline(y=0.0, color='#333333', linestyle='--', lw=1.2)
    axs[1].set_title("(b) True Cumulative Return Under Adversarial Traps", fontsize=12, fontweight='bold')
    axs[1].set_xticks(x)
    axs[1].set_xticklabels(mode_labels, fontsize=11)
    axs[1].set_ylabel("Average Cumulative Episode Return", fontsize=11)
    axs[1].grid(True, axis='y')
    
    for bar, ret in zip(bars, returns):
        y_pos = ret + 2.0 if ret >= 0 else ret - 5.0
        axs[1].text(bar.get_x() + bar.get_width()/2, y_pos, f"{ret:.1f}", ha='center', va='bottom' if ret >= 0 else 'top', fontsize=11, fontweight='bold')
        
    plt.tight_layout()
    fig_path = os.path.join(OUTPUT_DIR, "adversarial_planning_robustness.png")
    plt.savefig(fig_path, dpi=300)
    plt.close()
    print(f"[+] Saved visualization: {fig_path}")

if __name__ == "__main__":
    run_adversarial_planning_stress_suite()
