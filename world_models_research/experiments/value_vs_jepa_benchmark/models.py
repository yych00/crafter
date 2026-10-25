"""
Three World Model Architectures for Visual Distraction Benchmark
==============================================================
1. Reconstruction World Model (VAE-RSSM Paradigm)
2. Value-Equivalent World Model (MuZero Paradigm)
3. Joint-Embedding Predictive Architecture (JEPA / V-JEPA Paradigm)
"""

import numpy as np
from nn_core import (
    Linear, LayerNorm, ReLU, Tanh, Sequential, Adam,
    copy_parameters, ema_update, one_hot, mse_loss,
    softmax_cross_entropy, vicreg_loss
)


class ReconstructionWM:
    """
    Paradigm 1: Reconstruction World Model (VAE-RSSM)
    Forces fitting full pixel reconstruction L_recon + L_dyn + L_reward.
    """
    def __init__(self, obs_dim=256, latent_dim=32, action_dim=5, lr=1e-3):
        self.obs_dim = obs_dim
        self.latent_dim = latent_dim
        self.action_dim = action_dim
        
        # 1. Pixel Encoder: obs -> latent
        self.encoder = Sequential(
            Linear(obs_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, latent_dim),
            Tanh()
        )
        
        # 2. Pixel Decoder: latent -> obs
        self.decoder = Sequential(
            Linear(latent_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, obs_dim)
        )
        
        # 3. Latent Dynamics: (z_t, a_t) -> z_{t+1}
        self.dynamics = Sequential(
            Linear(latent_dim + action_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, latent_dim),
            Tanh()
        )
        
        # 4. Reward Head: z_{t+1} -> reward
        self.reward_head = Sequential(
            Linear(latent_dim, 32),
            ReLU(),
            Linear(32, 1)
        )
        
        all_params = (
            self.encoder.parameters() +
            self.decoder.parameters() +
            self.dynamics.parameters() +
            self.reward_head.parameters()
        )
        self.optimizer = Adam(all_params, lr=lr)
        
    def encode(self, obs):
        return self.encoder.forward(obs)
        
    def decode(self, z):
        return self.decoder.forward(z)
        
    def predict_next(self, z, action):
        if action.ndim == 1:
            a_vec = one_hot(action, self.action_dim)
        else:
            a_vec = action
        inp = np.concatenate([z, a_vec], axis=-1)
        z_next = self.dynamics.forward(inp)
        r_pred = self.reward_head.forward(z_next)
        return z_next, r_pred.squeeze(-1)
        
    def train_step(self, obs_t, actions, rewards, obs_next, lambda_recon=1.0, lambda_dyn=1.0, lambda_rew=1.0):
        self.optimizer.zero_grad()
        B = obs_t.shape[0]
        a_vec = one_hot(actions, self.action_dim)
        
        # 1. Encode
        z_t = self.encoder.forward(obs_t)
        z_tp1_target = self.encoder.forward(obs_next)
        
        # 2. Decode obs_t
        obs_recon = self.decoder.forward(z_t)
        loss_recon, grad_recon = mse_loss(obs_recon, obs_t)
        
        # 3. Dynamics
        inp_dyn = np.concatenate([z_t, a_vec], axis=-1)
        z_pred_tp1 = self.dynamics.forward(inp_dyn)
        loss_dyn, grad_dyn = mse_loss(z_pred_tp1, z_tp1_target)
        
        # 4. Reward
        r_pred = self.reward_head.forward(z_pred_tp1)
        loss_rew, grad_rew = mse_loss(r_pred, rewards[:, None])
        
        total_loss = (
            lambda_recon * loss_recon +
            lambda_dyn * loss_dyn +
            lambda_rew * loss_rew
        )
        
        # Backward pass
        # Reward head
        grad_z_from_rew = self.reward_head.backward(lambda_rew * grad_rew)
        
        # Dynamics backward: combines dyn loss and reward loss
        grad_z_dyn_out = lambda_dyn * grad_dyn + grad_z_from_rew
        grad_inp_dyn = self.dynamics.backward(grad_z_dyn_out)
        grad_zt_from_dyn = grad_inp_dyn[:, :self.latent_dim]
        
        # Decoder backward
        grad_zt_from_recon = self.decoder.backward(lambda_recon * grad_recon)
        
        # Encoder backward for z_t: combines recon and dyn
        grad_zt_total = grad_zt_from_recon + grad_zt_from_dyn
        self.encoder.backward(grad_zt_total)
        
        # Encoder backward for z_tp1_target
        # In RSSM, target z_tp1 provides gradient to encoder
        grad_target = -lambda_dyn * grad_dyn
        self.encoder.backward(grad_target)
        
        self.optimizer.step()
        
        return {
            "loss_total": total_loss,
            "loss_recon": loss_recon,
            "loss_dyn": loss_dyn,
            "loss_rew": loss_rew
        }


class ValueEquivalentWM:
    """
    Paradigm 2: Value-Equivalent World Model (MuZero)
    Completely decoupled from pixels. Learns g(s, a) -> (r, s') and f(s) -> (p, v).
    """
    def __init__(self, obs_dim=256, latent_dim=32, action_dim=5, lr=1e-3):
        self.obs_dim = obs_dim
        self.latent_dim = latent_dim
        self.action_dim = action_dim
        
        # 1. Representation Network: obs -> s
        self.representation = Sequential(
            Linear(obs_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, latent_dim),
            Tanh()
        )
        
        # 2. Dynamics Network: (s_t, a_t) -> s_{t+1}
        self.dynamics = Sequential(
            Linear(latent_dim + action_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, latent_dim),
            Tanh()
        )
        
        # 3. Reward Head: s_{t+1} -> reward
        self.reward_head = Sequential(
            Linear(latent_dim, 32),
            ReLU(),
            Linear(32, 1)
        )
        
        # 4. Value Head: s -> value
        self.value_head = Sequential(
            Linear(latent_dim, 32),
            ReLU(),
            Linear(32, 1)
        )
        
        # 5. Policy Head: s -> policy logits
        self.policy_head = Sequential(
            Linear(latent_dim, 32),
            ReLU(),
            Linear(32, action_dim)
        )
        
        all_params = (
            self.representation.parameters() +
            self.dynamics.parameters() +
            self.reward_head.parameters() +
            self.value_head.parameters() +
            self.policy_head.parameters()
        )
        self.optimizer = Adam(all_params, lr=lr)
        
    def encode(self, obs):
        return self.representation.forward(obs)
        
    def predict_next(self, s, action):
        if action.ndim == 1:
            a_vec = one_hot(action, self.action_dim)
        else:
            a_vec = action
        inp = np.concatenate([s, a_vec], axis=-1)
        s_next = self.dynamics.forward(inp)
        r_pred = self.reward_head.forward(s_next)
        return s_next, r_pred.squeeze(-1)
        
    def predict_value_policy(self, s):
        v = self.value_head.forward(s).squeeze(-1)
        logits = self.policy_head.forward(s)
        return v, logits
        
    def train_step(self, obs_t, actions, rewards, obs_next, values_t, values_tp1, target_actions,
                   lambda_rew=1.0, lambda_val=0.5, lambda_pol=0.5):
        self.optimizer.zero_grad()
        B = obs_t.shape[0]
        a_vec = one_hot(actions, self.action_dim)
        
        # 1. Initial state representation
        s_t = self.representation.forward(obs_t)
        
        # 2. Prediction at root (s_t)
        v_t = self.value_head.forward(s_t)
        pi_logits = self.policy_head.forward(s_t)
        
        loss_val_t, grad_vt = mse_loss(v_t, values_t[:, None])
        loss_pol, grad_pol, _ = softmax_cross_entropy(pi_logits, target_actions)
        
        # 3. Transition to s_{t+1}
        inp_dyn = np.concatenate([s_t, a_vec], axis=-1)
        s_pred_tp1 = self.dynamics.forward(inp_dyn)
        
        # 4. Predictions at s_{t+1}
        r_pred = self.reward_head.forward(s_pred_tp1)
        v_tp1 = self.value_head.forward(s_pred_tp1)
        
        loss_rew, grad_rew = mse_loss(r_pred, rewards[:, None])
        loss_val_tp1, grad_vtp1 = mse_loss(v_tp1, values_tp1[:, None])
        
        total_loss = (
            lambda_rew * loss_rew +
            lambda_val * (loss_val_t + loss_val_tp1) +
            lambda_pol * loss_pol
        )
        
        # Backward pass from s_{t+1}
        grad_s_rew = self.reward_head.backward(lambda_rew * grad_rew)
        grad_s_vtp1 = self.value_head.backward(lambda_val * grad_vtp1)
        grad_stp1_total = grad_s_rew + grad_s_vtp1
        
        # Dynamics backward
        grad_inp_dyn = self.dynamics.backward(grad_stp1_total)
        grad_st_from_dyn = grad_inp_dyn[:, :self.latent_dim]
        
        # Predictions at s_t backward
        grad_st_from_vt = self.value_head.backward(lambda_val * grad_vt)
        grad_st_from_pol = self.policy_head.backward(lambda_pol * grad_pol)
        
        # Total gradient into representation
        grad_st_total = grad_st_from_dyn + grad_st_from_vt + grad_st_from_pol
        self.representation.backward(grad_st_total)
        
        self.optimizer.step()
        
        return {
            "loss_total": total_loss,
            "loss_rew": loss_rew,
            "loss_val": loss_val_t + loss_val_tp1,
            "loss_pol": loss_pol
        }


class JepaWM:
    """
    Paradigm 3: Joint-Embedding Predictive Architecture (JEPA / V-JEPA)
    No generative decoder. Abstract feature space prediction with EMA target
    and VICReg non-contrastive anti-collapse regularization.
    """
    def __init__(self, obs_dim=256, latent_dim=32, action_dim=5, lr=1e-3, ema_tau=0.99):
        self.obs_dim = obs_dim
        self.latent_dim = latent_dim
        self.action_dim = action_dim
        self.ema_tau = ema_tau
        
        # 1. Online Context Encoder
        self.context_encoder = Sequential(
            Linear(obs_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, latent_dim),
            Tanh()
        )
        
        # 2. Target Encoder (EMA updated, no direct gradient)
        self.target_encoder = Sequential(
            Linear(obs_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, latent_dim),
            Tanh()
        )
        # Initialize target encoder with identical weights
        copy_parameters(self.context_encoder.parameters(), self.target_encoder.parameters())
        
        # 3. Predictor in Latent Space: (z_t, a_t) -> hat{z}_{t+1}
        self.predictor = Sequential(
            Linear(latent_dim + action_dim, 64),
            LayerNorm(64),
            ReLU(),
            Linear(64, latent_dim),
            Tanh()
        )
        
        # 4. Downstream / Auxiliary Reward Head: z_{t+1} -> reward
        self.reward_head = Sequential(
            Linear(latent_dim, 32),
            ReLU(),
            Linear(32, 1)
        )
        
        all_params = (
            self.context_encoder.parameters() +
            self.predictor.parameters() +
            self.reward_head.parameters()
        )
        self.optimizer = Adam(all_params, lr=lr)
        
    def encode(self, obs):
        return self.context_encoder.forward(obs)
        
    def predict_next(self, z, action):
        if action.ndim == 1:
            a_vec = one_hot(action, self.action_dim)
        else:
            a_vec = action
        inp = np.concatenate([z, a_vec], axis=-1)
        z_next = self.predictor.forward(inp)
        r_pred = self.reward_head.forward(z_next)
        return z_next, r_pred.squeeze(-1)
        
    def train_step(self, obs_t, actions, rewards, obs_next,
                   lambda_pred=1.0, lambda_vicreg=0.2, lambda_rew=1.0):
        self.optimizer.zero_grad()
        B = obs_t.shape[0]
        a_vec = one_hot(actions, self.action_dim)
        
        # 1. Context encoding & Target encoding
        z_t = self.context_encoder.forward(obs_t)
        # Target encoder forward (stop gradient)
        z_tp1_target = self.target_encoder.forward(obs_next)
        
        # 2. Latent prediction
        inp_pred = np.concatenate([z_t, a_vec], axis=-1)
        z_pred_tp1 = self.predictor.forward(inp_pred)
        
        # Prediction L2 / Cosine loss
        loss_pred, grad_pred = mse_loss(z_pred_tp1, z_tp1_target)
        
        # 3. VICReg anti-collapse regularizer on z_t
        var_loss, cov_loss, grad_vicreg = vicreg_loss(z_t, gamma=1.0)
        vicreg_total_loss = var_loss + cov_loss
        
        # 4. Reward head prediction
        r_pred = self.reward_head.forward(z_pred_tp1)
        loss_rew, grad_rew = mse_loss(r_pred, rewards[:, None])
        
        total_loss = (
            lambda_pred * loss_pred +
            lambda_vicreg * vicreg_total_loss +
            lambda_rew * loss_rew
        )
        
        # Backward pass
        # Reward head
        grad_z_from_rew = self.reward_head.backward(lambda_rew * grad_rew)
        
        # Predictor backward: combines pred loss and reward loss
        grad_z_pred_out = lambda_pred * grad_pred + grad_z_from_rew
        grad_inp_pred = self.predictor.backward(grad_z_pred_out)
        grad_zt_from_pred = grad_inp_pred[:, :self.latent_dim]
        
        # Context encoder backward: combines predictor gradient and VICReg anti-collapse gradient
        grad_zt_total = grad_zt_from_pred + lambda_vicreg * grad_vicreg
        self.context_encoder.backward(grad_zt_total)
        
        self.optimizer.step()
        
        # EMA update for target encoder
        ema_update(self.context_encoder.parameters(), self.target_encoder.parameters(), tau=self.ema_tau)
        
        return {
            "loss_total": total_loss,
            "loss_pred": loss_pred,
            "loss_vicreg": vicreg_total_loss,
            "loss_rew": loss_rew
        }
