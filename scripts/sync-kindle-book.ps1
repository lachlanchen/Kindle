[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Source,
    [string[]] $Collections = @("PocketPolished", "LinguaLeaf"),
    [string] $KindleRoot,
    [string] $ExpectedSha256
)

$ErrorActionPreference = "Stop"

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

$sourceItem = Get-Item -LiteralPath $Source
if ($sourceItem.PSIsContainer) {
    throw "Source must be one file, not a directory."
}
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceItem.FullName).Hash.ToLowerInvariant()
if ($ExpectedSha256 -and $sourceHash -ne $ExpectedSha256.ToLowerInvariant()) {
    throw "Source SHA-256 mismatch. Expected $ExpectedSha256, got $sourceHash"
}

$root = Resolve-KindleRoot $KindleRoot
$results = @()
$backupRoot = $null
foreach ($collection in $Collections) {
    if ([string]::IsNullOrWhiteSpace($collection) -or $collection -match "[\\/:*?`"<>|]" -or $collection -in @(".", "..")) {
        throw "Unsafe collection name: $collection"
    }
    $directory = Join-Path $root ("documents\" + $collection)
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $destination = Join-Path $directory $sourceItem.Name
    if (Test-Path -LiteralPath $destination) {
        $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($existingHash -eq $sourceHash) {
            $results += [ordered]@{ destination = $destination; status = "already-current"; sha256 = $sourceHash }
            continue
        }
        if (-not $backupRoot) {
            $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
            $backupRoot = Join-Path $projectRoot ("device-backups\book-sync-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        }
        $backup = Join-Path (Join-Path $backupRoot $collection) $sourceItem.Name
        New-Item -ItemType Directory -Path (Split-Path $backup -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $destination -Destination $backup -Force
    }
    Copy-Item -LiteralPath $sourceItem.FullName -Destination $destination -Force
    $copiedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
    if ($copiedHash -ne $sourceHash) {
        throw "Post-copy SHA-256 mismatch: $destination"
    }
    $results += [ordered]@{ destination = $destination; status = "copied"; sha256 = $copiedHash }
}

$results | ConvertTo-Json -Depth 4
