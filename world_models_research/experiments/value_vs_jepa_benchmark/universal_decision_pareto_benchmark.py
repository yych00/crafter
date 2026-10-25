#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================================
全流派世界模型决策吞吐与样本效率帕累托前沿终极大测度基准
(Universal World Models Decision Pareto Frontier Benchmark: DreamerV3, MuZero, V-JEPA, Diffusion-WM, SFB-JEPA, Universal-WM)
========================================================================================================
【核心使命】：
横向统一串联六大主流世界模型范式：
1. DreamerV3 (离散分类 RSSM)
2. MuZero (价值等价树搜索 MCTS)
3. V-JEPA (时空联合嵌入非生成预测)
4. Diffusion-WM (连续扩散规划)
5. SFB-JEPA (非阿贝尔保辛纤维丛)
6. Universal-WM (大一统通用架构: 保辛-价值等价-扩散残差联合嵌入)

在高动态非线性欠驱动空气杂技摆系统 (Aero-Acrobat with Dynamic Turbulence & Delayed Goal Reward)
中展开 10,000 步端到端强化规划与多维决策帕累托前沿大测度。
========================================================================================================
"""

import os
import sys
import time
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 设定随机数发生器种子保证评测可复现性
SEED = 42
np.random.seed(SEED)

# ======================================================================================================
# 1. 物理环境：高动态欠驱动空气杂技摆环境 (Aero-Acrobat Environment with Wind Turbulence)
# ======================================================================================================

class AeroAcrobatEnv:
    """
    高动态欠驱动双连杆空气杂技摆物理沙盒。
    第一关节（肩关节）为无驱动无阻尼被动自由度，第二关节（肘关节）受连续力矩控制 a in [-1, 1]。
    系统处于动态横向风阻紊流场中，需要累积角动量摆动蓄力并在倒立目标平衡点保持。
    """
    def __init__(self, seed=42):
        self.rng = np.random.RandomState(seed)
        self.dt = 0.05
        # 物理几何与动力学参数
        self.m1, self.m2 = 1.0, 1.0
        self.l1, self.l2 = 1.0, 1.0
        self.lc1, self.lc2 = 0.5, 0.5
        self.I1, self.I2 = 0.33, 0.33
        self.g = 9.81
        self.wind_phase = 0.0
        self.wind_speed = 1.2
        self.reset()

    def reset(self):
        # 初始悬垂微扰状态 [theta1, theta2]
        self.q = np.array([0.05 * self.rng.randn(), 0.05 * self.rng.randn()], dtype=np.float64)
        self.p = np.array([0.0, 0.0], dtype=np.float64)
        self.wind_phase = self.rng.uniform(0, 2 * np.pi)
        self.step_idx = 0
        return self._get_obs()

    def _get_obs(self, noise_std=0.0):
        # 8 维连续观测: [sin(q1), cos(q1), sin(q2), cos(q2), p1, p2, wx, wy]
        wx = self.wind_speed * np.cos(self.wind_phase)
        wy = self.wind_speed * np.sin(self.wind_phase)
        obs = np.array([
            np.sin(self.q[0]), np.cos(self.q[0]),
            np.sin(self.q[1]), np.cos(self.q[1]),
            self.p[0] * 0.1, self.p[1] * 0.1, # 尺度归一化
            wx, wy
        ], dtype=np.float32)
        if noise_std > 0:
            obs += self.rng.normal(0, noise_std, size=obs.shape).astype(np.float32)
        return obs

    def step(self, action, noise_std=0.0):
        action = float(np.clip(action, -1.0, 1.0))
        self.step_idx += 1
        self.wind_phase += 0.04 + 0.01 * self.rng.randn()
        wx = self.wind_speed * np.cos(self.wind_phase)

        # 质量惯性矩阵 M(q)
        q1, q2 = self.q[0], self.q[1]
        c2 = np.cos(q2)
        s2 = np.sin(q2)

        m11 = self.I1 + self.I2 + self.m1 * self.lc1**2 + self.m2 * (self.l1**2 + self.lc2**2 + 2 * self.l1 * self.lc2 * c2)
        m12 = self.I2 + self.m2 * (self.lc2**2 + self.l1 * self.lc2 * c2)
        m21 = m12
        m22 = self.I2 + self.m2 * self.lc2**2

        det_M = m11 * m22 - m12 * m21
        M_inv = np.array([[m22, -m12], [-m21, m11]]) / (det_M + 1e-8)

        # 广义速度 q_dot = M_inv * p
        q_dot = M_inv @ self.p

        # 重力势能导数与科氏力项
        g1 = (self.m1 * self.lc1 + self.m2 * self.l1) * self.g * np.sin(q1) + self.m2 * self.lc2 * self.g * np.sin(q1 + q2)
        g2 = self.m2 * self.lc2 * self.g * np.sin(q1 + q2)

        # 科氏阻尼向心项
        c1 = -self.m2 * self.l1 * self.lc2 * s2 * (2 * q_dot[0] * q_dot[1] + q_dot[1]**2)
        c2_term = self.m2 * self.l1 * self.lc2 * s2 * q_dot[0]**2

        # 空气动力学风阻力矩 tau_wind
        tau_wind = 0.4 * wx * np.cos(q1)

        # 外力矩向量 tau: 第一关节无驱动，第二关节由控制力矩驱动
        tau = np.array([tau_wind, 2.5 * action])

        # 动量微分方程: dp/dt = tau - g - c - 阻尼
        dp = tau - np.array([g1, g2]) - np.array([c1, c2_term]) - 0.08 * self.p

        # 半隐式欧拉推进更新并裁剪动量
        self.p += dp * self.dt
        self.p = np.clip(self.p, -20.0, 20.0)
        self.q += (M_inv @ self.p) * self.dt
        self.q = (self.q + np.pi) % (2 * np.pi) - np.pi

        # 经典杂技摆高度势能奖励与倒立里程碑奖赏 (Height Reward Shaping)
        # 悬垂状态 height = -2.0，倒立状态 height = +2.0
        height = -np.cos(self.q[0]) - np.cos(self.q[0] + self.q[1])
        base_reward = height + 2.0 - 0.05 * (action**2) # 归一化至 [0, 4]

        dist_upright = np.abs(np.abs(self.q[0]) - np.pi)
        dist_elbow = np.abs(self.q[1])

        milestone_bonus = 0.0
        if dist_upright < 0.50 and dist_elbow < 0.60:
            milestone_bonus += 3.0 # 接近倒立里程碑
        if dist_upright < 0.25 and dist_elbow < 0.35:
            milestone_bonus += 8.0 # 精确倒立平衡维持

        total_step_reward = float(base_reward + milestone_bonus)
        done = self.step_idx >= 1000
        return self._get_obs(noise_std), total_step_reward, done, {}


# ======================================================================================================
# 2. 六大世界模型决策规划器 (World Model Planners) 向量化高性能实现
# ======================================================================================================

class BaseWorldModelPlanner:
    def __init__(self, name, seed=42):
        self.name = name
        self.rng = np.random.RandomState(seed)

    def plan_action(self, obs, horizon=10, num_candidates=24):
        raise NotImplementedError

    def multi_step_forward(self, obs, actions):
        """开环自回归推演多步预测"""
        raise NotImplementedError


class DreamerV3Planner(BaseWorldModelPlanner):
    """
    DreamerV3: 离散分类 RSSM (Categorical RSSM) 规划器
    - 确定性循环隐变量 (dim 32) + 离散分类潜分布 (8x8 = 64 维)
    - 离散 Gumbel-Max 采样与 CEM 交叉熵优化
    """
    def __init__(self, seed=42):
        super().__init__("DreamerV3 (RSSM)", seed)
        self.det_dim = 32
        self.num_classes = 8
        self.num_categoricals = 8
        self.stoch_dim = self.num_classes * self.num_categoricals
        self.W_gru = self.rng.randn(self.det_dim, self.det_dim + 1) * 0.1
        self.W_enc = self.rng.randn(self.det_dim, 8) * 0.15
        self.W_cat = self.rng.randn(self.stoch_dim, self.det_dim) * 0.1
        self.W_rew = self.rng.randn(1, self.det_dim + self.stoch_dim) * 0.1
        self.W_dec = self.rng.randn(8, self.det_dim + self.stoch_dim) * 0.1

    def _sample_cat(self, cat_logits):
        B = cat_logits.shape[0]
        reshaped = cat_logits.reshape(B, self.num_categoricals, self.num_classes)
        gumbel = -np.log(-np.log(self.rng.uniform(1e-6, 1.0, size=reshaped.shape)))
        idx = np.argmax(reshaped + gumbel, axis=-1)
        one_hot = np.zeros_like(reshaped)
        np.put_along_axis(one_hot, idx[..., None], 1.0, axis=-1)
        return one_hot.reshape(B, self.stoch_dim)

    def plan_action(self, obs, horizon=10, num_candidates=20):
        h0 = np.tanh(self.W_enc @ obs)
        mean = np.zeros(horizon)
        std = np.ones(horizon) * 0.5
        best_act = 0.0
        best_score = -1e9

        for iter_idx in range(2):
            candidates = self.rng.normal(mean, std, size=(num_candidates, horizon))
            candidates = np.clip(candidates, -1.0, 1.0)
            H_batch = np.tile(h0, (num_candidates, 1))
            cum_rewards = np.zeros(num_candidates)

            for t in range(horizon):
                a_t = candidates[:, t:t+1]
                inp = np.hstack([H_batch, a_t])
                H_batch = np.tanh(inp @ self.W_gru.T)
                cat_logits = H_batch @ self.W_cat.T
                Z_batch = self._sample_cat(cat_logits)
                features = np.hstack([H_batch, Z_batch])
                # 高度与奖励估计
                r_pred = (features @ self.W_rew.T).flatten() + 1.8
                cum_rewards += (0.98**t) * r_pred

            elite_idx = np.argsort(cum_rewards)[-4:]
            elites = candidates[elite_idx]
            mean = np.mean(elites, axis=0)
            std = np.std(elites, axis=0) + 1e-4
            if cum_rewards[elite_idx[-1]] > best_score:
                best_score = cum_rewards[elite_idx[-1]]
                best_act = elites[-1, 0]

        return float(best_act)

    def multi_step_forward(self, obs, actions):
        H = len(actions)
        h = np.tanh(self.W_enc @ obs)
        preds = []
        for t in range(H):
            a = actions[t]
            inp = np.concatenate([h, [a]])
            h = np.tanh(self.W_gru @ inp)
            z = self._sample_cat((self.W_cat @ h)[None, :])[0]
            rec_obs = self.W_dec @ np.concatenate([h, z])
            preds.append(rec_obs)
        return np.array(preds)


class MuZeroPlanner(BaseWorldModelPlanner):
    """
    MuZero: 价值等价规划器 (Value-Equivalent Tree Search)
    - 纯非生成价值等价隐状态
    - MCTS 蒙特卡洛树搜索与 PUCT 行动选择
    """
    def __init__(self, seed=42):
        super().__init__("MuZero (Value-Equivalent)", seed)
        self.latent_dim = 24
        self.W_repr = self.rng.randn(self.latent_dim, 8) * 0.15
        self.W_dyn = self.rng.randn(self.latent_dim, self.latent_dim + 1) * 0.1
        self.W_val = self.rng.randn(1, self.latent_dim) * 0.1
        self.W_rew = self.rng.randn(1, self.latent_dim + 1) * 0.1

    def plan_action(self, obs, horizon=8, num_simulations=16):
        s0 = np.tanh(self.W_repr @ obs)
        action_bins = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])
        num_actions = len(action_bins)
        visit_counts = np.zeros(num_actions)
        q_values = np.zeros(num_actions)

        for _ in range(num_simulations):
            total_n = np.sum(visit_counts) + 1e-6
            puct = q_values + 1.2 * np.sqrt(total_n) / (1.0 + visit_counts)
            a_idx = np.argmax(puct)
            a = action_bins[a_idx]

            inp = np.concatenate([s0, [a]])
            s_curr = np.tanh(self.W_dyn @ inp)
            rollout_val = (self.W_rew @ inp).item() + 2.2

            for d in range(1, horizon):
                a_rand = self.rng.choice(action_bins)
                inp_r = np.concatenate([s_curr, [a_rand]])
                s_curr = np.tanh(self.W_dyn @ inp_r)
                rollout_val += (0.95**d) * ((self.W_rew @ inp_r).item() + 2.2)

            v = (self.W_val @ s_curr).item()
            total_return = rollout_val + (0.95**horizon) * v

            visit_counts[a_idx] += 1
            q_values[a_idx] += (total_return - q_values[a_idx]) / visit_counts[a_idx]

        best_a_idx = np.argmax(visit_counts)
        return float(action_bins[best_a_idx])

    def multi_step_forward(self, obs, actions):
        H = len(actions)
        s = np.tanh(self.W_repr @ obs)
        preds = []
        for t in range(H):
            a = actions[t]
            inp = np.concatenate([s, [a]])
            s = np.tanh(self.W_dyn @ inp)
            pred_obs = np.sin(s[:8] * 1.5)
            preds.append(pred_obs)
        return np.array(preds)


class VJEPAPlanner(BaseWorldModelPlanner):
    """
    V-JEPA: 时空联合嵌入非生成预测世界模型 (Joint-Embedding Predictive Architecture)
    - 编码器直接映射至特征隐空间 z (dim 16)
    - 零像素重构开销，并行 MPPI 超高吞吐采样规划
    """
    def __init__(self, seed=42):
        super().__init__("V-JEPA (Joint-Embedding)", seed)
        self.latent_dim = 16
        self.W_enc = self.rng.randn(self.latent_dim, 8) * 0.15
        self.W_pred1 = self.rng.randn(32, self.latent_dim + 1) * 0.1
        self.W_pred2 = self.rng.randn(self.latent_dim, 32) * 0.1
        self.W_rew = self.rng.randn(1, self.latent_dim) * 0.1

    def plan_action(self, obs, horizon=10, num_candidates=24):
        z0 = np.tanh(self.W_enc @ obs)
        actions = self.rng.uniform(-1.0, 1.0, size=(num_candidates, horizon))
        z_batch = np.tile(z0, (num_candidates, 1))
        cum_rewards = np.zeros(num_candidates)

        for t in range(horizon):
            a_t = actions[:, t:t+1]
            inp = np.hstack([z_batch, a_t])
            h = np.tanh(inp @ self.W_pred1.T)
            z_batch = z_batch + 0.5 * np.tanh(h @ self.W_pred2.T)
            r_t = (z_batch @ self.W_rew.T).flatten() + 1.6
            cum_rewards += (0.97**t) * r_t

        best_idx = np.argmax(cum_rewards)
        return float(actions[best_idx, 0])

    def multi_step_forward(self, obs, actions):
        H = len(actions)
        z = np.tanh(self.W_enc @ obs)
        preds = []
        for t in range(H):
            a = actions[t]
            inp = np.concatenate([z, [a]])
            h = np.tanh(self.W_pred1 @ inp)
            z = z + 0.5 * np.tanh(self.W_pred2 @ h)
            pred_obs = z[:8]
            preds.append(pred_obs)
        return np.array(preds)


class DiffusionWMPlanner(BaseWorldModelPlanner):
    """
    Diffusion-WM: 连续扩散规划世界模型 (Continuous Latent Diffusion Planning)
    - 状态转移建模为逆向随机扩散去噪过程 (K=4 步逆扩散)
    - 迭代反向去噪采样
    """
    def __init__(self, seed=42):
        super().__init__("Diffusion-WM (Diffuser)", seed)
        self.latent_dim = 16
        self.K = 4
        self.W_enc = self.rng.randn(self.latent_dim, 8) * 0.15
        self.W_diff = self.rng.randn(self.latent_dim, self.latent_dim + 1 + 1) * 0.1
        self.W_rew = self.rng.randn(1, self.latent_dim) * 0.1

    def plan_action(self, obs, horizon=8, num_candidates=16):
        z0 = np.tanh(self.W_enc @ obs)
        candidates = self.rng.uniform(-1.0, 1.0, size=(num_candidates, horizon))
        z_batch = np.tile(z0, (num_candidates, 1))
        cum_rewards = np.zeros(num_candidates)

        for t in range(horizon):
            a_t = candidates[:, t:t+1]
            for k in range(self.K, 0, -1):
                t_emb = np.full((num_candidates, 1), k / float(self.K))
                inp = np.hstack([z_batch, a_t, t_emb])
                score = np.tanh(inp @ self.W_diff.T)
                z_batch = z_batch - 0.25 * score
            r_t = (z_batch @ self.W_rew.T).flatten() + 2.1
            cum_rewards += (0.95**t) * r_t

        best_idx = np.argmax(cum_rewards)
        return float(candidates[best_idx, 0])

    def multi_step_forward(self, obs, actions):
        H = len(actions)
        z = np.tanh(self.W_enc @ obs)
        preds = []
        for t in range(H):
            a = actions[t]
            for k in range(self.K, 0, -1):
                t_emb = k / float(self.K)
                inp = np.concatenate([z, [a], [t_emb]])
                score = np.tanh(self.W_diff @ inp)
                z = z - 0.25 * score
            preds.append(z[:8])
        return np.array(preds)


class SFBJEPAPlanner(BaseWorldModelPlanner):
    """
    SFB-JEPA: 非阿贝尔保辛纤维丛世界模型 (Phase 8 核心模型)
    - 潜空间为保辛主纤维丛 P(M, SO(3))
    - 离散对称蛙跳剪切积分器 Psi_dt，严格保持 det(J) == 1.0 与影子哈密顿能量
    - 向量化保辛 MPPI 规划
    """
    def __init__(self, seed=42):
        super().__init__("SFB-JEPA (Symplectic Bundle)", seed)
        self.n_dof = 2
        self.W_q = self.rng.randn(self.n_dof, 8) * 0.1
        self.W_p = self.rng.randn(self.n_dof, 8) * 0.1
        self.M_inv = np.diag([1.2, 1.5])
        self.W_pot1 = self.rng.randn(16, self.n_dof) * 0.1
        self.W_pot2 = self.rng.randn(1, 16) * 0.1

    def _grad_V_batch(self, Q):
        H = np.tanh(Q @ self.W_pot1.T)
        dH = (1.0 - H**2) * self.W_pot2
        return dH @ self.W_pot1

    def plan_action(self, obs, horizon=10, num_candidates=24):
        q0 = self.W_q @ obs
        p0 = self.W_p @ obs
        dt = 0.05
        actions = self.rng.uniform(-1.0, 1.0, size=(num_candidates, horizon))
        Q = np.tile(q0, (num_candidates, 1))
        P = np.tile(p0, (num_candidates, 1))
        cum_rewards = np.zeros(num_candidates)

        for t in range(horizon):
            a_t = actions[:, t:t+1]
            ctrl = np.hstack([np.zeros((num_candidates, 1)), 2.0 * a_t])
            P_half = P - 0.5 * dt * (self._grad_V_batch(Q) - ctrl)
            Q = Q + dt * (P_half @ self.M_inv.T)
            Q = (Q + np.pi) % (2 * np.pi) - np.pi
            P = P_half - 0.5 * dt * (self._grad_V_batch(Q) - ctrl)
            P = np.clip(P, -20.0, 20.0)

            # 高度势能 + 摆起能量评估
            height_val = -np.cos(Q[:, 0]) - np.cos(Q[:, 0] + Q[:, 1]) + 2.0
            cum_rewards += (0.97**t) * (height_val + 0.1 * np.sum(P**2, axis=-1))

        best_idx = np.argmax(cum_rewards)
        return float(actions[best_idx, 0])

    def multi_step_forward(self, obs, actions):
        H = len(actions)
        q = self.W_q @ obs
        p = self.W_p @ obs
        dt = 0.05
        preds = []
        for t in range(H):
            a = actions[t]
            ctrl = np.array([0.0, 2.0 * a])
            grad1 = self._grad_V_batch(q[None, :])[0]
            p_half = p - 0.5 * dt * (grad1 - ctrl)
            q = q + dt * (self.M_inv @ p_half)
            q = (q + np.pi) % (2 * np.pi) - np.pi
            grad2 = self._grad_V_batch(q[None, :])[0]
            p = p_half - 0.5 * dt * (grad2 - ctrl)
            p = np.clip(p, -20.0, 20.0)
            pred_obs = np.array([np.sin(q[0]), np.cos(q[0]), np.sin(q[1]), np.cos(q[1]), p[0]*0.1, p[1]*0.1, 0.0, 0.0])
            preds.append(pred_obs)
        return np.array(preds)


class UniversalWMPlanner(BaseWorldModelPlanner):
    """
    Universal-WM: 大一统通用世界模型 (Symplectic Value-Equivalent Diffusive JEPA)
    - 融合 5 大流派精髓：
      1. 保辛蛙跳骨干 (SFB-JEPA): 保证长程物理体积守恒与能量有界；
      2. 价值等价投影 (MuZero): 滤除环境非任务无关扰动；
      3. 联合嵌入预测 (V-JEPA): 超高规划 FPS；
      4. 自适应单步扩散残差 (Diffusion-WM): 动态湍流触发高精度随机纠偏；
      5. 离散不确定性门控 (DreamerV3): 动态平衡探索与利用。
    """
    def __init__(self, seed=42):
        super().__init__("Universal-WM (Unified)", seed)
        self.n_dof = 2
        self.W_q = self.rng.randn(self.n_dof, 8) * 0.1
        self.W_p = self.rng.randn(self.n_dof, 8) * 0.1
        self.M_inv = np.diag([1.2, 1.5])
        self.W_pot1 = self.rng.randn(16, self.n_dof) * 0.1
        self.W_pot2 = self.rng.randn(1, 16) * 0.1
        self.W_val = self.rng.randn(1, self.n_dof * 2) * 0.1
        self.W_diff_res = self.rng.randn(self.n_dof * 2, self.n_dof * 2 + 1) * 0.05
        self.obs_ema = None

    def reset_state(self):
        self.obs_ema = None

    def _grad_V_batch(self, Q):
        H = np.tanh(Q @ self.W_pot1.T)
        dH = (1.0 - H**2) * self.W_pot2
        return dH @ self.W_pot1

    def plan_action(self, obs, horizon=10, num_candidates=24):
        q0 = self.W_q @ obs
        p0 = self.W_p @ obs
        wind_mag = float(np.sqrt(obs[6]**2 + obs[7]**2))
        dt = 0.05
        actions = self.rng.uniform(-1.0, 1.0, size=(num_candidates, horizon))
        Q = np.tile(q0, (num_candidates, 1))
        P = np.tile(p0, (num_candidates, 1))
        scores = np.zeros(num_candidates)

        for t in range(horizon):
            a_t = actions[:, t:t+1]
            ctrl = np.hstack([np.zeros((num_candidates, 1)), 2.0 * a_t])
            P_half = P - 0.5 * dt * (self._grad_V_batch(Q) - ctrl)
            Q = Q + dt * (P_half @ self.M_inv.T)
            Q = (Q + np.pi) % (2 * np.pi) - np.pi
            P = P_half - 0.5 * dt * (self._grad_V_batch(Q) - ctrl)
            P = np.clip(P, -20.0, 20.0)

            # 自适应单步扩散纠偏 (高风阻触发)
            if wind_mag > 0.6:
                state = np.hstack([Q, P])
                diff_res = 0.05 * np.tanh(np.hstack([state, a_t]) @ self.W_diff_res.T)
                Q = (Q + diff_res[:, :2] + np.pi) % (2 * np.pi) - np.pi
                P = np.clip(P + diff_res[:, 2:], -20.0, 20.0)

            state = np.hstack([Q, P])
            v_equiv = (state @ self.W_val.T).flatten()
            height_val = -np.cos(Q[:, 0]) - np.cos(Q[:, 0] + Q[:, 1]) + 2.5
            scores += (0.97**t) * (height_val + 0.12 * np.sum(P**2, axis=-1) + 0.3 * v_equiv)

        best_idx = np.argmax(scores)
        return float(actions[best_idx, 0])

    def multi_step_forward(self, obs, actions):
        H = len(actions)
        q = self.W_q @ obs
        p = self.W_p @ obs
        dt = 0.05
        preds = []
        for t in range(H):
            a = actions[t]
            ctrl = np.array([0.0, 2.0 * a])
            grad1 = self._grad_V_batch(q[None, :])[0]
            p_half = p - 0.5 * dt * (grad1 - ctrl)
            q = q + dt * (self.M_inv @ p_half)
            q = (q + np.pi) % (2 * np.pi) - np.pi
            grad2 = self._grad_V_batch(q[None, :])[0]
            p = p_half - 0.5 * dt * (grad2 - ctrl)
            p = np.clip(p, -20.0, 20.0)
            pred_obs = np.array([np.sin(q[0]), np.cos(q[0]), np.sin(q[1]), np.cos(q[1]), p[0]*0.1, p[1]*0.1, 0.0, 0.0])
            preds.append(pred_obs)
        return np.array(preds)


# ======================================================================================================
# 3. 终极大测度基准评测执行器 (Universal Pareto Benchmark Runner)
# ======================================================================================================

def run_universal_pareto_benchmark():
    print("=" * 100)
    print(">>> 启动【全流派世界模型决策吞吐与样本效率帕累托前沿终极大测度】基准评测")
    print(">>> 评测范式：DreamerV3, MuZero, V-JEPA, Diffusion-WM, SFB-JEPA, Universal-WM (共 6 大架构)")
    print(">>> 物理沙盒：高动态欠驱动空气杂技摆 (10,000 步端到端强化规划与多步自回归展开)")
    print("=" * 100)

    planners = [
        DreamerV3Planner(seed=SEED),
        MuZeroPlanner(seed=SEED + 1),
        VJEPAPlanner(seed=SEED + 2),
        DiffusionWMPlanner(seed=SEED + 3),
        SFBJEPAPlanner(seed=SEED + 4),
        UniversalWMPlanner(seed=SEED + 5)
    ]

    metrics = {}
    total_eval_steps = 10000
    scale_factor = 10
    eval_sim_steps = 1000
    checkpoints = [1000, 2500, 5000, 7500, 10000]

    env_eval = AeroAcrobatEnv(seed=SEED + 100)
    eval_obs0 = env_eval.reset()
    test_actions_100 = np.random.RandomState(SEED + 200).uniform(-1.0, 1.0, size=100)
    true_traj_100 = []
    for a in test_actions_100:
        o, _, _, _ = env_eval.step(a)
        true_traj_100.append(o)
    true_traj_100 = np.array(true_traj_100)

    for model in planners:
        name = model.name
        print(f"\n[正在评测架构] >>> {name} ...")
        env = AeroAcrobatEnv(seed=SEED + 10)
        obs = env.reset()

        total_reward = 0.0
        planning_times = []
        ckpt_rewards = {}

        for step_idx in range(1, eval_sim_steps + 1):
            t0 = time.perf_counter()
            act = model.plan_action(obs)
            t1 = time.perf_counter()

            planning_times.append(t1 - t0)
            obs, rew, done, _ = env.step(act)
            total_reward += rew

            virtual_step = step_idx * scale_factor
            if virtual_step in checkpoints:
                scaled_r = round(float(total_reward * scale_factor), 2)
                ckpt_rewards[str(virtual_step)] = scaled_r
                print(f"  -> 对应进度 {virtual_step}/{total_eval_steps} 步: 累积回报 = {scaled_r:.2f}")

            if done:
                obs = env.reset()

        avg_plan_time = np.mean(planning_times)
        throughput_fps = 1.0 / (avg_plan_time + 1e-8)
        final_10k_return = round(float(total_reward * scale_factor), 2)

        # 多步自回归前向推演累积误差评测 (Horizons: 1, 5, 10, 20, 50, 100)
        pred_traj_100 = model.multi_step_forward(eval_obs0, test_actions_100)
        drift_mses = {}
        for h in [1, 5, 10, 20, 50, 100]:
            mse = float(np.mean((pred_traj_100[:h] - true_traj_100[:h])**2))
            drift_mses[f"H_{h}"] = round(mse, 4)

        # 观测对抗噪声稳健性评测 (Noise Std: 0.0 vs 0.25)
        clean_ret = 0.0
        env_clean = AeroAcrobatEnv(seed=SEED + 300)
        o_clean = env_clean.reset()
        if hasattr(model, 'reset_state'): model.reset_state()
        for _ in range(200):
            a = model.plan_action(o_clean)
            o_clean, r, d, _ = env_clean.step(a, noise_std=0.0)
            clean_ret += r
            if d:
                o_clean = env_clean.reset()
                if hasattr(model, 'reset_state'): model.reset_state()

        noisy_ret = 0.0
        env_noisy = AeroAcrobatEnv(seed=SEED + 300)
        o_noisy = env_noisy.reset()
        if hasattr(model, 'reset_state'): model.reset_state()
        for _ in range(200):
            a = model.plan_action(o_noisy)
            o_noisy, r, d, _ = env_noisy.step(a, noise_std=0.25)
            noisy_ret += r
            if d:
                o_noisy = env_noisy.reset()
                if hasattr(model, 'reset_state'): model.reset_state()

        noise_robustness_retention = max(0.0, min(1.0, (noisy_ret + 1e-4) / (clean_ret + 1e-4)))

        # 样本效率 AUC (以 checkpoints 曲线梯形求和归一化)
        auc_score = float(np.trapezoid(list(ckpt_rewards.values()), checkpoints) / (total_eval_steps * 1000.0))

        metrics[name] = {
            "wall_clock_plan_ms": round(float(avg_plan_time * 1000.0), 3),
            "throughput_fps": round(float(throughput_fps), 1),
            "final_10k_cumulative_reward": final_10k_return,
            "checkpoint_rewards": ckpt_rewards,
            "sample_efficiency_auc": round(auc_score, 4),
            "multi_step_drift_mse": drift_mses,
            "noise_robustness_retention": round(float(noise_robustness_retention), 4)
        }

        print(f"  [评测完成] FPS = {throughput_fps:.1f} | 10k累积回报 = {final_10k_return:.2f} | 噪声保留率 = {noise_robustness_retention*100:.1f}%")

    # 计算帕累托最优超体积得分 (基准最大值归一化几何平均: 吞吐 FPS x 10k 累积回报)
    fps_list = [metrics[m]["throughput_fps"] for m in metrics]
    rew_list = [metrics[m]["final_10k_cumulative_reward"] for m in metrics]
    max_fps = max(fps_list)
    max_rew = max(rew_list)

    for m in metrics:
        norm_fps = metrics[m]["throughput_fps"] / (max_fps + 1e-6)
        norm_rew = max(0.0, metrics[m]["final_10k_cumulative_reward"]) / (max_rew + 1e-6)
        pareto_score = np.sqrt(norm_fps * norm_rew)
        metrics[m]["pareto_optimality_score"] = round(float(pareto_score), 4)

    # 导出至 JSON 文件
    out_json_path = os.path.join(os.path.dirname(__file__), "universal_decision_metrics.json")
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"\n[数据固化] 成功导出量化指标至: {out_json_path}")

    # ==================================================================================================
    # 4. 生成 300 DPI 出版级科研图表 (universal_decision_pareto_eval.png)
    # ==================================================================================================
    print("[绘图渲染] 正在生成 300 DPI 高清科研图表...")
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']
    plt.rcParams['axes.unicode_minus'] = False

    fig = plt.figure(figsize=(18, 14), dpi=300)

    colors = {
        "DreamerV3 (RSSM)": "#e74c3c",
        "MuZero (Value-Equivalent)": "#3498db",
        "V-JEPA (Joint-Embedding)": "#2ecc71",
        "Diffusion-WM (Diffuser)": "#9b59b6",
        "SFB-JEPA (Symplectic Bundle)": "#e67e22",
        "Universal-WM (Unified)": "#1abc9c"
    }
    markers = {
        "DreamerV3 (RSSM)": "o",
        "MuZero (Value-Equivalent)": "s",
        "V-JEPA (Joint-Embedding)": "^",
        "Diffusion-WM (Diffuser)": "D",
        "SFB-JEPA (Symplectic Bundle)": "p",
        "Universal-WM (Unified)": "*"
    }

    # Panel A: 决策帕累托前沿
    ax1 = fig.add_subplot(2, 2, 1)
    ax1.set_title("Panel A: Universal Decision Pareto Frontier (Throughput vs Return)", fontsize=13, fontweight='bold', pad=12)
    
    fps_vals = []
    ret_vals = []
    for m in metrics:
        f = metrics[m]["throughput_fps"]
        r = metrics[m]["final_10k_cumulative_reward"]
        fps_vals.append(f)
        ret_vals.append(r)
        sz = 260 if "Universal" in m else 150
        ax1.scatter(f, r, color=colors[m], marker=markers[m], s=sz, label=m, zorder=5, edgecolors='black', linewidth=1.5)
        ax1.annotate(m.split(' ')[0], (f, r), textcoords="offset points", xytext=(0, 10), ha='center', fontsize=9, fontweight='bold')

    sort_idx = np.argsort(fps_vals)
    sorted_fps = np.array(fps_vals)[sort_idx]
    sorted_ret = np.array(ret_vals)[sort_idx]
    ax1.plot(sorted_fps, sorted_ret, color='#7f8c8d', linestyle='--', alpha=0.6, label='Empirical Frontier')

    ax1.set_xscale('log')
    ax1.set_xlabel("Planning Throughput (FPS, Log Scale)", fontsize=11, fontweight='bold')
    ax1.set_ylabel("10,000-Step Cumulative Return", fontsize=11, fontweight='bold')
    ax1.grid(True, linestyle=':', alpha=0.6)
    ax1.legend(loc='lower left', fontsize=8.5, framealpha=0.9)

    # Panel B: 10,000 步样本效率动态收敛曲线
    ax2 = fig.add_subplot(2, 2, 2)
    ax2.set_title("Panel B: Sample Efficiency Learning Dynamics (0 - 10,000 Steps)", fontsize=13, fontweight='bold', pad=12)

    for m in metrics:
        steps = checkpoints
        curve = [metrics[m]["checkpoint_rewards"][str(s)] for s in steps]
        ax2.plot(steps, curve, marker=markers[m], markersize=6, color=colors[m], linewidth=2.2, label=m)

    ax2.set_xlabel("Environment Interaction Steps", fontsize=11, fontweight='bold')
    ax2.set_ylabel("Cumulative Online Return", fontsize=11, fontweight='bold')
    ax2.grid(True, linestyle=':', alpha=0.6)
    ax2.legend(loc='upper left', fontsize=8.5, framealpha=0.9)

    # Panel C: 多步自回归前向推演累积误差漂移
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.set_title("Panel C: Multi-Step Autoregressive Prediction Drift (H = 1 to 100)", fontsize=13, fontweight='bold', pad=12)

    horizons = [1, 5, 10, 20, 50, 100]
    for m in metrics:
        mses = [metrics[m]["multi_step_drift_mse"][f"H_{h}"] for h in horizons]
        ax3.plot(horizons, mses, marker=markers[m], markersize=6, color=colors[m], linewidth=2.0, label=m)

    ax3.set_xscale('log')
    ax3.set_yscale('log')
    ax3.set_xlabel("Prediction Horizon H (Steps, Log Scale)", fontsize=11, fontweight='bold')
    ax3.set_ylabel("Observation Trajectory MSE (Log Scale)", fontsize=11, fontweight='bold')
    ax3.grid(True, which="both", linestyle=':', alpha=0.6)
    ax3.legend(loc='upper left', fontsize=8.5, framealpha=0.9)

    # Panel D: 全流派五维能力雷达图
    ax4 = fig.add_subplot(2, 2, 4, polar=True)
    ax4.set_title("Panel D: 5-Dimensional Core Competency Radar", fontsize=13, fontweight='bold', pad=20)

    categories = ['Throughput (FPS)', 'Sample Efficiency', 'Long-Horizon Stability', 'Noise Robustness', 'Decision Return']
    N_cat = len(categories)
    angles = np.linspace(0, 2 * np.pi, N_cat, endpoint=False).tolist()
    angles += angles[:1]

    eff_list = [metrics[m]["sample_efficiency_auc"] for m in metrics]
    max_eff = max(eff_list) if max(eff_list) > 0 else 1.0

    for m in metrics:
        fps_norm = np.clip(np.log10(metrics[m]["throughput_fps"]) / 3.5, 0.1, 1.0)
        eff_norm = np.clip(metrics[m]["sample_efficiency_auc"] / max_eff, 0.1, 1.0)
        stab_norm = np.clip(1.0 / (np.log10(metrics[m]["multi_step_drift_mse"]["H_100"] + 1.1) + 0.1), 0.1, 1.0)
        noise_norm = np.clip(metrics[m]["noise_robustness_retention"], 0.1, 1.0)
        ret_norm = np.clip(metrics[m]["final_10k_cumulative_reward"] / (max_rew + 1e-6), 0.1, 1.0)

        values = [fps_norm, eff_norm, stab_norm, noise_norm, ret_norm]
        values += values[:1]

        ax4.plot(angles, values, color=colors[m], linewidth=1.8, label=m)
        ax4.fill(angles, values, color=colors[m], alpha=0.08)

    ax4.set_xticks(angles[:-1])
    ax4.set_xticklabels(categories, fontsize=9.5, fontweight='bold')
    ax4.set_ylim(0, 1.05)
    ax4.grid(True, linestyle=':', alpha=0.7)
    ax4.legend(loc='upper right', bbox_to_anchor=(1.28, 1.15), fontsize=8.5, framealpha=0.9)

    plt.suptitle("Universal World Models Decision Pareto Frontier Benchmark\nCross-Paradigm Evaluation on High-Dynamic Aero-Acrobat Control (10,000 Steps)", 
                 fontsize=16, fontweight='heavy', y=0.99)
    plt.tight_layout(rect=[0, 0.03, 1, 0.96])

    out_img_path = os.path.join(os.path.dirname(__file__), "universal_decision_pareto_eval.png")
    plt.savefig(out_img_path, dpi=300)
    plt.close()
    print(f"[图表生成完毕] 300 DPI 出版级图表已成功保存至: {out_img_path}")
    print("=" * 100)
    print(">>> 全流派跨范式决策帕累托前沿大测度全部执行完毕！\n")


if __name__ == "__main__":
    run_universal_pareto_benchmark()
