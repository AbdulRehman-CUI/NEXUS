$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = Join-Path (Get-Location) 'apps/api'
$env:ANONYMIZED_TELEMETRY = 'False'
$env:TOKENIZERS_PARALLELISM = 'false'
$env:OMP_NUM_THREADS = '2'
& .\.venv\Scripts\python.exe -m uvicorn nexus.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
if ($LASTEXITCODE -ne 0) { throw 'API did not start successfully.' }
