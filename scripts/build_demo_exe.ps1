$ErrorActionPreference = "Stop"

Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Run 'uv sync' before building the demo executable."
}

& ".\.venv\Scripts\python.exe" -m PyInstaller `
    --noconfirm `
    --clean `
    "packaging\flowremote_demo.spec"

if ($LASTEXITCODE -ne 0) {
    throw "The executable build failed (exit $LASTEXITCODE)."
}
$demoDigest = (Get-FileHash -LiteralPath "dist\FlowRemoteDemo.exe" -Algorithm SHA256).Hash
Set-Content -LiteralPath "dist\FlowRemoteDemo.exe.sha256" -Encoding utf8 -Value "$demoDigest  FlowRemoteDemo.exe"

Write-Host ""
Write-Host "Built: $((Resolve-Path 'dist\FlowRemoteDemo.exe').Path)"
