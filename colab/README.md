# 🎮 Crafter x DreamerV3 100k Steps 训练工具套件 (Google Colab)

本目录为 **Crafter** 环境定制了基于 **DreamerV3 (Danijar Hafner 官方 JAX 实现)** 的 **100k (100,000 steps)** 样本效率训练套件，提供从环境依赖配置、JAX 显存优化、100k 步训练执行、Crafter 22 项成就解锁可视化，到模型与日志一键导出的完整工作流。

---

## 📂 文件清单

| 文件名 | 类型 | 说明 |
| :--- | :--- | :--- |
| [`run_on_colab.py`](file:///e:/code/Crafter/colab/run_on_colab.py) | Python 驱动脚本 | **【本地调用云端核心】单脚本在本地一键运行**，自动调度 Colab GPU、流式输出训练日志并同步权重回本地 |
| [`run_dreamerv3.bat`](file:///e:/code/Crafter/colab/run_dreamerv3.bat) | Windows 批处理 | **Windows 双击即跑跳板**，自动检测 Python 环境并启动云端训练驱动 |
| [`train_crafter_dreamerv3_100k.ipynb`](file:///e:/code/Crafter/colab/train_crafter_dreamerv3_100k.ipynb) | Jupyter Notebook | **Google Colab 网页交互式笔记本**，开箱即用，内置 GPU 检测、训练、实时曲线与成就达成柱状图展示 |
| [`train_dreamerv3.py`](file:///e:/code/Crafter/colab/train_dreamerv3.py) | Python 脚本 | 远端自动化训练工作进程，负责 100k 训练、指标统计与产物压缩 |
| [`run_colab_dreamerv3_100k.ps1`](file:///e:/code/Crafter/colab/run_colab_dreamerv3_100k.ps1) | PowerShell 脚本 | 本地 PowerShell 自动化脚本（基于 WSL 2 + `google-colab-cli`） |

---

## 🚀 使用方式

### 方式一：本地单一脚本直接运行（最省心，本地敲命令调用云端）

你只需在本地终端运行一个脚本，即可实现 **本地调度云端 GPU -> 实时看日志 -> 自动存回本地 -> 自动关机**：

```bash
# 1. 方式 A: 直接使用 Python 执行
python colab/run_on_colab.py

# 2. 方式 B: 在 Windows 资源管理器中直接双击 colab/run_dreamerv3.bat
```

可选参数调节（例如指定使用 A100 GPU、修改步数）：
```bash
python colab/run_on_colab.py --gpu A100 --steps 100000 --size size12m
```

---

### 方式二：通过 Google Colab 网页端运行与断点续训 (推荐)

1. 打开 [Google Colab](https://colab.research.google.com/)。
2. 点击 **文件 (File)** -> **上传笔记本 (Upload notebook)**，选择本地的 [`train_crafter_dreamerv3_100k.ipynb`](file:///e:/code/Crafter/colab/train_crafter_dreamerv3_100k.ipynb)。
3. 检查运行时：**代码执行程序 (Runtime)** -> **更改运行时类型 (Change runtime type)** -> 硬件加速器选择 **T4 GPU**。
4. **支持两种模式**：
   - **模式 A：从零全新训练 (100k 步)**：依次执行各个单元格，默认将完成 100,000 步训练，并在训练完成后自动将成果同步至你的 Google Drive 根目录的 `crafter_dreamerv3_100k` 文件夹。
   - **模式 B：从 Google Drive 继续训练 (Resume Training，如增训至 200k 步)**：
     1. 运行 **Cell 2 (挂载 Google Drive 与恢复检查点)**：脚本会自动识别 Google 云端硬盘中的 [`crafter_dreamerv3_100k`](https://drive.google.com/drive/folders/1e9HPKs4uWtNjp2FiKyucV9CNe-egakLl) 历史存档，并自动恢复至 Colab 本地高速 SSD。
     2. 运行 **Cell 5 (启动训练)**：在参数配置中设置 `TARGET_STEPS = 200000`（或更高），DreamerV3 将自动加载历史权重、优化器与经验回放数据，无缝增量训练至目标总步数。
     3. 训练结束或手动终止时，脚本会自动将最新权重与 `metrics.jsonl` 回写备份到 Google Drive。
   - **后续单元格**：运行可视化单元格，动态绘制累计步数的平均得分、生存时长与 22 项成就解锁率柱状图，并打包下载最新产物。

---

### 方式二：在本地 Windows 终端一键运行 (全自动闭环)

如果你已经在 WSL 2 中配置好了 `google-colab-cli`，可以在 Windows PowerShell 中执行一键训练脚本：

```powershell
# 使用默认配置 (T4 GPU, 100k 步, size12m 模型)
powershell -ExecutionPolicy Bypass -File e:/code/Crafter/colab/run_colab_dreamerv3_100k.ps1

# 或自定义参数 (例如使用更高规格的 A100 GPU)
powershell -ExecutionPolicy Bypass -File e:/code/Crafter/colab/run_colab_dreamerv3_100k.ps1 -Gpu "A100" -Steps 100000 -ModelSize "size12m"
```

**脚本全自动处理流程：**
1. 检查 WSL 内部 Colab CLI 授权状态；
2. 向 Google Colab 申请指定 GPU 实例；
3. 远程配置环境并执行 [`train_dreamerv3.py`](file:///e:/code/Crafter/colab/train_dreamerv3.py)；
4. 训练完成后将 `metrics.jsonl` 及打包的权重压缩包下载至本地 `output/crafter_dreamerv3_100k/`；
5. 自动释放销毁 Colab 算力实例，避免算力时长浪费。

---

## ⚙️ 核心参数与调优说明

| 参数项 | 默认值 | 作用与建议 |
| :--- | :--- | :--- |
| `--run.steps` | `100000` | 严格控制 100k 环境交互步数，用于测试高样本效率场景。 |
| `--configs` | `crafter size12m` | `crafter` 加载官方图像与环境配置；`size12m` 为中型模型（~12M 参数），在 T4 显存和速度上表现最优（可选 `size1m` 或 `size50m`）。 |
| `--task` | `crafter_reward` | 标准 Crafter 任务，包含存活奖励、生命值反馈与成就奖励。 |
| `--run.train_ratio` | `512` | 样本复用比率。Crafter 环境轻量且交互快，高 train ratio 能让世界模型从少量交互中最大化提取动态规律。 |
| `--jax.prealloc` | `False` | 禁用 JAX 预占 90% 显存的策略，按需动态分配，防止在 Colab 单卡上引发 OOM。 |

---

## 📊 100k 步预期表现

在 100k 步基准测试中：
- **经典无模型 RL (如 PPO / DQN)**：由于样本效率瓶颈，100k 步通常只能勉强学会收集木头（Score < 4）。
- **DreamerV3 世界模型**：凭借在隐空间世界模型中的高频想象（Imagination Planning），100k 步即可稳定解锁木镐（`make_wood_pickaxe`）、石镐（`make_stone_pickaxe`）、狩猎奶牛（`collect_sapling`, `eat_cow`）等复合成就，平均得分通常可达到 **8 ~ 12+**。
