"""
RSSM Discrete Dynamics & Ablation Engine
========================================
Pure NumPy implementation of Recurrent State-Space Models (RSSM)
comparing Continuous Gaussian (DreamerV1) and Discrete Categorical (DreamerV2/V3)
stochastic dynamics, KL Balancing mechanisms, and Symlog transformation.

Components:
1. HybridNonlinearPhysicsEnv: Environment with continuous state dynamics,
   discrete regime/collision switches, and multi-scale rewards.
2. ContinuousGaussianRSSM: PlaNet/DreamerV1 style Gaussian latent with reparameterization.
3. DiscreteCategoricalRSSM: DreamerV2/V3 style 32x32 categorical latent with Straight-Through Estimator (STE).
4. KL Balancing: Loss computation with alpha balancing parameter.
5. Symlog / Symexp transformations: Numerical stabilization and gradient scaling.
"""

import math
import numpy as np

# ---------------------------------------------------------------------------
# Utility Math Functions & Activations
# ---------------------------------------------------------------------------

def sigmoid(x):
    """Numerically stable sigmoid."""
    x_clamped = np.clip(x, -20.0, 20.0)
    return 1.0 / (1.0 + np.exp(-x_clamped))

def d_sigmoid(s):
    """Derivative of sigmoid given output s = sigmoid(x)."""
    return s * (1.0 - s)

def tanh(x):
    return np.tanh(np.clip(x, -15.0, 15.0))

def d_tanh(t):
    """Derivative of tanh given output t = tanh(x)."""
    return 1.0 - t ** 2

def relu(x):
    return np.maximum(0.0, x)

def d_relu(x):
    return (x > 0.0).astype(np.float64)

def softplus(x):
    """Numerically stable softplus."""
    return np.log1p(np.exp(-np.abs(x))) + np.maximum(x, 0.0)

def softmax(x, axis=-1):
    """Numerically stable softmax along specified axis."""
    x_max = np.max(x, axis=axis, keepdims=True)
    exp_x = np.exp(x - x_max)
    return exp_x / np.sum(exp_x, axis=axis, keepdims=True)

# ---------------------------------------------------------------------------
# Symlog & Symexp Transformations
# ---------------------------------------------------------------------------

def symlog(x):
    """
    symlog(x) = sign(x) * ln(|x| + 1)
    Compresses large values logarithmically while remaining smooth and linear near zero.
    """
    return np.sign(x) * np.log1p(np.abs(x))

def symexp(y):
    """
    symexp(y) = sign(y) * (exp(|y|) - 1)
    Exact inverse of symlog.
    """
    return np.sign(y) * np.expm1(np.abs(y))

def d_symlog(x):
    """Derivative of symlog with respect to x: 1 / (|x| + 1)."""
    return 1.0 / (np.abs(x) + 1.0)

# ---------------------------------------------------------------------------
# Straight-Through Categorical Distribution
# ---------------------------------------------------------------------------

class CategoricalLatent:
    """
    Categorical latent distribution over N independent groups of K classes.
    For DreamerV2/V3: N=32, K=32. Total stochastic vector size = 32 * 32 = 1024.
    Supports Straight-Through Estimator (STE) and DreamerV3 Unimix.
    """
    def __init__(self, num_vars=32, num_classes=32, unimix_ratio=0.01):
        self.num_vars = num_vars
        self.num_classes = num_classes
        self.unimix_ratio = unimix_ratio

    def logits_to_probs(self, logits):
        """
        logits: shape (..., num_vars, num_classes) or (..., num_vars * num_classes)
        Returns unimixed probabilities.
        """
        orig_shape = logits.shape
        reshaped = logits.reshape(-1, self.num_vars, self.num_classes)
        probs = softmax(reshaped, axis=-1)
        # DreamerV3 unimix to avoid extreme probabilities and log(0)
        if self.unimix_ratio > 0.0:
            probs = (1.0 - self.unimix_ratio) * probs + self.unimix_ratio / self.num_classes
        return probs.reshape(orig_shape)

    def sample_ste(self, probs):
        """
        Sample discrete one-hot vectors using Straight-Through Estimator.
        Forward pass: discrete one-hot sample.
        Backward pass: identity gradient with respect to probs.
        """
        orig_shape = probs.shape
        p = probs.reshape(-1, self.num_vars, self.num_classes)
        batch_size = p.shape[0]
        one_hot = np.zeros_like(p)

        for b in range(batch_size):
            for v in range(self.num_vars):
                k = np.random.choice(self.num_classes, p=p[b, v])
                one_hot[b, v, k] = 1.0

        # Straight-Through: output = one_hot in forward, gradient flows to p in backward
        # In NumPy, we return both the one_hot sample and probs for forward/backward tracking
        sample_flat = one_hot.reshape(orig_shape)
        return sample_flat

    def kl_divergence(self, post_probs, prior_probs):
        """
        KL(q || p) = sum_{v=1}^N sum_{k=1}^K q_{v,k} * (ln(q_{v,k}) - ln(p_{v,k}))
        Returns scalar or per-sample KL divergence.
        """
        q = post_probs.reshape(-1, self.num_vars, self.num_classes)
        p = prior_probs.reshape(-1, self.num_vars, self.num_classes)
        eps = 1e-12
        q = np.clip(q, eps, 1.0)
        p = np.clip(p, eps, 1.0)
        kl_per_var = np.sum(q * (np.log(q) - np.log(p)), axis=-1) # shape: (batch, num_vars)
        total_kl = np.sum(kl_per_var, axis=-1) # shape: (batch,)
        return total_kl

    def entropy(self, probs):
        """Compute Shannon entropy: H(q) = - sum q ln(q)."""
        p = probs.reshape(-1, self.num_vars, self.num_classes)
        eps = 1e-12
        p_safe = np.clip(p, eps, 1.0)
        h_per_var = -np.sum(p_safe * np.log(p_safe), axis=-1)
        return np.sum(h_per_var, axis=-1)

# ---------------------------------------------------------------------------
# Continuous Gaussian Latent Distribution
# ---------------------------------------------------------------------------

class GaussianLatent:
    """
    Continuous Gaussian latent distribution.
    For PlaNet/DreamerV1: dimension D=32.
    Parameterizes mean mu and std sigma (via softplus).
    """
    def __init__(self, dim=32, min_std=0.1):
        self.dim = dim
        self.min_std = min_std

    def transform_std(self, raw_std):
        """Standard deviation parameterization with softplus and minimum bound."""
        return softplus(raw_std) + self.min_std

    def sample_reparameterized(self, mean, std):
        """z = mu + sigma * eps, eps ~ N(0, I)."""
        eps = np.random.randn(*mean.shape)
        return mean + std * eps, eps

    def kl_divergence(self, post_mean, post_std, prior_mean, prior_std):
        """
        KL(q || p) = sum [ ln(std_p / std_q) + (std_q^2 + (mu_q - mu_p)^2) / (2 * std_p^2) - 0.5 ]
        """
        eps = 1e-10
        p_std_safe = np.maximum(prior_std, eps)
        q_std_safe = np.maximum(post_std, eps)
        var_p = p_std_safe ** 2
        var_q = q_std_safe ** 2
        kl = np.log(p_std_safe / q_std_safe) + (var_q + (post_mean - prior_mean)**2) / (2.0 * var_p) - 0.5
        return np.sum(kl, axis=-1)

    def entropy(self, std):
        """Differential entropy of Gaussian: 0.5 * ln(2 * pi * e * sigma^2)."""
        eps = 1e-10
        std_safe = np.maximum(std, eps)
        h = 0.5 * np.log(2.0 * np.pi * np.e * (std_safe ** 2))
        return np.sum(h, axis=-1)

# ---------------------------------------------------------------------------
# Physical Environment: Hybrid Dynamics with Discrete Regimes
# ---------------------------------------------------------------------------

class HybridNonlinearPhysicsEnv:
    """
    Synthetic physical environment simulating non-linear jumpy / hybrid dynamics:
    - 2D bouncing ball under gravity, aerodynamic drag, and obstacle collisions
    - 4 discrete contact / friction regimes:
        0: Free Flight (ballistic motion)
        1: Ground Contact (Coulomb friction, inelastic damping)
        2: Elastic Wall Rebound (sudden velocity sign flip + restitution coefficient)
        3: Trapped / Obstacle Collision (high impulse shockwave, non-linear scattering)
    - Multi-scale observation: coordinates, velocities, kinetic/potential energy,
      discrete regime one-hot, contact impulses.
    - Multi-magnitude reward signals: small step penalty (-0.01), regular tracking reward (+1.0),
      rare high-magnitude target event (+100.0 to +10,000.0).
    """
    def __init__(self, obs_dim=16, action_dim=2, seed=42):
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.rng = np.random.RandomState(seed)
        
        # Physical parameters
        self.dt = 0.05
        self.gravity = 9.81
        self.drag_coeff = 0.05
        self.wall_x = 2.0
        self.floor_y = -1.5
        self.restitution = 0.85
        
        # State vector: [x, y, vx, vy, regime]
        self.reset()

    def reset(self):
        self.x = self.rng.uniform(-1.0, 1.0)
        self.y = self.rng.uniform(0.0, 2.0)
        self.vx = self.rng.uniform(-1.5, 1.5)
        self.vy = self.rng.uniform(-0.5, 1.0)
        self.regime = 0 # 0: Free flight
        self.step_count = 0
        return self._get_obs(), 0.0

    def _get_obs(self):
        """Construct multi-feature observation vector (16-D)."""
        kinetic_energy = 0.5 * (self.vx**2 + self.vy**2)
        potential_energy = self.gravity * max(0.0, self.y - self.floor_y)
        total_energy = kinetic_energy + potential_energy
        
        # One-hot regime encoding (4-D)
        regime_one_hot = np.zeros(4)
        regime_one_hot[self.regime] = 1.0
        
        # Non-linear sensory features
        obs = np.array([
            self.x,
            self.y,
            self.vx,
            self.vy,
            np.sin(self.x * np.pi),
            np.cos(self.x * np.pi),
            np.sin(self.y * np.pi),
            np.cos(self.y * np.pi),
            kinetic_energy,
            potential_energy,
            total_energy,
            float(self.x * self.vx < 0.0), # heading towards center
            regime_one_hot[0],
            regime_one_hot[1],
            regime_one_hot[2],
            regime_one_hot[3]
        ], dtype=np.float64)
        
        return obs

    def step(self, action):
        """
        Execute physics step with discrete regime transitions.
        action: [ax, ay] bounded in [-1, 1]
        """
        self.step_count += 1
        ax = np.clip(action[0], -1.0, 1.0) * 4.0
        ay = np.clip(action[1], -1.0, 1.0) * 4.0
        
        # Base aerodynamic drag
        speed = math.hypot(self.vx, self.vy)
        drag_x = -self.drag_coeff * speed * self.vx
        drag_y = -self.drag_coeff * speed * self.vy
        
        # Advance state under continuous physics
        self.vx += (ax + drag_x) * self.dt
        self.vy += (ay - self.gravity + drag_y) * self.dt
        self.x += self.vx * self.dt
        self.y += self.vy * self.dt
        
        prev_regime = self.regime
        reward = -0.01 # Dense time step penalty
        
        # Discrete collision & boundary handling (Hybrid dynamics)
        # 1. Floor collision
        if self.y <= self.floor_y:
            self.y = self.floor_y
            if abs(self.vy) < 0.3:
                # Sticking / Ground friction regime
                self.vy = 0.0
                self.vx *= 0.85
                self.regime = 1 # Ground friction
            else:
                # Floor rebound
                self.vy = -self.restitution * self.vy
                self.regime = 2 # Boundary rebound
                reward += 0.5
        # 2. Left / Right Wall collision (Sudden discrete velocity flip)
        elif abs(self.x) >= self.wall_x:
            self.x = np.sign(self.x) * self.wall_x
            self.vx = -self.restitution * self.vx + self.rng.uniform(-0.2, 0.2)
            self.regime = 2 # Wall collision
            reward += 1.0
        # 3. Obstacle collision (rare high-magnitude event in central zone)
        elif abs(self.x) < 0.3 and 0.8 < self.y < 1.2:
            # High-velocity shockwave scattering
            angle = self.rng.uniform(0, 2 * np.pi)
            scatter_speed = 3.5
            self.vx = scatter_speed * np.cos(angle)
            self.vy = scatter_speed * np.sin(angle)
            self.regime = 3 # Central obstacle scatter
            # Rare multi-scale high reward event! (Spanning 10^2 ~ 10^4)
            jackpot_multiplier = self.rng.choice([10.0, 100.0, 1000.0, 5000.0], p=[0.5, 0.3, 0.15, 0.05])
            reward += jackpot_multiplier
        else:
            self.regime = 0 # Free flight
            
        obs = self._get_obs()
        return obs, reward, self.regime

    def rollout_trajectory(self, horizon=40):
        """Generate a complete trajectory for RSSM evaluation."""
        obs_list = []
        action_list = []
        reward_list = []
        regime_list = []
        
        obs, _ = self.reset()
        obs_list.append(obs)
        
        for _ in range(horizon):
            # Smoothly correlated continuous control
            act = np.clip(self.rng.normal(0.0, 0.6, self.action_dim), -1.0, 1.0)
            next_obs, rew, reg = self.step(act)
            obs_list.append(next_obs)
            action_list.append(act)
            reward_list.append(rew)
            regime_list.append(reg)
            
        return (np.array(obs_list),
                np.array(action_list),
                np.array(reward_list),
                np.array(regime_list))

# ---------------------------------------------------------------------------
# GRU Recurrent Cell with Gradient Computation
# ---------------------------------------------------------------------------

class GRUCell:
    """
    Standard Gated Recurrent Unit (GRU) with clean analytic weights.
    h_t = (1 - z) * n + z * h_{t-1}
    """
    def __init__(self, input_dim, hidden_dim, seed=42):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        rng = np.random.RandomState(seed)
        
        limit_ih = np.sqrt(6.0 / (input_dim + hidden_dim))
        limit_hh = np.sqrt(6.0 / (hidden_dim + hidden_dim))
        
        # 3 gates: reset (r), update (z), new state (n)
        self.W_ih = rng.uniform(-limit_ih, limit_ih, (3 * hidden_dim, input_dim))
        self.W_hh = rng.uniform(-limit_hh, limit_hh, (3 * hidden_dim, hidden_dim))
        self.b_ih = np.zeros(3 * hidden_dim)
        self.b_hh = np.zeros(3 * hidden_dim)

    def forward(self, x, h_prev):
        """
        x: (input_dim,)
        h_prev: (hidden_dim,)
        """
        H = self.hidden_dim
        gi = np.dot(self.W_ih, x) + self.b_ih
        gh = np.dot(self.W_hh, h_prev) + self.b_hh
        
        r_gate = sigmoid(gi[0:H] + gh[0:H])
        z_gate = sigmoid(gi[H:2*H] + gh[H:2*H])
        n_cand = tanh(gi[2*H:3*H] + r_gate * gh[2*H:3*H])
        
        h_next = (1.0 - z_gate) * n_cand + z_gate * h_prev
        return h_next, (r_gate, z_gate, n_cand, x, h_prev)

# ---------------------------------------------------------------------------
# Multi-Layer Perceptron (MLP) Layer
# ---------------------------------------------------------------------------

class DenseLayer:
    """Fully connected linear layer with bias and optional activation."""
    def __init__(self, in_features, out_features, activation='none', seed=42):
        self.in_features = in_features
        self.out_features = out_features
        self.activation = activation
        
        rng = np.random.RandomState(seed)
        limit = np.sqrt(6.0 / (in_features + out_features))
        self.W = rng.uniform(-limit, limit, (out_features, in_features))
        self.b = np.zeros(out_features)
        
        # Adam optimizer cache
        self.mW = np.zeros_like(self.W)
        self.vW = np.zeros_like(self.W)
        self.mb = np.zeros_like(self.b)
        self.vb = np.zeros_like(self.b)

    def forward(self, x):
        lin = np.dot(self.W, x) + self.b
        if self.activation == 'relu':
            out = relu(lin)
        elif self.activation == 'tanh':
            out = tanh(lin)
        elif self.activation == 'none':
            out = lin
        else:
            raise ValueError(f"Unknown activation: {self.activation}")
        return out, (x, lin, out)

    def backward(self, grad_output, cache):
        x, lin, out = cache
        if self.activation == 'relu':
            grad_lin = grad_output * d_relu(lin)
        elif self.activation == 'tanh':
            grad_lin = grad_output * d_tanh(out)
        else:
            grad_lin = grad_output
            
        grad_W = np.outer(grad_lin, x)
        grad_b = np.copy(grad_lin)
        grad_x = np.dot(self.W.T, grad_lin)
        return grad_x, grad_W, grad_b

    def step_adam(self, grad_W, grad_b, lr=1e-3, beta1=0.9, beta2=0.999, eps=1e-8, t=1):
        """Adam parameter update step."""
        grad_W_clipped = np.clip(grad_W, -10.0, 10.0)
        grad_b_clipped = np.clip(grad_b, -10.0, 10.0)
        
        self.mW = beta1 * self.mW + (1.0 - beta1) * grad_W_clipped
        self.vW = beta2 * self.vW + (1.0 - beta2) * (grad_W_clipped ** 2)
        mW_hat = self.mW / (1.0 - beta1 ** t)
        vW_hat = self.vW / (1.0 - beta2 ** t)
        self.W -= lr * mW_hat / (np.sqrt(vW_hat) + eps)
        
        self.mb = beta1 * self.mb + (1.0 - beta1) * grad_b_clipped
        self.vb = beta2 * self.vb + (1.0 - beta2) * (grad_b_clipped ** 2)
        mb_hat = self.mb / (1.0 - beta1 ** t)
        vb_hat = self.vb / (1.0 - beta2 ** t)
        self.b -= lr * mb_hat / (np.sqrt(vb_hat) + eps)

# ---------------------------------------------------------------------------
# Complete RSSM Models: Continuous vs Discrete
# ---------------------------------------------------------------------------

class ContinuousGaussianRSSM:
    """
    Continuous Gaussian RSSM (PlaNet / DreamerV1 style).
    - Latent state: s_t = (h_t, z_t), where z_t ~ N(mu, sigma^2), dim=32.
    - Recurrence: h_t = GRU([z_{t-1}, a_{t-1}], h_{t-1})
    - Prior: p(z_t | h_t)
    - Posterior: q(z_t | h_t, x_t)
    - Observation Decoder: [h_t, z_t] -> x_hat_t
    """
    def __init__(self, obs_dim=16, action_dim=2, deter_dim=128, stoch_dim=32, seed=42):
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.deter_dim = deter_dim
        self.stoch_dim = stoch_dim
        self.gaussian = GaussianLatent(dim=stoch_dim, min_std=0.1)
        
        # Deterministic GRU cell
        self.gru = GRUCell(input_dim=stoch_dim + action_dim, hidden_dim=deter_dim, seed=seed)
        
        # Prior network: h_t -> hidden -> (mean, std)
        self.prior_mlp = DenseLayer(deter_dim, 64, activation='relu', seed=seed+1)
        self.prior_mean = DenseLayer(64, stoch_dim, activation='none', seed=seed+2)
        self.prior_std_raw = DenseLayer(64, stoch_dim, activation='none', seed=seed+3)
        
        # Posterior network: [h_t, x_t] -> hidden -> (mean, std)
        self.post_mlp = DenseLayer(deter_dim + obs_dim, 64, activation='relu', seed=seed+4)
        self.post_mean = DenseLayer(64, stoch_dim, activation='none', seed=seed+5)
        self.post_std_raw = DenseLayer(64, stoch_dim, activation='none', seed=seed+6)
        
        # Observation decoder: [h_t, z_t] -> hidden -> x_hat
        self.dec_mlp = DenseLayer(deter_dim + stoch_dim, 64, activation='relu', seed=seed+7)
        self.dec_out = DenseLayer(64, obs_dim, activation='none', seed=seed+8)
        
        self.train_step_count = 0

    def init_state(self):
        h = np.zeros(self.deter_dim)
        z = np.zeros(self.stoch_dim)
        return h, z

    def compute_prior(self, h):
        feat, c1 = self.prior_mlp.forward(h)
        mean, c2 = self.prior_mean.forward(feat)
        raw_std, c3 = self.prior_std_raw.forward(feat)
        std = self.gaussian.transform_std(raw_std)
        return mean, std, (c1, c2, c3, raw_std)

    def compute_posterior(self, h, obs):
        inp = np.concatenate([h, obs])
        feat, c1 = self.post_mlp.forward(inp)
        mean, c2 = self.post_mean.forward(feat)
        raw_std, c3 = self.post_std_raw.forward(feat)
        std = self.gaussian.transform_std(raw_std)
        return mean, std, (c1, c2, c3, raw_std)

    def decode_obs(self, h, z):
        feat = np.concatenate([h, z])
        hid, c1 = self.dec_mlp.forward(feat)
        pred_obs, c2 = self.dec_out.forward(hid)
        return pred_obs, (c1, c2)

    def observe_step(self, prev_h, prev_z, action, obs):
        """Closed-loop filter step conditioned on ground-truth observation."""
        gru_in = np.concatenate([prev_z, action])
        h_t, gru_cache = self.gru.forward(gru_in, prev_h)
        
        prior_mean, prior_std, prior_cache = self.compute_prior(h_t)
        post_mean, post_std, post_cache = self.compute_posterior(h_t, obs)
        
        z_sample, eps = self.gaussian.sample_reparameterized(post_mean, post_std)
        kl = self.gaussian.kl_divergence(post_mean, post_std, prior_mean, prior_std)
        
        pred_obs, dec_cache = self.decode_obs(h_t, z_sample)
        recon_loss = np.mean((pred_obs - obs) ** 2)
        
        step_data = {
            'h_t': h_t,
            'z_t': z_sample,
            'prior_mean': prior_mean,
            'prior_std': prior_std,
            'post_mean': post_mean,
            'post_std': post_std,
            'kl': kl,
            'pred_obs': pred_obs,
            'recon_loss': recon_loss,
            'entropy': self.gaussian.entropy(post_std),
            'caches': (gru_cache, prior_cache, post_cache, dec_cache, eps)
        }
        return h_t, z_sample, step_data

    def imagine_step(self, prev_h, prev_z, action):
        """Open-loop hallucination/imagination step purely relying on internal prior."""
        gru_in = np.concatenate([prev_z, action])
        h_t, _ = self.gru.forward(gru_in, prev_h)
        prior_mean, prior_std, _ = self.compute_prior(h_t)
        z_sample, _ = self.gaussian.sample_reparameterized(prior_mean, prior_std)
        pred_obs, _ = self.decode_obs(h_t, z_sample)
        return h_t, z_sample, pred_obs

    def train_step_sgd(self, step_data, obs, kl_balance_alpha=0.8, lr=1e-3):
        """
        Backpropagation training step for Continuous Gaussian RSSM.
        Applies KL dynamic balancing:
        L_KL = alpha * KL(sg(q) || p) + (1 - alpha) * KL(q || sg(p))
        """
        self.train_step_count += 1
        t = self.train_step_count
        
        pred_obs = step_data['pred_obs']
        recon_err = (pred_obs - obs) # d(0.5 * MSE) / d(pred_obs) = (pred_obs - obs) / dim
        d_pred = 2.0 * recon_err / self.obs_dim
        
        # 1. Backprop through decoder
        gru_cache, prior_cache, post_cache, dec_cache, eps = step_data['caches']
        c_dec1, c_dec2 = dec_cache
        d_hid, dW_dec2, db_dec2 = self.dec_out.backward(d_pred, c_dec2)
        d_feat, dW_dec1, db_dec1 = self.dec_mlp.backward(d_hid, c_dec1)
        
        # d_feat splits into d_h and d_z
        d_h_dec = d_feat[:self.deter_dim]
        d_z_dec = d_feat[self.deter_dim:]
        
        # 2. Gradient of posterior reparameterization: z = post_mean + post_std * eps
        d_post_mean_recon = d_z_dec
        d_post_std_recon = d_z_dec * eps
        
        # 3. KL Balancing gradients
        # KL(q || p) = ln(s_p/s_q) + (s_q^2 + (m_q - m_p)^2)/(2 s_p^2) - 0.5
        m_q = step_data['post_mean']
        s_q = step_data['post_std']
        m_p = step_data['prior_mean']
        s_p = step_data['prior_std']
        
        # Gradient w.r.t prior (scaled by alpha):
        # dKL/dm_p = -(m_q - m_p) / (s_p^2)
        # dKL/ds_p = 1/s_p - (s_q^2 + (m_q - m_p)^2) / (s_p^3)
        d_m_p_kl = kl_balance_alpha * (-(m_q - m_p) / (s_p ** 2))
        d_s_p_kl = kl_balance_alpha * (1.0 / s_p - (s_q ** 2 + (m_q - m_p) ** 2) / (s_p ** 3))
        
        # Gradient w.r.t posterior (scaled by (1 - alpha)):
        # dKL/dm_q = (m_q - m_p) / (s_p^2)
        # dKL/ds_q = -1/s_q + s_q / (s_p^2)
        d_m_q_kl = (1.0 - kl_balance_alpha) * ((m_q - m_p) / (s_p ** 2))
        d_s_q_kl = (1.0 - kl_balance_alpha) * (-1.0 / s_q + s_q / (s_p ** 2))
        
        # Backprop through Prior network
        c_p1, c_p2, c_p3, raw_std_p = prior_cache
        # std = softplus(raw_std) + 0.1 => d_std / d_raw = sigmoid(raw_std)
        d_raw_s_p = d_s_p_kl * sigmoid(raw_std_p)
        
        d_feat_p_mean, dW_p_mean, db_p_mean = self.prior_mean.backward(d_m_p_kl, c_p2)
        d_feat_p_std, dW_p_std, db_p_std = self.prior_std_raw.backward(d_raw_s_p, c_p3)
        d_feat_p = d_feat_p_mean + d_feat_p_std
        d_h_prior, dW_p_mlp, db_p_mlp = self.prior_mlp.backward(d_feat_p, c_p1)
        
        # Backprop through Posterior network
        total_d_m_q = d_post_mean_recon + d_m_q_kl
        total_d_s_q = d_post_std_recon + d_s_q_kl
        raw_std_q = post_cache[3]
        d_raw_s_q = total_d_s_q * sigmoid(raw_std_q)
        
        c_q1, c_q2, c_q3, _ = post_cache
        d_feat_q_mean, dW_q_mean, db_q_mean = self.post_mean.backward(total_d_m_q, c_q2)
        d_feat_q_std, dW_q_std, db_q_std = self.post_std_raw.backward(d_raw_s_q, c_q3)
        d_feat_q = d_feat_q_mean + d_feat_q_std
        d_inp_post, dW_q_mlp, db_q_mlp = self.post_mlp.backward(d_feat_q, c_q1)
        
        # Update layers with Adam
        self.dec_out.step_adam(dW_dec2, db_dec2, lr=lr, t=t)
        self.dec_mlp.step_adam(dW_dec1, db_dec1, lr=lr, t=t)
        self.prior_mean.step_adam(dW_p_mean, db_p_mean, lr=lr, t=t)
        self.prior_std_raw.step_adam(dW_p_std, db_p_std, lr=lr, t=t)
        self.prior_mlp.step_adam(dW_p_mlp, db_p_mlp, lr=lr, t=t)
        self.post_mean.step_adam(dW_q_mean, db_q_mean, lr=lr, t=t)
        self.post_std_raw.step_adam(dW_q_std, db_q_std, lr=lr, t=t)
        self.post_mlp.step_adam(dW_q_mlp, db_q_mlp, lr=lr, t=t)
        
        # Compute and return gradient norm summary
        grad_norm = math.sqrt(
            np.sum(dW_dec2**2) + np.sum(dW_p_mean**2) + np.sum(dW_q_mean**2)
        )
        return grad_norm

# ---------------------------------------------------------------------------
# Discrete Categorical RSSM (DreamerV2 / DreamerV3 Style)
# ---------------------------------------------------------------------------

class DiscreteCategoricalRSSM:
    """
    Discrete Categorical RSSM (DreamerV2 / DreamerV3 style).
    - Latent state: s_t = (h_t, z_t), where z_t is a concatenation of N=32 categorical distributions
      each with K=32 classes (total size 32 * 32 = 1024).
    - Straight-Through Estimator (STE) for discrete one-hot samples with continuous gradients.
    - DreamerV3 Unimix regularization (0.01) ensuring bounded KL and gradient flow.
    - Observation Decoder: [h_t, z_t] -> x_hat_t
    """
    def __init__(self, obs_dim=16, action_dim=2, deter_dim=128, num_vars=32, num_classes=32, seed=42):
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.deter_dim = deter_dim
        self.num_vars = num_vars
        self.num_classes = num_classes
        self.stoch_dim = num_vars * num_classes # 1024
        self.categorical = CategoricalLatent(num_vars=num_vars, num_classes=num_classes, unimix_ratio=0.01)
        
        # Deterministic GRU cell
        self.gru = GRUCell(input_dim=self.stoch_dim + action_dim, hidden_dim=deter_dim, seed=seed)
        
        # Prior network: h_t -> hidden -> logits (32 * 32)
        self.prior_mlp = DenseLayer(deter_dim, 64, activation='relu', seed=seed+1)
        self.prior_logits = DenseLayer(64, self.stoch_dim, activation='none', seed=seed+2)
        
        # Posterior network: [h_t, x_t] -> hidden -> logits (32 * 32)
        self.post_mlp = DenseLayer(deter_dim + obs_dim, 64, activation='relu', seed=seed+3)
        self.post_logits = DenseLayer(64, self.stoch_dim, activation='none', seed=seed+4)
        
        # Observation decoder: [h_t, z_t] -> hidden -> x_hat
        self.dec_mlp = DenseLayer(deter_dim + self.stoch_dim, 64, activation='relu', seed=seed+5)
        self.dec_out = DenseLayer(64, obs_dim, activation='none', seed=seed+6)
        
        self.train_step_count = 0

    def init_state(self):
        h = np.zeros(self.deter_dim)
        z = np.zeros(self.stoch_dim)
        return h, z

    def compute_prior(self, h):
        feat, c1 = self.prior_mlp.forward(h)
        logits, c2 = self.prior_logits.forward(feat)
        probs = self.categorical.logits_to_probs(logits)
        return logits, probs, (c1, c2)

    def compute_posterior(self, h, obs):
        inp = np.concatenate([h, obs])
        feat, c1 = self.post_mlp.forward(inp)
        logits, c2 = self.post_logits.forward(feat)
        probs = self.categorical.logits_to_probs(logits)
        return logits, probs, (c1, c2)

    def decode_obs(self, h, z):
        feat = np.concatenate([h, z])
        hid, c1 = self.dec_mlp.forward(feat)
        pred_obs, c2 = self.dec_out.forward(hid)
        return pred_obs, (c1, c2)

    def observe_step(self, prev_h, prev_z, action, obs):
        """Closed-loop filter step conditioned on ground-truth observation."""
        gru_in = np.concatenate([prev_z, action])
        h_t, gru_cache = self.gru.forward(gru_in, prev_h)
        
        prior_logits, prior_probs, prior_cache = self.compute_prior(h_t)
        post_logits, post_probs, post_cache = self.compute_posterior(h_t, obs)
        
        # Sample discrete categorical one-hot vectors using Straight-Through
        z_sample = self.categorical.sample_ste(post_probs)
        kl = float(self.categorical.kl_divergence(post_probs, prior_probs)[0])
        
        pred_obs, dec_cache = self.decode_obs(h_t, z_sample)
        recon_loss = np.mean((pred_obs - obs) ** 2)
        
        step_data = {
            'h_t': h_t,
            'z_t': z_sample,
            'prior_probs': prior_probs,
            'post_probs': post_probs,
            'prior_logits': prior_logits,
            'post_logits': post_logits,
            'kl': kl,
            'pred_obs': pred_obs,
            'recon_loss': recon_loss,
            'entropy': float(self.categorical.entropy(post_probs)[0]),
            'caches': (gru_cache, prior_cache, post_cache, dec_cache)
        }
        return h_t, z_sample, step_data

    def imagine_step(self, prev_h, prev_z, action):
        """Open-loop hallucination/imagination step purely relying on internal prior."""
        gru_in = np.concatenate([prev_z, action])
        h_t, _ = self.gru.forward(gru_in, prev_h)
        _, prior_probs, _ = self.compute_prior(h_t)
        z_sample = self.categorical.sample_ste(prior_probs)
        pred_obs, _ = self.decode_obs(h_t, z_sample)
        return h_t, z_sample, pred_obs

    def train_step_sgd(self, step_data, obs, kl_balance_alpha=0.8, lr=1e-3):
        """
        Backpropagation training step for Discrete Categorical RSSM with Straight-Through Estimator.
        Applies KL dynamic balancing:
        L_KL = alpha * KL(sg(q) || p) + (1 - alpha) * KL(q || sg(p))
        """
        self.train_step_count += 1
        t = self.train_step_count
        
        pred_obs = step_data['pred_obs']
        recon_err = (pred_obs - obs)
        d_pred = 2.0 * recon_err / self.obs_dim
        
        # 1. Backprop through decoder
        gru_cache, prior_cache, post_cache, dec_cache = step_data['caches']
        c_dec1, c_dec2 = dec_cache
        d_hid, dW_dec2, db_dec2 = self.dec_out.backward(d_pred, c_dec2)
        d_feat, dW_dec1, db_dec1 = self.dec_mlp.backward(d_hid, c_dec1)
        
        # Straight-Through: d_z directly gradients to post_probs!
        d_z = d_feat[self.deter_dim:]
        
        # 2. KL balancing gradients for categorical logits:
        # KL(q || p) = sum q * (ln q - ln p)
        # Gradient w.r.t prior logits ell_p:
        # dKL / d(ell_p) = alpha * (p - q)
        # Gradient w.r.t posterior logits ell_q:
        # dKL / d(ell_q) = (1 - alpha) * (q * (ln q - ln p - KL_v))
        # Straight-Through gradient to posterior logits from reconstruction:
        # For softmax, d_loss / d_ell = probs * (d_loss / d_probs - sum(probs * d_loss / d_probs))
        
        q = step_data['post_probs'].reshape(self.num_vars, self.num_classes)
        p = step_data['prior_probs'].reshape(self.num_vars, self.num_classes)
        eps = 1e-12
        q_safe = np.clip(q, eps, 1.0)
        p_safe = np.clip(p, eps, 1.0)
        
        # Prior logit gradient (Prior chases Posterior):
        # When minimizing -ln p(z) under q(z), gradient is (p - q)
        d_prior_logits = kl_balance_alpha * (p - q).flatten()
        
        # Posterior logit gradient from KL:
        log_diff = np.log(q_safe) - np.log(p_safe)
        kl_per_var = np.sum(q_safe * log_diff, axis=-1, keepdims=True)
        d_post_kl_logits = (1.0 - kl_balance_alpha) * (q_safe * (log_diff - kl_per_var)).flatten()
        
        # Posterior logit gradient from Reconstruction (via STE):
        d_z_reshaped = d_z.reshape(self.num_vars, self.num_classes)
        d_post_recon_logits = (q * (d_z_reshaped - np.sum(q * d_z_reshaped, axis=-1, keepdims=True))).flatten()
        
        total_d_post_logits = d_post_recon_logits + d_post_kl_logits
        
        # Backprop through Prior network
        c_p1, c_p2 = prior_cache
        d_feat_p, dW_p_logits, db_p_logits = self.prior_logits.backward(d_prior_logits, c_p2)
        d_h_prior, dW_p_mlp, db_p_mlp = self.prior_mlp.backward(d_feat_p, c_p1)
        
        # Backprop through Posterior network
        c_q1, c_q2 = post_cache
        d_feat_q, dW_q_logits, db_q_logits = self.post_logits.backward(total_d_post_logits, c_q2)
        d_inp_post, dW_q_mlp, db_q_mlp = self.post_mlp.backward(d_feat_q, c_q1)
        
        # Update layers with Adam
        self.dec_out.step_adam(dW_dec2, db_dec2, lr=lr, t=t)
        self.dec_mlp.step_adam(dW_dec1, db_dec1, lr=lr, t=t)
        self.prior_logits.step_adam(dW_p_logits, db_p_logits, lr=lr, t=t)
        self.prior_mlp.step_adam(dW_p_mlp, db_p_mlp, lr=lr, t=t)
        self.post_logits.step_adam(dW_q_logits, db_q_logits, lr=lr, t=t)
        self.post_mlp.step_adam(dW_q_mlp, db_q_mlp, lr=lr, t=t)
        
        grad_norm = math.sqrt(
            np.sum(dW_dec2**2) + np.sum(dW_p_logits**2) + np.sum(dW_q_logits**2)
        )
        return grad_norm
