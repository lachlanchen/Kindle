[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$patchPath = Join-Path $projectRoot "assets\koreader-lazy\2-lazying-art-ambient-brightness.lua"
$configuratorPath = Join-Path $projectRoot "scripts\configure-koreader-usb.ps1"
$expectedSha256 = "b762305949d6c06cd3bd1415a689e058959ed502ebcff9c69b91810c0302fb0c"

Assert-True (Test-Path -LiteralPath $patchPath -PathType Leaf) `
    "The ambient-brightness user patch is missing."
Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $patchPath).Hash.ToLowerInvariant() -ceq $expectedSha256) `
    "The ambient-brightness user patch changed without updating its pin and audit."

$bytes = [IO.File]::ReadAllBytes($patchPath)
Assert-True ($bytes.Length -gt 0 -and $bytes[-1] -eq 10) "The Lua patch must end with LF."
for ($index = 0; $index -lt ($bytes.Length - 1); $index++) {
    Assert-True (-not ($bytes[$index] -eq 13 -and $bytes[$index + 1] -eq 10)) `
        "The Lua patch contains CRLF."
}

$patch = Get-Content -LiteralPath $patchPath -Raw
$configurator = Get-Content -LiteralPath $configuratorPath -Raw
Assert-True ($patch -match 'Device\.model ~= "KindlePaperWhite5SE"') `
    "The patch is not gated to the audited PW5SE model."
Assert-True ($patch -match 'opt_in_path = "/mnt/us/ENABLE_AMAZON_AUTO_BRIGHTNESS"' -and
    $patch -match 'lfs\.symlinkattributes\(opt_in_path, "mode"\) == "file" and 1 or 0') `
    "The default-manual, exact regular-file ambient-auto opt-in is missing."
Assert-True ($patch -match 'set_int_property\("com\.lab126\.powerd", "flAuto", desired\)') `
    "The patch does not use powerd's typed LIPC ambient-auto property."
Assert-True ($patch -match 'local original_after_resume = powerd\.afterResume' -and
    $patch -match 'original_after_resume\(self, \.\.\.\)' -and
    $patch -match 'UIManager:scheduleIn\(1, function\(\) applyAutoMode\("resume"\) end\)') `
    "The patch does not preserve KOReader resume handling and defer the ambient mode until restoration settles."
Assert-True ($patch -match 'UIManager:scheduleIn\(0, function\(\) applyAutoMode\("startup"\) end\)') `
    "The patch does not apply the selected ambient mode at startup."
Assert-True ($patch -notmatch '/sys/class/backlight|setWarmth|currentAmberLevel|amberSched') `
    "The ambient-brightness patch writes hardware paths or changes warmth controls."

Assert-True ($configurator -match ('AmbientBrightnessPatchSha256 = "' + [regex]::Escape($expectedSha256) + '"') -and
    $configurator -match '2-lazying-art-ambient-brightness\.lua' -and
    $configurator -match 'ambientBrightnessPatchVerified') `
    "The USB configurator does not install and report the exact pinned patch."

"PASS: PW5SE KOReader ambient-brightness guard tests"
