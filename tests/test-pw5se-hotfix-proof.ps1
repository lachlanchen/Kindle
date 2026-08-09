[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$implementation = Join-Path $repoRoot "scripts\pw5se-winterbreak.ps1"
$templateSource = Join-Path $repoRoot "assets\hotfix\verify-hotfix.sh.template"
$launcherSource = Join-Path $repoRoot "assets\koreader-lazy\KOReader.sh"

# Load function definitions only. No action dispatch, removable-drive
# discovery, ejection, or real device access occurs in this suite.
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($implementation, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) { throw "Implementation parse failed: $($parseErrors[0].Message)" }
foreach ($functionAst in $ast.FindAll({
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst]
        }, $true)) {
    Invoke-Expression $functionAst.Extent.Text
}

$ExpectedFirmware = "5.15.1"
$FillerOwnerText = "lazying-art Kindle PW5SE WinterBreak filler v1"
$ConfirmedAirplaneMode = $true
$UniversalHotfix = [ordered]@{
    Version = "2.5.0"
    File = "Update_hotfix_universal.bin"
    Sha256 = "94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59"
}
$HotfixProbe = [ordered]@{
    TemplateRelativePath = "assets\hotfix\verify-hotfix.sh.template"
    TemplateSha256 = "55f1fa496a001c4d8712722c4e5f214f176fa7b52b27168174b2336c7376340e"
    NonceToken = "__LAZYING_ART_HOTFIX_NONCE_HEX__"
    ProbeRelativePath = "documents\Verify Hotfix.sh"
    ResultRelativePath = "documents\HOTFIX_VERIFIED_LAZYING_ART.txt"
    RunnerRelativePath = "documents\Run Hotfix.run_hotfix"
    RunnerContent = "2.5.0`n"
    DiagnosticRelativePath = "documents\Diagnose Hotfix.sh"
    DiagnosticResultRelativePath = "documents\HOTFIX_DIAGNOSTIC_LAZYING_ART.txt"
    DiagnosticTransformVersion = 1
}
$HotfixDiagnosticReasonCodes = @(
    "UID", "NONCE", "DOCUMENTS", "RESULT_EXISTS", "ESSENTIALS",
    "VERSION", "KEYSTORE", "KINDLET", "UPDATE_KEY", "DEBUG_HOOK",
    "START_LOG", "COMPLETION_LOG", "JOB_LOG", "TEMPORARY_FILE",
    "WRITE", "SYNC", "RESULT_APPEARED", "RENAME", "INTERNAL"
)
$HotfixProofModes = @("full-history-v1", "persistent-state-v2")
$KOReader = [ordered]@{
    Version = "2026.07.1"
    File = "fake-koreader-kindlepw2.zip"
    Sha256 = "e" * 64
    LauncherRelativePath = "assets\koreader-lazy\KOReader.sh"
    LauncherDeviceRelativePath = "documents\KOReader.sh"
    LauncherSha256 = "619e707a1dee8c36c1107af195a41c2c3f7f0d9b622b4e4cb5fbfcdae9c64e25"
}
$WinterBreak2SuccessEvidence = @(
    "Developer keys installed successfully (Standard Method)! (pubdevkey01.pem)",
    "Enabled developer flag",
    "Enabled mntus exec flag",
    "*** Finished installing jailbreak! ***",
    "***   Please Install HOTFIX now    ***"
)
$WinterBreak2FailureEvidence = @("ERR -", " FAIL", "ERROR:")
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("kindle-hotfix-proof-test-" + [Guid]::NewGuid().ToString("N"))
$script:activeProject = $null
$script:activeIdentity = "d" * 64
$script:wb2Record = $null

function Get-ProjectRoot { return $script:activeProject }
function Get-KindleIdentityHash { param([string] $Root) return $script:activeIdentity }
function Get-FreeBytes { param([string] $Root) return [int64](80MB) }
function Download-Packages { }
function Assert-ExactWinterBreak2Device {
    param([string] $Root)
    return [ordered]@{ firmware = $ExpectedFirmware }
}
function Get-WinterBreak2Record {
    param([string] $Kind = "active", [switch] $Require)
    if ($Kind -eq "executed" -and $script:wb2Record) { return $script:wb2Record }
    if ($Require) { throw "No mock WinterBreak2 record." }
    return $null
}
function Assert-WinterBreak2RecordMatchesDevice {
    param($Record, [string] $Root)
    if ([string]$Record.manifest.deviceFingerprint -cne (Get-KindleFingerprint $Root) -or
        [string]$Record.manifest.deviceIdentityHash -cne (Get-KindleIdentityHash $Root)) {
        throw "Mock WinterBreak2 device mismatch."
    }
}

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}
function Assert-Throws {
    param([scriptblock] $Action, [string] $Pattern, [string] $Message)
    $threw = $false
    try { & $Action } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw "$Message Unexpected: $($_.Exception.Message)" }
        $threw = $true
    }
    if (-not $threw) { throw $Message }
}

function New-FakeCase {
    param([string] $Name)

    $caseRoot = Join-Path $testRoot $Name
    $project = Join-Path $caseRoot "project"
    $device = Join-Path $caseRoot "device"
    foreach ($directory in @(
            $project,
            (Join-Path $project "assets\hotfix"),
            (Join-Path $project "assets\koreader-lazy"),
            (Join-Path $project "downloads"),
            (Join-Path $project "device-backups\wb2-executed"),
            (Join-Path $device "documents"),
            (Join-Path $device "system"),
            (Join-Path $device ".kindle-ota-space-filler")
        )) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    Copy-Item -LiteralPath $templateSource -Destination (Join-Path $project "assets\hotfix\verify-hotfix.sh.template")
    Copy-Item -LiteralPath $launcherSource -Destination (Join-Path $project "assets\koreader-lazy\KOReader.sh")
    $archiveTree = Join-Path $caseRoot "archive-tree"
    New-Item -ItemType Directory -Path (Join-Path $archiveTree "koreader") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $archiveTree "extensions\koreader") -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $archiveTree "koreader\koreader.sh"), "#!/bin/sh`nexit 0`n", (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $archiveTree "extensions\koreader\menu.json"), "{}`n", (New-Object Text.UTF8Encoding($false)))
    Compress-Archive -Path (Join-Path $archiveTree "*") -DestinationPath (Join-Path $project "downloads\$($KOReader.File)")
    $KOReader.Sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $project "downloads\$($KOReader.File)")).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText((Join-Path $device "system\version.txt"), "Kindle 5.15.1 fake`n", (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $device "documents\Run Hotfix.run_hotfix"), "2.5.0`n", (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $device ".kindle-ota-space-filler\.lazying-art-filler-owner-v1"), "$FillerOwnerText`n", (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllBytes((Join-Path $device ".kindle-ota-space-filler\filler-000.bin"), [byte[]](0, 1, 2, 3))
    $successLog = ($WinterBreak2SuccessEvidence -join "`n") + "`n"
    [IO.File]::WriteAllText((Join-Path $device "winterbreak.log"), $successLog, (New-Object Text.UTF8Encoding($false)))
    $script:activeProject = $project
    $wb2ManifestPath = Join-Path $project "device-backups\wb2-executed\manifest.json"
    $manifest = [pscustomobject][ordered]@{
        status = "executed"
        verifiedAt = "2026-08-09T00:00:00Z"
        winterBreakLogSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $device "winterbreak.log")).Hash.ToLowerInvariant()
        hotfixStageStatus = "complete"
        hotfixStagedAt = "2026-08-09T00:01:00Z"
        hotfixSha256 = $UniversalHotfix.Sha256
        deviceFingerprint = Get-KindleFingerprint $device
        deviceIdentityHash = $script:activeIdentity
    }
    Write-ProjectJsonAtomic $wb2ManifestPath $manifest
    $script:wb2Record = [ordered]@{ manifestPath = $wb2ManifestPath; manifest = $manifest }
    return [pscustomobject]@{ Project = $project; Device = $device }
}

function Complete-FakeHotfixProof {
    param([Parameter(Mandatory = $true)] $Case)

    Stage-HotfixProbe $Case.Device
    $active = Get-HotfixProbeRecord "active" -Require
    [IO.File]::WriteAllText(
        (Join-Path $Case.Device "documents\HOTFIX_VERIFIED_LAZYING_ART.txt"),
        (Get-ExpectedHotfixProbeResultContent $active.manifest.nonce),
        (New-Object Text.UTF8Encoding($false))
    )
    Verify-UniversalHotfix $Case.Device
    return Get-HotfixProbeRecord "verified" -Require
}

function Complete-FakeHotfixDiagnostic {
    param(
        [Parameter(Mandatory = $true)] $Case,
        [Parameter(Mandatory = $true)][string] $ReasonCode
    )

    Stage-HotfixProbe $Case.Device
    Stage-HotfixDiagnostic $Case.Device
    $record = Get-HotfixProbeRecord "active" -Require
    [IO.File]::WriteAllText(
        (Join-Path $Case.Device "documents\HOTFIX_DIAGNOSTIC_LAZYING_ART.txt"),
        (Get-ExpectedHotfixDiagnosticContent $record.manifest.nonce $ReasonCode),
        (New-Object Text.UTF8Encoding($false))
    )
    Read-HotfixDiagnostic $Case.Device | Out-Null
    return Get-HotfixProbeRecord "active" -Require
}

function New-FakeKOReaderStageRecord {
    param(
        [Parameter(Mandatory = $true)] $Case,
        [Parameter(Mandatory = $true)] $Proof,
        [Parameter(Mandatory = $true)][string] $Status
    )

    $runId = "f" * 32
    $recordRoot = Join-Path $Case.Project "device-backups\koreader-stage-test-$runId"
    New-Item -ItemType Directory -Path $recordRoot -Force | Out-Null
    $manifest = [ordered]@{
        schemaVersion = 1
        status = $Status
        runId = $runId
        createdAt = "2026-08-09T00:00:00Z"
        firmware = $ExpectedFirmware
        koreaderVersion = $KOReader.Version
        koreaderArchiveSha256 = $KOReader.Sha256
        deviceFingerprint = Get-KindleFingerprint $Case.Device
        deviceIdentityHash = Get-KindleIdentityHash $Case.Device
        hotfixProofMode = Get-HotfixProofMode $Proof -Require
        hotfixProofManifestPath = $Proof.manifestPath
        hotfixProofManifestSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Proof.manifestPath).Hash.ToLowerInvariant()
    }
    $manifestPath = Join-Path $recordRoot "manifest.json"
    Write-ProjectJsonAtomic $manifestPath $manifest
    Write-ProjectTextAtomic (Get-FullProjectPath "logs\latest-koreader-stage.txt") $manifestPath
    return Get-KOReaderStageRecord -Require
}

try {
    $source = Get-Content -LiteralPath $implementation -Raw
    Assert-True ($source -match '"StageHotfixProbe"') "StageHotfixProbe is missing from action dispatch."
    Assert-True ($source -match '"VerifyHotfix"') "VerifyHotfix is missing from action dispatch."
    Assert-True ($source -match '"AcceptHotfixPersistentState"') "AcceptHotfixPersistentState is missing from action dispatch."
    Assert-True ($source -match '"VerifyKOReaderStage"') "VerifyKOReaderStage is missing from action dispatch."
    $stageKoAst = $ast.FindAll({
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq "Stage-KOReaderFallback"
        }, $true) | Select-Object -First 1
    Assert-True ($stageKoAst.Extent.Text -notmatch "JAILBROKEN") "StageKOReader still uses the old marker gate."
    Assert-True ($stageKoAst.Extent.Text -match "Get-VerifiedHotfixProofForDevice") "StageKOReader lacks the verified hotfix proof gate."
    Assert-True ($stageKoAst.Extent.Text -match "Assert-AirplaneConfirmation") "StageKOReader lost its Airplane Mode confirmation gate."
    $verifyKoAst = $ast.FindAll({
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq "Verify-KOReaderStage"
        }, $true) | Select-Object -First 1
    Assert-True ($null -ne $verifyKoAst) "Verify-KOReaderStage function is missing."
    Assert-True ($verifyKoAst.Extent.Text -notmatch "Assert-AirplaneConfirmation") "VerifyKOReaderStage is not read-only accessible without Airplane confirmation."

    $happy = New-FakeCase "happy"
    Stage-HotfixProbe $happy.Device
    $active = Get-HotfixProbeRecord "active" -Require
    Assert-True ([string]$active.manifest.status -ceq "staged") "Probe did not reach staged state."
    Assert-True ([string]$active.manifest.nonce -match "^[0-9a-f]{32}$") "Nonce is not canonical CSPRNG output."
    $probe = Join-Path $happy.Device "documents\Verify Hotfix.sh"
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $probe).Hash.ToLowerInvariant() -ceq [string]$active.manifest.probeSha256) "Staged probe hash differs."
    Assert-True (-not (Get-Content -LiteralPath $probe -Raw).Contains($HotfixProbe.NonceToken)) "Nonce token remained in staged probe."
    Assert-True (@(Get-ChildItem -LiteralPath (Join-Path $happy.Device "documents") -File).Count -eq 2) "Stage mutated more than the runner and one probe document."
    $result = Join-Path $happy.Device "documents\HOTFIX_VERIFIED_LAZYING_ART.txt"
    [IO.File]::WriteAllText($result, (Get-ExpectedHotfixProbeResultContent $active.manifest.nonce), (New-Object Text.UTF8Encoding($false)))
    Verify-UniversalHotfix $happy.Device
    $verified = Get-HotfixProbeRecord "verified" -Require
    Assert-True ([string]$verified.manifest.status -ceq "verified") "Hotfix record did not reach verified state."
    Assert-True ([string]$verified.manifest.proofMode -ceq "full-history-v1") "Full verification did not publish its explicit proof mode."
    Assert-True (-not (Test-Path -LiteralPath (Get-FullProjectPath "logs\latest-hotfix-probe.txt"))) "Active pointer was not retired."
    Verify-UniversalHotfix $happy.Device
    Assert-True (Test-Path -LiteralPath (Get-FullProjectPath "logs\latest-hotfix-verified.txt") -PathType Leaf) "Idempotent verification removed the verified pointer."

    $copyCrash = New-FakeCase "copy-before-state-crash"
    Stage-HotfixProbe $copyCrash.Device
    $crashRecord = Get-HotfixProbeRecord "active" -Require
    $crashRecord.manifest.status = "prepared"
    Write-ProjectJsonAtomic $crashRecord.manifestPath $crashRecord.manifest
    [IO.File]::WriteAllText(
        (Join-Path $copyCrash.Device "documents\HOTFIX_VERIFIED_LAZYING_ART.txt"),
        (Get-ExpectedHotfixProbeResultContent $crashRecord.manifest.nonce),
        (New-Object Text.UTF8Encoding($false))
    )
    Assert-Throws { Stage-HotfixProbe $copyCrash.Device } "state was reconciled.*VerifyHotfix" "Stage did not reconcile a copy-before-state crash."
    Assert-True ([string](Get-HotfixProbeRecord "active" -Require).manifest.status -ceq "staged") "Crash reconciliation did not persist staged state."
    Verify-UniversalHotfix $copyCrash.Device
    Assert-True ([string](Get-HotfixProbeRecord "verified" -Require).manifest.status -ceq "verified") "Reconciled proof did not verify."

    $badResult = New-FakeCase "bad-result"
    Stage-HotfixProbe $badResult.Device
    $badRecord = Get-HotfixProbeRecord "active" -Require
    [IO.File]::WriteAllText(
        (Join-Path $badResult.Device "documents\HOTFIX_VERIFIED_LAZYING_ART.txt"),
        (Get-ExpectedHotfixProbeResultContent $badRecord.manifest.nonce) + "extra`n",
        (New-Object Text.UTF8Encoding($false))
    )
    Assert-Throws { Verify-UniversalHotfix $badResult.Device } "exact expected UTF-8 bytes" "A non-exact result was accepted."
    Assert-True (-not (Test-Path -LiteralPath (Get-FullProjectPath "logs\latest-hotfix-verified.txt"))) "A bad result was marked verified."

    $preexisting = New-FakeCase "preexisting-result"
    [IO.File]::WriteAllText(
        (Join-Path $preexisting.Device "documents\HOTFIX_VERIFIED_LAZYING_ART.txt"),
        "forged`n",
        (New-Object Text.UTF8Encoding($false))
    )
    Assert-Throws { Stage-HotfixProbe $preexisting.Device } "existed before this nonce" "A pre-existing result was accepted."
    Assert-True (-not (Test-Path -LiteralPath (Get-FullProjectPath "logs\latest-hotfix-probe.txt"))) "Pre-existing evidence produced an active record."

    $badRunner = New-FakeCase "bad-runner"
    [IO.File]::WriteAllText(
        (Join-Path $badRunner.Device "documents\Run Hotfix.run_hotfix"),
        "2.5.0`r`n",
        (New-Object Text.UTF8Encoding($false))
    )
    Assert-Throws { Stage-HotfixProbe $badRunner.Device } "exact expected UTF-8 bytes" "A non-exact runner marker was accepted."
    Assert-True (-not (Test-Path -LiteralPath (Get-FullProjectPath "logs\latest-hotfix-probe.txt"))) "Bad runner produced an active record."

    $diagnostic = New-FakeCase "diagnostic-failure"
    Stage-HotfixProbe $diagnostic.Device
    $diagnosticRecord = Get-HotfixProbeRecord "active" -Require
    $originalProbePath = Join-Path $diagnostic.Device "documents\Verify Hotfix.sh"
    $originalProbeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $originalProbePath).Hash.ToLowerInvariant()
    Stage-HotfixDiagnostic $diagnostic.Device
    $diagnosticRecord = Get-HotfixProbeRecord "active" -Require
    Assert-True ([string]$diagnosticRecord.manifest.diagnosticStatus -ceq "staged") "Diagnostic did not reach staged state."
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $originalProbePath).Hash.ToLowerInvariant() -ceq $originalProbeHash) "Diagnostic staging changed the original probe."
    $diagnosticScript = Join-Path $diagnostic.Device "documents\Diagnose Hotfix.sh"
    Assert-True (Test-Path -LiteralPath $diagnosticScript -PathType Leaf) "Diagnostic document was not staged."
    & "C:\Program Files\Git\usr\bin\sh.exe" -n $diagnosticScript
    Assert-True ($LASTEXITCODE -eq 0) "Rendered diagnostic script failed POSIX shell syntax validation."
    $diagnosticText = Get-Content -LiteralPath $diagnosticScript -Raw
    Assert-True ($diagnosticText -match 'HOTFIX_DIAGNOSTIC_LAZYING_ART[.]txt') "Diagnostic script lacks its separate result path."
    Assert-True ($diagnosticText -match 'reason=\$REASON') "Diagnostic script lacks its fixed reason-only contract."
    Assert-True ($diagnosticText -match 'Hotfix diagnostic result already exists') "Diagnostic script lacks its exclusive-result rerun gate."
    $diagnosticResult = Join-Path $diagnostic.Device "documents\HOTFIX_DIAGNOSTIC_LAZYING_ART.txt"
    [IO.File]::WriteAllText(
        $diagnosticResult,
        (Get-ExpectedHotfixDiagnosticContent $diagnosticRecord.manifest.nonce "JOB_LOG"),
        (New-Object Text.UTF8Encoding($false))
    )
    $diagnosticOutput = Read-HotfixDiagnostic $diagnostic.Device
    Assert-True ($diagnosticOutput -match '"reasonCode":\s*"JOB_LOG"') "Allowlisted diagnostic code was not reported."
    Assert-True ([string](Get-HotfixProbeRecord "active" -Require).manifest.diagnosticStatus -ceq "failed") "Diagnostic failure was not persisted."

    $diagnosticTamper = New-FakeCase "diagnostic-tamper"
    Stage-HotfixProbe $diagnosticTamper.Device
    Stage-HotfixDiagnostic $diagnosticTamper.Device
    $tamperRecord = Get-HotfixProbeRecord "active" -Require
    [IO.File]::WriteAllText(
        (Join-Path $diagnosticTamper.Device "documents\HOTFIX_DIAGNOSTIC_LAZYING_ART.txt"),
        "kindle-hotfix-diagnostic-v1`nnonce=$($tamperRecord.manifest.nonce)`nhotfix=2.5.0`nreason=FREEFORM_DATA`n",
        (New-Object Text.UTF8Encoding($false))
    )
    Assert-Throws { Read-HotfixDiagnostic $diagnosticTamper.Device } "does not match any exact.*allowlisted" "A free-form diagnostic was accepted."

    $diagnosticSuccess = New-FakeCase "diagnostic-success"
    Stage-HotfixProbe $diagnosticSuccess.Device
    Stage-HotfixDiagnostic $diagnosticSuccess.Device
    $successDiagnosticRecord = Get-HotfixProbeRecord "active" -Require
    [IO.File]::WriteAllText(
        (Join-Path $diagnosticSuccess.Device "documents\HOTFIX_VERIFIED_LAZYING_ART.txt"),
        (Get-ExpectedHotfixProbeResultContent $successDiagnosticRecord.manifest.nonce),
        (New-Object Text.UTF8Encoding($false))
    )
    Verify-UniversalHotfix $diagnosticSuccess.Device
    Assert-True ([string](Get-HotfixProbeRecord "verified" -Require).manifest.status -ceq "verified") "Diagnostic success did not use the full proof contract."

    $persistent = New-FakeCase "persistent-state-v2"
    $persistentRecord = Complete-FakeHotfixDiagnostic $persistent "JOB_LOG"
    $persistentResult = Join-Path $persistent.Device "documents\HOTFIX_DIAGNOSTIC_LAZYING_ART.txt"
    foreach ($reasonCode in @($HotfixDiagnosticReasonCodes | Where-Object { $_ -cne "START_LOG" })) {
        $content = Get-ExpectedHotfixDiagnosticContent $persistentRecord.manifest.nonce $reasonCode
        [IO.File]::WriteAllText($persistentResult, $content, (New-Object Text.UTF8Encoding($false)))
        $persistentRecord.manifest.diagnosticReasonCode = $reasonCode
        $persistentRecord.manifest.diagnosticResultSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $persistentResult).Hash.ToLowerInvariant()
        Write-ProjectJsonAtomic $persistentRecord.manifestPath $persistentRecord.manifest
        Assert-Throws { Accept-HotfixPersistentState $persistent.Device } "exact recorded START_LOG" "Persistent acceptance allowed diagnostic reason $reasonCode."
    }
    $startContent = Get-ExpectedHotfixDiagnosticContent $persistentRecord.manifest.nonce "START_LOG"
    [IO.File]::WriteAllText($persistentResult, $startContent, (New-Object Text.UTF8Encoding($false)))
    $persistentRecord.manifest.diagnosticReasonCode = "START_LOG"
    $persistentRecord.manifest.diagnosticResultSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $persistentResult).Hash.ToLowerInvariant()
    Write-ProjectJsonAtomic $persistentRecord.manifestPath $persistentRecord.manifest
    $persistentOutput = Accept-HotfixPersistentState $persistent.Device
    Assert-True ($persistentOutput -match '"proofMode":\s*"persistent-state-v2"') "Persistent acceptance did not report its proof mode."
    $persistentProof = Get-HotfixProbeRecord "verified" -Require
    Assert-True ([string]$persistentProof.manifest.status -ceq "staged") "Persistent acceptance changed the original staged status."
    Assert-True ([string]$persistentProof.manifest.proofMode -ceq "persistent-state-v2") "Persistent proof mode was not published."
    Assert-True ([string]$persistentProof.manifest.historyEvidence -ceq "log-unavailable") "Persistent proof overstated log evidence."
    Assert-True ($persistentProof.manifest.historicalJobSequenceVerified -eq $false) "Persistent proof overstated historical job evidence."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $persistent.Device "documents\HOTFIX_VERIFIED_LAZYING_ART.txt"))) "Persistent acceptance manufactured a full-history result."
    Assert-True (Test-Path -LiteralPath $persistentResult -PathType Leaf) "Persistent acceptance removed its START_LOG artifact."
    Assert-True (-not (Test-Path -LiteralPath (Get-FullProjectPath "logs\latest-hotfix-probe.txt"))) "Persistent acceptance did not retire the active pointer."
    Accept-HotfixPersistentState $persistent.Device | Out-Null
    Assert-True ([string](Get-VerifiedHotfixProofForDevice $persistent.Device).proofMode -ceq "persistent-state-v2") "Persistent proof was not idempotently device-verifiable."

    $persistentConflict = New-FakeCase "persistent-success-conflict"
    $conflictRecord = Complete-FakeHotfixDiagnostic $persistentConflict "START_LOG"
    [IO.File]::WriteAllText(
        (Join-Path $persistentConflict.Device "documents\HOTFIX_VERIFIED_LAZYING_ART.txt"),
        (Get-ExpectedHotfixProbeResultContent $conflictRecord.manifest.nonce),
        (New-Object Text.UTF8Encoding($false))
    )
    Assert-Throws { Accept-HotfixPersistentState $persistentConflict.Device } "conflicts with START_LOG" "Persistent acceptance allowed conflicting full-history success."

    $persistentTamper = New-FakeCase "persistent-tamper"
    $tamperPersistentRecord = Complete-FakeHotfixDiagnostic $persistentTamper "START_LOG"
    $tamperedProbe = Join-Path $persistentTamper.Device "documents\Verify Hotfix.sh"
    [IO.File]::AppendAllText($tamperedProbe, "# tampered`n", (New-Object Text.UTF8Encoding($false)))
    Assert-Throws { Accept-HotfixPersistentState $persistentTamper.Device } "Verify Hotfix document is missing or changed" "Persistent acceptance allowed a changed original probe."

    $persistentKo = New-FakeCase "persistent-koreader"
    Complete-FakeHotfixDiagnostic $persistentKo "START_LOG" | Out-Null
    Accept-HotfixPersistentState $persistentKo.Device | Out-Null
    Stage-KOReaderFallback $persistentKo.Device
    $persistentKoRecord = Get-KOReaderStageRecord -Require
    Assert-True ([string]$persistentKoRecord.manifest.hotfixProofMode -ceq "persistent-state-v2") "KOReader did not pin the accepted persistent proof mode."
    Assert-True ([string]$persistentKoRecord.manifest.status -ceq "complete") "KOReader rejected the exact persistent-state proof."

    $unverifiedKo = New-FakeCase "unverified-koreader"
    Assert-Throws { Stage-KOReaderFallback $unverifiedKo.Device } "No local hotfix probe verified record" "KOReader accepted an unverified hotfix."
    Assert-True (Test-Path -LiteralPath (Join-Path $unverifiedKo.Device ".kindle-ota-space-filler") -PathType Container) "Unverified KOReader removed the filler."

    $koHappy = New-FakeCase "koreader-happy"
    $koProof = Complete-FakeHotfixProof $koHappy
    Assert-Throws { Remove-OtaFiller $koHappy.Device } "closed Store route" "Public RemoveFiller reopened after WB2."
    Stage-KOReaderFallback $koHappy.Device
    $koRecord = Get-KOReaderStageRecord -Require
    Assert-True ([string]$koRecord.manifest.status -ceq "complete") "KOReader stage did not complete."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $koHappy.Device ".kindle-ota-space-filler"))) "Verified KOReader did not remove the filler."
    Assert-True (Test-Path -LiteralPath (Join-Path $koHappy.Device "koreader\koreader.sh") -PathType Leaf) "KOReader tree was not copied."
    $ConfirmedAirplaneMode = $false
    try {
        $verifyKoOutput = Verify-KOReaderStage $koHappy.Device
    } finally {
        $ConfirmedAirplaneMode = $true
    }
    Assert-True ($verifyKoOutput -match '"status":\s*"verified"') "VerifyKOReaderStage did not report success."
    Assert-True ($verifyKoOutput -match '"proofMode":\s*"full-history-v1"') "VerifyKOReaderStage omitted the bound proof mode."
    Assert-True ($verifyKoOutput -notmatch [regex]::Escape([string]$koRecord.manifest.deviceFingerprint)) "VerifyKOReaderStage exposed a device fingerprint."
    Assert-True ($verifyKoOutput -notmatch [regex]::Escape([string]$koRecord.manifest.deviceIdentityHash)) "VerifyKOReaderStage exposed a device identity hash."

    $completedAt = [string]$koRecord.manifest.completedAt
    $koRecord.manifest.status = "staging"
    Write-ProjectJsonAtomic $koRecord.manifestPath $koRecord.manifest
    Assert-Throws { Verify-KOReaderStage $koHappy.Device } "staging is not complete" "VerifyKOReaderStage accepted an incomplete record."
    $koRecord.manifest.status = "complete"
    $koRecord.manifest.completedAt = "not-a-timestamp"
    Write-ProjectJsonAtomic $koRecord.manifestPath $koRecord.manifest
    Assert-Throws { Verify-KOReaderStage $koHappy.Device } "valid completedAt" "VerifyKOReaderStage accepted an invalid completion time."
    $koRecord.manifest.completedAt = $completedAt
    $koRecord.manifest.hotfixProofMode = "persistent-state-v2"
    Write-ProjectJsonAtomic $koRecord.manifestPath $koRecord.manifest
    Assert-Throws { Verify-KOReaderStage $koHappy.Device } "does not match the verified hotfix proof" "VerifyKOReaderStage accepted a mismatched proof mode."
    $koRecord.manifest.hotfixProofMode = "full-history-v1"
    Write-ProjectJsonAtomic $koRecord.manifestPath $koRecord.manifest

    $fillerPath = Join-Path $koHappy.Device ".kindle-ota-space-filler"
    New-Item -ItemType Directory -Path $fillerPath | Out-Null
    Assert-Throws { Verify-KOReaderStage $koHappy.Device } "filler reappeared" "VerifyKOReaderStage accepted a reappeared filler."
    Remove-Item -LiteralPath $fillerPath -Force
    $updatePath = Join-Path $koHappy.Device "Update_unexpected.bin"
    [IO.File]::WriteAllBytes($updatePath, [byte[]](1, 2, 3))
    Assert-Throws { Verify-KOReaderStage $koHappy.Device } "update package.*review" "VerifyKOReaderStage accepted a root update package."
    Remove-Item -LiteralPath $updatePath -Force

    $corePath = Join-Path $koHappy.Device "koreader\koreader.sh"
    $coreBackup = "$corePath.verify-test"
    Move-Item -LiteralPath $corePath -Destination $coreBackup
    Assert-Throws { Verify-KOReaderStage $koHappy.Device } "core launcher is missing" "VerifyKOReaderStage accepted a missing core launcher."
    Move-Item -LiteralPath $coreBackup -Destination $corePath
    $extensionPath = Join-Path $koHappy.Device "extensions\koreader"
    $extensionBackup = Join-Path $koHappy.Device "extensions\koreader.verify-test"
    Move-Item -LiteralPath $extensionPath -Destination $extensionBackup
    Assert-Throws { Verify-KOReaderStage $koHappy.Device } "extension directory is missing" "VerifyKOReaderStage accepted a missing extension directory."
    Move-Item -LiteralPath $extensionBackup -Destination $extensionPath

    $deviceLauncherPath = Join-Path $koHappy.Device "documents\KOReader.sh"
    $deviceLauncherBytes = [IO.File]::ReadAllBytes($deviceLauncherPath)
    [IO.File]::WriteAllText($deviceLauncherPath, "tampered`n", (New-Object Text.UTF8Encoding($false)))
    Assert-Throws { Verify-KOReaderStage $koHappy.Device } "exact expected UTF-8 bytes" "VerifyKOReaderStage accepted a changed document launcher."
    [IO.File]::WriteAllBytes($deviceLauncherPath, $deviceLauncherBytes)
    $localLauncherPath = Join-Path $koHappy.Project "assets\koreader-lazy\KOReader.sh"
    $localLauncherBytes = [IO.File]::ReadAllBytes($localLauncherPath)
    [IO.File]::WriteAllText($localLauncherPath, "#!/bin/sh`r`n", (New-Object Text.UTF8Encoding($true)))
    Assert-Throws { Verify-KOReaderStage $koHappy.Device } "pinned SHA-256" "VerifyKOReaderStage accepted a changed local launcher asset."
    [IO.File]::WriteAllBytes($localLauncherPath, $localLauncherBytes)
    Verify-KOReaderStage $koHappy.Device | Out-Null

    Stage-KOReaderFallback $koHappy.Device
    Assert-True ([string](Get-KOReaderStageRecord -Require).manifest.status -ceq "complete") "Completed KOReader stage was not safely repairable."
    Verify-UniversalHotfix $koHappy.Device

    $emptyCrash = New-FakeCase "authorized-empty-filler"
    $emptyProof = Complete-FakeHotfixProof $emptyCrash
    $emptyRecord = New-FakeKOReaderStageRecord $emptyCrash $emptyProof "filler-removal-authorized"
    Get-ChildItem -LiteralPath (Join-Path $emptyCrash.Device ".kindle-ota-space-filler") -Force | Remove-Item -Force
    Remove-VerifiedPostHotfixOtaFiller $emptyCrash.Device $emptyRecord $emptyProof
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $emptyCrash.Device ".kindle-ota-space-filler"))) "Authorized empty-filler crash did not resume."
    Assert-True ([string](Get-KOReaderStageRecord -Require).manifest.status -ceq "filler-removed") "Authorized removal did not persist completion."

    $copyResume = New-FakeCase "koreader-copy-resume"
    $resumeProof = Complete-FakeHotfixProof $copyResume
    $resumeRecord = New-FakeKOReaderStageRecord $copyResume $resumeProof "staging"
    Remove-Item -LiteralPath (Join-Path $copyResume.Device ".kindle-ota-space-filler") -Recurse -Force
    Stage-KOReaderFallback $copyResume.Device
    Assert-True ([string](Get-KOReaderStageRecord -Require).manifest.status -ceq "complete") "KOReader copy did not resume after authorized filler removal."

    "PASS: PW5SE hotfix proof fake-root tests"
} finally {
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
