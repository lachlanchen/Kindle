[CmdletBinding()]
param(
    [ValidateSet(
        "Diagnose",
        "Download",
        "Backup",
        "Stage",
        "UndoStage",
        "FillSpace",
        "RemoveFiller",
        "ResetStoreCache",
        "RestoreStoreCache",
        "BeginStoreRegeneration",
        "RestoreStoreSandbox",
        "Prepare",
        "VerifyJailbreak",
        "BindDeviceIdentity",
        "StageWinterBreak2",
        "VerifyWinterBreak2",
        "UndoWinterBreak2",
        "StageHotfix",
        "StageHotfixProbe",
        "StageHotfixDiagnostic",
        "ReadHotfixDiagnostic",
        "AcceptHotfixPersistentState",
        "VerifyHotfix",
        "StageKOReader",
        "VerifyKOReaderStage",
        "Eject"
    )]
    [string] $Action = "Diagnose",
    [string] $KindleRoot,
    [ValidateRange(50, 90)]
    [int] $LeaveMiB = 80,
    [switch] $ConfirmedAirplaneMode,
    [switch] $ForceFirmwareOverride
)

$ErrorActionPreference = "Stop"
$ExpectedFirmware = "5.15.1"
$FillerOwnerText = "lazying-art Kindle PW5SE WinterBreak filler v1"
$StoreSandboxRelativePath = ".active_content_sandbox"

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

$WinterBreak2Files = @(
    "jb.sh",
    "patchedUks.sqsh",
    "winterbreak2\dialoger.html"
)
$WinterBreak2Directories = @("winterbreak2")
$WinterBreak2SuccessEvidence = @(
    "Developer keys installed successfully (Standard Method)! (pubdevkey01.pem)",
    "Enabled developer flag",
    "Enabled mntus exec flag",
    "*** Finished installing jailbreak! ***",
    "***   Please Install HOTFIX now    ***"
)
$WinterBreak2FailureEvidence = @("ERR -", " FAIL", "ERROR:")

$KOReader = [ordered]@{
    Version = "2026.07.1"
    Url = "https://github.com/koreader/koreader/releases/download/v2026.07.1/koreader-kindlepw2-v2026.07.1.zip"
    File = "koreader-kindlepw2-v2026.07.1.zip"
    Sha256 = "ea1f575c54492a2c679d128b7f3210fd7d6a87e5f5a1ff1f7a7fe2080ff68f86"
    LauncherRelativePath = "assets\koreader-lazy\KOReader.sh"
    LauncherDeviceRelativePath = "documents\KOReader.sh"
    LauncherSha256 = "619e707a1dee8c36c1107af195a41c2c3f7f0d9b622b4e4cb5fbfcdae9c64e25"
}

function Get-ProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-FullProjectPath {
    param([Parameter(Mandatory = $true)][string] $RelativePath)
    return [IO.Path]::GetFullPath((Join-Path (Get-ProjectRoot) $RelativePath))
}

function Write-ProjectTextAtomic {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string] $Content
    )

    $projectPrefix = [IO.Path]::GetFullPath((Get-ProjectRoot)).TrimEnd("\") + "\"
    $destination = [IO.Path]::GetFullPath($Path)
    if (-not $destination.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing an atomic state write outside the project."
    }
    $parent = Split-Path $destination -Parent
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = Join-Path $parent (".{0}.{1}.tmp" -f (Split-Path $destination -Leaf), [Guid]::NewGuid().ToString("N"))
    $encoding = New-Object Text.UTF8Encoding($false)
    $bytes = $encoding.GetBytes($Content)
    $stream = [IO.File]::Open(
        $temporary,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
    try {
        if (-not [StringComparer]::Ordinal.Equals(
                [IO.File]::ReadAllText($temporary, $encoding),
                $Content
            )) {
            throw "Atomic state-file verification failed before publication."
        }
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            $replaceBackup = Join-Path $parent (".{0}.{1}.replace-backup" -f (Split-Path $destination -Leaf), [Guid]::NewGuid().ToString("N"))
            [IO.File]::Replace($temporary, $destination, $replaceBackup)
        } elseif (Test-Path -LiteralPath $destination) {
            throw "A non-file blocks the atomic state destination."
        } else {
            [IO.File]::Move($temporary, $destination)
        }
        if (-not [StringComparer]::Ordinal.Equals(
                [IO.File]::ReadAllText($destination, $encoding),
                $Content
            )) {
            throw "Atomic state-file verification failed after publication."
        }
        if ($replaceBackup -and (Test-Path -LiteralPath $replaceBackup -PathType Leaf)) {
            Remove-Item -LiteralPath $replaceBackup -Force
        }
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Write-ProjectJsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)] $Value
    )

    Write-ProjectTextAtomic $Path ($Value | ConvertTo-Json -Depth 10)
}

function Reset-ProjectDirectory {
    param([Parameter(Mandatory = $true)][string] $RelativePath)

    $project = [IO.Path]::GetFullPath((Get-ProjectRoot)).TrimEnd("\") + "\"
    $target = Get-FullProjectPath $RelativePath
    if (-not $target.StartsWith($project, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to reset a path outside the project: $target"
    }

    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    return $target
}

function Resolve-KindleRoot {
    param([string] $Requested)

    if ($Requested) {
        if (-not (Test-Path -LiteralPath $Requested)) {
            throw "Kindle root does not exist: $Requested"
        }
        $candidate = (Resolve-Path -LiteralPath $Requested).Path.TrimEnd("\") + "\"
    } else {
        $matches = @(
            Get-CimInstance Win32_LogicalDisk |
                Where-Object {
                    $_.DriveType -eq 2 -and
                    (Test-Path -LiteralPath (Join-Path $_.DeviceID "documents")) -and
                    (Test-Path -LiteralPath (Join-Path $_.DeviceID "system\version.txt"))
                }
        )
        if ($matches.Count -eq 0) {
            throw "No mounted Kindle USB storage was found."
        }
        if ($matches.Count -gt 1) {
            $names = ($matches | ForEach-Object { "$($_.DeviceID) ($($_.VolumeName))" }) -join ", "
            throw "Multiple Kindle-like volumes were found: $names. Pass -KindleRoot explicitly."
        }
        $candidate = "$($matches[0].DeviceID)\"
    }

    if ($candidate -notmatch "^[A-Za-z]:\\$") {
        throw "Refusing unsafe Kindle root: $candidate"
    }
    $drive = Get-CimInstance Win32_LogicalDisk |
        Where-Object { "$($_.DeviceID)\" -ieq $candidate } |
        Select-Object -First 1
    if (-not $drive -or $drive.DriveType -ne 2) {
        throw "Refusing non-removable drive $candidate. Kindle mutation is allowed only on a Windows removable volume."
    }
    $systemRoot = [IO.Path]::GetPathRoot($env:SystemRoot).TrimEnd("\") + "\"
    if ($candidate -ieq $systemRoot) {
        throw "Refusing the Windows system drive: $candidate"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $candidate "documents")) -or
        -not (Test-Path -LiteralPath (Join-Path $candidate "system\version.txt"))) {
        throw "$candidate does not have the expected Kindle structure."
    }
    return $candidate
}

function Get-SafeChildPath {
    param(
        [Parameter(Mandatory = $true)][string] $Parent,
        [Parameter(Mandatory = $true)][string] $RelativePath,
        [string] $Purpose = "child path"
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or [IO.Path]::IsPathRooted($RelativePath)) {
        throw "Refusing unsafe ${Purpose}: $RelativePath"
    }
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd("\") + "\"
    $target = [IO.Path]::GetFullPath((Join-Path $parentFull $RelativePath))
    if (-not $target.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing $Purpose outside ${parentFull}: $RelativePath"
    }
    return $target
}

function Get-DirectoryManifestInventory {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [string] $Purpose = "directory"
    )

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "The $Purpose is missing: $Root"
    }
    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path.TrimEnd("\")
    $prefix = $resolvedRoot + "\"
    $files = @()
    foreach ($file in Get-ChildItem -LiteralPath $resolvedRoot -File -Recurse -Force) {
        $files += [ordered]@{
            relativePath = $file.FullName.Substring($prefix.Length)
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
        }
    }
    $directories = @(
        Get-ChildItem -LiteralPath $resolvedRoot -Directory -Recurse -Force |
            ForEach-Object { $_.FullName.Substring($prefix.Length) }
    )
    return [ordered]@{
        files = @($files)
        directories = @($directories)
    }
}

function Get-ValidatedManifestRelativePath {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [AllowEmptyString()][string] $RelativePath,
        [Parameter(Mandatory = $true)][string] $Purpose
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or [IO.Path]::IsPathRooted($RelativePath)) {
        throw "The $Purpose contains an unsafe relative path: '$RelativePath'"
    }
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd("\") + "\"
    $candidate = Get-SafeChildPath $rootFull $RelativePath $Purpose
    $canonical = $candidate.Substring($rootFull.Length)
    if (-not [StringComparer]::Ordinal.Equals($canonical, $RelativePath)) {
        throw "The $Purpose contains a non-canonical relative path: '$RelativePath'"
    }
    return $canonical
}

function Assert-DirectoryMatchesManifest {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [AllowNull()] $Files,
        [AllowNull()] $Directories,
        [Parameter(Mandatory = $true)][string] $Purpose
    )

    $inventory = Get-DirectoryManifestInventory $Root $Purpose
    $expectedFiles = @{}
    foreach ($entry in @($Files)) {
        $relative = Get-ValidatedManifestRelativePath $Root ([string]$entry.relativePath) "$Purpose file manifest"
        if ($expectedFiles.ContainsKey($relative)) {
            throw "The $Purpose manifest contains a duplicate file path: $relative"
        }
        $hash = [string]$entry.sha256
        if ($hash -notmatch "^[0-9a-fA-F]{64}$") {
            throw "The $Purpose manifest contains an invalid SHA-256 for: $relative"
        }
        $expectedFiles[$relative] = $hash.ToLowerInvariant()
    }
    if ($inventory.files.Count -ne $expectedFiles.Count) {
        throw "The $Purpose file set differs from its manifest. Expected $($expectedFiles.Count), found $($inventory.files.Count)."
    }
    foreach ($entry in $inventory.files) {
        if (-not $expectedFiles.ContainsKey($entry.relativePath)) {
            throw "The $Purpose contains an unmanifested file: $($entry.relativePath)"
        }
        if ($expectedFiles[$entry.relativePath] -ne $entry.sha256) {
            throw "The $Purpose SHA-256 differs from its manifest: $($entry.relativePath)"
        }
    }

    $expectedDirectories = @{}
    foreach ($entry in @($Directories)) {
        $relative = Get-ValidatedManifestRelativePath $Root ([string]$entry) "$Purpose directory manifest"
        if ($expectedDirectories.ContainsKey($relative)) {
            throw "The $Purpose manifest contains a duplicate directory path: $relative"
        }
        $expectedDirectories[$relative] = $true
    }
    if ($inventory.directories.Count -ne $expectedDirectories.Count) {
        throw "The $Purpose directory set differs from its manifest. Expected $($expectedDirectories.Count), found $($inventory.directories.Count)."
    }
    foreach ($relative in $inventory.directories) {
        if (-not $expectedDirectories.ContainsKey($relative)) {
            throw "The $Purpose contains an unmanifested directory: $relative"
        }
    }
}

function Get-KindleFingerprint {
    param([Parameter(Mandatory = $true)][string] $Root)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Root "system\version.txt")).Hash.ToLowerInvariant()
}

function Get-KindleIdentityHash {
    param([Parameter(Mandatory = $true)][string] $Root)

    $normalizedRoot = [IO.Path]::GetFullPath($Root).TrimEnd("\") + "\"
    if ($normalizedRoot -notmatch "^[A-Za-z]:\\$") {
        throw "A drive-root path is required to derive the Kindle volume identity."
    }
    $drive = Get-CimInstance Win32_LogicalDisk |
        Where-Object { "$($_.DeviceID)\" -ieq $normalizedRoot } |
        Select-Object -First 1
    $volumeSerial = ([string]$drive.VolumeSerialNumber).Trim().ToUpperInvariant()
    $size = [int64]$drive.Size
    if (-not $drive -or [string]::IsNullOrWhiteSpace($volumeSerial) -or $size -le 0) {
        throw "Windows did not expose a stable volume identity for the connected Kindle."
    }

    # The raw Windows volume identifier is never persisted or printed. Only a
    # domain-separated digest of the stable serial/size tuple leaves this
    # function; the mount letter is intentionally not part of the identity.
    $material = "lazying-art/kindle-volume-identity/v1`n$volumeSerial`n$size"
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($material))
    } finally {
        $sha.Dispose()
    }
    return ([BitConverter]::ToString($digest) -replace "-", "").ToLowerInvariant()
}

function Get-RecordedManifest {
    param([switch] $Require)

    $latest = Get-FullProjectPath "logs\latest-winterbreak-stage.txt"
    if (-not (Test-Path -LiteralPath $latest)) {
        if ($Require) { throw "No local WinterBreak staging record was found." }
        return $null
    }
    $manifestPath = (Get-Content -LiteralPath $latest -Raw).Trim()
    $backupRoot = (Get-FullProjectPath "device-backups").TrimEnd("\") + "\"
    $manifestFull = [IO.Path]::GetFullPath($manifestPath)
    if (-not $manifestFull.StartsWith($backupRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a staging manifest outside the ignored device-backups tree: $manifestFull"
    }
    if (-not (Test-Path -LiteralPath $manifestFull -PathType Leaf)) {
        throw "The active staging manifest is missing: $manifestFull"
    }
    return [ordered]@{
        latestPath = $latest
        manifestPath = $manifestFull
        manifest = Get-Content -LiteralPath $manifestFull -Raw | ConvertFrom-Json
    }
}

function Assert-NoActiveStageRecord {
    $record = Get-RecordedManifest
    if (-not $record) { return }
    if ($record.manifest.status -in @("prepared", "complete", "rollback-incomplete")) {
        throw "An active WinterBreak staging record already exists. Reconnect the same Kindle and run UndoStage before staging again: $($record.manifestPath)"
    }
}

function Complete-StageRecordAfterJailbreak {
    param([Parameter(Mandatory = $true)][string] $Root)

    $record = Get-RecordedManifest
    if (-not $record) { return }
    if ($record.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The connected Kindle does not match the active staging manifest. The record was not consumed."
    }
    $record.manifest.status = "executed"
    $record.manifest | Add-Member -NotePropertyName jailbreakVerifiedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    $record.manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $record.manifestPath -Encoding UTF8
    Remove-Item -LiteralPath $record.latestPath -Force
    Write-Host "Marked the staging record executed and preserved its manifest for audit."
}

function Get-WinterBreak2Record {
    param(
        [ValidateSet("active", "executed")]
        [string] $Kind = "active",
        [switch] $Require
    )

    $pointerName = if ($Kind -eq "active") {
        "logs\latest-winterbreak2-stage.txt"
    } else {
        "logs\latest-winterbreak2-executed.txt"
    }
    $pointer = Get-FullProjectPath $pointerName
    if (-not (Test-Path -LiteralPath $pointer -PathType Leaf)) {
        if ($Require) { throw "No local WinterBreak2 $Kind record was found." }
        return $null
    }

    $manifestPath = (Get-Content -LiteralPath $pointer -Raw).Trim()
    $backupRoot = (Get-FullProjectPath "device-backups").TrimEnd("\") + "\"
    $manifestFull = [IO.Path]::GetFullPath($manifestPath)
    if (-not $manifestFull.StartsWith($backupRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a WinterBreak2 manifest outside device-backups: $manifestFull"
    }
    if ((Split-Path $manifestFull -Leaf) -cne "manifest.json" -or
        -not (Test-Path -LiteralPath $manifestFull -PathType Leaf)) {
        throw "The WinterBreak2 $Kind manifest is missing or is not manifest.json: $manifestFull"
    }
    $record = [ordered]@{
        pointerPath = $pointer
        manifestPath = $manifestFull
        manifest = Get-Content -LiteralPath $manifestFull -Raw | ConvertFrom-Json
    }
    Assert-WinterBreak2RecordShape $record $Kind
    return $record
}

function Assert-WinterBreak2RecordShape {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [ValidateSet("active", "executed")]
        [string] $Kind = "active"
    )

    $manifest = $Record.manifest
    if ([string]$manifest.firmware -cne $ExpectedFirmware -or
        [string]$manifest.winterBreak2Version -cne [string]$WinterBreak2.Version -or
        [string]$manifest.archiveSha256 -cne [string]$WinterBreak2.Sha256) {
        throw "The WinterBreak2 record does not match the pinned firmware, version, and archive."
    }
    if ([string]$manifest.deviceFingerprint -notmatch "^[0-9a-f]{64}$") {
        throw "The WinterBreak2 record has an invalid device fingerprint."
    }
    if ([string]$manifest.deviceIdentityHash -notmatch "^[0-9a-f]{64}$") {
        throw "The WinterBreak2 record has an invalid device identity hash."
    }
    $validStatuses = if ($Kind -eq "active") {
        @("prepared", "complete", "rollback-incomplete", "executed", "rolledBack")
    } else {
        @("executed")
    }
    if ([string]$manifest.status -notin $validStatuses) {
        throw "The WinterBreak2 $Kind record has invalid status '$($manifest.status)'."
    }

    $fileEntries = @($manifest.files)
    if ($fileEntries.Count -ne $WinterBreak2Files.Count) {
        throw "The WinterBreak2 record does not contain the exact pinned file set."
    }
    $seenFiles = @{}
    foreach ($entry in $fileEntries) {
        $relative = [string]$entry.relativePath
        if ($relative -cnotin $WinterBreak2Files -or $seenFiles.ContainsKey($relative)) {
            throw "The WinterBreak2 record contains an unexpected or duplicate file path: '$relative'."
        }
        $seenFiles[$relative] = $true
        if ([string]$entry.stagedSha256 -notmatch "^[0-9a-f]{64}$") {
            throw "The WinterBreak2 record contains an invalid staged SHA-256 for '$relative'."
        }
        if ($entry.PSObject.Properties.Name -notcontains "wasPresent" -or
            $entry.wasPresent -isnot [bool]) {
            throw "The WinterBreak2 record contains an invalid wasPresent flag for '$relative'."
        }
        if ($entry.wasPresent -and [string]$entry.originalSha256 -notmatch "^[0-9a-f]{64}$") {
            throw "The WinterBreak2 record contains an invalid original SHA-256 for '$relative'."
        }
        if (-not $entry.wasPresent -and -not [string]::IsNullOrEmpty([string]$entry.originalSha256)) {
            throw "The WinterBreak2 record unexpectedly contains an original SHA-256 for a new file: '$relative'."
        }
        $expectedStageTemp = "$relative.lazying-art-wb2-stage-$(([string]$entry.stagedSha256).Substring(0, 16)).tmp"
        if ([string]$entry.stageTemporaryRelativePath -cne $expectedStageTemp) {
            throw "The WinterBreak2 record contains an invalid stage temporary path for '$relative'."
        }
        if ($entry.wasPresent) {
            $expectedRestoreTemp = "$relative.lazying-art-wb2-restore-$(([string]$entry.originalSha256).Substring(0, 16)).tmp"
            if ([string]$entry.restoreTemporaryRelativePath -cne $expectedRestoreTemp) {
                throw "The WinterBreak2 record contains an invalid restore temporary path for '$relative'."
            }
        } elseif (-not [string]::IsNullOrEmpty([string]$entry.restoreTemporaryRelativePath)) {
            throw "The WinterBreak2 record unexpectedly declares a restore temporary path for a new file: '$relative'."
        }
    }

    $directoryEntries = @($manifest.directories)
    if ($directoryEntries.Count -ne $WinterBreak2Directories.Count) {
        throw "The WinterBreak2 record does not contain the exact pinned directory set."
    }
    $seenDirectories = @{}
    foreach ($entry in $directoryEntries) {
        $relative = [string]$entry.relativePath
        if ($relative -cnotin $WinterBreak2Directories -or $seenDirectories.ContainsKey($relative)) {
            throw "The WinterBreak2 record contains an unexpected or duplicate directory path: '$relative'."
        }
        if ($entry.PSObject.Properties.Name -notcontains "wasPresent" -or
            $entry.wasPresent -isnot [bool]) {
            throw "The WinterBreak2 record contains an invalid directory wasPresent flag for '$relative'."
        }
        $seenDirectories[$relative] = $true
    }
}

function Publish-WinterBreak2ExecutedRecord {
    param([Parameter(Mandatory = $true)] $Record)

    $executedPointer = Get-FullProjectPath "logs\latest-winterbreak2-executed.txt"
    if (Test-Path -LiteralPath $executedPointer -PathType Leaf) {
        $existing = [IO.Path]::GetFullPath((Get-Content -LiteralPath $executedPointer -Raw).Trim())
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($existing, $Record.manifestPath)) {
            throw "A different executed WinterBreak2 audit record already exists: $existing"
        }
    } else {
        New-Item -ItemType Directory -Path (Split-Path $executedPointer -Parent) -Force | Out-Null
        Write-ProjectTextAtomic $executedPointer $Record.manifestPath
    }

    if (Test-Path -LiteralPath $Record.pointerPath -PathType Leaf) {
        $active = [IO.Path]::GetFullPath((Get-Content -LiteralPath $Record.pointerPath -Raw).Trim())
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($active, $Record.manifestPath)) {
            throw "The active WinterBreak2 pointer changed while finalizing execution."
        }
        Remove-Item -LiteralPath $Record.pointerPath -Force
    }
}

function Get-StoreCacheRecord {
    param([switch] $Require)

    $latest = Get-FullProjectPath "logs\latest-winterbreak-store-cache.txt"
    if (-not (Test-Path -LiteralPath $latest)) {
        if ($Require) { throw "No local WinterBreak Store-cache record was found." }
        return $null
    }
    $manifestPath = (Get-Content -LiteralPath $latest -Raw).Trim()
    $backupRoot = (Get-FullProjectPath "device-backups").TrimEnd("\") + "\"
    $manifestFull = [IO.Path]::GetFullPath($manifestPath)
    if (-not $manifestFull.StartsWith($backupRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a Store-cache manifest outside device-backups: $manifestFull"
    }
    if (-not (Test-Path -LiteralPath $manifestFull -PathType Leaf)) {
        throw "The active Store-cache manifest is missing: $manifestFull"
    }
    return [ordered]@{
        latestPath = $latest
        manifestPath = $manifestFull
        manifest = Get-Content -LiteralPath $manifestFull -Raw | ConvertFrom-Json
    }
}

function Complete-StoreCacheRecordAfterJailbreak {
    param([Parameter(Mandatory = $true)][string] $Root)

    $record = Get-StoreCacheRecord
    if (-not $record) { return }
    if ($record.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The connected Kindle does not match the Store-cache record."
    }
    $record.manifest.status = "executed"
    $record.manifest | Add-Member -NotePropertyName jailbreakVerifiedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    $record.manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $record.manifestPath -Encoding UTF8
    Remove-Item -LiteralPath $record.latestPath -Force
}

function Assert-StoreSandboxRecordShape {
    param([Parameter(Mandatory = $true)] $Record)

    if ((Split-Path $Record.manifestPath -Leaf) -cne "manifest.json") {
        throw "The active Store-sandbox record does not point to manifest.json."
    }
    $manifest = $Record.manifest
    if (-not [StringComparer]::Ordinal.Equals(
            [string]$manifest.sandboxRelativePath,
            $StoreSandboxRelativePath
        )) {
        throw "The Store-sandbox manifest path is not exactly '$StoreSandboxRelativePath'."
    }
    if ([string]$manifest.status -notin @("prepared", "removed", "regenerated", "restored", "executed")) {
        throw "The Store-sandbox manifest has an invalid status: '$($manifest.status)'."
    }
    if ($manifest.PSObject.Properties.Name -notcontains "files" -or
        $manifest.PSObject.Properties.Name -notcontains "directories") {
        throw "The Store-sandbox manifest is missing its complete tree inventory."
    }
}

function Get-StoreSandboxRecord {
    param([switch] $Require)

    $latest = Get-FullProjectPath "logs\latest-winterbreak-store-sandbox.txt"
    if (-not (Test-Path -LiteralPath $latest)) {
        if ($Require) { throw "No local full Store-sandbox record was found." }
        return $null
    }
    $manifestPath = (Get-Content -LiteralPath $latest -Raw).Trim()
    $backupRoot = (Get-FullProjectPath "device-backups").TrimEnd("\") + "\"
    $manifestFull = [IO.Path]::GetFullPath($manifestPath)
    if (-not $manifestFull.StartsWith($backupRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a Store-sandbox manifest outside device-backups: $manifestFull"
    }
    if (-not (Test-Path -LiteralPath $manifestFull -PathType Leaf)) {
        throw "The active Store-sandbox manifest is missing: $manifestFull"
    }
    $record = [ordered]@{
        latestPath = $latest
        manifestPath = $manifestFull
        manifest = Get-Content -LiteralPath $manifestFull -Raw | ConvertFrom-Json
    }
    Assert-StoreSandboxRecordShape $record
    return $record
}

function Complete-StoreSandboxRecord {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)]
        [ValidateSet("regenerated", "executed")]
        [string] $Status,
        [switch] $ConfirmedPreparedRecovery
    )

    $record = Get-StoreSandboxRecord
    if (-not $record) { return }
    if ($record.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The connected Kindle does not match the full Store-sandbox record."
    }
    $current = [string]$record.manifest.status
    $validPriorStates = switch ($Status) {
        "regenerated" {
            if ($ConfirmedPreparedRecovery) { @("prepared", "removed") }
            else { @("removed") }
        }
        "executed" { @("removed", "regenerated") }
    }
    if ($current -eq $Status) {
        Remove-Item -LiteralPath $record.latestPath -Force
        return
    }
    if ($current -notin $validPriorStates) {
        throw "Invalid Store-sandbox transition '$current' -> '$Status'."
    }
    $record.manifest.status = $Status
    $record.manifest | Add-Member -NotePropertyName completedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    $record.manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $record.manifestPath -Encoding UTF8
    Remove-Item -LiteralPath $record.latestPath -Force
}

function Get-KindleInfo {
    param([Parameter(Mandatory = $true)][string] $Root)

    $versionText = (Get-Content -LiteralPath (Join-Path $Root "system\version.txt") -Raw).Trim()
    $firmware = $null
    if ($versionText -match "(\d+\.\d+(?:\.\d+){0,4})") {
        $firmware = $Matches[1]
    }
    $drive = Get-CimInstance Win32_LogicalDisk |
        Where-Object { "$($_.DeviceID)\" -ieq $Root } |
        Select-Object -First 1

    return [ordered]@{
        root = $Root
        volumeName = $drive.VolumeName
        firmware = $firmware
        sizeBytes = [int64]$drive.Size
        freeBytes = [int64]$drive.FreeSpace
        winterBreakStaged = (
            (Test-Path -LiteralPath (Join-Path $Root ".active_content_sandbox")) -and
            (Test-Path -LiteralPath (Join-Path $Root "apps\tech.hackerdude.winterbreak")) -and
            (Test-Path -LiteralPath (Join-Path $Root "mesquito"))
        )
        jailbrokenMarker = Test-Path -LiteralPath (Join-Path $Root "documents\JAILBROKEN.txt")
        kpmUserStore = Test-Path -LiteralPath (Join-Path $Root "kmc\kpm")
        kual = (
            (Test-Path -LiteralPath (Join-Path $Root "documents\KUAL.sh")) -or
            (Test-Path -LiteralPath (Join-Path $Root "documents\KUAL.jar"))
        )
        koreader = Test-Path -LiteralPath (Join-Path $Root "koreader\koreader.sh")
        otaFiller = Test-Path -LiteralPath (Join-Path $Root ".kindle-ota-space-filler")
        disableAutoStart = Test-Path -LiteralPath (Join-Path $Root "DISABLE_KOREADER_AUTOSTART")
    }
}

function Assert-ExpectedDevice {
    param([Parameter(Mandatory = $true)][string] $Root)

    $info = Get-KindleInfo $Root
    if (-not $ForceFirmwareOverride -and $info.firmware -ne $ExpectedFirmware) {
        throw "Expected firmware $ExpectedFirmware, but this Kindle reports $($info.firmware). This device-specific workflow will not continue; use -ForceFirmwareOverride only after a fresh independent compatibility audit."
    }
    return $info
}

function Assert-AirplaneConfirmation {
    if (-not $ConfirmedAirplaneMode) {
        throw "Before staging or filling storage: save a working Wi-Fi profile, turn Airplane Mode ON, restart the Kindle, reconnect USB, then rerun with -ConfirmedAirplaneMode."
    }
}

function Invoke-VerifiedDownload {
    param(
        [Parameter(Mandatory = $true)][string] $Url,
        [Parameter(Mandatory = $true)][string] $Destination,
        [Parameter(Mandatory = $true)][string] $Sha256
    )

    $destinationFull = [IO.Path]::GetFullPath($Destination)
    $destinationParent = [IO.Path]::GetDirectoryName($destinationFull)
    if ([string]::IsNullOrWhiteSpace($destinationParent)) {
        $destinationParent = [IO.Path]::GetPathRoot($destinationFull)
    }
    if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $Destination)) {
        Write-Host "Downloading $Url"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant()
    if ($actual -ne $Sha256.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $Destination. Expected $Sha256, got $actual"
    }
    Write-Host "Verified $Destination ($actual)"
    return $Destination
}

function Download-Packages {
    $downloads = Get-FullProjectPath "downloads"
    New-Item -ItemType Directory -Path $downloads -Force | Out-Null
    Invoke-VerifiedDownload $WinterBreak.Url (Join-Path $downloads $WinterBreak.File) $WinterBreak.Sha256 | Out-Null
    Invoke-VerifiedDownload $WinterBreak2.Url (Join-Path $downloads $WinterBreak2.File) $WinterBreak2.Sha256 | Out-Null
    Invoke-VerifiedDownload $UniversalHotfix.Url (Join-Path $downloads $UniversalHotfix.File) $UniversalHotfix.Sha256 | Out-Null
    Invoke-VerifiedDownload $KOReader.Url (Join-Path $downloads $KOReader.File) $KOReader.Sha256 | Out-Null
}

function Download-WinterBreak2Packages {
    $downloads = Get-FullProjectPath "downloads"
    New-Item -ItemType Directory -Path $downloads -Force | Out-Null
    Invoke-VerifiedDownload $WinterBreak2.Url (Join-Path $downloads $WinterBreak2.File) $WinterBreak2.Sha256 | Out-Null
    Invoke-VerifiedDownload $UniversalHotfix.Url (Join-Path $downloads $UniversalHotfix.File) $UniversalHotfix.Sha256 | Out-Null
}

function Backup-VisibleKindle {
    param([Parameter(Mandatory = $true)][string] $Root)

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = Get-FullProjectPath ("device-backups\pw5se-{0}-{1}" -f $ExpectedFirmware, $stamp)
    New-Item -ItemType Directory -Path $backup -Force | Out-Null

    foreach ($name in @("system", "documents", "voice", "audible", "fonts")) {
        $source = Join-Path $Root $name
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination $backup -Recurse -Force
        }
    }
    Write-Host "USB-visible Kindle backup: $backup"
    return $backup
}

function Expand-WinterBreak {
    $downloads = Get-FullProjectPath "downloads"
    $archive = Invoke-VerifiedDownload `
        $WinterBreak.Url `
        (Join-Path $downloads $WinterBreak.File) `
        $WinterBreak.Sha256
    $stage = Reset-ProjectDirectory "staging\winterbreak-v2.1.0-root"
    & tar.exe -xzf $archive -C $stage
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe failed to extract WinterBreak."
    }
    foreach ($required in @(".active_content_sandbox", "apps\tech.hackerdude.winterbreak", "mesquito")) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $required))) {
            throw "WinterBreak archive is missing required path: $required"
        }
    }
    return $stage
}

function Get-PinnedStoreStageInventory {
    $stage = Expand-WinterBreak
    $inventory = Get-DirectoryManifestInventory $stage "pinned Store WinterBreak package"
    if ($inventory.files.Count -ne 17) {
        throw "The pinned Store WinterBreak archive inventory unexpectedly contains $($inventory.files.Count) files instead of 17."
    }
    return [ordered]@{
        stageRoot = $stage
        files = @($inventory.files)
        directories = @($inventory.directories)
    }
}

function Stage-WinterBreak {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-StoreRouteOpen $Root "Stage"
    Assert-AirplaneConfirmation
    $info = Assert-ExpectedDevice $Root
    if ($info.jailbrokenMarker) {
        throw "documents\JAILBROKEN.txt already exists. Do not rerun the exploit; use VerifyJailbreak or StageKOReader."
    }
    if ($info.winterBreakStaged) {
        throw "WinterBreak is already staged. Use Diagnose or UndoStage; restaging is blocked so the original rollback provenance is preserved."
    }
    Assert-NoActiveStageRecord

    $stage = Expand-WinterBreak
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $recordRoot = Get-FullProjectPath ("device-backups\winterbreak-stage-{0}-{1}" -f $ExpectedFirmware, $stamp)
    $overwritten = Join-Path $recordRoot "overwritten"
    New-Item -ItemType Directory -Path $overwritten -Force | Out-Null

    $stagePrefix = $stage.TrimEnd("\") + "\"
    $directoryRecords = @(
        Get-ChildItem -LiteralPath $stage -Directory -Recurse -Force |
            ForEach-Object {
                $relative = $_.FullName.Substring($stagePrefix.Length)
                [ordered]@{
                    relativePath = $relative
                    wasPresent = Test-Path -LiteralPath (Get-SafeChildPath $Root $relative "staged directory")
                }
            }
    )
    $fileRecords = @()
    foreach ($file in Get-ChildItem -LiteralPath $stage -File -Recurse -Force) {
        $relative = $file.FullName.Substring($stagePrefix.Length)
        $destination = Get-SafeChildPath $Root $relative "staged file"
        $wasPresent = Test-Path -LiteralPath $destination
        $originalHash = $null
        if ($wasPresent) {
            $originalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
            $backupFile = Get-SafeChildPath $overwritten $relative "rollback backup"
            New-Item -ItemType Directory -Path (Split-Path $backupFile -Parent) -Force | Out-Null
            Copy-Item -LiteralPath $destination -Destination $backupFile -Force
            $backupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupFile).Hash.ToLowerInvariant()
            if ($backupHash -ne $originalHash) {
                throw "Rollback backup SHA-256 mismatch: $backupFile"
            }
        }
        $stagedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
        $fileRecords += [ordered]@{
            relativePath = $relative
            wasPresent = $wasPresent
            originalSha256 = $originalHash
            stagedSha256 = $stagedHash
        }
    }

    $manifest = [ordered]@{
        createdAt = (Get-Date).ToString("o")
        status = "prepared"
        firmware = $info.firmware
        winterBreakVersion = $WinterBreak.Version
        archiveSha256 = $WinterBreak.Sha256
        deviceFingerprint = Get-KindleFingerprint $Root
        kindleRootAtStageTime = $Root
        files = $fileRecords
        directories = $directoryRecords
    }
    $manifestPath = Join-Path $recordRoot "manifest.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $latest = Get-FullProjectPath "logs\latest-winterbreak-stage.txt"
    New-Item -ItemType Directory -Path (Split-Path $latest -Parent) -Force | Out-Null
    Set-Content -LiteralPath $latest -Value $manifestPath -Encoding UTF8

    foreach ($entry in $directoryRecords) {
        New-Item -ItemType Directory -Path (Get-SafeChildPath $Root $entry.relativePath "staged directory") -Force | Out-Null
    }
    foreach ($entry in $fileRecords) {
        $source = Get-SafeChildPath $stage $entry.relativePath "staging source"
        $destination = Get-SafeChildPath $Root $entry.relativePath "staged file"
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
        $copiedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($copiedHash -ne $entry.stagedSha256) {
            throw "Post-copy SHA-256 mismatch: $destination"
        }
    }
    $manifest.status = "complete"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    Write-Host "WinterBreak v$($WinterBreak.Version) staged, including hidden files."
    Write-Host "Reversible stage manifest: $manifestPath"
}

function Undo-WinterBreakStage {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-StoreRouteOpen $Root "UndoStage"
    Assert-AirplaneConfirmation
    if (Test-Path -LiteralPath (Join-Path $Root "documents\JAILBROKEN.txt")) {
        throw "The jailbreak success marker exists. UndoStage is only for cancelling before the exploit runs."
    }
    $record = Get-RecordedManifest -Require
    $latest = $record.latestPath
    $manifestPath = $record.manifestPath
    $recordRoot = Split-Path $manifestPath -Parent
    $manifest = $record.manifest
    if ($manifest.status -notin @("prepared", "complete", "rollback-incomplete")) {
        throw "Manifest status '$($manifest.status)' is not an active stage and cannot be rolled back."
    }
    if ($manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The connected Kindle does not match the staging manifest fingerprint. No rollback changes were made."
    }
    $currentFirmware = (Get-KindleInfo $Root).firmware
    if ($manifest.firmware -ne $currentFirmware) {
        throw "The connected firmware ($currentFirmware) does not match the staging manifest ($($manifest.firmware))."
    }
    $skipped = @()

    # Validate every required local backup before changing anything on the
    # Kindle, so rollback cannot become half-applied due to a late bad backup.
    foreach ($entry in $manifest.files) {
        if (-not $entry.wasPresent) { continue }
        $backupFile = Get-SafeChildPath (Join-Path $recordRoot "overwritten") $entry.relativePath "rollback backup"
        if (-not (Test-Path -LiteralPath $backupFile -PathType Leaf)) {
            throw "Missing rollback file: $backupFile"
        }
        $backupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupFile).Hash.ToLowerInvariant()
        if ($backupHash -ne $entry.originalSha256.ToLowerInvariant()) {
            throw "Rollback backup SHA-256 mismatch: $backupFile"
        }
    }

    foreach ($entry in $manifest.files) {
        $destination = Get-SafeChildPath $Root $entry.relativePath "rollback destination"
        if (-not (Test-Path -LiteralPath $destination)) {
            if ($entry.wasPresent) {
                $backupFile = Get-SafeChildPath (Join-Path $recordRoot "overwritten") $entry.relativePath "rollback backup"
                if (-not (Test-Path -LiteralPath $backupFile)) {
                    throw "Missing rollback file: $backupFile"
                }
                New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
                Copy-Item -LiteralPath $backupFile -Destination $destination -Force
                $restoredHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
                if ($restoredHash -ne $entry.originalSha256.ToLowerInvariant()) {
                    throw "Restored file SHA-256 mismatch: $destination"
                }
            }
            continue
        }
        $currentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($entry.wasPresent -and $currentHash -eq $entry.originalSha256.ToLowerInvariant()) {
            # A previous rollback attempt already restored this file.
            continue
        }
        if ($currentHash -ne $entry.stagedSha256.ToLowerInvariant()) {
            $skipped += $entry.relativePath
            continue
        }
        if ($entry.wasPresent) {
            $backupFile = Get-SafeChildPath (Join-Path $recordRoot "overwritten") $entry.relativePath "rollback backup"
            if (-not (Test-Path -LiteralPath $backupFile)) {
                throw "Missing rollback file: $backupFile"
            }
            Copy-Item -LiteralPath $backupFile -Destination $destination -Force
            $restoredHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
            if ($restoredHash -ne $entry.originalSha256.ToLowerInvariant()) {
                throw "Restored file SHA-256 mismatch: $destination"
            }
        } else {
            Remove-Item -LiteralPath $destination -Force
        }
    }

    foreach ($entry in (@($manifest.directories) | Sort-Object { $_.relativePath.Length } -Descending)) {
        if ($entry.wasPresent) {
            continue
        }
        $directory = Get-SafeChildPath $Root $entry.relativePath "rollback directory"
        if (Test-Path -LiteralPath $directory) {
            $children = @(Get-ChildItem -LiteralPath $directory -Force)
            if ($children.Count -eq 0) {
                Remove-Item -LiteralPath $directory -Force
            }
        }
    }

    if ($skipped.Count -gt 0) {
        $manifest.status = "rollback-incomplete"
        $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
        Write-Warning ("Left diverged files untouched: " + ($skipped -join ", "))
    } else {
        $manifest.status = "rolledBack"
        $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
        Remove-Item -LiteralPath $latest -Force
    }
    Write-Host "WinterBreak staging rollback completed."
}

function Get-RootKindleUpdateFiles {
    param([Parameter(Mandatory = $true)][string] $Root)

    return @(
        Get-ChildItem -LiteralPath $Root -File -Force |
            Where-Object {
                $_.Name -ilike "update*.bin" -or
                $_.Name -ieq "update.bin.tmp.partial"
            }
    )
}

function Assert-NoRootKindleUpdates {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [string] $AllowedExactName
    )

    $unexpected = @(
        Get-RootKindleUpdateFiles $Root |
            Where-Object {
                -not $AllowedExactName -or
                -not [StringComparer]::OrdinalIgnoreCase.Equals($_.Name, $AllowedExactName)
            }
    )
    if ($unexpected.Count -gt 0) {
        $names = ($unexpected | ForEach-Object { $_.Name } | Sort-Object -Unique) -join ", "
        throw "Root-level Kindle update package(s) require review before continuing: $names"
    }
}

function Assert-StoreRouteOpen {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)][string] $ActionName
    )

    $statePaths = @(
        (Get-FullProjectPath "logs\latest-winterbreak2-stage.txt"),
        (Get-FullProjectPath "logs\latest-winterbreak2-executed.txt"),
        (Get-SafeChildPath $Root "winterbreak.log" "WinterBreak2 log")
    )
    if (@($statePaths | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0) {
        throw "$ActionName belongs to the closed Store route and is blocked after WinterBreak2 state exists. Use the dedicated WinterBreak2 actions."
    }
}

function Assert-ExactWinterBreak2Device {
    param([Parameter(Mandatory = $true)][string] $Root)

    $info = Get-KindleInfo $Root
    if ([string]$info.firmware -cne $ExpectedFirmware) {
        throw "WinterBreak2 is pinned to firmware $ExpectedFirmware; the connected Kindle reports '$($info.firmware)'. Firmware override is intentionally unavailable for this fallback."
    }
    return $info
}

function Assert-OriginalWinterBreakStageGuard {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [switch] $RequireDeviceIdentity
    )

    $record = Get-RecordedManifest -Require
    $manifest = $record.manifest
    $fingerprint = Get-KindleFingerprint $Root
    if ([string]$manifest.status -cne "complete" -or
        [string]$manifest.firmware -cne $ExpectedFirmware -or
        [string]$manifest.winterBreakVersion -cne [string]$WinterBreak.Version -or
        [string]$manifest.archiveSha256 -cne [string]$WinterBreak.Sha256 -or
        [string]$manifest.deviceFingerprint -cne $fingerprint) {
        throw "A matching, complete, pinned Store WinterBreak stage record is required before using the browser fallback."
    }

    $storeFiles = @($manifest.files)
    if ($storeFiles.Count -ne 17) {
        throw "The pinned Store WinterBreak stage manifest must contain exactly 17 files; found $($storeFiles.Count)."
    }
    $pinned = Get-PinnedStoreStageInventory
    $seen = @{}
    $actualFileRows = @()
    foreach ($entry in $storeFiles) {
        $relative = Get-ValidatedManifestRelativePath $Root ([string]$entry.relativePath) "Store WinterBreak stage manifest"
        if ($seen.ContainsKey($relative)) {
            throw "The Store WinterBreak stage manifest contains a duplicate path: $relative"
        }
        $seen[$relative] = $true
        $expectedHash = [string]$entry.stagedSha256
        if ($expectedHash -notmatch "^[0-9a-f]{64}$") {
            throw "The Store WinterBreak stage manifest has an invalid SHA-256: $relative"
        }
        $actualFileRows += "$relative|$expectedHash"
        $destination = Get-SafeChildPath $Root $relative "Store WinterBreak staged file"
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant() -ne $expectedHash) {
            throw "The Store WinterBreak stage no longer matches its manifest: $relative"
        }
    }
    $pinnedFileRows = @($pinned.files | ForEach-Object { "$($_.relativePath)|$($_.sha256)" })
    if (@(Compare-Object ($pinnedFileRows | Sort-Object) ($actualFileRows | Sort-Object) -CaseSensitive).Count -gt 0) {
        throw "The Store WinterBreak stage manifest file path/hash set differs from the pinned v$($WinterBreak.Version) archive."
    }

    $storeDirectories = @($manifest.directories)
    $actualDirectoryRows = @()
    $seenDirectories = @{}
    foreach ($entry in $storeDirectories) {
        $relative = Get-ValidatedManifestRelativePath $Root ([string]$entry.relativePath) "Store WinterBreak directory manifest"
        if ($seenDirectories.ContainsKey($relative)) {
            throw "The Store WinterBreak stage manifest contains a duplicate directory: $relative"
        }
        $seenDirectories[$relative] = $true
        $actualDirectoryRows += $relative
        if (-not (Test-Path -LiteralPath (Get-SafeChildPath $Root $relative "Store WinterBreak staged directory") -PathType Container)) {
            throw "The Store WinterBreak staged directory is missing: $relative"
        }
    }
    if (@(Compare-Object (@($pinned.directories) | Sort-Object) ($actualDirectoryRows | Sort-Object) -CaseSensitive).Count -gt 0) {
        throw "The Store WinterBreak stage manifest directory set differs from the pinned v$($WinterBreak.Version) archive."
    }

    $hasIdentity = $manifest.PSObject.Properties.Name -contains "deviceIdentityHash"
    if ($hasIdentity) {
        $identity = [string]$manifest.deviceIdentityHash
        if ($identity -notmatch "^[0-9a-f]{64}$" -or $identity -cne (Get-KindleIdentityHash $Root)) {
            throw "The connected Kindle does not match the Store-stage device identity binding."
        }
    } elseif ($RequireDeviceIdentity) {
        throw "The Store-stage record is not bound to a stable device identity. Run BindDeviceIdentity first."
    }
    return $record
}

function Assert-WinterBreak2PackageTree {
    param([Parameter(Mandatory = $true)][string] $Root)

    $inventory = Get-DirectoryManifestInventory $Root "WinterBreak2 package tree"
    if ($inventory.files.Count -ne $WinterBreak2Files.Count -or
        $inventory.directories.Count -ne $WinterBreak2Directories.Count) {
        throw "The WinterBreak2 archive does not contain the exact pinned file/directory set."
    }
    foreach ($entry in $inventory.files) {
        if ([string]$entry.relativePath -cnotin $WinterBreak2Files) {
            throw "The WinterBreak2 archive contains an unexpected file: $($entry.relativePath)"
        }
    }
    foreach ($relative in $inventory.directories) {
        if ([string]$relative -cnotin $WinterBreak2Directories) {
            throw "The WinterBreak2 archive contains an unexpected directory: $relative"
        }
    }
    return $inventory
}

function Bind-WinterBreak2DeviceIdentity {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-StoreRouteOpen $Root "BindDeviceIdentity"
    Assert-AirplaneConfirmation
    Assert-ExactWinterBreak2Device $Root | Out-Null
    $record = Assert-OriginalWinterBreakStageGuard $Root
    Assert-OwnedOtaFiller $Root | Out-Null
    Assert-NoRootKindleUpdates $Root
    $identity = Get-KindleIdentityHash $Root
    if ($record.manifest.PSObject.Properties.Name -contains "deviceIdentityHash") {
        if ([string]$record.manifest.deviceIdentityHash -cne $identity) {
            throw "The Store-stage record is already bound to a different device identity."
        }
        Write-Host "The Store-stage record is already bound to this Kindle identity."
        return
    }

    if (-not $record.latestPath -or -not (Test-Path -LiteralPath $record.latestPath -PathType Leaf)) {
        throw "The active Store-stage pointer is unavailable; identity binding was not written."
    }
    $pointedManifest = [IO.Path]::GetFullPath((Get-Content -LiteralPath $record.latestPath -Raw).Trim())
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals($pointedManifest, $record.manifestPath)) {
        throw "The active Store-stage pointer changed during identity binding."
    }
    $record.manifest | Add-Member -NotePropertyName deviceIdentityHash -NotePropertyValue $identity -Force
    $record.manifest | Add-Member -NotePropertyName deviceIdentityScheme -NotePropertyValue "windows-volume-serial-size-sha256-v1" -Force
    $record.manifest | Add-Member -NotePropertyName deviceIdentityBoundAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    Write-ProjectJsonAtomic $record.manifestPath $record.manifest

    $verified = Get-RecordedManifest -Require
    if ([string]$verified.manifest.deviceIdentityHash -cne $identity) {
        throw "The Store-stage identity binding did not verify after publication."
    }
    Write-Host "Bound the active Store-stage record to this Kindle identity without recording or printing the raw volume identifier."
}

function Expand-WinterBreak2 {
    $downloads = Get-FullProjectPath "downloads"
    $archive = Invoke-VerifiedDownload `
        $WinterBreak2.Url `
        (Join-Path $downloads $WinterBreak2.File) `
        $WinterBreak2.Sha256
    $stage = Reset-ProjectDirectory "staging\winterbreak2-v1.0.0-root"
    Expand-Archive -LiteralPath $archive -DestinationPath $stage -Force
    Assert-WinterBreak2PackageTree $stage | Out-Null
    return $stage
}

function Assert-NoWinterBreak2ExecutionEvidence {
    param([Parameter(Mandatory = $true)][string] $Root)

    $logPath = Get-SafeChildPath $Root "winterbreak.log" "WinterBreak2 log"
    if (Test-Path -LiteralPath $logPath) {
        throw "winterbreak.log exists, so browser exploit execution may already have started. Verification is allowed; staging or rollback is not."
    }
}

function Assert-WinterBreak2SuccessLog {
    param([Parameter(Mandatory = $true)][string] $Root)

    $logPath = Get-SafeChildPath $Root "winterbreak.log" "WinterBreak2 log"
    if (-not (Test-Path -LiteralPath $logPath -PathType Leaf)) {
        throw "winterbreak.log is absent; stock WinterBreak2 success is not proven."
    }
    $log = Get-Content -LiteralPath $logPath -Raw
    foreach ($failure in $WinterBreak2FailureEvidence) {
        if ($log.IndexOf($failure, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "winterbreak.log contains explicit failure evidence; the record was not marked executed."
        }
    }
    foreach ($evidence in $WinterBreak2SuccessEvidence) {
        if ($log.IndexOf($evidence, [StringComparison]::Ordinal) -lt 0) {
            throw "winterbreak.log is missing one or more required stock success gates; the record was not marked executed."
        }
    }
    Write-Host "WinterBreak2 log gates passed: developer key, developer flag, executable USB mount, jailbreak completion, and hotfix prompt."
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $logPath).Hash.ToLowerInvariant()
}

function Assert-WinterBreak2RecordMatchesDevice {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root
    )

    Assert-WinterBreak2RecordShape $Record $(if ([string]$Record.manifest.status -eq "executed") { "executed" } else { "active" })
    if ([string]$Record.manifest.deviceFingerprint -cne (Get-KindleFingerprint $Root)) {
        throw "The connected Kindle does not match the WinterBreak2 record fingerprint."
    }
    if ([string]$Record.manifest.deviceIdentityHash -cne (Get-KindleIdentityHash $Root)) {
        throw "The connected Kindle does not match the WinterBreak2 stable device identity."
    }
    foreach ($entry in @($Record.manifest.files)) {
        Get-ValidatedManifestRelativePath $Root ([string]$entry.relativePath) "WinterBreak2 manifest file" | Out-Null
    }
    foreach ($entry in @($Record.manifest.directories)) {
        Get-ValidatedManifestRelativePath $Root ([string]$entry.relativePath) "WinterBreak2 manifest directory" | Out-Null
    }
}

function Assert-WinterBreak2LocalBackups {
    param([Parameter(Mandatory = $true)] $Record)

    $overwritten = Join-Path (Split-Path $Record.manifestPath -Parent) "overwritten"
    foreach ($entry in @($Record.manifest.files)) {
        $backup = Get-SafeChildPath $overwritten ([string]$entry.relativePath) "WinterBreak2 rollback backup"
        if (-not [bool]$entry.wasPresent) {
            if (Test-Path -LiteralPath $backup) {
                throw "WinterBreak2 rollback backup state is inconsistent for a manifest-declared new file: $($entry.relativePath)"
            }
            continue
        }
        if (-not (Test-Path -LiteralPath $backup -PathType Leaf) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $backup).Hash.ToLowerInvariant() -ne [string]$entry.originalSha256) {
            throw "WinterBreak2 rollback backup verification failed: $($entry.relativePath)"
        }
    }
}

function Assert-WinterBreak2DestinationsResumable {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root
    )

    foreach ($entry in @($Record.manifest.directories)) {
        $destination = Get-SafeChildPath $Root ([string]$entry.relativePath) "WinterBreak2 directory"
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            throw "A file blocks the WinterBreak2 directory: $($entry.relativePath)"
        }
    }
    foreach ($entry in @($Record.manifest.files)) {
        $destination = Get-SafeChildPath $Root ([string]$entry.relativePath) "WinterBreak2 file"
        if (Test-Path -LiteralPath $destination -PathType Container) {
            throw "A directory blocks the WinterBreak2 file: $($entry.relativePath)"
        }
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
            # A power or cable interruption can leave the final name absent
            # after a same-volume temp was verified. The separately validated
            # rollback backup makes this safe to resume.
            continue
        }
        $currentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        $allowed = $currentHash -eq [string]$entry.stagedSha256
        if ([bool]$entry.wasPresent) {
            $allowed = $allowed -or $currentHash -eq [string]$entry.originalSha256
        }
        if (-not $allowed) {
            throw "A WinterBreak2 destination diverged while staging was incomplete: $($entry.relativePath)"
        }
    }
}

function Get-WinterBreak2OwnedTempPath {
    param(
        [Parameter(Mandatory = $true)][string] $Destination,
        [Parameter(Mandatory = $true)][string] $ExpectedSha256,
        [ValidateSet("stage", "restore")]
        [string] $Purpose = "stage"
    )

    return "$Destination.lazying-art-wb2-$Purpose-$($ExpectedSha256.Substring(0, 16)).tmp"
}

function Install-VerifiedFileAtomically {
    param(
        [Parameter(Mandatory = $true)][string] $Source,
        [Parameter(Mandatory = $true)][string] $Destination,
        [Parameter(Mandatory = $true)][string] $ExpectedSha256,
        [ValidateSet("stage", "restore")]
        [string] $Purpose = "stage"
    )

    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Source).Hash.ToLowerInvariant() -ne $ExpectedSha256) {
        throw "Atomic copy source SHA-256 mismatch."
    }
    $destinationFull = [IO.Path]::GetFullPath($Destination)
    $destinationParent = [IO.Path]::GetDirectoryName($destinationFull)
    if ([string]::IsNullOrWhiteSpace($destinationParent)) {
        $destinationParent = [IO.Path]::GetPathRoot($destinationFull)
    }
    if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    }
    $temporary = Get-WinterBreak2OwnedTempPath $Destination $ExpectedSha256 $Purpose
    if (Test-Path -LiteralPath $temporary -PathType Container) {
        throw "A directory blocks an owned WinterBreak2 temporary file."
    }
    if (Test-Path -LiteralPath $temporary -PathType Leaf) {
        $temporaryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant()
        if ($temporaryHash -ne $ExpectedSha256) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
    if (Test-Path -LiteralPath $Destination -PathType Container) {
        throw "A directory blocks a WinterBreak2 destination."
    }
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        $destinationHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant()
        if ($destinationHash -eq $ExpectedSha256) {
            if (Test-Path -LiteralPath $temporary -PathType Leaf) {
                Remove-Item -LiteralPath $temporary -Force
            }
            return
        }
    }
    if (-not (Test-Path -LiteralPath $temporary -PathType Leaf)) {
        Copy-Item -LiteralPath $Source -Destination $temporary
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant() -ne $ExpectedSha256) {
            throw "Owned WinterBreak2 temporary-file SHA-256 mismatch."
        }
    }
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        Remove-Item -LiteralPath $Destination -Force
    }
    [IO.File]::Move($temporary, $Destination)
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant() -ne $ExpectedSha256) {
        throw "WinterBreak2 atomic post-copy SHA-256 mismatch."
    }
}

function Assert-WinterBreak2PayloadReservation {
    param(
        [Parameter(Mandatory = $true)][string] $Stage,
        [Parameter(Mandatory = $true)][string] $Root
    )

    [int64]$payloadBytes = 0
    foreach ($relative in $WinterBreak2Files) {
        $payloadBytes += [int64](Get-Item -LiteralPath (Get-SafeChildPath $Stage $relative "WinterBreak2 payload reservation")).Length
    }
    if ((Get-FreeBytes $Root) - $payloadBytes -lt 50MB) {
        throw "The exact WinterBreak2 payload would cross the 50 MiB free-space floor; no device payload files were written."
    }
}

function Remove-WinterBreak2OwnedTemps {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root
    )

    foreach ($entry in @($Record.manifest.files)) {
        $temporaryRelatives = @([string]$entry.stageTemporaryRelativePath)
        if ([bool]$entry.wasPresent) {
            $temporaryRelatives += [string]$entry.restoreTemporaryRelativePath
        }
        foreach ($relative in $temporaryRelatives) {
            $temporary = Get-SafeChildPath $Root $relative "recorded WinterBreak2 temporary file"
            if (Test-Path -LiteralPath $temporary -PathType Container) {
                throw "A directory blocks deterministic WinterBreak2 temporary cleanup."
            }
            if (Test-Path -LiteralPath $temporary -PathType Leaf) {
                Remove-Item -LiteralPath $temporary -Force
            }
        }
    }
}

function Copy-WinterBreak2FromRecord {
    param(
        [Parameter(Mandatory = $true)][string] $Stage,
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root
    )

    foreach ($entry in @($Record.manifest.directories)) {
        New-Item -ItemType Directory -Path (Get-SafeChildPath $Root ([string]$entry.relativePath) "WinterBreak2 directory") -Force | Out-Null
    }
    foreach ($entry in @($Record.manifest.files)) {
        $source = Get-SafeChildPath $Stage ([string]$entry.relativePath) "WinterBreak2 source"
        $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
        if ($sourceHash -ne [string]$entry.stagedSha256) {
            throw "The extracted WinterBreak2 source changed: $($entry.relativePath)"
        }
        $destination = Get-SafeChildPath $Root ([string]$entry.relativePath) "WinterBreak2 file"
        Install-VerifiedFileAtomically $source $destination ([string]$entry.stagedSha256) "stage"
    }
}

function Assert-WinterBreak2StagedFiles {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root
    )

    foreach ($entry in @($Record.manifest.files)) {
        $destination = Get-SafeChildPath $Root ([string]$entry.relativePath) "WinterBreak2 staged file"
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant() -ne [string]$entry.stagedSha256) {
            throw "The staged WinterBreak2 file is absent or changed: $($entry.relativePath)"
        }
    }
}

function Assert-WinterBreak2Preflight {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [switch] $AllowPinnedHotfix
    )

    $info = Assert-ExactWinterBreak2Device $Root
    Assert-OriginalWinterBreakStageGuard $Root -RequireDeviceIdentity | Out-Null
    Assert-OwnedOtaFiller $Root | Out-Null
    Assert-WinterBreak2FreeSpaceGuard $Root "WinterBreak2 preflight"
    if ($AllowPinnedHotfix) {
        Assert-NoRootKindleUpdates $Root $UniversalHotfix.File
    } else {
        Assert-NoRootKindleUpdates $Root
    }
    return $info
}

function Assert-WinterBreak2FreeSpaceGuard {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)][string] $Context
    )

    $remaining = Get-FreeBytes $Root
    if ($remaining -lt 50MB -or $remaining -gt 90MB) {
        throw "$Context requires 50-90 MiB free; found $([Math]::Round($remaining / 1MB, 1)) MiB."
    }
}

function Stage-WinterBreak2 {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    $info = Assert-WinterBreak2Preflight $Root
    if ($info.jailbrokenMarker) {
        throw "documents\JAILBROKEN.txt already exists. Do not layer stock WinterBreak2 over another jailbreak state."
    }
    Assert-NoWinterBreak2ExecutionEvidence $Root
    if (Get-WinterBreak2Record "executed") {
        throw "WinterBreak2 was already verified as executed on this Kindle."
    }

    $record = Get-WinterBreak2Record "active"
    $stage = Expand-WinterBreak2
    Assert-WinterBreak2PayloadReservation $stage $Root
    if ($record) {
        Assert-WinterBreak2RecordMatchesDevice $record $Root
        if ([string]$record.manifest.status -eq "complete") {
            Assert-WinterBreak2LocalBackups $record
            Remove-WinterBreak2OwnedTemps $record $Root
            Assert-WinterBreak2StagedFiles $record $Root
            Write-Host "WinterBreak2 staging is already complete and hash-correct; the existing rollback record was retained."
            return
        }
        if ([string]$record.manifest.status -ne "prepared") {
            throw "WinterBreak2 staging cannot resume from status '$($record.manifest.status)'."
        }
        Assert-WinterBreak2LocalBackups $record
        Assert-WinterBreak2DestinationsResumable $record $Root
    } else {
        foreach ($relative in $WinterBreak2Directories) {
            $destination = Get-SafeChildPath $Root $relative "WinterBreak2 directory"
            if (Test-Path -LiteralPath $destination -PathType Leaf) {
                throw "A file blocks the WinterBreak2 directory: $relative"
            }
        }
        foreach ($relative in $WinterBreak2Files) {
            $destination = Get-SafeChildPath $Root $relative "WinterBreak2 file"
            if (Test-Path -LiteralPath $destination -PathType Container) {
                throw "A directory blocks the WinterBreak2 file: $relative"
            }
            $source = Get-SafeChildPath $stage $relative "WinterBreak2 source"
            $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
            $temporary = Get-WinterBreak2OwnedTempPath $destination $sourceHash "stage"
            if (Test-Path -LiteralPath $temporary) {
                throw "An unowned deterministic WinterBreak2 temporary path already exists: $relative"
            }
            if (Test-Path -LiteralPath $destination -PathType Leaf) {
                $originalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
                $restoreTemporary = Get-WinterBreak2OwnedTempPath $destination $originalHash "restore"
                if (Test-Path -LiteralPath $restoreTemporary) {
                    throw "An unowned deterministic WinterBreak2 restore-temporary path already exists: $relative"
                }
            }
        }

        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $recordName = "winterbreak2-stage-$ExpectedFirmware-$stamp-$([Guid]::NewGuid().ToString('N'))"
        $backupParent = Get-FullProjectPath "device-backups"
        New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
        $recordRoot = Get-SafeChildPath $backupParent $recordName "WinterBreak2 record directory"
        if (Test-Path -LiteralPath $recordRoot) {
            throw "Refusing to merge with an existing WinterBreak2 record directory: $recordRoot"
        }
        New-Item -ItemType Directory -Path $recordRoot | Out-Null
        $overwritten = Join-Path $recordRoot "overwritten"
        New-Item -ItemType Directory -Path $overwritten | Out-Null

        $directoryRecords = @()
        foreach ($relative in $WinterBreak2Directories) {
            $directoryRecords += [ordered]@{
                relativePath = $relative
                wasPresent = Test-Path -LiteralPath (Get-SafeChildPath $Root $relative "WinterBreak2 directory") -PathType Container
            }
        }
        $fileRecords = @()
        foreach ($relative in $WinterBreak2Files) {
            $source = Get-SafeChildPath $stage $relative "WinterBreak2 source"
            $destination = Get-SafeChildPath $Root $relative "WinterBreak2 file"
            $stagedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
            $wasPresent = Test-Path -LiteralPath $destination -PathType Leaf
            $originalHash = $null
            if ($wasPresent) {
                $originalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
                $backup = Get-SafeChildPath $overwritten $relative "WinterBreak2 rollback backup"
                New-Item -ItemType Directory -Path (Split-Path $backup -Parent) -Force | Out-Null
                Copy-Item -LiteralPath $destination -Destination $backup -Force
                if ((Get-FileHash -Algorithm SHA256 -LiteralPath $backup).Hash.ToLowerInvariant() -ne $originalHash) {
                    throw "WinterBreak2 rollback backup SHA-256 mismatch: $relative"
                }
            }
            $fileRecords += [ordered]@{
                relativePath = $relative
                wasPresent = $wasPresent
                originalSha256 = $originalHash
                stagedSha256 = $stagedHash
                stageTemporaryRelativePath = "$relative.lazying-art-wb2-stage-$($stagedHash.Substring(0, 16)).tmp"
                restoreTemporaryRelativePath = $(if ($wasPresent) { "$relative.lazying-art-wb2-restore-$($originalHash.Substring(0, 16)).tmp" } else { $null })
            }
        }
        $manifest = [ordered]@{
            createdAt = (Get-Date).ToString("o")
            status = "prepared"
            firmware = $ExpectedFirmware
            winterBreak2Version = $WinterBreak2.Version
            archiveSha256 = $WinterBreak2.Sha256
            deviceFingerprint = Get-KindleFingerprint $Root
            deviceIdentityHash = Get-KindleIdentityHash $Root
            deviceIdentityScheme = "windows-volume-serial-size-sha256-v1"
            kindleRootAtStageTime = $Root
            files = $fileRecords
            directories = $directoryRecords
        }
        $manifestPath = Join-Path $recordRoot "manifest.json"
        Write-ProjectJsonAtomic $manifestPath $manifest
        $pointer = Get-FullProjectPath "logs\latest-winterbreak2-stage.txt"
        if (Test-Path -LiteralPath $pointer) {
            throw "A WinterBreak2 rollback pointer appeared during staging; no device files were copied."
        }
        Write-ProjectTextAtomic $pointer $manifestPath
        $record = Get-WinterBreak2Record "active" -Require
    }

    Copy-WinterBreak2FromRecord $stage $record $Root
    Assert-WinterBreak2StagedFiles $record $Root
    Assert-WinterBreak2FreeSpaceGuard $Root "WinterBreak2 staging"
    $record.manifest.status = "complete"
    $record.manifest | Add-Member -NotePropertyName completedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    Write-ProjectJsonAtomic $record.manifestPath $record.manifest
    Write-Host "Stock WinterBreak2 v$($WinterBreak2.Version) staged with exact hashes. The Store WinterBreak stage and OTA filler remain intact."
    Write-Host "Reversible WinterBreak2 stage manifest: $($record.manifestPath)"
}

function Assert-WinterBreak2RollbackCompleteState {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root
    )

    foreach ($entry in @($Record.manifest.files)) {
        $destination = Get-SafeChildPath $Root ([string]$entry.relativePath) "completed WinterBreak2 rollback"
        if ([bool]$entry.wasPresent) {
            if (-not (Test-Path -LiteralPath $destination -PathType Leaf) -or
                (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant() -ne [string]$entry.originalSha256) {
                throw "A rolledBack WinterBreak2 record does not match its restored file state: $($entry.relativePath)"
            }
        } elseif (Test-Path -LiteralPath $destination) {
            throw "A rolledBack WinterBreak2 record still has a newly staged path: $($entry.relativePath)"
        }
    }
}

function Undo-WinterBreak2 {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    $info = Assert-ExactWinterBreak2Device $Root
    if ($info.jailbrokenMarker) {
        throw "A jailbreak marker exists. WinterBreak2 rollback is restricted to an unexecuted device."
    }
    Assert-NoWinterBreak2ExecutionEvidence $Root
    if (Get-WinterBreak2Record "executed") {
        throw "WinterBreak2 was already verified as executed; rollback is forbidden."
    }
    $record = Get-WinterBreak2Record "active" -Require
    Assert-WinterBreak2RecordMatchesDevice $record $Root
    if ([string]$record.manifest.status -notin @("prepared", "complete", "rollback-incomplete", "rolledBack")) {
        throw "WinterBreak2 cannot be rolled back from status '$($record.manifest.status)'."
    }
    Assert-WinterBreak2LocalBackups $record
    if ([string]$record.manifest.status -eq "rolledBack") {
        Assert-WinterBreak2RollbackCompleteState $record $Root
        Remove-Item -LiteralPath $record.pointerPath -Force
        Write-Host "Finalized a previously completed WinterBreak2 rollback after an interrupted pointer retirement."
        return
    }
    Remove-WinterBreak2OwnedTemps $record $Root

    foreach ($entry in @($record.manifest.files)) {
        $destination = Get-SafeChildPath $Root ([string]$entry.relativePath) "WinterBreak2 rollback destination"
        if (Test-Path -LiteralPath $destination -PathType Container) {
            throw "A directory replaced a WinterBreak2 staged file; rollback stopped before mutation: $($entry.relativePath)"
        }
    }

    $skipped = @()
    $overwritten = Join-Path (Split-Path $record.manifestPath -Parent) "overwritten"
    foreach ($entry in @($record.manifest.files)) {
        $destination = Get-SafeChildPath $Root ([string]$entry.relativePath) "WinterBreak2 rollback destination"
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
            if ([bool]$entry.wasPresent) {
                $backup = Get-SafeChildPath $overwritten ([string]$entry.relativePath) "WinterBreak2 rollback backup"
                Install-VerifiedFileAtomically $backup $destination ([string]$entry.originalSha256) "restore"
            }
            continue
        }
        $currentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ([bool]$entry.wasPresent -and $currentHash -eq [string]$entry.originalSha256) {
            continue
        }
        if ($currentHash -ne [string]$entry.stagedSha256) {
            $skipped += [string]$entry.relativePath
            continue
        }
        if ([bool]$entry.wasPresent) {
            $backup = Get-SafeChildPath $overwritten ([string]$entry.relativePath) "WinterBreak2 rollback backup"
            Install-VerifiedFileAtomically $backup $destination ([string]$entry.originalSha256) "restore"
        } else {
            Remove-Item -LiteralPath $destination -Force
        }
    }

    foreach ($entry in (@($record.manifest.directories) | Sort-Object { ([string]$_.relativePath).Length } -Descending)) {
        if ([bool]$entry.wasPresent) { continue }
        $directory = Get-SafeChildPath $Root ([string]$entry.relativePath) "WinterBreak2 rollback directory"
        if ((Test-Path -LiteralPath $directory -PathType Container) -and
            @(Get-ChildItem -LiteralPath $directory -Force).Count -eq 0) {
            Remove-Item -LiteralPath $directory -Force
        }
    }

    if ($skipped.Count -gt 0) {
        $record.manifest.status = "rollback-incomplete"
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
        Write-Warning ("Left diverged WinterBreak2 files untouched: " + ($skipped -join ", "))
    } else {
        $record.manifest.status = "rolledBack"
        $record.manifest | Add-Member -NotePropertyName rolledBackAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
        Remove-Item -LiteralPath $record.pointerPath -Force
    }
    Write-Host "WinterBreak2 staging rollback finished; the original Store stage and OTA filler were not changed."
}

function Complete-WinterBreak2Supersession {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root
    )

    if ($Record.manifest.PSObject.Properties.Name -notcontains "supersessionPlan") {
        $plan = @()
        $storeRecord = Get-RecordedManifest
        if ($storeRecord) {
            $plan += [ordered]@{ kind = "store-stage"; manifestPath = $storeRecord.manifestPath; pointerPath = $storeRecord.latestPath }
        }
        $cacheRecord = Get-StoreCacheRecord
        if ($cacheRecord) {
            $plan += [ordered]@{ kind = "store-cache"; manifestPath = $cacheRecord.manifestPath; pointerPath = $cacheRecord.latestPath }
        }
        $Record.manifest | Add-Member -NotePropertyName supersessionPlan -NotePropertyValue @($plan) -Force
        Write-ProjectJsonAtomic $Record.manifestPath $Record.manifest
    }

    $backupPrefix = (Get-FullProjectPath "device-backups").TrimEnd("\") + "\"
    $wb2Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Record.manifestPath).Hash.ToLowerInvariant()
    foreach ($entry in @($Record.manifest.supersessionPlan)) {
        $manifestPath = [IO.Path]::GetFullPath([string]$entry.manifestPath)
        if (-not $manifestPath.StartsWith($backupPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            throw "A planned Store supersession manifest is unavailable or outside device-backups."
        }
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if ([string]$manifest.deviceFingerprint -cne (Get-KindleFingerprint $Root)) {
            throw "A planned Store supersession record belongs to a different Kindle fingerprint."
        }
        if ([string]$entry.kind -eq "store-stage") {
            if ([string]$manifest.deviceIdentityHash -cne (Get-KindleIdentityHash $Root)) {
                throw "The Store-stage supersession record belongs to a different stable device identity."
            }
            $allowed = @("complete", "superseded-by-winterbreak2")
        } elseif ([string]$entry.kind -eq "store-cache") {
            $allowed = @("prepared", "complete", "superseded-by-winterbreak2")
        } else {
            throw "The WinterBreak2 supersession plan contains an unknown record kind."
        }
        if ([string]$manifest.status -notin $allowed) {
            throw "A planned Store record cannot be superseded from status '$($manifest.status)'."
        }
        if ([string]$manifest.status -ne "superseded-by-winterbreak2") {
            $manifest.status = "superseded-by-winterbreak2"
            $manifest | Add-Member -NotePropertyName supersededAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
            $manifest | Add-Member -NotePropertyName winterBreak2ManifestPath -NotePropertyValue $Record.manifestPath -Force
            $manifest | Add-Member -NotePropertyName winterBreak2ManifestSha256AtSupersession -NotePropertyValue $wb2Hash -Force
            Write-ProjectJsonAtomic $manifestPath $manifest
        }
        $pointer = [IO.Path]::GetFullPath([string]$entry.pointerPath)
        $logsPrefix = (Get-FullProjectPath "logs").TrimEnd("\") + "\"
        if (-not $pointer.StartsWith($logsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "A planned Store supersession pointer is outside logs."
        }
        if (Test-Path -LiteralPath $pointer -PathType Leaf) {
            $pointed = [IO.Path]::GetFullPath((Get-Content -LiteralPath $pointer -Raw).Trim())
            if (-not [StringComparer]::OrdinalIgnoreCase.Equals($pointed, $manifestPath)) {
                throw "A Store pointer changed during WinterBreak2 supersession."
            }
            Remove-Item -LiteralPath $pointer -Force
        }
    }
    $Record.manifest | Add-Member -NotePropertyName supersessionCompletedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    Write-ProjectJsonAtomic $Record.manifestPath $Record.manifest
}

function Write-WinterBreak2PostExecutionWarnings {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root
    )

    try { Assert-OwnedOtaFiller $Root | Out-Null } catch { Write-Warning "Post-execution OTA filler drift requires review." }
    try { Assert-WinterBreak2FreeSpaceGuard $Root "Post-execution audit" } catch { Write-Warning "Post-execution free space is outside the 50-90 MiB guard." }
    if (@(Get-RootKindleUpdateFiles $Root).Count -gt 0) {
        Write-Warning "Post-execution root update file(s) require review before hotfix staging."
    }
    try { Assert-WinterBreak2StagedFiles $Record $Root } catch { Write-Warning "Post-execution WinterBreak2 USB payload drift was detected; execution evidence remains recorded." }
}

function Verify-WinterBreak2 {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-ExactWinterBreak2Device $Root | Out-Null
    $record = Get-WinterBreak2Record "active"
    $alreadyExecuted = $false
    if (-not $record) {
        $record = Get-WinterBreak2Record "executed" -Require
        $alreadyExecuted = $true
    } else {
        if ([string]$record.manifest.status -notin @("complete", "executed")) {
            throw "WinterBreak2 verification requires a complete stage record, not '$($record.manifest.status)'."
        }
    }
    Assert-WinterBreak2RecordMatchesDevice $record $Root
    $logHash = Assert-WinterBreak2SuccessLog $Root

    if ($alreadyExecuted) {
        if ([string]$record.manifest.winterBreakLogSha256 -cne $logHash) {
            throw "winterbreak.log changed after the executed record was verified."
        }
    } else {
        $record.manifest.status = "executed"
        $record.manifest | Add-Member -NotePropertyName verifiedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
        $record.manifest | Add-Member -NotePropertyName winterBreakLogSha256 -NotePropertyValue $logHash -Force
        $record.manifest | Add-Member -NotePropertyName verifiedEvidence -NotePropertyValue @($WinterBreak2SuccessEvidence) -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
        Publish-WinterBreak2ExecutedRecord $record
    }
    Complete-WinterBreak2Supersession $record $Root
    Write-WinterBreak2PostExecutionWarnings $record $Root
    if ($alreadyExecuted) {
        Write-Host "WinterBreak2 was already verified; its executed audit and Store-route supersession records are complete."
    } else {
        Write-Host "Stock WinterBreak2 execution was recorded before drift checks. No JAILBROKEN.txt marker was used."
    }
}

function Stage-UniversalHotfix {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    Assert-ExactWinterBreak2Device $Root | Out-Null
    $record = Get-WinterBreak2Record "executed" -Require
    Assert-WinterBreak2RecordMatchesDevice $record $Root
    if ([string]$record.manifest.verifiedAt -eq "" -or
        [string]$record.manifest.winterBreakLogSha256 -notmatch "^[0-9a-f]{64}$") {
        throw "StageHotfix requires a WinterBreak2 record finalized by VerifyWinterBreak2."
    }
    $logHash = Assert-WinterBreak2SuccessLog $Root
    if ([string]$record.manifest.winterBreakLogSha256 -cne $logHash) {
        throw "winterbreak.log changed after VerifyWinterBreak2; hotfix staging stopped."
    }
    Assert-OwnedOtaFiller $Root | Out-Null
    Assert-WinterBreak2FreeSpaceGuard $Root "Universal Hotfix preflight"
    Assert-NoRootKindleUpdates $Root $UniversalHotfix.File

    $destination = Get-SafeChildPath $Root $UniversalHotfix.File "Universal Hotfix destination"
    if (Test-Path -LiteralPath $destination -PathType Container) {
        throw "A directory blocks the Universal Hotfix destination."
    }
    $existingUpdates = @(Get-RootKindleUpdateFiles $Root)
    foreach ($update in $existingUpdates) {
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($update.Name, $UniversalHotfix.File)) {
            throw "Another root-level update file blocks Universal Hotfix staging: $($update.Name)"
        }
    }

    $downloads = Get-FullProjectPath "downloads"
    $source = Invoke-VerifiedDownload `
        $UniversalHotfix.Url `
        (Join-Path $downloads $UniversalHotfix.File) `
        $UniversalHotfix.Sha256
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($existingHash -ne $UniversalHotfix.Sha256) {
            throw "The existing Update_hotfix_universal.bin does not match the pinned package; it was not overwritten."
        }
        Write-Host "The pinned Universal Hotfix is already staged and hash-correct."
    } else {
        if ((Get-FreeBytes $Root) - [int64](Get-Item -LiteralPath $source).Length -lt 50MB) {
            throw "Copying the Universal Hotfix would cross the 50 MiB free-space floor."
        }
        $temporary = Get-WinterBreak2OwnedTempPath $destination $UniversalHotfix.Sha256 "stage"
        if ([string]$record.manifest.hotfixStageStatus -ne "prepared" -and (Test-Path -LiteralPath $temporary)) {
            throw "An unowned Universal Hotfix temporary path already exists."
        }
        $record.manifest | Add-Member -NotePropertyName hotfixStageStatus -NotePropertyValue "prepared" -Force
        $record.manifest | Add-Member -NotePropertyName hotfixTemporaryName -NotePropertyValue (Split-Path $temporary -Leaf) -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
        Install-VerifiedFileAtomically $source $destination $UniversalHotfix.Sha256 "stage"
        Write-Host "Staged Universal Hotfix v$($UniversalHotfix.Version) with its pinned SHA-256."
    }
    Assert-WinterBreak2FreeSpaceGuard $Root "Universal Hotfix staging"
    Assert-OwnedOtaFiller $Root | Out-Null
    $record.manifest | Add-Member -NotePropertyName hotfixStagedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    $record.manifest | Add-Member -NotePropertyName hotfixSha256 -NotePropertyValue $UniversalHotfix.Sha256 -Force
    $record.manifest | Add-Member -NotePropertyName hotfixStageStatus -NotePropertyValue "complete" -Force
    Write-ProjectJsonAtomic $record.manifestPath $record.manifest
    Write-Host "The OTA filler remains in place. Safely eject, then install the update from Kindle Settings."
}

function New-CryptographicLowerHex32 {
    $bytes = New-Object byte[] 16
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return ([BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
}

function Assert-ExactUtf8FileContent {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string] $ExpectedContent,
        [Parameter(Mandatory = $true)][string] $Purpose
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "The $Purpose is missing."
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "The $Purpose must not be a reparse point."
    }
    $encoding = New-Object Text.UTF8Encoding($false)
    $expected = $encoding.GetBytes($ExpectedContent)
    $actual = [IO.File]::ReadAllBytes($item.FullName)
    if ($actual.Length -ne $expected.Length) {
        throw "The $Purpose does not have the exact expected UTF-8 bytes."
    }
    for ($index = 0; $index -lt $expected.Length; $index++) {
        if ($actual[$index] -ne $expected[$index]) {
            throw "The $Purpose does not have the exact expected UTF-8 bytes."
        }
    }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $item.FullName).Hash.ToLowerInvariant()
}

function Get-RenderedHotfixProbeContent {
    param([Parameter(Mandatory = $true)][string] $Nonce)

    if ($Nonce -notmatch "^[0-9a-f]{32}$") {
        throw "The hotfix probe nonce must be exactly 32 lowercase hexadecimal characters."
    }
    $templatePath = Get-FullProjectPath $HotfixProbe.TemplateRelativePath
    if (-not (Test-Path -LiteralPath $templatePath -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $templatePath).Hash.ToLowerInvariant() -cne [string]$HotfixProbe.TemplateSha256) {
        throw "The hotfix verification template does not match its pinned SHA-256."
    }
    $strictUtf8 = New-Object Text.UTF8Encoding($false, $true)
    $template = [IO.File]::ReadAllText($templatePath, $strictUtf8)
    $token = [string]$HotfixProbe.NonceToken
    $first = $template.IndexOf($token, [StringComparison]::Ordinal)
    if ($first -lt 0 -or $template.IndexOf($token, $first + $token.Length, [StringComparison]::Ordinal) -ge 0) {
        throw "The pinned hotfix template must contain its nonce token exactly once."
    }
    $rendered = $template.Substring(0, $first) + $Nonce + $template.Substring($first + $token.Length)
    if ($rendered.Contains("`r") -or $rendered.IndexOf($token, [StringComparison]::Ordinal) -ge 0) {
        throw "The rendered hotfix probe is not canonical LF text or still contains its token."
    }
    return $rendered
}

function Replace-ExactTextOnce {
    param(
        [Parameter(Mandatory = $true)][string] $Content,
        [Parameter(Mandatory = $true)][string] $Needle,
        [Parameter(Mandatory = $true)][string] $Replacement,
        [Parameter(Mandatory = $true)][string] $Purpose
    )

    $first = $Content.IndexOf($Needle, [StringComparison]::Ordinal)
    if ($first -lt 0 -or $Content.IndexOf($Needle, $first + $Needle.Length, [StringComparison]::Ordinal) -ge 0) {
        throw "The pinned hotfix template does not contain exactly one $Purpose insertion point."
    }
    return $Content.Substring(0, $first) + $Replacement + $Content.Substring($first + $Needle.Length)
}

function Get-RenderedHotfixDiagnosticContent {
    param([Parameter(Mandatory = $true)][string] $Nonce)

    $content = Get-RenderedHotfixProbeContent $Nonce
    $content = Replace-ExactTextOnce `
        $content `
        "RESULT=`"/mnt/us/documents/HOTFIX_VERIFIED_LAZYING_ART.txt`"`nTMP=`"`"" `
        "RESULT=`"/mnt/us/documents/HOTFIX_VERIFIED_LAZYING_ART.txt`"`nDIAGNOSTIC=`"/mnt/us/documents/HOTFIX_DIAGNOSTIC_LAZYING_ART.txt`"`nTMP=`"`"`nDIAGNOSTIC_TMP=`"`"" `
        "diagnostic path"
    $oldCleanup = @'
cleanup()
{
    if [ -n "$TMP" ] && { [ -e "$TMP" ] || [ -L "$TMP" ]; }; then
        rm -f "$TMP"
    fi
}
'@
    $newCleanup = @'
cleanup()
{
    if [ -n "$TMP" ] && { [ -e "$TMP" ] || [ -L "$TMP" ]; }; then
        rm -f "$TMP"
    fi
    if [ -n "$DIAGNOSTIC_TMP" ] && { [ -e "$DIAGNOSTIC_TMP" ] || [ -L "$DIAGNOSTIC_TMP" ]; }; then
        rm -f "$DIAGNOSTIC_TMP"
    fi
}
'@
    $content = Replace-ExactTextOnce $content $oldCleanup $newCleanup "diagnostic cleanup"
    $oldFail = @'
fail()
{
    show_message "Hotfix verify failed: $1"
    exit 1
}
'@
    $newFail = @'
write_diagnostic()
{
    case "$1" in
        "uid") REASON="UID" ;;
        "nonce") REASON="NONCE" ;;
        "documents") REASON="DOCUMENTS" ;;
        "result exists") REASON="RESULT_EXISTS" ;;
        "essentials") REASON="ESSENTIALS" ;;
        "version") REASON="VERSION" ;;
        "keystore") REASON="KEYSTORE" ;;
        "kindlet") REASON="KINDLET" ;;
        "update key") REASON="UPDATE_KEY" ;;
        "debug hook") REASON="DEBUG_HOOK" ;;
        "start log") REASON="START_LOG" ;;
        "completion log") REASON="COMPLETION_LOG" ;;
        "job log") REASON="JOB_LOG" ;;
        "temporary file") REASON="TEMPORARY_FILE" ;;
        "write") REASON="WRITE" ;;
        "sync") REASON="SYNC" ;;
        "result appeared") REASON="RESULT_APPEARED" ;;
        "rename") REASON="RENAME" ;;
        *) REASON="INTERNAL" ;;
    esac
    if [ -e "$RESULT" ] || [ -L "$RESULT" ] || [ ! -d "/mnt/us/documents" ] || [ ! -w "/mnt/us/documents" ]; then
        return 0
    fi
    if [ -e "$DIAGNOSTIC" ] || [ -L "$DIAGNOSTIC" ]; then
        return 0
    fi
    DIAGNOSTIC_TMP="${DIAGNOSTIC}.tmp.$$"
    if [ -e "$DIAGNOSTIC_TMP" ] || [ -L "$DIAGNOSTIC_TMP" ]; then
        DIAGNOSTIC_TMP=""
        return 0
    fi
    (
        umask 077
        set -C
        printf '%s\n' \
            "kindle-hotfix-diagnostic-v1" \
            "nonce=$NONCE" \
            "hotfix=2.5.0" \
            "reason=$REASON" > "$DIAGNOSTIC_TMP"
    ) || {
        rm -f "$DIAGNOSTIC_TMP" >/dev/null 2>&1 || true
        DIAGNOSTIC_TMP=""
        return 0
    }
    sync >/dev/null 2>&1 || {
        rm -f "$DIAGNOSTIC_TMP" >/dev/null 2>&1 || true
        DIAGNOSTIC_TMP=""
        return 0
    }
    if [ -e "$DIAGNOSTIC" ] || [ -L "$DIAGNOSTIC" ]; then
        rm -f "$DIAGNOSTIC_TMP" >/dev/null 2>&1 || true
        DIAGNOSTIC_TMP=""
        return 0
    fi
    mv "$DIAGNOSTIC_TMP" "$DIAGNOSTIC" >/dev/null 2>&1 || {
        rm -f "$DIAGNOSTIC_TMP" >/dev/null 2>&1 || true
        DIAGNOSTIC_TMP=""
        return 0
    }
    DIAGNOSTIC_TMP=""
    sync >/dev/null 2>&1 || true
}

fail()
{
    write_diagnostic "$1"
    show_message "Hotfix diagnostic failed."
    exit 1
}
'@
    $content = Replace-ExactTextOnce $content $oldFail $newFail "diagnostic failure handler"
    $existingResultGate = @'
if [ -e "$RESULT" ] || [ -L "$RESULT" ]; then
    fail "result exists"
fi
'@
    $exclusiveResultGate = @'
if [ -e "$RESULT" ] || [ -L "$RESULT" ]; then
    fail "result exists"
fi
if [ -e "$DIAGNOSTIC" ] || [ -L "$DIAGNOSTIC" ]; then
    show_message "Hotfix diagnostic result already exists."
    exit 1
fi
'@
    $content = Replace-ExactTextOnce $content $existingResultGate $exclusiveResultGate "diagnostic exclusivity gate"
    if ($content.Contains("`r")) {
        throw "The rendered hotfix diagnostic is not canonical LF text."
    }
    return $content
}

function Get-ExpectedHotfixProbeResultContent {
    param([Parameter(Mandatory = $true)][string] $Nonce)

    if ($Nonce -notmatch "^[0-9a-f]{32}$") {
        throw "The recorded hotfix probe nonce is invalid."
    }
    return "kindle-hotfix-evidence-v1`nnonce=$Nonce`nhotfix=$($UniversalHotfix.Version)`nrunner=complete`n"
}

function Get-ExpectedHotfixDiagnosticContent {
    param(
        [Parameter(Mandatory = $true)][string] $Nonce,
        [Parameter(Mandatory = $true)][string] $ReasonCode
    )

    if ($Nonce -notmatch "^[0-9a-f]{32}$" -or $ReasonCode -cnotin $HotfixDiagnosticReasonCodes) {
        throw "The hotfix diagnostic nonce or reason code is invalid."
    }
    return "kindle-hotfix-diagnostic-v1`nnonce=$Nonce`nhotfix=$($UniversalHotfix.Version)`nreason=$ReasonCode`n"
}

function Get-Utf8ContentSha256 {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string] $Content)

    $encoding = New-Object Text.UTF8Encoding($false)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash($encoding.GetBytes($Content))
    } finally {
        $sha.Dispose()
    }
    return ([BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
}

function Assert-HotfixDiagnosticRecordFields {
    param([Parameter(Mandatory = $true)] $Record)

    $manifest = $Record.manifest
    $names = @($manifest.PSObject.Properties.Name)
    $diagnosticFields = @(
        "diagnosticStatus", "diagnosticRelativePath",
        "diagnosticResultRelativePath", "diagnosticTransformVersion",
        "diagnosticSha256", "diagnosticReasonSetSha256"
    )
    if (@($diagnosticFields | Where-Object { $_ -in $names }).Count -eq 0) {
        return
    }
    foreach ($required in $diagnosticFields) {
        if ($required -notin $names) {
            throw "The hotfix diagnostic record is only partially defined."
        }
    }
    $reasonSetHash = Get-Utf8ContentSha256 (($HotfixDiagnosticReasonCodes -join "`n") + "`n")
    if ([string]$manifest.diagnosticStatus -notin @("prepared", "staged", "failed") -or
        [string]$manifest.diagnosticRelativePath -cne [string]$HotfixProbe.DiagnosticRelativePath -or
        [string]$manifest.diagnosticResultRelativePath -cne [string]$HotfixProbe.DiagnosticResultRelativePath -or
        [int]$manifest.diagnosticTransformVersion -ne [int]$HotfixProbe.DiagnosticTransformVersion -or
        [string]$manifest.diagnosticSha256 -notmatch "^[0-9a-f]{64}$" -or
        [string]$manifest.diagnosticReasonSetSha256 -cne $reasonSetHash) {
        throw "The hotfix diagnostic record has an invalid shape or pin set."
    }
    $canonical = Get-RenderedHotfixDiagnosticContent ([string]$manifest.nonce)
    $canonicalHash = Get-Utf8ContentSha256 $canonical
    $localPath = Join-Path (Split-Path $Record.manifestPath -Parent) "Diagnose Hotfix.sh"
    if ([string]$manifest.diagnosticSha256 -cne $canonicalHash -or
        (Assert-ExactUtf8FileContent $localPath $canonical "locally recorded hotfix diagnostic script") -cne $canonicalHash) {
        throw "The hotfix diagnostic script differs from its canonical nonce-bound content."
    }
    if ([string]$manifest.diagnosticStatus -eq "failed") {
        if ([string]$manifest.diagnosticReasonCode -cnotin $HotfixDiagnosticReasonCodes -or
            [string]$manifest.diagnosticResultSha256 -notmatch "^[0-9a-f]{64}$" -or
            [string]::IsNullOrWhiteSpace([string]$manifest.diagnosticReadAt)) {
            throw "The failed hotfix diagnostic record lacks exact failure evidence."
        }
    }
}

function Get-HotfixProofMode {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [switch] $Require
    )

    $names = @($Record.manifest.PSObject.Properties.Name)
    if ("proofMode" -notin $names) {
        if ($Require) {
            throw "The hotfix proof record does not declare an accepted proof mode."
        }
        return $null
    }
    $mode = [string]$Record.manifest.proofMode
    if ($mode -cnotin $HotfixProofModes) {
        throw "The hotfix proof record declares an unsupported proof mode."
    }
    return $mode
}

function Assert-HotfixProofModeFields {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [ValidateSet("active", "verified")]
        [string] $Kind
    )

    $manifest = $Record.manifest
    $names = @($manifest.PSObject.Properties.Name)
    $mode = Get-HotfixProofMode $Record
    if (-not $mode) {
        if ($Kind -eq "verified" -or [string]$manifest.status -eq "verified") {
            throw "The verified hotfix record lacks an explicit proof mode."
        }
        return
    }
    foreach ($required in @("proofAcceptedAt", "historyEvidence", "historicalJobSequenceVerified")) {
        if ($required -notin $names) {
            throw "The hotfix proof-mode record is only partially defined."
        }
    }
    if ([string]::IsNullOrWhiteSpace([string]$manifest.proofAcceptedAt) -or
        $manifest.historicalJobSequenceVerified -isnot [bool]) {
        throw "The hotfix proof-mode record has invalid evidence metadata."
    }
    if ($mode -eq "full-history-v1") {
        if ([string]$manifest.status -cne "verified" -or
            [string]$manifest.historyEvidence -cne "verified" -or
            $manifest.historicalJobSequenceVerified -ne $true -or
            [string]$manifest.resultSha256 -notmatch "^[0-9a-f]{64}$" -or
            [string]::IsNullOrWhiteSpace([string]$manifest.verifiedAt)) {
            throw "The full-history hotfix proof has invalid evidence fields."
        }
        return
    }
    if ([string]$manifest.status -cne "staged" -or
        [string]$manifest.historyEvidence -cne "log-unavailable" -or
        $manifest.historicalJobSequenceVerified -ne $false -or
        [string]$manifest.diagnosticStatus -cne "failed" -or
        [string]$manifest.diagnosticReasonCode -cne "START_LOG" -or
        [string]$manifest.diagnosticResultSha256 -notmatch "^[0-9a-f]{64}$" -or
        "verifiedAt" -in $names -or "resultSha256" -in $names) {
        throw "The persistent-state hotfix proof has invalid or overstated evidence fields."
    }
}

function Assert-CompletedHotfixUsbPrestate {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)] $WinterBreakRecord,
        [switch] $AllowVerifiedFillerRemoval
    )

    Assert-WinterBreak2RecordMatchesDevice $WinterBreakRecord $Root
    if ([string]$WinterBreakRecord.manifest.status -cne "executed" -or
        [string]$WinterBreakRecord.manifest.verifiedAt -eq "" -or
        [string]$WinterBreakRecord.manifest.winterBreakLogSha256 -notmatch "^[0-9a-f]{64}$") {
        throw "Hotfix proof requires an executed WinterBreak2 record finalized by VerifyWinterBreak2."
    }
    $logHash = Assert-WinterBreak2SuccessLog $Root
    if ([string]$WinterBreakRecord.manifest.winterBreakLogSha256 -cne $logHash) {
        throw "winterbreak.log changed after VerifyWinterBreak2; hotfix proof stopped."
    }
    if ([string]$WinterBreakRecord.manifest.hotfixStageStatus -cne "complete" -or
        [string]$WinterBreakRecord.manifest.hotfixSha256 -cne [string]$UniversalHotfix.Sha256 -or
        [string]::IsNullOrWhiteSpace([string]$WinterBreakRecord.manifest.hotfixStagedAt)) {
        throw "Hotfix proof requires a completed StageHotfix record for the pinned package."
    }
    $rootHotfix = Get-SafeChildPath $Root $UniversalHotfix.File "consumed Universal Hotfix package"
    if (Test-Path -LiteralPath $rootHotfix) {
        throw "The root Universal Hotfix package was not consumed by Update Your Kindle."
    }
    Assert-NoRootKindleUpdates $Root
    $runner = Get-SafeChildPath $Root $HotfixProbe.RunnerRelativePath "Run Hotfix booklet marker"
    Assert-ExactUtf8FileContent $runner $HotfixProbe.RunnerContent "Run Hotfix booklet marker" | Out-Null
    if (-not $AllowVerifiedFillerRemoval) {
        Assert-OwnedOtaFiller $Root | Out-Null
        Assert-WinterBreak2FreeSpaceGuard $Root "Hotfix proof preflight"
    }
}

function Assert-HotfixProbeRecordShape {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [ValidateSet("active", "verified")]
        [string] $Kind
    )

    $manifest = $Record.manifest
    $validStatuses = if ($Kind -eq "verified") { @("staged", "verified") } else { @("prepared", "staged", "verified") }
    if ([int]$manifest.schemaVersion -ne 1 -or
        [string]$manifest.status -notin $validStatuses -or
        [string]$manifest.runId -notmatch "^[0-9a-f]{32}$" -or
        [string]$manifest.nonce -notmatch "^[0-9a-f]{32}$" -or
        [string]$manifest.firmware -cne $ExpectedFirmware -or
        [string]$manifest.hotfixVersion -cne [string]$UniversalHotfix.Version -or
        [string]$manifest.hotfixPackageSha256 -cne [string]$UniversalHotfix.Sha256 -or
        [string]$manifest.templateSha256 -cne [string]$HotfixProbe.TemplateSha256 -or
        [string]$manifest.probeRelativePath -cne [string]$HotfixProbe.ProbeRelativePath -or
        [string]$manifest.resultRelativePath -cne [string]$HotfixProbe.ResultRelativePath -or
        [string]$manifest.runnerRelativePath -cne [string]$HotfixProbe.RunnerRelativePath -or
        [string]$manifest.probeSha256 -notmatch "^[0-9a-f]{64}$" -or
        [string]$manifest.expectedResultSha256 -notmatch "^[0-9a-f]{64}$" -or
        [string]$manifest.deviceFingerprint -notmatch "^[0-9a-f]{64}$" -or
        [string]$manifest.deviceIdentityHash -notmatch "^[0-9a-f]{64}$" -or
        [string]$manifest.winterBreak2ManifestSha256 -notmatch "^[0-9a-f]{64}$") {
        throw "The hotfix probe record has an invalid shape or pin set."
    }
    $backupPrefix = (Get-FullProjectPath "device-backups").TrimEnd("\") + "\"
    $wb2Path = [IO.Path]::GetFullPath([string]$manifest.winterBreak2ManifestPath)
    if (-not $wb2Path.StartsWith($backupPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path $wb2Path -Leaf) -cne "manifest.json" -or
        -not (Test-Path -LiteralPath $wb2Path -PathType Leaf)) {
        throw "The hotfix probe record points to an invalid WinterBreak2 manifest."
    }
    $canonicalProbe = Get-RenderedHotfixProbeContent ([string]$manifest.nonce)
    $canonicalProbeHash = Get-Utf8ContentSha256 $canonicalProbe
    $canonicalResultHash = Get-Utf8ContentSha256 (Get-ExpectedHotfixProbeResultContent ([string]$manifest.nonce))
    if ([string]$manifest.probeSha256 -cne $canonicalProbeHash -or
        [string]$manifest.expectedResultSha256 -cne $canonicalResultHash) {
        throw "The hotfix probe record hashes do not match canonical nonce-bound content."
    }
    $rendered = Join-Path (Split-Path $Record.manifestPath -Parent) "Verify Hotfix.sh"
    if ((Assert-ExactUtf8FileContent $rendered $canonicalProbe "locally recorded hotfix probe script") -cne $canonicalProbeHash) {
        throw "The locally recorded hotfix probe script is missing or changed."
    }
    Assert-HotfixDiagnosticRecordFields $Record
    Assert-HotfixProofModeFields $Record $Kind
}

function Get-HotfixProbeRecord {
    param(
        [ValidateSet("active", "verified")]
        [string] $Kind = "active",
        [switch] $Require
    )

    $pointer = Get-FullProjectPath $(if ($Kind -eq "active") { "logs\latest-hotfix-probe.txt" } else { "logs\latest-hotfix-verified.txt" })
    if (-not (Test-Path -LiteralPath $pointer -PathType Leaf)) {
        if ($Require) { throw "No local hotfix probe $Kind record was found." }
        return $null
    }
    $manifestPath = [IO.Path]::GetFullPath((Get-Content -LiteralPath $pointer -Raw).Trim())
    $backupPrefix = (Get-FullProjectPath "device-backups").TrimEnd("\") + "\"
    if (-not $manifestPath.StartsWith($backupPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path $manifestPath -Leaf) -cne "manifest.json" -or
        -not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "The hotfix probe pointer does not name a valid ignored manifest."
    }
    $record = [ordered]@{
        pointerPath = $pointer
        manifestPath = $manifestPath
        manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    }
    Assert-HotfixProbeRecordShape $record $Kind
    return $record
}

function Assert-HotfixProbeRecordMatchesDevice {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)] $WinterBreakRecord
    )

    Assert-HotfixProbeRecordShape $Record $(if (Get-HotfixProofMode $Record) { "verified" } else { "active" })
    if ([string]$Record.manifest.deviceFingerprint -cne (Get-KindleFingerprint $Root) -or
        [string]$Record.manifest.deviceIdentityHash -cne (Get-KindleIdentityHash $Root)) {
        throw "The connected Kindle does not match the hotfix probe record."
    }
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals(
            [IO.Path]::GetFullPath([string]$Record.manifest.winterBreak2ManifestPath),
            [IO.Path]::GetFullPath($WinterBreakRecord.manifestPath)
        ) -or
        [string]$Record.manifest.winterBreak2ManifestSha256 -cne
            (Get-FileHash -Algorithm SHA256 -LiteralPath $WinterBreakRecord.manifestPath).Hash.ToLowerInvariant()) {
        throw "The hotfix probe record does not match the executed WinterBreak2 audit record."
    }
}

function Publish-HotfixVerifiedRecord {
    param([Parameter(Mandatory = $true)] $Record)

    $verifiedPointer = Get-FullProjectPath "logs\latest-hotfix-verified.txt"
    if (Test-Path -LiteralPath $verifiedPointer -PathType Leaf) {
        $existing = [IO.Path]::GetFullPath((Get-Content -LiteralPath $verifiedPointer -Raw).Trim())
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($existing, $Record.manifestPath)) {
            throw "A different verified hotfix record already exists."
        }
    } else {
        Write-ProjectTextAtomic $verifiedPointer $Record.manifestPath
    }
    $activePointer = Get-FullProjectPath "logs\latest-hotfix-probe.txt"
    if (Test-Path -LiteralPath $activePointer -PathType Leaf) {
        $active = [IO.Path]::GetFullPath((Get-Content -LiteralPath $activePointer -Raw).Trim())
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($active, $Record.manifestPath)) {
            throw "The active hotfix probe pointer changed while finalizing verification."
        }
        Remove-Item -LiteralPath $activePointer -Force
    }
}

function Stage-HotfixProbe {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    Assert-ExactWinterBreak2Device $Root | Out-Null
    if (Get-HotfixProbeRecord "verified") {
        throw "Universal Hotfix is already verified for this recorded device."
    }
    $wb2 = Get-WinterBreak2Record "executed" -Require
    Assert-CompletedHotfixUsbPrestate $Root $wb2
    $record = Get-HotfixProbeRecord "active"
    $probeDestination = Get-SafeChildPath $Root $HotfixProbe.ProbeRelativePath "hotfix probe document"
    $resultDestination = Get-SafeChildPath $Root $HotfixProbe.ResultRelativePath "hotfix probe result"

    if (-not $record) {
        if (Test-Path -LiteralPath $resultDestination) {
            throw "A hotfix verification result existed before this nonce was staged; it was not trusted or removed."
        }
        if (Test-Path -LiteralPath $probeDestination) {
            throw "An unrecorded Verify Hotfix document already exists; it was not overwritten."
        }
        $runId = New-CryptographicLowerHex32
        $nonce = New-CryptographicLowerHex32
        $renderedContent = Get-RenderedHotfixProbeContent $nonce
        $recordName = "hotfix-probe-$ExpectedFirmware-$((Get-Date).ToString('yyyyMMdd-HHmmss'))-$runId"
        $recordRoot = Get-FullProjectPath ("device-backups\" + $recordName)
        if (Test-Path -LiteralPath $recordRoot) {
            throw "The planned hotfix probe record directory already exists."
        }
        New-Item -ItemType Directory -Path $recordRoot | Out-Null
        $renderedPath = Join-Path $recordRoot "Verify Hotfix.sh"
        Write-ProjectTextAtomic $renderedPath $renderedContent
        $probeSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $renderedPath).Hash.ToLowerInvariant()
        $manifest = [ordered]@{
            schemaVersion = 1
            status = "prepared"
            runId = $runId
            createdAt = (Get-Date).ToString("o")
            firmware = $ExpectedFirmware
            hotfixVersion = $UniversalHotfix.Version
            hotfixPackageSha256 = $UniversalHotfix.Sha256
            templateSha256 = $HotfixProbe.TemplateSha256
            nonce = $nonce
            probeRelativePath = $HotfixProbe.ProbeRelativePath
            resultRelativePath = $HotfixProbe.ResultRelativePath
            runnerRelativePath = $HotfixProbe.RunnerRelativePath
            probeSha256 = $probeSha
            expectedResultSha256 = Get-Utf8ContentSha256 (Get-ExpectedHotfixProbeResultContent $nonce)
            deviceFingerprint = Get-KindleFingerprint $Root
            deviceIdentityHash = Get-KindleIdentityHash $Root
            winterBreak2ManifestPath = $wb2.manifestPath
            winterBreak2ManifestSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $wb2.manifestPath).Hash.ToLowerInvariant()
        }
        $manifestPath = Join-Path $recordRoot "manifest.json"
        Write-ProjectJsonAtomic $manifestPath $manifest
        $pointer = Get-FullProjectPath "logs\latest-hotfix-probe.txt"
        if (Test-Path -LiteralPath $pointer) {
            throw "A hotfix probe pointer appeared during record creation; no device file was staged."
        }
        Write-ProjectTextAtomic $pointer $manifestPath
        $record = Get-HotfixProbeRecord "active" -Require
    }

    Assert-HotfixProbeRecordMatchesDevice $record $Root $wb2
    if ([string]$record.manifest.status -eq "verified") {
        throw "The hotfix probe record is already verified; use VerifyHotfix to finalize its pointer."
    }
    $renderedPath = Join-Path (Split-Path $record.manifestPath -Parent) "Verify Hotfix.sh"
    $resultExists = Test-Path -LiteralPath $resultDestination
    if (Test-Path -LiteralPath $probeDestination -PathType Container) {
        throw "A directory blocks the hotfix probe document."
    }
    if (Test-Path -LiteralPath $probeDestination -PathType Leaf) {
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $probeDestination).Hash.ToLowerInvariant() -cne [string]$record.manifest.probeSha256) {
            throw "The existing Verify Hotfix document differs from the active probe record."
        }
    } else {
        if ($resultExists) {
            throw "A hotfix result exists while its recorded probe document is absent; nothing was replaced."
        }
        Install-VerifiedFileAtomically $renderedPath $probeDestination ([string]$record.manifest.probeSha256) "stage"
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $probeDestination).Hash.ToLowerInvariant() -cne [string]$record.manifest.probeSha256) {
        throw "The staged Verify Hotfix document failed its final SHA-256 check."
    }
    if ([string]$record.manifest.status -eq "prepared") {
        $record.manifest.status = "staged"
        $record.manifest | Add-Member -NotePropertyName stagedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
    }
    if ($resultExists) {
        throw "The hotfix result is present and the staged state was reconciled. Run VerifyHotfix."
    }
    Write-Host "Staged one nonce-bound Verify Hotfix document. Safely eject and open it once from the Kindle library."
}

function Get-ExactHotfixDiagnosticFailure {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Nonce
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "The hotfix diagnostic result is absent; run Diagnose Hotfix on the Kindle first."
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $item.Length -gt 512) {
        throw "The hotfix diagnostic result is not a small regular file."
    }
    $actual = [IO.File]::ReadAllBytes($item.FullName)
    $encoding = New-Object Text.UTF8Encoding($false)
    foreach ($code in $HotfixDiagnosticReasonCodes) {
        $expected = $encoding.GetBytes((Get-ExpectedHotfixDiagnosticContent $Nonce $code))
        if ($actual.Length -ne $expected.Length) { continue }
        $matches = $true
        for ($index = 0; $index -lt $expected.Length; $index++) {
            if ($actual[$index] -ne $expected[$index]) {
                $matches = $false
                break
            }
        }
        if ($matches) {
            return [ordered]@{
                reasonCode = $code
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $item.FullName).Hash.ToLowerInvariant()
            }
        }
    }
    throw "The hotfix diagnostic result does not match any exact nonce-bound allowlisted failure record."
}

function Stage-HotfixDiagnostic {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    Assert-ExactWinterBreak2Device $Root | Out-Null
    if (Get-HotfixProbeRecord "verified") {
        throw "Universal Hotfix is already verified; no diagnostic is staged."
    }
    $wb2 = Get-WinterBreak2Record "executed" -Require
    Assert-CompletedHotfixUsbPrestate $Root $wb2
    $record = Get-HotfixProbeRecord "active" -Require
    Assert-HotfixProbeRecordMatchesDevice $record $Root $wb2
    if ([string]$record.manifest.status -cne "staged") {
        throw "StageHotfixDiagnostic requires the original hotfix probe to be fully staged."
    }
    $originalProbe = Get-SafeChildPath $Root $record.manifest.probeRelativePath "original hotfix probe"
    if (-not (Test-Path -LiteralPath $originalProbe -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $originalProbe).Hash.ToLowerInvariant() -cne [string]$record.manifest.probeSha256) {
        throw "The original staged hotfix probe is missing or changed; it was not overwritten."
    }
    $success = Get-SafeChildPath $Root $record.manifest.resultRelativePath "hotfix success result"
    if (Test-Path -LiteralPath $success) {
        throw "The hotfix success result exists. Run VerifyHotfix; no diagnostic was staged."
    }
    $diagnosticResult = Get-SafeChildPath $Root $HotfixProbe.DiagnosticResultRelativePath "hotfix diagnostic result"
    $diagnosticDestination = Get-SafeChildPath $Root $HotfixProbe.DiagnosticRelativePath "hotfix diagnostic document"
    $fieldNames = @($record.manifest.PSObject.Properties.Name)
    if ("diagnosticStatus" -notin $fieldNames) {
        if (Test-Path -LiteralPath $diagnosticResult) {
            throw "An unrecorded hotfix diagnostic result already exists; it was not trusted or removed."
        }
        if (Test-Path -LiteralPath $diagnosticDestination) {
            throw "An unrecorded Diagnose Hotfix document already exists; it was not overwritten."
        }
        $content = Get-RenderedHotfixDiagnosticContent ([string]$record.manifest.nonce)
        $localPath = Join-Path (Split-Path $record.manifestPath -Parent) "Diagnose Hotfix.sh"
        if (Test-Path -LiteralPath $localPath) {
            throw "An unrecorded local hotfix diagnostic script already exists."
        }
        Write-ProjectTextAtomic $localPath $content
        $record.manifest | Add-Member -NotePropertyName diagnosticStatus -NotePropertyValue "prepared" -Force
        $record.manifest | Add-Member -NotePropertyName diagnosticRelativePath -NotePropertyValue $HotfixProbe.DiagnosticRelativePath -Force
        $record.manifest | Add-Member -NotePropertyName diagnosticResultRelativePath -NotePropertyValue $HotfixProbe.DiagnosticResultRelativePath -Force
        $record.manifest | Add-Member -NotePropertyName diagnosticTransformVersion -NotePropertyValue $HotfixProbe.DiagnosticTransformVersion -Force
        $record.manifest | Add-Member -NotePropertyName diagnosticSha256 -NotePropertyValue (Get-Utf8ContentSha256 $content) -Force
        $record.manifest | Add-Member -NotePropertyName diagnosticReasonSetSha256 -NotePropertyValue (Get-Utf8ContentSha256 (($HotfixDiagnosticReasonCodes -join "`n") + "`n")) -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
        $record = Get-HotfixProbeRecord "active" -Require
    }
    Assert-HotfixDiagnosticRecordFields $record
    if ([string]$record.manifest.diagnosticStatus -eq "failed") {
        throw "The diagnostic failure was already recorded. Use ReadHotfixDiagnostic for its reason code."
    }
    $localPath = Join-Path (Split-Path $record.manifestPath -Parent) "Diagnose Hotfix.sh"
    $resultExists = Test-Path -LiteralPath $diagnosticResult
    if (Test-Path -LiteralPath $diagnosticDestination -PathType Container) {
        throw "A directory blocks the Diagnose Hotfix document."
    }
    if (Test-Path -LiteralPath $diagnosticDestination -PathType Leaf) {
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $diagnosticDestination).Hash.ToLowerInvariant() -cne [string]$record.manifest.diagnosticSha256) {
            throw "The existing Diagnose Hotfix document differs from its pinned record."
        }
    } else {
        if ($resultExists) {
            throw "A hotfix diagnostic result exists while its recorded script is absent."
        }
        Install-VerifiedFileAtomically $localPath $diagnosticDestination ([string]$record.manifest.diagnosticSha256) "stage"
    }
    if ([string]$record.manifest.diagnosticStatus -eq "prepared") {
        $record.manifest.diagnosticStatus = "staged"
        $record.manifest | Add-Member -NotePropertyName diagnosticStagedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
    }
    if ($resultExists) {
        throw "The diagnostic result is present and staged state was reconciled. Run ReadHotfixDiagnostic."
    }
    Write-Host "Staged Diagnose Hotfix without changing the original probe or nonce. Safely eject and open it once."
}

function Read-HotfixDiagnostic {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    Assert-ExactWinterBreak2Device $Root | Out-Null
    $wb2 = Get-WinterBreak2Record "executed" -Require
    Assert-CompletedHotfixUsbPrestate $Root $wb2
    $record = Get-HotfixProbeRecord "active" -Require
    Assert-HotfixProbeRecordMatchesDevice $record $Root $wb2
    Assert-HotfixDiagnosticRecordFields $record
    $success = Get-SafeChildPath $Root $record.manifest.resultRelativePath "hotfix success result"
    if (Test-Path -LiteralPath $success) {
        throw "The diagnostic produced the full success result. Run VerifyHotfix."
    }
    $diagnosticScript = Get-SafeChildPath $Root $record.manifest.diagnosticRelativePath "staged hotfix diagnostic"
    if (-not (Test-Path -LiteralPath $diagnosticScript -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $diagnosticScript).Hash.ToLowerInvariant() -cne [string]$record.manifest.diagnosticSha256) {
        throw "The staged Diagnose Hotfix document is missing or changed."
    }
    $resultPath = Get-SafeChildPath $Root $record.manifest.diagnosticResultRelativePath "hotfix diagnostic result"
    $evidence = Get-ExactHotfixDiagnosticFailure $resultPath ([string]$record.manifest.nonce)
    if ([string]$record.manifest.diagnosticStatus -ne "failed") {
        $record.manifest.diagnosticStatus = "failed"
        $record.manifest | Add-Member -NotePropertyName diagnosticReasonCode -NotePropertyValue $evidence.reasonCode -Force
        $record.manifest | Add-Member -NotePropertyName diagnosticResultSha256 -NotePropertyValue $evidence.sha256 -Force
        $record.manifest | Add-Member -NotePropertyName diagnosticReadAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
    } elseif ([string]$record.manifest.diagnosticReasonCode -cne [string]$evidence.reasonCode -or
        [string]$record.manifest.diagnosticResultSha256 -cne [string]$evidence.sha256) {
        throw "The hotfix diagnostic failure changed after it was recorded."
    }
    [ordered]@{
        status = "failed"
        reasonCode = [string]$evidence.reasonCode
        next = "Preserve the record and diagnose this allowlisted gate before any retry."
    } | ConvertTo-Json -Depth 3
}

function Accept-HotfixPersistentState {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    Assert-ExactWinterBreak2Device $Root | Out-Null
    $wb2 = Get-WinterBreak2Record "executed" -Require
    $active = Get-HotfixProbeRecord "active"
    $published = Get-HotfixProbeRecord "verified"
    if ($active -and $published -and
        -not [StringComparer]::OrdinalIgnoreCase.Equals($active.manifestPath, $published.manifestPath)) {
        throw "The active and verified hotfix pointers name different records."
    }
    $record = if ($published) { $published } elseif ($active) { $active } else {
        throw "No local hotfix probe record is available for persistent-state acceptance."
    }
    $alreadyPublished = [bool]$published
    Assert-CompletedHotfixUsbPrestate $Root $wb2 -AllowVerifiedFillerRemoval:$alreadyPublished
    Assert-HotfixProbeRecordMatchesDevice $record $Root $wb2

    $mode = Get-HotfixProofMode $record
    if ($mode -eq "full-history-v1") {
        throw "A stronger full-history hotfix proof is already published; it was not downgraded."
    }
    if ([string]$record.manifest.status -cne "staged" -or
        [string]$record.manifest.diagnosticStatus -cne "failed" -or
        [string]$record.manifest.diagnosticReasonCode -cne "START_LOG") {
        throw "Persistent-state acceptance requires the exact recorded START_LOG diagnostic from a staged probe."
    }

    $probe = Get-SafeChildPath $Root $record.manifest.probeRelativePath "staged hotfix probe"
    if (-not (Test-Path -LiteralPath $probe -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $probe).Hash.ToLowerInvariant() -cne [string]$record.manifest.probeSha256) {
        throw "The staged Verify Hotfix document is missing or changed."
    }
    $success = Get-SafeChildPath $Root $record.manifest.resultRelativePath "hotfix full-history result"
    if (Test-Path -LiteralPath $success) {
        throw "A full-history result conflicts with START_LOG persistent-state acceptance."
    }
    $diagnosticScript = Get-SafeChildPath $Root $record.manifest.diagnosticRelativePath "staged hotfix diagnostic"
    if (-not (Test-Path -LiteralPath $diagnosticScript -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $diagnosticScript).Hash.ToLowerInvariant() -cne [string]$record.manifest.diagnosticSha256) {
        throw "The staged Diagnose Hotfix document is missing or changed."
    }
    $diagnosticResult = Get-SafeChildPath $Root $record.manifest.diagnosticResultRelativePath "hotfix START_LOG diagnostic result"
    $evidence = Get-ExactHotfixDiagnosticFailure $diagnosticResult ([string]$record.manifest.nonce)
    if ([string]$evidence.reasonCode -cne "START_LOG" -or
        [string]$evidence.sha256 -cne [string]$record.manifest.diagnosticResultSha256) {
        throw "The connected diagnostic is not the exact recorded START_LOG evidence."
    }

    if (-not $mode) {
        $acceptedAt = (Get-Date).ToString("o")
        $record.manifest | Add-Member -NotePropertyName proofMode -NotePropertyValue "persistent-state-v2" -Force
        $record.manifest | Add-Member -NotePropertyName proofAcceptedAt -NotePropertyValue $acceptedAt -Force
        $record.manifest | Add-Member -NotePropertyName historyEvidence -NotePropertyValue "log-unavailable" -Force
        $record.manifest | Add-Member -NotePropertyName historicalJobSequenceVerified -NotePropertyValue $false -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
        $record = Get-HotfixProbeRecord $(if ($published) { "verified" } else { "active" }) -Require
    } elseif ($mode -cne "persistent-state-v2") {
        throw "The hotfix proof record has an incompatible accepted proof mode."
    }

    Publish-HotfixVerifiedRecord $record
    [ordered]@{
        status = "accepted"
        proofMode = "persistent-state-v2"
        persistentState = "verified"
        historicalRunLog = "unavailable"
        historicalJobSequenceVerified = $false
    } | ConvertTo-Json -Depth 3
}

function Verify-UniversalHotfix {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    Assert-ExactWinterBreak2Device $Root | Out-Null
    $wb2 = Get-WinterBreak2Record "executed" -Require
    $record = Get-HotfixProbeRecord "active"
    $alreadyPublished = $false
    if (-not $record) {
        $record = Get-HotfixProbeRecord "verified" -Require
        $alreadyPublished = $true
    }
    Assert-CompletedHotfixUsbPrestate $Root $wb2 -AllowVerifiedFillerRemoval:$alreadyPublished
    Assert-HotfixProbeRecordMatchesDevice $record $Root $wb2
    $proofMode = Get-HotfixProofMode $record
    if ($proofMode -eq "persistent-state-v2") {
        throw "This record was accepted as persistent-state-v2 with historical logs unavailable; its full-history result must remain absent."
    }
    if ($record.manifest.PSObject.Properties.Name -contains "diagnosticStatus") {
        $diagnosticResult = Get-SafeChildPath $Root $record.manifest.diagnosticResultRelativePath "hotfix diagnostic result"
        if (Test-Path -LiteralPath $diagnosticResult) {
            throw "A diagnostic failure result exists. Run ReadHotfixDiagnostic; success was not accepted."
        }
    }
    $probe = Get-SafeChildPath $Root $record.manifest.probeRelativePath "staged hotfix probe"
    if (-not (Test-Path -LiteralPath $probe -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $probe).Hash.ToLowerInvariant() -cne [string]$record.manifest.probeSha256) {
        throw "The staged Verify Hotfix document is missing or changed."
    }
    if ([string]$record.manifest.status -eq "prepared") {
        $record.manifest.status = "staged"
        $record.manifest | Add-Member -NotePropertyName stagedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
    } elseif ([string]$record.manifest.status -notin @("staged", "verified")) {
        throw "VerifyHotfix requires a fully staged probe record."
    }
    $result = Get-SafeChildPath $Root $record.manifest.resultRelativePath "hotfix verification result"
    $expectedContent = Get-ExpectedHotfixProbeResultContent ([string]$record.manifest.nonce)
    $resultHash = Assert-ExactUtf8FileContent $result $expectedContent "hotfix verification result"
    if ($resultHash -cne [string]$record.manifest.expectedResultSha256) {
        throw "The hotfix verification result does not match its prepared hash pin."
    }
    if ([string]$record.manifest.status -ne "verified") {
        $verifiedAt = (Get-Date).ToString("o")
        $record.manifest.status = "verified"
        $record.manifest | Add-Member -NotePropertyName verifiedAt -NotePropertyValue $verifiedAt -Force
        $record.manifest | Add-Member -NotePropertyName resultSha256 -NotePropertyValue $resultHash -Force
        $record.manifest | Add-Member -NotePropertyName proofMode -NotePropertyValue "full-history-v1" -Force
        $record.manifest | Add-Member -NotePropertyName proofAcceptedAt -NotePropertyValue $verifiedAt -Force
        $record.manifest | Add-Member -NotePropertyName historyEvidence -NotePropertyValue "verified" -Force
        $record.manifest | Add-Member -NotePropertyName historicalJobSequenceVerified -NotePropertyValue $true -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
    } elseif ([string]$record.manifest.resultSha256 -cne $resultHash) {
        throw "The verified hotfix result changed after completion."
    }
    Publish-HotfixVerifiedRecord $record
    Write-Host "Universal Hotfix v$($UniversalHotfix.Version) persistent state is nonce-bound and verified."
}

function Get-VerifiedHotfixProofForDevice {
    param([Parameter(Mandatory = $true)][string] $Root)

    $wb2 = Get-WinterBreak2Record "executed" -Require
    Assert-CompletedHotfixUsbPrestate $Root $wb2 -AllowVerifiedFillerRemoval
    $record = Get-HotfixProbeRecord "verified" -Require
    Assert-HotfixProbeRecordMatchesDevice $record $Root $wb2
    $proofMode = Get-HotfixProofMode $record -Require
    $probe = Get-SafeChildPath $Root $record.manifest.probeRelativePath "verified hotfix probe document"
    if (-not (Test-Path -LiteralPath $probe -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $probe).Hash.ToLowerInvariant() -cne [string]$record.manifest.probeSha256) {
        throw "The verified hotfix probe document is missing or changed."
    }
    if ($proofMode -eq "full-history-v1") {
        if ($record.manifest.PSObject.Properties.Name -contains "diagnosticStatus" -and
            (Test-Path -LiteralPath (Get-SafeChildPath $Root $record.manifest.diagnosticResultRelativePath "verified hotfix diagnostic result"))) {
            throw "A diagnostic failure artifact conflicts with the full-history hotfix proof."
        }
        $result = Get-SafeChildPath $Root $record.manifest.resultRelativePath "verified hotfix result"
        $resultHash = Assert-ExactUtf8FileContent `
            $result `
            (Get-ExpectedHotfixProbeResultContent ([string]$record.manifest.nonce)) `
            "verified hotfix result"
        if ($resultHash -cne [string]$record.manifest.resultSha256 -or
            $resultHash -cne [string]$record.manifest.expectedResultSha256) {
            throw "The verified hotfix result no longer matches its prepared and observed hash pins."
        }
    } else {
        $success = Get-SafeChildPath $Root $record.manifest.resultRelativePath "absent full-history hotfix result"
        if (Test-Path -LiteralPath $success) {
            throw "A full-history result appeared after persistent-state acceptance."
        }
        $diagnosticScript = Get-SafeChildPath $Root $record.manifest.diagnosticRelativePath "verified hotfix diagnostic document"
        if (-not (Test-Path -LiteralPath $diagnosticScript -PathType Leaf) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $diagnosticScript).Hash.ToLowerInvariant() -cne [string]$record.manifest.diagnosticSha256) {
            throw "The persistent-state diagnostic document is missing or changed."
        }
        $diagnosticResult = Get-SafeChildPath $Root $record.manifest.diagnosticResultRelativePath "verified START_LOG diagnostic result"
        $evidence = Get-ExactHotfixDiagnosticFailure $diagnosticResult ([string]$record.manifest.nonce)
        if ([string]$evidence.reasonCode -cne "START_LOG" -or
            [string]$evidence.sha256 -cne [string]$record.manifest.diagnosticResultSha256) {
            throw "The persistent-state START_LOG evidence changed after acceptance."
        }
    }
    return [ordered]@{ winterBreak2 = $wb2; proof = $record; proofMode = $proofMode }
}

function Assert-KOReaderStageRecordShape {
    param([Parameter(Mandatory = $true)] $Record)

    $manifest = $Record.manifest
    if ([int]$manifest.schemaVersion -ne 1 -or
        [string]$manifest.status -notin @("prepared", "filler-removal-authorized", "filler-removed", "staging", "complete") -or
        [string]$manifest.runId -notmatch "^[0-9a-f]{32}$" -or
        [string]$manifest.firmware -cne $ExpectedFirmware -or
        [string]$manifest.koreaderVersion -cne [string]$KOReader.Version -or
        [string]$manifest.koreaderArchiveSha256 -cne [string]$KOReader.Sha256 -or
        [string]$manifest.deviceFingerprint -notmatch "^[0-9a-f]{64}$" -or
        [string]$manifest.deviceIdentityHash -notmatch "^[0-9a-f]{64}$" -or
        [string]$manifest.hotfixProofMode -cnotin $HotfixProofModes -or
        [string]$manifest.hotfixProofManifestSha256 -notmatch "^[0-9a-f]{64}$") {
        throw "The KOReader stage record has an invalid shape or pin set."
    }
    $backupPrefix = (Get-FullProjectPath "device-backups").TrimEnd("\") + "\"
    $proofPath = [IO.Path]::GetFullPath([string]$manifest.hotfixProofManifestPath)
    if (-not $proofPath.StartsWith($backupPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path $proofPath -Leaf) -cne "manifest.json" -or
        -not (Test-Path -LiteralPath $proofPath -PathType Leaf)) {
        throw "The KOReader stage record points to an invalid hotfix proof manifest."
    }
}

function Get-KOReaderStageRecord {
    param([switch] $Require)

    $pointer = Get-FullProjectPath "logs\latest-koreader-stage.txt"
    if (-not (Test-Path -LiteralPath $pointer -PathType Leaf)) {
        if ($Require) { throw "No local KOReader stage record was found." }
        return $null
    }
    $manifestPath = [IO.Path]::GetFullPath((Get-Content -LiteralPath $pointer -Raw).Trim())
    $backupPrefix = (Get-FullProjectPath "device-backups").TrimEnd("\") + "\"
    if (-not $manifestPath.StartsWith($backupPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path $manifestPath -Leaf) -cne "manifest.json" -or
        -not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "The KOReader stage pointer does not name a valid ignored manifest."
    }
    $record = [ordered]@{
        pointerPath = $pointer
        manifestPath = $manifestPath
        manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    }
    Assert-KOReaderStageRecordShape $record
    return $record
}

function Assert-KOReaderStageRecordMatchesDevice {
    param(
        [Parameter(Mandatory = $true)] $Record,
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)] $HotfixProofRecord
    )

    Assert-KOReaderStageRecordShape $Record
    if ([string]$Record.manifest.deviceFingerprint -cne (Get-KindleFingerprint $Root) -or
        [string]$Record.manifest.deviceIdentityHash -cne (Get-KindleIdentityHash $Root)) {
        throw "The connected Kindle does not match the KOReader stage record."
    }
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals(
            [IO.Path]::GetFullPath([string]$Record.manifest.hotfixProofManifestPath),
            [IO.Path]::GetFullPath($HotfixProofRecord.manifestPath)
        ) -or
        [string]$Record.manifest.hotfixProofMode -cne (Get-HotfixProofMode $HotfixProofRecord -Require) -or
        [string]$Record.manifest.hotfixProofManifestSha256 -cne
            (Get-FileHash -Algorithm SHA256 -LiteralPath $HotfixProofRecord.manifestPath).Hash.ToLowerInvariant()) {
        throw "The KOReader stage record does not match the verified hotfix proof."
    }
}

function Remove-VerifiedPostHotfixOtaFiller {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)] $StageRecord,
        [Parameter(Mandatory = $true)] $HotfixProofRecord
    )

    Assert-AirplaneConfirmation
    Assert-KOReaderStageRecordMatchesDevice $StageRecord $Root $HotfixProofRecord
    Assert-NoRootKindleUpdates $Root
    $folder = Get-SafeChildPath $Root ".kindle-ota-space-filler" "post-hotfix OTA filler"
    if ([string]$StageRecord.manifest.status -eq "prepared") {
        Assert-OwnedOtaFiller $Root | Out-Null
        Assert-WinterBreak2FreeSpaceGuard $Root "KOReader filler-removal authorization"
        $StageRecord.manifest.status = "filler-removal-authorized"
        $StageRecord.manifest | Add-Member -NotePropertyName fillerRemovalAuthorizedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
        Write-ProjectJsonAtomic $StageRecord.manifestPath $StageRecord.manifest
    }
    if ([string]$StageRecord.manifest.status -eq "filler-removal-authorized") {
        if (Test-Path -LiteralPath $folder -PathType Container) {
            if (@(Get-ChildItem -LiteralPath $folder -Force).Count -eq 0) {
                # Authorized crash recovery after the owner marker was removed
                # but before the now-empty directory was removed.
                Remove-Item -LiteralPath $folder -Force
            } else {
                Remove-OwnedOtaFillerFiles $Root
            }
        } elseif (Test-Path -LiteralPath $folder) {
            throw "A non-directory replaced the authorized OTA filler path."
        }
        if (Test-Path -LiteralPath $folder) {
            throw "The authorized OTA filler removal did not complete."
        }
        Assert-NoRootKindleUpdates $Root
        $StageRecord.manifest.status = "filler-removed"
        $StageRecord.manifest | Add-Member -NotePropertyName fillerRemovedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
        Write-ProjectJsonAtomic $StageRecord.manifestPath $StageRecord.manifest
    } elseif ([string]$StageRecord.manifest.status -in @("filler-removed", "staging", "complete")) {
        if (Test-Path -LiteralPath $folder) {
            throw "The OTA filler reappeared after its verified KOReader-stage removal."
        }
        Assert-NoRootKindleUpdates $Root
    } else {
        throw "KOReader filler removal is not authorized from status '$($StageRecord.manifest.status)'."
    }
}

function Get-FreeBytes {
    param([Parameter(Mandatory = $true)][string] $Root)
    $drive = Get-CimInstance Win32_LogicalDisk |
        Where-Object { "$($_.DeviceID)\" -ieq $Root } |
        Select-Object -First 1
    return [int64]$drive.FreeSpace
}

function Fill-OtaSpace {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    Assert-ExpectedDevice $Root | Out-Null
    $folder = Join-Path $Root ".kindle-ota-space-filler"
    $folderWasPresent = Test-Path -LiteralPath $folder
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $ownerFile = Join-Path $folder ".lazying-art-filler-owner-v1"
    if (Test-Path -LiteralPath $ownerFile -PathType Leaf) {
        if ((Get-Content -LiteralPath $ownerFile -Raw).Trim() -ne $FillerOwnerText) {
            throw "The filler ownership marker is invalid: $ownerFile"
        }
    } elseif ($folderWasPresent -and @(Get-ChildItem -LiteralPath $folder -Force).Count -gt 0) {
        throw "Refusing to adopt a non-empty filler folder without this script's ownership marker: $folder"
    } else {
        [IO.File]::WriteAllText($ownerFile, "$FillerOwnerText`n", [Text.Encoding]::ASCII)
    }
    $target = [int64]$LeaveMiB * 1MB
    $tolerance = [int64]8MB
    $index = 0
    foreach ($existing in Get-ChildItem -LiteralPath $folder -File -Filter "filler-*.bin" -ErrorAction SilentlyContinue) {
        if ($existing.Name -match "^filler-(\d{3,})\.bin$") {
            $index = [Math]::Max($index, ([int]$Matches[1] + 1))
        }
    }

    while ((Get-FreeBytes $Root) -gt ($target + $tolerance)) {
        $before = Get-FreeBytes $Root
        $desired = $before - $target
        $bytes = [Math]::Min($desired, [int64](1024MB))
        if ($bytes -lt 1MB) { break }
        $path = Join-Path $folder ("filler-{0:D3}.bin" -f $index)
        Write-Host ("Allocating {0:N0} MiB: {1}" -f ($bytes / 1MB), $path)
        $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            $stream.SetLength($bytes)
            $stream.Flush()
        } finally {
            $stream.Dispose()
        }
        $after = Get-FreeBytes $Root
        if ($after -ge $before) {
            throw "Free space did not decrease after creating $path. Stop and inspect the filesystem."
        }
        $index++
    }

    $remaining = Get-FreeBytes $Root
    Write-Host ("Remaining free space: {0:N1} MiB" -f ($remaining / 1MB))
    if ($remaining -lt 50MB -or $remaining -gt 98MB) {
        throw "Free space ended outside the safety envelope (50-98 MiB). Remove the filler before continuing."
    }
}

function Assert-OwnedOtaFiller {
    param([Parameter(Mandatory = $true)][string] $Root)

    $folder = Get-SafeChildPath $Root ".kindle-ota-space-filler" "OTA filler folder"
    if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
        throw "The owned OTA filler folder is missing."
    }
    $ownerFile = Join-Path $folder ".lazying-art-filler-owner-v1"
    if (-not (Test-Path -LiteralPath $ownerFile -PathType Leaf) -or
        (Get-Content -LiteralPath $ownerFile -Raw).Trim() -ne $FillerOwnerText) {
        throw "The OTA filler ownership marker is missing or invalid."
    }
    $unexpected = @(
        Get-ChildItem -LiteralPath $folder -Force |
            Where-Object {
                $_.PSIsContainer -or
                ($_.Name -ne ".lazying-art-filler-owner-v1" -and $_.Name -notmatch "^filler-\d{3,}\.bin$")
            }
    )
    if ($unexpected.Count -gt 0) {
        $names = ($unexpected | ForEach-Object { $_.Name }) -join ", "
        throw "The OTA filler contains unexpected entries: $names"
    }
    $fillerFiles = @(Get-ChildItem -LiteralPath $folder -File -Filter "filler-*.bin" -Force)
    if ($fillerFiles.Count -eq 0) {
        throw "The owned OTA filler contains no filler files."
    }
    return $folder
}

function Remove-OwnedOtaFillerFiles {
    param([Parameter(Mandatory = $true)][string] $Root)

    $folder = [IO.Path]::GetFullPath((Join-Path $Root ".kindle-ota-space-filler"))
    $expected = [IO.Path]::GetFullPath(($Root.TrimEnd("\") + "\.kindle-ota-space-filler"))
    if ($folder -ne $expected) {
        throw "Refusing unexpected filler path: $folder"
    }
    if (Test-Path -LiteralPath $folder) {
        $ownerFile = Join-Path $folder ".lazying-art-filler-owner-v1"
        if (-not (Test-Path -LiteralPath $ownerFile -PathType Leaf) -or
            (Get-Content -LiteralPath $ownerFile -Raw).Trim() -ne $FillerOwnerText) {
            throw "Refusing to remove an unowned filler folder: $folder"
        }
        $unexpected = @(
            Get-ChildItem -LiteralPath $folder -Force |
                Where-Object {
                    $_.PSIsContainer -or
                    ($_.Name -ne ".lazying-art-filler-owner-v1" -and $_.Name -notmatch "^filler-\d{3,}\.bin$")
                }
        )
        if ($unexpected.Count -gt 0) {
            $names = ($unexpected | ForEach-Object { $_.Name }) -join ", "
            throw "Refusing to remove the filler folder because it contains unexpected entries: $names"
        }
        Get-ChildItem -LiteralPath $folder -File -Filter "filler-*.bin" -Force | Remove-Item -Force
        Remove-Item -LiteralPath $ownerFile -Force
        Remove-Item -LiteralPath $folder -Force
        Write-Host "Removed verified filler files from $folder"
    } else {
        Write-Host "No OTA filler folder is present."
    }
}

function Remove-OtaFiller {
    param([Parameter(Mandatory = $true)][string] $Root)

    # This remains the public Store-route cleanup and is intentionally blocked
    # once any WinterBreak2 state exists. Post-hotfix removal uses a separate,
    # verified and crash-resumable internal path.
    Assert-StoreRouteOpen $Root "RemoveFiller"
    Assert-AirplaneConfirmation
    Remove-OwnedOtaFillerFiles $Root
}

function Reset-WinterBreakStoreCache {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-StoreRouteOpen $Root "ResetStoreCache"
    Assert-AirplaneConfirmation
    $info = Assert-ExpectedDevice $Root
    if ($info.jailbrokenMarker) {
        throw "The jailbreak marker exists; Store-cache reset is only for a failed pre-jailbreak Mesquito launch."
    }
    $stageRecord = Get-RecordedManifest -Require
    if ($stageRecord.manifest.status -ne "complete" -or
        $stageRecord.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "A matching, complete WinterBreak staging manifest is required."
    }
    if (-not $info.winterBreakStaged) {
        throw "WinterBreak must be correctly restaged before Store-cache reset."
    }
    Assert-OwnedOtaFiller $Root | Out-Null
    Assert-WinterBreakFreeSpaceGuard $Root "Store-cache reset preflight"
    $strayUpdates = @(
        Get-ChildItem -LiteralPath $Root -File -Force |
            Where-Object {
                $_.Name -ilike "update*.bin" -or
                $_.Name -ieq "update.bin.tmp.partial"
            }
    )
    if ($strayUpdates.Count -gt 0) {
        $names = ($strayUpdates | ForEach-Object { $_.Name } | Sort-Object -Unique) -join ", "
        throw "Root-level Kindle update package(s) must be reviewed and removed before Store-cache reset: $names"
    }

    $cacheRelative = ".active_content_sandbox\store\resource\LocalStorage"
    $cachePath = Get-SafeChildPath $Root $cacheRelative "Store LocalStorage cache"
    $record = Get-StoreCacheRecord
    if ($record -and $record.manifest.status -eq "complete") {
        if ($record.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
            throw "The completed Store-cache record belongs to a different Kindle."
        }
        if (Test-Path -LiteralPath $cachePath) {
            throw "The Store-cache record is complete, but LocalStorage exists again. Refusing to treat this as an idempotent completion."
        }
        Assert-WinterBreakFreeSpaceGuard $Root "Completed Store-cache reset"
        Complete-StoreSandboxRecord $Root "regenerated" -ConfirmedPreparedRecovery
        Write-Host "The Store-cache reset was already complete; finalized the full Store-sandbox record."
        return
    }

    if (-not $record) {
        if (-not (Test-Path -LiteralPath $cachePath -PathType Container)) {
            throw "The Store did not generate LocalStorage. Follow the official browsing prerequisite before retrying."
        }
        $sourceFiles = @(Get-ChildItem -LiteralPath $cachePath -File -Recurse -Force)
        if ($sourceFiles.Count -eq 0) {
            throw "LocalStorage exists but contains no cache file; refusing a meaningless reset."
        }

        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $recordRoot = Get-FullProjectPath ("device-backups\winterbreak-store-cache-{0}" -f $stamp)
        New-Item -ItemType Directory -Path $recordRoot -Force | Out-Null
        Copy-Item -LiteralPath $cachePath -Destination $recordRoot -Recurse -Force
        $backupCache = Join-Path $recordRoot "LocalStorage"
        $prefix = $cachePath.TrimEnd("\") + "\"
        $entries = @()
        foreach ($file in $sourceFiles) {
            $relative = $file.FullName.Substring($prefix.Length)
            $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
            $backupFile = Get-SafeChildPath $backupCache $relative "Store-cache backup"
            if (-not (Test-Path -LiteralPath $backupFile -PathType Leaf) -or
                (Get-FileHash -Algorithm SHA256 -LiteralPath $backupFile).Hash.ToLowerInvariant() -ne $sourceHash) {
                throw "Store-cache backup verification failed: $relative"
            }
            $entries += [ordered]@{ relativePath = $relative; sha256 = $sourceHash }
        }
        $manifest = [ordered]@{
            createdAt = (Get-Date).ToString("o")
            status = "prepared"
            firmware = $info.firmware
            deviceFingerprint = Get-KindleFingerprint $Root
            cacheRelativePath = $cacheRelative
            files = $entries
        }
        $manifestPath = Join-Path $recordRoot "manifest.json"
        $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
        $latest = Get-FullProjectPath "logs\latest-winterbreak-store-cache.txt"
        New-Item -ItemType Directory -Path (Split-Path $latest -Parent) -Force | Out-Null
        Set-Content -LiteralPath $latest -Value $manifestPath -Encoding UTF8
        $record = Get-StoreCacheRecord -Require
    }

    if ($record.manifest.status -ne "prepared" -or
        $record.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The active Store-cache record cannot be resumed safely."
    }
    $recordRoot = Split-Path $record.manifestPath -Parent
    $backupCache = Join-Path $recordRoot "LocalStorage"
    foreach ($entry in $record.manifest.files) {
        $backupFile = Get-SafeChildPath $backupCache $entry.relativePath "Store-cache backup"
        if (-not (Test-Path -LiteralPath $backupFile -PathType Leaf) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $backupFile).Hash.ToLowerInvariant() -ne $entry.sha256.ToLowerInvariant()) {
            throw "Store-cache backup preflight failed: $($entry.relativePath)"
        }
    }

    if (Test-Path -LiteralPath $cachePath) {
        Remove-Item -LiteralPath $cachePath -Recurse -Force
    }
    $stage = Expand-WinterBreak
    $stagePrefix = $stage.TrimEnd("\") + "\"
    foreach ($directory in Get-ChildItem -LiteralPath $stage -Directory -Recurse -Force) {
        $relative = $directory.FullName.Substring($stagePrefix.Length)
        New-Item -ItemType Directory -Path (Get-SafeChildPath $Root $relative "WinterBreak retry directory") -Force | Out-Null
    }
    foreach ($file in Get-ChildItem -LiteralPath $stage -File -Recurse -Force) {
        $relative = $file.FullName.Substring($stagePrefix.Length)
        $destination = Get-SafeChildPath $Root $relative "WinterBreak retry file"
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash -ne
            (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash) {
            throw "WinterBreak retry copy verification failed: $relative"
        }
    }
    if (Test-Path -LiteralPath $cachePath) {
        throw "LocalStorage unexpectedly reappeared during offline retry preparation."
    }
    $remaining = Get-FreeBytes $Root
    if ($remaining -lt 50MB -or $remaining -gt 98MB) {
        throw "Store-cache reset left free space outside the 50-98 MiB guard: $([Math]::Round($remaining / 1MB, 1)) MiB"
    }
    Complete-StoreSandboxRecord $Root "regenerated"
    $record.manifest.status = "complete"
    $record.manifest | Add-Member -NotePropertyName completedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    $record.manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $record.manifestPath -Encoding UTF8
    Write-Host "Backed up and removed LocalStorage, then re-applied and verified WinterBreak."
}

function Restore-WinterBreakStoreCache {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-StoreRouteOpen $Root "RestoreStoreCache"
    Assert-AirplaneConfirmation
    if (Test-Path -LiteralPath (Join-Path $Root "documents\JAILBROKEN.txt")) {
        throw "The jailbreak marker exists; do not restore a pre-jailbreak Store cache."
    }
    $record = Get-StoreCacheRecord -Require
    if ($record.manifest.status -notin @("prepared", "complete") -or
        $record.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The connected Kindle does not match an active restorable Store-cache record."
    }
    $cachePath = Get-SafeChildPath $Root $record.manifest.cacheRelativePath "Store LocalStorage cache"
    if (Test-Path -LiteralPath $cachePath) {
        if (@(Get-ChildItem -LiteralPath $cachePath -Force).Count -gt 0) {
            throw "LocalStorage contains new data. Refusing to overwrite it with the backup."
        }
        Remove-Item -LiteralPath $cachePath -Force
    }
    $backupCache = Join-Path (Split-Path $record.manifestPath -Parent) "LocalStorage"
    Copy-DirectoryContents $backupCache $cachePath
    foreach ($entry in $record.manifest.files) {
        $restored = Get-SafeChildPath $cachePath $entry.relativePath "restored Store cache"
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $restored).Hash.ToLowerInvariant() -ne $entry.sha256.ToLowerInvariant()) {
            throw "Restored Store-cache hash mismatch: $($entry.relativePath)"
        }
    }
    $record.manifest.status = "restored"
    $record.manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $record.manifestPath -Encoding UTF8
    Remove-Item -LiteralPath $record.latestPath -Force
    Write-Host "Restored the backed-up Store LocalStorage cache."
}

function Assert-WinterBreakFreeSpaceGuard {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)][string] $Context
    )

    $remaining = Get-FreeBytes $Root
    if ($remaining -lt 50MB -or $remaining -gt 98MB) {
        throw "$Context left free space outside 50-98 MiB: $([Math]::Round($remaining / 1MB, 1)) MiB"
    }
}

function Complete-PreviousStoreCacheRecordForFullRegeneration {
    param([Parameter(Mandatory = $true)][string] $Root)

    $oldCacheRecord = Get-StoreCacheRecord
    if (-not $oldCacheRecord) { return }
    if ($oldCacheRecord.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The earlier Store-cache record belongs to a different Kindle."
    }
    $current = [string]$oldCacheRecord.manifest.status
    if ($current -eq "superseded-by-full-regeneration") {
        Remove-Item -LiteralPath $oldCacheRecord.latestPath -Force
        return
    }
    if ($current -notin @("prepared", "complete")) {
        throw "The earlier Store-cache record has an invalid supersession state: '$current'."
    }
    $oldCacheRecord.manifest.status = "superseded-by-full-regeneration"
    $oldCacheRecord.manifest | Add-Member -NotePropertyName supersededAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    $oldCacheRecord.manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $oldCacheRecord.manifestPath -Encoding UTF8
    Remove-Item -LiteralPath $oldCacheRecord.latestPath -Force
}

function Begin-WinterBreakStoreRegeneration {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-StoreRouteOpen $Root "BeginStoreRegeneration"
    Assert-AirplaneConfirmation
    $info = Assert-ExpectedDevice $Root
    if ($info.jailbrokenMarker) {
        throw "The jailbreak marker exists; full Store regeneration is pre-jailbreak troubleshooting only."
    }
    $stageRecord = Get-RecordedManifest -Require
    if ($stageRecord.manifest.status -ne "complete" -or
        $stageRecord.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "A matching, complete WinterBreak staging manifest is required."
    }
    Assert-OwnedOtaFiller $Root | Out-Null
    Assert-WinterBreakFreeSpaceGuard $Root "Store-regeneration preflight"

    $sandboxPath = Get-SafeChildPath $Root $StoreSandboxRelativePath "Store sandbox"
    $record = Get-StoreSandboxRecord
    if ($record -and $record.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The connected Kindle does not match the active full Store-sandbox record."
    }
    if ($record -and $record.manifest.status -eq "removed") {
        # The removal status is the commit point. Finalizing an older cache
        # pointer after it is safe makes this retry idempotent across crashes.
        Complete-PreviousStoreCacheRecordForFullRegeneration $Root
        if (Test-Path -LiteralPath $sandboxPath) {
            throw "The full Store sandbox was already removed and has since been regenerated. Use ResetStoreCache; BeginStoreRegeneration will not delete it again."
        }
        Assert-WinterBreakFreeSpaceGuard $Root "Completed Store-sandbox removal"
        Write-Host "The full Store sandbox removal was already committed."
        return
    }
    if ($record -and $record.manifest.status -ne "prepared") {
        throw "The full Store-sandbox record cannot begin from status '$($record.manifest.status)'."
    }

    if (-not $record) {
        if (-not (Test-Path -LiteralPath $sandboxPath -PathType Container)) {
            throw "The Store sandbox is already absent but has no reversible local record."
        }
        $inventory = Get-DirectoryManifestInventory $sandboxPath "Store sandbox"
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $recordName = "winterbreak-store-sandbox-$stamp-$([Guid]::NewGuid().ToString('N'))"
        $backupParent = Get-FullProjectPath "device-backups"
        New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
        $recordRoot = Get-SafeChildPath $backupParent $recordName "Store-sandbox record directory"
        if (Test-Path -LiteralPath $recordRoot) {
            throw "Refusing to merge with an existing Store-sandbox record directory: $recordRoot"
        }
        New-Item -ItemType Directory -Path $recordRoot | Out-Null
        $backupSandbox = Join-Path $recordRoot ".active_content_sandbox"
        Copy-DirectoryContents $sandboxPath $backupSandbox
        Assert-DirectoryMatchesManifest $backupSandbox $inventory.files $inventory.directories "Store-sandbox backup"
        Assert-DirectoryMatchesManifest $sandboxPath $inventory.files $inventory.directories "Store sandbox after backup"
        $manifest = [ordered]@{
            createdAt = (Get-Date).ToString("o")
            status = "prepared"
            firmware = $info.firmware
            deviceFingerprint = Get-KindleFingerprint $Root
            sandboxRelativePath = $StoreSandboxRelativePath
            files = $inventory.files
            directories = $inventory.directories
        }
        $manifestPath = Join-Path $recordRoot "manifest.json"
        $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
        $latest = Get-FullProjectPath "logs\latest-winterbreak-store-sandbox.txt"
        New-Item -ItemType Directory -Path (Split-Path $latest -Parent) -Force | Out-Null
        Set-Content -LiteralPath $latest -Value $manifestPath -Encoding UTF8
        $record = Get-StoreSandboxRecord -Require
    }

    if ($record.manifest.status -ne "prepared" -or
        $record.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The full Store-sandbox record cannot be resumed safely."
    }
    $backupSandbox = Join-Path (Split-Path $record.manifestPath -Parent) ".active_content_sandbox"
    Assert-DirectoryMatchesManifest $backupSandbox $record.manifest.files $record.manifest.directories "Store-sandbox backup preflight"

    if (Test-Path -LiteralPath $sandboxPath) {
        try {
            Assert-DirectoryMatchesManifest $sandboxPath $record.manifest.files $record.manifest.directories "current Store sandbox"
        } catch {
            throw "The current Store sandbox differs from the prepared backup. Refusing to delete regenerated or changed Store data. $($_.Exception.Message)"
        }
        Remove-Item -LiteralPath $sandboxPath -Recurse -Force
    }
    if (Test-Path -LiteralPath $sandboxPath) {
        throw "The full Store sandbox still exists after the removal attempt."
    }
    Assert-WinterBreakFreeSpaceGuard $Root "Full Store-sandbox removal"
    $record.manifest.status = "removed"
    $record.manifest | Add-Member -NotePropertyName removedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    $record.manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $record.manifestPath -Encoding UTF8
    Complete-PreviousStoreCacheRecordForFullRegeneration $Root
    Write-Host "Backed up and removed the full Store sandbox for official regeneration."
}

function Restore-WinterBreakStoreSandbox {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-StoreRouteOpen $Root "RestoreStoreSandbox"
    Assert-AirplaneConfirmation
    if (Test-Path -LiteralPath (Join-Path $Root "documents\JAILBROKEN.txt")) {
        throw "The jailbreak marker exists; do not restore a pre-jailbreak Store sandbox."
    }
    $record = Get-StoreSandboxRecord -Require
    if ($record.manifest.status -notin @("prepared", "removed", "restored") -or
        $record.manifest.deviceFingerprint -ne (Get-KindleFingerprint $Root)) {
        throw "The connected Kindle does not match an active Store-sandbox record."
    }
    $backupSandbox = Join-Path (Split-Path $record.manifestPath -Parent) ".active_content_sandbox"
    # Validate every declared hash and the exact file/directory set before any
    # destination mutation. Copying first would make a damaged backup harmful.
    Assert-DirectoryMatchesManifest $backupSandbox $record.manifest.files $record.manifest.directories "Store-sandbox restore backup"

    $sandboxPath = Get-SafeChildPath $Root $StoreSandboxRelativePath "Store sandbox"
    if ($record.manifest.status -eq "restored") {
        Assert-DirectoryMatchesManifest $sandboxPath $record.manifest.files $record.manifest.directories "already-restored Store sandbox"
        Remove-Item -LiteralPath $record.latestPath -Force
        Write-Host "The full Store sandbox was already restored; finalized its record."
        return
    }
    if (Test-Path -LiteralPath $sandboxPath) {
        if (@(Get-ChildItem -LiteralPath $sandboxPath -Force).Count -gt 0) {
            $difference = $null
            try {
                Assert-DirectoryMatchesManifest $sandboxPath $record.manifest.files $record.manifest.directories "existing Store sandbox"
            } catch {
                $difference = $_.Exception.Message
            }
            if ($difference) {
                throw "The Kindle contains a different Store sandbox. Refusing to overwrite it. $difference"
            }
            $record.manifest.status = "restored"
            $record.manifest | Add-Member -NotePropertyName restoredAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
            $record.manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $record.manifestPath -Encoding UTF8
            Remove-Item -LiteralPath $record.latestPath -Force
            Write-Host "The original full Store sandbox was already present; finalized its restored record."
            return
        }
        Remove-Item -LiteralPath $sandboxPath -Force
    }
    Copy-DirectoryContents $backupSandbox $sandboxPath
    Assert-DirectoryMatchesManifest $sandboxPath $record.manifest.files $record.manifest.directories "restored Store sandbox"
    $record.manifest.status = "restored"
    $record.manifest | Add-Member -NotePropertyName restoredAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    $record.manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $record.manifestPath -Encoding UTF8
    Remove-Item -LiteralPath $record.latestPath -Force
    Write-Host "Restored the backed-up full Store sandbox."
}

function Stage-KOReaderFallback {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-AirplaneConfirmation
    $info = Assert-ExactWinterBreak2Device $Root
    $verifiedHotfix = Get-VerifiedHotfixProofForDevice $Root
    Download-Packages

    $archivePath = Get-FullProjectPath ("downloads\" + $KOReader.File)
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant() -cne [string]$KOReader.Sha256) {
        throw "The KOReader archive does not match its pinned SHA-256."
    }

    $koStage = Reset-ProjectDirectory "staging\koreader-kindlepw2-v2026.07.1"
    Expand-Archive -LiteralPath $archivePath -DestinationPath $koStage -Force
    if (-not (Test-Path -LiteralPath (Join-Path $koStage "koreader\koreader.sh") -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $koStage "extensions\koreader") -PathType Container) -or
        -not (Test-Path -LiteralPath (Get-FullProjectPath $KOReader.LauncherRelativePath) -PathType Leaf)) {
        throw "The pinned KOReader inputs do not contain the required kindlepw2 tree and launcher."
    }

    $record = Get-KOReaderStageRecord
    if (-not $record) {
        foreach ($relative in @("koreader", "extensions\koreader", "documents\KOReader.sh")) {
            if (Test-Path -LiteralPath (Get-SafeChildPath $Root $relative "unrecorded KOReader destination")) {
                throw "An unrecorded KOReader destination already exists: $relative"
            }
        }
        $runId = New-CryptographicLowerHex32
        $recordRoot = Get-FullProjectPath ("device-backups\koreader-stage-$ExpectedFirmware-$((Get-Date).ToString('yyyyMMdd-HHmmss'))-$runId")
        if (Test-Path -LiteralPath $recordRoot) {
            throw "The planned KOReader stage record directory already exists."
        }
        New-Item -ItemType Directory -Path $recordRoot | Out-Null
        $manifest = [ordered]@{
            schemaVersion = 1
            status = "prepared"
            runId = $runId
            createdAt = (Get-Date).ToString("o")
            firmware = $ExpectedFirmware
            koreaderVersion = $KOReader.Version
            koreaderArchiveSha256 = $KOReader.Sha256
            deviceFingerprint = Get-KindleFingerprint $Root
            deviceIdentityHash = Get-KindleIdentityHash $Root
            hotfixProofMode = [string]$verifiedHotfix.proofMode
            hotfixProofManifestPath = $verifiedHotfix.proof.manifestPath
            hotfixProofManifestSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $verifiedHotfix.proof.manifestPath).Hash.ToLowerInvariant()
        }
        $manifestPath = Join-Path $recordRoot "manifest.json"
        Write-ProjectJsonAtomic $manifestPath $manifest
        $pointer = Get-FullProjectPath "logs\latest-koreader-stage.txt"
        if (Test-Path -LiteralPath $pointer) {
            throw "A KOReader stage pointer appeared during preparation; the filler was not removed."
        }
        Write-ProjectTextAtomic $pointer $manifestPath
        $record = Get-KOReaderStageRecord -Require
    }
    Assert-KOReaderStageRecordMatchesDevice $record $Root $verifiedHotfix.proof

    # The archive and its required tree were validated before this durable
    # authorization. Only this internal proof-bound state may remove or resume
    # removal of the exact owned filler after WinterBreak2 execution.
    Remove-VerifiedPostHotfixOtaFiller $Root $record $verifiedHotfix.proof
    if ([string]$record.manifest.status -ne "staging") {
        $record.manifest.status = "staging"
        $record.manifest | Add-Member -NotePropertyName stagingAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
        Write-ProjectJsonAtomic $record.manifestPath $record.manifest
    }
    Assert-NoRootKindleUpdates $Root

    Copy-DirectoryContents (Join-Path $koStage "koreader") (Join-Path $Root "koreader")
    Copy-DirectoryContents (Join-Path $koStage "extensions\koreader") (Join-Path $Root "extensions\koreader")
    Copy-TextFileAsLf `
        (Get-FullProjectPath $KOReader.LauncherRelativePath) `
        (Get-SafeChildPath $Root $KOReader.LauncherDeviceRelativePath "KOReader launcher destination")

    Assert-NoRootKindleUpdates $Root
    $record.manifest.status = "complete"
    $record.manifest | Add-Member -NotePropertyName completedAt -NotePropertyValue ((Get-Date).ToString("o")) -Force
    Write-ProjectJsonAtomic $record.manifestPath $record.manifest

    Write-Host "Staged KOReader kindlepw2 v$($KOReader.Version) and a shell-integration launcher."
    Write-Host "Do not install the KPM catalog's kindlehf KOReader build on firmware $($info.firmware)."
}

function Get-PinnedKOReaderLauncherContent {
    $launcher = Get-FullProjectPath $KOReader.LauncherRelativePath
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $launcher).Hash.ToLowerInvariant() -cne [string]$KOReader.LauncherSha256) {
        throw "The local KOReader launcher does not match its pinned SHA-256."
    }
    $bytes = [IO.File]::ReadAllBytes($launcher)
    if (($bytes.Length -ge 3 -and $bytes[0] -eq 0xef -and $bytes[1] -eq 0xbb -and $bytes[2] -eq 0xbf) -or
        [Array]::IndexOf($bytes, [byte]0x0d) -ge 0) {
        throw "The pinned KOReader launcher must be LF-only UTF-8 without a BOM."
    }
    $strictUtf8 = New-Object Text.UTF8Encoding($false, $true)
    return $strictUtf8.GetString($bytes)
}

function Verify-KOReaderStage {
    param([Parameter(Mandatory = $true)][string] $Root)

    Assert-ExactWinterBreak2Device $Root | Out-Null
    $verifiedHotfix = Get-VerifiedHotfixProofForDevice $Root
    $record = Get-KOReaderStageRecord -Require
    if ([string]$record.manifest.status -cne "complete") {
        throw "KOReader staging is not complete."
    }
    $completedAt = [string]$record.manifest.completedAt
    $parsedCompletedAt = [DateTimeOffset]::MinValue
    if ([string]::IsNullOrWhiteSpace($completedAt) -or
        -not [DateTimeOffset]::TryParse(
            $completedAt,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$parsedCompletedAt
        )) {
        throw "The completed KOReader stage record lacks a valid completedAt timestamp."
    }
    Assert-KOReaderStageRecordMatchesDevice $record $Root $verifiedHotfix.proof
    Assert-NoRootKindleUpdates $Root

    $filler = Get-SafeChildPath $Root ".kindle-ota-space-filler" "post-KOReader OTA filler"
    if (Test-Path -LiteralPath $filler) {
        throw "The OTA filler reappeared after completed KOReader staging."
    }
    $coreLauncher = Get-SafeChildPath $Root "koreader\koreader.sh" "KOReader core launcher"
    if (-not (Test-Path -LiteralPath $coreLauncher -PathType Leaf)) {
        throw "The KOReader core launcher is missing."
    }
    $extension = Get-SafeChildPath $Root "extensions\koreader" "KOReader extension directory"
    if (-not (Test-Path -LiteralPath $extension -PathType Container)) {
        throw "The KOReader extension directory is missing."
    }
    $launcherContent = Get-PinnedKOReaderLauncherContent
    $deviceLauncher = Get-SafeChildPath $Root $KOReader.LauncherDeviceRelativePath "KOReader document launcher"
    $launcherHash = Assert-ExactUtf8FileContent $deviceLauncher $launcherContent "KOReader document launcher"
    if ($launcherHash -cne [string]$KOReader.LauncherSha256) {
        throw "The KOReader document launcher does not match its pinned SHA-256."
    }

    [ordered]@{
        status = "verified"
        stageStatus = "complete"
        koreaderVersion = [string]$KOReader.Version
        proofMode = [string]$verifiedHotfix.proofMode
        otaFiller = "absent"
        rootUpdates = "absent"
        launcherSha256 = [string]$KOReader.LauncherSha256
    } | ConvertTo-Json -Depth 3
}

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)][string] $Source,
        [Parameter(Mandatory = $true)][string] $Destination
    )

    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Source directory is missing: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $prefix = (Resolve-Path -LiteralPath $Source).Path.TrimEnd("\") + "\"
    foreach ($directory in Get-ChildItem -LiteralPath $Source -Directory -Recurse -Force) {
        $relative = $directory.FullName.Substring($prefix.Length)
        New-Item -ItemType Directory -Path (Join-Path $Destination $relative) -Force | Out-Null
    }
    foreach ($file in Get-ChildItem -LiteralPath $Source -File -Recurse -Force) {
        $relative = $file.FullName.Substring($prefix.Length)
        $target = Join-Path $Destination $relative
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
        $targetHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
        if ($targetHash -ne $sourceHash) {
            throw "Post-copy SHA-256 mismatch: $target"
        }
    }
}

function Copy-TextFileAsLf {
    param(
        [Parameter(Mandatory = $true)][string] $Source,
        [Parameter(Mandatory = $true)][string] $Destination
    )
    $content = (Get-Content -LiteralPath $Source -Raw) -replace "`r`n", "`n"
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Destination, $content, $encoding)
}

function Eject-Kindle {
    param([Parameter(Mandatory = $true)][string] $Root)
    $drive = $Root.Substring(0, 2)
    $shell = New-Object -ComObject Shell.Application
    $item = $shell.Namespace(17).ParseName($drive)
    if (-not $item) {
        throw "Windows could not find $drive in the removable-drive shell."
    }
    $verb = @($item.Verbs()) |
        Where-Object {
            [StringComparer]::OrdinalIgnoreCase.Equals(
                (($_.Name -replace "&", "").Trim()),
                "Eject"
            )
        } |
        Select-Object -First 1
    if (-not $verb) {
        throw "Windows Explorer did not expose an exact Eject verb for $drive."
    }
    $verb.DoIt()

    $deadline = (Get-Date).AddSeconds(15)
    while ((Test-Path -LiteralPath $Root) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-Path -LiteralPath $Root)) {
        Write-Host "Safely ejected $drive; its drive path is no longer accessible."
    } else {
        Write-Warning "Windows accepted the Eject request for $drive, but its drive path remains accessible after 15 seconds. Detachment is not confirmed."
    }
}

$root = $null
if ($Action -ne "Download") {
    $root = Resolve-KindleRoot $KindleRoot
}

switch ($Action) {
    "Diagnose" {
        $info = Assert-ExpectedDevice $root
        $info["expectedModel"] = "PW5SE (model code audited separately; serial intentionally omitted)"
        $info["recommendedMethod"] = "WinterBreak2 v1.0.0 browser fallback (stock jb.sh)"
        $info["koreaderFamily"] = "kindlepw2"
        $info | ConvertTo-Json -Depth 5
    }
    "Download" { Download-Packages }
    "Backup" { Backup-VisibleKindle $root | Out-Null }
    "Stage" { Stage-WinterBreak $root }
    "UndoStage" { Undo-WinterBreakStage $root }
    "FillSpace" { Fill-OtaSpace $root }
    "RemoveFiller" { Remove-OtaFiller $root }
    "ResetStoreCache" { Reset-WinterBreakStoreCache $root }
    "RestoreStoreCache" { Restore-WinterBreakStoreCache $root }
    "BeginStoreRegeneration" { Begin-WinterBreakStoreRegeneration $root }
    "RestoreStoreSandbox" { Restore-WinterBreakStoreSandbox $root }
    "Prepare" {
        Assert-StoreRouteOpen $root "Prepare"
        Assert-AirplaneConfirmation
        Backup-VisibleKindle $root | Out-Null
        Stage-WinterBreak $root
        Fill-OtaSpace $root
    }
    "BindDeviceIdentity" { Bind-WinterBreak2DeviceIdentity $root }
    "StageWinterBreak2" { Stage-WinterBreak2 $root }
    "VerifyWinterBreak2" { Verify-WinterBreak2 $root }
    "UndoWinterBreak2" { Undo-WinterBreak2 $root }
    "StageHotfix" { Stage-UniversalHotfix $root }
    "StageHotfixProbe" { Stage-HotfixProbe $root }
    "StageHotfixDiagnostic" { Stage-HotfixDiagnostic $root }
    "ReadHotfixDiagnostic" { Read-HotfixDiagnostic $root }
    "AcceptHotfixPersistentState" { Accept-HotfixPersistentState $root }
    "VerifyHotfix" { Verify-UniversalHotfix $root }
    "VerifyJailbreak" {
        Assert-StoreRouteOpen $root "VerifyJailbreak"
        $info = Assert-ExpectedDevice $root
        $info | ConvertTo-Json -Depth 5
        if (-not $info.jailbrokenMarker) {
            throw "The USB-visible WinterBreak success marker is absent."
        }
        Complete-StageRecordAfterJailbreak $root
        Complete-StoreCacheRecordAfterJailbreak $root
        Complete-StoreSandboxRecord $root "executed"
        Write-Host "WinterBreak success marker found. KMC root state still requires an on-device/KPM or SSH check."
    }
    "StageKOReader" { Stage-KOReaderFallback $root }
    "VerifyKOReaderStage" { Verify-KOReaderStage $root }
    "Eject" { Eject-Kindle $root }
}
