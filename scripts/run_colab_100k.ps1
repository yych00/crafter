<#
.SYNOPSIS
    在 Windows 下通过 WSL 2 调用 Google Colab CLI，全自动训练 Crafter 100k 步并取回权重。
.DESCRIPTION
    1. 自动检查 WSL 中的 colab 命令
    2. 自动拉起 T4 GPU 实例
    3. 在远端极速安装 crafter, stable-baselines3, shimmy
    4. 执行训练脚本 scripts/train_crafter_colab.py
    5. 下载训练好的模型权重和 stats 到本地 output/crafter_ppo_100k
    6. 释放 Colab 算力实例
#>

[CmdletBinding()]
param(
    [string]$Gpu = "T4",
    [int]$Steps = 100000,
    [string]$LocalOutDir = "e:/code/Crafter/output/crafter_ppo_100k"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " [Crafter Colab Agent] Starting $Steps Steps Training Task" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. 检查 WSL 内部环境
Write-Host "[1/6] 检查 WSL 2 内部 Colab CLI 状态..." -ForegroundColor Yellow
$colabCmd = wsl bash -c "which colab || which ~/.local/bin/colab"
if (-not $colabCmd) {
    Write-Host "[ERROR] WSL 内部未找到 colab 命令，请先运行: wsl curl -LsSf https://astral.sh/uv/install.sh | sh && wsl ~/.local/bin/uv tool install google-colab-cli" -ForegroundColor Red
    exit 1
}

# 确保 Windows 本地 output 目录存在
if (-not (Test-Path $LocalOutDir)) {
    New-Item -ItemType Directory -Path $LocalOutDir -Force | Out-Null
}

try {
    # 2. 启动 Colab GPU 实例
    Write-Host "[2/6] 申请 Colab GPU 实例 ($Gpu)..." -ForegroundColor Yellow
    wsl bash -c "~/.local/bin/colab new --gpu $Gpu"
    if ($LASTEXITCODE -ne 0) {
        throw "创建 Colab 实例失败，请检查是否已执行 'wsl colab login' 登录授权。"
    }

    # 3. 远端极速预装核心依赖 (基于 uv)
    Write-Host "[3/6] 安装远端依赖环境 (crafter, stable-baselines3, shimmy)..." -ForegroundColor Yellow
    wsl bash -c "~/.local/bin/colab install crafter stable-baselines3 shimmy"

    # 4. 运行远程训练 (超时上限设置为 7200 秒)
    Write-Host "[4/6] 开始远程训练 (目标 $Steps 步)..." -ForegroundColor Yellow
    wsl bash -c "~/.local/bin/colab exec -f /mnt/e/code/Crafter/scripts/train_crafter_colab.py --env CRAFTER_STEPS=$Steps --timeout 7200"
    if ($LASTEXITCODE -ne 0) {
        throw "远程训练过程发生异常！"
    }

    # 5. 下载模型权重与日志到本地
    Write-Host "[5/6] 下载模型权重与日志到本地..." -ForegroundColor Yellow
    wsl bash -c "~/.local/bin/colab download /content/output/crafter_ppo_100k/crafter_ppo_100k.zip /mnt/e/code/Crafter/output/crafter_ppo_100k/crafter_ppo_100k.zip"
    wsl bash -c "~/.local/bin/colab download /content/output/crafter_ppo_100k/stats.csv /mnt/e/code/Crafter/output/crafter_ppo_100k/stats.csv"

    Write-Host "[SUCCESS] 训练权重与日志已成功同步至本地: $LocalOutDir" -ForegroundColor Green

} catch {
    Write-Host "[ERROR] 执行失败: $_" -ForegroundColor Red
} finally {
    # 6. 确保销毁实例，防止算力/时长泄露
    Write-Host "[6/6] 销毁 Colab 实例..." -ForegroundColor Yellow
    wsl bash -c "~/.local/bin/colab stop"
    Write-Host "Colab 算力实例已完全销毁释放。" -ForegroundColor Green
}
