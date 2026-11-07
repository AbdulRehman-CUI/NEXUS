param([string]$Python = "python", [switch]$WithTorch)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" } }
& $Python --version
Check-Exit
& $Python -m venv .venv
Check-Exit
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
Check-Exit
if ($WithTorch) {
    # Optional sentence-transformers Python runtime / cross-encoder; no CUDA download.
    & .\.venv\Scripts\python.exe -m pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
    Check-Exit
    & .\.venv\Scripts\python.exe -m pip install -r apps/api/requirements-ml.lock.txt
    Check-Exit
} else {
    # Default ONNX MiniLM profile uses the CPU runtime also required by Chroma.
    & .\.venv\Scripts\python.exe -m pip install -r apps/api/requirements.lock.txt
    Check-Exit
}
if (!(Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
& .\.venv\Scripts\python.exe -m pip install -r apps/api/requirements-typecheck.txt
Check-Exit
Push-Location apps/web
try { npm ci --no-audit --no-fund; Check-Exit } finally { Pop-Location }
Write-Host 'Ready. In separate terminals run .\scripts\api.ps1 and .\scripts\web.ps1'
