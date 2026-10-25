# 离散循环状态空间模型 (Discrete RSSM) 原型与推演分析

本目录包含 **Dreamer V2 / V3** 核心架构——离散分类循环状态空间模型（Discrete Categorical Recurrent State-Space Model, **Discrete RSSM**）的轻量级纯 Python / PyTorch 原型实现与复合误差（Compounding Error）评测套件。

---

## 目录
- [1. 核心数学机理与架构设计](#1-核心数学机理与架构设计)
  - [1.1 确定性与随机性隐状态解耦](#11-确定性与随机性隐状态解耦)
  - [1.2 多组独立离散分类潜变量 (Categorical Latents)](#12-多组独立离散分类潜变量-categorical-latents)
  - [1.3 直通估计器 (Straight-Through Estimator)](#13-直通估计器-straight-through-estimator)
  - [1.4 转移先验与表征后验](#14-转移先验与表征后验)
  - [1.5 KL 平衡机制 (KL Balancing)](#15-kl-平衡机制-kl-balancing)
- [2. 架构与数据流图解](#2-架构与数据流图解)
- [3. 快速上手与运行指南](#3-快速上手与运行指南)
  - [3.1 环境依赖](#31-环境依赖)
  - [3.2 运行脚本](#32-运行脚本)
  - [3.3 命令行参数详解](#33-命令行参数详解)
- [4. 单元测试与自测规范](#4-单元测试与自测规范)
- [5. 复合误差 (Compounding Error) 量化分析与曲线解读](#5-复合误差-compounding-error-量化分析与曲线解读)

---

## 1. 核心数学机理与架构设计

### 1.1 确定性与随机性隐状态解耦

经典循环神经网络在长期推演时容易受随机噪声干扰，而纯马尔可夫潜变量模型难以保持长时程因果记忆。RSSM（Hafner et al.）创造性地将模型隐状态解耦为两大互补部分：
- **确定性循环状态** $h_t \in \mathbb{R}^{D_h}$：通过门控循环单元（GRU Cell）维持跨步长程因果历史上下文，不包含随机采样噪声。
  $$h_t = \text{GRU}(h_{t-1}, [z_{t-1}, a_{t-1}])$$
- **随机分类状态** $z_t$：捕捉环境的不确定性、多峰物理演变以及无法由历史完全决定的随机事件。

完整潜空间表征定义为：
$$s_t = [h_t, \text{flatten}(z_t)] \in \mathbb{R}^{D_h + N \cdot K}$$

### 1.2 多组独立离散分类潜变量 (Categorical Latents)

与 Dreamer V1 采用的连续多维高斯分布不同，Dreamer V2 / V3 引入了离散多项式分类分布（Categorical Distributions）：
- 潜状态包含 $N$ 组独立的离散变量，每组具有 $K$ 个类别选项（如 $N=16, K=16$ 或 $N=32, K=32$）。
- **优势**：
  1. **防止后验塌缩**：连续高斯分布容易被优化器将方差拉平或匹配至单峰标准正态分布，离散分类分布天然具备信息瓶颈，抵抗模式丢失。
  2. **非平滑/多峰动力学建模**：物理世界中的接触、碰撞、离散状态切换（如物品掉落或按键开关）更适合用离散分类表示。

### 1.3 直通估计器 (Straight-Through Estimator)

离散采样（Argmax / One-Hot）不可微，为了使得端到端反向传播畅通，模型采用直通估计器技巧：
- **前向传播**：注入 Gumbel 噪声并提取硬 One-Hot 向量：
  $$z_{\text{soft}} = \text{softmax}\left(\frac{\text{logits} + g}{\tau}\right), \quad g \sim \text{Gumbel}(0, 1)$$
  $$z_{\text{hard}} = \text{one\_hot}(\arg\max(z_{\text{soft}}))$$
- **直通梯度运算**：
  $$z = z_{\text{hard}} + z_{\text{soft}} - \text{stop\_gradient}(z_{\text{soft}})$$
- **性质**：在前向计算中，$z \equiv z_{\text{hard}}$ 保持纯粹离散特性；在后向传播中，$\frac{\partial z}{\partial \text{logits}} \equiv \frac{\partial z_{\text{soft}}}{\partial \text{logits}}$，梯度顺畅无阻地传回参数网络。

### 1.4 转移先验与表征后验

RSSM 维持两套隐变量预测分支：
- **转移先验 (Transition Prior) $p(z_t \mid h_t)$**：仅依靠先前的确定性上下文 $h_t$，无外界输入。在纯粹“梦境想象”（Imagination Rollout）中，系统仅依靠先验动力学推进演变。
- **表征后验 (Representation Posterior) $q(z_t \mid h_t, o_t)$**：融合了外部环境传感器返回的真实观测 $o_t$，提取包含真实物理事实的高保真隐表征。

### 1.5 KL 平衡机制 (KL Balancing)

常规变分下界（ELBO）对先验和后验施加对称的 KL 散度约束，导致两个严重缺陷：
1. 先验模型尚未收敛时，后验被强行拉向错误的先验，导致特征表达能力退化；
2. 后验学习速度过快，产生过度正则化。

Dreamer V2 提出带有截断梯度（Stop-Gradient, $\text{sg}$）的 **KL 平衡损失**：
$$\mathcal{L}_{\text{KL}} = \alpha \cdot D_{\text{KL}}(\text{sg}(q(z_t \mid h_t, o_t)) \parallel p(z_t \mid h_t)) + (1 - \alpha) \cdot D_{\text{KL}}(q(z_t \mid h_t, o_t) \parallel \text{sg}(p(z_t \mid h_t)))$$
- 设置 $\alpha = 0.8$：让先验 $p$ 以 0.8 的较高权重加速逼近后验 $q$，快速掌握真实物理演进规律；
- 以 $1 - \alpha = 0.2$ 的温和权重约束后验 $q$，防止表征过载，提供正则化保护。

---

## 2. 架构与数据流图解

```text
[闭环感知时序步 (Filtering Step)]
   o_t (环境观测) ---> [Encoder] ---> e_t
                                      |
   [h_{t-1}, z_{t-1}, a_{t-1}]        v
                |             [Posterior Net] ---> q(z_t | h_t, o_t) ---> z_t (One-Hot)
                v                                                               |
            [GRU Cell] ---> h_t -----------------------------------------> [+] (拼接潜状态)
                |                                                               |
                v                                                               v
         [Prior Net] ---> p(z_t | h_t)                                  [Decoders]
                |                                                               |
                +-- (KL Balancing Loss: alpha=0.8) <----------------------------+---> \hat{o}_t, \hat{r}_t

[开环梦境推演步 (Imagination Rollout Step)]
   [h_{t-1}, z_{t-1}, a_{t-1}]
                |
                v
            [GRU Cell] ---> h_t
                |            |
                v            v
         [Prior Net] ---> p(z_t | h_t) ---> 采样 z_t (One-Hot)
                                                    |
                                                    v
                                          [Decoder] ---> \hat{o}_t^{dream}, \hat{r}_t^{dream}
```

---

## 3. 快速上手与运行指南

### 3.1 环境依赖

- Python >= 3.8
- PyTorch >= 2.0 (纯 CPU 环境即可秒级流畅运行)

如果项目根目录下已配置虚拟环境，脚本会自动侦测并使用 `.venv` 中的 Python 运行。

### 3.2 运行脚本

直接执行（将自动运行 4 大单元测试、仿真训练 100 步并输出 15 步复合误差报告）：

```powershell
python world_models_research/scripts/rssm_discrete_rollout.py
```

或使用项目虚拟环境显式运行：

```powershell
e:/code/Crafter/.venv/Scripts/python.exe e:/code/Crafter/world_models_research/scripts/rssm_discrete_rollout.py
```

### 3.3 命令行参数详解

| 参数项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--obs-dim` | `8` | 连续物理环境观测特征向量维度 |
| `--action-dim` | `2` | 控制动作维度（如二维驱动力向量） |
| `--deter-dim` | `128` | GRU 确定性循环隐状态 $h_t$ 向量维度 |
| `--num-cats`, `--num_cats`, `--num_stoch_groups` | `16` | 离散分类隐变量组数 $N$ |
| `--num-classes`, `--num_classes`, `--num_stoch_classes` | `16` | 每组离散分类隐变量类别数 $K$ (总隐维度 $N \times K = 256$) |
| `--kl-alpha`, `--kl_alpha`, `--kl-balancing-alpha` | `0.8` | KL 平衡权重 $\alpha$ (0.8 为先验快速跟踪，0.2 为后验正则) |
| `--free-bits`, `--kl-free-bits` | `0.1` | KL Free Bits 下限约束（仅施加于后验，先验自由拟合防梯度死区） |
| `--temperature`, `--temp` | `1.0` | Gumbel-Softmax 退火采样温度 (内置 $\ge 10^{-6}$ 数值防除零保护) |
| `--horizon` | `15` | 开环梦境推演评估视界步数 $H$ (动态自适应扩展物理轨迹长程评估) |
| `--steps` | `100` | 原型端到端微调优化训练步数 |
| `--test-only` | `False` | 仅执行自动化单元测试套件后退出 |

示例：自定义评估 30 步开环推演视界与隐变量配置：
```powershell
python rssm_discrete_rollout.py --horizon 30 --kl_alpha 0.8 --num_stoch_groups 16 --num_stoch_classes 16
```

---

## 4. 单元测试与自测规范

脚本内置了自动化测试套件 `TestDiscreteRSSMSuite`，每次运行均会自动触发：

1. **直通估计器梯度连通测试** (`test_straight_through_gradient`)：
   验证前向采样输出严格满足 One-Hot 分布归一化条件，同时梯度能够完整穿透离散采样层回传至对数几率张量 logits。
2. **KL 平衡梯度隔离与死区免疫测试** (`test_kl_balancing_stop_gradient`)：
   验证当优化先验损失项时，后验分支梯度为 None（无泄露）；优化后验约束项时，先验分支梯度为 None；并在极小散度下检验先验梯度依然顺畅流通无死区。
3. **时序张量维度完备性测试** (`test_tensor_shapes`)：
   验证闭环展开张量形状与解码输出维度完全对齐。
4. **开环推演时间轴对齐测试** (`test_rollout_horizon_consistency`)：
   验证推演视界在起始时步与闭环滤波历史状态平滑接轨。
5. **Gumbel-Softmax 温度下限与数值鲁棒性防御测试** (`test_temperature_boundary_defense`)：
   验证在极小采样温度 $T=0.0$ 或极端对数几率下，前向与反向传播不产生 `NaN` 或数值下溢。

---

## 5. 复合误差 (Compounding Error) 量化分析与曲线解读

### 5.1 复合误差核心指标定义

在推演视界 $h \in [1, H]$ 内，脚本定量追踪以下关键偏离度量：
1. **确定性隐状态漂移 (Deter L2)**：$\|h_{t+h}^{\text{dream}} - h_{t+h}^{\text{closed}}\|_2$
2. **离散符号未命中率 (Hamming Mismatch %)**：One-Hot 预测符号与真实后验未匹配的比例。
3. **潜分布 JSD (Jensen-Shannon Divergence)**：评估先验分布 $p(z_{t+h} \mid h_{t+h}^{\text{dream}})$ 与真实后验分布 $q(z_{t+h} \mid h_{t+h}^{\text{closed}}, o_{t+h})$ 之间的对称概率散度。
4. **观测重构均方误差漂移 (Reconstruction MSE)**：$\|\hat{o}_{t+h}^{\text{dream}} - o_{t+h}^{\text{true}}\|^2$。
5. **奖赏绝对误差 (Reward MAE)**：$|\hat{r}_{t+h}^{\text{dream}} - r_{t+h}^{\text{true}}|$。

### 5.2 复合误差三阶段演化机理

```text
观测 MSE 漂移
  ^
  |                     饱和衰减期 (Plateau Phase, t >= 8)
  |                  .-----------------------------
  |                 /  (动力学演化进入极限环或宏观稳态分布)
  |                /
  |               / 敏感情报发散期 (Divergence Phase, t = 4~7)
  |              /  (自回归反馈放大微小漂移)
  |    .--------'
  |   / 高保真惯性期 (Inertia Phase, t = 1~3)
  +----------------------------------------------------> 推演步数 H
```

1. **高保真惯性期 ($t = 1 \sim 3$)**：
   - 确定性隐状态 $h_t$ 刚从真实的感知观测中获得充分初始化，累积误差极低，重构误差维持在较低水平。
2. **敏感情报发散期 ($t = 4 \sim 7$)**：
   - 由于缺乏外部感知矫正，自回归单步先验预测的微小扰动作为输入再次喂回 GRU，误差呈现指数/超线性增长，离散类别未命中率快速上升。
3. **宏观统计饱和期 ($t \ge 8$)**：
   - 误差不再无限放大，而是收敛至物理动力学系统的遍历先验分布边界（如受阻震荡摆的能量边界），重构 MSE 进入平稳饱和平台。

这印证了在 Dreamer 体系中，潜空间想象步长通常设置在 $H = 15$ 步左右的原因：**既充分挖掘多步价值传播，又规避超长程推演带来的模型幻觉（Model Delusion）与策略过拟合**。
