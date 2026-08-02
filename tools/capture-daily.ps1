<#
.SYNOPSIS
    One day's capture for the signal-validation cohort series.

.DESCRIPTION
    Deribit does not publish historical option chains, so the validation sample
    cannot be backfilled; it has to be accumulated forward, one capture per
    day, until enough expiries have settled. This script is the unit of that
    accumulation and is meant to be driven by a scheduler.

    It keeps the existing local capture flow intact: append a chain snapshot,
    refresh the underlying and DVOL histories, then rebuild the series-history
    and signal-preflight artifacts. DVOL is enabled by default because the
    public VRP edition cannot be published without it.

    Every run writes a canonical JSON summary under artifacts/logs/. Stage
    failures are never swallowed: the script writes the failure summary, emits
    an optional failure webhook, and exits non-zero immediately.

    Any remote evidence-repo integration exposed here is preflight-only. This
    script never pushes, force-syncs, or overwrites a remote evidence repo.

.PARAMETER Currency
    Base currency to capture. Defaults to BTC.

.PARAMETER InstrumentLimit
    Maximum contract count pulled for the chain snapshot.

.PARAMETER HistoryDays
    Calendar days of underlying history to refresh.

.PARAMETER RepoRoot
    Repository root; inferred from the script location when omitted.

.PARAMETER CaptureDvolHistory
    Controls the DVOL history stage. It defaults to true; an explicit false is
    only for local diagnostics and makes the public publish inputs incomplete.

.PARAMETER DvolHistoryDays
    Calendar days of DVOL history to refresh when DVOL capture is enabled.

.PARAMETER FailureWebhookUrl
    Optional failure-only webhook URL. The script never writes this URL into
    the run summary and never includes secrets in the webhook payload.

.PARAMETER EvidenceRepoRoot
    Optional path to a separate evidence git repo for sync preflight checks.
    The script validates the path and remote configuration only; it never
    pushes or copies files into the repo.

.PARAMETER EvidenceRepoRemote
    Remote name expected inside the evidence repo when preflight runs.

.PARAMETER EnableEvidenceRepoPreflight
    Run the explicit evidence-repo preflight stage. When omitted, the script
    also checks CAPTURE_DAILY_EVIDENCE_PREFLIGHT.
#>

[CmdletBinding()]
param(
    [string] $Currency = 'BTC',
    [int]    $InstrumentLimit = 96,
    [int]    $HistoryDays = 1200,
    [string] $RepoRoot,
    [Nullable[bool]] $CaptureDvolHistory = $null,
    [int]    $DvolHistoryDays = 1095,
    [string] $FailureWebhookUrl,
    [string] $EvidenceRepoRoot,
    [string] $EvidenceRepoRemote = 'origin',
    [switch] $EnableEvidenceRepoPreflight
)

$ErrorActionPreference = 'Stop'

function Get-EnvFlag {
    param(
        [string] $Name,
        [bool] $Default = $false
    )

    $raw = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
    switch ($raw.Trim().ToLowerInvariant()) {
        '1' { return $true }
        'true' { return $true }
        'yes' { return $true }
        'on' { return $true }
        '0' { return $false }
        'false' { return $false }
        'no' { return $false }
        'off' { return $false }
        default { throw "environment flag $Name must be one of 1/0/true/false/yes/no/on/off" }
    }
}

function ConvertTo-CanonicalJson {
    param([Parameter(Mandatory)] $InputObject)

    return ($InputObject | ConvertTo-Json -Depth 12)
}

function Write-CanonicalJson {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] $InputObject
    )

    $json = ConvertTo-CanonicalJson -InputObject $InputObject
    [System.IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $utf8NoBom)
}

function Get-IsoTimestamp {
    return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

function Ensure-Directory {
    param([Parameter(Mandatory)] [string] $Path)

    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
        if (-not $item.PSIsContainer) {
            throw "required directory path exists as a file: $Path"
        }
        return
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Resolve-ToolCommand {
    param(
        [Parameter(Mandatory)] [string] $CommandName,
        [Parameter(Mandatory)] [string] $PythonModule
    )

    $resolved = Get-Command -Name $CommandName -ErrorAction SilentlyContinue
    if ($resolved) {
        return [ordered]@{
            executable = $resolved.Source
            prefix_args = @()
            display = $CommandName
        }
    }
    return [ordered]@{
        executable = 'python'
        prefix_args = @('-m', $PythonModule)
        display = "python -m $PythonModule"
    }
}

function Format-ExternalCommand {
    param(
        [Parameter(Mandatory)] [string] $Executable,
        [Parameter(Mandatory)] [string[]] $Arguments
    )

    $parts = @($Executable) + $Arguments
    return ($parts | ForEach-Object {
            if ($_ -match '\s') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
        }) -join ' '
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory)] [string] $Executable,
        [Parameter(Mandatory)] [string[]] $Arguments
    )

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    try {
        & $Executable @Arguments 1> $stdoutFile 2> $stderrFile
        $exitCode = if ($null -ne $LASTEXITCODE) { [int] $LASTEXITCODE } else { 0 }
        return [ordered]@{
            exit_code = $exitCode
            stdout = [System.IO.File]::ReadAllText($stdoutFile)
            stderr = [System.IO.File]::ReadAllText($stderrFile)
        }
    }
    finally {
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Parse-JsonText {
    param(
        [Parameter(Mandatory)] [string] $Text,
        [string] $Context = 'JSON payload'
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        throw "$Context was empty"
    }
    try {
        return $Text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "$Context was not valid JSON"
    }
}

function Get-LatestSnapshotPath {
    param([Parameter(Mandatory)] [string] $SeriesDirectory)

    $latest = Get-ChildItem -LiteralPath $SeriesDirectory -Filter '*.json' -File -ErrorAction SilentlyContinue |
        Sort-Object -Property Name |
        Select-Object -Last 1
    if ($latest) { return $latest.FullName }
    return $null
}

function Write-Log {
    param([string] $Message)
    $stamp = Get-IsoTimestamp
    Add-Content -Path $script:LogFile -Value "$stamp  $Message" -Encoding utf8
}

function Invoke-Stage {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string] $Command,
        [Parameter(Mandatory)] [scriptblock] $Action
    )

    $stage = [ordered]@{
        name = $Name
        status = 'running'
        command = $Command
        started_at = Get-IsoTimestamp
        finished_at = $null
        duration_ms = $null
        output_path = $null
        details = $null
        error = $null
    }
    $started = Get-Date

    try {
        $result = & $Action
        if ($result -is [System.Collections.IDictionary]) {
            if ($result.Contains('output_path')) { $stage.output_path = $result['output_path'] }
            if ($result.Contains('details')) { $stage.details = $result['details'] }
        }
        $stage.status = 'ok'
        Write-Log "$Name ok"
        return $result
    }
    catch {
        $stage.status = 'failed'
        $stage.error = $_.Exception.Message
        Write-Log "$Name FAILED $($stage.error)"
        throw
    }
    finally {
        $stage.finished_at = Get-IsoTimestamp
        $stage.duration_ms = [int] [Math]::Round(((Get-Date) - $started).TotalMilliseconds)
        $script:StageResults.Add([pscustomobject] $stage)
    }
}

function Invoke-CheckedJsonCommand {
    param(
        [Parameter(Mandatory)] [string] $Executable,
        [Parameter(Mandatory)] [string[]] $Arguments,
        [Parameter(Mandatory)] [string] $Context
    )

    $result = Invoke-ExternalCommand -Executable $Executable -Arguments $Arguments
    if ($result.exit_code -ne 0) {
        $stderr = $result.stderr.Trim()
        if ([string]::IsNullOrWhiteSpace($stderr)) { $stderr = "$Context exited $($result.exit_code)" }
        throw $stderr
    }
    return [ordered]@{
        raw = $result
        payload = Parse-JsonText -Text $result.stdout -Context $Context
    }
}

function Invoke-EvidenceRepoPreflight {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [string] $RemoteName,
        [Parameter(Mandatory)] [string] $ProductRepoRoot
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'evidence repo preflight requires -EvidenceRepoRoot or CAPTURE_DAILY_EVIDENCE_REPO_ROOT'
    }

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "evidence repo path does not exist: $Path"
    }

    $resolvedEvidenceRoot = (Resolve-Path -LiteralPath $Path).Path
    $resolvedProductRoot = (Resolve-Path -LiteralPath $ProductRepoRoot).Path
    if ($resolvedEvidenceRoot -eq $resolvedProductRoot) {
        throw 'evidence repo root must not be the product repo root'
    }

    $gitTopLevel = Invoke-ExternalCommand -Executable 'git' -Arguments @('-C', $resolvedEvidenceRoot, 'rev-parse', '--show-toplevel')
    if ($gitTopLevel.exit_code -ne 0) {
        throw "evidence repo is not a git worktree: $resolvedEvidenceRoot"
    }

    $remote = Invoke-ExternalCommand -Executable 'git' -Arguments @('-C', $resolvedEvidenceRoot, 'remote', 'get-url', $RemoteName)
    if ($remote.exit_code -ne 0) {
        throw "evidence repo remote is not configured: $RemoteName"
    }

    $requiredDirectories = @('snapshots', 'history', 'logs')
    $checks = foreach ($dir in $requiredDirectories) {
        $fullPath = Join-Path $resolvedEvidenceRoot $dir
        [ordered]@{
            directory = $dir
            path = $fullPath
            exists = [bool] (Test-Path -LiteralPath $fullPath -PathType Container)
        }
    }
    $missing = @($checks | Where-Object { -not $_.exists })
    if ($missing.Count -gt 0) {
        $names = ($missing | ForEach-Object { $_.directory }) -join ', '
        throw "evidence repo is missing required directories: $names"
    }

    return [ordered]@{
        output_path = $resolvedEvidenceRoot
        details = [ordered]@{
            repo_root = $resolvedEvidenceRoot
            remote_name = $RemoteName
            remote_configured = $true
            required_directories = $checks
            manual_sync_required = $true
            note = 'capture-daily.ps1 only performs preflight. Review and sync the evidence repo manually.'
        }
    }
}

function Send-FailureWebhook {
    param(
        [Parameter(Mandatory)] [string] $Url,
        [Parameter(Mandatory)] $Summary
    )

    $payload = [ordered]@{
        schema_version = 'capture_daily_failure_webhook.v1'
        run_id = $Summary.run_id
        currency = $Summary.currency
        status = $Summary.status
        failed_stage = $Summary.failed_stage
        captured_at = $Summary.capture_time
        summary_file = if ($Summary.summary_path) { Split-Path -Leaf $Summary.summary_path } else { $null }
        last_successful_snapshot_file = if ($Summary.last_successful_snapshot) { Split-Path -Leaf $Summary.last_successful_snapshot } else { $null }
    }

    $body = ConvertTo-CanonicalJson -InputObject $payload
    try {
        Invoke-WebRequest -Method Post -Uri $Url -ContentType 'application/json' -Body $body -TimeoutSec 15 | Out-Null
        return [ordered]@{
            configured = $true
            attempted = $true
            delivered = $true
            url = 'redacted'
            error = $null
        }
    }
    catch {
        return [ordered]@{
            configured = $true
            attempted = $true
            delivered = $false
            url = 'redacted'
            error = 'delivery failed'
        }
    }
}

if (-not $RepoRoot) {
    $scriptPath = $MyInvocation.MyCommand.Path
    if (-not $scriptPath) { $scriptPath = $PSCommandPath }
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptPath)
}

if ($null -eq $CaptureDvolHistory) {
    $CaptureDvolHistory = Get-EnvFlag -Name 'CAPTURE_DAILY_CAPTURE_DVOL' -Default $true
}
if (-not $FailureWebhookUrl) {
    $FailureWebhookUrl = [Environment]::GetEnvironmentVariable('CAPTURE_DAILY_FAILURE_WEBHOOK_URL')
}
if (-not $EvidenceRepoRoot) {
    $EvidenceRepoRoot = [Environment]::GetEnvironmentVariable('CAPTURE_DAILY_EVIDENCE_REPO_ROOT')
}
$evidenceRepoPreflightEnabled = $EnableEvidenceRepoPreflight.IsPresent -or (Get-EnvFlag -Name 'CAPTURE_DAILY_EVIDENCE_PREFLIGHT')

$currencyLower = $Currency.ToLowerInvariant()
$artifactsRoot = Join-Path $RepoRoot 'artifacts'
$snapshotsRoot = Join-Path $artifactsRoot 'snapshots'
$seriesDir = Join-Path $snapshotsRoot "$currencyLower-series"
$historyDir = Join-Path $artifactsRoot 'history'
$logDir = Join-Path $artifactsRoot 'logs'
$reportDir = Join-Path $artifactsRoot 'reports'

foreach ($dir in @($snapshotsRoot, $seriesDir, $historyDir, $logDir, $reportDir)) {
    Ensure-Directory -Path $dir
}

$script:LogFile = Join-Path $logDir 'capture-daily.log'
$script:StageResults = [System.Collections.Generic.List[object]]::new()

$runStartedAt = Get-IsoTimestamp
$runStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$summaryPath = Join-Path $logDir "capture-daily-$currencyLower-$runStamp.summary.json"
$latestSummaryPath = Join-Path $logDir "capture-daily-$currencyLower.latest.summary.json"

$snapshotTool = Resolve-ToolCommand -CommandName 'crypto-options-report' -PythonModule 'crypto_options_report.cli'
$underlyingTool = Resolve-ToolCommand -CommandName 'crypto-options-underlying-history' -PythonModule 'crypto_options_report.underlying_history_tool'
$dvolTool = Resolve-ToolCommand -CommandName 'crypto-options-dvol-history' -PythonModule 'crypto_options_report.dvol_history_tool'

$snapshotPath = $null
$underlyingHistoryPath = Join-Path $historyDir "$currencyLower-daily.json"
$dvolHistoryPath = Join-Path $historyDir "$currencyLower-dvol.json"
$seriesHistoryPath = Join-Path $reportDir 'series-history.json'
$signalPreflightPath = Join-Path $reportDir 'signal-preflight.json'
$lastSuccessfulSnapshot = Get-LatestSnapshotPath -SeriesDirectory $seriesDir
$failedStage = $null
$failureMessage = $null

Write-Log "capture start currency=$Currency limit=$InstrumentLimit dvol_enabled=$CaptureDvolHistory evidence_preflight=$evidenceRepoPreflightEnabled"

Set-Location $RepoRoot

try {
    $snapshotArgs = @($snapshotTool.prefix_args + @(
            'pull-snapshot',
            '--currency', $Currency,
            '--instrument-limit', [string] $InstrumentLimit,
            '--output-dir', $seriesDir,
            '--compact'
        ))
    $snapshotResult = Invoke-Stage -Name 'snapshot' -Command (Format-ExternalCommand -Executable $snapshotTool.display -Arguments $snapshotArgs) -Action {
        $response = Invoke-CheckedJsonCommand -Executable $snapshotTool.executable -Arguments $snapshotArgs -Context 'pull-snapshot'
        $script:snapshotPath = [string] $response.payload.path
        if ([string]::IsNullOrWhiteSpace($script:snapshotPath) -or -not (Test-Path -LiteralPath $script:snapshotPath -PathType Leaf)) {
            throw 'pull-snapshot did not produce a readable snapshot file'
        }
        $script:lastSuccessfulSnapshot = $script:snapshotPath
        return [ordered]@{
            output_path = $script:snapshotPath
            details = [ordered]@{
                captured_at = $response.payload.captured_at
                row_count = $response.payload.row_count
                fetch_errors = $response.payload.fetch_errors
            }
        }
    }

    $underlyingArgs = @($underlyingTool.prefix_args + @(
            '--currency', $Currency,
            '--days', [string] $HistoryDays,
            '--output', $underlyingHistoryPath
        ))
    Invoke-Stage -Name 'underlying_history' -Command (Format-ExternalCommand -Executable $underlyingTool.display -Arguments $underlyingArgs) -Action {
        $response = Invoke-CheckedJsonCommand -Executable $underlyingTool.executable -Arguments $underlyingArgs -Context 'underlying-history'
        return [ordered]@{
            output_path = $underlyingHistoryPath
            details = [ordered]@{
                observation_count = $response.payload.observation_count
                first_observed_at = $response.payload.first_observed_at
                last_observed_at = $response.payload.last_observed_at
            }
        }
    } | Out-Null

    if ($CaptureDvolHistory) {
        $dvolArgs = @($dvolTool.prefix_args + @(
                '--currency', $Currency,
                '--days', [string] $DvolHistoryDays,
                '--output', $dvolHistoryPath
            ))
        Invoke-Stage -Name 'dvol_history' -Command (Format-ExternalCommand -Executable $dvolTool.display -Arguments $dvolArgs) -Action {
            $response = Invoke-CheckedJsonCommand -Executable $dvolTool.executable -Arguments $dvolArgs -Context 'dvol-history'
            return [ordered]@{
                output_path = $dvolHistoryPath
                details = [ordered]@{
                    observation_count = $response.payload.observation_count
                    first_observed_at = $response.payload.first_observed_at
                    last_observed_at = $response.payload.last_observed_at
                    missing_day_count = $response.payload.missing_day_count
                }
            }
        } | Out-Null
    }

    $seriesArgs = @($snapshotTool.prefix_args + @(
            'series-history',
            '--snapshot-dir', $seriesDir,
            '--output', $seriesHistoryPath,
            '--compact'
        ))
    Invoke-Stage -Name 'series_history' -Command (Format-ExternalCommand -Executable $snapshotTool.display -Arguments $seriesArgs) -Action {
        $response = Invoke-CheckedJsonCommand -Executable $snapshotTool.executable -Arguments $seriesArgs -Context 'series-history'
        return [ordered]@{
            output_path = $seriesHistoryPath
            details = [ordered]@{
                generated_at = $response.payload.generated_at
                instrument_count = $response.payload.instrument_count
                capture_count = $response.payload.capture_count
            }
        }
    } | Out-Null

    $signalArgs = @($snapshotTool.prefix_args + @(
            'validate-signal',
            '--preflight',
            '--snapshot-dir', $seriesDir,
            '--underlying-history-fixture', $underlyingHistoryPath,
            '--output', $signalPreflightPath,
            '--compact'
        ))
    $analysisTimestamp = [string] $snapshotResult.details.captured_at
    if (-not [string]::IsNullOrWhiteSpace($analysisTimestamp)) {
        $signalArgs += @('--generated-at', $analysisTimestamp)
    }
    Invoke-Stage -Name 'signal_preflight' -Command (Format-ExternalCommand -Executable $snapshotTool.display -Arguments $signalArgs) -Action {
        $response = Invoke-CheckedJsonCommand -Executable $snapshotTool.executable -Arguments $signalArgs -Context 'signal-preflight'
        return [ordered]@{
            output_path = $signalPreflightPath
            details = [ordered]@{
                status = $response.payload.status
                generated_at = $response.payload.generated_at
                reason_code = $response.payload.reason_code
            }
        }
    } | Out-Null

    if ($evidenceRepoPreflightEnabled) {
        $displayPath = if ([string]::IsNullOrWhiteSpace($EvidenceRepoRoot)) { '<unset>' } else { $EvidenceRepoRoot }
        $preflightCommand = "evidence-repo-preflight --root `"$displayPath`" --remote `"$EvidenceRepoRemote`""
        Invoke-Stage -Name 'evidence_repo_preflight' -Command $preflightCommand -Action {
            Invoke-EvidenceRepoPreflight -Path $EvidenceRepoRoot -RemoteName $EvidenceRepoRemote -ProductRepoRoot $RepoRoot
        } | Out-Null
    }

    Write-Log "captures in series: $((Get-ChildItem -LiteralPath $seriesDir -Filter '*.json' -File -ErrorAction SilentlyContinue).Count)"
}
catch {
    $failedStage = if ($script:StageResults.Count -gt 0) { $script:StageResults[$script:StageResults.Count - 1].name } else { 'unknown' }
    $failureMessage = $_.Exception.Message
}

$summary = [ordered]@{
    schema_version = 'capture_daily_summary.v1'
    run_id = "capture-daily-$currencyLower-$runStamp"
    status = if ($failureMessage) { 'failed' } else { 'ok' }
    currency = $Currency
    capture_time = if ($snapshotResult -and $snapshotResult.details -and $snapshotResult.details.captured_at) { $snapshotResult.details.captured_at } else { $runStartedAt }
    run_started_at = $runStartedAt
    repo_root = $RepoRoot
    summary_path = $summaryPath
    summary_latest_path = $latestSummaryPath
    failed_stage = $failedStage
    error = $failureMessage
    directories = [ordered]@{
        snapshots = $snapshotsRoot
        series = $seriesDir
        history = $historyDir
        logs = $logDir
        reports = $reportDir
    }
    outputs = [ordered]@{
        snapshot = $snapshotPath
        underlying_history = $underlyingHistoryPath
        dvol_history = if ($CaptureDvolHistory) { $dvolHistoryPath } else { $null }
        series_history = $seriesHistoryPath
        signal_preflight = $signalPreflightPath
    }
    last_successful_snapshot = $lastSuccessfulSnapshot
    options = [ordered]@{
        capture_dvol_history = [bool] $CaptureDvolHistory
        dvol_history_days = $DvolHistoryDays
        evidence_repo_root = if ([string]::IsNullOrWhiteSpace($EvidenceRepoRoot)) { $null } else { $EvidenceRepoRoot }
        evidence_repo_remote = $EvidenceRepoRemote
        evidence_repo_preflight = $evidenceRepoPreflightEnabled
    }
    webhook = [ordered]@{
        configured = -not [string]::IsNullOrWhiteSpace($FailureWebhookUrl)
        attempted = $false
        delivered = $null
        url = if ([string]::IsNullOrWhiteSpace($FailureWebhookUrl)) { $null } else { 'redacted' }
        error = $null
    }
    stages = $script:StageResults
}

if ($failureMessage -and -not [string]::IsNullOrWhiteSpace($FailureWebhookUrl)) {
    $summary.webhook = Send-FailureWebhook -Url $FailureWebhookUrl -Summary $summary
}

Write-CanonicalJson -Path $summaryPath -InputObject $summary
Write-CanonicalJson -Path $latestSummaryPath -InputObject $summary

if ($failureMessage) { exit 1 }
exit 0
