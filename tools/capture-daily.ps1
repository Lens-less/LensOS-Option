<#
.SYNOPSIS
    One day's capture for the signal-validation cohort series.

.DESCRIPTION
    Deribit does not publish historical option chains, so the validation sample
    cannot be backfilled — it has to be accumulated forward, one capture per
    day, until enough expiries have settled. This script is the unit of that
    accumulation and is meant to be driven by a scheduler.

    It does two things, and the second is not optional: it appends a chain
    snapshot to the series directory, and it refreshes the underlying price
    history. The history supplies the settlement close for every expiry that has
    already resolved, so a stale history means the most recently settled cohorts
    silently drop out of the sample.

    Failures are logged and surfaced through the exit code rather than being
    swallowed, because a scheduled job that fails quietly for a week destroys
    the sample it was supposed to be building.
#>

[CmdletBinding()]
param(
    [string] $Currency = 'BTC',
    [int]    $InstrumentLimit = 96,
    [int]    $HistoryDays = 1200,
    [string] $RepoRoot
)

$ErrorActionPreference = 'Stop'

# Resolved here rather than as a param default: under `powershell.exe -File`,
# which is how the scheduler invokes this, $PSScriptRoot is still empty while
# param defaults are being evaluated, and the script fails before it can log
# anything about why.
if (-not $RepoRoot) {
    $scriptPath = $MyInvocation.MyCommand.Path
    if (-not $scriptPath) { $scriptPath = $PSCommandPath }
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptPath)
}

$seriesDir  = Join-Path $RepoRoot "artifacts/snapshots/$($Currency.ToLower())-series"
$historyDir = Join-Path $RepoRoot 'artifacts/history'
$logDir     = Join-Path $RepoRoot 'artifacts/logs'

foreach ($dir in @($seriesDir, $historyDir, $logDir)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
}

$logFile = Join-Path $logDir 'capture-daily.log'
function Write-Log {
    param([string] $Message)
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    Add-Content -Path $logFile -Value "$stamp  $Message" -Encoding utf8
}

Set-Location $RepoRoot
$failed = $false

Write-Log "capture start currency=$Currency limit=$InstrumentLimit"

try {
    $snapshot = & python -m crypto_options_report.cli pull-snapshot `
        --currency $Currency `
        --instrument-limit $InstrumentLimit `
        --output-dir $seriesDir `
        --compact
    if ($LASTEXITCODE -ne 0) { throw "pull-snapshot exited $LASTEXITCODE" }
    Write-Log "snapshot ok $snapshot"
}
catch {
    $failed = $true
    Write-Log "snapshot FAILED $($_.Exception.Message)"
}

# The history is refreshed every run rather than once, because each new
# settlement print is what turns a captured cohort into a usable outcome.
try {
    $historyPath = Join-Path $historyDir "$($Currency.ToLower())-daily.json"
    & python -m crypto_options_report.underlying_history_tool `
        --currency $Currency `
        --days $HistoryDays `
        --output $historyPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "underlying-history exited $LASTEXITCODE" }
    Write-Log "history ok $historyPath"
}
catch {
    $failed = $true
    Write-Log "history FAILED $($_.Exception.Message)"
}

$captureCount = (Get-ChildItem -Path $seriesDir -Filter '*.json' -ErrorAction SilentlyContinue).Count
Write-Log "captures in series: $captureCount"

if ($failed) { exit 1 }
exit 0
