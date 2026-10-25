"""
Composite Simulation Environment for World Model Robustness Benchmark
====================================================================
Environment with:
1. Low-dimensional core task: Continuous 2D point-mass tracking moving target.
2. High-entropy, multi-modal task-irrelevant visual distractors:
   - Dynamic White Noise (unpredictable i.i.d. Gaussian pixels)
   - Flickering TV Screen (high-contrast alternating pseudo-random checkerboard/static window)
   - Shaking Foliage (spatially-correlated autoregressive Markovian texture)
"""

import numpy as np


class CompositeDistractorEnv:
    def __init__(self, grid_size=16, noise_ratio=0.0, seed=42):
        """
        grid_size: H=W of rendered visual observation (e.g. 16x16 = 256 pixels)
        noise_ratio: eta in [0.0, 1.0], blending ratio between task signal and distractor.
        """
        self.grid_size = grid_size
        self.noise_ratio = noise_ratio
        self.rng = np.random.RandomState(seed)
        
        # Action space: 5 discrete actions
        # 0: Stay, 1: Up, 2: Down, 3: Left, 4: Right
        self.action_dim = 5
        self.action_vectors = np.array([
            [0.0, 0.0],   # Stay
            [0.0, 0.15],  # Up
            [0.0, -0.15], # Down
            [-0.15, 0.0], # Left
            [0.15, 0.0],  # Right
        ], dtype=np.float32)
        
        # Distractor sub-region coordinates (TV window: 5x5 in top-right)
        self.tv_r_slice = slice(1, 6)
        self.tv_c_slice = slice(10, 15)
        
        # Foliage autoregressive state (16x16)
        self.foliage_state = np.zeros((grid_size, grid_size), dtype=np.float32)
        
        self.reset()
        
    def reset(self, seed=None):
        if seed is not None:
            self.rng = np.random.RandomState(seed)
            
        # Agent position and velocity in [-1, 1]
        self.agent_pos = self.rng.uniform(-0.6, 0.6, size=2).astype(np.float32)
        self.agent_vel = np.zeros(2, dtype=np.float32)
        
        # Target position in [-1, 1]
        self.target_pos = self.rng.uniform(-0.6, 0.6, size=2).astype(np.float32)
        self.target_theta = self.rng.uniform(0, 2 * np.pi)
        
        # Distractor initializations
        self.foliage_state = self.rng.normal(0, 1.0, size=(self.grid_size, self.grid_size)).astype(np.float32)
        self.tv_pattern = self.rng.choice([0.0, 1.0], size=(5, 5)).astype(np.float32)
        self.tv_counter = 0
        
        self.step_count = 0
        self.max_steps = 50
        
        return self._get_obs(), self._get_true_state()
        
    def _get_true_state(self):
        """Returns ground-truth physical 6D state: [pos_x, pos_y, vel_x, vel_y, target_x, target_y]"""
        return np.concatenate([self.agent_pos, self.agent_vel, self.target_pos]).astype(np.float32)
        
    def _render_signal(self):
        """Render agent and target as smooth Gaussian blobs on grid."""
        H = W = self.grid_size
        xs = np.linspace(-1.0, 1.0, W)
        ys = np.linspace(1.0, -1.0, H)
        grid_x, grid_y = np.meshgrid(xs, ys)
        
        # Agent blob (sigma = 0.25)
        d_agent = (grid_x - self.agent_pos[0]) ** 2 + (grid_y - self.agent_pos[1]) ** 2
        agent_img = np.exp(-d_agent / (2.0 * (0.22 ** 2)))
        
        # Target blob (sigma = 0.20)
        d_target = (grid_x - self.target_pos[0]) ** 2 + (grid_y - self.target_pos[1]) ** 2
        target_img = np.exp(-d_target / (2.0 * (0.18 ** 2)))
        
        # Combine: Agent is intensity 0.9, Target is intensity 0.5
        signal_img = 0.9 * agent_img + 0.5 * target_img
        return np.clip(signal_img, 0.0, 1.0).astype(np.float32)
        
    def _render_distractors(self):
        """Render composite multi-modal distractors."""
        H = W = self.grid_size
        
        # 1. Dynamic White Noise (unpredictable i.i.d.)
        white_noise = self.rng.uniform(0.0, 1.0, size=(H, W)).astype(np.float32)
        
        # 2. Flickering TV Screen (alternating high contrast pattern every 2 steps)
        self.tv_counter += 1
        if self.tv_counter % 2 == 0:
            self.tv_pattern = self.rng.choice([0.1, 0.9], size=(5, 5)).astype(np.float32)
        tv_layer = np.zeros((H, W), dtype=np.float32)
        tv_layer[self.tv_r_slice, self.tv_c_slice] = self.tv_pattern
        
        # 3. Shaking foliage (Autoregressive spatially smoothed 2D noise)
        # AR(1) temporal update: F_t = 0.75 * F_{t-1} + sqrt(1 - 0.75^2) * N(0, 1)
        ar_noise = self.rng.normal(0, 1.0, size=(H, W)).astype(np.float32)
        self.foliage_state = 0.75 * self.foliage_state + np.sqrt(1.0 - 0.75**2) * ar_noise
        # Simple spatial 3x3 box blur for spatial correlation
        f_pad = np.pad(self.foliage_state, 1, mode='wrap')
        foliage_blurred = (
            f_pad[0:-2, 0:-2] + f_pad[0:-2, 1:-1] + f_pad[0:-2, 2:] +
            f_pad[1:-1, 0:-2] + f_pad[1:-1, 1:-1] + f_pad[1:-1, 2:] +
            f_pad[2:, 0:-2]   + f_pad[2:, 1:-1]   + f_pad[2:, 2:]
        ) / 9.0
        foliage_norm = 1.0 / (1.0 + np.exp(-foliage_blurred)) # sigmoid to [0, 1]
        
        # Blended distractor
        distractor_img = 0.35 * white_noise + 0.35 * tv_layer + 0.30 * foliage_norm
        return np.clip(distractor_img, 0.0, 1.0).astype(np.float32)
        
    def _get_obs(self):
        """Combine signal and distractor according to noise_ratio."""
        sig = self._render_signal()
        dist = self._render_distractors()
        obs = (1.0 - self.noise_ratio) * sig + self.noise_ratio * dist
        return obs.flatten().astype(np.float32)
        
    def step(self, action):
        self.step_count += 1
        
        # Update agent physics
        act_vec = self.action_vectors[action]
        self.agent_vel = 0.80 * self.agent_vel + act_vec
        self.agent_pos = np.clip(self.agent_pos + self.agent_vel, -1.0, 1.0)
        
        # Update target motion (smooth circular Lissajous motion + small noise)
        self.target_theta += 0.15
        target_drift = 0.03 * np.array([np.cos(self.target_theta), np.sin(self.target_theta * 1.5)], dtype=np.float32)
        target_drift += self.rng.normal(0, 0.02, size=2).astype(np.float32)
        self.target_pos = np.clip(self.target_pos + target_drift, -0.85, 0.85)
        
        # Distance & Reward
        dist_to_target = float(np.linalg.norm(self.agent_pos - self.target_pos))
        # Continuous shaping + bonus for close proximity
        reward = -dist_to_target + (1.5 if dist_to_target < 0.25 else 0.0)
        
        done = (self.step_count >= self.max_steps)
        info = {
            "dist": dist_to_target,
            "captured": (dist_to_target < 0.25),
            "true_state": self._get_true_state(),
            "tv_val": float(self.tv_pattern.mean())
        }
        
        return self._get_obs(), reward, done, info
