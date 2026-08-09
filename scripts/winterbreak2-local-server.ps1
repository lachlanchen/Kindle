[CmdletBinding()]
param(
    [ValidateSet("Start", "Status", "Stop")]
    [string] $Action = "Status",
    [ValidateRange(0, 65535)]
    [int] $Port = 0,
    [string] $BindAddress,
    [switch] $AllowPrivateSubnetFirewall
)

$ErrorActionPreference = "Stop"
$PinnedCommit = "40a1425215cfb6a1394590208acfefae920e5811"
$PinnedApiSha256 = "5078b00ec53d622137c692a2bc4a0625636841e7895c0e49a3f0fa411bc41e15"
$PinnedExpressVersion = "5.1.0"
$PinnedLauncherSha256 = "7ce5bc99d69bca313163d49f1925c1d0adf589e0f9f13c4b00098fcd6fa7cf6e"
$OfficialRemote = "https://github.com/KindleModding/Winterbreak2.git"
$ServerRoot = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE "Projects\winterbreak2-local"))
$MaxLogBytes = 262144

function Get-ProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-StateRoot {
    return [IO.Path]::GetFullPath((Join-Path (Get-ProjectRoot) "logs\winterbreak2-local-server"))
}

function Get-StatePath {
    return (Join-Path (Get-StateRoot) "state.json")
}

function Get-Sha256Text {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string] $Value)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
    } finally {
        $sha.Dispose()
    }
    return ([BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
}

function Write-StateTextAtomic {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string] $Content
    )

    $statePrefix = [IO.Path]::GetFullPath((Get-StateRoot)).TrimEnd("\") + "\"
    $destination = [IO.Path]::GetFullPath($Path)
    if (-not $destination.StartsWith($statePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a local-server state write outside its ignored state directory."
    }
    if ([Text.Encoding]::UTF8.GetByteCount($Content) -gt 65536) {
        throw "Refusing an oversized local-server state file."
    }
    $parent = Split-Path $destination -Parent
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = Join-Path $parent (".{0}.{1}.tmp" -f (Split-Path $destination -Leaf), [Guid]::NewGuid().ToString("N"))
    $replacementBackup = $null
    $encoding = New-Object Text.UTF8Encoding($false)
    $bytes = $encoding.GetBytes($Content)
    $stream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
    try {
        if (-not [StringComparer]::Ordinal.Equals([IO.File]::ReadAllText($temporary, $encoding), $Content)) {
            throw "Local-server state verification failed before publication."
        }
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            $replacementBackup = Join-Path $parent (".{0}.{1}.replace-backup" -f (Split-Path $destination -Leaf), [Guid]::NewGuid().ToString("N"))
            [IO.File]::Replace($temporary, $destination, $replacementBackup)
        } elseif (Test-Path -LiteralPath $destination) {
            throw "A non-file blocks the local-server state path."
        } else {
            [IO.File]::Move($temporary, $destination)
        }
        if (-not [StringComparer]::Ordinal.Equals([IO.File]::ReadAllText($destination, $encoding), $Content)) {
            throw "Local-server state verification failed after publication."
        }
        if ($replacementBackup -and (Test-Path -LiteralPath $replacementBackup -PathType Leaf)) {
            Remove-Item -LiteralPath $replacementBackup -Force
        }
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Write-StateJsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)] $Value
    )
    Write-StateTextAtomic $Path ($Value | ConvertTo-Json -Depth 8)
}

function Invoke-GitRead {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)

    $output = @(& git.exe -C $ServerRoot @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "The pinned WinterBreak2 clone failed a read-only Git validation."
    }
    return ($output -join "`n").Trim()
}

function Get-ServerPinReport {
    $issues = @()
    $head = $null
    $remote = $null
    $apiHash = $null
    $expressVersion = $null
    $launcherHash = $null
    try {
        if (-not (Test-Path -LiteralPath $ServerRoot -PathType Container)) {
            throw "clone missing"
        }
        $head = Invoke-GitRead @("rev-parse", "HEAD")
        if ($head -cne $PinnedCommit) { $issues += "commit" }
        $remote = Invoke-GitRead @("remote", "get-url", "origin")
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($remote.TrimEnd("/"), $OfficialRemote.TrimEnd("/"))) {
            $issues += "origin"
        }
        if (-not [string]::IsNullOrWhiteSpace((Invoke-GitRead @("status", "--porcelain", "--untracked-files=no")))) {
            $issues += "tracked-worktree"
        }
        $apiPath = Join-Path $ServerRoot "api\index.js"
        if (-not (Test-Path -LiteralPath $apiPath -PathType Leaf)) {
            $issues += "api-missing"
        } else {
            $apiHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $apiPath).Hash.ToLowerInvariant()
            if ($apiHash -cne $PinnedApiSha256) { $issues += "api-hash" }
        }
        $expressPackage = Join-Path $ServerRoot "node_modules\express\package.json"
        if (-not (Test-Path -LiteralPath $expressPackage -PathType Leaf)) {
            $issues += "express-missing"
        } else {
            $expressVersion = [string](Get-Content -LiteralPath $expressPackage -Raw | ConvertFrom-Json).version
            if ($expressVersion -cne $PinnedExpressVersion) { $issues += "express-version" }
        }
        $launcher = Join-Path (Get-ProjectRoot) "assets\winterbreak2-local-server\lan-bind-launcher.mjs"
        if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
            $issues += "launcher-missing"
        } else {
            $launcherHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $launcher).Hash.ToLowerInvariant()
            if ($launcherHash -cne $PinnedLauncherSha256) { $issues += "launcher-hash" }
        }
    } catch {
        $issues += "validation-error"
    }
    return [ordered]@{
        valid = $issues.Count -eq 0
        commitMatches = $head -ceq $PinnedCommit
        originMatches = $remote -and [StringComparer]::OrdinalIgnoreCase.Equals($remote.TrimEnd("/"), $OfficialRemote.TrimEnd("/"))
        apiHashMatches = $apiHash -ceq $PinnedApiSha256
        expressVersionMatches = $expressVersion -ceq $PinnedExpressVersion
        launcherHashMatches = $launcherHash -ceq $PinnedLauncherSha256
        issues = @($issues | Sort-Object -Unique)
    }
}

function Assert-ServerPin {
    $report = Get-ServerPinReport
    if (-not $report.valid) {
        throw "The local WinterBreak2 server does not match the pinned official commit/API/Express installation. Issues: $($report.issues -join ', ')"
    }
    return $report
}

function Test-PrivateIPv4 {
    param([Parameter(Mandatory = $true)][string] $Address)

    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$parsed) -or
        $parsed.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        return $false
    }
    $bytes = $parsed.GetAddressBytes()
    return (
        $bytes[0] -eq 10 -or
        ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
        ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
    )
}

function Resolve-PrivateLanAddress {
    param([string] $Requested)

    $privateIndexes = @(
        Get-NetConnectionProfile -ErrorAction Stop |
            Where-Object { $_.NetworkCategory -eq "Private" } |
            ForEach-Object { [int]$_.InterfaceIndex }
    )
    $candidates = @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.InterfaceIndex -in $privateIndexes -and
                $_.AddressState -eq "Preferred" -and
                (Test-PrivateIPv4 $_.IPAddress)
            } |
            Select-Object -ExpandProperty IPAddress -Unique
    )
    if ($Requested) {
        if (-not (Test-PrivateIPv4 $Requested) -or $Requested -notin $candidates) {
            throw "The requested bind address is not an active RFC1918 address on a Windows Private network."
        }
        return $Requested
    }
    if ($candidates.Count -ne 1) {
        throw "Expected exactly one active RFC1918 address on a Windows Private network; pass -BindAddress explicitly after review."
    }
    return [string]$candidates[0]
}

function Get-ListeningEndpoints {
    param([Parameter(Mandatory = $true)][int] $LocalPort)
    return @(
        Get-NetTCPConnection -State Listen -LocalPort $LocalPort -ErrorAction SilentlyContinue |
            ForEach-Object {
                [pscustomobject]@{
                    address = [string]$_.LocalAddress
                    port = [int]$_.LocalPort
                    pid = [int]$_.OwningProcess
                }
            }
    )
}

function Assert-PortAvailable {
    param([Parameter(Mandatory = $true)][int] $LocalPort)
    $listeners = @(Get-ListeningEndpoints $LocalPort)
    if ($listeners.Count -gt 0) {
        $owners = ($listeners | Select-Object -ExpandProperty pid -Unique | Sort-Object) -join ", "
        throw "TCP port $LocalPort is already occupied by unadopted process ID(s): $owners. No process was stopped or restarted."
    }
}

function Convert-CreationDateToUtcText {
    param([Parameter(Mandatory = $true)] $Value)
    if ($Value -is [DateTime]) {
        return $Value.ToUniversalTime().ToString("o")
    }
    return ([Management.ManagementDateTimeConverter]::ToDateTime([string]$Value)).ToUniversalTime().ToString("o")
}

function Get-ProcessSnapshot {
    param([Parameter(Mandatory = $true)][int] $ProcessId)

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    $commandLine = [string]$process.CommandLine
    return [pscustomobject]@{
        pid = [int]$process.ProcessId
        executablePath = [IO.Path]::GetFullPath([string]$process.ExecutablePath)
        creationTimeUtc = Convert-CreationDateToUtcText $process.CreationDate
        commandLine = $commandLine
        commandLineSha256 = Get-Sha256Text $commandLine
    }
}

function Test-RecordedProcessIdentity {
    param(
        [Parameter(Mandatory = $true)] $State,
        [AllowNull()] $Snapshot
    )
    if (-not $Snapshot) { return $false }
    $expectedNode = [IO.Path]::GetFullPath((Get-Command node.exe -ErrorAction Stop).Source)
    $expectedLauncher = [IO.Path]::GetFullPath((Join-Path (Get-ProjectRoot) "assets\winterbreak2-local-server\lan-bind-launcher.mjs"))
    return (
        [int]$State.pid -eq [int]$Snapshot.pid -and
        [StringComparer]::OrdinalIgnoreCase.Equals([string]$State.executablePath, [string]$Snapshot.executablePath) -and
        [StringComparer]::OrdinalIgnoreCase.Equals([string]$Snapshot.executablePath, $expectedNode) -and
        [StringComparer]::Ordinal.Equals([string]$State.creationTimeUtc, [string]$Snapshot.creationTimeUtc) -and
        [StringComparer]::Ordinal.Equals([string]$State.commandLineSha256, [string]$Snapshot.commandLineSha256) -and
        [string]$Snapshot.commandLine -and
        ([string]$Snapshot.commandLine).IndexOf($expectedLauncher, [StringComparison]::OrdinalIgnoreCase) -ge 0
    )
}

function Assert-StateShape {
    param([Parameter(Mandatory = $true)] $State)

    if ([int]$State.schemaVersion -ne 1 -or
        [string]$State.status -notin @("starting", "running") -or
        [string]$State.runId -notmatch "^[0-9a-f]{32}$" -or
        [string]$State.commit -cne $PinnedCommit -or
        [string]$State.apiSha256 -cne $PinnedApiSha256 -or
        [string]$State.expressVersion -cne $PinnedExpressVersion -or
        [string]$State.launcherSha256 -cne $PinnedLauncherSha256 -or
        [int]$State.pid -le 0 -or
        [int]$State.port -lt 1 -or [int]$State.port -gt 65535 -or
        [int]$State.maxLogBytes -ne $MaxLogBytes -or
        -not (Test-PrivateIPv4 ([string]$State.bindAddress)) -or
        [string]$State.commandLineSha256 -notmatch "^[0-9a-f]{64}$") {
        throw "The managed local-server state has an invalid shape or pin set."
    }
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals([IO.Path]::GetFullPath([string]$State.serverRoot), $ServerRoot)) {
        throw "The managed local-server state points to a different clone."
    }
    $expectedNode = [IO.Path]::GetFullPath((Get-Command node.exe -ErrorAction Stop).Source)
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals([IO.Path]::GetFullPath([string]$State.executablePath), $expectedNode)) {
        throw "The managed local-server state points to a different executable."
    }
    $statePrefix = [IO.Path]::GetFullPath((Get-StateRoot)).TrimEnd("\") + "\"
    $logPath = [IO.Path]::GetFullPath([string]$State.logPath)
    $expectedLogPath = [IO.Path]::GetFullPath((Join-Path (Get-StateRoot) "server-$($State.runId).log"))
    if (-not $logPath.StartsWith($statePrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not [StringComparer]::OrdinalIgnoreCase.Equals($logPath, $expectedLogPath)) {
        throw "The managed log path is outside the ignored state directory or differs from its run identity."
    }
    $launcherPath = [IO.Path]::GetFullPath([string]$State.launcherPath)
    $expectedLauncherPath = [IO.Path]::GetFullPath((Join-Path (Get-ProjectRoot) "assets\winterbreak2-local-server\lan-bind-launcher.mjs"))
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals($launcherPath, $expectedLauncherPath)) {
        throw "The managed launcher path differs from the tracked launcher."
    }
    $expectedRuleName = "lazying-art-wb2-local-$($State.runId)"
    if ($State.firewallRuleName -and
        -not [StringComparer]::Ordinal.Equals([string]$State.firewallRuleName, $expectedRuleName)) {
        throw "The managed firewall rule name is invalid."
    }
}

function Get-ManagedState {
    $path = Get-StatePath
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -gt 65536) {
        throw "The managed local-server state file is invalid or oversized."
    }
    $state = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    Assert-StateShape $state
    return $state
}

function Remove-OldBoundedLogs {
    param([string] $KeepLogPath)

    $root = Get-StateRoot
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return }
    $keep = if ($KeepLogPath) { [IO.Path]::GetFullPath($KeepLogPath) } else { $null }
    $logs = @(
        Get-ChildItem -LiteralPath $root -File -Filter "server-*.log*" |
            Where-Object { -not $keep -or -not $_.FullName.StartsWith($keep, [StringComparison]::OrdinalIgnoreCase) } |
            Sort-Object LastWriteTimeUtc -Descending
    )
    foreach ($old in @($logs | Select-Object -Skip 6)) {
        Remove-Item -LiteralPath $old.FullName -Force
    }
}

function New-PrivateSubnetFirewallRule {
    param(
        [Parameter(Mandatory = $true)][string] $RuleName,
        [Parameter(Mandatory = $true)][string] $Address,
        [Parameter(Mandatory = $true)][int] $LocalPort,
        [Parameter(Mandatory = $true)][string] $Program
    )
    if (Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue) {
        throw "The planned managed firewall rule already exists."
    }
    New-NetFirewallRule `
        -Name $RuleName `
        -DisplayName "lazying.art WinterBreak2 LAN-only $LocalPort" `
        -Direction Inbound `
        -Action Allow `
        -Enabled True `
        -Profile Private `
        -Protocol TCP `
        -LocalAddress $Address `
        -LocalPort $LocalPort `
        -RemoteAddress LocalSubnet `
        -Program $Program | Out-Null
}

function Remove-RecordedFirewallRule {
    param([AllowNull()][string] $RuleName)
    if (-not $RuleName) { return }
    if ($RuleName -notmatch "^lazying-art-wb2-local-[0-9a-f]{32}$") {
        throw "Refusing an invalid recorded firewall rule name."
    }
    $rule = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
    if ($rule) {
        Remove-NetFirewallRule -Name $RuleName
    }
}

function Get-ServerUrl {
    param(
        [Parameter(Mandatory = $true)][string] $Address,
        [Parameter(Mandatory = $true)][int] $LocalPort
    )
    if ($LocalPort -eq 80) { return "http://$Address/" }
    return "http://${Address}:$LocalPort/"
}

function Start-LocalServer {
    param(
        [Parameter(Mandatory = $true)][int] $LocalPort,
        [string] $RequestedAddress,
        [switch] $ConfigureFirewall
    )

    if (Get-ManagedState) {
        throw "A managed local-server state already exists. Use Status; never overwrite or adopt it."
    }
    Assert-ServerPin | Out-Null
    $address = Resolve-PrivateLanAddress $RequestedAddress
    Assert-PortAvailable $LocalPort
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $launcher = [IO.Path]::GetFullPath((Join-Path (Get-ProjectRoot) "assets\winterbreak2-local-server\lan-bind-launcher.mjs"))
    $entry = Join-Path $ServerRoot "api\index.js"
    $runId = [Guid]::NewGuid().ToString("N")
    $logPath = Join-Path (Get-StateRoot) "server-$runId.log"
    New-Item -ItemType Directory -Path (Get-StateRoot) -Force | Out-Null
    Remove-OldBoundedLogs

    $saved = [ordered]@{
        PORT = $env:PORT
        WB2_BIND_ADDRESS = $env:WB2_BIND_ADDRESS
        WB2_ENTRY_PATH = $env:WB2_ENTRY_PATH
        WB2_BOUNDED_LOG_PATH = $env:WB2_BOUNDED_LOG_PATH
        WB2_MAX_LOG_BYTES = $env:WB2_MAX_LOG_BYTES
    }
    try {
        $env:PORT = [string]$LocalPort
        $env:WB2_BIND_ADDRESS = $address
        $env:WB2_ENTRY_PATH = $entry
        $env:WB2_BOUNDED_LOG_PATH = $logPath
        $env:WB2_MAX_LOG_BYTES = [string]$MaxLogBytes
        $process = Start-Process `
            -FilePath $node `
            -ArgumentList ('"' + $launcher + '"') `
            -WorkingDirectory $ServerRoot `
            -WindowStyle Hidden `
            -PassThru
    } finally {
        foreach ($name in $saved.Keys) {
            if ($null -eq $saved[$name]) {
                Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
            } else {
                Set-Item -LiteralPath "Env:$name" -Value $saved[$name]
            }
        }
    }

    $snapshot = $null
    $snapshotDeadline = (Get-Date).AddSeconds(5)
    while (-not $snapshot -and (Get-Date) -lt $snapshotDeadline) {
        $snapshot = Get-ProcessSnapshot $process.Id
        if (-not $snapshot) { Start-Sleep -Milliseconds 100 }
    }
    if (-not $snapshot) {
        try {
            $process.Refresh()
            if (-not $process.HasExited) {
                # This Process object is the exact child returned by Start-Process;
                # do not look it up again by PID because a PID may be reused.
                $process.Kill()
                $null = $process.WaitForExit(5000)
            }
        } catch {
            # Preserve the launch failure below. No unrecorded PID is ever killed.
        }
        throw "The newly launched Node process exited before its identity could be recorded."
    }
    $state = [ordered]@{
        schemaVersion = 1
        createdAt = (Get-Date).ToString("o")
        status = "starting"
        runId = $runId
        serverRoot = $ServerRoot
        commit = $PinnedCommit
        apiSha256 = $PinnedApiSha256
        expressVersion = $PinnedExpressVersion
        launcherSha256 = $PinnedLauncherSha256
        pid = $snapshot.pid
        executablePath = $snapshot.executablePath
        creationTimeUtc = $snapshot.creationTimeUtc
        commandLineSha256 = $snapshot.commandLineSha256
        bindAddress = $address
        port = $LocalPort
        launcherPath = $launcher
        logPath = $logPath
        maxLogBytes = $MaxLogBytes
        firewallRuleName = $null
    }
    try {
        Write-StateJsonAtomic (Get-StatePath) $state
        $deadline = (Get-Date).AddSeconds(10)
        $listening = $false
        while ((Get-Date) -lt $deadline) {
            if (-not (Test-RecordedProcessIdentity $state (Get-ProcessSnapshot $state.pid))) {
                throw "The managed Node process exited or changed identity before listening."
            }
            $listening = @(
                Get-ListeningEndpoints $LocalPort |
                    Where-Object { $_.pid -eq $state.pid -and $_.address -eq $address }
            ).Count -eq 1
            if ($listening) { break }
            Start-Sleep -Milliseconds 200
        }
        if (-not $listening) {
            throw "The managed Node process did not bind the exact private address and port."
        }
        $response = Invoke-WebRequest -UseBasicParsing -Uri (Get-ServerUrl $address $LocalPort) -TimeoutSec 3
        if ($response.StatusCode -ne 200 -or [string]$response.Content -notmatch "Winterbreak2") {
            throw "The bound server did not return the pinned WinterBreak2 landing page."
        }
        if ($ConfigureFirewall) {
            $ruleName = "lazying-art-wb2-local-$runId"
            $state.firewallRuleName = $ruleName
            New-PrivateSubnetFirewallRule $ruleName $address $LocalPort $node
        }
        $state.status = "running"
        $state.startedAt = (Get-Date).ToString("o")
        Write-StateJsonAtomic (Get-StatePath) $state
    } catch {
        $current = Get-ProcessSnapshot $state.pid
        if (Test-RecordedProcessIdentity $state $current) {
            Stop-Process -Id $state.pid -Force
        }
        Remove-RecordedFirewallRule $state.firewallRuleName
        if (Test-Path -LiteralPath (Get-StatePath) -PathType Leaf) {
            Remove-Item -LiteralPath (Get-StatePath) -Force
        }
        throw
    }

    [ordered]@{
        managed = $true
        healthy = $true
        pid = $state.pid
        bindAddress = $state.bindAddress
        port = $state.port
        url = Get-ServerUrl $state.bindAddress $state.port
        firewall = if ($state.firewallRuleName) { "Private/LocalSubnet managed rule" } else { "unchanged" }
    } | ConvertTo-Json -Depth 5
}

function Get-LocalServerStatus {
    param(
        [int] $RequestedPort,
        [string] $RequestedAddress
    )

    $pin = Get-ServerPinReport
    $state = Get-ManagedState
    if ($state) {
        if ($RequestedPort -and $RequestedPort -ne [int]$state.port) {
            throw "The requested port differs from the managed state."
        }
        if ($RequestedAddress -and -not [StringComparer]::Ordinal.Equals($RequestedAddress, [string]$state.bindAddress)) {
            throw "The requested bind address differs from the managed state."
        }
        $snapshot = Get-ProcessSnapshot $state.pid
        $identityMatches = Test-RecordedProcessIdentity $state $snapshot
        $listenerMatches = $false
        $healthMatches = $false
        if ($identityMatches) {
            $listenerMatches = @(
                Get-ListeningEndpoints ([int]$state.port) |
                    Where-Object { $_.pid -eq [int]$state.pid -and $_.address -eq [string]$state.bindAddress }
            ).Count -eq 1
            if ($listenerMatches) {
                try {
                    $response = Invoke-WebRequest -UseBasicParsing -Uri (Get-ServerUrl $state.bindAddress $state.port) -TimeoutSec 2
                    $healthMatches = $response.StatusCode -eq 200 -and [string]$response.Content -match "Winterbreak2"
                } catch { $healthMatches = $false }
            }
        }
        return [ordered]@{
            managed = $true
            healthy = $pin.valid -and $identityMatches -and $listenerMatches -and $healthMatches
            repositoryValid = $pin.valid
            processIdentityMatches = $identityMatches
            listenerMatches = $listenerMatches
            pageMatches = $healthMatches
            pid = [int]$state.pid
            bindAddress = [string]$state.bindAddress
            port = [int]$state.port
            url = Get-ServerUrl $state.bindAddress $state.port
            firewall = if ($state.firewallRuleName) { "Private/LocalSubnet managed rule" } else { "unchanged" }
        }
    }

    $localPort = if ($RequestedPort) { $RequestedPort } else { 80 }
    $address = $null
    try { $address = Resolve-PrivateLanAddress $RequestedAddress } catch { }
    $listeners = @(Get-ListeningEndpoints $localPort)
    return [ordered]@{
        managed = $false
        healthy = $false
        repositoryValid = $pin.valid
        occupied = $listeners.Count -gt 0
        ownerPids = @($listeners | Select-Object -ExpandProperty pid -Unique | Sort-Object)
        bindAddress = $address
        port = $localPort
        url = if ($address) { Get-ServerUrl $address $localPort } else { $null }
        note = if ($listeners.Count -gt 0) { "Unmanaged listener observed; this helper will not adopt or stop it." } else { "No managed server or listener." }
    }
}

function Stop-LocalServer {
    param(
        [int] $RequestedPort,
        [string] $RequestedAddress
    )

    $state = Get-ManagedState
    if (-not $state) {
        throw "No managed local-server state exists. Unmanaged Node processes are never stopped."
    }
    if ($RequestedPort -and $RequestedPort -ne [int]$state.port) {
        throw "The requested port differs from the managed state; nothing was stopped."
    }
    if ($RequestedAddress -and -not [StringComparer]::Ordinal.Equals($RequestedAddress, [string]$state.bindAddress)) {
        throw "The requested bind address differs from the managed state; nothing was stopped."
    }
    $snapshot = Get-ProcessSnapshot $state.pid
    if ($snapshot -and -not (Test-RecordedProcessIdentity $state $snapshot)) {
        throw "PID $($state.pid) no longer matches the exact recorded process identity; nothing was stopped."
    }
    if ($snapshot) {
        Stop-Process -Id $state.pid -Force
        $deadline = (Get-Date).AddSeconds(10)
        while ((Get-ProcessSnapshot $state.pid) -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 200
        }
        if (Get-ProcessSnapshot $state.pid) {
            throw "The exact managed process did not stop; its state was retained."
        }
    }
    Remove-RecordedFirewallRule $state.firewallRuleName
    $audit = [ordered]@{
        stoppedAt = (Get-Date).ToString("o")
        runId = [string]$state.runId
        pid = [int]$state.pid
        processWasPresent = [bool]$snapshot
        firewallRuleRemoved = [bool]$state.firewallRuleName
    }
    Write-StateJsonAtomic (Join-Path (Get-StateRoot) "last-stop.json") $audit
    Remove-Item -LiteralPath (Get-StatePath) -Force
    Remove-OldBoundedLogs
    $audit | ConvertTo-Json -Depth 5
}

if ($Action -ne "Start" -and $AllowPrivateSubnetFirewall) {
    throw "-AllowPrivateSubnetFirewall is valid only with -Action Start."
}

switch ($Action) {
    "Start" {
        $effectivePort = if ($Port) { $Port } else { 80 }
        Start-LocalServer $effectivePort $BindAddress -ConfigureFirewall:$AllowPrivateSubnetFirewall
    }
    "Status" {
        Get-LocalServerStatus $Port $BindAddress | ConvertTo-Json -Depth 6
    }
    "Stop" {
        Stop-LocalServer $Port $BindAddress
    }
}
