"""
Optimal Transport Wasserstein World Models (OTW-WM)
===================================================================================
Phase 14 Cutting-Edge Benchmark:
Comparing Euclidean Linear Interpolation (Teleportation) vs KL Gradient Flow vs
2-Wasserstein Optimal Transport World Models (OTW-WM) under
Benamou-Brenier Fluid Dynamics, McCann Displacement Interpolation,
Monge-Kantorovich Couplings, and Otto-Wasserstein Information Geometry.

Mathematical Foundations:
- Benamou-Brenier Dynamic Formulation:
    W_2^2(\\rho_0, \\rho_1) = \\inf_{(\\rho, v)} \\int_0^1 dt \\int_{\\mathbb{R}^d} \\rho_t(x) ||v_t(x)||^2 dx
    subject to \\partial_t \\rho + \\nabla \\cdot (\\rho v) = 0.
- McCann Displacement Geodesic Interpolation:
    T_t(x) = (1 - t)x + t T(x), \\quad \\rho_t = (T_t)_\\# \\rho_0.
- Brenier's Theorem:
    T(x) = \\nabla \\psi(x), where \\psi: \\mathbb{R}^d \\to \\mathbb{R} is strictly convex.
- Otto Infinite-Dimensional Riemannian Manifold & Wasserstein Gradient Flow:
    \\partial_t \\rho = \\nabla \\cdot (\\rho \\nabla \\frac{\\delta \\mathcal{F}}{\\delta \\rho}) = - \\text{grad}_{W_2} \\mathcal{F}(\\rho).
- Bakry-Émery Ricci Curvature Criterion & Relative Fisher Information Dissipation:
    - d/dt \\mathcal{F}(\\rho_t) = - \\mathcal{I}_F(\\rho_t || \\rho_\\infty) \\leq 0.
- Theorem 60: Benamou-Brenier Optimal Transport Geodesic Convexity &
  Fisher Information Convergence Theorem in 2-Wasserstein Space.

Author: Agent 2 (Discrete Dynamics & RSSM Ablations Engineer)
Date: October 2026
"""

import os
import json
import time
import numpy as np
import matplotlib.pyplot as plt

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 1. Optimal Transport & Geodesic Dynamics Engine
# ---------------------------------------------------------------------------

class OptimalTransportEngine:
    """
    Implements 1D Monge-Kantorovich Optimal Transport via Quantile Functions,
    McCann Displacement Geodesic Interpolation, and Benamou-Brenier Fluid Action.
    """
    def __init__(self, x_grid, rho0, rho1, num_quantiles=5000):
        self.x = x_grid
        self.dx = x_grid[1] - x_grid[0]
        self.num_quantiles = num_quantiles
        
        # Normalize probability densities
        self.rho0 = rho0 / np.sum(rho0 * self.dx)
        self.rho1 = rho1 / np.sum(rho1 * self.dx)
        
        # Cumulative distribution functions
        self.F0 = np.clip(np.cumsum(self.rho0 * self.dx), 0.0, 1.0)
        self.F1 = np.clip(np.cumsum(self.rho1 * self.dx), 0.0, 1.0)
        
        # Quantile coordinate grid u in (0, 1)
        self.u = np.linspace(1e-6, 1.0 - 1e-6, self.num_quantiles)
        self.du = self.u[1] - self.u[0]
        
        # Inverse CDFs (Quantile representations)
        self.X0_u = np.interp(self.u, self.F0, self.x)
        self.X1_u = np.interp(self.u, self.F1, self.x)
        
        # Exact 2-Wasserstein Distance Squared: W_2^2 = \\int_0^1 |X_1(u) - X_0(u)|^2 du
        self.W2_sq = float(np.sum((self.X1_u - self.X0_u)**2 * self.du))
        self.W2 = float(np.sqrt(self.W2_sq))
        
        # Monge Map T(x) = F1^{-1}(F0(x)) evaluated on original grid x
        inv_F1_u = np.interp(self.F0, self.u, self.X1_u)
        self.T_x = inv_F1_u
        
        # Brenier convex potential psi(x) such that T(x) = d psi / dx
        # psi(x) = \\int_{x_0}^x T(y) dy
        self.psi_x = np.cumsum(self.T_x * self.dx)
        self.psi_x -= self.psi_x[0]

    def mccann_interpolation(self, t):
        """
        Computes the McCann displacement interpolation density rho_t and CDF F_t at time t in [0, 1].
        Xt(u) = (1 - t) X0(u) + t X1(u).
        """
        t = np.clip(t, 0.0, 1.0)
        Xt_u = (1.0 - t) * self.X0_u + t * self.X1_u
        
        # Reconstruct CDF F_t on evaluation grid x
        Ft = np.interp(self.x, Xt_u, self.u, left=0.0, right=1.0)
        
        # Density rho_t = dF_t / dx
        rhot = np.gradient(Ft, self.dx)
        rhot = np.clip(rhot, 0.0, None)
        mass = np.sum(rhot * self.dx)
        if mass > 1e-12:
            rhot /= mass
            
        return rhot, Ft, Xt_u

    def ot_velocity_and_kinetic_energy(self, t):
        """
        Under Benamou-Brenier optimal transport, particles move with constant velocity
        v_t(Xt(u)) = X1(u) - X0(u) along McCann geodesics.
        Thus instantaneous kinetic energy K_OT(t) == W_2^2 for all t in [0, 1].
        """
        # Kinetic energy is identically W_2^2
        return self.W2_sq


# ---------------------------------------------------------------------------
# 2. Euclidean Linear Interpolation (Teleportation Baseline)
# ---------------------------------------------------------------------------

class EuclideanTeleportationEngine:
    """
    Computes Euclidean linear interpolation rho_t^{Euc}(x) = (1 - t) rho_0(x) + t rho_1(x)
    and reconstructs the apparent fluid velocity field v_t^{Euc}(x) via the continuity equation:
        \\partial_t rho_t + \\partial_x (rho_t v_t) = 0
        \\implies rho_1 - rho_0 = - \\partial_x (rho_t v_t)
        \\implies J_t(x) = rho_t v_t = F_0(x) - F_1(x)
        \\implies v_t^{Euc}(x) = (F_0(x) - F_1(x)) / rho_t^{Euc}(x).
    """
    def __init__(self, x_grid, rho0, rho1):
        self.x = x_grid
        self.dx = x_grid[1] - x_grid[0]
        self.rho0 = rho0 / np.sum(rho0 * self.dx)
        self.rho1 = rho1 / np.sum(rho1 * self.dx)
        self.F0 = np.clip(np.cumsum(self.rho0 * self.dx), 0.0, 1.0)
        self.F1 = np.clip(np.cumsum(self.rho1 * self.dx), 0.0, 1.0)
        self.J_flux = self.F0 - self.F1

    def density(self, t):
        """Euclidean mixture density rho_t = (1 - t) rho0 + t rho1."""
        t = np.clip(t, 0.0, 1.0)
        return (1.0 - t) * self.rho0 + t * self.rho1

    def velocity(self, t, eps=1e-10):
        """Continuity apparent velocity field v_t(x) = J(x) / rho_t(x)."""
        rhot = self.density(t)
        return self.J_flux / (rhot + eps)

    def kinetic_energy(self, t, eps=1e-10):
        """
        Instantaneous kinetic energy action under Euclidean continuity:
        K_Euc(t) = \\int rho_t(x) |v_t(x)|^2 dx = \\int J(x)^2 / (rho_t(x) + eps) dx.
        """
        rhot = self.density(t)
        return float(np.sum((self.J_flux**2) / (rhot + eps) * self.dx))


# ---------------------------------------------------------------------------
# 3. Otto-Wasserstein Gradient Flow & Fisher Information Convergence
# ---------------------------------------------------------------------------

class WassersteinGradientFlowEngine:
    """
    Simulates the Wasserstein gradient flow of free energy on a quadratic potential V(x) = 1/2 kappa x^2:
        \\partial_s rho = \\partial_x (rho \\partial_x V) + beta^{-1} \\partial_{xx} rho
                        = \\partial_x (rho \\partial_x (V + beta^{-1} ln rho))
    Demonstrates:
    - Dissipation identity: - d/ds F(rho_s) = I_F(rho_s || rho_infty)
    - Exponential convergence: I_F(rho_s) <= I_F(rho_0) exp(- 2 kappa s)
    """
    def __init__(self, x_grid, kappa=1.0, beta=1.0):
        self.x = x_grid
        self.dx = x_grid[1] - x_grid[0]
        self.kappa = kappa
        self.beta = beta
        self.V = 0.5 * kappa * (self.x**2)
        self.dV = kappa * self.x
        
        # Gibbs equilibrium distribution rho_infty(x)
        self.rho_inf = np.sqrt(beta * kappa / (2.0 * np.pi)) * np.exp(-0.5 * beta * kappa * (self.x**2))
        self.rho_inf /= np.sum(self.rho_inf * self.dx)

    def free_energy(self, rho, eps=1e-15):
        """
        Relative Free Energy (scaled KL divergence):
        \\Delta F(rho) = (1 / beta) * \\int rho(x) ln(rho(x) / rho_infty(x)) dx.
        """
        p_safe = np.clip(rho, eps, None)
        inf_safe = np.clip(self.rho_inf, eps, None)
        return float((1.0 / self.beta) * np.sum(p_safe * np.log(p_safe / inf_safe) * self.dx))

    def fisher_information(self, rho, eps=1e-15):
        """
        Relative Fisher Information (Wasserstein gradient norm squared):
        I_F(rho) = \\int rho |\\partial_x (V + beta^{-1} ln rho)|^2 dx
                 = \\int rho (dV + beta^{-1} (d rho / dx) / rho)^2 dx.
        """
        p_safe = np.clip(rho, eps, None)
        drho = np.gradient(p_safe, self.dx)
        drift_plus_diff = self.dV + (1.0 / self.beta) * (drho / p_safe)
        return float(np.sum(p_safe * (drift_plus_diff**2) * self.dx))

    def run_flow(self, rho_init, total_time=1.5, dt=0.0001, record_steps=60):
        """
        Simulates the Fokker-Planck Wasserstein gradient flow via conservative flux differencing.
        """
        num_steps = int(total_time / dt)
        stride = max(1, num_steps // record_steps)
        
        rho = rho_init.copy() / np.sum(rho_init * self.dx)
        
        s_history = []
        F_history = []
        I_history = []
        profiles = []
        
        for step in range(num_steps + 1):
            s = step * dt
            if step % stride == 0 or step == num_steps:
                F_val = self.free_energy(rho)
                I_val = self.fisher_information(rho)
                s_history.append(s)
                F_history.append(F_val)
                I_history.append(I_val)
                profiles.append((s, rho.copy()))
                
            if step < num_steps:
                # Conservative flux: J = - rho * dV - (1/beta) * d rho / dx
                drho = np.gradient(rho, self.dx)
                J = - rho * self.dV - (1.0 / self.beta) * drho
                # Zero boundary flux
                J[0] = 0.0
                J[-1] = 0.0
                
                # Evolution: d rho / dt = - dJ / dx
                dJ = np.gradient(J, self.dx)
                rho = rho - dt * dJ
                rho = np.clip(rho, 0.0, None)
                mass = np.sum(rho * self.dx)
                if mass > 1e-12:
                    rho /= mass

        return {
            "time": np.array(s_history),
            "free_energy": np.array(F_history),
            "fisher_info": np.array(I_history),
            "profiles": profiles
        }


# ---------------------------------------------------------------------------
# 4. Benchmark Execution & Metrics Extraction
# ---------------------------------------------------------------------------

def run_optimal_transport_benchmark():
    print("=====================================================================")
    print("Phase 14: Optimal Transport Wasserstein World Models (OTW-WM) Benchmark")
    print("=====================================================================")
    start_time = time.time()
    
    # 1. Define spatial grids and multi-modal distributions
    x_fine = np.linspace(-12.0, 12.0, 8000)
    dx_fine = x_fine[1] - x_fine[0]
    
    # Source distribution rho0: asymmetric bimodal at x = -4.5 and x = -1.5
    rho0_fine = (0.55 * np.exp(-0.5 * ((x_fine + 4.5) / 0.75)**2) / (np.sqrt(2 * np.pi) * 0.75) +
                 0.45 * np.exp(-0.5 * ((x_fine + 1.5) / 0.85)**2) / (np.sqrt(2 * np.pi) * 0.85))
    rho0_fine /= np.sum(rho0_fine * dx_fine)
    
    # Target distribution rho1: asymmetric bimodal at x = +1.5 and x = +4.5
    rho1_fine = (0.40 * np.exp(-0.5 * ((x_fine - 1.5) / 0.70)**2) / (np.sqrt(2 * np.pi) * 0.70) +
                 0.60 * np.exp(-0.5 * ((x_fine - 4.5) / 0.90)**2) / (np.sqrt(2 * np.pi) * 0.90))
    rho1_fine /= np.sum(rho1_fine * dx_fine)
    
    # Initialize OT and Euclidean engines
    ot_engine = OptimalTransportEngine(x_fine, rho0_fine, rho1_fine, num_quantiles=6000)
    euc_engine = EuclideanTeleportationEngine(x_fine, rho0_fine, rho1_fine)
    
    W2_sq = ot_engine.W2_sq
    W2_dist = ot_engine.W2
    print(f"[1] 2-Wasserstein Distance: W_2 = {W2_dist:.4f}, W_2^2 = {W2_sq:.4f}")
    
    # 2. Kinetic Energy & Action Comparison across t in [0.01, 0.99]
    t_eval = np.linspace(0.01, 0.99, 100)
    K_ot_vals = []
    K_euc_vals = []
    
    for t in t_eval:
        K_ot = ot_engine.ot_velocity_and_kinetic_energy(t)
        K_euc = euc_engine.kinetic_energy(t)
        K_ot_vals.append(K_ot)
        K_euc_vals.append(K_euc)
        
    K_ot_arr = np.array(K_ot_vals)
    K_euc_arr = np.array(K_euc_vals)
    
    action_ot = float(np.mean(K_ot_arr))
    action_euc = float(np.mean(K_euc_arr))
    peak_ratio = float(np.max(K_euc_arr) / W2_sq)
    action_reduction_pct = float((action_euc - action_ot) / action_euc * 100.0)
    
    print(f"[2] Action Comparison:")
    print(f"    Benamou-Brenier Action (OTW-WM): {action_ot:.4f}")
    print(f"    Euclidean Teleportation Action : {action_euc:.4f}")
    print(f"    Action Reduction by OTW-WM     : {action_reduction_pct:.2f}%")
    print(f"    Peak Kinetic Energy Ratio      : {peak_ratio:.2f}x (Euclidean / OT at t=0.5)")
    
    # 3. Density Profiles at Interpolation Slices t = 0.0, 0.25, 0.5, 0.75, 1.0
    slices_t = [0.0, 0.25, 0.5, 0.75, 1.0]
    densities_ot = {}
    densities_euc = {}
    
    for t in slices_t:
        r_ot, _, _ = ot_engine.mccann_interpolation(t)
        r_euc = euc_engine.density(t)
        densities_ot[t] = r_ot
        densities_euc[t] = r_euc
        
    # 4. Otto-Wasserstein Gradient Flow & Fisher Information Dissipation
    print(f"[3] Simulating Otto-Wasserstein Gradient Flow under Harmonic Well...")
    x_flow = np.linspace(-6.0, 6.0, 1500)
    dx_flow = x_flow[1] - x_flow[0]
    kappa = 1.0
    beta = 1.0
    flow_engine = WassersteinGradientFlowEngine(x_flow, kappa=kappa, beta=beta)
    
    # Non-equilibrium initial density: shifted double-peak
    rho_init_flow = (0.60 * np.exp(-0.5 * ((x_flow + 2.5) / 0.65)**2) +
                     0.40 * np.exp(-0.5 * ((x_flow - 1.2) / 0.75)**2))
    rho_init_flow /= np.sum(rho_init_flow * dx_flow)
    
    flow_res = flow_engine.run_flow(rho_init_flow, total_time=1.5, dt=0.0001, record_steps=80)
    s_arr = flow_res["time"]
    F_arr = flow_res["free_energy"]
    I_arr = flow_res["fisher_info"]
    
    # Compute numerical time-derivative of free energy: dF / ds
    ds = s_arr[1] - s_arr[0]
    dF_ds = np.gradient(F_arr, ds)
    dissipation_residual = np.abs(dF_ds + I_arr) / (np.abs(I_arr) + 1e-8)
    median_dissipation_residual = float(np.median(dissipation_residual))
    
    # Bakry-Émery exponential decay bound: I_F(s) <= I_F(0) * exp(- 2 * kappa * s)
    I_0 = I_arr[0]
    theoretical_decay_bound = I_0 * np.exp(- 2.0 * kappa * s_arr)
    be_violations = int(np.sum(I_arr > theoretical_decay_bound * 1.02))
    
    print(f"    Relative Dissipation Residual |-dF/ds - I_F| / I_F: {median_dissipation_residual:.4e}")
    print(f"    Bakry-Emery Decay Invariant Violations: {be_violations} / {len(s_arr)}")
    print(f"    Initial Fisher Info: {I_0:.4f}, Final: {I_arr[-1]:.4e}")

    # 5. Compile Metrics JSON
    metrics = {
        "W2_distance": W2_dist,
        "W2_squared": W2_sq,
        "action_benamou_brenier_ot": action_ot,
        "action_euclidean_teleportation": action_euc,
        "action_reduction_percentage": action_reduction_pct,
        "peak_kinetic_energy_ratio_euc_vs_ot": peak_ratio,
        "median_dissipation_identity_residual": median_dissipation_residual,
        "bakry_emery_decay_violations": be_violations,
        "initial_fisher_information": float(I_0),
        "final_fisher_information": float(I_arr[-1]),
        "brenier_convexity_verified": bool(np.all(np.diff(ot_engine.T_x) >= -1e-6)),
        "execution_time_sec": float(time.time() - start_time)
    }
    
    metrics_path = os.path.join(OUTPUT_DIR, "optimal_transport_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=4)
    print(f"[4] Saved metrics to {metrics_path}")

    # 6. Generate Publication-Quality 300 DPI Evaluation Figure
    print(f"[5] Rendering 300 DPI Publication Figure: optimal_transport_eval.png...")
    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 11,
        "axes.labelsize": 12,
        "axes.titlesize": 13,
        "legend.fontsize": 10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "figure.titlesize": 14,
        "text.usetex": False
    })
    
    fig, axs = plt.subplots(2, 2, figsize=(14, 11), dpi=300)
    
    # ----------------------------------------------------
    # Subplot (a): Geodesic Density Evolution: OTW-WM vs Euclidean
    # ----------------------------------------------------
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
    x_plot = x_fine
    mask = (x_plot >= -8.0) & (x_plot <= 8.0)
    
    for idx, t in enumerate(slices_t):
        axs[0, 0].plot(x_plot[mask], densities_ot[t][mask], color=colors[idx], lw=2.2,
                       label=f"OTW-WM (t={t:.2f})")
        axs[0, 0].plot(x_plot[mask], densities_euc[t][mask], color=colors[idx], lw=1.2,
                       linestyle="--", alpha=0.7)
        
    axs[0, 0].plot([], [], color="gray", lw=2.0, label="OTW-WM (McCann Geodesic)")
    axs[0, 0].plot([], [], color="gray", lw=1.2, linestyle="--", label="Euclidean (Teleportation)")
    axs[0, 0].set_title(r"(a) Latent Measure Evolution: McCann Geodesic vs Euclidean", pad=10)
    axs[0, 0].set_xlabel(r"Latent Coordinate $x$")
    axs[0, 0].set_ylabel(r"Probability Density $\rho_t(x)$")
    axs[0, 0].grid(True, linestyle=":", alpha=0.6)
    axs[0, 0].legend(loc="upper right", framealpha=0.9, fontsize=9)
    axs[0, 0].set_xlim(-7.5, 7.5)
    
    # ----------------------------------------------------
    # Subplot (b): Benamou-Brenier Instantaneous Kinetic Energy
    # ----------------------------------------------------
    axs[0, 1].plot(t_eval, K_ot_arr, color="#1f77b4", lw=2.5,
                   label=r"OTW-WM Kinetic $\mathcal{K}_{\mathrm{OT}}(t) \equiv W_2^2$")
    axs[0, 1].plot(t_eval, K_euc_arr, color="#d62728", lw=2.5, linestyle="-",
                   label=r"Euclidean Continuity Kinetic $\mathcal{K}_{\mathrm{Euc}}(t)$")
    axs[0, 1].axhline(W2_sq, color="#1f77b4", linestyle=":", alpha=0.7, label=r"$W_2^2$ Distance Bound")
    
    axs[0, 1].annotate(f"Peak Divergence: {peak_ratio:.1f}x\n(Mass Teleportation)",
                       xy=(0.5, np.max(K_euc_arr)), xytext=(0.25, np.max(K_euc_arr)*0.75),
                       arrowprops=dict(facecolor="#d62728", shrink=0.08, width=1.5, headwidth=8),
                       fontweight="bold", color="#d62728",
                       bbox=dict(boxstyle="round,pad=0.3", fc="#ffebee", ec="#d62728", lw=1))
    
    axs[0, 1].set_title(r"(b) Benamou-Brenier Kinetic Energy & Action Minimization", pad=10)
    axs[0, 1].set_xlabel(r"Interpolation Time $t \in [0, 1]$")
    axs[0, 1].set_ylabel(r"Instantaneous Kinetic Energy $\mathcal{K}(t)$")
    axs[0, 1].grid(True, linestyle=":", alpha=0.6)
    axs[0, 1].legend(loc="upper left", framealpha=0.9, fontsize=9.5)
    axs[0, 1].set_ylim(0, np.max(K_euc_arr) * 1.15)
    
    # ----------------------------------------------------
    # Subplot (c): Monge Optimal Transport Map & Displacement
    # ----------------------------------------------------
    mask_c = (x_plot >= -6.0) & (x_plot <= 3.0)
    axs[1, 0].plot(x_plot[mask_c], ot_engine.T_x[mask_c], color="#2ca02c", lw=2.5,
                   label=r"Monge Optimal Transport Map $T(x) = \nabla \psi(x)$")
    axs[1, 0].plot(x_plot[mask_c], x_plot[mask_c], color="black", linestyle="--", lw=1.5, alpha=0.7,
                   label=r"Identity Map $\mathrm{Id}(x) = x$")
    axs[1, 0].plot(x_plot[mask_c], ot_engine.T_x[mask_c] - x_plot[mask_c], color="#ff7f0e", linestyle="-.", lw=2.0,
                   label=r"Displacement Field $v(x) = T(x) - x$")
    
    axs[1, 0].set_title(r"(c) Monge Map Monotonicity & Brenier Gradient Field", pad=10)
    axs[1, 0].set_xlabel(r"Source Coordinate $x$")
    axs[1, 0].set_ylabel(r"Target Coordinate $T(x)$ / Displacement $v(x)$")
    axs[1, 0].grid(True, linestyle=":", alpha=0.6)
    axs[1, 0].legend(loc="upper left", framealpha=0.9, fontsize=9.5)
    
    # ----------------------------------------------------
    # Subplot (d): Otto-Wasserstein Gradient Flow & Fisher Info Convergence
    # ----------------------------------------------------
    axs[1, 1].semilogy(s_arr, F_arr, color="#9467bd", lw=2.5,
                       label=r"Relative Free Energy $\Delta \mathcal{F}(\rho_s)$")
    axs[1, 1].semilogy(s_arr, I_arr, color="#1f77b4", lw=2.5,
                       label=r"Relative Fisher Info $\mathcal{I}_F(\rho_s \parallel \rho_\infty)$")
    axs[1, 1].semilogy(s_arr, theoretical_decay_bound, color="#e377c2", linestyle="--", lw=2.0,
                       label=r"Bakry-Émery Bound $\mathcal{I}_0 e^{-2\kappa s}$")
    
    axs[1, 1].annotate(r"$\frac{d\mathcal{F}}{ds} = -\mathcal{I}_F$ (Exact Identity)" + "\n" +
                       f"Median Residual: {median_dissipation_residual:.2e}",
                       xy=(0.6, I_arr[len(s_arr)//2]), xytext=(0.4, I_arr[len(s_arr)//2]*5),
                       arrowprops=dict(facecolor="#1f77b4", shrink=0.08, width=1.2, headwidth=6),
                       fontweight="bold", color="#1f77b4",
                       bbox=dict(boxstyle="round,pad=0.3", fc="#e8eaf6", ec="#3f51b5", lw=1))
    
    axs[1, 1].set_title(r"(d) Otto Flow: Free Energy Dissipation & Fisher Information Convergence", pad=10)
    axs[1, 1].set_xlabel(r"Fokker-Planck Flow Time $s$")
    axs[1, 1].set_ylabel(r"Logarithmic Metric Value (Semi-Log)")
    axs[1, 1].grid(True, linestyle=":", alpha=0.6, which="both")
    axs[1, 1].legend(loc="upper right", framealpha=0.9, fontsize=9)
    
    plt.tight_layout()
    figure_path = os.path.join(OUTPUT_DIR, "optimal_transport_eval.png")
    plt.savefig(figure_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"[6] Saved evaluation plot to {figure_path}")
    print("=====================================================================")
    print("Benchmark complete successfully in {:.2f}s.".format(time.time() - start_time))

if __name__ == "__main__":
    run_optimal_transport_benchmark()
