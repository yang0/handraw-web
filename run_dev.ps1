# Handraw Studio Local Dev Server Launcher
# Usage: .\run_dev.ps1 [-Port 3000] [-DiscourseUrl https://handraw-style.com]
param(
    [int]$Port = 3000,
    [string]$DiscourseUrl = "https://handraw-style.com"
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Handraw Studio 本地极速调试系统 (Zero-Ops)" -ForegroundColor Green
Write-Host "  访问地址: http://localhost:$Port/studio" -ForegroundColor Yellow
Write-Host "  论坛上游: $DiscourseUrl (点击交流讨论自动跳转)" -ForegroundColor Magenta
Write-Host "  直接保存前端代码即可 F5 实时刷新调试" -ForegroundColor Gray
Write-Host "==========================================================" -ForegroundColor Cyan

python ops/dev_server.py --port $Port --discourse $DiscourseUrl
