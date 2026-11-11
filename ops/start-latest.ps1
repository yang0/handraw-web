param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 0,
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
if (-not $Port) { $Port = if ($Demo) { 3097 } else { 3080 } }
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
    $record = Read-RunRecord
    $isHandraw = $record -and $record.pid -eq $owner.ProcessId -and
        $record.creationTicks -eq $owner.CreationDate.ToUniversalTime().Ticks.ToString() -and
        $commandLine -match '-m\s+backend\.server(?:\s|$)'
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
    if ($Demo) { return }
    $record = Read-RunRecord
    if ($record -and $record.commit -eq $commit) { return }
    $backupDir = Join-Path $localDir 'backups'
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $target = Join-Path $backupDir ("handraw-before-$commit-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump')
    $pgDump = (Get-Command pg_dump -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    if (-not $pgDump) { $pgDump = 'D:\PostgreSQL\pgsql\bin\pg_dump.exe' }
    $backupScript = @'
import os
import subprocess
import sys
from psycopg.conninfo import conninfo_to_dict, make_conninfo

settings = conninfo_to_dict(os.environ['HANDRAW_DATABASE_URL'])
env = dict(os.environ)
if 'password' in settings:
    env['PGPASSWORD'] = settings.pop('password')
if 'sslpassword' in settings:
    env['PGSSLPASSWORD'] = settings.pop('sslpassword')
result = subprocess.run([
    sys.argv[1], '--no-password', '--format=custom', '--file', sys.argv[2],
    '--dbname', make_conninfo(**settings),
], env=env)
raise SystemExit(result.returncode)
'@
    & $python -X utf8 -c $backupScript $pgDump $target
    if ($LASTEXITCODE -ne 0) { throw '数据库备份失败，未启动新版本。' }
    Write-Host "代码有更新，已先备份数据库：$target"
}

try {
    foreach ($envName in @('.env.local', '.env')) {
        $envFile = Join-Path $repo $envName
        if (Test-Path -LiteralPath $envFile -PathType Leaf) {
            foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
                if ($line -match '^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=(.*)$' -and
                    $null -eq [Environment]::GetEnvironmentVariable($Matches[1], 'Process')) {
                    [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), 'Process')
                }
            }
        }
    }
    if ($Demo) {
        if (-not $env:HANDRAW_DEMO_DATABASE_URL -or $env:HANDRAW_DEMO_DATABASE_URL -eq $env:HANDRAW_DATABASE_URL) {
            throw '请设置独立的 HANDRAW_DEMO_DATABASE_URL 演示库。'
        }
        $env:HANDRAW_DATABASE_URL = $env:HANDRAW_DEMO_DATABASE_URL
    }
    if (-not $env:HANDRAW_DATABASE_URL) { throw '请设置 HANDRAW_DATABASE_URL。' }
    $commit = Update-LatestCode
    $localPython = Join-Path $repo '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $python = $localPython
    } else {
        $python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    }
    Backup-Database $python $commit
    Stop-OldServer

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
    $serverArgs = @('-X', 'utf8', '-u', '-m', 'backend.server', '--port', [string]$Port)
    $process = Start-Process -FilePath $python -ArgumentList $serverArgs -WorkingDirectory $latest `
        -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru

    $ready = $false
    for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
        Start-Sleep -Milliseconds 500
        try { $ready = [bool](Invoke-RestMethod -Uri "$origin/api/health" -TimeoutSec 1).ok } catch { }
    }
    if (-not $ready) { throw "服务没有启动成功，请查看日志：$errLog" }
    $owner = Get-PortOwner
    if (-not $owner -or $owner.ProcessId -ne $process.Id) { throw '服务端口的进程身份与启动记录不符。' }
    @{ commit = $commit; port = $Port; pid = $process.Id; creationTicks = $owner.CreationDate.ToUniversalTime().Ticks.ToString() } |
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
