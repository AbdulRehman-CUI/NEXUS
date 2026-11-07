$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'apps/web')
# Next reads browser-public values from the repository's .env via this process.
$taskEnv = Join-Path (Split-Path -Parent $PSScriptRoot) '.env'
if (Test-Path -LiteralPath $taskEnv) {
    $apiLine = Get-Content -LiteralPath $taskEnv | Where-Object { $_ -match '^NEXT_PUBLIC_API_URL=' } | Select-Object -First 1
    if ($apiLine) { $env:NEXT_PUBLIC_API_URL = ($apiLine -split '=', 2)[1].Trim().Trim('"').Trim("'") }
}
npm run dev
if ($LASTEXITCODE -ne 0) { throw 'Web server did not start successfully.' }
