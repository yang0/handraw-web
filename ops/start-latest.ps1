param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 0,
    [string]$DatabasePath = '',
    [switch]$Demo,
    [switch]$NoBrowser
)

# One-click local start of the latest origin/main.
# Code runs from a script-owned worktree (.local\latest) so the main checkout's
# uncommitted work is never touched; data, uploads and service configs still
# come from the main checkout.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$localDir = Join-Path $repo '.local'
$latest = Join-Path $localDir 'latest'
# -Demo runs on a private copy of the seed database, where the starter test
# accounts (.local\starter_credentials.seed_v2.json) can log in.
if (-not $Port) { $Port = if ($Demo) { 3097 } else { 3080 } }
if (-not $DatabasePath) {
    if ($Demo) {
        $DatabasePath = Join-Path $localDir 'demo_v2.db'
        if (-not (Test-Path $DatabasePath)) {
            Copy-Item (Join-Path $localDir 'seed_v2.db') $DatabasePath
            Write-Host "已从种子库创建演示库：$DatabasePath"
        }
    } else {
        $DatabasePath = Join-Path $localDir 'handraw_v2.db'
    }
}
$databaseFile = [IO.Path]::GetFullPath($DatabasePath)
$recordFile = Join-Path $localDir "latest-run-$Port.json"
$origin = "http://127.0.0.1:$Port"

function Invoke-Git {
    & git @args
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') 执行失败。" }
}

function Update-LatestCode {
    Write-Host '正在获取最新代码……'
    & git -C $repo fetch --quiet origin
    if ($LASTEXITCODE -ne 0) { Write-Host '提示：联网获取失败，使用本机已有的最新版本。' -ForegroundColor Yellow }
    if (-not (Test-Path (Join-Path $latest '.git'))) {
        Invoke-Git -C $repo worktree add --quiet --detach $latest origin/main
    } elseif (@(& git -C $latest status --porcelain).Count -gt 0) {
        Write-Host "提示：$latest 里有改动，本次不更新代码。" -ForegroundColor Yellow
    } else {
        Invoke-Git -C $latest checkout --quiet --detach origin/main
    }
    return (& git -C $latest rev-parse --short HEAD).Trim()
}

function Read-RunRecord {
    if (-not (Test-Path $recordFile)) { return $null }
    try { return Get-Content $recordFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

function Get-PortOwner {
    $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -eq 0) { return $null }
    if ($owners.Count -ne 1) { throw "端口 $Port 有多个进程占用，未执行操作。" }
    return Get-CimInstance Win32_Process -Filter "ProcessId = $($owners[0])"
}
function Stop-OldServer {
    $owner = Get-PortOwner
    if (-not $owner) { return }
    $commandLine = [string]$owner.CommandLine
    $isHandraw = $commandLine -match '-m\s+backend\.server(?:\s|$)' -and
        $commandLine.IndexOf($databaseFile, [StringComparison]::OrdinalIgnoreCase) -ge 0
    if (-not $isHandraw) {
        throw "端口 $Port 被其他程序占用（PID $($owner.ProcessId)），未关闭任何程序。"
    }
    Write-Host "正在关闭旧的网站服务（PID $($owner.ProcessId)）……"
    # Re-check identity right before stopping; never kill unrelated Python processes.
    $fresh = Get-CimInstance Win32_Process -Filter "ProcessId = $($owner.ProcessId)"
    if (-not $fresh -or $fresh.CreationDate -ne $owner.CreationDate) {
        throw '进程状态已变化，未执行关闭，请重试。'
    }
    Stop-Process -Id $owner.ProcessId -ErrorAction Stop
    Wait-Process -Id $owner.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
}

function Backup-Database([string]$python, [string]$commit) {
    # The demo database is a disposable seed copy; only real data gets backups.
    if ($Demo -or -not (Test-Path $databaseFile)) { return }
    $record = Read-RunRecord
    if ($record -and $record.commit -eq $commit) { return }
    $backupDir = Join-Path $localDir 'backups'
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $baseName = [IO.Path]::GetFileNameWithoutExtension($databaseFile)
    $target = Join-Path $backupDir ("$baseName-before-$commit-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.db')
    # sqlite3 backup API copies a consistent snapshot even when WAL files exist.
    & $python -X utf8 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $databaseFile $target
    if ($LASTEXITCODE -ne 0) { throw '数据库备份失败，未启动新版本。' }
    Write-Host "代码有更新，已先备份数据库：$target"
}

try {
    $commit = Update-LatestCode
    $localPython = Join-Path $repo '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $python = $localPython
    } else {
        $python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    }
    Stop-OldServer
    Backup-Database $python $commit

    # Point the worktree's code at the main checkout's data and service configs.
    $env:HANDRAW_PRIVATE_STORAGE = $localDir
    # Demo seed accounts are intentionally disabled in normal mode.  The
    # isolated -Demo database must opt into those credentials explicitly.
    # Also clear an inherited demo flag for normal starts on port 3080.
    $env:HANDRAW_DEMO_MODE = if ($Demo) { '1' } else { '0' }
    $env:HANDRAW_IMAGE_CONFIG = Join-Path $repo 'image-service.json'
    $env:HANDRAW_AI_CONFIG = Join-Path $repo 'ai-service.json'
    $env:HANDRAW_MAIL_CONFIG = Join-Path $localDir 'mail-service.json'
    # Recovery/verification links must resolve to the actual local site.
    # -Demo uses 3097, while the normal local site uses 3080.
    $env:HANDRAW_PUBLIC_URL = $origin
    if ($Port -ne 3080) { $env:HANDRAW_ALLOWED_ORIGINS = "$origin,http://localhost:$Port" }

    $logDir = Join-Path $localDir 'logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $outLog = Join-Path $logDir "latest-$Port.out.log"
    $errLog = Join-Path $logDir "latest-$Port.err.log"
    $serverArgs = @('-X', 'utf8', '-u', '-m', 'backend.server', '--port', [string]$Port, '--db', "`"$databaseFile`"")
    Start-Process -FilePath $python -ArgumentList $serverArgs -WorkingDirectory $latest `
        -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog | Out-Null

    $ready = $false
    for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
        Start-Sleep -Milliseconds 500
        try { $ready = [bool](Invoke-RestMethod -Uri "$origin/api/health" -TimeoutSec 1).ok } catch { }
    }
    if (-not $ready) { throw "服务没有启动成功，请查看日志：$errLog" }
    @{ commit = $commit; port = $Port; startedAt = (Get-Date).ToString('s') } |
        ConvertTo-Json | Set-Content -Path $recordFile -Encoding UTF8

    Write-Host ''
    Write-Host "已启动最新版本 $commit，服务在后台运行，关闭这个窗口不影响。" -ForegroundColor Green
    Write-Host "首页：   $origin/"
    Write-Host "创作台： $origin/studio/"
    Write-Host "社区：   $origin/forum/"
    Write-Host "后台：   $origin/admin/"
    if (-not $NoBrowser) { Start-Process "$origin/" }
    exit 0
} catch {
    Write-Host "启动失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
