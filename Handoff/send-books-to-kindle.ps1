[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0, ValueFromRemainingArguments = $true)]
    [string[]] $Path,

    [string] $KindleIp = "192.168.1.109",

    [int] $Port = 2222,

    [string] $Destination = "/mnt/us/documents/Books"
)

$ErrorActionPreference = "Stop"

$keyFile = Join-Path $PSScriptRoot "keys\kindle_handoff_rsa"
$sshExe = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$scpExe = Join-Path $env:WINDIR "System32\OpenSSH\scp.exe"

foreach ($required in @($keyFile, $sshExe, $scpExe)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required file not found: $required"
    }
}

$resolvedFiles = foreach ($item in $Path) {
    $resolved = Resolve-Path -LiteralPath $item
    if ((Get-Item -LiteralPath $resolved.Path).PSIsContainer) {
        throw "Folders are not accepted. Supply book files: $item"
    }
    $resolved.Path
}

$commonOptions = @(
    "-i", $keyFile,
    "-o", "IdentitiesOnly=yes",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new"
)

Write-Host "Preparing $Destination on $KindleIp..."
& $sshExe @commonOptions -p $Port "root@$KindleIp" "mkdir -p '$Destination'"
if ($LASTEXITCODE -ne 0) {
    throw "Could not prepare the Kindle destination. Start KOReader SSH and verify the IP."
}

foreach ($file in $resolvedFiles) {
    $remoteTarget = "root@$KindleIp" + ":" + $Destination + "/"
    Write-Host "Sending: $file"
    & $scpExe -O @commonOptions -P $Port $file $remoteTarget
    if ($LASTEXITCODE -ne 0) {
        throw "Transfer failed: $file"
    }
}

Write-Host "Transfer complete. Refresh KOReader's file browser."
