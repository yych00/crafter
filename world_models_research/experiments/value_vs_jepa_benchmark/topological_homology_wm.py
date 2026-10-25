"""
Topological Homology & Persistent Homology Latent World Models Benchmark
========================================================================
Phase 7: Persistent Homology & Vietoris-Rips Filtration in World Models.
Preserves algebraic topological structures (Betti numbers beta_0, beta_1) during:
1. Dynamic Untangling of Linked Rings (Hopf Link phase change)
2. Torus Pinch-Off Topological Phase Transition

Compares:
- Standard Euclidean RSSM (Recurrent State Space Model, L2-only loss)
- Standard Latent VAE (Variational Autoencoder without topological regularization)
- TDA-WM (Topological Data Analysis World Model with Persistent Metric Regularization, Ours)

Evaluates:
- Persistent Homology Bottleneck Distance (d_B)
- Betti Number Identification Accuracy (beta_0, beta_1)
- Topological False Crossing Rate (% unphysical ring penetrations)
- Autoregressive Trajectory MSE
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
# 1. Algebraic Topology & Persistent Homology Engine (Pure NumPy)
# ==============================================================================

def compute_pairwise_distances(X):
    """Pairwise Euclidean distance matrix for point cloud X of shape (N, D)."""
    diff = X[:, None, :] - X[None, :, :]
    return np.sqrt(np.sum(diff ** 2, axis=-1) + 1e-12)


def compute_persistence_diagrams(points, max_edge=1.3):
    """
    Computes exact 0D (connected components) and 1D (loops/tunnels) Persistence Diagrams
    using Vietoris-Rips filtration and Z_2 boundary matrix reduction.
    Returns:
      dgm0: list of (birth, death) for H_0
      dgm1: list of (birth, death) for H_1
    """
    N = points.shape[0]
    dist = compute_pairwise_distances(points)
    
    simplices = []
    # 0-simplices
    for i in range(N):
        simplices.append((0.0, 0, (i,)))
        
    # 1-simplices
    for i in range(N):
        for j in range(i + 1, N):
            d = dist[i, j]
            if d <= max_edge:
                simplices.append((d, 1, (i, j)))
                
    # 2-simplices
    for i in range(N):
        for j in range(i + 1, N):
            d_ij = dist[i, j]
            if d_ij > max_edge:
                continue
            for k in range(j + 1, N):
                d_jk = dist[j, k]
                d_ik = dist[i, k]
                d_tri = max(d_ij, d_jk, d_ik)
                if d_tri <= max_edge:
                    simplices.append((d_tri, 2, (i, j, k)))
                    
    # Sort simplices: filtration value first, then dimension (faces precede cofaces)
    simplices.sort(key=lambda s: (s[0], s[1]))
    simplex_to_idx = {s[2]: idx for idx, s in enumerate(simplices)}
    M = len(simplices)
    
    # Boundary matrix columns over Z_2
    R = [set() for _ in range(M)]
    for idx, (val, dim, verts) in enumerate(simplices):
        if dim == 1:
            i, j = verts
            R[idx] = {simplex_to_idx[(i,)], simplex_to_idx[(j,)]}
        elif dim == 2:
            i, j, k = verts
            R[idx] = {simplex_to_idx[(i, j)], simplex_to_idx[(i, k)], simplex_to_idx[(j, k)]}
            
    # Standard matrix reduction over Z_2
    low = {}
    for j in range(M):
        while len(R[j]) > 0:
            i = max(R[j])
            if i in low:
                R[j] = R[j] ^ R[low[i]]
            else:
                low[i] = j
                break
                
    dgm0 = []
    dgm1 = []
    max_death_bound = max_edge * 1.5
    for i in range(M):
        val_i, dim_i, _ = simplices[i]
        if i in low:
            j = low[i]
            val_j, dim_j, _ = simplices[j]
            if val_j > val_i + 1e-4:
                if dim_i == 0:
                    dgm0.append((val_i, val_j))
                elif dim_i == 1:
                    dgm1.append((val_i, val_j))
        else:
            if dim_i == 0:
                dgm0.append((val_i, max_death_bound))
            elif dim_i == 1 and len(R[i]) == 0:
                dgm1.append((val_i, max_death_bound))
                
    return dgm0, dgm1


def extract_betti_numbers(dgm0, dgm1, persistence_threshold=0.10):
    """
    Calculates macroscopic Betti numbers beta_0 and beta_1 by counting
    topological features whose lifespan (death - birth) exceeds persistence_threshold.
    """
    # beta_0: count components whose lifespan > 0.25 (excluding boundary bound) + 1
    pers0 = [d - b for b, d in dgm0 if d < 1.4]
    beta_0 = 1 + sum(1 for p in pers0 if p > 0.25)
    
    # beta_1: count prominent 1D topological cycles
    num_cycles = sum(1 for b, d in dgm1 if (d - b) > persistence_threshold)
    if num_cycles >= 2:
        beta_1 = 2
    elif num_cycles == 1:
        beta_1 = 1
    else:
        beta_1 = 0
        
    return int(beta_0), int(beta_1)


def bottleneck_distance(dgmA, dgmB, min_persistence=0.08, max_features=4):
    """
    Computes exact Bottleneck Distance d_B between two persistence diagrams on top prominent features.
    d_B(Dgm_A, Dgm_B) = inf_gamma sup_p ||p - gamma(p)||_inf
    """
    ptsA = sorted([p for p in dgmA if (p[1] - p[0]) > min_persistence],
                  key=lambda p: p[1] - p[0], reverse=True)[:max_features]
    ptsB = sorted([p for p in dgmB if (p[1] - p[0]) > min_persistence],
                  key=lambda p: p[1] - p[0], reverse=True)[:max_features]
    
    if len(ptsA) == 0 and len(ptsB) == 0:
        return 0.0
    if len(ptsA) == 0:
        return max((d - b) / 2.0 for b, d in ptsB)
    if len(ptsB) == 0:
        return max((d - b) / 2.0 for b, d in ptsA)
        
    nA = len(ptsA)
    nB = len(ptsB)
    
    cost_mat = np.zeros((nA, nB), dtype=np.float32)
    for i in range(nA):
        for j in range(nB):
            cost_mat[i, j] = max(abs(ptsA[i][0] - ptsB[j][0]), abs(ptsA[i][1] - ptsB[j][1]))
            
    diagA = np.array([(d - b) / 2.0 for b, d in ptsA], dtype=np.float32)
    diagB = np.array([(d - b) / 2.0 for b, d in ptsB], dtype=np.float32)
    
    def solve(i, usedB, current_max):
        if i == nA:
            for j in range(nB):
                if not (usedB & (1 << j)):
                    current_max = max(current_max, diagB[j])
            return current_max
            
        best = solve(i + 1, usedB, max(current_max, diagA[i]))
        for j in range(nB):
            if not (usedB & (1 << j)):
                cost = max(current_max, cost_mat[i, j])
                if cost < best:
                    sub = solve(i + 1, usedB | (1 << j), cost)
                    best = min(best, sub)
        return best

    return float(solve(0, 0, 0.0))


# ==============================================================================
# 2. Physics Sandboxes with Non-Trivial Topological Transitions
# ==============================================================================

class LinkedRingsPhysicsEnv:
    """
    Dynamic Hopf Link Untangling Sandbox:
    Two 3D closed elastic rings.
    Initial state: Linked (Linking Number Lk = 1, beta_1 = 2).
    Dynamics: Ring 2 is pulled along a 3D trajectory to untangle from Ring 1.
    Final state: Unlinked (Linking Number Lk = 0, beta_0 = 2, beta_1 = 2 separated).
    Euclidean-only models fail by falsely penetrating (False Crossing).
    """
    def __init__(self, num_points_per_ring=16, seed=42):
        self.num_pts = num_points_per_ring
        self.rng = np.random.RandomState(seed)
        self.max_steps = 15
        self.r1 = 0.50
        self.r2 = 0.50
        self.reset()

    def reset(self, seed=None):
        if seed is not None:
            self.rng = np.random.RandomState(seed)
        self.step_t = 0
        self.ring2_offset = np.array([0.25, 0.0, 0.0], dtype=np.float32)
        return self._generate_point_cloud()

    def _generate_point_cloud(self):
        theta = np.linspace(0, 2*np.pi, self.num_pts, endpoint=False)
        # Ring 1: lying in XY plane at z = 0
        ring1 = np.stack([
            self.r1 * np.cos(theta),
            self.r1 * np.sin(theta),
            np.zeros_like(theta)
        ], axis=-1)
        
        # Ring 2: oriented in YZ plane, offset by ring2_offset
        ring2 = np.stack([
            np.zeros_like(theta),
            self.r2 * np.cos(theta),
            self.r2 * np.sin(theta)
        ], axis=-1) + self.ring2_offset
        
        pts = np.concatenate([ring1, ring2], axis=0).astype(np.float32)
        noise = self.rng.normal(0.0, 0.005, size=pts.shape).astype(np.float32)
        return pts + noise

    def step(self, action):
        self.step_t += 1
        action = np.clip(np.array(action, dtype=np.float32), -0.25, 0.25)
        
        # Untangling canonical motion towards x > 0.85
        self.ring2_offset += action + np.array([0.08, 0.02, 0.03], dtype=np.float32)
        
        pts = self._generate_point_cloud()
        dgm0, dgm1 = compute_persistence_diagrams(pts)
        b0, b1 = extract_betti_numbers(dgm0, dgm1)
        
        is_untangled = bool(self.ring2_offset[0] > (self.r1 + self.r2 + 0.05))
        
        # False crossing: Ring 2 center penetrating through Ring 1 disk (z ~ 0, x < r1)
        false_crossing = bool(abs(self.ring2_offset[2]) < 0.08 and abs(self.ring2_offset[0]) < self.r1 * 0.9)
            
        done = (self.step_t >= self.max_steps) or is_untangled
        info = {
            "betti": (b0, b1),
            "is_untangled": is_untangled,
            "false_crossing": false_crossing,
            "dgm0": dgm0,
            "dgm1": dgm1
        }
        return pts, done, info


class TorusPinchOffPhysicsEnv:
    """
    Torus Pinch-off Topological Phase Transition Sandbox:
    Major radius R = 0.75. Minor radius r(t) decreases under surface tension.
    Sampled with 8 x 4 = 32 points.
    At critical neck step 7, minor radius r_neck -> 0.
    Topological transition: Betti number beta_1 drops from 2 (Torus) to 1 (Pinched loop).
    """
    def __init__(self, num_pts=32, seed=42):
        self.num_pts = num_pts
        self.rng = np.random.RandomState(seed)
        self.max_steps = 12
        self.R = 0.75
        self.r0 = 0.35
        self.reset()

    def reset(self, seed=None):
        if seed is not None:
            self.rng = np.random.RandomState(seed)
        self.t = 0
        return self._generate_point_cloud()

    def _generate_point_cloud(self):
        contract = min(1.0, self.t / 7.0)
        r_current = max(0.02, self.r0 * (1.0 - contract))
        
        u = np.linspace(0, 2*np.pi, 8, endpoint=False)
        v = np.linspace(0, 2*np.pi, 4, endpoint=False)
        U, V = np.meshgrid(u, v)
        U, V = U.flatten(), V.flatten()
        
        X = (self.R + r_current * np.cos(V)) * np.cos(U)
        Y = (self.R + r_current * np.cos(V)) * np.sin(U)
        Z = r_current * np.sin(V)
        
        pts = np.stack([X, Y, Z], axis=-1).astype(np.float32)
        noise = self.rng.normal(0.0, 0.005, size=pts.shape).astype(np.float32)
        return pts + noise

    def step(self):
        self.t += 1
        pts = self._generate_point_cloud()
        dgm0, dgm1 = compute_persistence_diagrams(pts)
        b0, b1 = extract_betti_numbers(dgm0, dgm1, persistence_threshold=0.10)
        
        is_pinched = (self.t >= 7)
        expected_b1 = 1 if is_pinched else 2
        
        done = (self.t >= self.max_steps)
        info = {
            "t": self.t,
            "betti": (b0, b1),
            "expected_b1": expected_b1,
            "is_pinched": is_pinched,
            "dgm0": dgm0,
            "dgm1": dgm1
        }
        return pts, done, info


# ==============================================================================
# 3. Model Architectures: Euclidean RSSM vs VAE vs TDA-WM
# ==============================================================================

class StandardEuclideanRSSM:
    """Standard Recurrent State Space Model with purely Euclidean L2 loss."""
    def __init__(self, point_dim=32*3, latent_dim=24, lr=3e-3):
        self.point_dim = point_dim
        self.latent_dim = latent_dim
        self.encoder = Sequential(Linear(point_dim, 64), LayerNorm(64), ReLU(), Linear(64, latent_dim), Tanh())
        self.dynamics = Sequential(Linear(latent_dim, 48), LayerNorm(48), ReLU(), Linear(48, latent_dim), Tanh())
        self.decoder = Sequential(Linear(latent_dim, 64), ReLU(), Linear(64, point_dim))
        
        params = self.encoder.parameters() + self.dynamics.parameters() + self.decoder.parameters()
        self.optimizer = Adam(params, lr=lr)

    def train_step(self, pts_t, pts_tp1):
        self.optimizer.zero_grad()
        B = pts_t.shape[0]
        x_t = pts_t.reshape(B, -1)
        x_tp1 = pts_tp1.reshape(B, -1)
        
        z_t = self.encoder.forward(x_t)
        z_pred_tp1 = self.dynamics.forward(z_t)
        x_rec_tp1 = self.decoder.forward(z_pred_tp1)
        
        loss, grad = mse_loss(x_rec_tp1, x_tp1)
        g_dec = self.decoder.backward(grad)
        g_dyn = self.dynamics.backward(g_dec)
        self.encoder.backward(g_dyn)
        
        self.optimizer.step()
        return float(loss)

    def predict_next(self, pts_t):
        x_t = pts_t.reshape(1, -1)
        z_t = self.encoder.forward(x_t)
        z_tp1 = self.dynamics.forward(z_t)
        x_rec = self.decoder.forward(z_tp1)
        return x_rec.reshape(pts_t.shape)


class StandardLatentVAE:
    """Standard Variational Autoencoder without topological loss."""
    def __init__(self, point_dim=32*3, latent_dim=24, lr=3e-3):
        self.point_dim = point_dim
        self.latent_dim = latent_dim
        self.encoder_mu = Sequential(Linear(point_dim, 64), LayerNorm(64), ReLU(), Linear(64, latent_dim))
        self.dynamics = Sequential(Linear(latent_dim, 48), LayerNorm(48), ReLU(), Linear(48, latent_dim), Tanh())
        self.decoder = Sequential(Linear(latent_dim, 64), ReLU(), Linear(64, point_dim))
        
        params = self.encoder_mu.parameters() + self.dynamics.parameters() + self.decoder.parameters()
        self.optimizer = Adam(params, lr=lr)

    def train_step(self, pts_t, pts_tp1):
        self.optimizer.zero_grad()
        B = pts_t.shape[0]
        x_t = pts_t.reshape(B, -1)
        x_tp1 = pts_tp1.reshape(B, -1)
        
        mu_t = self.encoder_mu.forward(x_t)
        z_tp1 = self.dynamics.forward(mu_t)
        x_rec_tp1 = self.decoder.forward(z_tp1)
        
        loss_rec, grad_rec = mse_loss(x_rec_tp1, x_tp1)
        g_dec = self.decoder.backward(grad_rec)
        g_dyn = self.dynamics.backward(g_dec)
        self.encoder_mu.backward(g_dyn)
        
        self.optimizer.step()
        return float(loss_rec)

    def predict_next(self, pts_t):
        x_t = pts_t.reshape(1, -1)
        mu_t = self.encoder_mu.forward(x_t)
        z_tp1 = self.dynamics.forward(mu_t)
        x_rec = self.decoder.forward(z_tp1)
        return x_rec.reshape(pts_t.shape)


class TDAWorldModel:
    """
    Topological Data Analysis World Model (TDA-WM, Ours):
    Augmented with persistent metric preservation and topological regularizer.
    Preserves simplicial complex connectivity and avoids topological collapse.
    """
    def __init__(self, point_dim=32*3, latent_dim=24, lr=3e-3, topo_weight=0.08):
        self.point_dim = point_dim
        self.latent_dim = latent_dim
        self.topo_weight = topo_weight
        
        self.encoder = Sequential(Linear(point_dim, 64), LayerNorm(64), ReLU(), Linear(64, latent_dim), Tanh())
        self.dynamics = Sequential(Linear(latent_dim, 48), LayerNorm(48), ReLU(), Linear(48, latent_dim), Tanh())
        self.decoder = Sequential(Linear(latent_dim, 64), ReLU(), Linear(64, point_dim))
        
        params = self.encoder.parameters() + self.dynamics.parameters() + self.decoder.parameters()
        self.optimizer = Adam(params, lr=lr)

    def train_step(self, pts_t, pts_tp1):
        self.optimizer.zero_grad()
        B = pts_t.shape[0]
        N_pts = pts_t.shape[1]
        x_t = pts_t.reshape(B, -1)
        x_tp1 = pts_tp1.reshape(B, -1)
        
        z_t = self.encoder.forward(x_t)
        z_pred_tp1 = self.dynamics.forward(z_t)
        x_rec_tp1 = self.decoder.forward(z_pred_tp1)
        
        # 1. Standard Geometric Reconstruction MSE
        loss_geom, grad_geom = mse_loss(x_rec_tp1, x_tp1)
        
        # 2. Topological Metric Preservation Loss & Gradient
        pts_pred_3d = x_rec_tp1.reshape(B, N_pts, 3)
        pts_true_3d = pts_tp1.reshape(B, N_pts, 3)
        
        diff_pred = pts_pred_3d[:, :, None, :] - pts_pred_3d[:, None, :, :]
        d_pred = np.sqrt(np.sum(diff_pred ** 2, axis=-1) + 1e-12)
        diff_true = pts_true_3d[:, :, None, :] - pts_true_3d[:, None, :, :]
        d_true = np.sqrt(np.sum(diff_true ** 2, axis=-1) + 1e-12)
        
        d_err = d_pred - d_true
        loss_topo = float(np.mean(d_err ** 2))
        
        unit_vec = diff_pred / (d_pred[:, :, :, None] + 1e-6)
        grad_topo = (4.0 / (N_pts * N_pts)) * np.sum(d_err[:, :, :, None] * unit_vec, axis=2)
        grad_topo_flat = (grad_topo.reshape(B, -1) / B).astype(np.float32)
        
        total_loss = loss_geom + self.topo_weight * loss_topo
        grad_total = grad_geom + self.topo_weight * grad_topo_flat
        
        g_dec = self.decoder.backward(grad_total)
        g_dyn = self.dynamics.backward(g_dec)
        self.encoder.backward(g_dyn)
        
        self.optimizer.step()
        return float(total_loss)

    def predict_next(self, pts_t):
        x_t = pts_t.reshape(1, -1)
        z_t = self.encoder.forward(x_t)
        z_tp1 = self.dynamics.forward(z_t)
        x_rec = self.decoder.forward(z_tp1)
        return x_rec.reshape(pts_t.shape)


# ==============================================================================
# 4. Phase 7 Benchmark Execution Pipeline
# ==============================================================================

def run_topological_benchmark():
    print("================================================================================")
    print("STARTING PHASE 7: TOPOLOGICAL HOMOLOGY & PERSISTENT WORLD MODELS BENCHMARK")
    print("================================================================================")
    
    seed = 42
    np.random.seed(seed)
    
    # 1. Environment Initialization
    ring_env = LinkedRingsPhysicsEnv(num_points_per_ring=16, seed=seed)
    torus_env = TorusPinchOffPhysicsEnv(num_pts=32, seed=seed)
    
    point_dim = 32 * 3 # 96
    
    # 2. Collect Training Dataset of Topological Transitions
    print("\n1. Collecting topological transition trajectories...")
    train_data = []
    # Collect Linked Rings trajectories
    for ep in range(30):
        pts = ring_env.reset(seed=ep * 10 + 1)
        for _ in range(ring_env.max_steps):
            act = ring_env.rng.uniform(-0.08, 0.08, size=3).astype(np.float32)
            n_pts, d, _ = ring_env.step(act)
            train_data.append((pts, n_pts))
            if d: break
            pts = n_pts
            
    # Collect Torus Pinch-Off trajectories
    for ep in range(30):
        pts = torus_env.reset(seed=ep * 10 + 7)
        for _ in range(torus_env.max_steps):
            n_pts, d, _ = torus_env.step()
            train_data.append((pts, n_pts))
            if d: break
            pts = n_pts
            
    pts_t_arr = np.array([x[0] for x in train_data], dtype=np.float32)
    pts_tp1_arr = np.array([x[1] for x in train_data], dtype=np.float32)
    N = len(pts_t_arr)
    print(f"   Collected {N} topological transition pairs.")
    
    # 3. Model Training
    print("\n2. Training Models: Euclidean RSSM, Latent VAE, and Topological TDA-WM...")
    rssm = StandardEuclideanRSSM(point_dim=point_dim, latent_dim=24, lr=3e-3)
    vae = StandardLatentVAE(point_dim=point_dim, latent_dim=24, lr=3e-3)
    tda_wm = TDAWorldModel(point_dim=point_dim, latent_dim=24, lr=3e-3, topo_weight=0.08)
    
    t0 = time.time()
    for ep in range(45):
        perm = np.random.permutation(N)
        for s in range(N // 32):
            idx = perm[s * 32:(s + 1) * 32]
            rssm.train_step(pts_t_arr[idx], pts_tp1_arr[idx])
            vae.train_step(pts_t_arr[idx], pts_tp1_arr[idx])
            tda_wm.train_step(pts_t_arr[idx], pts_tp1_arr[idx])
    train_sec = time.time() - t0
    print(f"   Model training completed in {train_sec:.2f} seconds.")

    # 4. Closed-Loop Topological Evaluations
    print("\n3. Running Closed-Loop Topological Homology Evaluations...")
    eval_episodes = 15
    
    metrics = {
        "Linked_Rings_Untangling": {
            "Euclidean_RSSM": {"bottleneck_d": [], "betti_acc": [], "false_crossing": [], "mse": []},
            "Latent_VAE":     {"bottleneck_d": [], "betti_acc": [], "false_crossing": [], "mse": []},
            "TDA_WM":         {"bottleneck_d": [], "betti_acc": [], "false_crossing": [], "mse": []}
        },
        "Torus_PinchOff_Transition": {
            "Euclidean_RSSM": {"bottleneck_d": [], "betti_acc": [], "mse": []},
            "Latent_VAE":     {"bottleneck_d": [], "betti_acc": [], "mse": []},
            "TDA_WM":         {"bottleneck_d": [], "betti_acc": [], "mse": []}
        }
    }
    
    # --- Task A: Linked Rings Untangling ---
    print("  -> Evaluating Task A: Dynamic Hopf Link Untangling...")
    for ep in range(eval_episodes):
        pts = ring_env.reset(seed=ep * 100 + 42)
        cur_pts = {"Euclidean_RSSM": pts.copy(), "Latent_VAE": pts.copy(), "TDA_WM": pts.copy()}
        
        for step_i in range(ring_env.max_steps):
            act = ring_env.rng.uniform(-0.05, 0.05, size=3).astype(np.float32)
            true_next_pts, done, info = ring_env.step(act)
            true_dgm0, true_dgm1 = info["dgm0"], info["dgm1"]
            true_b0, true_b1 = info["betti"]
            
            for m_name, model in [("Euclidean_RSSM", rssm), ("Latent_VAE", vae), ("TDA_WM", tda_wm)]:
                pred_next = model.predict_next(cur_pts[m_name])
                cur_pts[m_name] = pred_next
                
                # Topological persistent homology on predicted manifold
                pred_dgm0, pred_dgm1 = compute_persistence_diagrams(pred_next)
                pred_b0, pred_b1 = extract_betti_numbers(pred_dgm0, pred_dgm1)
                
                # Metrics
                d_B = bottleneck_distance(true_dgm1, pred_dgm1)
                betti_match = float(pred_b0 == true_b0 and pred_b1 == true_b1)
                mse_geom = float(np.mean((pred_next - true_next_pts) ** 2))
                
                # Check false crossing penetration in prediction
                r2_pts = pred_next[ring_env.num_pts:]
                r2_center = np.mean(r2_pts, axis=0)
                false_cross = bool(abs(r2_center[2]) < 0.08 and abs(r2_center[0]) < ring_env.r1 * 0.9)
                
                metrics["Linked_Rings_Untangling"][m_name]["bottleneck_d"].append(d_B)
                metrics["Linked_Rings_Untangling"][m_name]["betti_acc"].append(betti_match)
                metrics["Linked_Rings_Untangling"][m_name]["false_crossing"].append(float(false_cross))
                metrics["Linked_Rings_Untangling"][m_name]["mse"].append(mse_geom)
                
            if done: break
            
    # --- Task B: Torus Pinch-Off Topological Phase Transition ---
    print("  -> Evaluating Task B: Torus Capillary Pinch-Off Phase Transition...")
    for ep in range(eval_episodes):
        pts = torus_env.reset(seed=ep * 100 + 99)
        cur_pts = {"Euclidean_RSSM": pts.copy(), "Latent_VAE": pts.copy(), "TDA_WM": pts.copy()}
        
        for step_i in range(torus_env.max_steps):
            true_next_pts, done, info = torus_env.step()
            true_dgm0, true_dgm1 = info["dgm0"], info["dgm1"]
            exp_b1 = info["expected_b1"]
            
            for m_name, model in [("Euclidean_RSSM", rssm), ("Latent_VAE", vae), ("TDA_WM", tda_wm)]:
                pred_next = model.predict_next(cur_pts[m_name])
                cur_pts[m_name] = pred_next
                
                pred_dgm0, pred_dgm1 = compute_persistence_diagrams(pred_next)
                pred_b0, pred_b1 = extract_betti_numbers(pred_dgm0, pred_dgm1, persistence_threshold=0.10)
                
                d_B = bottleneck_distance(true_dgm1, pred_dgm1)
                betti_match = float(pred_b1 == exp_b1)
                mse_geom = float(np.mean((pred_next - true_next_pts) ** 2))
                
                metrics["Torus_PinchOff_Transition"][m_name]["bottleneck_d"].append(d_B)
                metrics["Torus_PinchOff_Transition"][m_name]["betti_acc"].append(betti_match)
                metrics["Torus_PinchOff_Transition"][m_name]["mse"].append(mse_geom)
                
            if done: break

    # 5. Aggregate Metrics and Summary
    summary = {}
    print("\n================================================================================")
    print("PHASE 7 TOPOLOGICAL EVALUATION SUMMARY REPORT")
    print("================================================================================")
    
    for task_name in ["Linked_Rings_Untangling", "Torus_PinchOff_Transition"]:
        summary[task_name] = {}
        print(f"\n[{task_name}]")
        print(f"{'Model Architecture':20s} | {'Bottleneck d_B':16s} | {'Betti Acc (%)':16s} | {'False Cross (%)':16s} | {'Geom MSE':12s}")
        print("-" * 88)
        
        for m_name in ["Euclidean_RSSM", "Latent_VAE", "TDA_WM"]:
            d_b = float(np.mean(metrics[task_name][m_name]["bottleneck_d"]))
            b_acc = float(np.mean(metrics[task_name][m_name]["betti_acc"]) * 100.0)
            fc = float(np.mean(metrics[task_name][m_name].get("false_crossing", [0.0])) * 100.0)
            mse_val = float(np.mean(metrics[task_name][m_name]["mse"]))
            
            summary[task_name][m_name] = {
                "bottleneck_distance": d_b,
                "betti_accuracy_pct": b_acc,
                "false_crossing_rate_pct": fc,
                "geometric_mse": mse_val
            }
            fc_str = f"{fc:14.1f}%" if "false_crossing" in metrics[task_name][m_name] else "N/A"
            print(f"{m_name:20s} | {d_b:16.4f} | {b_acc:14.1f}% | {fc_str:16s} | {mse_val:12.4f}")

    # Save Metrics JSON
    json_path = os.path.join(curr_dir, "topological_metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nMetrics written to: {json_path}")
    
    # 6. Generate 300 DPI Publication Visualizations
    generate_topological_charts(summary)


def generate_topological_charts(summary):
    """Generates 300 DPI publication figure for Topological Homology World Models Benchmark."""
    plt.style.use('default')
    plt.rcParams['font.family'] = 'DejaVu Sans'
    
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), dpi=300)
    fig.suptitle("Topological Homology & Persistent Latent World Models Benchmark",
                 fontsize=13, fontweight='bold', y=0.98)
                 
    models = ["Euclidean RSSM", "Latent VAE", "TDA-WM (Ours)"]
    m_keys = ["Euclidean_RSSM", "Latent_VAE", "TDA_WM"]
    colors = ['#E63946', '#F4A261', '#2A9D8F']
    
    # Panel A: Persistent Homology Bottleneck Distance (Lower is Better)
    ax1 = axes[0]
    task_a = "Linked_Rings_Untangling"
    db_vals = [summary[task_a][k]["bottleneck_distance"] for k in m_keys]
    bars1 = ax1.bar(models, db_vals, color=colors, width=0.52, alpha=0.9)
    ax1.set_ylabel("Bottleneck Distance d_B (Lower is Better)", fontsize=10, fontweight='bold')
    ax1.set_title("A. Persistent Diagram Distance (Linked Rings)", fontsize=11, fontweight='bold', pad=8)
    ax1.grid(axis='y', linestyle='--', alpha=0.5)
    for b in bars1:
        h = b.get_height()
        ax1.annotate(f"{h:.3f}", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                     textcoords="offset points", ha='center', va='bottom', fontsize=9, fontweight='bold')
                     
    # Panel B: Betti Number Identification Accuracy (%)
    ax2 = axes[1]
    betti_a = [summary[task_a][k]["betti_accuracy_pct"] for k in m_keys]
    bars2 = ax2.bar(models, betti_a, color=colors, width=0.52, alpha=0.9)
    ax2.set_ylabel("Betti Number Accuracy (%)", fontsize=10, fontweight='bold')
    ax2.set_title("B. Betti Number Accuracy beta_0, beta_1 (Higher is Better)", fontsize=11, fontweight='bold', pad=8)
    ax2.set_ylim(0, 105)
    ax2.grid(axis='y', linestyle='--', alpha=0.5)
    for b in bars2:
        h = b.get_height()
        ax2.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                     textcoords="offset points", ha='center', va='bottom', fontsize=9, fontweight='bold')
                     
    # Panel C: Topological False Crossing Rate in Untangling (%)
    ax3 = axes[2]
    fc_vals = [summary[task_a][k]["false_crossing_rate_pct"] for k in m_keys]
    bars3 = ax3.bar(models, fc_vals, color=colors, width=0.52, alpha=0.9)
    ax3.set_ylabel("False Crossing Rate (%) (Lower is Better)", fontsize=10, fontweight='bold')
    ax3.set_title("C. Unphysical Ring Penetration Rate", fontsize=11, fontweight='bold', pad=8)
    ax3.set_ylim(0, 105)
    ax3.grid(axis='y', linestyle='--', alpha=0.5)
    for b in bars3:
        h = b.get_height()
        ax3.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                     textcoords="offset points", ha='center', va='bottom', fontsize=9, fontweight='bold')
                     
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    eval_path = os.path.join(curr_dir, "topological_homology_eval.png")
    plt.savefig(eval_path, dpi=300)
    plt.close()
    print(f"Saved: {eval_path}")


if __name__ == "__main__":
    run_topological_benchmark()
