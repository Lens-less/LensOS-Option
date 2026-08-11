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

    When explicitly enabled, the script can reconcile the local artifacts tree
    against a separate evidence git repo, copy the unsynced durable evidence
    diff, then `git add` / `git commit` / `git push` that durable copy. Push
    failures are fatal and flow into the same failure summary + webhook path as
    capture failures.

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

.PARAMETER SuccessHeartbeatUrl
    Optional success-only heartbeat URL. When set, the script posts a redacted
    success ping only after capture plus evidence reconciliation finish cleanly.
    Delivery failures fail closed and are recorded in the summary.

.PARAMETER EvidenceRepoRoot
    Optional path to a separate evidence git repo. The repo must already exist,
    already be a git worktree, and already have a configured remote.

.PARAMETER EvidenceRepoRemote
    Remote name expected inside the evidence repo when preflight runs.

.PARAMETER EnableEvidenceRepoPreflight
    Run the explicit evidence-repo preflight stage. When omitted, the script
    also checks CAPTURE_DAILY_EVIDENCE_PREFLIGHT.

.PARAMETER EnableEvidenceRepoSync
    Opt into copying this run's snapshots/history/logs/reports into the
    separate evidence repo and pushing the resulting commit. When omitted, the
    script also checks CAPTURE_DAILY_EVIDENCE_SYNC.
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
    [string] $SuccessHeartbeatUrl,
    [string] $EvidenceRepoRoot,
    [string] $EvidenceRepoRemote = 'origin',
    [switch] $EnableEvidenceRepoPreflight,
    [switch] $EnableEvidenceRepoSync
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

function Resolve-NormalizedPath {
    param([Parameter(Mandatory)] [string] $Path)

    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    return [System.IO.Path]::GetFullPath($resolved).TrimEnd('\', '/')
}

function Test-PathWithin {
    param(
        [Parameter(Mandatory)] [string] $ChildPath,
        [Parameter(Mandatory)] [string] $ParentPath
    )

    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    $normalizedParent = $ParentPath.TrimEnd('\', '/')
    $prefix = $normalizedParent + [System.IO.Path]::DirectorySeparatorChar
    return $ChildPath.StartsWith($prefix, $comparison)
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

function Assert-RealDirectory {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [string] $Context = 'directory'
    )

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (-not $item.PSIsContainer) {
        throw "$Context must be a directory: $Path"
    }
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "reparse points are not allowed in evidence sync paths: $Path"
    }
}

function Ensure-RealDirectoryTree {
    param(
        [Parameter(Mandatory)] [string] $RootPath,
        [Parameter(Mandatory)] [string] $DirectoryPath
    )

    $resolvedRoot = Resolve-NormalizedPath -Path $RootPath
    $normalizedDirectory = [System.IO.Path]::GetFullPath($DirectoryPath).TrimEnd('\', '/')
    if ($normalizedDirectory -ne $resolvedRoot -and -not (
            Test-PathWithin -ChildPath $normalizedDirectory -ParentPath $resolvedRoot
        )) {
        throw "evidence sync destination escaped the evidence repo: $normalizedDirectory"
    }

    Assert-RealDirectory -Path $resolvedRoot -Context 'evidence repo root'
    $relative = $normalizedDirectory.Substring($resolvedRoot.Length).TrimStart('\', '/')
    $current = $resolvedRoot
    foreach ($segment in @($relative -split '[\\/]' | Where-Object { $_ })) {
        $current = Join-Path $current $segment
        if (-not (Test-Path -LiteralPath $current)) {
            New-Item -ItemType Directory -Path $current -ErrorAction Stop | Out-Null
        }
        Assert-RealDirectory -Path $current -Context 'evidence sync destination ancestor'
    }
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
    $python = Get-Command -Name 'python' -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "capture tooling is unavailable: neither $CommandName nor python could be resolved"
    }
    return [ordered]@{
        executable = $python.Source
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
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 promotes native stderr to its error stream.
        # Commands such as `git push` write ordinary progress there even on a
        # zero exit, so rely on the native exit code instead of terminating on
        # the presence of stderr text.
        $ErrorActionPreference = 'Continue'
        & $Executable @Arguments 1> $stdoutFile 2> $stderrFile
        $exitCode = if ($null -ne $LASTEXITCODE) { [int] $LASTEXITCODE } else { 0 }
        return [ordered]@{
            exit_code = $exitCode
            stdout = [System.IO.File]::ReadAllText($stdoutFile)
            stderr = [System.IO.File]::ReadAllText($stderrFile)
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-GitChecked {
    param(
        [Parameter(Mandatory)] [string] $RepoRoot,
        [Parameter(Mandatory)] [string[]] $Arguments,
        [Parameter(Mandatory)] [string] $Context
    )

    $gitArguments = @('-C', $RepoRoot) + $Arguments
    $result = Invoke-ExternalCommand -Executable 'git' -Arguments $gitArguments
    if ($result.exit_code -ne 0) {
        $stderr = $result.stderr.Trim()
        if ([string]::IsNullOrWhiteSpace($stderr)) {
            $stderr = $result.stdout.Trim()
        }
        if ([string]::IsNullOrWhiteSpace($stderr)) {
            $stderr = "$Context failed"
        }
        throw "$Context failed with exit code $($result.exit_code): $stderr"
    }
    return $result
}

function Get-GitCommonDirChecked {
    param([Parameter(Mandatory)] [string] $RepoRoot)

    $result = Invoke-GitChecked -RepoRoot $RepoRoot -Arguments @(
        'rev-parse', '--git-common-dir'
    ) -Context 'git common directory identity check'
    $commonDir = $result.stdout.Trim()
    if ([string]::IsNullOrWhiteSpace($commonDir)) {
        throw 'git common directory identity check returned an empty path'
    }
    if ([System.IO.Path]::IsPathRooted($commonDir)) {
        return [System.IO.Path]::GetFullPath($commonDir).TrimEnd('\', '/')
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $commonDir)).TrimEnd('\', '/')
}

function Get-GitRemoteUrlsForNameChecked {
    param(
        [Parameter(Mandatory)] [string] $RepoRoot,
        [Parameter(Mandatory)] [string] $RemoteName,
        [Parameter(Mandatory)] [string] $ContextPrefix
    )

    $urls = [System.Collections.Generic.List[string]]::new()
    foreach ($mode in @('fetch', 'push')) {
        $arguments = if ($mode -eq 'push') {
            @('remote', 'get-url', '--push', '--all', $RemoteName)
        }
        else {
            @('remote', 'get-url', '--all', $RemoteName)
        }
        $remoteResult = Invoke-GitChecked -RepoRoot $RepoRoot -Arguments $arguments -Context "$ContextPrefix $mode URL lookup for $RemoteName"
        foreach ($url in @($remoteResult.stdout -split "`r?`n")) {
            $url = $url.Trim()
            if (-not [string]::IsNullOrWhiteSpace($url) -and -not $urls.Contains($url)) {
                $urls.Add($url)
            }
        }
    }
    if ($urls.Count -eq 0) {
        throw "$ContextPrefix lookup returned no URLs for $RemoteName"
    }
    return $urls.ToArray()
}

function Get-GitRemoteUrlsChecked {
    param([Parameter(Mandatory)] [string] $RepoRoot)

    $result = Invoke-GitChecked -RepoRoot $RepoRoot -Arguments @('remote') -Context 'git remote identity list'
    $remoteNames = @(
        $result.stdout -split "`r?`n" |
        ForEach-Object { $_.Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($remoteNames.Count -eq 0) {
        throw 'product repo must configure at least one git remote for evidence identity checks'
    }
    $urls = [System.Collections.Generic.List[string]]::new()
    foreach ($remoteName in $remoteNames) {
        foreach ($url in @(Get-GitRemoteUrlsForNameChecked -RepoRoot $RepoRoot -RemoteName $remoteName -ContextPrefix 'git remote identity')) {
            if (-not $urls.Contains($url)) {
                $urls.Add($url)
            }
        }
    }
    if ($urls.Count -eq 0) {
        throw 'product repo git remote identity lookup returned no URLs'
    }
    return $urls.ToArray()
}

function ConvertTo-GitRemoteIdentity {
    param(
        [Parameter(Mandatory)] [string] $Url,
        [Parameter(Mandatory)] [string] $RepoRoot
    )

    $candidate = $Url.Trim()
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        throw 'git remote identity URL must not be empty'
    }

    if ([System.IO.Path]::IsPathRooted($candidate)) {
        $localPath = [System.IO.Path]::GetFullPath($candidate).TrimEnd('\', '/')
        return 'file:' + $localPath.ToLowerInvariant()
    }

    $parsedUri = $null
    if (
        [System.Uri]::TryCreate(
            $candidate,
            [System.UriKind]::Absolute,
            [ref] $parsedUri
        ) -and
        -not [string]::IsNullOrWhiteSpace($parsedUri.Host)
    ) {
        $hostName = $parsedUri.Host.ToLowerInvariant()
        $remotePath = [System.Uri]::UnescapeDataString($parsedUri.AbsolutePath)
    }
    elseif ($candidate -match '^(?:[^@/\s]+@)?(?<host>[A-Za-z0-9._-]+):(?<path>.+)$') {
        $hostName = $Matches.host.ToLowerInvariant()
        $remotePath = $Matches.path
    }
    elseif ($candidate.StartsWith('.', [System.StringComparison]::Ordinal)) {
        $localPath = [System.IO.Path]::GetFullPath(
            (Join-Path $RepoRoot $candidate)
        ).TrimEnd('\', '/')
        return 'file:' + $localPath.ToLowerInvariant()
    }
    else {
        throw 'git remote identity URL format is unsupported'
    }

    $remotePath = $remotePath.Replace('\', '/').Trim('/')
    while ($remotePath.Contains('//')) {
        $remotePath = $remotePath.Replace('//', '/')
    }
    if ($remotePath.EndsWith('.git', [System.StringComparison]::OrdinalIgnoreCase)) {
        $remotePath = $remotePath.Substring(0, $remotePath.Length - 4)
    }
    if ([string]::IsNullOrWhiteSpace($remotePath)) {
        throw 'git remote identity URL does not contain a repository path'
    }
    if ($hostName -eq 'github.com') {
        $remotePath = $remotePath.ToLowerInvariant()
    }
    return "remote:$hostName/$remotePath"
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory)] [string] $RootPath,
        [Parameter(Mandatory)] [string] $ChildPath
    )

    $resolvedRoot = Resolve-NormalizedPath -Path $RootPath
    $resolvedChild = Resolve-NormalizedPath -Path $ChildPath
    if (-not (Test-PathWithin -ChildPath $resolvedChild -ParentPath $resolvedRoot)) {
        throw "path does not live under root: $resolvedChild"
    }
    return $resolvedChild.Substring($resolvedRoot.Length).TrimStart('\', '/').Replace('\', '/')
}

function Get-FileSha256Hex {
    param([Parameter(Mandatory)] [string] $Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}

function Add-UniqueString {
    param(
        [System.Collections.Generic.List[string]] $List,
        [string] $Value
    )

    if ($null -eq $List) {
        throw 'Add-UniqueString requires a destination list'
    }
    if (-not [string]::IsNullOrWhiteSpace($Value) -and -not $List.Contains($Value)) {
        $List.Add($Value) | Out-Null
    }
}

function Get-ManagedArtifactRelativePaths {
    param([Parameter(Mandatory)] [string] $ArtifactsRoot)

    $relativePaths = [System.Collections.Generic.List[string]]::new()

    $snapshotsRoot = Join-Path $ArtifactsRoot 'snapshots'
    if (Test-Path -LiteralPath $snapshotsRoot) {
        foreach ($item in Get-ChildItem -LiteralPath $snapshotsRoot -Recurse -File -ErrorAction SilentlyContinue) {
            Add-UniqueString -List $relativePaths -Value (Get-RelativePath -RootPath $ArtifactsRoot -ChildPath $item.FullName)
        }
    }

    $historyRoot = Join-Path $ArtifactsRoot 'history'
    if (Test-Path -LiteralPath $historyRoot) {
        foreach ($item in Get-ChildItem -LiteralPath $historyRoot -File -ErrorAction SilentlyContinue) {
            Add-UniqueString -List $relativePaths -Value (Get-RelativePath -RootPath $ArtifactsRoot -ChildPath $item.FullName)
        }
    }

    $signalPreflight = Join-Path $ArtifactsRoot 'reports/signal-preflight.json'
    if (Test-Path -LiteralPath $signalPreflight) {
        Add-UniqueString -List $relativePaths -Value (Get-RelativePath -RootPath $ArtifactsRoot -ChildPath $signalPreflight)
    }

    $receiptRoot = Join-Path $ArtifactsRoot 'logs'
    if (Test-Path -LiteralPath $receiptRoot) {
        foreach ($item in Get-ChildItem -LiteralPath $receiptRoot -Filter 'capture-daily-*.receipt.json' -File -ErrorAction SilentlyContinue) {
            Add-UniqueString -List $relativePaths -Value (Get-RelativePath -RootPath $ArtifactsRoot -ChildPath $item.FullName)
        }
    }

    return @($relativePaths | Sort-Object)
}

function Get-UnsyncedLocalArtifacts {
    param(
        [Parameter(Mandatory)] [string] $ProductArtifactsRoot,
        [Parameter(Mandatory)] [string] $EvidenceRepoRoot
    )

    $relativePaths = Get-ManagedArtifactRelativePaths -ArtifactsRoot $ProductArtifactsRoot
    $unsynced = [System.Collections.Generic.List[object]]::new()
    foreach ($relativePath in $relativePaths) {
        $localPath = Join-Path $ProductArtifactsRoot $relativePath
        $evidencePath = Join-Path $EvidenceRepoRoot $relativePath
        if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
            $unsynced.Add([ordered]@{
                    relative_path = $relativePath
                    source_path = $localPath
                    reason = 'missing'
                }) | Out-Null
            continue
        }
        $localHash = Get-FileSha256Hex -Path $localPath
        $evidenceHash = Get-FileSha256Hex -Path $evidencePath
        if ($localHash -ne $evidenceHash) {
            $unsynced.Add([ordered]@{
                    relative_path = $relativePath
                    source_path = $localPath
                    reason = 'content_mismatch'
                }) | Out-Null
        }
    }
    return $unsynced
}

function Get-UnsyncedLocalCaptureRunCount {
    param(
        [Parameter(Mandatory)] [string] $ProductArtifactsRoot,
        [Parameter(Mandatory)] [string] $EvidenceRepoRoot,
        [Parameter(Mandatory)] [string] $RemoteName
    )

    $receiptRoot = Join-Path $ProductArtifactsRoot 'logs'
    if (-not (Test-Path -LiteralPath $receiptRoot -PathType Container)) {
        return 0
    }
    $receipts = @(
        Get-ChildItem -LiteralPath $receiptRoot -Filter 'capture-daily-*.receipt.json' -File -ErrorAction Stop |
        Sort-Object -Property Name
    )
    if ($receipts.Count -eq 0) {
        return 0
    }

    $receiptsByRunId = @{}
    foreach ($receipt in $receipts) {
        $payload = Get-Content -Raw -LiteralPath $receipt.FullName -ErrorAction Stop |
            ConvertFrom-Json -ErrorAction Stop
        if ([string] $payload.schema_version -ne 'capture_daily_receipt.v1') {
            throw "local capture receipt has an unexpected schema: $($receipt.FullName)"
        }
        $runId = [string] $payload.run_id
        if ([string]::IsNullOrWhiteSpace($runId)) {
            throw "local capture receipt is missing run_id: $($receipt.FullName)"
        }
        $contentHash = Get-FileSha256Hex -Path $receipt.FullName
        if (-not $receiptsByRunId.ContainsKey($runId)) {
            $receiptsByRunId[$runId] = [ordered]@{
                content_sha256 = $contentHash
                receipts = [System.Collections.Generic.List[object]]::new()
            }
        }
        elseif ($receiptsByRunId[$runId].content_sha256 -ne $contentHash) {
            throw "local capture receipts reuse run_id with different content: $runId"
        }
        $receiptsByRunId[$runId].receipts.Add($receipt) | Out-Null
    }

    $branch = Get-EvidenceRepoBranch -RepoRoot $EvidenceRepoRoot
    $remoteRef = "refs/remotes/$RemoteName/$branch"
    $remoteCommit = Invoke-ExternalCommand -Executable 'git' -Arguments @(
        '-C', $EvidenceRepoRoot, 'rev-parse', '--verify', "$remoteRef^{commit}"
    )
    if ($remoteCommit.exit_code -ne 0) {
        return $receiptsByRunId.Count
    }

    $unsyncedRunCount = 0
    foreach ($runId in @($receiptsByRunId.Keys | Sort-Object)) {
        $runIsSynced = $false
        foreach ($receipt in $receiptsByRunId[$runId].receipts) {
            $relativePath = Get-RelativePath -RootPath $ProductArtifactsRoot -ChildPath $receipt.FullName
            $localBlob = Invoke-GitChecked -RepoRoot $EvidenceRepoRoot -Arguments @(
                'hash-object', "--path=$relativePath", '--', $receipt.FullName
            ) -Context 'local capture receipt git hash'
            $remoteBlob = Invoke-ExternalCommand -Executable 'git' -Arguments @(
                '-C', $EvidenceRepoRoot, 'rev-parse', '--verify', "${remoteRef}:$relativePath"
            )
            if (
                $remoteBlob.exit_code -eq 0 `
                -and $remoteBlob.stdout.Trim() -eq $localBlob.stdout.Trim()
            ) {
                $runIsSynced = $true
                break
            }
        }
        if (-not $runIsSynced) {
            $unsyncedRunCount++
        }
    }
    return $unsyncedRunCount
}

function Update-UnsyncedLocalCaptureCount {
    $script:UnsyncedLocalCaptureCount = $null
    if ([string]::IsNullOrWhiteSpace($EvidenceRepoRoot) -or -not (Test-Path -LiteralPath $EvidenceRepoRoot)) {
        return
    }
    try {
        $script:UnsyncedLocalCaptureCount = Get-UnsyncedLocalCaptureRunCount `
            -ProductArtifactsRoot $artifactsRoot `
            -EvidenceRepoRoot $EvidenceRepoRoot `
            -RemoteName $EvidenceRepoRemote
    }
    catch {
        $script:UnsyncedLocalCaptureCount = $null
    }
}

function Copy-EvidenceRepoSeedToLocalArtifacts {
    param(
        [Parameter(Mandatory)] [string] $EvidenceRepoRoot,
        [Parameter(Mandatory)] [string] $ArtifactsRoot,
        [Parameter(Mandatory)] [string] $CurrencyLower
    )

    $seedRelativePaths = [System.Collections.Generic.List[string]]::new()
    $snapshotsRoot = Join-Path $EvidenceRepoRoot 'snapshots'
    if (Test-Path -LiteralPath $snapshotsRoot) {
        foreach ($item in Get-ChildItem -LiteralPath $snapshotsRoot -Recurse -File -ErrorAction SilentlyContinue) {
            Add-UniqueString -List $seedRelativePaths -Value (Get-RelativePath -RootPath $EvidenceRepoRoot -ChildPath $item.FullName)
        }
    }
    foreach ($relativePath in @(
            "history/$CurrencyLower-daily.json",
            "history/$CurrencyLower-dvol.json",
            'logs/capture-daily.log'
        )) {
        if (Test-Path -LiteralPath (Join-Path $EvidenceRepoRoot $relativePath)) {
            Add-UniqueString -List $seedRelativePaths -Value $relativePath
        }
    }

    foreach ($relativePath in $seedRelativePaths) {
        $sourcePath = Join-Path $EvidenceRepoRoot $relativePath
        $destinationPath = Join-Path $ArtifactsRoot $relativePath
        if (Test-Path -LiteralPath $destinationPath) {
            continue
        }
        Ensure-Directory -Path (Split-Path -Parent $destinationPath)
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -ErrorAction Stop
    }
}

function Assert-EvidencePathsNotIgnored {
    param(
        [Parameter(Mandatory)] [string] $RepoRoot,
        [Parameter(Mandatory)] [string[]] $RelativePaths
    )

    if ($RelativePaths.Count -eq 0) {
        return
    }

    $stdinPath = [System.IO.Path]::GetTempFileName()
    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    try {
        [System.IO.File]::WriteAllText(
            $stdinPath,
            ($RelativePaths -join [Environment]::NewLine) + [Environment]::NewLine,
            $utf8NoBom
        )
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            Get-Content -LiteralPath $stdinPath | & git -C $RepoRoot check-ignore --stdin 1> $stdoutPath 2> $stderrPath
            $exitCode = if ($null -ne $LASTEXITCODE) { [int] $LASTEXITCODE } else { 0 }
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        if ($exitCode -eq 0) {
            $ignored = @(
                [System.IO.File]::ReadAllText($stdoutPath) -split "`r?`n" |
                ForEach-Object { $_.Trim() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
            )
            throw "evidence repo .gitignore matches managed sync paths: $($ignored -join ', ')"
        }
        if ($exitCode -ne 1) {
            $stderr = [System.IO.File]::ReadAllText($stderrPath).Trim()
            if ([string]::IsNullOrWhiteSpace($stderr)) {
                $stderr = 'git check-ignore failed'
            }
            throw $stderr
        }
    }
    finally {
        Remove-Item -LiteralPath $stdinPath, $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-EvidenceRepoPushWithRetry {
    param(
        [Parameter(Mandatory)] [string] $RepoRoot,
        [Parameter(Mandatory)] [string] $RemoteName,
        [Parameter(Mandatory)] [string] $Branch
    )

    $maxAttempts = 3
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $pushResult = Invoke-ExternalCommand -Executable 'git' -Arguments @('-C', $RepoRoot, 'push', $RemoteName, "HEAD:$Branch")
        if ($pushResult.exit_code -eq 0) {
            Invoke-GitChecked -RepoRoot $RepoRoot -Arguments @(
                'fetch', $RemoteName,
                "+refs/heads/${Branch}:refs/remotes/${RemoteName}/${Branch}"
            ) -Context 'evidence repo post-push remote verification fetch' | Out-Null
            $localHead = Invoke-GitChecked -RepoRoot $RepoRoot -Arguments @(
                'rev-parse', '--verify', 'HEAD^{commit}'
            ) -Context 'evidence repo local HEAD verification'
            $remoteHead = Invoke-GitChecked -RepoRoot $RepoRoot -Arguments @(
                'rev-parse', '--verify', "refs/remotes/${RemoteName}/${Branch}^{commit}"
            ) -Context 'evidence repo remote HEAD verification'
            if ($localHead.stdout.Trim() -ne $remoteHead.stdout.Trim()) {
                throw 'evidence repo push verification did not observe the local commit on the remote branch'
            }
            return $attempt
        }

        $stderr = $pushResult.stderr.Trim()
        if ([string]::IsNullOrWhiteSpace($stderr)) {
            $stderr = $pushResult.stdout.Trim()
        }
        if ([string]::IsNullOrWhiteSpace($stderr)) {
            $stderr = 'git push failed'
        }

        if ($attempt -ge $maxAttempts -or $stderr -notmatch 'non-fast-forward|fetch first|rejected') {
            throw "git push failed with exit code $($pushResult.exit_code): $stderr"
        }

        Write-Log "retrying evidence repo push after remote update attempt=$attempt"
        Invoke-GitChecked -RepoRoot $RepoRoot -Arguments @('fetch', $RemoteName, $Branch) -Context 'evidence repo git fetch' | Out-Null
        $rebaseResult = Invoke-ExternalCommand -Executable 'git' -Arguments @('-C', $RepoRoot, 'rebase', "$RemoteName/$Branch")
        if ($rebaseResult.exit_code -ne 0) {
            Invoke-ExternalCommand -Executable 'git' -Arguments @('-C', $RepoRoot, 'rebase', '--abort') | Out-Null
            $rebaseError = $rebaseResult.stderr.Trim()
            if ([string]::IsNullOrWhiteSpace($rebaseError)) {
                $rebaseError = $rebaseResult.stdout.Trim()
            }
            if ([string]::IsNullOrWhiteSpace($rebaseError)) {
                $rebaseError = 'evidence repo rebase failed'
            }
            throw "evidence repo rebase failed with exit code $($rebaseResult.exit_code): $rebaseError"
        }
        Start-Sleep -Seconds $attempt
    }

    throw 'git push retry loop exhausted unexpectedly'
}

function Invoke-NotificationRequest {
    param(
        [Parameter(Mandatory)] [string] $Url,
        [Parameter(Mandatory)] [string] $Body,
        [switch] $IncludeRedactedUrl
    )

    $state = [ordered]@{
        configured = $true
        attempted = $false
        delivered = $null
        delivery_attempts = 0
        error = $null
    }
    if ($IncludeRedactedUrl.IsPresent) {
        $state.url = 'redacted'
    }

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $state.attempted = $true
        $state.delivery_attempts = $attempt
        try {
            Invoke-WebRequest -Method Post -Uri $Url -ContentType 'application/json; charset=utf-8' -Body $Body -TimeoutSec 15 -UseBasicParsing | Out-Null
            $state.delivered = $true
            return $state
        }
        catch {
            if ($attempt -lt 3) {
                Start-Sleep -Seconds ([int] [Math]::Pow(2, $attempt - 1))
                continue
            }
            $state.delivered = $false
            $state.error = 'delivery failed'
            return $state
        }
    }

    throw 'notification retry loop exhausted unexpectedly'
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
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.IO.StreamWriter]::new($script:LogFile, $true, $utf8NoBom)
    try {
        $writer.WriteLine("$stamp  $Message")
    }
    finally {
        $writer.Dispose()
    }
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

    $resolvedEvidenceRoot = Resolve-NormalizedPath -Path $Path
    $resolvedProductRoot = Resolve-NormalizedPath -Path $ProductRepoRoot
    Assert-RealDirectory -Path $resolvedEvidenceRoot -Context 'evidence repo root'
    if ($resolvedEvidenceRoot -eq $resolvedProductRoot) {
        throw 'evidence repo root must not be the product repo root'
    }
    if (Test-PathWithin -ChildPath $resolvedEvidenceRoot -ParentPath $resolvedProductRoot) {
        throw 'evidence repo root must live outside the product repo tree'
    }
    if (Test-PathWithin -ChildPath $resolvedProductRoot -ParentPath $resolvedEvidenceRoot) {
        throw 'product repo root must not live inside the evidence repo tree'
    }

    $gitTopLevel = Invoke-GitChecked -RepoRoot $resolvedEvidenceRoot -Arguments @('rev-parse', '--show-toplevel') -Context 'evidence repo git root'
    $topLevelPath = $gitTopLevel.stdout.Trim()
    if ([string]::IsNullOrWhiteSpace($topLevelPath)) {
        throw "evidence repo is not a git worktree: $resolvedEvidenceRoot"
    }
    $topLevelPath = Resolve-NormalizedPath -Path $topLevelPath
    if ($topLevelPath -ne $resolvedEvidenceRoot) {
        throw 'evidence repo root must point at the git toplevel, not a subdirectory'
    }

    $evidenceCommonDir = Get-GitCommonDirChecked -RepoRoot $resolvedEvidenceRoot
    $productCommonDir = Get-GitCommonDirChecked -RepoRoot $resolvedProductRoot
    if ($evidenceCommonDir.Equals($productCommonDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'evidence repo git-common-dir must not match the product repo git-common-dir'
    }

    $remote = Invoke-GitChecked -RepoRoot $resolvedEvidenceRoot -Arguments @('remote', 'get-url', $RemoteName) -Context "evidence repo remote $RemoteName"
    $evidenceRemoteUrl = $remote.stdout.Trim()
    if ([string]::IsNullOrWhiteSpace($evidenceRemoteUrl)) {
        throw "evidence repo remote is not configured: $RemoteName"
    }
    $evidenceRemoteUrls = @(
        Get-GitRemoteUrlsForNameChecked -RepoRoot $resolvedEvidenceRoot -RemoteName $RemoteName -ContextPrefix 'evidence repo remote identity'
    )
    $evidenceRemoteIdentities = @(
        $evidenceRemoteUrls |
        ForEach-Object {
            ConvertTo-GitRemoteIdentity -Url $_ -RepoRoot $resolvedEvidenceRoot
        }
    )
    $productRemoteIdentities = @(
        Get-GitRemoteUrlsChecked -RepoRoot $resolvedProductRoot |
        ForEach-Object {
            ConvertTo-GitRemoteIdentity -Url $_ -RepoRoot $resolvedProductRoot
        }
    )
    if (@($evidenceRemoteIdentities | Where-Object { $productRemoteIdentities -contains $_ }).Count -gt 0) {
        throw 'evidence repo remote must not match any product repo remote'
    }

    $requiredDirectories = @('snapshots', 'history', 'logs', 'reports')
    $checks = foreach ($dir in $requiredDirectories) {
        $fullPath = Join-Path $resolvedEvidenceRoot $dir
        $item = Get-Item -LiteralPath $fullPath -ErrorAction SilentlyContinue
        [ordered]@{
            directory = $dir
            path = $fullPath
            exists = [bool] ($item -and $item.PSIsContainer)
            reparse_point = [bool] ($item -and ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint))
        }
    }
    $missing = @($checks | Where-Object { -not $_.exists })
    if ($missing.Count -gt 0) {
        $names = ($missing | ForEach-Object { $_.directory }) -join ', '
        throw "evidence repo is missing required directories: $names"
    }
    $linked = @($checks | Where-Object { $_.reparse_point })
    if ($linked.Count -gt 0) {
        $names = ($linked | ForEach-Object { $_.directory }) -join ', '
        throw "evidence repo required directories must not be reparse points: $names"
    }

    $status = Invoke-GitChecked -RepoRoot $resolvedEvidenceRoot -Arguments @(
        'status', '--porcelain=v1', '--untracked-files=all'
    ) -Context 'evidence repo clean-worktree check'
    if (-not [string]::IsNullOrWhiteSpace($status.stdout)) {
        throw 'evidence repo must be clean before sync'
    }

    return [ordered]@{
        output_path = $resolvedEvidenceRoot
        details = [ordered]@{
            repo_root = $resolvedEvidenceRoot
            remote_name = $RemoteName
            remote_url = $evidenceRemoteUrl
            remote_urls = $evidenceRemoteUrls
            remote_configured = $true
            required_directories = $checks
            sync_ready = $true
        }
    }
}

function Copy-ArtifactIntoEvidenceRepo {
    param(
        [Parameter(Mandatory)] [string] $SourcePath,
        [Parameter(Mandatory)] [string] $DestinationPath,
        [Parameter(Mandatory)] [string] $EvidenceRepoRoot
    )

    $sourceItem = Get-Item -LiteralPath $SourcePath -Force -ErrorAction SilentlyContinue
    if (-not $sourceItem -or $sourceItem.PSIsContainer) {
        throw "evidence sync source is missing: $SourcePath"
    }
    if ($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "evidence sync source must not be a reparse point: $SourcePath"
    }

    $destinationParent = Split-Path -Parent $DestinationPath
    Ensure-RealDirectoryTree -RootPath $EvidenceRepoRoot -DirectoryPath $destinationParent

    if (Test-Path -LiteralPath $DestinationPath) {
        $destinationItem = Get-Item -LiteralPath $DestinationPath -Force -ErrorAction Stop
        if ($destinationItem.PSIsContainer) {
            throw "evidence sync destination exists as a directory: $DestinationPath"
        }
        if ($destinationItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "evidence sync destination must not be a reparse point: $DestinationPath"
        }
    }

    $temporaryDestination = Join-Path $destinationParent (
        ".lensos-sync-$([Guid]::NewGuid().ToString('N')).tmp"
    )
    try {
        Copy-Item -LiteralPath $SourcePath -Destination $temporaryDestination -ErrorAction Stop
        if (Test-Path -LiteralPath $DestinationPath) {
            Remove-Item -LiteralPath $DestinationPath -Force -ErrorAction Stop
        }
        Move-Item -LiteralPath $temporaryDestination -Destination $DestinationPath -ErrorAction Stop
    }
    finally {
        if (Test-Path -LiteralPath $temporaryDestination) {
            Remove-Item -LiteralPath $temporaryDestination -Force -ErrorAction SilentlyContinue
        }
    }
    return $DestinationPath
}

function Get-EvidenceRepoBranch {
    param([Parameter(Mandatory)] [string] $RepoRoot)

    $result = Invoke-GitChecked -RepoRoot $RepoRoot -Arguments @('symbolic-ref', '--quiet', '--short', 'HEAD') -Context 'evidence repo branch'
    $branch = $result.stdout.Trim()
    if ([string]::IsNullOrWhiteSpace($branch) -or $branch -eq 'HEAD') {
        throw 'evidence repo must be on a named branch before sync'
    }
    return $branch
}

function Invoke-EvidenceRepoSync {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [string] $RemoteName,
        [Parameter(Mandatory)] [string] $ProductRepoRoot
    )

    $preflight = Invoke-EvidenceRepoPreflight -Path $Path -RemoteName $RemoteName -ProductRepoRoot $ProductRepoRoot
    $resolvedEvidenceRoot = [string] $preflight.output_path
    $branch = Get-EvidenceRepoBranch -RepoRoot $resolvedEvidenceRoot
    $productArtifactsRoot = Join-Path $ProductRepoRoot 'artifacts'
    $unsyncedArtifacts = @(
        Get-UnsyncedLocalArtifacts -ProductArtifactsRoot $productArtifactsRoot -EvidenceRepoRoot $resolvedEvidenceRoot
    )
    $copiedRelativePaths = [System.Collections.Generic.List[string]]::new()
    foreach ($artifact in $unsyncedArtifacts) {
        $resolvedSource = Resolve-NormalizedPath -Path $artifact.source_path
        $sourceRoot = Resolve-NormalizedPath -Path $productArtifactsRoot
        if (-not (Test-PathWithin -ChildPath $resolvedSource -ParentPath $sourceRoot)) {
            throw "evidence sync source must stay inside the product artifacts directory: $resolvedSource"
        }
        $relativePath = [string] $artifact.relative_path
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            throw "evidence sync source produced an empty relative path: $resolvedSource"
        }
        $destination = Join-Path $resolvedEvidenceRoot $relativePath
        Copy-ArtifactIntoEvidenceRepo -SourcePath $resolvedSource -DestinationPath $destination -EvidenceRepoRoot $resolvedEvidenceRoot | Out-Null
        if (-not $copiedRelativePaths.Contains($relativePath)) {
            $copiedRelativePaths.Add($relativePath)
        }
    }

    Assert-EvidencePathsNotIgnored -RepoRoot $resolvedEvidenceRoot -RelativePaths $copiedRelativePaths.ToArray()
    if ($copiedRelativePaths.Count -gt 0) {
        $gitAddArguments = @('add', '--') + $copiedRelativePaths.ToArray()
        Invoke-GitChecked -RepoRoot $resolvedEvidenceRoot -Arguments $gitAddArguments -Context 'evidence repo git add' | Out-Null
    }

    $cachedDiff = Invoke-ExternalCommand -Executable 'git' -Arguments @('-C', $resolvedEvidenceRoot, 'diff', '--cached', '--quiet', '--')
    $commitCreated = $false
    if ($cachedDiff.exit_code -eq 0) {
        Write-Log 'evidence repo has no new staged artifact diff; reconciling any previously committed push'
    }
    elseif ($cachedDiff.exit_code -eq 1) {
        $commitMessage = @(
            'Preserve daily market evidence outside the product workspace',
            '',
            'Constraint: Deribit option-chain captures cannot be backfilled',
            'Confidence: high',
            'Scope-risk: narrow',
            "Tested: capture-daily evidence sync $script:RunId"
        ) -join [Environment]::NewLine
        Invoke-GitChecked -RepoRoot $resolvedEvidenceRoot -Arguments @(
            '-c', 'user.name=LensOS Capture Bot',
            '-c', 'user.email=lensos-capture-bot@users.noreply.github.com',
            'commit', '-m', $commitMessage
        ) -Context 'evidence repo git commit' | Out-Null
        $commitCreated = $true
    }
    else {
        throw 'evidence repo staged diff check failed'
    }

    $pushAttempts = Invoke-EvidenceRepoPushWithRetry -RepoRoot $resolvedEvidenceRoot -RemoteName $RemoteName -Branch $branch

    return [ordered]@{
        output_path = $resolvedEvidenceRoot
        details = [ordered]@{
            repo_root = $resolvedEvidenceRoot
            remote_name = $RemoteName
            branch = $branch
            mode = if ($commitCreated) { 'pushed' } else { 'reconciled' }
            push_attempts = $pushAttempts
            copied_paths = $copiedRelativePaths
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
    return Invoke-NotificationRequest -Url $Url -Body $body -IncludeRedactedUrl
}

function Send-SuccessHeartbeat {
    param(
        [Parameter(Mandatory)] [string] $Url,
        [Parameter(Mandatory)] $Summary
    )

    $payload = [ordered]@{
        schema_version = 'capture_daily_success_heartbeat.v1'
        run_id = $Summary.run_id
        currency = $Summary.currency
        status = $Summary.status
        captured_at = $Summary.capture_time
        summary_file = if ($Summary.summary_path) { Split-Path -Leaf $Summary.summary_path } else { $null }
        last_successful_snapshot_file = if ($Summary.last_successful_snapshot) { Split-Path -Leaf $Summary.last_successful_snapshot } else { $null }
        unsynced_local_capture_count = $Summary.unsynced_local_capture_count
    }

    $body = ConvertTo-CanonicalJson -InputObject $payload
    return Invoke-NotificationRequest -Url $Url -Body $body
}

$evidenceRepoSyncEnabled = $false
$evidenceRepoPreflightEnabled = $false
$script:StageResults = [System.Collections.Generic.List[object]]::new()
$script:UnsyncedLocalCaptureCount = $null
$runStartedAt = Get-IsoTimestamp
$runStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ')
$script:RunId = "capture-daily-bootstrap-$runStamp"
$currencyLower = $null
$artifactsRoot = $null
$snapshotsRoot = $null
$seriesDir = $null
$historyDir = $null
$logDir = $null
$reportDir = $null
$script:LogFile = $null
$summaryPath = $null
$latestSummaryPath = $null
$receiptPath = $null
$snapshotTool = $null
$underlyingTool = $null
$dvolTool = $null
$snapshotResult = $null
$snapshotPath = $null
$underlyingHistoryPath = $null
$dvolHistoryPath = $null
$seriesHistoryPath = $null
$signalPreflightPath = $null
$lastSuccessfulSnapshot = $null
$failedStage = $null
$failureMessage = $null
$currentPhase = 'bootstrap'
$webhookState = [ordered]@{
    configured = $false
    attempted = $false
    delivered = $null
    delivery_attempts = 0
    url = $null
    error = $null
}
$successHeartbeatState = [ordered]@{
    configured = $false
    attempted = $false
    delivered = $null
    delivery_attempts = 0
    error = $null
}

function New-CaptureSummary {
    Update-UnsyncedLocalCaptureCount
    $receiptSyncStatus = if ($evidenceRepoSyncEnabled) { 'pending' } else { 'not_requested' }
    foreach ($stageResult in $script:StageResults) {
        if ($stageResult.name -eq 'evidence_repo_sync') {
            $receiptSyncStatus = if ($stageResult.status -eq 'ok') { 'synchronized' } else { 'failed' }
        }
    }
    $summary = [ordered]@{
        schema_version = 'capture_daily_summary.v1'
        run_id = $script:RunId
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
        unsynced_local_capture_count = $script:UnsyncedLocalCaptureCount
        evidence_receipt = if ([string]::IsNullOrWhiteSpace($receiptPath)) {
            $null
        }
        else {
            [ordered]@{
                protocol = 'immutable_pre_sync_receipt.v1'
                path = $receiptPath
                phase = 'capture_complete_before_evidence_sync'
                immutable = $true
                sync_status = $receiptSyncStatus
            }
        }
        options = [ordered]@{
            capture_dvol_history = [bool] $CaptureDvolHistory
            dvol_history_days = $DvolHistoryDays
            evidence_repo_root = if ([string]::IsNullOrWhiteSpace($EvidenceRepoRoot)) { $null } else { $EvidenceRepoRoot }
            evidence_repo_remote = $EvidenceRepoRemote
            evidence_repo_preflight = $evidenceRepoPreflightEnabled
            evidence_repo_sync = $evidenceRepoSyncEnabled
        }
        webhook = $webhookState
        success_heartbeat = $successHeartbeatState
        stages = $script:StageResults
    }

    return $summary
}

function Write-CaptureSummary {
    if ([string]::IsNullOrWhiteSpace($summaryPath) -or [string]::IsNullOrWhiteSpace($latestSummaryPath)) {
        throw 'capture summary paths are unavailable'
    }

    $summary = New-CaptureSummary
    Write-CanonicalJson -Path $summaryPath -InputObject $summary
    Write-CanonicalJson -Path $latestSummaryPath -InputObject $summary
    return $summary
}

function New-ReceiptArtifactRecord {
    param([string] $Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    return [ordered]@{
        relative_path = Get-RelativePath -RootPath $artifactsRoot -ChildPath $Path
        sha256 = Get-FileSha256Hex -Path $Path
    }
}

function Write-CaptureReceipt {
    if ([string]::IsNullOrWhiteSpace($receiptPath)) {
        throw 'capture receipt path is unavailable'
    }
    if (Test-Path -LiteralPath $receiptPath) {
        throw "immutable capture receipt already exists: $receiptPath"
    }

    $captureStageNames = @(
        'snapshot',
        'underlying_history',
        'dvol_history',
        'series_history',
        'signal_preflight'
    )
    $captureStages = @(
        $script:StageResults |
        Where-Object { $captureStageNames -contains $_.name } |
        ForEach-Object {
            [ordered]@{
                name = $_.name
                status = $_.status
                started_at = $_.started_at
                finished_at = $_.finished_at
                duration_ms = $_.duration_ms
                details = $_.details
            }
        }
    )
    $receipt = [ordered]@{
        schema_version = 'capture_daily_receipt.v1'
        protocol = 'immutable_pre_sync_receipt.v1'
        run_id = $script:RunId
        status = 'capture_complete'
        currency = $Currency
        capture_time = if ($snapshotResult -and $snapshotResult.details -and $snapshotResult.details.captured_at) { $snapshotResult.details.captured_at } else { $runStartedAt }
        run_started_at = $runStartedAt
        artifacts = [ordered]@{
            snapshot = New-ReceiptArtifactRecord -Path $snapshotPath
            underlying_history = New-ReceiptArtifactRecord -Path $underlyingHistoryPath
            dvol_history = if ($CaptureDvolHistory) { New-ReceiptArtifactRecord -Path $dvolHistoryPath } else { $null }
            series_history = New-ReceiptArtifactRecord -Path $seriesHistoryPath
            signal_preflight = New-ReceiptArtifactRecord -Path $signalPreflightPath
        }
        capture_stages = $captureStages
        evidence_repo_sync = [ordered]@{
            status = 'pending'
            result_source = if ($summaryPath) { Split-Path -Leaf $summaryPath } else { $null }
            note = 'This immutable receipt intentionally precedes evidence sync; the local run summary records sync and heartbeat outcomes.'
        }
    }
    Write-CanonicalJson -Path $receiptPath -InputObject $receipt
    return [ordered]@{
        output_path = $receiptPath
        details = [ordered]@{
            protocol = 'immutable_pre_sync_receipt.v1'
            sha256 = Get-FileSha256Hex -Path $receiptPath
        }
    }
}

try {
    if (-not $FailureWebhookUrl) {
        $FailureWebhookUrl = [Environment]::GetEnvironmentVariable('CAPTURE_DAILY_FAILURE_WEBHOOK_URL')
    }
    if (-not $SuccessHeartbeatUrl) {
        $SuccessHeartbeatUrl = [Environment]::GetEnvironmentVariable('CAPTURE_DAILY_SUCCESS_HEARTBEAT_URL')
    }
    if (-not $SuccessHeartbeatUrl) {
        $SuccessHeartbeatUrl = [Environment]::GetEnvironmentVariable('CAPTURE_SUCCESS_HEARTBEAT_URL')
    }
    if (-not $EvidenceRepoRoot) {
        $EvidenceRepoRoot = [Environment]::GetEnvironmentVariable('CAPTURE_DAILY_EVIDENCE_REPO_ROOT')
    }
    $webhookState.configured = -not [string]::IsNullOrWhiteSpace($FailureWebhookUrl)
    $webhookState.url = if ($webhookState.configured) { 'redacted' } else { $null }
    $successHeartbeatState.configured = -not [string]::IsNullOrWhiteSpace($SuccessHeartbeatUrl)

    if (-not $RepoRoot) {
        $scriptPath = $MyInvocation.MyCommand.Path
        if (-not $scriptPath) { $scriptPath = $PSCommandPath }
        if ([string]::IsNullOrWhiteSpace($scriptPath)) {
            throw 'repository root inference failed because the script path is unavailable'
        }
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptPath)
    }
    if ([string]::IsNullOrWhiteSpace($RepoRoot) -or -not (Test-Path -LiteralPath $RepoRoot)) {
        throw "repository root directory does not exist: $RepoRoot"
    }
    $repoItem = Get-Item -LiteralPath $RepoRoot -Force -ErrorAction Stop
    if (-not $repoItem.PSIsContainer) {
        throw "repository root must be a directory: $RepoRoot"
    }
    $RepoRoot = Resolve-NormalizedPath -Path $RepoRoot
    if ([string]::IsNullOrWhiteSpace($Currency)) {
        throw 'currency must not be empty'
    }
    $currencyLower = $Currency.ToLowerInvariant()
    $script:RunId = "capture-daily-$currencyLower-$runStamp"

    $artifactsRoot = Join-Path $RepoRoot 'artifacts'
    Ensure-Directory -Path $artifactsRoot
    $logDir = Join-Path $artifactsRoot 'logs'
    Ensure-Directory -Path $logDir
    $script:LogFile = Join-Path $logDir 'capture-daily.log'
    $summaryPath = Join-Path $logDir "capture-daily-$currencyLower-$runStamp.summary.json"
    $latestSummaryPath = Join-Path $logDir "capture-daily-$currencyLower.latest.summary.json"
    $receiptPath = Join-Path $logDir "capture-daily-$currencyLower-$runStamp.receipt.json"

    $snapshotsRoot = Join-Path $artifactsRoot 'snapshots'
    $seriesDir = Join-Path $snapshotsRoot "$currencyLower-series"
    $historyDir = Join-Path $artifactsRoot 'history'
    $reportDir = Join-Path $artifactsRoot 'reports'
    foreach ($dir in @($snapshotsRoot, $seriesDir, $historyDir, $reportDir)) {
        Ensure-Directory -Path $dir
    }
    $underlyingHistoryPath = Join-Path $historyDir "$currencyLower-daily.json"
    $dvolHistoryPath = Join-Path $historyDir "$currencyLower-dvol.json"
    $seriesHistoryPath = Join-Path $reportDir 'series-history.json'
    $signalPreflightPath = Join-Path $reportDir 'signal-preflight.json'

    if ($null -eq $CaptureDvolHistory) {
        $CaptureDvolHistory = Get-EnvFlag -Name 'CAPTURE_DAILY_CAPTURE_DVOL' -Default $true
    }
    $evidenceRepoSyncEnabled = $EnableEvidenceRepoSync.IsPresent -or (Get-EnvFlag -Name 'CAPTURE_DAILY_EVIDENCE_SYNC')
    $evidenceRepoPreflightEnabled = $EnableEvidenceRepoPreflight.IsPresent -or $evidenceRepoSyncEnabled -or (Get-EnvFlag -Name 'CAPTURE_DAILY_EVIDENCE_PREFLIGHT')

    $snapshotTool = Resolve-ToolCommand -CommandName 'crypto-options-report' -PythonModule 'crypto_options_report.cli'
    $underlyingTool = Resolve-ToolCommand -CommandName 'crypto-options-underlying-history' -PythonModule 'crypto_options_report.underlying_history_tool'
    $dvolTool = Resolve-ToolCommand -CommandName 'crypto-options-dvol-history' -PythonModule 'crypto_options_report.dvol_history_tool'

    if (
        $evidenceRepoPreflightEnabled -and
        -not [string]::IsNullOrWhiteSpace($EvidenceRepoRoot) -and
        (Test-Path -LiteralPath $EvidenceRepoRoot)
    ) {
        try {
            Copy-EvidenceRepoSeedToLocalArtifacts -EvidenceRepoRoot $EvidenceRepoRoot -ArtifactsRoot $artifactsRoot -CurrencyLower $currencyLower
        }
        catch {
            Write-Log "evidence seed hydrate skipped $($_.Exception.Message)"
        }
    }

    $lastSuccessfulSnapshot = Get-LatestSnapshotPath -SeriesDirectory $seriesDir
    Write-Log "capture start currency=$Currency limit=$InstrumentLimit dvol_enabled=$CaptureDvolHistory evidence_preflight=$evidenceRepoPreflightEnabled evidence_sync=$evidenceRepoSyncEnabled"

    Set-Location $RepoRoot
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
    $analysisTimestamp = [string] $snapshotResult.details.captured_at

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
    if (-not [string]::IsNullOrWhiteSpace($analysisTimestamp)) {
        $seriesArgs += @('--generated-at', $analysisTimestamp)
    }
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

    $currentPhase = 'capture_receipt'
    Invoke-Stage -Name 'capture_receipt' -Command 'write immutable pre-sync capture receipt' -Action {
        Write-CaptureReceipt
    } | Out-Null

    if ($evidenceRepoPreflightEnabled) {
        $displayPath = if ([string]::IsNullOrWhiteSpace($EvidenceRepoRoot)) { '<unset>' } else { $EvidenceRepoRoot }
        $preflightCommand = "evidence-repo-preflight --root `"$displayPath`" --remote `"$EvidenceRepoRemote`""
        Invoke-Stage -Name 'evidence_repo_preflight' -Command $preflightCommand -Action {
            Invoke-EvidenceRepoPreflight -Path $EvidenceRepoRoot -RemoteName $EvidenceRepoRemote -ProductRepoRoot $RepoRoot
        } | Out-Null
    }

    if ($evidenceRepoSyncEnabled) {
        $displayPath = if ([string]::IsNullOrWhiteSpace($EvidenceRepoRoot)) { '<unset>' } else { $EvidenceRepoRoot }
        $syncCommand = "evidence-repo-sync --root `"$displayPath`" --remote `"$EvidenceRepoRemote`""
        Invoke-Stage -Name 'evidence_repo_sync' -Command $syncCommand -Action {
            Invoke-EvidenceRepoSync -Path $EvidenceRepoRoot -RemoteName $EvidenceRepoRemote -ProductRepoRoot $RepoRoot
        } | Out-Null
    }

    Update-UnsyncedLocalCaptureCount

    $heartbeatCommand = "success-heartbeat --configured $(-not [string]::IsNullOrWhiteSpace($SuccessHeartbeatUrl))"
    Invoke-Stage -Name 'success_heartbeat' -Command $heartbeatCommand -Action {
        if ([string]::IsNullOrWhiteSpace($SuccessHeartbeatUrl)) {
            $script:successHeartbeatState = [ordered]@{
                configured = $false
                attempted = $false
                delivered = $null
                delivery_attempts = 0
                error = $null
            }
            return [ordered]@{
                details = $script:successHeartbeatState
            }
        }

        $preHeartbeatSummary = New-CaptureSummary
        $script:successHeartbeatState = Send-SuccessHeartbeat -Url $SuccessHeartbeatUrl -Summary $preHeartbeatSummary
        if (-not $script:successHeartbeatState.delivered) {
            throw 'success heartbeat delivery failed'
        }
        return [ordered]@{
            details = $script:successHeartbeatState
        }
    } | Out-Null

    $currentPhase = 'finalization'
    Write-Log "captures in series: $((Get-ChildItem -LiteralPath $seriesDir -Filter '*.json' -File -ErrorAction SilentlyContinue).Count)"
}
catch {
    $failedStage = $currentPhase
    if ($script:StageResults.Count -gt 0) {
        $lastStage = $script:StageResults[$script:StageResults.Count - 1]
        if ($lastStage.status -eq 'failed') {
            $failedStage = $lastStage.name
        }
    }
    $failureMessage = $_.Exception.Message
}

$summary = $null
$summaryWriteFailure = $null
if (-not [string]::IsNullOrWhiteSpace($summaryPath)) {
    try {
        $summary = Write-CaptureSummary
    }
    catch {
        $summaryWriteFailure = $_.Exception.Message
        if (-not $failureMessage) {
            $failedStage = 'finalization'
            $failureMessage = "capture summary write failed: $summaryWriteFailure"
        }
    }
}
if ($null -eq $summary) {
    $summary = New-CaptureSummary
}

if ($failureMessage -and -not [string]::IsNullOrWhiteSpace($FailureWebhookUrl)) {
    $webhookState = Send-FailureWebhook -Url $FailureWebhookUrl -Summary $summary
    $summary = New-CaptureSummary
    if (-not [string]::IsNullOrWhiteSpace($summaryPath)) {
        try {
            $summary = Write-CaptureSummary
        }
        catch {
            if (-not $summaryWriteFailure) {
                $summaryWriteFailure = $_.Exception.Message
            }
        }
    }
}

if ($failureMessage) {
    if ($summaryWriteFailure -or [string]::IsNullOrWhiteSpace($summaryPath)) {
        $summaryDetail = if ($summaryWriteFailure) { $summaryWriteFailure } else { 'no safe artifacts/logs directory could be established' }
        Write-Error "capture bootstrap failed before a safe summary path was available: $failureMessage; summary_error=$summaryDetail"
    }
    exit 1
}
exit 0
