[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$latest = Join-Path $repoRoot "logs\latest-winterbreak-stage.txt"
if (Test-Path -LiteralPath $latest) {
    throw "Refusing to test while a real or incomplete staging record is active: $latest"
}

# Load the implementation without resolving or mutating a real Kindle.
. (Join-Path $repoRoot "scripts\pw5se-winterbreak.ps1") -Action Download -ConfirmedAirplaneMode

# Production correctly closes these legacy Store actions after any WB2 record
# exists. This isolated fake-root suite tests only their rollback mechanics, so
# assert the production gate is present and replace it only in this test scope.
$stageCommand = Get-Command Stage-WinterBreak -CommandType Function
if ($stageCommand.ScriptBlock.Ast.Extent.Text -notmatch "Assert-StoreRouteOpen") {
    throw "Stage-WinterBreak no longer contains the production Store-route guard."
}
function Assert-StoreRouteOpen {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)][string] $ActionName
    )
}

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("kindle-pw5se-stage-test-" + [Guid]::NewGuid().ToString("N"))
$recordRoot = $null

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
    }
}

function Get-TreeSignature {
    param([Parameter(Mandatory = $true)][string] $Root)
    $prefix = [IO.Path]::GetFullPath($Root).TrimEnd("\") + "\"
    $rows = @()
    foreach ($directory in Get-ChildItem -LiteralPath $Root -Directory -Recurse -Force) {
        $rows += "D|" + $directory.FullName.Substring($prefix.Length)
    }
    foreach ($file in Get-ChildItem -LiteralPath $Root -File -Recurse -Force) {
        $relative = $file.FullName.Substring($prefix.Length)
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
        $rows += "F|$relative|$hash"
    }
    return ($rows | Sort-Object) -join "`n"
}

try {
    New-Item -ItemType Directory -Path (Join-Path $testRoot "documents") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $testRoot "system") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $testRoot "mesquito") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $testRoot ".active_content_sandbox\store\resource\cachedResources\temp") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $testRoot "system\version.txt") -Value "Kindle 5.15.1 integration-test" -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $testRoot "mesquito\main.css") -Value "original-test-content" -Encoding ASCII
    $before = Get-TreeSignature $testRoot

    Stage-WinterBreak $testRoot
    foreach ($required in @(".active_content_sandbox", "apps\tech.hackerdude.winterbreak", "mesquito")) {
        if (-not (Test-Path -LiteralPath (Join-Path $testRoot $required))) {
            throw "Stage test missed required path: $required"
        }
    }
    if (-not (Test-Path -LiteralPath $latest)) {
        throw "Stage test did not create the active manifest pointer."
    }
    $manifestPath = (Get-Content -LiteralPath $latest -Raw).Trim()
    $recordRoot = Split-Path $manifestPath -Parent

    $restageBlocked = $false
    try {
        Stage-WinterBreak $testRoot
    } catch {
        if ($_.Exception.Message -match "already staged|active WinterBreak staging record") {
            $restageBlocked = $true
        } else {
            throw
        }
    }
    if (-not $restageBlocked) {
        throw "A second exploit stage unexpectedly succeeded."
    }

    Undo-WinterBreakStage $testRoot
    $after = Get-TreeSignature $testRoot
    if ($after -ne $before) {
        throw "Stage -> rollback did not restore the original mock tree."
    }
    if (Test-Path -LiteralPath $latest) {
        throw "Successful rollback left the active manifest pointer behind."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.status -ne "rolledBack") {
        throw "Expected rolledBack manifest status, got '$($manifest.status)'."
    }

    $filler = Join-Path $testRoot ".kindle-ota-space-filler"
    New-Item -ItemType Directory -Path $filler -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $filler ".lazying-art-filler-owner-v1"), "$FillerOwnerText`n", [Text.Encoding]::ASCII)
    [IO.File]::WriteAllBytes((Join-Path $filler "filler-000.bin"), [byte[]](0, 0, 0, 0))
    Remove-OtaFiller $testRoot
    if (Test-Path -LiteralPath $filler) {
        throw "Owned filler cleanup left its folder behind."
    }

    Write-Host "PASS WinterBreak stage, restage guard, exact rollback, and owned-filler cleanup"
} finally {
    if ((Test-Path -LiteralPath $latest) -and (Test-Path -LiteralPath $testRoot)) {
        $candidateManifest = (Get-Content -LiteralPath $latest -Raw).Trim()
        if (Test-Path -LiteralPath $candidateManifest -PathType Leaf) {
            $candidate = Get-Content -LiteralPath $candidateManifest -Raw | ConvertFrom-Json
            if ($candidate.deviceFingerprint -eq (Get-KindleFingerprint $testRoot)) {
                if (-not $recordRoot) { $recordRoot = Split-Path $candidateManifest -Parent }
                try { Undo-WinterBreakStage $testRoot } catch { Write-Warning $_.Exception.Message }
                if (Test-Path -LiteralPath $latest) {
                    Remove-Item -LiteralPath $latest -Force
                }
            }
        }
    }

    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd("\") + "\"
    $resolvedTest = [IO.Path]::GetFullPath($testRoot)
    if ($resolvedTest.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path $resolvedTest -Leaf) -like "kindle-pw5se-stage-test-*") {
        Remove-Item -LiteralPath $resolvedTest -Recurse -Force -ErrorAction SilentlyContinue
    }

    if ($recordRoot) {
        $backupPrefix = [IO.Path]::GetFullPath((Join-Path $repoRoot "device-backups")).TrimEnd("\") + "\"
        $resolvedRecord = [IO.Path]::GetFullPath($recordRoot)
        if ($resolvedRecord.StartsWith($backupPrefix, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path $resolvedRecord -Leaf) -like "winterbreak-stage-5.15.1-*") {
            Remove-Item -LiteralPath $resolvedRecord -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
