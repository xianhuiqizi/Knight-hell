# FlowRemote - one-time development setup
#
# Usage:
#   cd 'E:\knight hell'
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Installs uv, Python 3.13, and every dependency from the agreed stack.
# Safe to run twice: every step either skips or is idempotent.

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $projectRoot
Write-Host "project : $projectRoot"

# 1) If Windows has a system proxy enabled (Clash Verge does this), let uv use it too.
$ie = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
if ($ie -and $ie.ProxyEnable -eq 1 -and $ie.ProxyServer) {
    $proxy = if ($ie.ProxyServer -match '^https?://') { $ie.ProxyServer } else { "http://$($ie.ProxyServer)" }
    $env:HTTP_PROXY = $proxy
    $env:HTTPS_PROXY = $proxy
    $env:ALL_PROXY = $proxy
    Write-Host "proxy   : $proxy"
}

# 2) uv
function Find-Uv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

$uv = Find-Uv
if (-not $uv) {
    Write-Host "uv      : installing"
    try {
        powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    } catch {
        Write-Host "astral.sh failed, falling back to the Tsinghua mirror"
        python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple uv
    }
    $uv = Find-Uv
}
if (-not $uv) { throw "uv could not be installed. Install it manually, then run this script again." }
Write-Host "uv      : $uv"
& $uv --version

# 3) Python 3.13, pinned for this project.
& $uv python install 3.13
& $uv python pin 3.13

# 4) Dependencies from the agreed stack.
& $uv add fastapi uvicorn jinja2 httpx pydantic pydantic-settings sqlalchemy alembic openpyxl
& $uv add --dev pytest pytest-asyncio ruff

# 5) Prove the environment works.
Write-Host "`n--- versions"
& $uv run python -c "import sys, fastapi, pydantic, sqlalchemy, alembic, jinja2, httpx, openpyxl; print('python      ', sys.version.split()[0]); print('fastapi     ', fastapi.__version__); print('pydantic    ', pydantic.__version__); print('sqlalchemy  ', sqlalchemy.__version__); print('alembic     ', alembic.__version__); print('jinja2      ', jinja2.__version__); print('httpx       ', httpx.__version__); print('openpyxl    ', openpyxl.__version__)"
& $uv run pytest --version
& $uv run ruff --version

Write-Host "`nEnvironment ready. Prefix every command with 'uv run', for example:"
Write-Host "  uv run python src\flowremote\devtools\seed.py --reset --verify"
Write-Host "  uv run python -m unittest discover -s tests"
