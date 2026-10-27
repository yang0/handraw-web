param(
    [int]$Port = 3080,
    [switch]$ResetDb
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
Set-Location $PSScriptRoot\..

Write-Host "Checking Handraw Web 2.0 backend syntax..." -ForegroundColor Cyan
python -m py_compile backend/server.py backend/services.py backend/admin_services.py demo/serve_demo.py

$StudioPort = $Port + 1
$ForumPort  = $Port + 2
$AdminPort  = $Port + 3

Write-Host "==============================================================" -ForegroundColor Green
Write-Host " Handraw Web 2.0 Full-Stack 4-Subdomain Platform" -ForegroundColor Green
Write-Host "  [1] Main Portal : http://localhost:$Port" -ForegroundColor Yellow
Write-Host "  [2] Studio      : http://localhost:$StudioPort" -ForegroundColor Yellow
Write-Host "  [3] Forum       : http://localhost:$ForumPort" -ForegroundColor Yellow
Write-Host "  [4] Admin       : http://localhost:$AdminPort" -ForegroundColor Yellow
Write-Host "==============================================================" -ForegroundColor Green

if ($ResetDb) {
    python demo/serve_demo.py --port $Port --reset-db
} else {
    python demo/serve_demo.py --port $Port
}
