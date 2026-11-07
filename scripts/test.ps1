$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
& .\.venv\Scripts\python.exe -m pytest apps/api -q
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
& .\.venv\Scripts\python.exe -m ruff check apps/api
if ($LASTEXITCODE -ne 0) { throw 'Python lint failed.' }
& .\.venv\Scripts\python.exe scripts/typecheck.py
if ($LASTEXITCODE -ne 0) { throw 'Python configuration/contract type checks failed. Install apps/api/requirements-typecheck.txt.' }
Push-Location apps/web
try {
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Type check failed.' }
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw 'Web lint failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Web build failed.' }
} finally { Pop-Location }
