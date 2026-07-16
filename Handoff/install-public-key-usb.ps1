[CmdletBinding()]
param(
    [string] $DriveRoot
)

$ErrorActionPreference = "Stop"
$publicKeyFile = Join-Path $PSScriptRoot "keys\kindle_handoff_rsa.pub"

if (-not (Test-Path -LiteralPath $publicKeyFile)) {
    throw "Public key not found: $publicKeyFile"
}

if (-not $DriveRoot) {
    $matches = @(
        Get-PSDrive -PSProvider FileSystem |
            ForEach-Object { $_.Root } |
            Where-Object {
                (Test-Path -LiteralPath (Join-Path $_ "documents")) -and
                (Test-Path -LiteralPath (Join-Path $_ "koreader"))
            }
    )

    if ($matches.Count -ne 1) {
        throw "Exit KOReader so Kindle storage can appear, connect by USB, or pass -DriveRoot F:\ explicitly. To keep KOReader open, use the app's no-password Wi-Fi pairing instead."
    }
    $DriveRoot = $matches[0]
}

$documents = Join-Path $DriveRoot "documents"
$koreader = Join-Path $DriveRoot "koreader"
if (-not (Test-Path -LiteralPath $documents) -or -not (Test-Path -LiteralPath $koreader)) {
    throw "This does not look like the mounted KOReader Kindle: $DriveRoot"
}

$sshSettings = Join-Path $koreader "settings\SSH"
$authorizedKeys = Join-Path $sshSettings "authorized_keys"
New-Item -ItemType Directory -Path $sshSettings -Force | Out-Null

$publicKey = (Get-Content -LiteralPath $publicKeyFile -Raw).Trim()
$existing = if (Test-Path -LiteralPath $authorizedKeys) {
    Get-Content -LiteralPath $authorizedKeys -Raw
} else {
    ""
}

if ($existing -notlike "*$publicKey*") {
    $prefix = if ($existing.Length -gt 0 -and -not $existing.EndsWith([string][char]10)) {
        [Environment]::NewLine
    } else {
        ""
    }
    [IO.File]::AppendAllText(
        $authorizedKeys,
        $prefix + $publicKey + [Environment]::NewLine,
        [Text.Encoding]::ASCII
    )
    Write-Host "Installed the Kindle-only public key: $authorizedKeys"
} else {
    Write-Host "The Kindle-only public key is already installed."
}
