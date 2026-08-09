[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$implementation = Join-Path $repoRoot "scripts\pw5se-winterbreak.ps1"

# Load function definitions only. No removable-drive discovery or top-level
# action dispatch runs in this test.
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $implementation,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
    throw "Implementation parse failed: $($parseErrors[0].Message)"
}
foreach ($functionAst in $ast.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
        }, $true)) {
    Invoke-Expression $functionAst.Extent.Text
}

$ExpectedFirmware = "5.15.1"
$FillerOwnerText = "lazying-art Kindle PW5SE WinterBreak filler v1"
$StoreSandboxRelativePath = ".active_content_sandbox"
$ConfirmedAirplaneMode = $true
$ForceFirmwareOverride = $false
$WinterBreak = [ordered]@{
    Version = "2.1.0"
    Url = "https://github.com/KindleModding/WinterBreak/releases/download/v2.1.0/WinterBreak.tar.gz"
    File = "WinterBreak-v2.1.0.tar.gz"
    Sha256 = "dc04fff5fcb685834cba9f9e95d4818b473d4100b2d40b8bb7c598ad09eb850d"
}
$WinterBreak2 = [ordered]@{
    Version = "1.0.0"
    Url = "https://github.com/KindleModding/Winterbreak2/releases/download/v1.0.0/wb2.zip"
    File = "wb2.zip"
    Sha256 = "932ff113c414c9b0109b98d7f4b96da20815364fb4905e4483581b881b2ae2e2"
}
$UniversalHotfix = [ordered]@{
    Version = "2.5.0"
    Url = "https://github.com/KindleModding/Hotfix/releases/download/2.5.0/Update_hotfix_universal.bin"
    File = "Update_hotfix_universal.bin"
    Sha256 = "94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59"
}
$WinterBreak2Files = @("jb.sh", "patchedUks.sqsh", "winterbreak2\dialoger.html")
$WinterBreak2Directories = @("winterbreak2")
$WinterBreak2SuccessEvidence = @(
    "Developer keys installed successfully (Standard Method)! (pubdevkey01.pem)",
    "Enabled developer flag",
    "Enabled mntus exec flag",
    "*** Finished installing jailbreak! ***",
    "***   Please Install HOTFIX now    ***"
)
$WinterBreak2FailureEvidence = @("ERR -", " FAIL", "ERROR:")

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("kindle-pw5se-wb2-test-" + [Guid]::NewGuid().ToString("N"))
$script:activeContext = $null
$script:mockFirmware = "5.15.1"
$script:mockFreeBytes = [int64](80MB)
$script:mockIdentityHash = ("a" * 64)

function Get-ProjectRoot {
    return $script:activeContext.Project
}

function Get-FreeBytes {
    param([Parameter(Mandatory = $true)][string] $Root)
    return $script:mockFreeBytes
}

function Get-KindleInfo {
    param([Parameter(Mandatory = $true)][string] $Root)
    return [ordered]@{
        firmware = $script:mockFirmware
        jailbrokenMarker = Test-Path -LiteralPath (Join-Path $Root "documents\JAILBROKEN.txt")
        winterBreakStaged = $true
        otaFiller = Test-Path -LiteralPath (Join-Path $Root ".kindle-ota-space-filler")
    }
}

function Get-KindleIdentityHash {
    param([Parameter(Mandatory = $true)][string] $Root)
    return $script:mockIdentityHash
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

function Get-SelectedTreeSignature {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)][string[]] $RelativeRoots
    )
    $rows = @()
    foreach ($relativeRoot in $RelativeRoots) {
        $absolute = Join-Path $Root $relativeRoot
        foreach ($file in Get-ChildItem -LiteralPath $absolute -File -Recurse -Force) {
            $relative = $file.FullName.Substring(([IO.Path]::GetFullPath($Root).TrimEnd("\") + "\").Length)
            $rows += "$relative|$((Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant())"
        }
    }
    return ($rows | Sort-Object) -join "`n"
}

function New-MockCase {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [switch] $Unbound
    )

    $caseRoot = Join-Path $testRoot $Name
    $project = Join-Path $caseRoot "project"
    $kindle = Join-Path $caseRoot "kindle"
    foreach ($directory in @(
            $project,
            (Join-Path $project "downloads"),
            (Join-Path $kindle "documents"),
            (Join-Path $kindle "system"),
            (Join-Path $kindle ".kindle-ota-space-filler"),
            (Join-Path $kindle "winterbreak2")
        )) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    Copy-Item -LiteralPath (Join-Path $repoRoot "downloads\wb2.zip") -Destination (Join-Path $project "downloads\wb2.zip")
    Copy-Item -LiteralPath (Join-Path $repoRoot "downloads\Update_hotfix_universal.bin") -Destination (Join-Path $project "downloads\Update_hotfix_universal.bin")
    Copy-Item -LiteralPath (Join-Path $repoRoot "downloads\WinterBreak-v2.1.0.tar.gz") -Destination (Join-Path $project "downloads\WinterBreak-v2.1.0.tar.gz")
    Set-Content -LiteralPath (Join-Path $kindle "system\version.txt") -Value "Kindle 5.15.1 WB2 fake-root test" -Encoding ASCII
    $context = [pscustomobject]@{
        Name = $Name
        Project = $project
        Kindle = $kindle
        StoreRoots = @(".active_content_sandbox", "apps\tech.hackerdude.winterbreak", "mesquito")
        OriginalJbHash = $null
        StoreManifestPath = $null
    }
    $script:activeContext = $context
    $script:mockFirmware = "5.15.1"
    $script:mockFreeBytes = [int64](80MB)
    $script:mockIdentityHash = ("a" * 64)

    $pinned = Get-PinnedStoreStageInventory
    foreach ($relative in $pinned.directories) {
        New-Item -ItemType Directory -Path (Join-Path $kindle $relative) -Force | Out-Null
    }
    foreach ($entry in $pinned.files) {
        $destination = Join-Path $kindle $entry.relativePath
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $pinned.stageRoot $entry.relativePath) -Destination $destination
    }
    Set-Content -LiteralPath (Join-Path $kindle "jb.sh") -Value "pre-existing-jb-$Name" -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $kindle "winterbreak2\user-note.txt") -Value "preserve-$Name" -Encoding ASCII
    $context.OriginalJbHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $kindle "jb.sh")).Hash.ToLowerInvariant()
    $filler = Join-Path $kindle ".kindle-ota-space-filler"
    [IO.File]::WriteAllText((Join-Path $filler ".lazying-art-filler-owner-v1"), "$FillerOwnerText`n", [Text.Encoding]::ASCII)
    [IO.File]::WriteAllBytes((Join-Path $filler "filler-000.bin"), [byte[]](0, 1, 2, 3))

    $storeFiles = @()
    foreach ($entry in $pinned.files) {
        $storeFiles += [ordered]@{
            relativePath = $entry.relativePath
            wasPresent = $false
            originalSha256 = $null
            stagedSha256 = $entry.sha256
        }
    }
    $storeDirectories = @($pinned.directories | ForEach-Object {
            [ordered]@{ relativePath = $_; wasPresent = $false }
        })
    $storeManifest = [ordered]@{
        status = "complete"
        firmware = "5.15.1"
        winterBreakVersion = $WinterBreak.Version
        archiveSha256 = $WinterBreak.Sha256
        deviceFingerprint = Get-KindleFingerprint $kindle
        files = $storeFiles
        directories = $storeDirectories
    }
    if (-not $Unbound) {
        $storeManifest["deviceIdentityHash"] = $script:mockIdentityHash
        $storeManifest["deviceIdentityScheme"] = "windows-volume-serial-size-sha256-v1"
    }
    $storeRecordRoot = Join-Path $project "device-backups\winterbreak-stage-5.15.1-mock-$Name"
    New-Item -ItemType Directory -Path $storeRecordRoot -Force | Out-Null
    $context.StoreManifestPath = Join-Path $storeRecordRoot "manifest.json"
    $storeManifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $context.StoreManifestPath -Encoding UTF8
    $storePointer = Join-Path $project "logs\latest-winterbreak-stage.txt"
    New-Item -ItemType Directory -Path (Split-Path $storePointer -Parent) -Force | Out-Null
    Set-Content -LiteralPath $storePointer -Value $context.StoreManifestPath -Encoding UTF8
    return $context
}

function Write-SuccessLog {
    param(
        [Parameter(Mandatory = $true)] $Context,
        [string] $ExtraLine
    )
    $lines = @($WinterBreak2SuccessEvidence)
    if ($ExtraLine) { $lines += $ExtraLine }
    Set-Content -LiteralPath (Join-Path $Context.Kindle "winterbreak.log") -Value $lines -Encoding ASCII
}

function Get-ActiveWb2Record {
    return Get-WinterBreak2Record "active" -Require
}

function New-MockStoreCacheRecord {
    param([Parameter(Mandatory = $true)] $Context)

    $recordRoot = Join-Path $Context.Project ("device-backups\winterbreak-store-cache-mock-" + $Context.Name)
    New-Item -ItemType Directory -Path $recordRoot -Force | Out-Null
    $manifestPath = Join-Path $recordRoot "manifest.json"
    [ordered]@{
        status = "complete"
        firmware = "5.15.1"
        deviceFingerprint = Get-KindleFingerprint $Context.Kindle
        files = @()
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $pointer = Join-Path $Context.Project "logs\latest-winterbreak-store-cache.txt"
    Set-Content -LiteralPath $pointer -Value $manifestPath -Encoding UTF8
    return [pscustomobject]@{ ManifestPath = $manifestPath; PointerPath = $pointer }
}

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

    # Identity adoption is explicit and local-only. Staging refuses an
    # unbound Store record, binding is idempotent, and a different stable
    # identity cannot adopt the record later.
    $binding = New-MockCase "identity-binding" -Unbound
    Assert-Throws { Stage-WinterBreak2 $binding.Kindle } "BindDeviceIdentity" "WB2 staging accepted an unbound Store-stage record."
    Bind-WinterBreak2DeviceIdentity $binding.Kindle
    $boundManifest = Get-Content -LiteralPath $binding.StoreManifestPath -Raw | ConvertFrom-Json
    Assert-True ($boundManifest.deviceIdentityHash -eq ("a" * 64)) "BindDeviceIdentity did not persist the mock stable identity."
    Bind-WinterBreak2DeviceIdentity $binding.Kindle
    $script:mockIdentityHash = ("b" * 64)
    Assert-Throws { Bind-WinterBreak2DeviceIdentity $binding.Kindle } "device identity" "A different stable device identity was accepted."

    # A same-count substituted Store path is not the pinned 17-file archive.
    $substituted = New-MockCase "substituted-store-path"
    $substitutedManifest = Get-Content -LiteralPath $substituted.StoreManifestPath -Raw | ConvertFrom-Json
    $firstStoreFile = $substitutedManifest.files[0]
    $substituteRelative = "documents\substituted-store-payload.bin"
    Copy-Item -LiteralPath (Join-Path $substituted.Kindle $firstStoreFile.relativePath) -Destination (Join-Path $substituted.Kindle $substituteRelative)
    $firstStoreFile.relativePath = $substituteRelative
    $substitutedManifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $substituted.StoreManifestPath -Encoding UTF8
    Assert-Throws { Stage-WinterBreak2 $substituted.Kindle } "path/hash set differs" "A same-count substituted Store-stage path was accepted."

    # Before a WB2 write-ahead record exists, a prospective deterministic temp
    # name is unowned and must be preserved rather than cleaned or adopted.
    $tempCollision = New-MockCase "temp-collision"
    $tempStage = Expand-WinterBreak2
    $tempSourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $tempStage "jb.sh")).Hash.ToLowerInvariant()
    $collidingTemp = Get-WinterBreak2OwnedTempPath (Join-Path $tempCollision.Kindle "jb.sh") $tempSourceHash "stage"
    Set-Content -LiteralPath $collidingTemp -Value "unowned-sentinel" -Encoding ASCII
    Assert-Throws { Stage-WinterBreak2 $tempCollision.Kindle } "unowned deterministic" "An unowned WB2 temp collision was adopted or deleted."
    Assert-True ((Get-Content -LiteralPath $collidingTemp -Raw) -match "unowned-sentinel") "WB2 staging deleted an unowned temp collision."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $tempCollision.Project "logs\latest-winterbreak2-stage.txt"))) "Temp-collision refusal created a WB2 pointer."

    # Exact stock staging is idempotent, preserves the Store payload/filler,
    # and rolls back collisions without deleting unrelated directory content.
    $roundTrip = New-MockCase "round-trip"
    $storeBefore = Get-SelectedTreeSignature $roundTrip.Kindle $roundTrip.StoreRoots
    Stage-WinterBreak2 $roundTrip.Kindle
    $roundTripRecord = Get-ActiveWb2Record
    Assert-True ([string]$roundTripRecord.manifest.status -eq "complete") "WB2 stage did not commit complete status."
    Assert-True (@($roundTripRecord.manifest.files).Count -eq 3) "WB2 manifest does not contain exactly three files."
    Assert-True (@($roundTripRecord.manifest.directories).Count -eq 1) "WB2 manifest does not contain exactly one directory."
    foreach ($relative in $WinterBreak2Files) {
        Assert-True (Test-Path -LiteralPath (Join-Path $roundTrip.Kindle $relative) -PathType Leaf) "WB2 missed exact path $relative."
    }
    Assert-True ((Get-SelectedTreeSignature $roundTrip.Kindle $roundTrip.StoreRoots) -eq $storeBefore) "WB2 staging changed the Store WinterBreak tree."
    Assert-True (Test-Path -LiteralPath (Join-Path $roundTrip.Kindle ".kindle-ota-space-filler")) "WB2 staging removed the OTA filler."
    $recordPath = $roundTripRecord.manifestPath
    Stage-WinterBreak2 $roundTrip.Kindle
    Assert-True ((Get-ActiveWb2Record).manifestPath -eq $recordPath) "Idempotent WB2 stage replaced its rollback record."
    Assert-True (@(Get-ChildItem -LiteralPath (Join-Path $roundTrip.Project "device-backups") -Directory -Filter "winterbreak2-stage-*").Count -eq 1) "Idempotent WB2 stage created a second record."
    Undo-WinterBreak2 $roundTrip.Kindle
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $roundTrip.Kindle "jb.sh")).Hash.ToLowerInvariant() -eq $roundTrip.OriginalJbHash) "WB2 rollback did not restore the original jb.sh."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $roundTrip.Kindle "patchedUks.sqsh"))) "WB2 rollback left patchedUks.sqsh."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $roundTrip.Kindle "winterbreak2\dialoger.html"))) "WB2 rollback left dialoger.html."
    Assert-True (Test-Path -LiteralPath (Join-Path $roundTrip.Kindle "winterbreak2\user-note.txt")) "WB2 rollback deleted unrelated directory content."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $roundTrip.Project "logs\latest-winterbreak2-stage.txt"))) "WB2 rollback left its active pointer."
    $roundTripManifest = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
    Assert-True ($roundTripManifest.status -eq "rolledBack") "WB2 rollback did not persist rolledBack status."
    Assert-True ((Get-SelectedTreeSignature $roundTrip.Kindle $roundTrip.StoreRoots) -eq $storeBefore) "WB2 rollback changed the Store WinterBreak tree."
    $staleRollbackPointer = Join-Path $roundTrip.Project "logs\latest-winterbreak2-stage.txt"
    Set-Content -LiteralPath $staleRollbackPointer -Value $recordPath -Encoding UTF8
    Undo-WinterBreak2 $roundTrip.Kindle
    Assert-True (-not (Test-Path -LiteralPath $staleRollbackPointer)) "A stale rolledBack pointer was not retired idempotently."
    Assert-True (@(Get-ChildItem -LiteralPath $roundTrip.Project -File -Recurse -Filter "*.tmp").Count -eq 0) "Atomic project writes left temporary files behind."

    # A prepared record resumes only from original/staged destination hashes.
    $resume = New-MockCase "resume"
    Stage-WinterBreak2 $resume.Kindle
    $resumeRecord = Get-ActiveWb2Record
    $resumeManifest = Get-Content -LiteralPath $resumeRecord.manifestPath -Raw | ConvertFrom-Json
    $resumeManifest.status = "prepared"
    $resumeManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resumeRecord.manifestPath -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $resume.Kindle "jb.sh") -Value "pre-existing-jb-resume" -Encoding ASCII
    Remove-Item -LiteralPath (Join-Path $resume.Kindle "patchedUks.sqsh") -Force
    Remove-Item -LiteralPath (Join-Path $resume.Kindle "winterbreak2\dialoger.html") -Force
    $resumePatchedEntry = @($resumeManifest.files | Where-Object { $_.relativePath -eq "patchedUks.sqsh" })[0]
    Set-Content -LiteralPath (Join-Path $resume.Kindle $resumePatchedEntry.stageTemporaryRelativePath) -Value "partial-copy" -Encoding ASCII
    Stage-WinterBreak2 $resume.Kindle
    Assert-True ((Get-ActiveWb2Record).manifest.status -eq "complete") "WB2 prepared-record resume did not complete."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $resume.Kindle $resumePatchedEntry.stageTemporaryRelativePath))) "WB2 resume left its recorded partial temp file."

    # The complete-stage idempotent path must validate rollback material, not
    # merely the files currently staged on the fake Kindle.
    $missingBackup = New-MockCase "missing-complete-backup"
    Stage-WinterBreak2 $missingBackup.Kindle
    $missingBackupRecord = Get-ActiveWb2Record
    Remove-Item -LiteralPath (Join-Path (Split-Path $missingBackupRecord.manifestPath -Parent) "overwritten\jb.sh") -Force
    Assert-Throws { Stage-WinterBreak2 $missingBackup.Kindle } "rollback backup verification failed" "An idempotent WB2 stage accepted a missing rollback backup."
    Assert-True ((Get-ActiveWb2Record).manifest.status -eq "complete") "Missing-backup refusal changed the complete record status."

    # Flipping wasPresent cannot turn a backed-up original into a deletable new
    # file, and a WB2 record is also bound to the stable identity independently
    # of the legacy version-file fingerprint.
    $tamperedPresence = New-MockCase "tampered-presence"
    Stage-WinterBreak2 $tamperedPresence.Kindle
    $tamperedPresenceRecord = Get-ActiveWb2Record
    $tamperedPresenceManifest = Get-Content -LiteralPath $tamperedPresenceRecord.manifestPath -Raw | ConvertFrom-Json
    $jbEntry = @($tamperedPresenceManifest.files | Where-Object { $_.relativePath -eq "jb.sh" })[0]
    $jbEntry.wasPresent = $false
    $jbEntry.originalSha256 = $null
    $jbEntry.restoreTemporaryRelativePath = $null
    $tamperedPresenceManifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $tamperedPresenceRecord.manifestPath -Encoding UTF8
    Assert-Throws { Undo-WinterBreak2 $tamperedPresence.Kindle } "backup state is inconsistent" "A wasPresent flip was accepted despite its original-file backup."
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $tamperedPresence.Kindle "jb.sh")).Hash.ToLowerInvariant() -ne $tamperedPresence.OriginalJbHash) "Tampered presence metadata caused the staged jb.sh to be deleted/restored unexpectedly."

    $wrongWb2Identity = New-MockCase "wrong-wb2-identity"
    Stage-WinterBreak2 $wrongWb2Identity.Kindle
    $wrongStoreManifest = Get-Content -LiteralPath $wrongWb2Identity.StoreManifestPath -Raw | ConvertFrom-Json
    $wrongStoreManifest.deviceIdentityHash = ("b" * 64)
    $wrongStoreManifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $wrongWb2Identity.StoreManifestPath -Encoding UTF8
    $script:mockIdentityHash = ("b" * 64)
    Assert-Throws { Stage-WinterBreak2 $wrongWb2Identity.Kindle } "stable device identity" "A different identity resumed an existing WB2 record."

    # Diverged files are preserved and keep the rollback pointer active.
    $diverged = New-MockCase "diverged"
    Stage-WinterBreak2 $diverged.Kindle
    $divergedRecord = Get-ActiveWb2Record
    Set-Content -LiteralPath (Join-Path $diverged.Kindle "winterbreak2\dialoger.html") -Value "operator-change" -Encoding ASCII
    Undo-WinterBreak2 $diverged.Kindle
    Assert-True ((Get-Content -LiteralPath (Join-Path $diverged.Kindle "winterbreak2\dialoger.html") -Raw) -match "operator-change") "WB2 rollback overwrote a diverged file."
    Assert-True ((Get-Content -LiteralPath $divergedRecord.manifestPath -Raw | ConvertFrom-Json).status -eq "rollback-incomplete") "Diverged rollback did not persist rollback-incomplete."
    Assert-True (Test-Path -LiteralPath $divergedRecord.pointerPath) "Diverged rollback retired its recovery pointer."

    # Generic Store/filler mutators close as soon as WB2 state exists, while
    # dedicated rollback remains available despite filler, free-space, Store,
    # or unrelated OTA drift.
    $rollbackDrift = New-MockCase "rollback-drift"
    Stage-WinterBreak2 $rollbackDrift.Kindle
    Assert-Throws { Remove-OtaFiller $rollbackDrift.Kindle } "closed Store route" "Generic RemoveFiller was not isolated from active WB2 state."
    Assert-True (Test-Path -LiteralPath (Join-Path $rollbackDrift.Kindle ".kindle-ota-space-filler")) "Blocked RemoveFiller removed the guard."
    Assert-Throws { Undo-WinterBreakStage $rollbackDrift.Kindle } "closed Store route" "Legacy UndoStage was not isolated from active WB2 state."
    Assert-Throws { Assert-StoreRouteOpen $rollbackDrift.Kindle "VerifyJailbreak" } "closed Store route" "Legacy VerifyJailbreak was not isolated from active WB2 state."
    Remove-Item -LiteralPath (Join-Path $rollbackDrift.Kindle ".kindle-ota-space-filler") -Recurse -Force
    $script:mockFreeBytes = [int64](140MB)
    $rollbackStoreManifest = Get-Content -LiteralPath $rollbackDrift.StoreManifestPath -Raw | ConvertFrom-Json
    $storeDriftFile = Join-Path $rollbackDrift.Kindle ([string]$rollbackStoreManifest.files[0].relativePath)
    Set-Content -LiteralPath $storeDriftFile -Value "post-stage-store-drift" -Encoding ASCII
    $driftUpdate = Join-Path $rollbackDrift.Kindle "UPDATE-drift.bin"
    [IO.File]::WriteAllBytes($driftUpdate, [byte[]](1, 9, 9, 9))
    Undo-WinterBreak2 $rollbackDrift.Kindle
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $rollbackDrift.Kindle "jb.sh")).Hash.ToLowerInvariant() -eq $rollbackDrift.OriginalJbHash) "Rollback drift gates prevented original jb.sh restoration."
    Assert-True (Test-Path -LiteralPath $driftUpdate) "Dedicated rollback deleted an unrelated OTA file."
    Assert-True ((Get-Content -LiteralPath $storeDriftFile -Raw) -match "post-stage-store-drift") "Dedicated rollback overwrote Store drift."

    # Any execution log, even incomplete, closes the rollback boundary.
    $partial = New-MockCase "partial-log"
    Stage-WinterBreak2 $partial.Kindle
    Set-Content -LiteralPath (Join-Path $partial.Kindle "winterbreak.log") -Value "browser transport started" -Encoding ASCII
    Assert-Throws { Undo-WinterBreak2 $partial.Kindle } "execution may already have started" "A partial execution log did not block rollback."

    # A generic marker is never accepted as WB2 success.
    $markerOnly = New-MockCase "marker-only"
    Stage-WinterBreak2 $markerOnly.Kindle
    Set-Content -LiteralPath (Join-Path $markerOnly.Kindle "documents\JAILBROKEN.txt") -Value "unrelated marker" -Encoding ASCII
    Assert-Throws { Verify-WinterBreak2 $markerOnly.Kindle } "winterbreak\.log is absent" "JAILBROKEN.txt was incorrectly accepted as WB2 success."
    Assert-True ((Get-ActiveWb2Record).manifest.status -eq "complete") "Marker-only verification consumed the WB2 record."

    # Explicit failure text blocks completion even when all five success lines
    # are present.
    $failedLog = New-MockCase "failed-log"
    Stage-WinterBreak2 $failedLog.Kindle
    Write-SuccessLog $failedLog "ERR - mock developer-key failure"
    Assert-Throws { Verify-WinterBreak2 $failedLog.Kindle } "explicit failure evidence" "A WB2 log containing ERR - was accepted."
    Assert-True ((Get-ActiveWb2Record).manifest.status -eq "complete") "Failed-log verification consumed the WB2 record."

    # Once the root script has produced complete success evidence, USB drift
    # must not prevent recording that irreversible fact.
    $executionDrift = New-MockCase "execution-drift"
    Stage-WinterBreak2 $executionDrift.Kindle
    Write-SuccessLog $executionDrift
    Remove-Item -LiteralPath (Join-Path $executionDrift.Kindle ".kindle-ota-space-filler") -Recurse -Force
    Remove-Item -LiteralPath (Join-Path $executionDrift.Kindle "patchedUks.sqsh") -Force
    [IO.File]::WriteAllBytes((Join-Path $executionDrift.Kindle "update.bin.tmp.partial"), [byte[]](7, 7, 7))
    $script:mockFreeBytes = [int64](160MB)
    Verify-WinterBreak2 $executionDrift.Kindle
    Assert-True ((Get-WinterBreak2Record "executed" -Require).manifest.status -eq "executed") "Post-execution drift prevented WB2 execution bookkeeping."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $executionDrift.Project "logs\latest-winterbreak2-stage.txt"))) "Post-execution drift left the rollback pointer active."

    # Verified stock execution retires only the rollback pointer. Hotfix
    # staging requires that executed audit, refuses other updates, is
    # idempotent, and leaves the filler and Store stage intact.
    $success = New-MockCase "success-hotfix"
    $successStoreBefore = Get-SelectedTreeSignature $success.Kindle $success.StoreRoots
    $successCache = New-MockStoreCacheRecord $success
    Stage-WinterBreak2 $success.Kindle
    Assert-Throws { Stage-UniversalHotfix $success.Kindle } "executed record" "Hotfix staged before VerifyWinterBreak2."
    Write-SuccessLog $success
    Verify-WinterBreak2 $success.Kindle
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $success.Kindle "documents\JAILBROKEN.txt"))) "The test unexpectedly depended on JAILBROKEN.txt."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $success.Project "logs\latest-winterbreak2-stage.txt"))) "WB2 verification left its rollback pointer."
    Assert-True (Test-Path -LiteralPath (Join-Path $success.Project "logs\latest-winterbreak2-executed.txt")) "WB2 verification did not publish its executed audit pointer."
    $executed = Get-WinterBreak2Record "executed" -Require
    Assert-True ($executed.manifest.status -eq "executed") "WB2 verification did not persist executed status."
    $supersededStore = Get-Content -LiteralPath $success.StoreManifestPath -Raw | ConvertFrom-Json
    Assert-True ($supersededStore.status -eq "superseded-by-winterbreak2") "WB2 verification did not supersede the Store-stage record truthfully."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $success.Project "logs\latest-winterbreak-stage.txt"))) "WB2 verification left the Store-stage pointer active."
    Assert-True ((Get-Content -LiteralPath $successCache.ManifestPath -Raw | ConvertFrom-Json).status -eq "superseded-by-winterbreak2") "WB2 verification did not supersede the active Store-cache record."
    Assert-True (-not (Test-Path -LiteralPath $successCache.PointerPath)) "WB2 verification left the Store-cache pointer active."
    Assert-Throws { Remove-OtaFiller $success.Kindle } "closed Store route" "RemoveFiller was allowed before hotfix persistence evidence."
    Verify-WinterBreak2 $success.Kindle

    $partialUpdate = Join-Path $success.Kindle "update.bin.tmp.partial"
    [IO.File]::WriteAllBytes($partialUpdate, [byte[]](5, 4, 3, 2, 1))
    Assert-Throws { Stage-UniversalHotfix $success.Kindle } "update package|blocks Universal" "Another root update did not block hotfix staging."
    Assert-True (Test-Path -LiteralPath $partialUpdate) "Hotfix guard deleted another update file."
    Remove-Item -LiteralPath $partialUpdate -Force
    Stage-UniversalHotfix $success.Kindle
    $hotfixDestination = Join-Path $success.Kindle "Update_hotfix_universal.bin"
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $hotfixDestination).Hash.ToLowerInvariant() -eq $UniversalHotfix.Sha256) "Hotfix destination hash is wrong."
    Assert-True (Test-Path -LiteralPath (Join-Path $success.Kindle ".kindle-ota-space-filler")) "Hotfix staging removed the OTA filler."
    Assert-True ((Get-SelectedTreeSignature $success.Kindle $success.StoreRoots) -eq $successStoreBefore) "Hotfix staging changed the Store WinterBreak tree."
    Stage-UniversalHotfix $success.Kindle
    Verify-WinterBreak2 $success.Kindle

    # Root OTA files and firmware drift stop staging before any WB2 mutation;
    # ForceFirmwareOverride intentionally does not bypass this fallback gate.
    $ota = New-MockCase "ota-block"
    $otaOriginalJb = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $ota.Kindle "jb.sh")).Hash
    [IO.File]::WriteAllBytes((Join-Path $ota.Kindle "UPDATE-other.bin"), [byte[]](8, 8, 8))
    Assert-Throws { Stage-WinterBreak2 $ota.Kindle } "update package" "A root OTA package did not block WB2 staging."
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $ota.Kindle "jb.sh")).Hash -eq $otaOriginalJb) "OTA-blocked staging changed jb.sh."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $ota.Project "logs\latest-winterbreak2-stage.txt"))) "OTA-blocked staging created a rollback pointer."

    $firmware = New-MockCase "firmware-block"
    $script:mockFirmware = "5.16.0"
    $ForceFirmwareOverride = $true
    Assert-Throws { Stage-WinterBreak2 $firmware.Kindle } "pinned to firmware 5\.15\.1" "Firmware override bypassed the exact WB2 gate."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $firmware.Project "logs\latest-winterbreak2-stage.txt"))) "Firmware-blocked staging created a rollback pointer."
    $ForceFirmwareOverride = $false

    $space = New-MockCase "space-block"
    $script:mockFreeBytes = [int64](91MB)
    Assert-Throws { Stage-WinterBreak2 $space.Kindle } "requires 50-90 MiB" "The WB2-specific 90 MiB ceiling was not enforced."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $space.Project "logs\latest-winterbreak2-stage.txt"))) "Space-blocked staging created a rollback pointer."

    $reservation = New-MockCase "payload-reservation"
    $script:mockFreeBytes = [int64](50MB)
    Assert-Throws { Stage-WinterBreak2 $reservation.Kindle } "exact WinterBreak2 payload would cross" "WB2 staging did not reserve its exact payload above the 50 MiB floor."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $reservation.Project "logs\latest-winterbreak2-stage.txt"))) "Payload-reservation refusal created a rollback pointer."

    $truncated = New-MockCase "truncated-store-manifest"
    $truncatedManifest = Get-Content -LiteralPath $truncated.StoreManifestPath -Raw | ConvertFrom-Json
    $truncatedManifest.files = @($truncatedManifest.files | Select-Object -First 16)
    $truncatedManifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $truncated.StoreManifestPath -Encoding UTF8
    Assert-Throws { Stage-WinterBreak2 $truncated.Kindle } "exactly 17 files" "A truncated Store-stage manifest was accepted."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $truncated.Project "logs\latest-winterbreak2-stage.txt"))) "Truncated-manifest staging created a rollback pointer."

    $implementationText = Get-Content -LiteralPath $implementation -Raw
    Assert-True ($implementationText -match '"VerifyJailbreak"\s*\{\s*Assert-StoreRouteOpen') "VerifyJailbreak dispatch is missing its WB2 method-isolation guard."

    Write-Host "PASS stock WinterBreak2 exact stage/resume/rollback, divergence preservation, log-only verification, OTA/firmware gates, and guarded Hotfix 2.5.0 staging"
} finally {
    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd("\") + "\"
    $resolvedTest = [IO.Path]::GetFullPath($testRoot)
    if ($resolvedTest.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path $resolvedTest -Leaf) -like "kindle-pw5se-wb2-test-*") {
        Remove-Item -LiteralPath $resolvedTest -Recurse -Force -ErrorAction SilentlyContinue
    }
}
