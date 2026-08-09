[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$implementation = Join-Path $repoRoot "scripts\winterbreak2-local-server.ps1"

# Load function definitions only. This never dispatches Start/Status/Stop,
# opens a listener, changes the firewall, or discovers a removable drive.
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $implementation,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
    throw "Implementation parse failed: $($parseErrors[0].Message)"
}
foreach ($functionAst in $ast.FindAll({
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst]
        }, $true)) {
    Invoke-Expression $functionAst.Extent.Text
}

$PinnedCommit = "40a1425215cfb6a1394590208acfefae920e5811"
$PinnedApiSha256 = "5078b00ec53d622137c692a2bc4a0625636841e7895c0e49a3f0fa411bc41e15"
$PinnedExpressVersion = "5.1.0"
$PinnedLauncherSha256 = "7ce5bc99d69bca313163d49f1925c1d0adf589e0f9f13c4b00098fcd6fa7cf6e"
$OfficialRemote = "https://github.com/KindleModding/Winterbreak2.git"
$ServerRoot = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE "Projects\winterbreak2-local"))
$MaxLogBytes = 262144
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("kindle-wb2-local-server-test-" + [Guid]::NewGuid().ToString("N"))
$script:testStateRoot = Join-Path $testRoot "state"

function Get-ProjectRoot {
    return $repoRoot
}

function Get-StateRoot {
    return $script:testStateRoot
}

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool] $Condition,
        [Parameter(Mandatory = $true)][string] $Message
    )
    if (-not $Condition) { throw $Message }
}

function Assert-Throws {
    param(
        [Parameter(Mandatory = $true)][scriptblock] $Action,
        [Parameter(Mandatory = $true)][string] $Pattern,
        [Parameter(Mandatory = $true)][string] $Message
    )
    $threw = $false
    try {
        & $Action
    } catch {
        if ($_.Exception.Message -notmatch $Pattern) {
            throw "$Message Unexpected error: $($_.Exception.Message)"
        }
        $threw = $true
    }
    if (-not $threw) { throw $Message }
}

function New-GoodState {
    $runId = "a" * 32
    return [pscustomobject][ordered]@{
        schemaVersion = 1
        createdAt = "2026-08-09T00:00:00.0000000Z"
        status = "running"
        runId = $runId
        serverRoot = $ServerRoot
        commit = $PinnedCommit
        apiSha256 = $PinnedApiSha256
        expressVersion = $PinnedExpressVersion
        launcherSha256 = $PinnedLauncherSha256
        pid = 4242
        executablePath = [IO.Path]::GetFullPath((Get-Command node.exe -ErrorAction Stop).Source)
        creationTimeUtc = "2026-08-09T00:00:00.0000000Z"
        commandLineSha256 = "b" * 64
        bindAddress = "192.168.50.2"
        port = 80
        launcherPath = Join-Path $repoRoot "assets\winterbreak2-local-server\lan-bind-launcher.mjs"
        logPath = Join-Path $script:testStateRoot "server-$runId.log"
        maxLogBytes = $MaxLogBytes
        firewallRuleName = $null
    }
}

try {
    New-Item -ItemType Directory -Path $script:testStateRoot -Force | Out-Null

    $source = Get-Content -LiteralPath $implementation -Raw
    Assert-True ($source -match "-WindowStyle\s+Hidden") "The launcher must remain hidden."
    Assert-True ($source -match "-Profile\s+Private") "The optional firewall rule must remain Private-profile only."
    Assert-True ($source -match "-RemoteAddress\s+LocalSubnet") "The optional firewall rule must remain LocalSubnet only."
    Assert-True ($source -notmatch "Get-Volume|Get-Disk|Win32_LogicalDisk") "The helper must not discover removable storage."

    foreach ($address in @("10.1.2.3", "172.16.0.1", "172.31.255.254", "192.168.1.8")) {
        Assert-True (Test-PrivateIPv4 $address) "Expected private IPv4 address: $address"
    }
    foreach ($address in @("127.0.0.1", "172.32.0.1", "8.8.8.8", "::1", "not-an-ip")) {
        Assert-True (-not (Test-PrivateIPv4 $address)) "Expected rejected IPv4 address: $address"
    }
    Assert-True ((Get-ServerUrl "192.168.1.8" 80) -ceq "http://192.168.1.8/") "Port 80 URL is wrong."
    Assert-True ((Get-ServerUrl "192.168.1.8" 8080) -ceq "http://192.168.1.8:8080/") "Non-default URL is wrong."

    $pin = Get-ServerPinReport
    Assert-True ([bool]$pin.valid) "The official local clone no longer matches its pin set: $($pin.issues -join ', ')"

    $state = New-GoodState
    Assert-StateShape $state
    $snapshot = [pscustomobject]@{
        pid = $state.pid
        executablePath = $state.executablePath
        creationTimeUtc = $state.creationTimeUtc
        commandLine = '"' + $state.executablePath + '" "' + $state.launcherPath + '"'
        commandLineSha256 = $state.commandLineSha256
    }
    Assert-True (Test-RecordedProcessIdentity $state $snapshot) "Exact process identity should match."
    $snapshot.creationTimeUtc = "2026-08-09T00:00:01.0000000Z"
    Assert-True (-not (Test-RecordedProcessIdentity $state $snapshot)) "Changed creation time must fail process identity."
    $snapshot = [pscustomobject]@{
        pid = $state.pid
        executablePath = $state.executablePath
        creationTimeUtc = $state.creationTimeUtc
        commandLine = '"' + $state.executablePath + '" unrelated-script.mjs'
        commandLineSha256 = $state.commandLineSha256
    }
    Assert-True (-not (Test-RecordedProcessIdentity $state $snapshot)) "A different Node command line must fail process identity."

    $tampered = New-GoodState
    $tampered.launcherPath = $tampered.logPath
    Assert-Throws { Assert-StateShape $tampered } "launcher" "A disguised launcher path was accepted."
    $tampered = New-GoodState
    $tampered.logPath = Join-Path $testRoot "outside.log"
    Assert-Throws { Assert-StateShape $tampered } "log path" "An out-of-scope log path was accepted."
    $tampered = New-GoodState
    $tampered.runId = "c" * 32
    Assert-Throws { Assert-StateShape $tampered } "log path" "A log path from another run was accepted."
    $tampered = New-GoodState
    $tampered.executablePath = $implementation
    Assert-Throws { Assert-StateShape $tampered } "executable" "A different executable path was accepted."
    $tampered = New-GoodState
    $tampered.firewallRuleName = "lazying-art-wb2-local-$('c' * 32)"
    Assert-Throws { Assert-StateShape $tampered } "firewall" "A firewall rule from another run was accepted."

    $statePath = Get-StatePath
    Write-StateJsonAtomic $statePath $state
    $state.status = "starting"
    Write-StateJsonAtomic $statePath $state
    $roundTrip = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    Assert-True ($roundTrip.status -ceq "starting") "Atomic replacement did not publish the second state."
    $leftovers = @(Get-ChildItem -LiteralPath $script:testStateRoot -File -Force | Where-Object { $_.Name -match "\.tmp$|\.replace-backup$" })
    Assert-True ($leftovers.Count -eq 0) "Atomic state publication left temporary files."

    1..9 | ForEach-Object {
        $path = Join-Path $script:testStateRoot ("server-{0:d2}.log" -f $_)
        Set-Content -LiteralPath $path -Value $_ -Encoding ASCII
        (Get-Item -LiteralPath $path).LastWriteTimeUtc = [DateTime]::UtcNow.AddMinutes(-$_)
    }
    Remove-OldBoundedLogs
    Assert-True (@(Get-ChildItem -LiteralPath $script:testStateRoot -File -Filter "server-*.log*").Count -le 6) "Old server logs were not bounded."

    function Get-ListeningEndpoints {
        param([int] $LocalPort)
        return @([pscustomobject]@{ address = "0.0.0.0"; port = $LocalPort; pid = 9001 })
    }
    Assert-Throws { Assert-PortAvailable 80 } "occupied.*9001" "An occupied port was accepted."

    $script:stopCalled = $false
    function Get-ManagedState { return $null }
    function Stop-Process {
        param([int] $Id, [switch] $Force)
        $script:stopCalled = $true
    }
    Assert-Throws { Stop-LocalServer 80 $null } "Unmanaged Node processes are never stopped" "Stop accepted missing managed state."
    Assert-True (-not $script:stopCalled) "Stop touched an unmanaged process."

    "PASS: WinterBreak2 local-server guard tests"
} finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
