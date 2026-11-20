$ErrorActionPreference = 'Stop'
$package = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = (Get-Location).Path
if (-not (Test-Path (Join-Path $repo 'src'))) { throw 'Run this script from the cloned repository root.' }
if (-not (Test-Path (Join-Path $repo 'public'))) { throw 'Run this script from the cloned repository root.' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $repo "rollback-backup-$stamp"
New-Item -ItemType Directory -Path (Join-Path $backup 'src') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $backup 'public') -Force | Out-Null
if (Test-Path (Join-Path $repo 'src\worker.py')) { Copy-Item (Join-Path $repo 'src\worker.py') (Join-Path $backup 'src\worker.py') -Force }
if (Test-Path (Join-Path $repo 'public\index.html')) { Copy-Item (Join-Path $repo 'public\index.html') (Join-Path $backup 'public\index.html') -Force }
Copy-Item (Join-Path $package 'src\worker.py') (Join-Path $repo 'src\worker.py') -Force
Copy-Item (Join-Path $package 'public\index.html') (Join-Path $repo 'public\index.html') -Force
Remove-Item (Join-Path $repo 'migrations\001_d1_read_indexes.sql') -ErrorAction SilentlyContinue
Remove-Item (Join-Path $repo 'scripts\apply_frontend_cache_patch.py') -ErrorAction SilentlyContinue
Get-ChildItem (Join-Path $repo 'public') -Recurse -Filter '*.before-d1-cache.bak' -ErrorAction SilentlyContinue | ForEach-Object {
  $original = $_.FullName -replace '\.before-d1-cache\.bak$', ''
  Copy-Item $_.FullName $original -Force
}
Write-Host "Rollback files installed. Backup: $backup" -ForegroundColor Green
Write-Host 'Next run: uv sync' -ForegroundColor Cyan
Write-Host 'Then run: uv run pywrangler deploy' -ForegroundColor Cyan
