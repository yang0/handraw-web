param(
    [Parameter(Position=0)][ValidateSet('update','status','deploy','rollback','preview','test','dev','local')][string]$Action='status',
    [string]$Commit,
    [string]$Server='tencent-vm',
    [int]$Port=3000,
    [string]$DiscourseUrl='https://handraw-style.com'
)
$ErrorActionPreference='Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed ($LASTEXITCODE)" }
}
if ($Action -eq 'update') {
    $changes = & git status --porcelain
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect Git status' }
    if ($changes) { throw 'Commit or preserve local changes before updating. No files were overwritten.' }
    Invoke-Checked git @('pull','--ff-only')
} elseif ($Action -eq 'status') {
    Invoke-Checked git @('status','--short','--branch')
    Invoke-Checked ssh @($Server,'bash /home/yang0/projectHome/handraw-web/ops/server-deploy.sh status')
} elseif ($Action -eq 'deploy') {
    if (& git status --porcelain) { throw 'Commit local changes before deployment.' }
    if (-not $Commit) { $Commit = & git rev-parse HEAD }
    if ($Commit -notmatch '^[0-9a-f]{40}$') { throw 'Use a full 40-character commit SHA.' }
    Invoke-Checked git @('push','origin','main')
    $checksJson = & gh run list --repo yang0/handraw-web --workflow checks.yml --commit $Commit --limit 1 --json status,conclusion
    if ($LASTEXITCODE -ne 0) { throw 'Unable to verify GitHub checks. Deployment stopped.' }
    $checks = @($checksJson | ConvertFrom-Json)
    if ($checks.Count -ne 1 -or $checks[0].status -ne 'completed' -or $checks[0].conclusion -ne 'success') {
        throw 'This commit has not passed GitHub checks. Wait for a successful run before deployment.'
    }
    Invoke-Checked ssh @($Server,"bash /home/yang0/projectHome/handraw-web/ops/server-deploy.sh deploy $Commit")
} elseif ($Action -eq 'rollback') {
    Invoke-Checked ssh @($Server,'bash /home/yang0/projectHome/handraw-web/ops/server-deploy.sh rollback')
} elseif ($Action -eq 'preview') {
    Write-Host 'Preview tunnel: http://localhost:3010/studio (Ctrl+C closes only the tunnel)'
    Invoke-Checked ssh @('-N','-L','3010:127.0.0.1:3010',$Server)
} elseif ($Action -in @('dev','local')) {
    Write-Host "Starting local zero-ops development server on port $Port (Discourse: $DiscourseUrl)..."
    Invoke-Checked python @('ops/dev_server.py','--port',"$Port",'--discourse',"$DiscourseUrl")
} else {
    Invoke-Checked python @('-m','unittest','discover','-s','tests','-v')
    Invoke-Checked node @('--check','plugin/public/portal.js')
}
