@echo off
chcp 65001 >nul
rem ============================================================
rem Crafter DreamerV3 100k 本地调用 Colab 云端算力启动跳板
rem ============================================================

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "RUNNER_PY=%SCRIPT_DIR%run_on_colab.py"
set "VENV_PY=%SCRIPT_DIR%..\.venv\Scripts\python.exe"

echo [*] 正在定位 Python 运行时环境...

if exist "%VENV_PY%" (
    set "TARGET_PY=%VENV_PY%"
    echo [OK] 找到本地虚拟环境 Python: !TARGET_PY!
) else (
    set "TARGET_PY=python"
    echo [*] 使用系统全局 Python: !TARGET_PY!
)

echo [*] 启动云端训练驱动程序...
echo [*] 目标: Google Colab T4 GPU (100,000 steps, size12m)
echo ============================================================

"!TARGET_PY!" "%RUNNER_PY%" %*

if errorlevel 1 (
    echo.
    echo [ERROR] 任务执行失败，退出代码: !errorlevel!
) else (
    echo.
    echo [OK] 任务执行完毕。
)

echo.
pause
