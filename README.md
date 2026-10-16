# Crafter：本地人玩版

Crafter 是一个用于强化学习研究的二维开放世界生存游戏，也可以直接用键盘游玩。你需要在随机生成的世界里采集资源、寻找食物和水、睡觉恢复体力、制作工具，并抵御怪物。目标是在每局中尽可能解锁更多成就，没有必须完成的单一通关任务。

本项目基于 [Danijar Hafner 的官方 Crafter](https://github.com/danijar/crafter)，保留官方游戏规则，增加 Windows 一键启动入口。英文原文见 [README.en.md](README.en.md)。

![Crafter 地形示例](media/terrain.png)

## 一键启动（Windows）

**双击根目录的 `play.bat`。** 本机环境准备好后，会打开一个 720 × 720 的游戏窗口。先点击游戏窗口获得键盘焦点，再开始操作。

**新手推荐双击 `play_beginner.bat`。** 它自动以 `--wait True` 启动，不按键时世界暂停，可以慢慢熟悉操作；睡觉期间世界仍会推进。也可以在 PowerShell 中运行 `.\play_beginner.bat`。

首次启动会自动创建项目专用的 `.venv` 并安装依赖，需要联网；后续启动复用环境，不再重复安装。游戏本身在本地运行，不需要账号、服务器或 GPU。不需要手动激活虚拟环境，也不会修改其他项目的 Python 环境。

新机器需要先安装以下任意一种工具：

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**：启动脚本会通过 uv 自动准备 Python 3.11。
- **[Python 3.11](https://www.python.org/downloads/)**：安装时勾选 “Add python.exe to PATH”。也支持 Python 3.10 / 3.12。

脚本使用固定的游戏依赖版本，采用 Python 3.10–3.12；如果只有 Python 3.13 / 3.14，请安装 uv 或上述 Python 版本。

在 PowerShell 中也可以运行：

```powershell
.\play.bat
```

默认每秒推进 5 个游戏步，**不按键时世界也会继续运行**，食物、水分和体力会消耗。死亡后自动开始新一局；按 `Esc` 或关闭游戏窗口退出。

## 操作按键

| 按键 | 功能 |
| --- | --- |
| `W / A / S / D` | 上 / 左 / 下 / 右移动，同时改变朝向 |
| `Space`（空格） | 与面前一格交互：砍树、挖矿、喝水、攻击或吃成熟作物 |
| `Tab` | 睡觉，直到体力恢复；受到伤害会醒来 |
| `T` | 在面前放置工作台，消耗 2 木材 |
| `R` | 在面前放置石块，消耗 1 石头，可用于搭桥 |
| `F` | 在面前放置熔炉，消耗 4 石头 |
| `P` | 在面前的草地种植，消耗 1 树苗 |
| `1 / 2 / 3` | 制作木镐 / 石镐 / 铁镐 |
| `4 / 5 / 6` | 制作木剑 / 石剑 / 铁剑 |
| `Esc` | 退出游戏 |

长按可以重复移动或交互。采集、攻击、放置都作用于**角色朝向的一格**；先按方向键面对目标，再按空格。工具放在背包里便会自动使用，无需切换装备。

窗口下方用图标和数字显示生命、食物、水分、体力以及资源和工具数量。解锁成就和本局结束信息会显示在启动时的控制台中。

## 新手路线

1. 找到树，面对树按空格收集木材。至少准备 3 木材：2 个用于工作台，1 个用于木镐。
2. 面对空地按 `T` 放工作台，站在它附近按 `1` 制作木镐。
3. 有木镐后可以采集石头和煤。采集石头，再在工作台附近按 `2` 制作石镐。
4. 有石镐后采集铁；收集煤、铁、木材，并用 4 石头放置熔炉。
5. 在工作台和熔炉附近按 `3` 制作铁镐，再探索矿区寻找钻石。
6. 途中持续补给：面对水按空格喝水；攻击牛获得食物；在草地按空格有概率获得树苗，种植后等待成熟再吃；找安全地点按 `Tab` 睡觉。

工具制作配方如下。工作台或熔炉需要在角色周围一格范围内，材料不足或距离太远时按键不会制作。

| 工具 | 消耗材料 | 附近设施 |
| --- | --- | --- |
| 木镐 / 木剑 | 1 木材 | 工作台 |
| 石镐 / 石剑 | 1 木材 + 1 石头 | 工作台 |
| 铁镐 / 铁剑 | 1 木材 + 1 煤 + 1 铁 | 工作台与熔炉 |

夜间留意僵尸，矿区留意骷髅。饥饿、缺水或体力不足会损失生命，走入岩浆会死亡。背包物品通常最多保留 9 个。

## 可选启动参数

参数会传给官方的 `crafter.run_gui`。例如：

```powershell
# 固定初始随机种子
.\play.bat --seed 42

# 不按键时暂停世界，适合慢慢熟悉玩法；睡觉期间仍会推进
.\play.bat --wait True

# 修改窗口大小或游戏速度
.\play.bat --window 900 900 --fps 5

# 死亡后退出，不自动开新局
.\play.bat --death quit

# 仅准备环境，不打开窗口
.\play.bat -SetupOnly

# 查看全部官方参数
.\play.bat --help
```

`--seed` 固定的是初始种子；同一次运行中死亡重开会使用下一局的地图。`--wait True` 会改变时间推进方式，因此与默认实时玩法不同。

## 常见问题

- **提示找不到 Python：** 安装 uv，或安装 Python 3.11 并加入 PATH，然后重新双击。安装工具后如在旧终端运行，请重新打开终端。
- **第一次启动较慢：** 正在下载 Python 或依赖；地图首次生成也可能需要等待片刻。
- **依赖安装失败：** 检查网络后重试；脚本只在安装成功后记录环境已就绪。
- **环境损坏或移动文件夹后无法启动：** 关闭游戏，删除本项目的 `.venv` 文件夹，再双击重建。不要删除其他项目的环境。
- **按键没有反应：** 点击游戏窗口获得焦点。游戏会自动关闭窗口的文字输入模式，避免中文输入法把 `WASD` 当作拼音拦截；更新代码后请关闭旧窗口，重新运行 `play.bat`。制作还需要满足材料和附近设施条件。
- **双击后出现错误：** 控制台会保留错误并等待按键，便于查看；可以从 PowerShell 运行 `play.bat` 检查输出。

## 手动运行与研究接口

已经通过脚本安装依赖后，可以直接使用项目环境：

```powershell
.\.venv\Scripts\python.exe -m crafter.run_gui
```

Linux / macOS 可以在 Python 3.10–3.12 环境中手动运行：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-play.txt
python -m crafter.run_gui
```

研究接口也保留在 `crafter` 包中；默认观察为 64 × 64 RGB 图像，有 17 个离散动作、22 项成就。可直接使用环境，无需安装 Gym：

```python
import crafter

env = crafter.Env(seed=42)
obs = env.reset()
obs, reward, done, info = env.step(env.action_names.index("move_right"))
print(info["inventory"], info["achievements"])
```

当前接口返回 `reset() -> obs`、`step() -> (obs, reward, done, info)`，接入使用新接口的 Gymnasium 算法时需要适配。

## 来源与许可证

- 官方源码：[danijar/crafter](https://github.com/danijar/crafter)
- 论文：[Benchmarking the Spectrum of Agent Capabilities](https://arxiv.org/abs/2109.06780)
- 许可证：[MIT](LICENSE)

本地新增入口为 `play.bat`、`play_beginner.bat`、`scripts/play.ps1` 和 `requirements-play.txt`；游戏窗口增加了标题操作提示，并关闭文字输入模式以避免中文输入法拦截游戏按键。
