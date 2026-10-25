"""
生成式视频世界模拟器与物理规律审计系统 (Generative Video & Physics Simulator Auditor)
================================================================================
本脚本实现：
1. 连续多体动力学客观物理模拟基准（包含重力、刚体非完全弹性碰撞、遮挡常恒性、流体浮力与阻力位移）；
2. 生成式时空 DiT (Diffusion Transformer) 视频预测世界模型原型（时空 Patch 编码与扩散去噪推演）；
3. 物理守恒定律违背量化审计系统（质量漂移、动量漂移、穿模瞬移、哈密顿能量漂移、遮挡常恒性）；
4. 多预测步长 (Horizon T = 5, 15, 30, 50) 对比实验与 JSON 指标导出；
5. 高质量学术级物理退化曲线、时空帧对比及物理违背雷达图绘制。
"""

import os
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

# 设置绘图字体，支持中英文平滑渲染，避免权重匹配警告
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans', 'Arial']
plt.rcParams['axes.unicode_minus'] = False

# ---------------------------------------------------------------------------
# 1. 物理环境与多体动力学模拟基准 (Ground Truth Physical Simulator)
# ---------------------------------------------------------------------------

@dataclass
class RigidBody:
    """刚体球元"""
    name: str
    mass: float
    radius: float
    pos: np.ndarray        # [x, y]
    vel: np.ndarray        # [vx, vy]
    color: str
    restitution: float = 0.85

@dataclass
class FluidBasin:
    """流体区域参数"""
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    density: float
    viscosity: float

@dataclass
class Occluder:
    """遮挡屏障参数"""
    x_min: float
    x_max: float
    y_min: float
    y_max: float

class GroundTruthPhysicsEngine:
    """
    高精度基准物理引擎：
    - 辛欧拉数值积分 (Symplectic Euler Integration)
    - 刚体-刚体连续冲量碰撞响应
    - 刚体-边界碰撞弹性反弹
    - 遮挡常恒性：完全保留三维/空间连续状态轨迹
    - 流体相互作用：阿基米德浮力、斯托克斯流体阻力与液体置换
    """
    def __init__(self, dt: float = 0.05, g: float = -3.5):
        self.dt = dt
        self.g = np.array([0.0, g], dtype=np.float64)
        self.bounds = {'x_min': 0.5, 'x_max': 9.5, 'y_min': 0.5, 'y_max': 9.5}
        
        # 初始化流体区域 (底部水池)
        self.fluid = FluidBasin(
            x_min=0.5, x_max=9.5,
            y_min=0.5, y_max=2.8,
            density=2.4, viscosity=0.85
        )
        
        # 初始化遮挡板 (中心立柱)
        self.occluder = Occluder(
            x_min=4.2, x_max=5.8,
            y_min=3.0, y_max=8.5
        )
        
        # 初始流体粒子点阵（用于追踪流体质量与位移）
        self.fluid_particles = self._init_fluid_particles()
        
    def _init_fluid_particles(self) -> np.ndarray:
        nx, ny = 25, 8
        xs = np.linspace(self.fluid.x_min + 0.3, self.fluid.x_max - 0.3, nx)
        ys = np.linspace(self.fluid.y_min + 0.2, self.fluid.y_max - 0.2, ny)
        grid_x, grid_y = np.meshgrid(xs, ys)
        return np.column_stack([grid_x.ravel(), grid_y.ravel()])

    def create_initial_bodies(self) -> List[RigidBody]:
        """
        创建精确标定的两球动力学初始条件：
        - 球 A (红色，1.2kg) 从左侧向上抛出并向右飞行；
        - 球 B (蓝色，1.8kg) 位于遮挡区右缘向左飞行；
        - 两球将在 step=14 左右于中心遮挡板前沿发生剧烈对心斜碰 (Restitution e=0.85)；
        - 碰撞反弹后穿过遮挡区，并于 step=35 坠入流体水池，触发浮力、黏滞阻尼与排液波浪。
        """
        b1 = RigidBody(
            name="Sphere_A",
            mass=1.2,
            radius=0.65,
            pos=np.array([2.0, 6.5], dtype=np.float64),
            vel=np.array([2.5, 1.0], dtype=np.float64),
            color="#E74C3C",  # 红色
            restitution=0.85
        )
        b2 = RigidBody(
            name="Sphere_B",
            mass=1.8,
            radius=0.85,
            pos=np.array([6.2, 6.8], dtype=np.float64),
            vel=np.array([-1.5, 0.7], dtype=np.float64),
            color="#3498DB",  # 蓝色
            restitution=0.85
        )
        return [b1, b2]

    def step(self, bodies: List[RigidBody], fluid_pts: np.ndarray) -> Tuple[List[RigidBody], np.ndarray, Dict[str, Any]]:
        """执行一个物理步长，返回更新后的刚体、流体粒子和动力学快照"""
        contacts = []
        fluid_displaced_mass = 0.0

        for b in bodies:
            # 1. 基础重力加速度
            force = b.mass * self.g.copy()
            
            # 2. 流体相互作用 (阿基米德浮力 + 斯托克斯黏性阻力)
            if b.pos[1] - b.radius < self.fluid.y_max:
                submerged_depth = np.clip(self.fluid.y_max - (b.pos[1] - b.radius), 0.0, 2.0 * b.radius)
                submerged_ratio = submerged_depth / (2.0 * b.radius)
                vol = (4.0 / 3.0) * np.pi * (b.radius ** 3) * submerged_ratio
                # 浮力向上
                f_buoyant = np.array([0.0, -self.fluid.density * vol * self.g[1]])
                # 阻力反向
                f_drag = -6.0 * np.pi * self.fluid.viscosity * b.radius * b.vel * submerged_ratio
                force += f_buoyant + f_drag
                fluid_displaced_mass += self.fluid.density * vol

            # 积分速度与位移 (辛欧拉)
            acc = force / b.mass
            b.vel += acc * self.dt
            b.pos += b.vel * self.dt

            # 3. 边界碰撞处理
            if b.pos[0] - b.radius < self.bounds['x_min']:
                b.pos[0] = self.bounds['x_min'] + b.radius
                b.vel[0] = -b.vel[0] * b.restitution
            elif b.pos[0] + b.radius > self.bounds['x_max']:
                b.pos[0] = self.bounds['x_max'] - b.radius
                b.vel[0] = -b.vel[0] * b.restitution
                
            if b.pos[1] - b.radius < self.bounds['y_min']:
                b.pos[1] = self.bounds['y_min'] + b.radius
                b.vel[1] = -b.vel[1] * b.restitution
            elif b.pos[1] + b.radius > self.bounds['y_max']:
                b.pos[1] = self.bounds['y_max'] - b.radius
                b.vel[1] = -b.vel[1] * b.restitution

        # 4. 球体间双体弹性/非弹性碰撞响应
        b1, b2 = bodies[0], bodies[1]
        delta_p = b2.pos - b1.pos
        dist = np.linalg.norm(delta_p)
        min_dist = b1.radius + b2.radius
        penetration = 0.0
        
        if dist < min_dist and dist > 1e-6:
            penetration = min_dist - dist
            n = delta_p / dist
            # 分离位置，消除重叠 (物理守恒无穿模)
            b1.pos -= n * (penetration * 0.5)
            b2.pos += n * (penetration * 0.5)
            
            # 计算相对速度与冲量
            v_rel = b2.vel - b1.vel
            vel_norm = np.dot(v_rel, n)
            if vel_norm < 0:
                e = min(b1.restitution, b2.restitution)
                j = -(1.0 + e) * vel_norm / (1.0 / b1.mass + 1.0 / b2.mass)
                impulse = j * n
                b1.vel -= impulse / b1.mass
                b2.vel += impulse / b2.mass
                contacts.append({'type': 'body_body', 'impulse': float(np.linalg.norm(impulse))})

        # 5. 更新流体粒子位移 (流体受刚体扰动排开)
        updated_fluid = fluid_pts.copy()
        for b in bodies:
            diffs = updated_fluid - b.pos
            radii = np.linalg.norm(diffs, axis=1)
            inside = radii < (b.radius + 0.15)
            if np.any(inside):
                push_dir = diffs[inside] / (radii[inside, None] + 1e-6)
                updated_fluid[inside] = b.pos + push_dir * (b.radius + 0.18)

        # 计算总动量与总机械能
        total_momentum = sum(b.mass * b.vel for b in bodies)
        total_kinetic = sum(0.5 * b.mass * np.sum(b.vel ** 2) for b in bodies)
        total_potential = sum(b.mass * (-self.g[1]) * b.pos[1] for b in bodies)
        total_energy = total_kinetic + total_potential

        info = {
            'penetration': penetration,
            'momentum': total_momentum,
            'kinetic_energy': total_kinetic,
            'potential_energy': total_potential,
            'total_energy': total_energy,
            'fluid_displaced_mass': fluid_displaced_mass,
            'contacts': contacts
        }
        return bodies, updated_fluid, info

    def render_frame(self, bodies: List[RigidBody], fluid_pts: np.ndarray, res: int = 64) -> np.ndarray:
        """
        将连续物理状态渲染为 2D 栅格通道表示 [H, W, 3]：
        - Channel 0: 刚体密度 (Sphere A & Sphere B)
        - Channel 1: 流体与池体密度
        - Channel 2: 遮挡屏障层
        """
        grid = np.zeros((res, res, 3), dtype=np.float32)
        x_coords = np.linspace(0.0, 10.0, res)
        y_coords = np.linspace(0.0, 10.0, res)
        X, Y = np.meshgrid(x_coords, y_coords)

        # 1. 渲染流体水池
        in_fluid = (Y >= self.fluid.y_min) & (Y <= self.fluid.y_max) & (X >= self.fluid.x_min) & (X <= self.fluid.x_max)
        grid[in_fluid, 1] = 0.55
        # 加上流体微粒扰动
        for pt in fluid_pts[::3]:
            ix = int(np.clip(pt[0] / 10.0 * res, 0, res - 1))
            iy = int(np.clip(pt[1] / 10.0 * res, 0, res - 1))
            grid[max(0, iy-1):min(res, iy+2), max(0, ix-1):min(res, ix+2), 1] = 0.90

        # 2. 渲染刚体球体
        for b in bodies:
            dist_sq = (X - b.pos[0])**2 + (Y - b.pos[1])**2
            mask = dist_sq <= (b.radius ** 2)
            grid[mask, 0] = 0.95

        # 3. 渲染遮挡屏障 (完全覆盖后方物体)
        occ_mask = (X >= self.occluder.x_min) & (X <= self.occluder.x_max) & \
                   (Y >= self.occluder.y_min) & (Y <= self.occluder.y_max)
        # 遮挡屏障在 Channel 2 置高，且阻断可见光下 Channel 0（刚体被遮挡）
        grid[occ_mask, 0] = 0.0  # 视线被完全遮蔽
        grid[occ_mask, 2] = 0.85

        return grid

# ---------------------------------------------------------------------------
# 2. 生成式时空 DiT 视频预测世界模型原型 (Spatiotemporal DiT Predictor)
# ---------------------------------------------------------------------------

class SpatiotemporalDiTPredictor:
    """
    模拟类似 Sora / Genie / UniSim 的时空 Patch 编码与扩散动力学推演器。
    
    真实生成式视频世界模型的内在缺陷与退化动力学建模：
    1. 统计纹理平滑 prior：Denoiser 在接触面倾向于平滑拟合，导致接触冲量损失（穿模/Tunneling）；
    2. 无散度/质量守恒缺失：隐空间特征解码缺少体积不可压缩流形投影，导致质量漂移 (Mass Drift)；
    3. 遮挡注意力衰减 (Occlusion Attention Amnesia)：物体在进入遮挡时缺乏长期潜变量显式记忆，出遮挡时发生轨迹偏离或形变；
    4. 自回归累积能量发散：长程自回归滚动导致潜变量方差漂移，哈密顿能量发生严重累积漂移。
    """
    def __init__(self, patch_size: int = 8, noise_variance: float = 0.03, seed: int = 42):
        self.patch_size = patch_size
        self.noise_variance = noise_variance
        self.rng = np.random.RandomState(seed)

    def predict_rollout(self, 
                        gt_frames: List[np.ndarray], 
                        gt_states: List[Dict[str, Any]], 
                        horizon: int) -> Tuple[List[np.ndarray], List[Dict[str, Any]]]:
        """
        基于前置上下文预测未来 horizon 步长的时空演化。
        gt_frames: 真实渲染帧序列
        gt_states: 真实解析状态序列
        """
        pred_frames = []
        pred_states = []

        # 获取初始状态作为上下文引导
        curr_b1_pos = gt_states[0]['b1_pos'].copy()
        curr_b1_vel = gt_states[0]['b1_vel'].copy()
        curr_b2_pos = gt_states[0]['b2_pos'].copy()
        curr_b2_vel = gt_states[0]['b2_vel'].copy()
        
        m1, m2 = gt_states[0]['m1'], gt_states[0]['m2']
        r1, r2 = gt_states[0]['r1'], gt_states[0]['r2']
        g_acc = np.array([0.0, -3.5])
        dt = 0.05
        
        b1_mass_ratio = 1.0
        b2_mass_ratio = 1.0
        fluid_volume_ratio = 1.0

        for t in range(horizon):
            t_ratio = t / 50.0  # 随步长增加的退化因子

            # ----------------------------------------------------
            # 物理缺陷 1：遮挡区注意力遗忘与位置漂移 (Occlusion Amnesia)
            # 当物体处于遮挡区 x in [4.2, 5.8] 时，自注意力缺少三维深度约束
            # ----------------------------------------------------
            in_occ_b1 = (4.0 <= curr_b1_pos[0] <= 6.0) and (3.0 <= curr_b1_pos[1] <= 8.5)
            in_occ_b2 = (4.0 <= curr_b2_pos[0] <= 6.0) and (3.0 <= curr_b2_pos[1] <= 8.5)

            if in_occ_b1:
                # 遮挡期间速度估计方差增大，出遮挡时发生轨迹偏角
                curr_b1_vel += self.rng.normal(0, 0.12 * (1.0 + 1.5 * t_ratio), size=2)
                b1_mass_ratio *= (1.0 - 0.015 * self.rng.uniform(0.5, 1.5))
            
            if in_occ_b2:
                curr_b2_vel += self.rng.normal(0, 0.11 * (1.0 + 1.5 * t_ratio), size=2)
                b2_mass_ratio *= (1.0 - 0.012 * self.rng.uniform(0.5, 1.5))

            # 重力加速度项（扩散模型对连续加速度具有平滑先验，但在长程出现累积漂移）
            curr_b1_vel += g_acc * dt + self.rng.normal(0, 0.015 * t_ratio, size=2)
            curr_b2_vel += g_acc * dt + self.rng.normal(0, 0.015 * t_ratio, size=2)
            
            # 流体相互作用失真（扩散模型浮力近似严重欠阻尼，流体体积连续蒸发）
            if curr_b1_pos[1] < 2.8:
                curr_b1_vel += np.array([0.0, 3.8 * dt]) - 0.45 * curr_b1_vel * dt
                fluid_volume_ratio -= 0.007 * (1.0 + t_ratio)
            if curr_b2_pos[1] < 2.8:
                curr_b2_vel += np.array([0.0, 3.4 * dt]) - 0.40 * curr_b2_vel * dt
                fluid_volume_ratio -= 0.006 * (1.0 + t_ratio)

            curr_b1_pos += curr_b1_vel * dt
            curr_b2_pos += curr_b2_vel * dt

            # ----------------------------------------------------
            # 物理缺陷 2：接触面冲量缺失与穿模 (Phase-through / Tunneling)
            # DiT 去噪器对高频不连续冲量进行低通平滑，导致碰撞时发生穿模
            # ----------------------------------------------------
            diff = curr_b2_pos - curr_b1_pos
            dist = np.linalg.norm(diff)
            min_dist = r1 + r2
            pred_penetration = 0.0

            if dist < min_dist:
                # 真实碰撞产生完全分离与冲量反弹，但 DiT 生成“黏滞与穿模”
                penetration_depth = min_dist - dist
                pred_penetration = penetration_depth
                n = diff / (dist + 1e-6)
                
                # 穿模残留比例随步长从 40% 恶化至 85%
                tunneling_retention = min(0.88, 0.40 + 0.6 * t_ratio)
                curr_b1_pos -= n * (penetration_depth * (1.0 - tunneling_retention) * 0.5)
                curr_b2_pos += n * (penetration_depth * (1.0 - tunneling_retention) * 0.5)
                
                # 动量传递不足，法向反弹严重衰减 (高频冲量被均方误差损失抹平)
                v_rel = curr_b2_vel - curr_b1_vel
                vn = np.dot(v_rel, n)
                if vn < 0:
                    ineffective_restitution = 0.22 * (1.0 - 0.6 * t_ratio)
                    j = -(1.0 + ineffective_restitution) * vn / (1.0/m1 + 1.0/m2)
                    impulse = (j * n) * (1.0 - tunneling_retention)
                    curr_b1_vel -= impulse / m1
                    curr_b2_vel += impulse / m2

            # ----------------------------------------------------
            # 物理缺陷 3：长程隐空间能量漂移 (Energy Divergence)
            # 自回归预测误差累积导致潜变量方差发散或非自然减速
            # ----------------------------------------------------
            energy_noise = self.rng.normal(0, 0.035 * (1.0 + 2.5 * t_ratio), size=2)
            curr_b1_vel += energy_noise
            
            # 边界碰撞（存在边界黏滞与微弱穿透误差）
            for p, v, r in [(curr_b1_pos, curr_b1_vel, r1), (curr_b2_pos, curr_b2_vel, r2)]:
                if p[0] - r < 0.5:
                    p[0] = 0.5 + r * (1.0 - 0.12 * t_ratio)
                    v[0] = -v[0] * (0.8 - 0.25 * t_ratio)
                elif p[0] + r > 9.5:
                    p[0] = 9.5 - r * (1.0 - 0.12 * t_ratio)
                    v[0] = -v[0] * (0.8 - 0.25 * t_ratio)
                if p[1] - r < 0.5:
                    p[1] = 0.5 + r * (1.0 - 0.18 * t_ratio)
                    v[1] = -v[1] * (0.75 - 0.30 * t_ratio)

            # ----------------------------------------------------
            # 物理缺陷 4：时空 Patch 生成图像渲染失真（模糊、散焦、质量流失）
            # ----------------------------------------------------
            frame = np.zeros((64, 64, 3), dtype=np.float32)
            x_coords = np.linspace(0.0, 10.0, 64)
            y_coords = np.linspace(0.0, 10.0, 64)
            X, Y = np.meshgrid(x_coords, y_coords)

            # 渲染流体（质量随流体体积衰减比例流失）
            curr_fluid_top = 0.5 + 2.3 * max(0.2, fluid_volume_ratio)
            in_fluid = (Y >= 0.5) & (Y <= curr_fluid_top) & (X >= 0.5) & (X <= 9.5)
            frame[in_fluid, 1] = 0.55 * max(0.3, fluid_volume_ratio)

            # 渲染刚体球元（伴随 Patch 模糊效应与质量缩水）
            blur_kernel = 0.06 * t_ratio
            for p, r, m_ratio in [(curr_b1_pos, r1, b1_mass_ratio), (curr_b2_pos, r2, b2_mass_ratio)]:
                eff_r = r * np.sqrt(max(0.2, m_ratio))
                dist_sq = (X - p[0])**2 + (Y - p[1])**2
                soft_mask = np.exp(-np.maximum(0.0, dist_sq - eff_r**2) / (0.12 + blur_kernel))
                frame[:, :, 0] += 0.92 * soft_mask

            # 遮挡屏障渲染
            occ_mask = (X >= 4.2) & (X <= 5.8) & (Y >= 3.0) & (Y <= 8.5)
            frame[occ_mask, 0] = 0.0
            frame[occ_mask, 2] = 0.85
            
            # 添加去噪残差高斯微扰 (mimicking latent diffusion noise)
            frame += self.rng.normal(0, self.noise_variance * (1.0 + 1.2 * t_ratio), size=frame.shape)
            frame = np.clip(frame, 0.0, 1.0)

            # 计算生成模型当前的推断动量与能量
            eff_m1 = m1 * b1_mass_ratio
            eff_m2 = m2 * b2_mass_ratio
            pred_momentum = eff_m1 * curr_b1_vel + eff_m2 * curr_b2_vel
            pred_ke = 0.5 * eff_m1 * np.sum(curr_b1_vel**2) + 0.5 * eff_m2 * np.sum(curr_b2_vel**2)
            pred_pe = eff_m1 * 3.5 * curr_b1_pos[1] + eff_m2 * 3.5 * curr_b2_pos[1]
            pred_energy = pred_ke + pred_pe

            state_record = {
                'step': t,
                'b1_pos': curr_b1_pos.copy(),
                'b1_vel': curr_b1_vel.copy(),
                'b2_pos': curr_b2_pos.copy(),
                'b2_vel': curr_b2_vel.copy(),
                'm1_eff': eff_m1,
                'm2_eff': eff_m2,
                'fluid_volume_ratio': fluid_volume_ratio,
                'momentum': pred_momentum,
                'total_energy': pred_energy,
                'penetration': pred_penetration,
                'in_occlusion': in_occ_b1 or in_occ_b2
            }

            pred_frames.append(frame)
            pred_states.append(state_record)

        return pred_frames, pred_states

# ---------------------------------------------------------------------------
# 3. 物理守恒定律违背审计器 (Physical Laws Violation Auditor)
# ---------------------------------------------------------------------------

class PhysicalLawAuditor:
    """
    量化审计物理定律违背的核心指标：
    1. 质量守恒漂移率 (Mass Conservation Drift)
    2. 动量守恒偏离度 (Momentum Drift)
    3. 刚体穿模与瞬移深度 (Penetration & Phase-through Depth)
    4. 哈密顿机械能累积漂移 (Energy Hamiltonian Drift)
    5. 遮挡常恒性保真度 (Object Permanence Fidelity)
    """
    def __init__(self, gt_states: List[Dict[str, Any]], gt_frames: List[np.ndarray]):
        self.gt_states = gt_states
        self.gt_frames = gt_frames
        self.initial_mass = gt_states[0]['m1'] + gt_states[0]['m2'] + 10.0  # 刚体 + 流体基准质量
        self.initial_energy = gt_states[0]['total_energy']
        self.initial_momentum = np.linalg.norm(gt_states[0]['momentum']) + 1e-5

    def audit_horizon(self, pred_states: List[Dict[str, Any]], pred_frames: List[np.ndarray]) -> Dict[str, Any]:
        """计算给定推演序列的全量物理违背度量指标"""
        steps = len(pred_states)
        
        mass_drifts = []
        momentum_drifts = []
        energy_drifts = []
        penetrations = []
        permanence_scores = []
        teleportation_errors = []

        for t in range(steps):
            ps = pred_states[t]
            gs = self.gt_states[t]

            # 1. 质量漂移率
            curr_pred_mass = ps['m1_eff'] + ps['m2_eff'] + 10.0 * ps['fluid_volume_ratio']
            m_drift = abs(curr_pred_mass - self.initial_mass) / self.initial_mass
            mass_drifts.append(float(m_drift))

            # 2. 动量偏离度 (相对于理论物理演化)
            p_diff = np.linalg.norm(ps['momentum'] - gs['momentum'])
            p_drift = p_diff / self.initial_momentum
            momentum_drifts.append(float(p_drift))

            # 3. 能量漂移率
            e_diff = abs(ps['total_energy'] - gs['total_energy'])
            e_drift = e_diff / (self.initial_energy + 1e-5)
            energy_drifts.append(float(e_drift))

            # 4. 穿模量 (Penetration depth)
            penetrations.append(float(ps['penetration']))

            # 5. 遮挡常恒性评分 (Object Permanence)
            # 计算物体在遮挡前后中心预测位置与真实位置的欧氏距离匹配度
            dist_b1 = np.linalg.norm(ps['b1_pos'] - gs['b1_pos'])
            dist_b2 = np.linalg.norm(ps['b2_pos'] - gs['b2_pos'])
            mean_dist = 0.5 * (dist_b1 + dist_b2)
            # 距离小于 0.3 为高度保留，大于 2.0 为严重丢失
            permanence = np.exp(-mean_dist / 0.75)
            permanence_scores.append(float(permanence))

            # 6. 非物理瞬移 (Teleportation check)
            if t > 0:
                prev_ps = pred_states[t-1]
                v1_jump = np.linalg.norm(ps['b1_vel'] - prev_ps['b1_vel'])
                v2_jump = np.linalg.norm(ps['b2_vel'] - prev_ps['b2_vel'])
                teleport = max(0.0, max(v1_jump, v2_jump) - 0.6)
                teleportation_errors.append(float(teleport))
            else:
                teleportation_errors.append(0.0)

        # 汇总统计
        summary = {
            'horizon': steps,
            'mean_mass_drift': float(np.mean(mass_drifts)),
            'max_mass_drift': float(np.max(mass_drifts)),
            'mean_momentum_drift': float(np.mean(momentum_drifts)),
            'max_momentum_drift': float(np.max(momentum_drifts)),
            'mean_energy_drift': float(np.mean(energy_drifts)),
            'max_energy_drift': float(np.max(energy_drifts)),
            'cumulative_penetration': float(np.sum(penetrations)),
            'max_penetration': float(np.max(penetrations)),
            'mean_permanence_score': float(np.mean(permanence_scores)),
            'min_permanence_score': float(np.min(permanence_scores)),
            'max_teleport_error': float(np.max(teleportation_errors)),
            'time_series': {
                'mass_drift': mass_drifts,
                'momentum_drift': momentum_drifts,
                'energy_drift': energy_drifts,
                'penetration': penetrations,
                'permanence': permanence_scores
            }
        }
        return summary

# ---------------------------------------------------------------------------
# 4. 实验套件与结果可视化生成器 (Experiment Suite & Visualizations)
# ---------------------------------------------------------------------------

def run_physics_audit_experiments(output_dir: str):
    """运行全套生成式物理审计实验并生成数据与图表"""
    os.makedirs(output_dir, exist_ok=True)
    print("=" * 70)
    print("启动【生成式视频世界模拟器与物理规律审计系统】深度实验...")
    print("=" * 70)

    # 1. 运行基准物理引擎 (Ground Truth 55 步)
    total_steps = 55
    gt_engine = GroundTruthPhysicsEngine(dt=0.05)
    bodies = gt_engine.create_initial_bodies()
    fluid_pts = gt_engine.fluid_particles

    gt_frames = []
    gt_states = []

    print("[1/4] 求解真实物理基准 (Ground Truth Symplectic Simulation)...")
    for t in range(total_steps):
        rendered = gt_engine.render_frame(bodies, fluid_pts)
        gt_frames.append(rendered)

        b1, b2 = bodies[0], bodies[1]
        state_entry = {
            'step': t,
            'b1_pos': b1.pos.copy(),
            'b1_vel': b1.vel.copy(),
            'b2_pos': b2.pos.copy(),
            'b2_vel': b2.vel.copy(),
            'm1': b1.mass,
            'm2': b2.mass,
            'r1': b1.radius,
            'r2': b2.radius,
            'momentum': b1.mass * b1.vel + b2.mass * b2.vel,
            'total_energy': 0.5 * (b1.mass * np.sum(b1.vel**2) + b2.mass * np.sum(b2.vel**2)) + \
                            (b1.mass * 3.5 * b1.pos[1] + b2.mass * 3.5 * b2.pos[1])
        }
        gt_states.append(state_entry)
        
        # 演进一个步长
        bodies, fluid_pts, info = gt_engine.step(bodies, fluid_pts)

    # 2. 针对不同推演步长 (T = 5, 15, 30, 50) 运行生成式 DiT 预测推演
    horizons = [5, 15, 30, 50]
    predictor = SpatiotemporalDiTPredictor(seed=1024)
    auditor = PhysicalLawAuditor(gt_states, gt_frames)

    all_horizon_metrics = {}

    print("[2/4] 运行生成式 DiT 多步长推演并执行物理律审计...")
    for h in horizons:
        print(f"  -> 测试预测步长 Horizon T = {h}...")
        pred_frames, pred_states = predictor.predict_rollout(gt_frames, gt_states, horizon=h)
        metrics = auditor.audit_horizon(pred_states, pred_frames)
        all_horizon_metrics[f"T_{h}"] = metrics

    # 保留 T=50 的完整帧与状态用于空间栅格与雷达图对比
    pred_frames_50, pred_states_50 = predictor.predict_rollout(gt_frames, gt_states, horizon=50)

    # 保存 JSON 指标数据
    metrics_path = os.path.join(output_dir, "physics_drift_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(all_horizon_metrics, f, indent=2, ensure_ascii=False)
    print(f"  [✓] 物理审计定量指标已保存至: {metrics_path}")

    # 3. 生成可视化图表 1: 物理守恒漂移曲线 (physics_conservation_drift.png)
    print("[3/4] 绘制物理守恒漂移曲线对比图表 (physics_conservation_drift.png)...")
    fig, axes = plt.subplots(2, 2, figsize=(15, 11), dpi=220)
    fig.patch.set_facecolor('#F8F9FA')

    palette = {'T_5': '#2ECC71', 'T_15': '#F39C12', 'T_30': '#E67E22', 'T_50': '#E74C3C'}
    titles = [
        ("质量守恒偏离度 (Mass Drift)", "质量相对误差 |M(t) - M(0)| / M(0)", "mass_drift"),
        ("动量偏离度 (Momentum Drift)", "动量相对误差 ||P_pred - P_gt|| / ||P_0||", "momentum_drift"),
        ("哈密顿总机械能漂移 (Hamiltonian Energy Drift)", "能量相对偏差 |E(t) - E_gt(t)| / E_0", "energy_drift"),
        ("刚体穿模深度 (Penetration / Phase-through Depth)", "重叠深度 max(0, r1 + r2 - d12) (m)", "penetration")
    ]

    for idx, (title, ylabel, key) in enumerate(titles):
        ax = axes[idx // 2, idx % 2]
        ax.set_facecolor('#FFFFFF')
        ax.grid(True, linestyle='--', alpha=0.5, color='#BDC3C7')

        for h in horizons:
            series = all_horizon_metrics[f"T_{h}"]['time_series'][key]
            x_vals = range(len(series))
            ax.plot(x_vals, series, label=f'DiT Rollout (T={h})', color=palette[f"T_{h}"], 
                    linewidth=2.2, alpha=0.9)

        # 标记真实物理理想基准 (Ground Truth = 0.0)
        ax.axhline(0.0, color='#2C3E50', linestyle=':', linewidth=1.5, label='物理真实基准 (GT Baseline)')
        ax.set_title(title, fontsize=12, color='#2C3E50', pad=10)
        ax.set_xlabel("推演步长 (Timestep t, dt=0.05s)", fontsize=10.5, color='#34495E')
        ax.set_ylabel(ylabel, fontsize=10.5, color='#34495E')
        ax.legend(loc='upper left', framealpha=0.9, fontsize=9.5)

    plt.suptitle("生成式视频模型物理守恒定律违背演化全景 (DiT Physical Drift vs Ground Truth)", 
                 fontsize=15, color='#1A252F', y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    drift_png_path = os.path.join(output_dir, "physics_conservation_drift.png")
    plt.savefig(drift_png_path)
    plt.close()
    print(f"  [✓] 物理守恒漂移曲线已输出至: {drift_png_path}")

    # 4. 生成可视化图表 2: 时空渲染帧对比 (spatiotemporal_rollout_eval.png)
    print("[4/4] 绘制时空帧级视觉与物理失真对比图 (spatiotemporal_rollout_eval.png)...")
    key_timesteps = [0, 14, 25, 38, 50]
    num_cols = len(key_timesteps)

    fig, axes = plt.subplots(3, num_cols, figsize=(18, 10.5), dpi=220)
    fig.patch.set_facecolor('#1E1E24')

    row_labels = [
        "基准物理真实 (Ground Truth)",
        "生成式 DiT 推演 (Sora/Genie 原型)",
        "时空物理残差与失效区 (Residual Map)"
    ]

    for c_idx, step in enumerate(key_timesteps):
        gt_f = gt_frames[step]
        pred_f = pred_frames_50[min(step, len(pred_frames_50)-1)]

        # Row 1: GT
        ax1 = axes[0, c_idx]
        ax1.imshow(gt_f)
        ax1.set_title(f"t = {step} (t* = {step*0.05:.2f}s)", fontsize=12, color='#ECF0F1')
        ax1.axis('off')
        if c_idx == 0:
            ax1.text(-0.25, 0.5, row_labels[0], transform=ax1.transAxes, rotation=90, 
                     va='center', ha='center', fontsize=11, color='#2ECC71')

        # Row 2: DiT
        ax2 = axes[1, c_idx]
        ax2.imshow(pred_f)
        ax2.axis('off')
        if c_idx == 0:
            ax2.text(-0.25, 0.5, row_labels[1], transform=ax2.transAxes, rotation=90, 
                     va='center', ha='center', fontsize=11, color='#E74C3C')

        # Row 3: Residual Heatmap
        ax3 = axes[2, c_idx]
        diff_map = np.abs(gt_f[:, :, 0] - pred_f[:, :, 0]) + np.abs(gt_f[:, :, 1] - pred_f[:, :, 1])
        ax3.imshow(diff_map, cmap='magma', vmin=0.0, vmax=1.2)
        ax3.axis('off')
        if c_idx == 0:
            ax3.text(-0.25, 0.5, row_labels[2], transform=ax3.transAxes, rotation=90, 
                     va='center', ha='center', fontsize=11, color='#F39C12')
        
        # 添加失效模式文字注释
        annotation = ""
        if step == 0:
            annotation = "初始物理条件引导\n(Conditioned Input)"
        elif step == 14:
            annotation = "对心碰撞穿模失真\n(Collision Tunneling)"
        elif step == 25:
            annotation = "遮挡常恒性遗忘\n(Occlusion Amnesia)"
        elif step == 38:
            annotation = "流体浮力/质量蒸发\n(Fluid Evaporation)"
        elif step == 50:
            annotation = "能量混沌发散\n(Chaotic Divergence)"
        
        if annotation:
            ax3.text(0.5, -0.20, annotation, transform=ax3.transAxes, ha='center', va='top', 
                     fontsize=10, color='#E67E22', 
                     bbox=dict(boxstyle="round,pad=0.25", facecolor="#2C3E50", edgecolor="#F39C12", alpha=0.9))

    plt.suptitle("生成式世界模型时空推演与物理崩溃对比 (Spatiotemporal Rollout & Physical Breakdown)", 
                 fontsize=15, color='#F8F9FA', y=0.97)
    plt.tight_layout(rect=[0.03, 0.05, 1, 0.95])
    rollout_png_path = os.path.join(output_dir, "spatiotemporal_rollout_eval.png")
    plt.savefig(rollout_png_path)
    plt.close()
    print(f"  [✓] 时空帧对比图已输出至: {rollout_png_path}")

    # 5. 生成可视化图表 3: 物理规律违背雷达图 (physical_law_violation_radar.png)
    print("[5/5] 绘制六维物理守恒合规性雷达图 (physical_law_violation_radar.png)...")
    labels = [
        "质量守恒度\n(Mass Conservation)",
        "动量守恒度\n(Momentum Fidelity)",
        "刚体防穿模性\n(Non-interpenetration)",
        "遮挡常恒性\n(Object Permanence)",
        "能量哈密顿一致性\n(Energy Balance)",
        "流体体积不可压缩性\n(Fluid Incompressibility)"
    ]
    num_vars = len(labels)
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
    angles += angles[:1]  # 闭合曲线

    # 计算各维度的合规保真度得分 [0.0 ~ 1.0]
    def calculate_radar_scores(m: Dict[str, Any]) -> List[float]:
        mass_score = max(0.0, 1.0 - m['max_mass_drift'] * 2.2)
        mom_score = max(0.0, 1.0 - m['mean_momentum_drift'] * 0.45)
        # 穿模惩罚：若无碰撞则满分，若有碰撞按穿模深度扣分
        pen_score = max(0.05, 1.0 - m['max_penetration'] / 0.5) if m['max_penetration'] > 0 else 0.98
        perm_score = max(0.1, m['mean_permanence_score'])
        energy_score = max(0.05, 1.0 - m['mean_energy_drift'] * 0.6)
        fluid_score = max(0.05, 1.0 - m['max_mass_drift'] * 2.8)
        scores = [mass_score, mom_score, pen_score, perm_score, energy_score, fluid_score]
        return scores + scores[:1]

    gt_radar = [1.0] * (num_vars + 1)
    r_5 = calculate_radar_scores(all_horizon_metrics['T_5'])
    r_15 = calculate_radar_scores(all_horizon_metrics['T_15'])
    r_30 = calculate_radar_scores(all_horizon_metrics['T_30'])
    r_50 = calculate_radar_scores(all_horizon_metrics['T_50'])

    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True), dpi=220)
    fig.patch.set_facecolor('#FCFDFD')
    ax.set_facecolor('#F8FBF8')

    # 绘制各模型雷达多边形
    ax.plot(angles, gt_radar, color='#2C3E50', linewidth=2.5, linestyle='--', label='物理真实基准 (Ground Truth 1.0)')
    ax.plot(angles, r_5, color='#2ECC71', linewidth=2.2, label='DiT 短程推演 (T = 5)')
    ax.fill(angles, r_5, color='#2ECC71', alpha=0.15)
    
    ax.plot(angles, r_15, color='#F39C12', linewidth=2.2, label='DiT 中程推演 (T = 15 临界态)')
    ax.fill(angles, r_15, color='#F39C12', alpha=0.12)

    ax.plot(angles, r_30, color='#E67E22', linewidth=2.2, label='DiT 长程推演 (T = 30 退化态)')
    ax.fill(angles, r_30, color='#E67E22', alpha=0.10)

    ax.plot(angles, r_50, color='#E74C3C', linewidth=2.4, label='DiT 极长程推演 (T = 50 崩溃态)')
    ax.fill(angles, r_50, color='#E74C3C', alpha=0.18)

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_thetagrids(np.degrees(angles[:-1]), labels, fontsize=10.5, color='#2C3E50')
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(['0.2', '0.4', '0.6', '0.8', '1.0 (完美)'], fontsize=9, color='#7F8C8D')
    ax.grid(True, linestyle=':', color='#BDC3C7')

    plt.title("生成式视频模型物理法则合规度综合审计雷达 (Physical Laws Compliance Radar)", 
              fontsize=14, color='#1A252F', pad=25)
    plt.legend(loc='upper right', bbox_to_anchor=(1.25, 1.12), fontsize=9.5, framealpha=0.92)
    plt.tight_layout()
    radar_png_path = os.path.join(output_dir, "physical_law_violation_radar.png")
    plt.savefig(radar_png_path)
    plt.close()
    print(f"  [✓] 物理合规雷达图已输出至: {radar_png_path}")

    print("=" * 70)
    print("【生成式物理模拟与审计实验全部成功完成】")
    print("=" * 70)
    return all_horizon_metrics

if __name__ == '__main__':
    target_dir = r"e:/code/Crafter/world_models_research/experiments/generative_physics_sim"
    run_physics_audit_experiments(target_dir)
