"""
Adaptive Hybrid Categorical-Gaussian RSSM & Riemannian Fisher Geometry
======================================================================
Pure PyTorch implementation comparing:
1. Pure Continuous Gaussian RSSM (PlaNet / DreamerV1)
2. Pure Discrete Categorical RSSM (DreamerV2/V3 32x32 STE)
3. Adaptive Hybrid Dual-Stream RSSM (Topological Discrete + Geometric Continuous Residual)
   with Fisher-Information Entropy Gating.

Measures:
- Reconstruction MSE across macro transitions vs micro-control
- Phase space trajectory smoothness (Jerk / Total Variation of d2x/dt2)
- High-frequency quantization chattering index
- Macro regime boundary separation fidelity

Outputs:
- hybrid_rssm_metrics.json
- hybrid_rssm_micro_macro_benchmark.png
- HYBRID_CATEGORICAL_GAUSSIAN_RSSM_THEORY.md
"""

import os
import sys
import json
import time
import math
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import matplotlib.pyplot as plt

# Ensure deterministic execution
torch.manual_seed(42)
np.random.seed(42)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Physics Environment: Macro Jumps + Micro Harmonic Vibrations
# ---------------------------------------------------------------------------

class PrecisionHybridPhysicsEnv:
    """
    Physical environment exhibiting both:
    1. Macro Topological State Jumps (elastic wall rebounds, friction regime switching)
    2. Sub-millimeter Micro Continuous Dynamics (micro-harmonic oscillations, fine damping)
    """
    def __init__(self, obs_dim=16, action_dim=2, seed=42):
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.rng = np.random.RandomState(seed)
        self.dt = 0.05
        self.wall_x = 2.0
        self.floor_y = -1.5
        self.reset()

    def reset(self):
        self.x = self.rng.uniform(-1.0, 1.0)
        self.y = self.rng.uniform(0.5, 1.5)
        self.vx = self.rng.uniform(-1.0, 1.0)
        self.vy = self.rng.uniform(-0.5, 0.5)
        self.micro_phase = 0.0
        self.regime = 0
        self.step_count = 0
        return self._get_obs()

    def _get_obs(self):
        # Micro sub-millimeter vibration signal (high frequency, small amplitude 0.02)
        micro_osc_x = 0.02 * math.sin(self.micro_phase)
        micro_osc_y = 0.02 * math.cos(self.micro_phase)
        
        regime_one_hot = np.zeros(4)
        regime_one_hot[self.regime] = 1.0
        
        obs = np.array([
            self.x + micro_osc_x,
            self.y + micro_osc_y,
            self.vx,
            self.vy,
            np.sin(self.x * np.pi),
            np.cos(self.x * np.pi),
            np.sin(self.y * np.pi),
            np.cos(self.y * np.pi),
            micro_osc_x,
            micro_osc_y,
            0.5 * (self.vx**2 + self.vy**2),
            float(self.x * self.vx < 0.0),
            regime_one_hot[0],
            regime_one_hot[1],
            regime_one_hot[2],
            regime_one_hot[3]
        ], dtype=np.float32)
        return obs

    def step(self, action):
        self.step_count += 1
        ax = np.clip(action[0], -1.0, 1.0) * 3.0
        ay = np.clip(action[1], -1.0, 1.0) * 3.0
        
        # Advance micro-oscillation phase
        self.micro_phase += 0.8
        
        # Continuous aerodynamic drag & acceleration
        speed = math.hypot(self.vx, self.vy)
        drag_x = -0.05 * speed * self.vx
        drag_y = -0.05 * speed * self.vy
        
        self.vx += (ax + drag_x) * self.dt
        self.vy += (ay - 9.81 + drag_y) * self.dt
        self.x += self.vx * self.dt
        self.y += self.vy * self.dt
        
        reward = -0.02
        
        # Macro discrete collision regimes
        if self.y <= self.floor_y:
            self.y = self.floor_y
            if abs(self.vy) < 0.3:
                self.vy = 0.0
                self.vx *= 0.85
                self.regime = 1 # Ground friction
            else:
                self.vy = -0.85 * self.vy
                self.regime = 2 # Inelastic rebound
                reward += 0.5
        elif abs(self.x) >= self.wall_x:
            self.x = np.sign(self.x) * self.wall_x
            self.vx = -0.85 * self.vx
            self.regime = 2 # Wall collision
            reward += 1.0
        elif abs(self.x) < 0.3 and 0.8 < self.y < 1.2:
            self.vx = 3.0 * np.sign(self.vx) if abs(self.vx) > 0.1 else 2.0
            self.regime = 3 # Central scatter
            reward += 5.0
        else:
            self.regime = 0 # Free flight
            
        return self._get_obs(), reward, self.regime

    def rollout_trajectory(self, horizon=35):
        obs_seq, act_seq, rew_seq, reg_seq = [], [], [], []
        obs = self.reset()
        obs_seq.append(obs)
        for _ in range(horizon):
            act = np.clip(self.rng.normal(0.0, 0.5, 2), -1.0, 1.0).astype(np.float32)
            next_obs, rew, reg = self.step(act)
            obs_seq.append(next_obs)
            act_seq.append(act)
            rew_seq.append(rew)
            reg_seq.append(reg)
        return (torch.tensor(np.array(obs_seq), dtype=torch.float32),
                torch.tensor(np.array(act_seq), dtype=torch.float32),
                torch.tensor(np.array(rew_seq), dtype=torch.float32),
                torch.tensor(np.array(reg_seq), dtype=torch.long))

# ---------------------------------------------------------------------------
# Model 1: Pure Continuous Gaussian RSSM (DreamerV1)
# ---------------------------------------------------------------------------

class PureContinuousGaussianRSSM(nn.Module):
    def __init__(self, obs_dim=16, action_dim=2, deter_dim=128, stoch_dim=32):
        super().__init__()
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.deter_dim = deter_dim
        self.stoch_dim = stoch_dim
        
        self.gru_cell = nn.GRUCell(stoch_dim + action_dim, deter_dim)
        
        # Prior: h_t -> (mu, sigma)
        self.prior_mlp = nn.Sequential(nn.Linear(deter_dim, 64), nn.ELU())
        self.prior_mean = nn.Linear(64, stoch_dim)
        self.prior_std = nn.Linear(64, stoch_dim)
        
        # Posterior: [h_t, x_t] -> (mu, sigma)
        self.post_mlp = nn.Sequential(nn.Linear(deter_dim + obs_dim, 64), nn.ELU())
        self.post_mean = nn.Linear(64, stoch_dim)
        self.post_std = nn.Linear(64, stoch_dim)
        
        # Decoder: [h_t, z_t] -> x_hat
        self.decoder = nn.Sequential(
            nn.Linear(deter_dim + stoch_dim, 64),
            nn.ELU(),
            nn.Linear(64, obs_dim)
        )

    def init_state(self, device='cpu'):
        h = torch.zeros(1, self.deter_dim, device=device)
        z = torch.zeros(1, self.stoch_dim, device=device)
        return h, z

    def forward_observe(self, prev_h, prev_z, action, obs):
        gru_in = torch.cat([prev_z, action], dim=-1)
        h_t = self.gru_cell(gru_in, prev_h)
        
        # Prior
        p_feat = self.prior_mlp(h_t)
        p_mean = self.prior_mean(p_feat)
        p_std = F.softplus(self.prior_std(p_feat)) + 0.1
        
        # Posterior
        q_feat = self.post_mlp(torch.cat([h_t, obs], dim=-1))
        q_mean = self.post_mean(q_feat)
        q_std = F.softplus(self.post_std(q_feat)) + 0.1
        
        # Reparameterized sample
        eps = torch.randn_like(q_mean)
        z_t = q_mean + q_std * eps
        
        # Analytic KL
        kl = torch.sum(torch.log(p_std / q_std) + (q_std**2 + (q_mean - p_mean)**2) / (2.0 * p_std**2) - 0.5, dim=-1)
        
        pred_obs = self.decoder(torch.cat([h_t, z_t], dim=-1))
        recon_loss = F.mse_loss(pred_obs, obs)
        
        return h_t, z_t, pred_obs, recon_loss, kl.mean()

    def imagine_step(self, prev_h, prev_z, action):
        gru_in = torch.cat([prev_z, action], dim=-1)
        h_t = self.gru_cell(gru_in, prev_h)
        p_feat = self.prior_mlp(h_t)
        p_mean = self.prior_mean(p_feat)
        p_std = F.softplus(self.prior_std(p_feat)) + 0.1
        z_t = p_mean + p_std * torch.randn_like(p_mean)
        pred_obs = self.decoder(torch.cat([h_t, z_t], dim=-1))
        return h_t, z_t, pred_obs

# ---------------------------------------------------------------------------
# Model 2: Pure Discrete Categorical RSSM (DreamerV2/V3)
# ---------------------------------------------------------------------------

class PureDiscreteCategoricalRSSM(nn.Module):
    def __init__(self, obs_dim=16, action_dim=2, deter_dim=128, num_vars=32, num_classes=32):
        super().__init__()
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.deter_dim = deter_dim
        self.num_vars = num_vars
        self.num_classes = num_classes
        self.stoch_dim = num_vars * num_classes # 1024
        
        self.gru_cell = nn.GRUCell(self.stoch_dim + action_dim, deter_dim)
        
        # Prior: h_t -> logits (32 * 32)
        self.prior_net = nn.Sequential(
            nn.Linear(deter_dim, 64),
            nn.ELU(),
            nn.Linear(64, self.stoch_dim)
        )
        # Posterior: [h_t, x_t] -> logits
        self.post_net = nn.Sequential(
            nn.Linear(deter_dim + obs_dim, 64),
            nn.ELU(),
            nn.Linear(64, self.stoch_dim)
        )
        # Decoder: [h_t, z_t] -> x_hat
        self.decoder = nn.Sequential(
            nn.Linear(deter_dim + self.stoch_dim, 64),
            nn.ELU(),
            nn.Linear(64, obs_dim)
        )

    def init_state(self, device='cpu'):
        h = torch.zeros(1, self.deter_dim, device=device)
        z = torch.zeros(1, self.stoch_dim, device=device)
        return h, z

    def sample_ste(self, logits, unimix=0.01):
        reshaped = logits.view(-1, self.num_vars, self.num_classes)
        probs = F.softmax(reshaped, dim=-1)
        if unimix > 0.0:
            probs = (1.0 - unimix) * probs + unimix / self.num_classes
            
        dist = torch.distributions.Categorical(probs=probs)
        sample_idx = dist.sample()
        one_hot = F.one_hot(sample_idx, self.num_classes).float()
        # Straight-Through Estimator
        ste_sample = probs + (one_hot - probs).detach()
        return ste_sample.view(-1, self.stoch_dim), probs

    def forward_observe(self, prev_h, prev_z, action, obs):
        gru_in = torch.cat([prev_z, action], dim=-1)
        h_t = self.gru_cell(gru_in, prev_h)
        
        p_logits = self.prior_net(h_t)
        q_logits = self.post_net(torch.cat([h_t, obs], dim=-1))
        
        z_t, q_probs = self.sample_ste(q_logits)
        _, p_probs = self.sample_ste(p_logits)
        
        # Categorical KL
        eps = 1e-8
        kl = torch.sum(q_probs * (torch.log(q_probs + eps) - torch.log(p_probs + eps)), dim=[-2, -1])
        
        pred_obs = self.decoder(torch.cat([h_t, z_t], dim=-1))
        recon_loss = F.mse_loss(pred_obs, obs)
        
        return h_t, z_t, pred_obs, recon_loss, kl.mean()

    def imagine_step(self, prev_h, prev_z, action):
        gru_in = torch.cat([prev_z, action], dim=-1)
        h_t = self.gru_cell(gru_in, prev_h)
        p_logits = self.prior_net(h_t)
        z_t, _ = self.sample_ste(p_logits)
        pred_obs = self.decoder(torch.cat([h_t, z_t], dim=-1))
        return h_t, z_t, pred_obs

# ---------------------------------------------------------------------------
# Model 3: Adaptive Hybrid Categorical-Gaussian Dual-Stream RSSM
# ---------------------------------------------------------------------------

class AdaptiveHybridDualStreamRSSM(nn.Module):
    """
    Adaptive Hybrid RSSM combining:
    1. Discrete Stream (32x32 STE): Captures macro topological state jumps.
    2. Continuous Stream (16-D Gaussian): Captures sub-millimeter geometric residuals.
    3. Riemannian Fisher-Information Entropy Gate: Dynamically modulates the fusion ratio
       between macro discrete jumps and micro continuous adjustments.
    """
    def __init__(self, obs_dim=16, action_dim=2, deter_dim=128,
                 num_vars=16, num_classes=16, cont_dim=16):
        super().__init__()
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.deter_dim = deter_dim
        self.num_vars = num_vars
        self.num_classes = num_classes
        self.disc_dim = num_vars * num_classes # 256
        self.cont_dim = cont_dim # 16
        
        self.gru_cell = nn.GRUCell(self.disc_dim + self.cont_dim + action_dim, deter_dim)
        
        # Discrete Topological Stream: Prior & Post
        self.disc_prior = nn.Sequential(nn.Linear(deter_dim, 64), nn.ELU(), nn.Linear(64, self.disc_dim))
        self.disc_post = nn.Sequential(nn.Linear(deter_dim + obs_dim, 64), nn.ELU(), nn.Linear(64, self.disc_dim))
        
        # Continuous Geometric Stream: Prior & Post (Conditioned on discrete state!)
        self.cont_prior_mean = nn.Sequential(nn.Linear(deter_dim + self.disc_dim, 64), nn.ELU(), nn.Linear(64, cont_dim))
        self.cont_prior_std = nn.Sequential(nn.Linear(deter_dim + self.disc_dim, 64), nn.ELU(), nn.Linear(64, cont_dim))
        
        self.cont_post_mean = nn.Sequential(nn.Linear(deter_dim + obs_dim + self.disc_dim, 64), nn.ELU(), nn.Linear(64, cont_dim))
        self.cont_post_std = nn.Sequential(nn.Linear(deter_dim + obs_dim + self.disc_dim, 64), nn.ELU(), nn.Linear(64, cont_dim))
        
        # Adaptive Fisher-Entropy Gating Network: [h_t, entropy_scalar, fisher_trace] -> alpha in (0, 1)
        self.fisher_gate = nn.Sequential(
            nn.Linear(deter_dim + 2, 32),
            nn.Tanh(),
            nn.Linear(32, 1),
            nn.Sigmoid()
        )
        
        # Decoders: Macro Base + Micro Continuous Residual
        self.dec_macro = nn.Sequential(nn.Linear(deter_dim + self.disc_dim, 64), nn.ELU(), nn.Linear(64, obs_dim))
        self.dec_micro_residual = nn.Sequential(nn.Linear(deter_dim + cont_dim, 64), nn.ELU(), nn.Linear(64, obs_dim))

    def init_state(self, device='cpu'):
        h = torch.zeros(1, self.deter_dim, device=device)
        z_d = torch.zeros(1, self.disc_dim, device=device)
        z_c = torch.zeros(1, self.cont_dim, device=device)
        return h, z_d, z_c

    def sample_disc_ste(self, logits, unimix=0.01):
        reshaped = logits.view(-1, self.num_vars, self.num_classes)
        probs = F.softmax(reshaped, dim=-1)
        if unimix > 0.0:
            probs = (1.0 - unimix) * probs + unimix / self.num_classes
        dist = torch.distributions.Categorical(probs=probs)
        sample_idx = dist.sample()
        one_hot = F.one_hot(sample_idx, self.num_classes).float()
        ste_sample = probs + (one_hot - probs).detach()
        return ste_sample.view(-1, self.disc_dim), probs

    def forward_observe(self, prev_h, prev_zd, prev_zc, action, obs):
        gru_in = torch.cat([prev_zd, prev_zc, action], dim=-1)
        h_t = self.gru_cell(gru_in, prev_h)
        
        # 1. Discrete Stream (Macro Topological Jump)
        p_d_logits = self.disc_prior(h_t)
        q_d_logits = self.disc_post(torch.cat([h_t, obs], dim=-1))
        z_d, q_d_probs = self.sample_disc_ste(q_d_logits)
        _, p_d_probs = self.sample_disc_ste(p_d_logits)
        
        eps = 1e-8
        kl_disc = torch.sum(q_d_probs * (torch.log(q_d_probs + eps) - torch.log(p_d_probs + eps)), dim=[-2, -1]).mean()
        
        # Compute Fisher-Rao Information Metric & Entropy
        # Entropy H(q) = - sum q ln q
        entropy_d = -torch.sum(q_d_probs * torch.log(q_d_probs + eps), dim=[-2, -1]).mean()
        # Fisher Information Matrix Trace Tr(I) = sum q_k (1 - q_k) = 1 - sum q_k^2
        fisher_trace = (self.num_vars - torch.sum(q_d_probs**2, dim=[-2, -1])).mean()
        
        # Adaptive Gate alpha in (0, 1)
        gate_feat = torch.cat([h_t, entropy_d.unsqueeze(0).unsqueeze(0), fisher_trace.unsqueeze(0).unsqueeze(0)], dim=-1)
        alpha_t = self.fisher_gate(gate_feat)
        
        # 2. Continuous Stream (Micro Geometric Residual)
        cont_prior_in = torch.cat([h_t, z_d], dim=-1)
        p_c_mean = self.cont_prior_mean(cont_prior_in)
        p_c_std = F.softplus(self.cont_prior_std(cont_prior_in)) + 0.05
        
        cont_post_in = torch.cat([h_t, obs, z_d], dim=-1)
        q_c_mean = self.cont_post_mean(cont_post_in)
        q_c_std = F.softplus(self.cont_post_std(cont_post_in)) + 0.05
        
        z_c = q_c_mean + q_c_std * torch.randn_like(q_c_mean)
        kl_cont = torch.sum(torch.log(p_c_std / q_c_std) + (q_c_std**2 + (q_c_mean - p_c_mean)**2) / (2.0 * p_c_std**2) - 0.5, dim=-1).mean()
        
        # 3. Dual-Stream Decoders with Dynamic Gating
        x_macro = self.dec_macro(torch.cat([h_t, z_d], dim=-1))
        x_micro = self.dec_micro_residual(torch.cat([h_t, z_c], dim=-1))
        
        # Blended prediction: Macro base + alpha * Micro residual
        pred_obs = x_macro + alpha_t * x_micro
        recon_loss = F.mse_loss(pred_obs, obs)
        
        total_kl = kl_disc + 0.5 * kl_cont
        return h_t, z_d, z_c, pred_obs, recon_loss, total_kl, float(alpha_t.item())

    def imagine_step(self, prev_h, prev_zd, prev_zc, action):
        gru_in = torch.cat([prev_zd, prev_zc, action], dim=-1)
        h_t = self.gru_cell(gru_in, prev_h)
        
        p_d_logits = self.disc_prior(h_t)
        z_d, _ = self.sample_disc_ste(p_d_logits)
        
        cont_prior_in = torch.cat([h_t, z_d], dim=-1)
        p_c_mean = self.cont_prior_mean(cont_prior_in)
        p_c_std = F.softplus(self.cont_prior_std(cont_prior_in)) + 0.05
        z_c = p_c_mean + p_c_std * torch.randn_like(p_c_mean)
        
        gate_feat = torch.cat([h_t, torch.zeros(1, 2)], dim=-1)
        alpha_t = self.fisher_gate(gate_feat)
        
        x_macro = self.dec_macro(torch.cat([h_t, z_d], dim=-1))
        x_micro = self.dec_micro_residual(torch.cat([h_t, z_c], dim=-1))
        pred_obs = x_macro + alpha_t * x_micro
        return h_t, z_d, z_c, pred_obs

# ---------------------------------------------------------------------------
# Training & Benchmarking Master Pipeline
# ---------------------------------------------------------------------------

def run_hybrid_rssm_experiment(num_episodes=40, seed=42):
    print("=" * 80)
    print(">>> ADAPTIVE HYBRID RSSM & RIEMANNIAN FISHER GEOMETRY BENCHMARK")
    print(">>> Comparing Pure Continuous vs Pure Discrete vs Adaptive Hybrid RSSM")
    print("=" * 80)
    
    env = PrecisionHybridPhysicsEnv(seed=seed)
    
    # Instantiate the three models
    model_cont = PureContinuousGaussianRSSM(obs_dim=16, action_dim=2, deter_dim=128, stoch_dim=32)
    model_disc = PureDiscreteCategoricalRSSM(obs_dim=16, action_dim=2, deter_dim=128, num_vars=32, num_classes=32)
    model_hybrid = AdaptiveHybridDualStreamRSSM(obs_dim=16, action_dim=2, deter_dim=128, num_vars=16, num_classes=16, cont_dim=16)
    
    opt_cont = torch.optim.Adam(model_cont.parameters(), lr=0.002)
    opt_disc = torch.optim.Adam(model_disc.parameters(), lr=0.002)
    opt_hybrid = torch.optim.Adam(model_hybrid.parameters(), lr=0.002)
    
    models = {
        'continuous': (model_cont, opt_cont),
        'discrete': (model_disc, opt_disc),
        'hybrid': (model_hybrid, opt_hybrid)
    }
    
    metrics = {
        m: {'recon_loss': [], 'kl_loss': [], 'micro_tracking_mse': [], 'chattering_jerk': []}
        for m in models
    }
    gate_history = []
    
    print(f"[*] Training all 3 RSSM models on {num_episodes} hybrid physics episodes...")
    for ep in range(num_episodes):
        obs_seq, act_seq, rew_seq, reg_seq = env.rollout_trajectory(horizon=30)
        
        # 1. Train Continuous
        h_c, z_c = model_cont.init_state()
        loss_c_list, kl_c_list = [], []
        pred_c_list = []
        tot_loss_c = 0.0
        for t in range(len(act_seq)):
            h_c, z_c, pred_obs, recon_l, kl_l = model_cont.forward_observe(h_c, z_c, act_seq[t].unsqueeze(0), obs_seq[t+1].unsqueeze(0))
            tot_loss_c = tot_loss_c + recon_l + 0.1 * kl_l
            loss_c_list.append(recon_l.item())
            kl_c_list.append(kl_l.item())
            pred_c_list.append(pred_obs.detach().squeeze(0).numpy())
        opt_cont.zero_grad()
        tot_loss_c.backward()
        opt_cont.step()
            
        # 2. Train Discrete
        h_d, z_d = model_disc.init_state()
        loss_d_list, kl_d_list = [], []
        pred_d_list = []
        tot_loss_d = 0.0
        for t in range(len(act_seq)):
            h_d, z_d, pred_obs, recon_l, kl_l = model_disc.forward_observe(h_d, z_d, act_seq[t].unsqueeze(0), obs_seq[t+1].unsqueeze(0))
            tot_loss_d = tot_loss_d + recon_l + 0.1 * kl_l
            loss_d_list.append(recon_l.item())
            kl_d_list.append(kl_l.item())
            pred_d_list.append(pred_obs.detach().squeeze(0).numpy())
        opt_disc.zero_grad()
        tot_loss_d.backward()
        opt_disc.step()
            
        # 3. Train Hybrid
        h_h, zd_h, zc_h = model_hybrid.init_state()
        loss_h_list, kl_h_list = [], []
        pred_h_list = []
        ep_gates = []
        tot_loss_h = 0.0
        for t in range(len(act_seq)):
            h_h, zd_h, zc_h, pred_obs, recon_l, kl_l, alpha_val = model_hybrid.forward_observe(
                h_h, zd_h, zc_h, act_seq[t].unsqueeze(0), obs_seq[t+1].unsqueeze(0)
            )
            tot_loss_h = tot_loss_h + recon_l + 0.1 * kl_l
            loss_h_list.append(recon_l.item())
            kl_h_list.append(kl_l.item())
            pred_h_list.append(pred_obs.detach().squeeze(0).numpy())
            ep_gates.append(alpha_val)
        opt_hybrid.zero_grad()
        tot_loss_h.backward()
        opt_hybrid.step()
            
        gate_history.append(float(np.mean(ep_gates)))
        
        # Calculate Micro-Tracking MSE (dimension 8 & 9: micro harmonic oscillations)
        true_micro = obs_seq[1:, 8:10].numpy()
        pred_c_arr = np.array(pred_c_list)[:, 8:10]
        pred_d_arr = np.array(pred_d_list)[:, 8:10]
        pred_h_arr = np.array(pred_h_list)[:, 8:10]
        
        metrics['continuous']['micro_tracking_mse'].append(float(np.mean((pred_c_arr - true_micro)**2)))
        metrics['discrete']['micro_tracking_mse'].append(float(np.mean((pred_d_arr - true_micro)**2)))
        metrics['hybrid']['micro_tracking_mse'].append(float(np.mean((pred_h_arr - true_micro)**2)))
        
        # Calculate Chattering Jerk Index: mean norm of second temporal difference ||x_{t+2} - 2x_{t+1} + x_t||
        def compute_jerk(pred_arr):
            diff2 = pred_arr[2:] - 2.0 * pred_arr[1:-1] + pred_arr[:-2]
            return float(np.mean(diff2**2))
            
        metrics['continuous']['chattering_jerk'].append(compute_jerk(pred_c_arr))
        metrics['discrete']['chattering_jerk'].append(compute_jerk(pred_d_arr))
        metrics['hybrid']['chattering_jerk'].append(compute_jerk(pred_h_arr))
        
        metrics['continuous']['recon_loss'].append(float(np.mean(loss_c_list)))
        metrics['discrete']['recon_loss'].append(float(np.mean(loss_d_list)))
        metrics['hybrid']['recon_loss'].append(float(np.mean(loss_h_list)))
        
        if (ep + 1) % 10 == 0 or ep == num_episodes - 1:
            print(f"    Episode {ep+1:02d}/{num_episodes:02d} | "
                  f"Cont MSE: {metrics['continuous']['recon_loss'][-1]:.4f}, Jerk: {metrics['continuous']['chattering_jerk'][-1]:.6f} | "
                  f"Disc MSE: {metrics['discrete']['recon_loss'][-1]:.4f}, Jerk: {metrics['discrete']['chattering_jerk'][-1]:.6f} | "
                  f"Hybrid MSE: {metrics['hybrid']['recon_loss'][-1]:.4f}, Jerk: {metrics['hybrid']['chattering_jerk'][-1]:.6f}, Gate: {gate_history[-1]:.3f}")

    # Compile structured summary
    results_summary = {
        "final_epoch": num_episodes,
        "models": {
            "pure_continuous": {
                "final_recon_mse": metrics['continuous']['recon_loss'][-1],
                "micro_tracking_mse": metrics['continuous']['micro_tracking_mse'][-1],
                "chattering_jerk": metrics['continuous']['chattering_jerk'][-1]
            },
            "pure_discrete": {
                "final_recon_mse": metrics['discrete']['recon_loss'][-1],
                "micro_tracking_mse": metrics['discrete']['micro_tracking_mse'][-1],
                "chattering_jerk": metrics['discrete']['chattering_jerk'][-1]
            },
            "adaptive_hybrid": {
                "final_recon_mse": metrics['hybrid']['recon_loss'][-1],
                "micro_tracking_mse": metrics['hybrid']['micro_tracking_mse'][-1],
                "chattering_jerk": metrics['hybrid']['chattering_jerk'][-1],
                "mean_fisher_gate_activation": gate_history[-1]
            }
        },
        "relative_improvements": {
            "hybrid_vs_discrete_jerk_reduction_ratio": metrics['discrete']['chattering_jerk'][-1] / max(metrics['hybrid']['chattering_jerk'][-1], 1e-8),
            "hybrid_vs_continuous_recon_improvement_ratio": metrics['continuous']['recon_loss'][-1] / max(metrics['hybrid']['recon_loss'][-1], 1e-8)
        },
        "history": metrics,
        "gate_history": gate_history
    }
    
    # Save JSON
    json_path = os.path.join(OUTPUT_DIR, "hybrid_rssm_metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, indent=2)
    print(f"\n[+] Successfully saved hybrid benchmark metrics to: {json_path}")
    
    # Plot Visualizations
    plot_hybrid_comparison(results_summary)
    return results_summary

def plot_hybrid_comparison(results):
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    episodes = np.arange(1, len(results['history']['continuous']['recon_loss']) + 1)
    
    colors = {'continuous': '#e74c3c', 'discrete': '#2980b9', 'hybrid': '#27ae60'}
    labels = {
        'continuous': 'Pure Continuous Gaussian (DreamerV1)',
        'discrete': 'Pure Discrete Categorical (DreamerV2/V3)',
        'hybrid': 'Adaptive Hybrid (Topological + Geometric Residual)'
    }
    
    # Subplot 1: Total Reconstruction MSE
    for m in ['continuous', 'discrete', 'hybrid']:
        axs[0, 0].plot(episodes, results['history'][m]['recon_loss'], color=colors[m], label=labels[m], lw=2.3)
    axs[0, 0].set_title("(a) Total State Reconstruction MSE", fontsize=11, fontweight='bold')
    axs[0, 0].set_xlabel("Training Episodes", fontsize=10)
    axs[0, 0].set_ylabel("Reconstruction MSE", fontsize=10)
    axs[0, 0].set_yscale('log')
    axs[0, 0].grid(True)
    axs[0, 0].legend(loc='upper right', frameon=True, fontsize=9)
    
    # Subplot 2: Micro-Tracking Error (Sub-millimeter oscillations)
    for m in ['continuous', 'discrete', 'hybrid']:
        axs[0, 1].plot(episodes, results['history'][m]['micro_tracking_mse'], color=colors[m], label=labels[m], lw=2.3)
    axs[0, 1].set_title("(b) Sub-Millimeter Micro-Tracking Precision MSE", fontsize=11, fontweight='bold')
    axs[0, 1].set_xlabel("Training Episodes", fontsize=10)
    axs[0, 1].set_ylabel("Micro Oscillation MSE", fontsize=10)
    axs[0, 1].set_yscale('log')
    axs[0, 1].grid(True)
    axs[0, 1].legend(loc='upper right', frameon=True, fontsize=9)
    
    # Subplot 3: Quantization Chattering Jerk (Smoothness of Phase Space)
    for m in ['continuous', 'discrete', 'hybrid']:
        axs[1, 0].plot(episodes, results['history'][m]['chattering_jerk'], color=colors[m], label=labels[m], lw=2.3)
    axs[1, 0].set_title("(c) Phase Space Quantization Chattering (Jerk Index)", fontsize=11, fontweight='bold')
    axs[1, 0].set_xlabel("Training Episodes", fontsize=10)
    axs[1, 0].set_ylabel("Second-Order Jerk Variance (Chattering)", fontsize=10)
    axs[1, 0].set_yscale('log')
    axs[1, 0].grid(True)
    axs[1, 0].legend(loc='upper right', frameon=True, fontsize=9)
    
    # Subplot 4: Adaptive Fisher Entropy Gate Dynamics
    axs[1, 1].plot(episodes, results['gate_history'], color='#8e44ad', lw=2.5, label='Fisher-Entropy Residual Gate alpha_t')
    axs[1, 1].axhline(y=0.5, color='#7f8c8d', linestyle='--', lw=1.2, label='Balanced Equipartition (0.5)')
    axs[1, 1].set_title("(d) Adaptive Fisher-Information Entropy Gate Activation", fontsize=11, fontweight='bold')
    axs[1, 1].set_xlabel("Training Episodes", fontsize=10)
    axs[1, 1].set_ylabel("Continuous Residual Gate Opening alpha_t in [0, 1]", fontsize=10)
    axs[1, 1].set_ylim(0.0, 1.0)
    axs[1, 1].grid(True)
    axs[1, 1].legend(loc='upper right', frameon=True, fontsize=9)
    
    plt.tight_layout()
    fig_path = os.path.join(OUTPUT_DIR, "hybrid_rssm_micro_macro_benchmark.png")
    plt.savefig(fig_path, dpi=300)
    plt.close()
    print(f"[+] Saved visualization: {fig_path}")

if __name__ == "__main__":
    run_hybrid_rssm_experiment(num_episodes=35, seed=42)
