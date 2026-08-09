[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$implementation = Join-Path $repoRoot "scripts\pw5se-winterbreak.ps1"

# Load function definitions only. This deliberately skips the script's
# top-level removable-drive resolution and action dispatch.
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
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("kindle-pw5se-store-sandbox-test-" + [Guid]::NewGuid().ToString("N"))
$script:mockProjectRoot = $null
$script:activeMockRoot = $null

function Get-ProjectRoot {
    return $script:mockProjectRoot
}

function Get-FreeBytes {
    param([Parameter(Mandatory = $true)][string] $Root)
    return [int64](80MB)
}

function Get-KindleInfo {
    param([Parameter(Mandatory = $true)][string] $Root)
    return [ordered]@{
        firmware = "5.15.1"
        jailbrokenMarker = Test-Path -LiteralPath (Join-Path $Root "documents\JAILBROKEN.txt")
        winterBreakStaged = (
            (Test-Path -LiteralPath (Join-Path $Root ".active_content_sandbox")) -and
            (Test-Path -LiteralPath (Join-Path $Root "apps\tech.hackerdude.winterbreak")) -and
            (Test-Path -LiteralPath (Join-Path $Root "mesquito"))
        )
        otaFiller = Test-Path -LiteralPath (Join-Path $Root ".kindle-ota-space-filler")
    }
}

function Get-RecordedManifest {
    param([switch] $Require)
    if (-not $script:activeMockRoot) {
        if ($Require) { throw "No active mock Kindle." }
        return $null
    }
    return [ordered]@{
        manifestPath = Join-Path $script:mockProjectRoot "mock-stage-manifest.json"
        manifest = [pscustomobject]@{
            status = "complete"
            deviceFingerprint = Get-KindleFingerprint $script:activeMockRoot
        }
    }
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

function New-MockCase {
    param([Parameter(Mandatory = $true)][string] $Name)

    $caseRoot = Join-Path $testRoot $Name
    $project = Join-Path $caseRoot "project"
    $kindle = Join-Path $caseRoot "kindle"
    $sandbox = Join-Path $kindle $StoreSandboxRelativePath
    foreach ($directory in @(
            $project,
            (Join-Path $kindle "documents"),
            (Join-Path $kindle "system"),
            (Join-Path $kindle "apps\tech.hackerdude.winterbreak"),
            (Join-Path $kindle "mesquito"),
            (Join-Path $sandbox "store\resource\LocalStorage"),
            (Join-Path $sandbox "store\resource\empty-directory"),
            (Join-Path $kindle ".kindle-ota-space-filler")
        )) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    Set-Content -LiteralPath (Join-Path $kindle "system\version.txt") -Value "Kindle 5.15.1 mock" -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $sandbox "store\resource\LocalStorage\store.db") -Value "original-store-data-$Name" -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $sandbox "root-state.json") -Value '{"mock":true}' -Encoding ASCII
    $filler = Join-Path $kindle ".kindle-ota-space-filler"
    [IO.File]::WriteAllText((Join-Path $filler ".lazying-art-filler-owner-v1"), "$FillerOwnerText`n", [Text.Encoding]::ASCII)
    [IO.File]::WriteAllBytes((Join-Path $filler "filler-000.bin"), [byte[]](0, 1, 2, 3))

    $script:mockProjectRoot = $project
    $script:activeMockRoot = $kindle
    return [pscustomobject]@{
        Name = $Name
        Project = $project
        Kindle = $kindle
        Sandbox = $sandbox
    }
}

function Get-ActiveSandboxRecord {
    return Get-StoreSandboxRecord -Require
}

function Set-SandboxRecordStatus {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Status
    )
    $manifest = Get-Content -LiteralPath $Record.manifestPath -Raw | ConvertFrom-Json
    $manifest.status = $Status
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Record.manifestPath -Encoding UTF8
}

function New-MockCacheRecord {
    param(
        [Parameter(Mandatory = $true)] $Context,
        [string] $Status = "complete"
    )
    $recordRoot = Join-Path $Context.Project ("device-backups\winterbreak-store-cache-mock-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $recordRoot -Force | Out-Null
    $manifestPath = Join-Path $recordRoot "manifest.json"
    [ordered]@{
        createdAt = (Get-Date).ToString("o")
        status = $Status
        firmware = "5.15.1"
        deviceFingerprint = Get-KindleFingerprint $Context.Kindle
        cacheRelativePath = ".active_content_sandbox\store\resource\LocalStorage"
        files = @()
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $latest = Join-Path $Context.Project "logs\latest-winterbreak-store-cache.txt"
    New-Item -ItemType Directory -Path (Split-Path $latest -Parent) -Force | Out-Null
    Set-Content -LiteralPath $latest -Value $manifestPath -Encoding UTF8
    return [pscustomobject]@{ latestPath = $latest; manifestPath = $manifestPath }
}

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

    # Happy removal and restore preserves the complete tree and retires only
    # the full-sandbox pointer.
    $happy = New-MockCase "happy-restore"
    $expectedHappy = Get-DirectoryManifestInventory $happy.Sandbox "expected happy sandbox"
    Begin-WinterBreakStoreRegeneration $happy.Kindle
    $happyRecord = Get-ActiveSandboxRecord
    Assert-True (-not (Test-Path -LiteralPath $happy.Sandbox)) "Begin did not remove the happy-path sandbox."
    Restore-WinterBreakStoreSandbox $happy.Kindle
    Assert-DirectoryMatchesManifest $happy.Sandbox $expectedHappy.files $expectedHappy.directories "happy restored sandbox"
    Assert-True (-not (Test-Path -LiteralPath $happyRecord.latestPath)) "Happy restore left its active pointer."
    $happyManifest = Get-Content -LiteralPath $happyRecord.manifestPath -Raw | ConvertFrom-Json
    Assert-True ($happyManifest.status -eq "restored") "Happy restore did not persist restored status."

    # Corruption must be detected before any destination file is created.
    $corrupt = New-MockCase "corrupt-backup"
    Begin-WinterBreakStoreRegeneration $corrupt.Kindle
    $corruptRecord = Get-ActiveSandboxRecord
    $corruptManifest = $corruptRecord.manifest
    $corruptBackup = Join-Path (Split-Path $corruptRecord.manifestPath -Parent) ".active_content_sandbox"
    Set-Content -LiteralPath (Join-Path $corruptBackup $corruptManifest.files[0].relativePath) -Value "corrupt" -Encoding ASCII
    Assert-Throws { Restore-WinterBreakStoreSandbox $corrupt.Kindle } "SHA-256" "Corrupt backup restore was not rejected."
    Assert-True (-not (Test-Path -LiteralPath $corrupt.Sandbox)) "Corrupt backup wrote destination data before rejection."

    # Extra backup content is outside the manifest and must be rejected before
    # destination mutation.
    $extra = New-MockCase "extra-backup-file"
    Begin-WinterBreakStoreRegeneration $extra.Kindle
    $extraRecord = Get-ActiveSandboxRecord
    $extraBackup = Join-Path (Split-Path $extraRecord.manifestPath -Parent) ".active_content_sandbox"
    Set-Content -LiteralPath (Join-Path $extraBackup "unmanifested.bin") -Value "extra" -Encoding ASCII
    Assert-Throws { Restore-WinterBreakStoreSandbox $extra.Kindle } "file set|unmanifested" "Extra backup file was not rejected."
    Assert-True (-not (Test-Path -LiteralPath $extra.Sandbox)) "Extra backup file caused destination mutation."

    # The destination path is a fixed constant, never a mutable manifest field.
    $tampered = New-MockCase "tampered-path"
    Begin-WinterBreakStoreRegeneration $tampered.Kindle
    $tamperedRecord = Get-ActiveSandboxRecord
    $tamperedManifest = Get-Content -LiteralPath $tamperedRecord.manifestPath -Raw | ConvertFrom-Json
    $tamperedManifest.sandboxRelativePath = "documents\unexpected-child"
    $tamperedManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tamperedRecord.manifestPath -Encoding UTF8
    Assert-Throws { Restore-WinterBreakStoreSandbox $tampered.Kindle } "not exactly" "Tampered sandboxRelativePath was accepted."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $tampered.Kindle "documents\unexpected-child"))) "Tampered path wrote outside the fixed sandbox."

    # A crash before the removed-status write is recoverable when the source is
    # absent or still exactly equal to the backup.
    $preparedAbsent = New-MockCase "prepared-absent"
    Begin-WinterBreakStoreRegeneration $preparedAbsent.Kindle
    $preparedAbsentRecord = Get-ActiveSandboxRecord
    Set-SandboxRecordStatus $preparedAbsentRecord "prepared"
    Begin-WinterBreakStoreRegeneration $preparedAbsent.Kindle
    $preparedAbsentManifest = Get-Content -LiteralPath $preparedAbsentRecord.manifestPath -Raw | ConvertFrom-Json
    Assert-True ($preparedAbsentManifest.status -eq "removed") "Prepared/absent recovery did not commit removed status."

    $preparedSame = New-MockCase "prepared-same"
    Begin-WinterBreakStoreRegeneration $preparedSame.Kindle
    $preparedSameRecord = Get-ActiveSandboxRecord
    Set-SandboxRecordStatus $preparedSameRecord "prepared"
    $preparedSameBackup = Join-Path (Split-Path $preparedSameRecord.manifestPath -Parent) ".active_content_sandbox"
    Copy-DirectoryContents $preparedSameBackup $preparedSame.Sandbox
    Begin-WinterBreakStoreRegeneration $preparedSame.Kindle
    Assert-True (-not (Test-Path -LiteralPath $preparedSame.Sandbox)) "Prepared/equal source was not safely removed."

    # A changed/regenerated source must remain untouched, and an older cache
    # pointer must not be superseded before the removal commit.
    $preparedDifferent = New-MockCase "prepared-different"
    Begin-WinterBreakStoreRegeneration $preparedDifferent.Kindle
    $preparedDifferentRecord = Get-ActiveSandboxRecord
    Set-SandboxRecordStatus $preparedDifferentRecord "prepared"
    New-Item -ItemType Directory -Path $preparedDifferent.Sandbox -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $preparedDifferent.Sandbox "new-store-data.bin") -Value "regenerated" -Encoding ASCII
    $oldCache = New-MockCacheRecord $preparedDifferent "complete"
    Assert-Throws { Begin-WinterBreakStoreRegeneration $preparedDifferent.Kindle } "differs from the prepared backup" "Prepared/different source was not rejected."
    Assert-True (Test-Path -LiteralPath (Join-Path $preparedDifferent.Sandbox "new-store-data.bin")) "Prepared/different source was mutated."
    Assert-True (Test-Path -LiteralPath $oldCache.latestPath) "Old cache pointer was superseded before removal commit."
    $oldCacheManifest = Get-Content -LiteralPath $oldCache.manifestPath -Raw | ConvertFrom-Json
    Assert-True ($oldCacheManifest.status -eq "complete") "Old cache status changed before removal commit."

    # Begin requires the exact ownership marker and an allowlisted filler tree.
    $badFiller = New-MockCase "bad-filler"
    Set-Content -LiteralPath (Join-Path $badFiller.Kindle ".kindle-ota-space-filler\unexpected.txt") -Value "no" -Encoding ASCII
    Assert-Throws { Begin-WinterBreakStoreRegeneration $badFiller.Kindle } "unexpected entries" "Unexpected filler entry was accepted."
    Assert-True (Test-Path -LiteralPath $badFiller.Sandbox) "Invalid filler caused Store mutation."

    # Completion permits only valid transitions and cleans a stale pointer when
    # the target status was already committed.
    $strict = New-MockCase "strict-completion"
    Begin-WinterBreakStoreRegeneration $strict.Kindle
    $strictRecord = Get-ActiveSandboxRecord
    Set-SandboxRecordStatus $strictRecord "prepared"
    Assert-Throws { Complete-StoreSandboxRecord $strict.Kindle "regenerated" } "Invalid Store-sandbox transition" "Invalid prepared -> regenerated transition succeeded."
    Assert-True (Test-Path -LiteralPath $strictRecord.latestPath) "Invalid transition consumed its pointer."
    Set-SandboxRecordStatus $strictRecord "regenerated"
    Complete-StoreSandboxRecord $strict.Kindle "regenerated"
    Assert-True (-not (Test-Path -LiteralPath $strictRecord.latestPath)) "Idempotent completion did not retire a stale pointer."

    $valid = New-MockCase "valid-completion"
    Begin-WinterBreakStoreRegeneration $valid.Kindle
    $validRecord = Get-ActiveSandboxRecord
    Complete-StoreSandboxRecord $valid.Kindle "regenerated"
    $validManifest = Get-Content -LiteralPath $validRecord.manifestPath -Raw | ConvertFrom-Json
    Assert-True ($validManifest.status -eq "regenerated") "Valid removed -> regenerated transition failed."
    Assert-True (-not (Test-Path -LiteralPath $validRecord.latestPath)) "Valid completion left its pointer."

    # A previously completed cache record can finalize a still-active removed
    # sandbox record without repeating cache mutation.
    $cacheResume = New-MockCase "complete-cache-resume"
    Begin-WinterBreakStoreRegeneration $cacheResume.Kindle
    $cacheResumeRecord = Get-ActiveSandboxRecord
    Set-SandboxRecordStatus $cacheResumeRecord "prepared"
    New-Item -ItemType Directory -Path $cacheResume.Sandbox -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $cacheResume.Sandbox "winterbreak-payload.bin") -Value "restaged" -Encoding ASCII
    $cacheResumePointer = New-MockCacheRecord $cacheResume "complete"
    Reset-WinterBreakStoreCache $cacheResume.Kindle
    $cacheResumeManifest = Get-Content -LiteralPath $cacheResumeRecord.manifestPath -Raw | ConvertFrom-Json
    Assert-True ($cacheResumeManifest.status -eq "regenerated") "Complete-cache recovery did not finalize the sandbox record."
    Assert-True (-not (Test-Path -LiteralPath $cacheResumeRecord.latestPath)) "Complete-cache recovery left the sandbox pointer."
    Assert-True (Test-Path -LiteralPath $cacheResumePointer.latestPath) "Complete-cache recovery incorrectly consumed the cache pointer."

    # Root-level OTA packages stop cache reset without automatic deletion.
    $ota = New-MockCase "ota-guard"
    $otaFile = Join-Path $ota.Kindle "UPDATE-test.BIN"
    [IO.File]::WriteAllBytes($otaFile, [byte[]](9, 8, 7))
    $cacheFile = Join-Path $ota.Sandbox "store\resource\LocalStorage\store.db"
    $cacheHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $cacheFile).Hash
    Assert-Throws { Reset-WinterBreakStoreCache $ota.Kindle } "UPDATE-test\.BIN" "Root-level OTA package did not block cache reset."
    Assert-True (Test-Path -LiteralPath $otaFile) "OTA guard deleted the update package automatically."
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $cacheFile).Hash -eq $cacheHash) "OTA guard mutated LocalStorage."

    Write-Host "PASS Store-sandbox exact backup/restore, crash recovery, strict transitions, filler guard, cache completion, and OTA refusal"
} finally {
    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd("\") + "\"
    $resolvedTest = [IO.Path]::GetFullPath($testRoot)
    if ($resolvedTest.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path $resolvedTest -Leaf) -like "kindle-pw5se-store-sandbox-test-*") {
        Remove-Item -LiteralPath $resolvedTest -Recurse -Force -ErrorAction SilentlyContinue
    }
}
