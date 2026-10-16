# Keep this file ASCII so Windows PowerShell 5.1 can read it without a BOM.
param(
    [switch]$SetupOnly,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GameArgs
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$env:PYGAME_HIDE_SUPPORT_PROMPT = '1'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$requirementsPath = Join-Path $projectRoot 'requirements-play.txt'
$markerPath = Join-Path $projectRoot '.venv\crafter-play.sha256'

function Assert-CommandSucceeded([string]$message) {
    if ($LASTEXITCODE -ne 0) { throw $message }
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        Write-Host '[1/3] Creating an isolated Python environment...'
        $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
        if ($uvCommand) {
            # uv downloads Python 3.11 automatically if it is not installed.
            & $uvCommand.Source venv --python 3.11 --seed --link-mode copy .venv
            Assert-CommandSucceeded 'Could not create .venv with uv. Check your network connection.'
        } else {
            $candidates = @(
                @{Command = 'py'; Args = @('-3.11')},
                @{Command = 'py'; Args = @('-3.12')},
                @{Command = 'py'; Args = @('-3.10')},
                @{Command = 'python'; Args = @()}
            )
            $created = $false
            foreach ($candidate in $candidates) {
                $command = Get-Command $candidate.Command -ErrorAction SilentlyContinue
                if (-not $command) { continue }
                $prefix = $candidate.Args
                try {
                    & $command.Source @prefix -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' 2>$null
                } catch { continue }
                if ($LASTEXITCODE -ne 0) { continue }
                & $command.Source @prefix -m venv .venv
                Assert-CommandSucceeded 'Could not create .venv with Python.'
                $created = $true
                break
            }
            if (-not $created) {
                throw 'Install Python 3.11 (add it to PATH) or uv, then double-click play.bat again. See README.md.'
            }
        }
    }

    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $requirementsHash = [BitConverter]::ToString(
            $hasher.ComputeHash([System.IO.File]::ReadAllBytes($requirementsPath))).Replace('-', '')
    } finally { $hasher.Dispose() }
    $installedHash = if (Test-Path -LiteralPath $markerPath) {
        (Get-Content -LiteralPath $markerPath -Raw).Trim()
    } else { '' }
    if ($installedHash -ne $requirementsHash) {
        Write-Host '[2/3] Installing game dependencies (first launch needs internet)...'
        & $pythonPath -m pip install --disable-pip-version-check -r $requirementsPath
        Assert-CommandSucceeded 'Dependency installation failed. Check your network and retry play.bat.'
        Set-Content -LiteralPath $markerPath -Value $requirementsHash -Encoding ASCII
    }

    & $pythonPath -c 'import crafter, pygame; import numpy, imageio, PIL, opensimplex, ruamel.yaml'
    Assert-CommandSucceeded 'The game environment is incomplete. Remove .venv and retry play.bat.'
    if ($SetupOnly) {
        Write-Host 'Setup complete. Double-click play.bat to play.'
        exit 0
    }
    Write-Host '[3/3] Starting Crafter. Click the game window to focus it.'
    Write-Host 'WASD: move | SPACE: interact | TAB: sleep | ESC: quit'
    Write-Host 'T/R/F/P: place | 1-6: craft | Chinese instructions: README.md'
    # Preserve the official real-time rules: 5 world steps per second,
    # time advances while idle, and death starts a new episode.
    & $pythonPath -m crafter.run_gui --window 720 720 @GameArgs
    Assert-CommandSucceeded 'The game exited with an error.'
    exit 0
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
