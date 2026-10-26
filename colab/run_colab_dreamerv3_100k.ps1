<#
.SYNOPSIS
    在 Windows 下通过 WSL 2 调用 Google Colab CLI，全自动训练 Crafter DreamerV3 100k 步并取回权重与评估日志。
.DESCRIPTION
    1. 自动检查 WSL 内部 Colab CLI 状态
    2. 自动拉起 T4 或 A100 GPU 算力实例
    3. 远端极速安装 JAX GPU 依赖、克隆 danijar/dreamerv3 与安装 crafter
    4. 执行专用训练脚本 colab/train_dreamerv3.py (目标 100,000 步)
    5. 下载模型权重 (checkpoint)、日志 (metrics.jsonl) 与整体压缩包至本地 output 目录
    6. 最终自动销毁 Colab 实例，杜绝算力与费用泄露
#>

[CmdletBinding()]
param(
    [string]$Gpu = "T4",
    [int]$Steps = 100000,
    [string]$ModelSize = "size12m",
    [int]$TrainRatio = 512,
    [string]$LocalOutDir = "e:/code/Crafter/output/crafter_dreamerv3_100k"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " [Crafter DreamerV3 Colab Runner] 启动 100k 训练任务" -ForegroundColor Cyan
Write-Host " 目标步数: $Steps | 模型规模: $ModelSize | GPU 类型: $Gpu" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. 检查 WSL 内部环境
Write-Host "[1/6] 检查 WSL 2 内部 Colab CLI 工具链..." -ForegroundColor Yellow
$colabCmd = wsl bash -c "which colab || which ~/.local/bin/colab"
if (-not $colabCmd) {
    Write-Host "[ERROR] WSL 内部未找到 colab 命令！" -ForegroundColor Red
    Write-Host "请在 WSL 2 终端中运行以下命令安装 Colab CLI:" -ForegroundColor Red
    Write-Host "  curl -LsSf https://astral.sh/uv/install.sh | sh" -ForegroundColor White
    Write-Host "  ~/.local/bin/uv tool install google-colab-cli" -ForegroundColor White
    Write-Host "并执行 'colab login' 完成 Google 账号授权。" -ForegroundColor White
    exit 1
}

# 确保 Windows 本地输出目录存在
if (-not (Test-Path $LocalOutDir)) {
    New-Item -ItemType Directory -Path $LocalOutDir -Force | Out-Null
}

try {
    # 2. 申请并启动 Colab GPU 实例
    Write-Host "[2/6] 申请 Colab GPU 实例 ($Gpu)..." -ForegroundColor Yellow
    wsl bash -c "~/.local/bin/colab new --gpu $Gpu"
    if ($LASTEXITCODE -ne 0) {
        throw "创建 Colab 实例失败，请检查是否已在 WSL 中执行 'colab login' 登录授权。"
    }

    # 3. 远端极速部署核心依赖 (基于 uv)
    Write-Host "[3/6] 配置远端 DreamerV3 与 Crafter 依赖环境..." -ForegroundColor Yellow
    wsl bash -c "~/.local/bin/colab install crafter elements portal ninjax optax chex einops ruamel.yaml scope matplotlib pandas"
    Start-Sleep -Seconds 5

    # 4. 执行远程训练
    Write-Host "[4/6] 开始远程训练 (目标 $Steps 步, 超时上限 3 小时)..." -ForegroundColor Yellow
    $remoteScript = "/mnt/e/code/Crafter/colab/train_dreamerv3.py"
    wsl bash -c "~/.local/bin/colab exec -f $remoteScript --env DREAMER_STEPS=$Steps --env DREAMER_SIZE=$ModelSize --env DREAMER_TRAIN_RATIO=$TrainRatio --timeout 10800"
    if ($LASTEXITCODE -ne 0) {
        throw "远程训练过程发生异常！"
    }

    # 5. 下载模型权重、评估日志和归档包到本地
    Write-Host "[5/6] 正在下载模型成果到本地..." -ForegroundColor Yellow
    wsl bash -c "~/.local/bin/colab download /content/output/crafter_dreamerv3_100k/metrics.jsonl /mnt/e/code/Crafter/output/crafter_dreamerv3_100k/metrics.jsonl"
    wsl bash -c "~/.local/bin/colab download /content/crafter_dreamerv3_100k.zip /mnt/e/code/Crafter/output/crafter_dreamerv3_100k/crafter_dreamerv3_100k.zip"

    Write-Host "[SUCCESS] 训练权重与日志已成功同步至本地: $LocalOutDir" -ForegroundColor Green

} catch {
    Write-Host "[ERROR] 执行失败: $_" -ForegroundColor Red
} finally {
    # 6. 销毁实例，防止算力时长泄露
    Write-Host "[6/6] 销毁 Colab 实例..." -ForegroundColor Yellow
    wsl bash -c "~/.local/bin/colab stop"
    Write-Host "Colab 算力实例已完全销毁释放。" -ForegroundColor Green
}
