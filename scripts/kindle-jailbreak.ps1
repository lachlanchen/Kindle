param(
    [ValidateSet(
        "Diagnose",
        "DownloadLegacy",
        "DownloadModern",
        "BuildLegacy",
        "Prepare",
        "StageWinterBreak2",
        "StageAdBreak",
        "StagePostJailbreak",
        "FillOtaSpace",
        "RemoveOtaFiller",
        "Eject"
    )]
    [string]$Action = "Diagnose",
    [string]$KindleRoot,
    [int]$LeaveMiB = 80,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Get-ProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Join-Root {
    param([string]$Path)
    return (Join-Path (Get-ProjectRoot) $Path)
}

function Resolve-KindleRoot {
    param([string]$Requested)
    if ($Requested) {
        if (-not (Test-Path $Requested)) {
            throw "Kindle root does not exist: $Requested"
        }
        return (Resolve-Path $Requested).Path.TrimEnd("\") + "\"
    }

    $volumes = Get-CimInstance Win32_LogicalDisk |
        Where-Object {
            $_.DriveType -eq 2 -and
            ($_.VolumeName -like "*Kindle*" -or
             (Test-Path (Join-Path $_.DeviceID "documents")) -and
             (Test-Path (Join-Path $_.DeviceID "system")))
        }

    if (-not $volumes) {
        throw "No mounted Kindle storage found. Connect the Kindle in USB Drive Mode."
    }
    if (@($volumes).Count -gt 1) {
        $list = ($volumes | ForEach-Object { "$($_.DeviceID)\ ($($_.VolumeName))" }) -join ", "
        throw "Multiple possible Kindle roots found: $list. Pass -KindleRoot explicitly."
    }

    return "$($volumes[0].DeviceID)\"
}

function Assert-SafeKindleRoot {
    param([string]$Root)
    $resolved = (Resolve-Path $Root).Path.TrimEnd("\") + "\"
    if ($resolved -match "^[A-Za-z]:\\$") {
        if (-not (Test-Path (Join-Path $resolved "documents")) -or -not (Test-Path (Join-Path $resolved "system"))) {
            throw "Refusing to use $resolved because it does not look like a Kindle root."
        }
        return $resolved
    }
    throw "Refusing unsafe Kindle root: $resolved"
}

function Get-KindleInfo {
    param([string]$Root)
    $versionFile = Join-Path $Root "system\version.txt"
    $versionText = if (Test-Path $versionFile) { (Get-Content $versionFile -Raw).Trim() } else { "" }
    $firmware = $null
    if ($versionText -match "(\d+\.\d+(?:\.\d+){0,4})") {
        $firmware = $Matches[1]
    }

    $disk = Get-CimInstance Win32_DiskDrive |
        Where-Object { $_.Model -like "*Kindle*" } |
        Select-Object -First 1

    $drive = Get-CimInstance Win32_LogicalDisk |
        Where-Object { "$($_.DeviceID)\" -ieq $Root } |
        Select-Object -First 1

    [ordered]@{
        root = $Root
        volumeName = $drive.VolumeName
        firmware = $firmware
        versionText = $versionText
        serial = $disk.SerialNumber
        sizeBytes = [int64]$drive.Size
        freeBytes = [int64]$drive.FreeSpace
        documents = Test-Path (Join-Path $Root "documents")
        system = Test-Path (Join-Path $Root "system")
        extensions = Test-Path (Join-Path $Root "extensions")
        mrpackages = Test-Path (Join-Path $Root "mrpackages")
        koreader = Test-Path (Join-Path $Root "koreader")
        winterbreakLog = Test-Path (Join-Path $Root "winterbreak.log")
    }
}

function Convert-VersionParts {
    param([string]$Version)
    if (-not $Version) { return @(0, 0, 0, 0, 0) }
    $parts = $Version -split "[^0-9]+" | Where-Object { $_ -ne "" } | ForEach-Object { [int]$_ }
    while ($parts.Count -lt 5) { $parts += 0 }
    return @($parts[0], $parts[1], $parts[2], $parts[3], $parts[4])
}

function Compare-KindleVersion {
    param([string]$A, [string]$B)
    $ap = Convert-VersionParts $A
    $bp = Convert-VersionParts $B
    for ($i = 0; $i -lt 5; $i++) {
        if ($ap[$i] -lt $bp[$i]) { return -1 }
        if ($ap[$i] -gt $bp[$i]) { return 1 }
    }
    return 0
}

function Get-RecommendedMethod {
    param([string]$Firmware)
    if (-not $Firmware) { return "unknown" }
    if ((Compare-KindleVersion $Firmware "5.18.1") -lt 0) { return "winterbreak" }
    if ((Compare-KindleVersion $Firmware "5.18.5.0.1") -le 0) { return "adbreak-or-nosebleed" }
    return "check-current-kindlemodding"
}

function Get-KOReaderFamily {
    param([string]$Firmware)
    if ($Firmware -and (Compare-KindleVersion $Firmware "5.16.3") -ge 0) {
        return "kindlehf"
    }
    return "kindlepw2"
}

function Invoke-Download {
    param(
        [string]$Url,
        [string]$OutFile,
        [string]$Sha256
    )
    New-Item -ItemType Directory -Path (Split-Path $OutFile -Parent) -Force | Out-Null
    if (-not (Test-Path $OutFile)) {
        Write-Host "Downloading $Url"
        Invoke-WebRequest -Uri $Url -OutFile $OutFile
    }
    if ($Sha256) {
        $actual = (Get-FileHash -Algorithm SHA256 $OutFile).Hash.ToLowerInvariant()
        if ($actual -ne $Sha256.ToLowerInvariant()) {
            throw "Hash mismatch for $OutFile. Expected $Sha256, got $actual"
        }
    }
}

function Get-GitHubLatestAssetUrl {
    param(
        [string]$Owner,
        [string]$Repo,
        [string]$NameRegex
    )
    $api = "https://api.github.com/repos/$Owner/$Repo/releases/latest"
    $release = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "Kindle-Jailbreak-Script" }
    $asset = $release.assets | Where-Object { $_.name -match $NameRegex } | Select-Object -First 1
    if (-not $asset) {
        throw "No matching asset found for $Owner/$Repo with regex $NameRegex"
    }
    return $asset.browser_download_url
}

function Download-LegacyPackages {
    $downloads = Join-Root "downloads"
    Invoke-Download "https://github.com/KindleModding/Winterbreak2/releases/download/v1.0.0/wb2.zip" (Join-Path $downloads "wb2.zip") "932ff113c414c9b0109b98d7f4b96da20815364fb4905e4483581b881b2ae2e2"
    Invoke-Download "https://github.com/KindleModding/Hotfix/releases/latest/download/Update_hotfix_universal.bin" (Join-Path $downloads "Update_hotfix_universal.bin") "94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59"
    Invoke-Download "https://kindlemodding.org/jailbreaking/post-jailbreak/installing-kual-mrpi/kual-mrinstaller-khf.zip" (Join-Path $downloads "kual-mrinstaller-khf.zip") "9974dfc2d1e7687b3fc74d68f6b5aeab2428f22d83ab82e6d600a0384c607d09"
    Invoke-Download "https://kindlemodding.org/jailbreaking/post-jailbreak/installing-kual-mrpi/Update_KUALBooklet_HDRepack.bin" (Join-Path $downloads "Update_KUALBooklet_HDRepack.bin") "a0cd1f490b2fc779457990cefa4a9ae53921fc8c2b5551f095500be3b55fc20a"
    Invoke-Download "https://github.com/koreader/koreader/releases/download/v2026.03/koreader-kindlepw2-v2026.03.zip" (Join-Path $downloads "koreader-kindlepw2-v2026.03.zip") "46e969bb13765b2630b5e14aa2e7fa2445ec551ccaa47db3efe644d0e34944b0"
}

function Download-ModernPackages {
    $downloads = Join-Root "downloads"
    Invoke-Download "https://github.com/KindleModding/Hotfix/releases/latest/download/Update_hotfix_universal.bin" (Join-Path $downloads "Update_hotfix_universal.bin") "94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59"
    Invoke-Download "https://fw.notmarek.com/khf/kual-mrinstaller-khf.tar.xz" (Join-Path $downloads "kual-mrinstaller-khf.tar.xz") ""
    $peki = Get-GitHubLatestAssetUrl "KindleTweaks" "PEKI" "\.zip$"
    $adbreak = Get-GitHubLatestAssetUrl "KindleModding" "AdBreak" "\.zip$"
    Invoke-Download $peki (Join-Path $downloads "PEKI-latest.zip") ""
    Invoke-Download $adbreak (Join-Path $downloads "AdBreak-latest.zip") ""
    Invoke-Download "https://build.koreader.rocks/download/stable/2026.03/koreader-kindlehf-v2026.03.zip" (Join-Path $downloads "koreader-kindlehf-v2026.03.zip") ""
}

function Expand-ZipClean {
    param([string]$Zip, [string]$Destination)
    $root = Get-ProjectRoot
    $dest = (Join-Path $root $Destination)
    if (-not ($dest.StartsWith($root))) { throw "Unsafe extract destination: $dest" }
    Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Expand-Archive -LiteralPath $Zip -DestinationPath $dest -Force
    return $dest
}

function Expand-TarClean {
    param([string]$Archive, [string]$Destination)
    $root = Get-ProjectRoot
    $dest = (Join-Path $root $Destination)
    if (-not ($dest.StartsWith($root))) { throw "Unsafe extract destination: $dest" }
    Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    & tar.exe -xf $Archive -C $dest
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe failed extracting $Archive"
    }
    return $dest
}

function Build-LegacyStaging {
    Download-LegacyPackages
    $downloads = Join-Root "downloads"
    $packages = Join-Root "packages"
    $staging = Join-Root "staging"

    $winter = Expand-ZipClean (Join-Path $downloads "wb2.zip") "packages\winterbreak2"
    $mrpi = Expand-ZipClean (Join-Path $downloads "kual-mrinstaller-khf.zip") "packages\mrpi"
    $koreader = Expand-ZipClean (Join-Path $downloads "koreader-kindlepw2-v2026.03.zip") "packages\koreader-kindlepw2-v2026.03"

    Remove-Item (Join-Path $staging "winterbreak2-root") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $staging "post-jailbreak-root") -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path (Join-Path $staging "winterbreak2-root") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $staging "post-jailbreak-root") -Force | Out-Null

    Copy-Item (Join-Path $winter "*") (Join-Path $staging "winterbreak2-root") -Recurse -Force
    Copy-Item (Join-Path $mrpi "extensions") (Join-Path $staging "post-jailbreak-root") -Recurse -Force
    Copy-Item (Join-Path $mrpi "mrpackages") (Join-Path $staging "post-jailbreak-root") -Recurse -Force
    Copy-Item (Join-Path $koreader "extensions\*") (Join-Path $staging "post-jailbreak-root\extensions") -Recurse -Force
    Copy-Item (Join-Path $koreader "koreader") (Join-Path $staging "post-jailbreak-root") -Recurse -Force
    Copy-Item (Join-Path $downloads "Update_hotfix_universal.bin") (Join-Path $staging "post-jailbreak-root") -Force
    Copy-Item (Join-Path $downloads "Update_KUALBooklet_HDRepack.bin") (Join-Path $staging "post-jailbreak-root\mrpackages") -Force

    Write-Host "Built legacy staging trees in $staging"
}

function Fill-OtaSpace {
    param([string]$Root, [int]$Leave)
    if ($Leave -lt 50) { throw "LeaveMiB should stay at least 50 MiB." }
    $folder = Join-Path $Root ".kindle-ota-space-filler"
    Remove-Item $folder -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $folder -Force | Out-Null

    $drive = Get-CimInstance Win32_LogicalDisk | Where-Object { "$($_.DeviceID)\" -ieq $Root } | Select-Object -First 1
    $leaveBytes = [int64]$Leave * 1MB
    $index = 0
    while ([int64]$drive.FreeSpace -gt ($leaveBytes + 64MB)) {
        $bytes = [Math]::Min(([int64]$drive.FreeSpace - $leaveBytes), [int64](1024MB))
        $file = Join-Path $folder ("filler-{0:D3}.bin" -f $index)
        Write-Host "Creating filler chunk $file ($([Math]::Round($bytes / 1MB)) MiB)"
        $stream = [System.IO.File]::Open($file, [System.IO.FileMode]::CreateNew)
        try {
            $stream.SetLength($bytes)
        } finally {
            $stream.Dispose()
        }
        $index++
        $drive = Get-CimInstance Win32_LogicalDisk | Where-Object { "$($_.DeviceID)\" -ieq $Root } | Select-Object -First 1
    }
}

function Remove-OtaFiller {
    param([string]$Root)
    Remove-Item (Join-Path $Root ".kindle-ota-space-filler") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $Root ".kindle-ota-space-filler.bin") -Force -ErrorAction SilentlyContinue
}

function Stage-WinterBreak2 {
    param([string]$Root)
    $info = Get-KindleInfo $Root
    $method = Get-RecommendedMethod $info.firmware
    if ($method -ne "winterbreak2" -and -not $Force) {
        throw "Firmware $($info.firmware) should not use WinterBreak2. Recommended method: $method. Use -Force only if you know this device is compatible."
    }
    Build-LegacyStaging
    $stage = Join-Root "staging\winterbreak2-root"
    Copy-Item (Join-Path $stage "*") $Root -Recurse -Force
    Write-Host "Staged WinterBreak2 files. Eject, then run https://winterbreak2.now.sh/ in the Kindle Experimental Browser."
}

function Stage-AdBreak {
    param([string]$Root)
    $info = Get-KindleInfo $Root
    $method = Get-RecommendedMethod $info.firmware
    if ($method -ne "adbreak-or-nosebleed" -and -not $Force) {
        throw "Firmware $($info.firmware) does not map to AdBreak in this script. Recommended method: $method."
    }
    if (-not $Force) {
        throw "StageAdBreak rewrites the Kindle ad .assets folder. Rerun with -Force after confirming the device is registered and ads are enabled."
    }

    Download-ModernPackages
    $downloads = Join-Root "downloads"
    $adbreakExtract = Expand-ZipClean (Join-Path $downloads "AdBreak-latest.zip") "packages\adbreak"

    $assets = Join-Path $Root "system\.assets"
    if (-not (Test-Path $assets)) {
        $assets = Join-Path $Root ".assets"
    }
    if (-not (Test-Path $assets)) {
        throw "Could not find Kindle .assets folder. Let the Kindle download ads first, then reconnect."
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = Join-Root ("device-backups\assets-{0}-{1}" -f ($info.serial -replace "[^A-Za-z0-9]", ""), $stamp)
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-Item $assets $backup -Recurse -Force

    $work = Join-Root "staging\adbreak-assets\.assets"
    Remove-Item (Split-Path $work -Parent) -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path (Split-Path $work -Parent) -Force | Out-Null
    Copy-Item $assets $work -Recurse -Force
    $adbreakHtml = Get-ChildItem $adbreakExtract -Filter "adbreak.html" -Recurse | Select-Object -First 1
    if (-not $adbreakHtml) {
        throw "AdBreak extracted, but adbreak.html was not found."
    }
    $adbreakPayload = $adbreakHtml.DirectoryName
    Copy-Item (Join-Path $adbreakPayload "*") $work -Recurse -Force

    $replace = Get-ChildItem $work -Filter "replace.bat" -Recurse | Select-Object -First 1
    if ($replace) {
        Push-Location $replace.DirectoryName
        try {
            & cmd.exe /c "`"$($replace.FullName)`""
        } finally {
            Pop-Location
        }
    } else {
        $adbreakHtml = Get-Item (Join-Path $work "adbreak.html")
        Get-ChildItem $work -Filter "details.html" -Recurse | ForEach-Object {
            Copy-Item $adbreakHtml.FullName $_.FullName -Force
        }
    }

    Remove-Item $assets -Recurse -Force
    Copy-Item $work (Split-Path $assets -Parent) -Recurse -Force
    Write-Host "Staged AdBreak assets. Eject, keep airplane mode on, then open a lockscreen ad and proceed through the popups."
}

function Stage-PostJailbreak {
    param([string]$Root)
    $info = Get-KindleInfo $Root
    $family = Get-KOReaderFamily $info.firmware
    if (-not $Force -and -not $info.winterbreakLog -and -not $info.extensions) {
        throw "No jailbreak marker was detected. Run with -Force only after the on-device jailbreak has completed."
    }

    Download-ModernPackages
    $downloads = Join-Root "downloads"
    $mrpi = Expand-TarClean (Join-Path $downloads "kual-mrinstaller-khf.tar.xz") "packages\mrpi-modern"
    $peki = Expand-ZipClean (Join-Path $downloads "PEKI-latest.zip") "packages\peki"
    $koreaderZip = Join-Path $downloads ("koreader-{0}-v2026.03.zip" -f $family)
    if (-not (Test-Path $koreaderZip)) {
        $koreaderZip = Join-Path $downloads "koreader-kindlepw2-v2026.03.zip"
    }
    $koreader = Expand-ZipClean $koreaderZip ("packages\koreader-{0}-v2026.03" -f $family)

    Remove-OtaFiller $Root
    New-Item -ItemType Directory -Path (Join-Path $Root "extensions") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $Root "mrpackages") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $Root "documents") -Force | Out-Null

    Copy-Item (Join-Path $downloads "Update_hotfix_universal.bin") $Root -Force
    Copy-Item (Join-Path $mrpi "extensions\*") (Join-Path $Root "extensions") -Recurse -Force
    Copy-Item (Join-Path $mrpi "mrpackages\*") (Join-Path $Root "mrpackages") -Recurse -Force
    Get-ChildItem $peki -Filter "KUAL.*" -Recurse | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $Root "documents") -Force
    }
    Copy-Item (Join-Path $koreader "extensions\*") (Join-Path $Root "extensions") -Recurse -Force
    Copy-Item (Join-Path $koreader "koreader") $Root -Recurse -Force

    Write-Host "Staged post-jailbreak files."
    Write-Host "Next: eject, install hotfix if required, run KUAL/PEKI, and launch KOReader."
}

function Eject-Kindle {
    param([string]$Root)
    $drive = $Root.Substring(0, 2)
    $shell = New-Object -ComObject Shell.Application
    $item = $shell.Namespace(17).ParseName($drive)
    if ($item) {
        $item.InvokeVerb("Eject")
        Write-Host "Requested eject for $drive"
    } else {
        Write-Host "Could not request GUI eject. Use Windows safe remove for $drive."
    }
}

$root = $null
if ($Action -notin @("DownloadLegacy", "DownloadModern", "BuildLegacy")) {
    $root = Assert-SafeKindleRoot (Resolve-KindleRoot $KindleRoot)
}

switch ($Action) {
    "Diagnose" {
        $info = Get-KindleInfo $root
        # Do not print a full serial or raw version text into terminals/logs.
        $info.Remove("versionText")
        $info.Remove("serial")
        $info["recommendedMethod"] = Get-RecommendedMethod $info.firmware
        $info["koreaderFamily"] = Get-KOReaderFamily $info.firmware
        $info | ConvertTo-Json -Depth 5
    }
    "DownloadLegacy" { Download-LegacyPackages }
    "DownloadModern" { Download-ModernPackages }
    "BuildLegacy" { Build-LegacyStaging }
    "Prepare" {
        $info = Get-KindleInfo $root
        $method = Get-RecommendedMethod $info.firmware
        Write-Host "Firmware: $($info.firmware)"
        Write-Host "Recommended method: $method"
        if ($method -eq "winterbreak") {
            Write-Host "This generic helper will not infer a device payload from firmware alone. For the audited PW5SE 5.15.1 use scripts\pw5se-winterbreak.ps1; for any other device use its current model-specific WinterBreak guide."
        } elseif ($method -eq "adbreak-or-nosebleed") {
            Write-Host "Use StageAdBreak -Force only after confirming ads are enabled on the registered Kindle."
        } else {
            Write-Host "This script will not auto-stage method '$method'. Check KindleModding first."
        }
    }
    "StageWinterBreak2" { Stage-WinterBreak2 $root }
    "StageAdBreak" { Stage-AdBreak $root }
    "StagePostJailbreak" { Stage-PostJailbreak $root }
    "FillOtaSpace" { Fill-OtaSpace $root $LeaveMiB }
    "RemoveOtaFiller" { Remove-OtaFiller $root }
    "Eject" { Eject-Kindle $root }
}
