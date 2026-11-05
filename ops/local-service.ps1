param(
    [ValidateSet('start', 'stop', 'restart', 'status')]
    [string]$Action = 'status',
    [ValidateRange(1024, 65535)]
    [int]$Port = 3080,
    [string]$DatabasePath = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $DatabasePath) {
    $DatabasePath = Join-Path $projectRoot '.local\handraw_v2.db'
}
$databaseFile = [IO.Path]::GetFullPath($DatabasePath)
$localOrigin = "http://127.0.0.1:$Port"
$escapedDatabase = [regex]::Escape($databaseFile)
$databaseArgument = '(?i)(?:^|\s)--db(?:\s+|=)(?:"' + $escapedDatabase + '"|' + $escapedDatabase + '(?=\s|$))'

function Get-HandrawProcess {
    $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -eq 0) { return $null }
    if ($owners.Count -ne 1) {
        throw "端口 $Port 有多个进程占用，未执行操作。"
    }
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($owners[0])"
    $commandLine = [string]$owner.CommandLine
    if (-not ($commandLine -match '-m\s+backend\.server(?:\s|$)' -and
        $commandLine -match $databaseArgument)) {
        throw "端口 $Port 被其他服务占用，未启动或关闭任何程序。"
    }
    return $owner
}

function Show-HandrawStatus {
    $running = Get-HandrawProcess
    if (-not $running) {
        Write-Host "服务未运行（端口 $Port）。"
        return
    }
    Write-Host "服务正在运行，PID：$($running.ProcessId)，端口：$Port"
    Write-Host "首页：   $localOrigin/"
    Write-Host "创作台： $localOrigin/studio/"
    Write-Host "社区：   $localOrigin/forum/"
    Write-Host "后台：   $localOrigin/admin/"
}

function Start-Handraw {
    if (Get-HandrawProcess) {
        Write-Host '服务已经运行，无需重复启动。'
        Show-HandrawStatus
        return
    }
    # Prefer a project-local interpreter over an unrelated activated venv
    # (e.g. Hermes). Do not force users to change their system-wide PATH.
    $localPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $python = $localPython
    } else {
        $python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    }
    # Check package presence WITHOUT importing fitz: modern PyMuPDF emits a
    # FutureWarning from that legacy alias, and PowerShell 5.1 can promote
    # native stderr into a terminating error under ErrorActionPreference=Stop.
    $checkScript = @'
import importlib.util
missing = []
for modules, package in [
    (('docx',), 'python-docx'),
    (('pymupdf', 'fitz'), 'PyMuPDF'),
    (('PIL',), 'Pillow'),
]:
    if not any(importlib.util.find_spec(name) is not None for name in modules):
        missing.append(package)
if missing:
    print(', '.join(missing))
'@
    # This is an advisory probe. Incidental native warnings must never prevent
    # the actual server from starting; runtime failures are captured in logs.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $missingLibs = & $python -c $checkScript 2>$null
        $probeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($probeExitCode -ne 0) {
        Write-Warning '依赖预检查未完成，将继续尝试启动服务；如启动失败请查看 .local\logs。'
    } elseif ($missingLibs -and -not [string]::IsNullOrWhiteSpace($missingLibs)) {
        Write-Host "提示：缺少依赖库 $($missingLibs.Trim())，导入 .docx / .pdf 或图片处理可能会受影响。"
        Write-Host "请运行命令安装依赖：python -m pip install -r requirements.txt"
    }
    $logDirectory = Join-Path $projectRoot '.local\logs'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $outputLog = Join-Path $logDirectory "service-$Port.out.log"
    $errorLog = Join-Path $logDirectory "service-$Port.err.log"
    $serverArguments = @('-X', 'utf8', '-u', '-m', 'backend.server', '--port', [string]$Port, '--db', "`"$databaseFile`"")
    Start-Process -FilePath $python -ArgumentList $serverArguments -WorkingDirectory $projectRoot `
        -WindowStyle Hidden -RedirectStandardOutput $outputLog -RedirectStandardError $errorLog | Out-Null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "$localOrigin/api/health" -TimeoutSec 1
        } catch {
            $health = $null
        }
        if ($health.ok -and (Get-HandrawProcess)) {
            Write-Host '服务已在后台启动，关闭菜单窗口不会停止服务。'
            Show-HandrawStatus
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "尚未确认服务启动成功，请查看日志：$errorLog"
}

function Stop-Handraw {
    $running = Get-HandrawProcess
    if (-not $running) {
        Write-Host '服务已经关闭。'
        return
    }
    # Check process identity again immediately before stopping; never kill all Python processes.
    $fresh = Get-CimInstance Win32_Process -Filter "ProcessId = $($running.ProcessId)"
    if (-not $fresh -or $fresh.CreationDate -ne $running.CreationDate -or $fresh.CommandLine -ne $running.CommandLine) {
        throw '进程状态已变化，未执行关闭，请重新查看状态。'
    }
    Stop-Process -Id $running.ProcessId -ErrorAction Stop
    Wait-Process -Id $running.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    Write-Host '服务已关闭。'
}

try {
    switch ($Action) {
        'start' { Start-Handraw }
        'stop' { Stop-Handraw }
        'restart' { Stop-Handraw; Start-Handraw }
        'status' { Show-HandrawStatus }
    }
    exit 0
} catch {
    Write-Host "操作失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
