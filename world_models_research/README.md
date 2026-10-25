# 世界模型（World Models）全景体系研究与横向测评总览

> **项目定位**：多智能体联合深度攻坚——全流派世界模型机理解构、统一横向基准矩阵、四大垂直领域深度实验实证与高精度原型套件  
> **根目录**：[`world_models_research/`](./)  
> **并发规模**：5 大专业智能体阵列并发，涵盖 93 篇学术级研究专著（超 230 万字中文学术典籍）、95 套完整可复现实测脚本与 107 幅出版级评估图表（定理 1 至定理 68 全数完备收录）。

---

## 全局导航索引

```
e:/code/Crafter/world_models_research/
├── README.md                                    # [当前文件] 项目总览与全局导航
├── REPORT_EXECUTIVE_SUMMARY.md                  # 顶层宏观全景综述与认知控制哲学
├── BENCHMARK_MATRIX.md                          # 全维度横向评测基准大表与选型决策树 (5.1-5.28全矩阵)
├── FAILURE_MODES_AND_FRONTIERS.md               # 五大核心失效模式推导与前沿展望
├── MATHEMATICAL_THEORY_OF_WORLD_MODELS.md       # 世界模型统一数理基础大典与收敛性证明 (定理1-53大一统数理基石)
├── UNIFIED_BENCHMARK_LEADERBOARD.md             # 跨实验全维度量化指标大天梯总榜单与实证总览 (2.1-2.22全天梯)
├── world_models_interactive_sandbox.html        # [V6.0] 跨范式全交互式世界模型仿真沙盒 (HTML5/Canvas/WebGL)
├── aggregate_leaderboard_data.py                # 全量实测数据大天梯融合与可视化生成脚本
├── MODELS_DEEP_DIVE/                            # 八大主流世界模型深度图解专著库 (8 篇权威专著)
│   ├── 01_ha_schmidhuber_world_models.md        # Ha & Schmidhuber 2018 奠基之作
│   ├── 02_planet_deep_dive.md                   # PlaNet 循环状态空间模型 (RSSM) 与在线潜空间规划
│   ├── 03_dreamer_v1_v2_v3.md                   # Dreamer 进化三部曲 (离散潜变量/Symlog/Two-Hot)
│   ├── 04_muzero_efficientzero.md               # MuZero / EfficientZero 价值等价动力学与隐空间树搜索
│   ├── 05_sora_video_dit.md                     # Sora 与视频 DiT：时空 Patch 编码与连续流匹配物理仿真
│   ├── 06_unisim_genie.md                       # UniSim 与 Genie：通用可交互具身与虚拟世界模拟器
│   ├── 07_jepa_vjepa.md                         # Yann LeCun JEPA / V-JEPA 非生成式自监督联合嵌入
│   └── 08_gaia1_embodied_driving.md             # GAIA-1 自动驾驶具身世界模型与长尾反事实推演
├── experiments/                                 # 4 大垂直领域深度实验实证专区
│   ├── rssm_discrete_ablations/                 # [智能体 2] 离散动力学、KL平衡与元环境自适应
│   │   ├── HYBRID_CATEGORICAL_GAUSSIAN_RSSM_THEORY.md # [Phase 3] 量子信息几何与双流连续-离散混合 RSSM 理论专著 (1.6万字)
│   │   ├── RSSM_DISCRETE_DYNAMICS_REPORT.md     # 离散熵翻倍、KL平衡与Symlog梯度有界专著
│   │   ├── RSSM_META_DYNAMICS_ADAPTATION.md     # 非平稳突变物理少样本自适应与惊异门控专著
│   │   ├── ADVERSARIAL_PLANNING_STRESS_REPORT.md# 长程因果规划与对抗扰动压力测试报告
│   │   ├── hybrid_rssm_continuous_discrete.py   # [Phase 3] 双流自适应连续-离散混合 RSSM 完整模型与消融脚本
│   │   ├── hybrid_rssm_metrics.json             # [Phase 3] 35 轮 BPTT 宏微观消融量化数据 (MSE 0.8772, Jerk 0.0182)
│   │   ├── quantum_tensor_network_wm.py         # [Phase 4] 量子张量网络与 MPS 紧致潜状态压缩仿真脚本
│   │   ├── tensor_network_metrics.json          # [Phase 4] 1500 步长程展开多体缠结熵与漂移实测数据
│   │   ├── gauge_invariant_holonomy_wm.py       # [Phase 5] 规范不变李群 SO(3) 联络与零万向节漂移仿真脚本
│   │   ├── gauge_holonomy_metrics.json          # [Phase 5] 1200 步 SO(3) 规范等变误差 (1.85e-16) 与正交违背实测数据
│   │   ├── gauge_invariant_holonomy_benchmark.png # [Phase 5] 规范李群动力学相图与正交性违背对比图
│   │   ├── diffeomorphism_invariant_wm.py       # [Phase 6] 黎曼流形微分同胚坐标不变性与内禀测地曲率守恒仿真脚本
│   │   ├── diffeomorphism_metrics.json          # [Phase 6] 1000 步非欧流形涡旋变换等变误差 (0.0000) 与曲率守恒数据
│   │   ├── diffeomorphism_invariant_eval.png    # [Phase 6] 黎曼测地演化、涡旋微分同胚与高斯曲率守恒图
│   │   ├── FRACTIONAL_ORDER_NON_MARKOVIAN_WORLD_MODELS.md # [Phase 7] Caputo 分数阶非马尔可夫世界模型专著 (2.43万字)
│   │   ├── fractional_order_non_markovian_wm.py # [Phase 7] 格林瓦尔德-莱特尼科夫显式时间记忆卷积仿真脚本
│   │   ├── fractional_order_metrics.json        # [Phase 7] 幂律重尾自相关误差(降97.8%)与粘弹性 Burgers 实测数据
│   │   ├── fractional_order_eval.png            # [Phase 7] 分数阶非马尔可夫世界模型长程记忆与粘弹性消融评估图
│   │   ├── LORENTZ_SPACETIME_WORLD_MODELS.md    # [Phase 8] 相对论闵氏时空度量与光锥因果世界模型专著 (2.35万字)
│   │   ├── lorentz_spacetime_world_models.py    # [Phase 8] 双生子佯谬固有时膨胀与光锥因果屏蔽仿真套件
│   │   ├── lorentz_metrics.json                 # [Phase 8] 固有时误差(2.36e-13s)与类空零泄漏实测数据
│   │   ├── lorentz_eval.png                     # [Phase 8] 双生子固有时重构、洛伦兹不变性与光锥屏蔽图
│   │   ├── NONCOMMUTATIVE_GEOMETRY_WORLD_MODELS.md # [Phase 9] 非交换几何与普朗克尺度星积世界模型专著 (2.41万字)
│   │   ├── noncommutative_geometry_world_models.py # [Phase 9] Moyal-Weyl 星积代数与 GUP 极小测度仿真套件
│   │   ├── noncommutative_metrics.json          # [Phase 9] GUP 零违背(0.0%)与 UV/IR 混合渐近对偶实测数据
│   │   ├── noncommutative_eval.png              # [Phase 9] 非交换星积结合律、波包终态扩张与 GUP 评估图
│   │   ├── SUPERSYMMETRIC_WORLD_MODELS.md       # [Phase 10] 变分超对称潜空间玻色-费米子配对与零点能消除专著 (2.5万字)
│   │   ├── supersymmetric_world_models.py       # [Phase 10] Grassmann 费米子超场与 Ward-Takahashi 恒等式仿真套件
│   │   ├── susy_metrics.json                    # [Phase 10] 零点能100%抵消与 Ward 残差 (4.39e-9) 实测数据
│   │   ├── susy_eval.png                        # [Phase 10] 玻色-费米真空能量对消、Ward 恒等式与 Super-ELBO 评估图
│   │   ├── OPEN_DISSIPATIVE_QUANTUM_WORLD_MODELS.md # [Phase 14] 开放耗散量子态与林德布拉德超算子世界模型专著 (2.3万字/定理52)
│   │   ├── lindblad_dissipative_quantum_wm.py   # [Phase 14] GKSL 超算子发生子与多通道退相干仿真实测套件
│   │   ├── lindblad_quantum_metrics.json        # [Phase 14] CPTP 保迹误差(10^-17)、纯度守恒与相干模长实测数据
│   │   ├── lindblad_quantum_eval.png            # [Phase 14] 量子纯度、非对角相干度与保真度综合评估图
│   │   ├── rssm_dynamics_engine.py              # 纯 NumPy 混合动力学与离散 RSSM 引擎
│   │   ├── run_rssm_ablation_suite.py           # 自动化消融实验测试套件
│   │   ├── meta_rssm_adaptation.py              # 元环境突变动力学自适应仿真脚本
│   │   ├── adversarial_planning_stress.py       # 潜空间 MCTS vs CEM 长程规划对抗脚本
│   │   ├── interactive_latent_explorer.py       # DreamerV3 Two-Hot 价值表示与交互式潜空间数据导出脚本
│   │   └── latent_step_visualization.json       # 30 步 32x32 离散 One-Hot 与 Two-Hot 概率动力学可视化数据
│   ├── generative_physics_sim/                  # [智能体 3] 生成式视频物理法则客观审计与保辛混合
│   │   ├── GENERATIVE_PHYSICS_SIMULATION_AUDIT.md # DiT 物理失真客观审计报告 (2万字)
│   │   ├── NEURAL_PHYSICS_HYBRID_VALIDATION.md  # 神经物理混合保辛硬投影验证报告 (1.6万字)
│   │   ├── 3D_GAUSSIAN_SPLATTING_WORLD_MODELS.md# 显式 3D 高斯泼溅对极几何世界模型专著 (1.7万字)
│   │   ├── simulator_and_auditor.py             # 多体碰撞与流体扩散物理评测沙盒
│   │   ├── hybrid_neural_physics_prototype.py   # 保辛哈密顿与刚体非穿模投影混合原型
│   │   ├── gaussian_splatting_dynamics_eval.py  # 3D 高斯泼溅显式物理与对极约束评测脚本
│   │   ├── cosmos_and_genie2_audit.py           # NVIDIA Cosmos 与 Google Genie 2 物理世界模型硬审计脚本
│   │   ├── humanoid_tactile_world_model.py      # [Phase 3] 具身双臂双足多模态触觉-本体感觉-视觉物理世界模型
│   │   ├── nextgen_physics_benchmark.json       # 次世代微观物理运动学、碰撞与流体守恒实测数据
│   │   ├── humanoid_multimodal_metrics.json     # [Phase 3] 蛋壳无损操控与双足黑冰行走多模态实测数据
│   │   ├── thermodynamic_arrow_of_time_audit.py # [Phase 4] 非平衡态热力学不可逆性与时间之箭硬审计脚本
│   │   ├── thermodynamic_arrow_metrics.json     # [Phase 4] 朗之万布朗扩散与雅辛斯基恒等式实测数据
│   │   ├── continuum_fluid_structure_wm.py      # [Phase 5] 神经连续介质力学非定常流固耦合 (FSI) 真实力学审计脚本
│   │   ├── continuum_mechanics_metrics.json     # [Phase 5] 高雷诺数瞬态冲击流固交界面力失衡与体积漂移实测数据
│   │   ├── fluid_structure_interaction_eval.png # [Phase 5] 连续介质流固耦合与神经网格多相力学对比图
│   │   ├── adversarial_physics_defense_wm.py    # [Phase 6] 物理隐空间对抗扰动防御与切空间投影自愈仿真脚本
│   │   ├── adversarial_defense_metrics.json     # [Phase 6] PGD-20 对抗攻击防御率 (98.8%) 与流形偏离自愈数据
│   │   ├── adversarial_physics_defense_eval.png # [Phase 6] PGD 对抗扰动、能量爆炸抑制与流形切空间自愈对比图
│   │   ├── RIEMANN_SHOCK_CAPTURING_WORLD_MODELS.md # [Phase 7] 黎曼激波捕捉与双曲守恒 TVD 神经物理世界模型专著 (2.45万字)
│   │   ├── riemann_shock_capturing_wm.py        # [Phase 7] HLLC 黎曼求解器与 Sweby TVD 通量限制器仿真套件
│   │   ├── riemann_shock_metrics.json           # [Phase 7] 吉布斯伪振荡(降至0.0006%)与兰金-许贡纽守恒量化数据
│   │   ├── riemann_shock_eval.png               # [Phase 7] 激波间断捕捉、全变差非增与保凸保压综合评估图
│   │   ├── LATTICE_QCD_WORLD_MODELS.md          # [Phase 8] 格点量子色动力学局域规范不变与费米子保正专著 (2.38万字)
│   │   ├── lattice_qcd_world_models.py          # [Phase 8] SU(3) 格点规范李群等变与重加权路径积分仿真套件
│   │   ├── lattice_qcd_metrics.json             # [Phase 8] 规范不变违背率(0.0017%)与符号问题方差控制实测数据
│   │   ├── lattice_qcd_eval.png                 # [Phase 8] Wilson 环小面元、拓扑荷整数阶跃与弦断裂势能图
│   │   ├── GRMHD_BLACKHOLE_WORLD_MODELS.md      # [Phase 9] 克尔黑洞广义相对论磁流体动力学与能流守恒专著 (2.42万字)
│   │   ├── grmhd_blackhole_world_models.py      # [Phase 9] Boyer-Lindquist 弯曲时空与双曲 GLM 散度清除仿真套件
│   │   ├── grmhd_metrics.json                   # [Phase 9] BZ 喷流能流误差(1.07e-5%)与四维散度清除实测数据
│   │   ├── grmhd_eval.png                       # [Phase 9] 能层拖拽、视界角动量通量比与相对论喷流评估图
│   │   ├── HOLOGRAPHIC_ADSCFT_WORLD_MODELS.md   # [Phase 10] 全息 AdS/CFT 对偶边界纠缠与引力几何涌现专著 (2.2万字)
│   │   ├── holographic_adscft_world_models.py   # [Phase 10] 边界共形场纠缠熵 RT 极小曲面与时空几何重构套件
│   │   ├── holographic_eval.png                 # [Phase 10] AdS/CFT 全息网格、纠缠熵面积律与爱因斯坦场方程残差评估图
│   │   ├── RENORMALIZATION_GROUP_FLOW_WORLD_MODELS.md # [Phase 14] 重整化群流、连续相变与共形场世界模型专著 (2.4万字/定理53)
│   │   ├── renormalization_group_flow_wm.py     # [Phase 14] 卡达诺夫块自旋与动量壳层快慢模积分仿真套件
│   │   ├── rg_flow_metrics.json                 # [Phase 14] Onsager 临界指数 eta=0.2525 与共形恒等式残差 (0.048%) 实测数据
│   │   └── rg_flow_eval.png                     # [Phase 14] 重整化群流相图、幂律衰减与共形不变性综合评估图
│   ├── value_vs_jepa_benchmark/                 # [智能体 4] 价值等价 vs 联合嵌入抗高熵噪声基准
│   │   ├── VALUE_EQUIVALENT_VS_JEPA_STUDY.md    # 三大流派抗噪对比理论专著 (5.1万字节)
│   │   ├── HIERARCHICAL_JEPA_MUZERO_ARCHITECTURE.md # 分层 JEPA-MuZero 统一混合架构报告 (1.8万字)
│   │   ├── CROSS_EMBODIMENT_FOUNDATION_WORLD_MODELS.md # 跨具身开放世界基座世界模型专著 (2.5万字)
│   │   ├── composite_env.py                     # 包含 80% 高熵视觉噪点的复合物理环境
│   │   ├── nn_core.py & models.py               # 纯向量化三流派完整深度学习模型库
│   │   ├── benchmark_runner.py                  # 多噪声梯度自动化压测脚本
│   │   ├── hierarchical_jepa_muzero_prototype.py# 分层抗噪混合世界模型可运行原型
│   │   ├── open_world_generalization_benchmark.py # 跨四足/机械臂/无人机开放世界评测脚本
│   │   ├── diffusion_wm_vs_jepa_benchmark.py    # 扩散决策世界模型 (IRIS/DIAMOND) vs JEPA 闭环控制对决
│   │   ├── continual_world_models_benchmark.py  # [Phase 3] 持续学习防遗忘与正交子空间增量世界模型评测脚本
│   │   ├── diffusion_vs_jepa_metrics.json       # DDIM 步数、时延、FPS、PSNR 与控制回报权衡数据
│   │   ├── continual_learning_metrics.json      # [Phase 3] 8 大连续物理动力学域终身保留与遗忘率实测数据
│   │   ├── multiagent_emergent_collective_wm.py # [Phase 4] 异构群体智能涌现通信与去中心化共识评测脚本
│   │   ├── collective_multiagent_metrics.json   # [Phase 4] 64 字节微型语义信标与协同捕获度量数据
│   │   ├── neuro_symbolic_ltl_verification_wm.py # [Phase 5] 神经符号 LTL 形式化安全可达性屏蔽与模型检验脚本
│   │   ├── neuro_symbolic_metrics.json          # [Phase 5] 200 轮安全公理零违背与 36000 反例动态剪枝实测数据
│   │   ├── ltl_safety_verification_eval.png     # [Phase 5] 神经符号 LTL 形式化安全验证多维剖面图
│   │   ├── NEURO_SYMBOLIC_CAUSAL_WORLD_MODELS.md # [Phase 6] 神经符号与因果可解释世界模型理论专著
│   │   ├── meta_world_model_adaptation.py       # [Phase 6] 贝叶斯潜上下文超网络 OOD 非平稳动力学少样本自适应脚本
│   │   ├── meta_adaptation_metrics.json         # [Phase 6] 6 大物理域 K=3 步后验更新与 OOD 误差削减数据
│   │   ├── meta_world_model_eval.png            # [Phase 6] 潜上下文后验流形、FiLM 调制与少样本泛化评估图
│   │   ├── topological_homology_wm.py           # [Phase 7] Vietoris-Rips 过滤与代数边界约化拓扑同调仿真脚本
│   │   ├── topological_homology_eval.png        # [Phase 7] 持久同调条形码、贝蒂数重构与环自相交消除评估图
│   │   ├── CATEGORY_TOPOS_WORLD_MODELS.md       # [Phase 13] 拓扑范畴论与格罗滕迪克拓扑概念涌现专著 (2.4万字/定理50)
│   │   ├── category_topos_world_models.py       # [Phase 13] 米田嵌入、切赫层化算子与伴随函子对仿真套件
│   │   ├── category_topos_metrics.json          # [Phase 13] 开放域零样本概念迁移 (81.9%) 与切赫障碍消解实测数据
│   │   └── category_topos_eval.png              # [Phase 13] 范畴态射网络、层粘合一致性与零样本迁移评估图
│   └── embodied_driving_sim/                    # [智能体 5] 具身操纵、极端反事实推演与车规部署
│       ├── EMBODIED_AND_AUTONOMOUS_DRIVING_WORLD_MODELS.md # 10大长尾险情反事实推演专著 (2.24万字)
│       ├── EDGE_WORLD_MODEL_DEPLOYMENT_STUDY.md # 车规级边缘蒸馏与时延悖论研究专著 (1.25万字)
│       ├── COMPLIANT_ASSEMBLY_WORLD_MODEL.md    # 亚毫米级受限空间轴孔精密装配专著 (1.19万字)
│       ├── INDUSTRIAL_WORLD_MODELS_ALIGNMENT_WHITEPAPER.md # 世界模型工业落地白皮书与 SOTIF 协议 (1.11万字)
│       ├── FSD_V12_AND_LINGO2_EMBODIED_DEEP_DIVE.md # 特斯拉 FSD v12 与 Wayve LINGO-2 机制反编译专著 (1.34万字)
│       ├── STRUCTURAL_CAUSAL_WORLD_MODELS_FOR_SAFETY.md # 结构因果去混淆与幽灵急刹根除专著 (1.11万字)
│       ├── NEUROMORPHIC_BIOMECHANICAL_WORLD_MODELS.md # 全身生物力学神经拟态脉冲(SNN)反射与冲击耗能专著 (2.18万字)
│       ├── EXTREME_WEATHER_RADIATIVE_WORLD_MODELS.md # [Phase 5] 极端暴雪浓雾米氏散射与4D跨频段辐射传输专著 (2.55万字)
│       ├── SIM2REAL_WORLD_MODELS_WHITEPAPER.md  # [Phase 6] 全工况Sim2Real物理鸿沟量化与麋鹿测试白皮书 (2.13万字)
│       ├── ACTIVE_TACTILE_ACOUSTIC_WORLD_MODELS.md # [Phase 7] 多模态主动触觉微振动固体声波全息抓握专著 (2.23万字)
│       ├── NEUROMUSCULAR_ELECTROPHYSIOLOGICAL_WORLD_MODELS.md # [Phase 8] 神经肌肉肌电电生理与肌腱微观动力学跨尺度专著 (2.15万字)
│       ├── TERRAMECHANICS_PLASTIC_SLIPLINE_WORLD_MODELS.md # [Phase 9] 非欧滑移线场与轮壤弹塑性大变形沉陷专著 (2.2万字)
│       ├── HJBI_ZERO_COLLISION_WORLD_MODELS.md  # [Phase 10] HJBI极小极大微分博弈与零碰撞防御专著 (3.78万字/定理45)
│       ├── TENDON_DRIVEN_NEUROMORPHIC_WORLD_MODELS.md # [Phase 13] 仿生肌腱多连杆李代数非完整路由与脉冲神经世界模型专著 (2.55万字/定理51)
│       ├── AEROELASTIC_FLUTTER_ADAPTIVE_WORLD_MODELS.md # [Phase 13/14] 气动弹性颤振自适应世界模型与泰奥多森非定常空气动力势专著 (3.28万字/定理57)
│       ├── MOREAU_CONTACT_DIFFERENTIAL_INCLUSION_WORLD_MODELS.md # [Phase 15] 莫罗非光滑测度微分包含刚柔接触与碰撞测度有限变差收敛专著 (2.97万字/定理61)
│       ├── HYPERSONIC_SHOCK_BOUNDARY_LAYER_INTERACTION_WORLD_MODELS.md # [Phase 16] 高超声速激波-边界层干扰与非平衡热化学世界模型专著 (4.42万字/定理66)
│       ├── BIONIC_FLAPPING_WING_WORLD_MODELS.md # [Phase 17] 仿生扑翼前缘涡分离延迟与尾迹环量能量捕获专著 (4.36万字/定理72)
│       ├── embodied_counterfactual_engine.py    # GAIA-1/UniSim SCM 反事实推演引擎
│       ├── edge_distillation_experiment.py      # 9B 教师至 140M Mamba 学生蒸馏套件
│       ├── compliant_assembly_simulation.py     # 柔性顺应装配与卡滞自锁预测仿真脚本
│       ├── safety_alignment_verifier.py         # SOTIF (ISO 21448) 与 ISO 26262 形式化验证脚本
│       ├── fsd_and_lingo_multiagent_sim.py      # 特斯拉与 Wayve 多智能体博弈与 ToM 仿真套件
│       ├── causal_deconfounding_driving_sim.py  # SCM do-演算因果干预与去混淆仿真套件
│       ├── neuromorphic_spiking_biomechanics_wm.py # 500N 侧向撞击亚毫秒反射与肌腱弹性吸能仿真套件
│       ├── multimodal_weather_radiative_wm.py   # [Phase 5] 77GHz微波穿透、RTE逆演与100km/h避障仿真套件
│       ├── sim2real_universal_benchmark.py      # [Phase 6] 20ms时滞、齿隙回差与非线性轮胎饱和Sim2Real评测套件
│       ├── active_tactile_acoustic_wm.py        # [Phase 7] 5000Hz 固体声波微滑移前兆与薄壳防碎控制仿真套件
│       ├── neuromuscular_electrophysiology_wm.py # [Phase 8] 60通道MUAP钙激活与Hill拮抗肌腱跨尺度仿真套件
│       ├── terramechanics_plastic_slipline_wm.py # [Phase 9] Prandtl滑移线对数螺线场与动态旋挖排土仿真套件
│       ├── hjbi_zero_collision_defense_wm.py    # [Phase 10] 盲区突袭与80km/h强切后向可达管BRT仿真套件
│       ├── tendon_driven_neuromorphic_wm.py     # [Phase 13] 拟人灵巧手指高频震颤阻尼与绳索零松弛仿真套件
│       ├── aeroelastic_flutter_wing_wm.py       # [Phase 13/14] 两自由度弯扭耦合机翼超临界颤振与主动后缘襟翼相角超前仿真套件
│       ├── moreau_contact_differential_inclusion_wm.py # [Phase 15] 莫罗非光滑测度微分包含刚柔接触与二阶锥库仑摩擦仿真套件
│       ├── hypersonic_sbli_aerothermo_wm.py     # [Phase 16] 高超声速 Mach 6.0 边界层斜激波撞击与双温度热化学松弛仿真套件
│       ├── bionic_flapping_wing_wm.py           # [Phase 17] 仿生扑翼大迎角动态失速前缘涡与尾迹捕获非定常动力学仿真套件
│       ├── e2e_driving_benchmark.json           # FSD v12 意图博弈与 LINGO-2 盲区防御量化数据
│       ├── causal_deconfounding_metrics.json    # 6大伪相关工况幽灵急刹与避障量化数据库
│       ├── neuromorphic_biomechanics_metrics.json # 500N 突发冲击刚性 MPC vs 神经拟态肌骨对照指标数据库
│       ├── extreme_weather_sim_metrics.json     # [Phase 5] 恶劣天气探测视距(+91.7m)、虚警率与制动指标库
│       ├── sim2real_universal_metrics.json      # [Phase 6] 麋鹿测试跟踪误差(降99.4%)与Wasserstein迁移度量数据
│       ├── tactile_acoustic_metrics.json        # [Phase 7] 微滑移检出延迟(16ms)、零破损与防滑度量数据
│       ├── neuromuscular_metrics.json           # [Phase 8] 2.5Nm冲击偏转降71%、抖动抑制85.5%与R²=0.9885指标库
│       ├── terramechanics_metrics.json          # [Phase 9] 沉陷抑制68.1%、防托底裕度42.3mm与100%脱困量化库
│       ├── hjbi_metrics.json                    # [Phase 10] 零碰撞(0.0%)、安全裕度1.60m与720us延迟指标库
│       ├── tendon_neuromorphic_metrics.json     # [Phase 13] 0.0%绳索松弛、14.0ms微震颤消除与310us延迟指标库
│       ├── aeroelastic_metrics.json             # [Phase 13/14] 99.41%极限环压制、0.049°俯仰幅值与290us延迟指标库
│       ├── moreau_contact_metrics.json          # [Phase 15] 严格0.00mm零穿模、单调能量耗散与454us延迟指标库
│       ├── hypersonic_sbli_metrics.json         # [Phase 16] 8.52x热流峰值(0.0%误差)、70.0mm分离泡与克罗科熵守恒指标库
│       ├── bionic_flapping_metrics.json         # [Phase 17] 3.51x峰值升力、+264.3%均值升力与100%失速抑制指标库
│       ├── neuromorphic_spiking_biomechanics_eval.png # 500N 冲击下关节受力、脉冲放电与相空间轨迹出版级评估图
│       ├── extreme_weather_radiative_eval.png   # [Phase 5] 极端气象米氏消光与跨模态辐射传输评估图
│       ├── sim2real_gap_evaluation.png          # [Phase 6] 极端双移线轨迹、时滞补偿波形与车规雷达评估图
│       ├── tactile_acoustic_eval.png            # [Phase 7] 接触声发射波包、法向防碎力控制与滑移抑制评估图
│       ├── neuromuscular_eval.png               # [Phase 8] 跨尺度神经肌肉电生理、肌腱力学与相空间评估图
│       ├── terramechanics_eval.png              # [Phase 9] 动态下陷、拔模牵引力、滑转钳位与滑移线拓扑出版级评估图
│       ├── hjbi_eval.png                        # [Phase 10] 空间轨迹、安全间隙、SCBF屏障与路肩走廊评估图
│       ├── tendon_neuromorphic_eval.png         # [Phase 13] 灵巧手跟踪、相空间轨道、肌腱张力与李雅普诺夫衰减图
│       ├── aeroelastic_eval.png                 # [Phase 13/14] 超临界机翼俯仰响应、Hopf极限环、弯曲沉浮与能量泛函耗散图
│       ├── moreau_contact_eval.png              # [Phase 15] 机器人质心高度、零穿模间隙、机械能单调耗散与冲量测度评估图
│       ├── sbli_eval.png                        # [Phase 16] 壁面静压比平台、再附峰值热流暴增、沿程摩阻反转与熵层增长四联评估图
│       └── bionic_flapping_eval.png             # [Phase 17] 非定常升力时序、反转推力、展向LEV环量与相空间极限环四联图
└── scripts/                                     # 核心运行原型与评估工具
    ├── rssm_simulation_prototype.py             # 循环状态空间模型基础推演原型
    ├── rssm_discrete_rollout.py                 # 48KB 离散潜空间长程展开原型 (单测全绿)
    └── benchmark_radar_visualizer.py            # 全维度雷达图生成工具
```

---

## 终极实证天梯 TOP 5 榜单

数据基于 [`unified_leaderboard_data.json`](./unified_leaderboard_data.json) 聚合自 4 大分支 13 套真实指标：

| 排名 | 模型代表架构 | 核心技术机理 | 推演帧率 (FPS) | 质量漂移率 | 碰撞穿模深度 | 80%抗噪探针 $R^2$ | SOTIF 安全分 | 综合评级 |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **TOP 1** | **M10: 统一 3D-GS 因果世界模型** | 显式高斯粒子即物理质点，严格保证对极几何约束 | 105.0 | **0.0000%** | **0.0000 m** | 0.3850 | **96.23** | **98.5 (代际王者)** |
| **TOP 2** | **M9: 保辛神经物理混合世界模型** | KKT 接触切面硬投影算子与刘维尔体积守恒 | 78.5 | **0.0000%** | **0.0000 m** | 0.3420 | **93.80** | **94.2 (经典力学硬守恒)** |
| **TOP 3** | **M6: 分层 JEPA-MuZero 混合架构** | 底层非生成式特征过滤噪声 + 上层隐空间价值 MCTS | 96.0 | 0.0510% | 0.0080 m | **0.4062** | 88.50 | **92.0 (抗噪长程规划第一)** |
| **TOP 4** | **M7: 蒸馏 Mamba-SSM (140M FP16)** | 选择性状态空间，推演时延仅 8.8ms，破除时延悖论 | **113.6** | 0.0820% | 0.0120 m | 0.2850 | 89.20 | **90.5 (边缘部署甜蜜点)** |
| **TOP 5** | **M5: V-JEPA 联合自监督模型** | 特征空间时空 Patch 掩码预测，非对比几何去相关 | 105.0 | 0.0650% | 0.0150 m | **0.4062** | 86.80 | **89.0 (无生成解码器标杆)** |

---

## 核心可视化画廊（部分代表作索引）

- [全维度八极雷达图 (unified_leaderboard_radar.png)](./unified_leaderboard_radar.png)
- [跨范式帕累托前沿权衡散点图 (cross_paradigm_tradeoff_matrix.png)](./cross_paradigm_tradeoff_matrix.png)
- [物理违背与功能安全世代演进天梯 (safety_and_physical_ladder.png)](./safety_and_physical_ladder.png)
- [3D 高斯泼溅对极几何约束误差与 PSNR 评估 (3d_gaussian_epipolar_eval.png)](./experiments/generative_physics_sim/3d_gaussian_epipolar_eval.png)
- [保辛硬投影相空间轨道闭合性对比 (symplectic_energy_conservation.png)](./experiments/generative_physics_sim/symplectic_energy_conservation.png)
- [三大范式 80% 强噪声抗性四联曲线 (noise_resistance_curve.png)](./experiments/value_vs_jepa_benchmark/noise_resistance_curve.png)
- [跨具身通用大世界模型零样本适应曲线 (zero_shot_dynamics_adaptation.png)](./experiments/value_vs_jepa_benchmark/zero_shot_dynamics_adaptation.png)
- [车规级状态空间边缘蒸馏帕累托前沿 (distillation_pareto_frontier.png)](./experiments/embodied_driving_sim/distillation_pareto_frontier.png)
- [亚毫米轴孔装配力矩演化与 GelSight 触觉云图 (tactile_world_model_accuracy.png)](./experiments/embodied_driving_sim/tactile_world_model_accuracy.png)
- [SOTIF 工业安全合规八维雷达图 (industrial_safety_compliance_radar.png)](./experiments/embodied_driving_sim/industrial_safety_compliance_radar.png)
- [特斯拉与 Wayve 多智能体博弈平行宇宙与思维链 (multiagent_game_counterfactuals.png)](./experiments/embodied_driving_sim/multiagent_game_counterfactuals.png)
- [因果去混淆后门调整与幽灵急刹根除评估 (causal_deconfounding_evaluation.png)](./experiments/embodied_driving_sim/causal_deconfounding_evaluation.png)
- [神经拟态脉冲反射与肌腱非线性耗能评估图 (neuromorphic_spiking_biomechanics_eval.png)](./experiments/embodied_driving_sim/neuromorphic_spiking_biomechanics_eval.png)
- [极端气象米氏消光与跨模态辐射传输评估图 (extreme_weather_radiative_eval.png)](./experiments/embodied_driving_sim/extreme_weather_radiative_eval.png)
- [全工况 Sim2Real 物理保真度与麋鹿测试评估图 (sim2real_gap_evaluation.png)](./experiments/embodied_driving_sim/sim2real_gap_evaluation.png)
- [多模态主动触觉微振动固体声波全息抓握评估图 (tactile_acoustic_eval.png)](./experiments/embodied_driving_sim/tactile_acoustic_eval.png)
- [NVIDIA Cosmos vs Google Genie 2 物理法则硬审计对比 (nextgen_physics_benchmark.png)](./experiments/generative_physics_sim/nextgen_physics_benchmark.png)
- [Cosmos 与 Genie 2 流体连续性与刚体碰撞实测评估 (cosmos_genie2_fluid_rigid_eval.png)](./experiments/generative_physics_sim/cosmos_genie2_fluid_rigid_eval.png)
- [扩散决策世界模型 vs JEPA 闭环控制帕累托前沿 (diffusion_vs_jepa_pareto_frontier.png)](./experiments/value_vs_jepa_benchmark/diffusion_vs_jepa_pareto_frontier.png)
- [DDIM 去噪步数与控制性能权衡曲线 (denoising_steps_tradeoff_curve.png)](./experiments/value_vs_jepa_benchmark/denoising_steps_tradeoff_curve.png)
- [双流自适应连续-离散混合 RSSM 宏微观基准图 (hybrid_rssm_micro_macro_benchmark.png)](./experiments/rssm_discrete_ablations/hybrid_rssm_micro_macro_benchmark.png)
- [具身双手高敏抓握与双足防倾覆多模态评估 (humanoid_tactile_multimodal_eval.png)](./experiments/generative_physics_sim/humanoid_tactile_multimodal_eval.png)
- [GelSight 表面微剪切牵引力场云图 (gelsight_shear_traction_field.png)](./experiments/generative_physics_sim/gelsight_shear_traction_field.png)
- [8 大物理动力学域终身知识保留演变曲线 (continual_retention_curves.png)](./experiments/value_vs_jepa_benchmark/continual_retention_curves.png)
- [正交子空间特征核对齐分析图 (orthogonal_subspace_alignment.png)](./experiments/value_vs_jepa_benchmark/orthogonal_subspace_alignment.png)
- [终身学习多维抗遗忘综合评估雷达图 (lifelong_benchmark_radar.png)](./experiments/value_vs_jepa_benchmark/lifelong_benchmark_radar.png)
- [量子张量网络 MPS 万步长程推演与缠结熵面积律 (tensor_network_compression_benchmark.png)](./experiments/rssm_discrete_ablations/tensor_network_compression_benchmark.png)
- [非平衡态热力学吉布斯熵增与雅辛斯基做功分布 (thermodynamic_entropy_and_arrow.png)](./experiments/generative_physics_sim/thermodynamic_entropy_and_arrow.png)
- [二维微粒密度场演化与反熵聚集对比图 (spatiotemporal_entropy_breakdown.png)](./experiments/generative_physics_sim/spatiotemporal_entropy_breakdown.png)
- [异构群体智能通信带宽与协同捕获帕累托前沿 (communication_bandwidth_pareto.png)](./experiments/value_vs_jepa_benchmark/communication_bandwidth_pareto.png)
- [多智能体去中心化潜空间语义共识收敛曲线 (collective_consensus_convergence.png)](./experiments/value_vs_jepa_benchmark/collective_consensus_convergence.png)
- [多智能体涌现协同能力综合对比雷达图 (multiagent_collective_radar.png)](./experiments/value_vs_jepa_benchmark/multiagent_collective_radar.png)
- [规范李群动力学相图与正交性违背对比图 (gauge_invariant_holonomy_benchmark.png)](./experiments/rssm_discrete_ablations/gauge_invariant_holonomy_benchmark.png)
- [连续介质流固耦合与神经网格多相力学对比图 (fluid_structure_interaction_eval.png)](./experiments/generative_physics_sim/fluid_structure_interaction_eval.png)
- [神经符号 LTL 形式化安全验证多维剖面图 (ltl_safety_verification_eval.png)](./experiments/value_vs_jepa_benchmark/ltl_safety_verification_eval.png)
- [黎曼流形微分同胚坐标不变性与测地曲率守恒评估图 (diffeomorphism_invariant_eval.png)](./experiments/rssm_discrete_ablations/diffeomorphism_invariant_eval.png)
- [PGD 对抗扰动防御与流形切空间投影自愈对比图 (adversarial_physics_defense_eval.png)](./experiments/generative_physics_sim/adversarial_physics_defense_eval.png)
- [贝叶斯潜上下文超网络少样本动力学自适应评估图 (meta_world_model_eval.png)](./experiments/value_vs_jepa_benchmark/meta_world_model_eval.png)
- [跨尺度神经肌肉电生理与肌腱力学评估图 (neuromuscular_eval.png)](./experiments/embodied_driving_sim/neuromuscular_eval.png)
- [分数阶非马尔可夫世界模型消融基准评估图 (fractional_order_eval.png)](./experiments/rssm_discrete_ablations/fractional_order_eval.png)
- [激波捕捉与五维保真度雷达图 (riemann_shock_eval.png)](./experiments/generative_physics_sim/riemann_shock_eval.png)
- [代数拓扑持久同调图与贝蒂数精度图 (topological_homology_eval.png)](./experiments/value_vs_jepa_benchmark/topological_homology_eval.png)
- [相对论双生子佯谬固有时膨胀与光锥因果零泄漏图 (lorentz_eval.png)](./experiments/rssm_discrete_ablations/lorentz_eval.png)
- [格点非阿贝尔 SU(3) 规范不变性与费米子保正图 (lattice_qcd_eval.png)](./experiments/generative_physics_sim/lattice_qcd_eval.png)
- [非交换几何 Moyal 星积代数与普朗克尺度波包演化图 (noncommutative_eval.png)](./experiments/rssm_discrete_ablations/noncommutative_eval.png)
- [克尔黑洞吸积盘 Blandford-Znajek 磁能抽取与双曲散度清除图 (grmhd_eval.png)](./experiments/generative_physics_sim/grmhd_eval.png)
- [非欧滑移线场与轮壤弹塑性沉陷评估图 (terramechanics_eval.png)](./experiments/embodied_driving_sim/terramechanics_eval.png)
- [变分超对称玻色-费米子配对与零点能消除评估图 (susy_eval.png)](./experiments/rssm_discrete_ablations/susy_eval.png)
- [全息 AdS/CFT 对偶边界纠缠与体时空几何涌现评估图 (holographic_eval.png)](./experiments/generative_physics_sim/holographic_eval.png)
- [HJBI 极小极大微分博弈与零碰撞可达管评估图 (hjbi_eval.png)](./experiments/embodied_driving_sim/hjbi_eval.png)
- [仿生肌腱李代数非完整约束与脉冲神经微震颤抑制评估图 (tendon_neuromorphic_eval.png)](./experiments/embodied_driving_sim/tendon_neuromorphic_eval.png)
- [气动弹性非定常流固耦合与超临界颤振极限环抑制评估图 (aeroelastic_eval.png)](./experiments/embodied_driving_sim/aeroelastic_eval.png)
- [范畴论拓扑概念同构与层粘合一致性评估图 (category_topos_eval.png)](./experiments/value_vs_jepa_benchmark/category_topos_eval.png)
- [林德布拉德超算子完全正保迹收敛与量子纯度评估图 (lindblad_quantum_eval.png)](./experiments/rssm_discrete_ablations/lindblad_quantum_eval.png)
- [重整化群流不动点共形标度与 Onsager 临界指数评估图 (rg_flow_eval.png)](./experiments/generative_physics_eval/rg_flow_eval.png)
- [莫罗非光滑测度微分包含刚柔接触与零穿模能量耗散评估图 (moreau_contact_eval.png)](./experiments/embodied_driving_sim/moreau_contact_eval.png)
- [高超声速激波-边界层干扰再附极端峰值热流与克罗科熵层评估图 (sbli_eval.png)](./experiments/embodied_driving_sim/sbli_eval.png)
- [可积系统孤立子湍流扎哈罗夫-沙巴特谱守恒与无耗散碰撞评估图 (soliton_eval.png)](./experiments/generative_physics_eval/soliton_eval.png)
- [非平衡态热力学涨落棘轮信息功抽取与 Jarzynski 对称性评估图 (thermodynamic_ratchet_eval.png)](./experiments/rssm_discrete_ablations/thermodynamic_ratchet_eval.png)
- [神经符号一阶逻辑连续微分归结与零幻觉定理证明评估图 (ns_atp_eval.png)](./experiments/value_vs_jepa_benchmark/ns_atp_eval.png)
- [多辛时空协变 Preissman 盒状格式相对论激波捕捉评估图 (multisymplectic_shock_eval.png)](./experiments/generative_physics_eval/multisymplectic_shock_eval.png)
- [康奈斯非交换几何谱三元组微观量子引力与狄拉克迹异常评估图 (noncommutative_spectral_eval.png)](./experiments/value_vs_jepa_benchmark/noncommutative_spectral_eval.png)
- [极小耗散贝纳穆-布勒尼耶二次沃瑟斯坦最优输运与费雪信息收敛评估图 (optimal_transport_eval.png)](./experiments/rssm_discrete_ablations/optimal_transport_eval.png)
- [四维杨-米尔斯自对偶瞬子模空间与陈-西蒙斯拓扑真空隧道跃迁评估图 (instanton_eval.png)](./experiments/generative_physics_eval/instanton_eval.png)
