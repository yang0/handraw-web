<#
.SYNOPSIS
    Handraw 本地基础设置（PostgreSQL + Redis）运维管理脚本
.DESCRIPTION
    支持启动、停止、查看状态以及快速连接本地 D 盘安装的 PostgreSQL 16 与 Redis 实例。
.EXAMPLE
    .\ops\infra.ps1 status
    .\ops\infra.ps1 start
    .\ops\infra.ps1 stop
    .\ops\infra.ps1 psql
#>
param(
    [ValidateSet('start', 'stop', 'restart', 'status', 'psql', 'redis-cli')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$PgBin = "D:\PostgreSQL\pgsql\bin"
$PgData = "D:\PostgreSQL\data"
$PgLog = "D:\PostgreSQL\logfile"
$PgCtl = Join-Path $PgBin "pg_ctl.exe"
$Psql = Join-Path $PgBin "psql.exe"

$RedisDir = "D:\Program Files\Redis"
$RedisServer = Join-Path $RedisDir "redis-server.exe"
$RedisConf = Join-Path $RedisDir "redis.windows.conf"
$RedisCli = Join-Path $RedisDir "redis-cli.exe"

function Get-RedisProcess {
    $conns = @(Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    if ($conns.Count -gt 0) {
        return (Get-CimInstance Win32_Process -Filter "ProcessId = $($conns[0])" -ErrorAction SilentlyContinue)
    }
    return $null
}

function Show-Status {
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host "  Handraw 本地基础设施运行状态巡检" -ForegroundColor Cyan
    Write-Host "==========================================" -ForegroundColor Cyan

    # 1. PostgreSQL
    if (Test-Path $PgCtl) {
        Write-Host "[PostgreSQL 16]" -ForegroundColor Yellow
        try {
            $pgOut = & $PgCtl status -D $PgData 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  状态: 正在运行" -ForegroundColor Green
                Write-Host "  数据目录: $PgData"
                Write-Host "  端口: 5432"
                Write-Host "  业务库: handraw_v2"
            } else {
                Write-Host "  状态: 未运行" -ForegroundColor Red
            }
        } catch {
            Write-Host "  状态检查异常: $_" -ForegroundColor Red
        }
    } else {
        Write-Host "[PostgreSQL] 未在 $PgCtl 检测到二进制程序" -ForegroundColor DarkGray
    }

    Write-Host ""

    # 2. Redis
    if (Test-Path $RedisCli) {
        Write-Host "[Redis (RESP2)]" -ForegroundColor Yellow
        $redisProc = Get-RedisProcess
        try {
            $ping = & $RedisCli ping 2>$null
            if ($ping -match "PONG") {
                Write-Host "  状态: 正在运行 (PID: $($redisProc.ProcessId))" -ForegroundColor Green
                Write-Host "  端口: 6379"
                Write-Host "  响应: $ping"
            } else {
                Write-Host "  状态: 未响应 (未运行)" -ForegroundColor Red
            }
        } catch {
            Write-Host "  状态检查异常: $_" -ForegroundColor Red
        }
    } else {
        Write-Host "[Redis] 未在 $RedisCli 检测到客户端程序" -ForegroundColor DarkGray
    }

    Write-Host "==========================================" -ForegroundColor Cyan
}

function Start-Infra {
    Write-Host "正在启动本地 PostgreSQL 与 Redis 服务..." -ForegroundColor Cyan

    # 启动 PostgreSQL
    if (Test-Path $PgCtl) {
        $pgOut = & $PgCtl status -D $PgData 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[PostgreSQL] 已经处于运行状态。" -ForegroundColor Green
        } else {
            Write-Host "[PostgreSQL] 正在启动..."
            & $PgCtl start -D $PgData -l $PgLog -w
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[PostgreSQL] 启动成功！" -ForegroundColor Green
            } else {
                Write-Host "[PostgreSQL] 启动失败，请检查日志：$PgLog" -ForegroundColor Red
            }
        }
    }

    # 启动 Redis
    if (Test-Path $RedisServer) {
        $redisProc = Get-RedisProcess
        if ($redisProc) {
            Write-Host "[Redis] 已经处于运行状态 (PID: $($redisProc.ProcessId))。" -ForegroundColor Green
        } else {
            Write-Host "[Redis] 正在启动后台服务..."
            Start-Process -FilePath $RedisServer -ArgumentList "`"$RedisConf`"" -WindowStyle Hidden
            Start-Sleep -Seconds 1
            $ping = & $RedisCli ping 2>$null
            if ($ping -match "PONG") {
                Write-Host "[Redis] 启动成功！" -ForegroundColor Green
            } else {
                Write-Host "[Redis] 启动失败或未能在 1 秒内响应。" -ForegroundColor Red
            }
        }
    }
}

function Stop-Infra {
    Write-Host "正在停止本地 PostgreSQL 与 Redis 服务..." -ForegroundColor Yellow

    # 停止 PostgreSQL
    if (Test-Path $PgCtl) {
        $pgOut = & $PgCtl status -D $PgData 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[PostgreSQL] 正在安全停止..."
            & $PgCtl stop -D $PgData -m fast -w
            Write-Host "[PostgreSQL] 已停止。" -ForegroundColor Green
        } else {
            Write-Host "[PostgreSQL] 未在运行。" -ForegroundColor DarkGray
        }
    }

    # 停止 Redis
    if (Test-Path $RedisCli) {
        $redisProc = Get-RedisProcess
        if ($redisProc) {
            Write-Host "[Redis] 正在关闭 (PID: $($redisProc.ProcessId))..."
            try {
                & $RedisCli shutdown 2>$null
            } catch {}
            Start-Sleep -Milliseconds 500
            $after = Get-RedisProcess
            if ($after) {
                Stop-Process -Id $after.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Write-Host "[Redis] 已停止。" -ForegroundColor Green
        } else {
            Write-Host "[Redis] 未在运行。" -ForegroundColor DarkGray
        }
    }
}

switch ($Action) {
    'status'   { Show-Status }
    'start'    { Start-Infra; Show-Status }
    'stop'     { Stop-Infra; Show-Status }
    'restart'  { Stop-Infra; Start-Sleep -Seconds 1; Start-Infra; Show-Status }
    'psql'     {
        & $Psql -U postgres -h 127.0.0.1 -d handraw_v2
    }
    'redis-cli' {
        & $RedisCli
    }
}
