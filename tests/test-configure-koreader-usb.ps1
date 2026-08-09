$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}

function Assert-Throws {
    param([scriptblock] $Action, [string] $Message)
    $threw = $false
    try { & $Action } catch { $threw = $true }
    if (-not $threw) { throw $Message }
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$scriptPath = Join-Path $projectRoot "scripts\configure-koreader-usb.ps1"
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$errors
)
Assert-True ($errors.Count -eq 0) "The SSH configurator does not parse."
$scriptText = Get-Content -LiteralPath $scriptPath -Raw

foreach ($functionName in @(
    "Get-UsbAutoStartMarkerState",
    "Disable-KOReaderAutoStartFromUsb",
    "Get-ExpectedPublicKey",
    "Assert-ExclusiveAuthorizedKeyState",
    "Install-PinnedFileAtomically",
    "Install-ExclusiveAuthorizedKeyAtomically"
)) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $functionName
    }, $true))
    Assert-True ($functionAst.Count -eq 1) "Expected one $functionName definition."
    Invoke-Expression $functionAst[0].Extent.Text
}

Assert-True ($scriptText -notmatch "JAILBROKEN\.txt") "The old marker gate returned."
Assert-True ($scriptText -notmatch "(?im)(Copy-Item|Move-Item|New-Item|Remove-Item)[^\r\n]*emergency") `
    "The configurator mutates emergency.sh."
Assert-True ($scriptText -match "(?s)Install-PinnedFileAtomically.+Install-ExclusiveAuthorizedKeyAtomically") `
    "The exclusive key is not the final enabling install."
Assert-True ($scriptText -match "ConvertFrom-Json" -and $scriptText -match 'status\s+-cne\s+"verified"') `
    "The proof verifier JSON contract is not enforced."
Assert-True ($scriptText -match "secureSshPatchVerified") "Status does not verify the patch hash."
Assert-True ($scriptText -notmatch 'bootAutoStartSupported\s*=\s*\$false') `
    "Status still falsely reports that the accepted autostart design is unsupported."
Assert-True ($scriptText -match 'bootAutoStartVisibility\s*=\s*"usb_marker_only"' -and
    $scriptText -match 'bootAutoStartJobAudited\s*=\s*\$false') `
    "Status does not make its USB-only visibility boundary explicit."
Assert-True ($scriptText -match 'bootAutoStartUsbEnableSupported\s*=\s*\$false' -and
    $scriptText -match 'bootAutoStartEnableRequiresSshManager\s*=\s*\$true') `
    "Status does not reserve autostart enablement for the audited SSH manager."
Assert-True ($scriptText -match 'manage-koreader-autostart\.sh enable over SSH') `
    "USB enablement does not direct the operator to the audited SSH manager."
Assert-True (-not (Test-Path -LiteralPath (Join-Path $projectRoot "assets\koreader-lazy\emergency.sh"))) `
    "The unsafe emergency.sh asset is still present."

$disableFunction = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq "Disable-KOReaderAutoStartFromUsb"
}, $true))[0].Extent.Text
Assert-True ($disableFunction -match 'Move-Item\s+-LiteralPath\s+\$marker\.parkedPath\s+-Destination\s+\$marker\.activePath') `
    "USB disablement is not the exact parked-to-active same-directory rename."
Assert-True ($disableFunction -notmatch '(Remove-Item|\.Delete\s*\()') `
    "USB disablement can delete the persistent recovery marker."

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("kindle-configure-test-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $publicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMockKeyMaterialForOfflineTestsOnly kindle-test"
    $publicKeyFile = Join-Path $tempRoot "expected.pub"
    [IO.File]::WriteAllText($publicKeyFile, ($publicKey + "`n"), [Text.Encoding]::ASCII)
    Assert-True ((Get-ExpectedPublicKey $publicKeyFile) -ceq $publicKey) "A valid single key was not read exactly."

    $multipleKeyFile = Join-Path $tempRoot "multiple.pub"
    [IO.File]::WriteAllText($multipleKeyFile, ($publicKey + "`n" + $publicKey + "`n"), [Text.Encoding]::ASCII)
    Assert-Throws { Get-ExpectedPublicKey $multipleKeyFile | Out-Null } "Multiple public-key lines were accepted."

    $unicodeKeyFile = Join-Path $tempRoot "unicode.pub"
    [IO.File]::WriteAllText($unicodeKeyFile, ($publicKey + "-unicode-雪`n"), [Text.Encoding]::UTF8)
    Assert-Throws { Get-ExpectedPublicKey $unicodeKeyFile | Out-Null } "A non-ASCII public-key record was accepted."

    $sourcePatch = Join-Path $tempRoot "patch.lua"
    [IO.File]::WriteAllText($sourcePatch, "return {}`n", (New-Object Text.UTF8Encoding($false)))
    $patchHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePatch).Hash.ToLowerInvariant()
    $installedPatch = Join-Path $tempRoot "device\koreader\patches\managed.lua"
    Install-PinnedFileAtomically $sourcePatch $installedPatch $patchHash
    Install-PinnedFileAtomically $sourcePatch $installedPatch $patchHash
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $installedPatch).Hash.ToLowerInvariant() -ceq $patchHash) `
        "The pinned patch was not installed exactly."
    Assert-True (@(Get-ChildItem -LiteralPath (Split-Path $installedPatch -Parent) -Filter ".*.tmp" -Force).Count -eq 0) `
        "A patch transaction temporary file remained."
    [IO.File]::WriteAllText($installedPatch, "tampered`n", [Text.Encoding]::ASCII)
    Assert-Throws { Install-PinnedFileAtomically $sourcePatch $installedPatch $patchHash } `
        "A different existing patch was overwritten."

    $authorizedKeys = Join-Path $tempRoot "device\koreader\settings\SSH\authorized_keys"
    $captured = @(Install-ExclusiveAuthorizedKeyAtomically $authorizedKeys $publicKey 6>&1)
    Assert-True (($captured -join "`n") -notmatch [Regex]::Escape($publicKey)) "Public-key content leaked to output."
    Install-ExclusiveAuthorizedKeyAtomically $authorizedKeys $publicKey
    Assert-ExclusiveAuthorizedKeyState $authorizedKeys $publicKey
    Assert-True (@(Get-ChildItem -LiteralPath (Split-Path $authorizedKeys -Parent) -Filter ".authorized_keys.*.tmp" -Force).Count -eq 0) `
        "An authorized_keys transaction temporary file remained."

    $differentKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDifferentMockKeyMaterialOnly other"
    [IO.File]::WriteAllText($authorizedKeys, ($publicKey + "`n" + $differentKey + "`n"), [Text.Encoding]::ASCII)
    Assert-Throws { Install-ExclusiveAuthorizedKeyAtomically $authorizedKeys $publicKey } `
        "An additional authorized key was preserved."
    Assert-True ((Get-Content -LiteralPath $authorizedKeys).Count -eq 2) `
        "The rejected multi-key file was modified."

    [IO.File]::WriteAllText($authorizedKeys, ($publicKey + "`n" + $publicKey + "`n"), [Text.Encoding]::ASCII)
    Assert-Throws { Install-ExclusiveAuthorizedKeyAtomically $authorizedKeys $publicKey } `
        "A duplicate expected key was accepted."

    $markerRoot = Join-Path $tempRoot "markers"
    New-Item -ItemType Directory -Path $markerRoot | Out-Null
    $activeMarker = Join-Path $markerRoot "DISABLE_KOREADER_AUTOSTART"
    $parkedMarker = Join-Path $markerRoot "_DISABLE_KOREADER_AUTOSTART"

    $marker = Get-UsbAutoStartMarkerState $markerRoot
    Assert-True ($marker.state -ceq "unsafe_missing_both") "Missing markers were not reported as unsafe."
    Assert-Throws { Disable-KOReaderAutoStartFromUsb $markerRoot | Out-Null } `
        "USB disablement fabricated a missing recovery marker."
    Assert-True (-not (Test-Path -LiteralPath $activeMarker) -and -not (Test-Path -LiteralPath $parkedMarker)) `
        "The rejected missing-marker state was modified."

    $markerBytes = [byte[]](0, 1, 2, 127, 128, 254, 255)
    [IO.File]::WriteAllBytes($parkedMarker, $markerBytes)
    $beforeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $parkedMarker).Hash
    $marker = Get-UsbAutoStartMarkerState $markerRoot
    Assert-True ($marker.state -ceq "parked_job_audit_required") `
        "A parked marker was falsely reported as fully audited or enabled."
    $result = Disable-KOReaderAutoStartFromUsb $markerRoot
    Assert-True ($result.changed -and $result.state -ceq "disabled") `
        "The valid USB disable rename did not report its change."
    Assert-True ((Test-Path -LiteralPath $activeMarker -PathType Leaf) -and
        -not (Test-Path -LiteralPath $parkedMarker)) `
        "The valid USB disable rename did not establish the one-marker disabled state."
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $activeMarker).Hash -ceq $beforeHash) `
        "The USB disable rename changed the marker contents."
    $result = Disable-KOReaderAutoStartFromUsb $markerRoot
    Assert-True (-not $result.changed) "An already-disabled marker was not idempotent."

    Move-Item -LiteralPath $activeMarker -Destination $parkedMarker
    [IO.File]::WriteAllText($activeMarker, "second marker", [Text.Encoding]::ASCII)
    Assert-True ((Get-UsbAutoStartMarkerState $markerRoot).state -ceq "unsafe_both_present") `
        "The ambiguous two-marker state was not reported as unsafe."
    Assert-Throws { Disable-KOReaderAutoStartFromUsb $markerRoot | Out-Null } `
        "USB disablement modified an ambiguous two-marker state."
    Assert-True ((Test-Path -LiteralPath $activeMarker) -and (Test-Path -LiteralPath $parkedMarker)) `
        "The rejected two-marker state was modified."
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}

"PASS: KOReader exclusive-key configurator tests"
