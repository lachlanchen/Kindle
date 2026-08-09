[CmdletBinding()]
param(
    [ValidateSet("Configure", "EnableAutoStart", "DisableAutoStart", "Status")]
    [string] $Action = "Configure",
    [string] $KindleRoot,
    [string] $PublicKeyPath = (Join-Path $env:USERPROFILE ".ssh\kindle_pw5se.pub"),
    [switch] $EnableAutoStart,
    [switch] $ConfirmedAirplaneMode
)

$ErrorActionPreference = "Stop"
$SecureSshPatchSha256 = "6624414f7d1afca463bb98c6147a91f91d11b75d2fb682b258375450469fe264"
$KOReaderLauncherSha256 = "619e707a1dee8c36c1107af195a41c2c3f7f0d9b622b4e4cb5fbfcdae9c64e25"

function Resolve-KindleRoot {
    param([string] $Requested)
    if ($Requested) {
        $root = (Resolve-Path -LiteralPath $Requested).Path.TrimEnd("\") + "\"
    } else {
        $matches = @(
            Get-CimInstance Win32_LogicalDisk |
                Where-Object {
                    $_.DriveType -eq 2 -and
                    (Test-Path -LiteralPath (Join-Path $_.DeviceID "documents")) -and
                    (Test-Path -LiteralPath (Join-Path $_.DeviceID "system\version.txt"))
                }
        )
        if ($matches.Count -ne 1) {
            throw "Expected exactly one mounted Kindle; found $($matches.Count). Pass -KindleRoot explicitly."
        }
        $root = "$($matches[0].DeviceID)\"
    }
    if ($root -notmatch "^[A-Za-z]:\\$" -or -not (Test-Path -LiteralPath (Join-Path $root "documents"))) {
        throw "Refusing unsafe or non-Kindle root: $root"
    }
    $drive = Get-CimInstance Win32_LogicalDisk |
        Where-Object { "$($_.DeviceID)\" -ieq $root } |
        Select-Object -First 1
    if (-not $drive -or $drive.DriveType -ne 2) {
        throw "Refusing non-removable drive: $root"
    }
    $systemRoot = [IO.Path]::GetPathRoot($env:SystemRoot).TrimEnd("\") + "\"
    if ($root -ieq $systemRoot) {
        throw "Refusing the Windows system drive: $root"
    }
    return $root
}

function Get-UsbAutoStartMarkerState {
    param([Parameter(Mandatory = $true)][string] $Root)

    $activePath = Join-Path $Root "DISABLE_KOREADER_AUTOSTART"
    $parkedPath = Join-Path $Root "_DISABLE_KOREADER_AUTOSTART"
    $activePresent = Test-Path -LiteralPath $activePath
    $parkedPresent = Test-Path -LiteralPath $parkedPath
    $activeRegular = $false
    $parkedRegular = $false

    if ($activePresent) {
        $activeItem = Get-Item -LiteralPath $activePath -Force
        $activeRegular = (Test-Path -LiteralPath $activePath -PathType Leaf) -and
            -not [bool]($activeItem.Attributes -band [IO.FileAttributes]::ReparsePoint)
    }
    if ($parkedPresent) {
        $parkedItem = Get-Item -LiteralPath $parkedPath -Force
        $parkedRegular = (Test-Path -LiteralPath $parkedPath -PathType Leaf) -and
            -not [bool]($parkedItem.Attributes -band [IO.FileAttributes]::ReparsePoint)
    }

    $state = if ($activePresent -and $parkedPresent) {
        "unsafe_both_present"
    } elseif ($activePresent -and -not $activeRegular) {
        "unsafe_active_not_regular"
    } elseif ($parkedPresent -and -not $parkedRegular) {
        "unsafe_parked_not_regular"
    } elseif ($activeRegular) {
        "disabled"
    } elseif ($parkedRegular) {
        # USB storage exposes the marker but not the root-owned Upstart job.
        # Do not call this state enabled until the SSH manager audits the job.
        "parked_job_audit_required"
    } else {
        "unsafe_missing_both"
    }

    [pscustomobject][ordered]@{
        state = $state
        activePath = $activePath
        parkedPath = $parkedPath
        activePresent = $activePresent
        activeRegularFile = $activeRegular
        parkedPresent = $parkedPresent
        parkedRegularFile = $parkedRegular
    }
}

function Disable-KOReaderAutoStartFromUsb {
    param([Parameter(Mandatory = $true)][string] $Root)

    $marker = Get-UsbAutoStartMarkerState $Root
    if ($marker.state -ceq "disabled") {
        return [pscustomobject][ordered]@{
            changed = $false
            state = "disabled"
        }
    }
    if ($marker.state -cne "parked_job_audit_required") {
        throw "Refusing USB autostart change: marker state is '$($marker.state)'. Do not create, delete, or guess at either marker; audit through SSH."
    }

    # This same-directory rename is the entire USB recovery transaction. It
    # preserves the marker's type and contents; the marker is never deleted.
    Move-Item -LiteralPath $marker.parkedPath -Destination $marker.activePath
    $after = Get-UsbAutoStartMarkerState $Root
    if ($after.state -cne "disabled") {
        throw "The USB disable-marker rename did not establish the exact disabled state."
    }
    return [pscustomobject][ordered]@{
        changed = $true
        state = "disabled"
    }
}

function Install-PinnedFileAtomically {
    param(
        [Parameter(Mandatory = $true)][string] $Source,
        [Parameter(Mandatory = $true)][string] $Destination,
        [Parameter(Mandatory = $true)][string] $ExpectedSha256
    )

    if (Test-Path -LiteralPath $Destination) {
        if (-not (Test-Path -LiteralPath $Destination -PathType Leaf) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant() -cne
                $ExpectedSha256) {
            throw "Refusing to overwrite a different managed file at $Destination"
        }
        return
    }

    $parent = Split-Path $Destination -Parent
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = Join-Path $parent ("." + (Split-Path $Destination -Leaf) + "." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        Copy-Item -LiteralPath $Source -Destination $temporary
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant() -cne
            $ExpectedSha256) {
            throw "The temporary managed file failed its SHA-256 check."
        }
        Move-Item -LiteralPath $temporary -Destination $Destination
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant() -cne
            $ExpectedSha256) {
            throw "The installed managed file failed its SHA-256 check."
        }
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Assert-VerifiedKOReaderStage {
    param([Parameter(Mandatory = $true)][string] $Root)

    $verifier = Join-Path $PSScriptRoot "pw5se-winterbreak.ps1"
    if (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) {
        throw "The proof-bound KOReader verifier is missing: $verifier"
    }
    $json = (& $verifier -Action VerifyKOReaderStage -KindleRoot $Root 6>$null | Out-String).Trim()
    try {
        $result = $json | ConvertFrom-Json
    } catch {
        throw "The proof-bound KOReader verifier returned an invalid result."
    }
    if ([string]$result.status -cne "verified" -or
        [string]$result.stageStatus -cne "complete" -or
        [string]$result.proofMode -cnotin @("full-history-v1", "persistent-state-v2") -or
        [string]$result.otaFiller -cne "absent" -or
        [string]$result.rootUpdates -cne "absent" -or
        [string]$result.launcherSha256 -cne $KOReaderLauncherSha256) {
        throw "The proof-bound KOReader verifier did not return the required verified contract."
    }
}

function Get-ExpectedPublicKey {
    param([Parameter(Mandatory = $true)][string] $Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Public key not found: $Path"
    }
    $publicKey = (Get-Content -LiteralPath $Path -Raw).Trim()
    if ($publicKey -match "[\r\n]" -or
        $publicKey -cmatch "[^\x20-\x7e]" -or
        $publicKey -notmatch "^(ssh-ed25519|ssh-rsa|ecdsa-sha2-\S+)\s+[A-Za-z0-9+/]+={0,3}(?:\s+.*)?$") {
        throw "The supplied file does not look like exactly one OpenSSH public key."
    }
    return $publicKey
}

function Assert-ExclusiveAuthorizedKeyState {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $ExpectedPublicKey
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "The KOReader authorized_keys path is not a regular file."
    }
    $lines = @(Get-Content -LiteralPath $Path | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($lines.Count -ne 1 -or -not [StringComparer]::Ordinal.Equals($lines[0].Trim(), $ExpectedPublicKey)) {
        throw "Refusing to modify authorized_keys: it is not already absent or exactly the expected single fresh key. Review and migrate it explicitly."
    }
}

function Install-ExclusiveAuthorizedKeyAtomically {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $ExpectedPublicKey
    )

    Assert-ExclusiveAuthorizedKeyState $Path $ExpectedPublicKey
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return
    }

    $parent = Split-Path $Path -Parent
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = Join-Path $parent (".authorized_keys." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        [IO.File]::WriteAllText($temporary, ($ExpectedPublicKey + "`n"), [Text.Encoding]::ASCII)
        Assert-ExclusiveAuthorizedKeyState $temporary $ExpectedPublicKey
        Move-Item -LiteralPath $temporary -Destination $Path
        Assert-ExclusiveAuthorizedKeyState $Path $ExpectedPublicKey
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

$root = Resolve-KindleRoot $KindleRoot
$koreader = Join-Path $root "koreader"
$emergency = Join-Path $root "emergency.sh"

switch ($Action) {
    "Status" {
        $stageVerified = $false
        $stageError = $null
        try {
            Assert-VerifiedKOReaderStage $root
            $stageVerified = $true
        } catch {
            $stageError = $_.Exception.Message
        }
        $expectedKey = $null
        if (Test-Path -LiteralPath $PublicKeyPath -PathType Leaf) {
            try { $expectedKey = Get-ExpectedPublicKey $PublicKeyPath } catch {}
        }
        $authorizedKeys = Join-Path $koreader "settings\SSH\authorized_keys"
        $exclusiveExpectedKey = $false
        if ($expectedKey) {
            try {
                Assert-ExclusiveAuthorizedKeyState $authorizedKeys $expectedKey
                $exclusiveExpectedKey = Test-Path -LiteralPath $authorizedKeys -PathType Leaf
            } catch {}
        }
        $securePatch = Join-Path $koreader "patches\1-lazying-art-secure-ssh.lua"
        $secureSshPatchVerified = (Test-Path -LiteralPath $securePatch -PathType Leaf) -and
            ((Get-FileHash -Algorithm SHA256 -LiteralPath $securePatch).Hash.ToLowerInvariant() -ceq
                $SecureSshPatchSha256)
        $autoStartMarker = Get-UsbAutoStartMarkerState $root
        $autoStartNextBoot = if ($autoStartMarker.state -ceq "disabled") {
            "disabled_by_usb_marker"
        } elseif ($autoStartMarker.state -ceq "parked_job_audit_required") {
            "unknown_requires_ssh_job_audit"
        } else {
            "unsafe_marker_state"
        }
        [ordered]@{
            root = $root
            koreaderStageVerified = $stageVerified
            koreaderStageError = $stageError
            koreader = Test-Path -LiteralPath (Join-Path $koreader "koreader.sh")
            authorizedKeys = Test-Path -LiteralPath $authorizedKeys
            exclusiveExpectedKey = $exclusiveExpectedKey
            secureSshPatch = Test-Path -LiteralPath $securePatch
            secureSshPatchVerified = $secureSshPatchVerified
            emergencyHookPresent = Test-Path -LiteralPath $emergency
            bootAutoStartVisibility = "usb_marker_only"
            bootAutoStartMarkerState = $autoStartMarker.state
            bootAutoStartNextBoot = $autoStartNextBoot
            bootAutoStartUsbDisableSupported = $true
            bootAutoStartDisableAvailable = $autoStartMarker.state -cin @("disabled", "parked_job_audit_required")
            bootAutoStartUsbEnableSupported = $false
            bootAutoStartEnableRequiresSshManager = $true
            bootAutoStartJobAudited = $false
        } | ConvertTo-Json -Depth 4
    }
    "DisableAutoStart" {
        $result = Disable-KOReaderAutoStartFromUsb $root
        if ($result.changed) {
            Write-Host "Disabled KOReader boot autostart by preserving and renaming the parked marker to DISABLE_KOREADER_AUTOSTART."
        } else {
            Write-Host "KOReader boot autostart is already disabled by the regular DISABLE_KOREADER_AUTOSTART marker."
        }
        Write-Host "Safely eject USB storage, disconnect USB data, and reboot when ready."
    }
    "EnableAutoStart" {
        throw "USB storage cannot safely enable boot autostart because it cannot audit the root-owned Upstart job, runtime prerequisites, and pinned hash. Use manage-koreader-autostart.sh enable over SSH."
    }
    "Configure" {
        if ($EnableAutoStart) {
            throw "-EnableAutoStart is not available over USB. Use manage-koreader-autostart.sh enable over SSH so the root-owned Upstart job, runtime prerequisites, and pinned hash are audited first."
        }
        if (-not $ConfirmedAirplaneMode) {
            throw "Before configuring SSH: turn Airplane Mode ON, reconnect USB, then rerun with -ConfirmedAirplaneMode."
        }
        Assert-VerifiedKOReaderStage $root

        if (Test-Path -LiteralPath $emergency) {
            throw "Refusing to configure while emergency.sh exists. Remove it only after identifying its owner; commissioning requires this unsafe escape hook to be absent."
        }

        $publicKey = Get-ExpectedPublicKey $PublicKeyPath
        $sshDir = Join-Path $koreader "settings\SSH"
        $authorizedKeys = Join-Path $sshDir "authorized_keys"
        if ((Test-Path -LiteralPath $sshDir) -and
            -not (Test-Path -LiteralPath $sshDir -PathType Container)) {
            throw "The KOReader SSH settings path is not a directory."
        }
        Assert-ExclusiveAuthorizedKeyState $authorizedKeys $publicKey

        $assetRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\assets\koreader-lazy")).Path
        $sourcePatch = Join-Path $assetRoot "1-lazying-art-secure-ssh.lua"
        if (-not (Test-Path -LiteralPath $sourcePatch -PathType Leaf) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePatch).Hash.ToLowerInvariant() -cne
                $SecureSshPatchSha256) {
            throw "The secure-SSH patch asset is missing or does not match its pinned SHA-256."
        }
        $patchDir = Join-Path $koreader "patches"
        $destinationPatch = Join-Path $patchDir "1-lazying-art-secure-ssh.lua"
        if ((Test-Path -LiteralPath $patchDir) -and
            -not (Test-Path -LiteralPath $patchDir -PathType Container)) {
            throw "The KOReader patches path is not a directory."
        }
        # Install the inert settings patch first. The authorized key is the
        # final enabling write, so an interruption cannot leave a key without
        # its pinned key-only SSH policy.
        Install-PinnedFileAtomically $sourcePatch $destinationPatch $SecureSshPatchSha256
        Install-ExclusiveAuthorizedKeyAtomically $authorizedKeys $publicKey
        Assert-ExclusiveAuthorizedKeyState $authorizedKeys $publicKey
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $destinationPatch).Hash.ToLowerInvariant() -cne
            $SecureSshPatchSha256) {
            throw "The secure-SSH patch did not match its pinned SHA-256 after copying."
        }
        if (Test-Path -LiteralPath $emergency) {
            throw "emergency.sh appeared during SSH configuration; commissioning is not complete."
        }

        Write-Host "Installed the exclusive fresh public key and secure KOReader SSH defaults."
        Write-Host "USB configuration does not change autostart. Enable only through the audited SSH manager; USB DisableAutoStart remains available as a rename-only recovery action."
    }
}
