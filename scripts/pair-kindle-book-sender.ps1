[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $KindleIp,
    [ValidateRange(1, 65535)]
    [int] $Port = 2222,
    [string] $AdminPrivateKeyPath = (Join-Path $env:USERPROFILE ".ssh\kindle_pw5se"),
    [string] $AdminPublicKeyPath = (Join-Path $env:USERPROFILE ".ssh\kindle_pw5se.pub"),
    [string] $PortablePrivateKeyPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\Handoff\keys\kindle_handoff_rsa")),
    [string] $PortablePublicKeyPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\Handoff\keys\kindle_handoff_rsa.pub")),
    [string] $KnownHostsPath = (Join-Path $env:USERPROFILE ".ssh\known_hosts"),
    [ValidateRange(5, 300)]
    [int] $TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$PortablePublicKeySha256 = "2c855a602b748ba931123647a50d59d9fa43fd3acd6f1fb6acaf5fe7c1cbc2cf"
$RemoteAuthorizedKeys = "/mnt/us/koreader/settings/SSH/authorized_keys"

function Resolve-RequiredLocalFile {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Purpose
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Purpose is missing."
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Purpose must not be a reparse point."
    }
    return $item.FullName
}

function ConvertFrom-OpenSshPublicKeyLine {
    param(
        [Parameter(Mandatory = $true)][string] $Line,
        [Parameter(Mandatory = $true)][string] $Purpose
    )

    $pattern = '^(?<type>ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh[.]com|sk-ecdsa-sha2-nistp256@openssh[.]com) (?<blob>[A-Za-z0-9+/]+={0,2})(?: (?<comment>[\x21-\x7e][\x20-\x7e]*))?$'
    $match = [regex]::Match($Line, $pattern, [Text.RegularExpressions.RegexOptions]::CultureInvariant)
    if (-not $match.Success) {
        throw "$Purpose is not one exact OpenSSH public-key line."
    }
    try {
        $decoded = [Convert]::FromBase64String($match.Groups["blob"].Value)
    } catch {
        throw "$Purpose contains invalid OpenSSH key data."
    }
    if ($decoded.Length -eq 0) {
        throw "$Purpose contains empty OpenSSH key data."
    }
    return [pscustomobject][ordered]@{
        line = $Line
        identity = $match.Groups["type"].Value + " " + $match.Groups["blob"].Value
    }
}

function Read-ExactOpenSshPublicKeyFile {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Purpose
    )

    $resolved = Resolve-RequiredLocalFile $Path $Purpose
    $bytes = [IO.File]::ReadAllBytes($resolved)
    if (($bytes.Length -ge 3 -and $bytes[0] -eq 0xef -and $bytes[1] -eq 0xbb -and $bytes[2] -eq 0xbf) -or
        @($bytes | Where-Object { $_ -gt 0x7f }).Count -gt 0) {
        throw "$Purpose must be printable ASCII without a BOM."
    }
    $text = [Text.Encoding]::ASCII.GetString($bytes)
    $match = [regex]::Match($text, '\A(?<line>[^\r\n]+)(?:\r?\n)?\z', [Text.RegularExpressions.RegexOptions]::CultureInvariant)
    if (-not $match.Success) {
        throw "$Purpose must contain exactly one public-key line."
    }
    return ConvertFrom-OpenSshPublicKeyLine $match.Groups["line"].Value $Purpose
}

function New-ManagedAuthorizedKeySet {
    param(
        [Parameter(Mandatory = $true)] $AdminKey,
        [Parameter(Mandatory = $true)] $PortableKey
    )

    if ([StringComparer]::Ordinal.Equals([string]$AdminKey.identity, [string]$PortableKey.identity)) {
        throw "The admin recovery key and portable sender key are duplicates."
    }
    $byIdentity = @{}
    $byIdentity.Add([string]$AdminKey.identity, [string]$AdminKey.line)
    $byIdentity.Add([string]$PortableKey.identity, [string]$PortableKey.line)
    return [pscustomobject][ordered]@{
        admin = $AdminKey
        portable = $PortableKey
        byIdentity = $byIdentity
        content = [string]$AdminKey.line + "`n" + [string]$PortableKey.line + "`n"
    }
}

function ConvertFrom-AuthorizedKeysText {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string] $Text,
        [Parameter(Mandatory = $true)][string] $Purpose
    )

    if ($Text.Length -eq 0) {
        return @()
    }
    if ($Text.Contains("`r")) {
        throw "$Purpose is not canonical LF text."
    }
    $body = if ($Text.EndsWith("`n", [StringComparison]::Ordinal)) {
        $Text.Substring(0, $Text.Length - 1)
    } else {
        $Text
    }
    if ($body.Length -eq 0) {
        throw "$Purpose contains a blank line."
    }
    $records = @()
    foreach ($line in $body.Split([char]0x0a)) {
        if ($line.Length -eq 0) {
            throw "$Purpose contains a blank line."
        }
        $records += ConvertFrom-OpenSshPublicKeyLine $line $Purpose
    }
    return $records
}

function Assert-RemoteManagedSubset {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()] $Records,
        [Parameter(Mandatory = $true)] $ManagedSet
    )

    $seen = @{}
    foreach ($record in @($Records)) {
        $identity = [string]$record.identity
        if ($seen.ContainsKey($identity)) {
            throw "Remote authorized_keys contains a duplicate managed identity."
        }
        $seen.Add($identity, $true)
        if (-not $ManagedSet.byIdentity.ContainsKey($identity) -or
            -not [StringComparer]::Ordinal.Equals([string]$ManagedSet.byIdentity[$identity], [string]$record.line)) {
            throw "Remote authorized_keys contains an unknown or noncanonical key."
        }
    }
}

function ConvertFrom-RemoteKeyEnvelope {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string] $Text)

    $absent = "KBS1:ABSENT`n"
    $present = "KBS1:PRESENT`n"
    if ([StringComparer]::Ordinal.Equals($Text, $absent)) {
        return [pscustomobject][ordered]@{ state = "absent"; content = "" }
    }
    if ($Text.StartsWith($present, [StringComparison]::Ordinal)) {
        return [pscustomobject][ordered]@{ state = "present"; content = $Text.Substring($present.Length) }
    }
    throw "The remote authorized_keys reader returned an invalid envelope."
}

function Get-AsciiMd5 {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string] $Text)

    if ($Text -cmatch "[^\x00-\x7f]") {
        throw "Refusing to hash non-ASCII remote key state."
    }
    $md5 = [Security.Cryptography.MD5]::Create()
    try {
        $bytes = $md5.ComputeHash([Text.Encoding]::ASCII.GetBytes($Text))
    } finally {
        $md5.Dispose()
    }
    return ([BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
}

function Get-RemoteAuthorizedKeysReadCommand {
    return "set -eu; p='$RemoteAuthorizedKeys'; if [ -L `"`$p`" ]; then exit 41; fi; if [ -e `"`$p`" ]; then [ -f `"`$p`" ] || exit 42; printf 'KBS1:PRESENT\n'; cat `"`$p`"; else printf 'KBS1:ABSENT\n'; fi"
}

function New-RemoteAuthorizedKeysInstallCommand {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("absent", "present")][string] $ExpectedState,
        [string] $ExpectedCurrentMd5,
        [Parameter(Mandatory = $true)][string] $DesiredMd5
    )

    if ($DesiredMd5 -notmatch '^[0-9a-f]{32}$' -or
        ($ExpectedState -eq "present" -and $ExpectedCurrentMd5 -notmatch '^[0-9a-f]{32}$') -or
        ($ExpectedState -eq "absent" -and $ExpectedCurrentMd5)) {
        throw "The remote transaction hash preconditions are invalid."
    }
    $current = if ($ExpectedState -eq "present") { $ExpectedCurrentMd5 } else { "-" }
    return "set -eu; d='/mnt/us/koreader/settings/SSH'; p='$RemoteAuthorizedKeys'; expected_state='$ExpectedState'; expected_md5='$current'; desired_md5='$DesiredMd5'; [ -d `"`$d`" ] && [ ! -L `"`$d`" ] || exit 43; [ ! -L `"`$p`" ] || exit 44; if [ `"`$expected_state`" = absent ]; then [ ! -e `"`$p`" ] || exit 45; else [ -f `"`$p`" ] || exit 46; actual=`$(md5sum `"`$p`" | awk 'NR == 1 { print `$1 }'); [ `"`$actual`" = `"`$expected_md5`" ] || exit 47; fi; tmp=`"`$d/.authorized_keys.kbs.`$`$.tmp`"; [ ! -e `"`$tmp`" ] && [ ! -L `"`$tmp`" ] || exit 48; trap 'rm -f `"`$tmp`"' 0 1 2 15; umask 077; cat > `"`$tmp`"; actual=`$(md5sum `"`$tmp`" | awk 'NR == 1 { print `$1 }'); [ `"`$actual`" = `"`$desired_md5`" ] || exit 49; sync; mv -f `"`$tmp`" `"`$p`"; tmp=''; trap - 0 1 2 15; sync"
}

function ConvertTo-NativeWindowsArgument {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string] $Argument)

    if ($Argument.Length -gt 0 -and $Argument -notmatch '[\s"]') {
        return $Argument
    }
    $escaped = [regex]::Replace($Argument, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Invoke-CapturedProcess {
    param(
        [Parameter(Mandatory = $true)][string] $FilePath,
        [Parameter(Mandatory = $true)][string[]] $Arguments,
        [AllowNull()][string] $StandardInputText,
        [Parameter(Mandatory = $true)][string] $Purpose,
        [Parameter(Mandatory = $true)][int] $TimeoutSeconds
    )

    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath
    $start.Arguments = (@($Arguments | ForEach-Object { ConvertTo-NativeWindowsArgument $_ }) -join " ")
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $encoding = New-Object Text.UTF8Encoding($false)
    $start.StandardOutputEncoding = $encoding
    $start.StandardErrorEncoding = $encoding

    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) {
            throw "$Purpose could not start."
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if ($null -ne $StandardInputText) {
            $process.StandardInput.Write($StandardInputText)
        }
        $process.StandardInput.Close()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try { $process.Kill() } catch {}
            $process.WaitForExit()
            throw "$Purpose timed out."
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) {
            throw "$Purpose failed with ssh exit code $($process.ExitCode)."
        }
        return [pscustomobject][ordered]@{
            exitCode = $process.ExitCode
            stdout = $stdout
            stderrLength = $stderr.Length
        }
    } finally {
        $process.Dispose()
    }
}

function New-SshArguments {
    param(
        [Parameter(Mandatory = $true)][string] $PrivateKeyPath,
        [Parameter(Mandatory = $true)][string] $KnownHostsPath,
        [Parameter(Mandatory = $true)][string] $KindleIp,
        [Parameter(Mandatory = $true)][int] $Port,
        [Parameter(Mandatory = $true)][string] $RemoteCommand
    )

    return @(
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile=$KnownHostsPath",
        "-o", "IdentitiesOnly=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "RequestTTY=no",
        "-o", "ConnectTimeout=10",
        "-o", "ConnectionAttempts=1",
        "-o", "LogLevel=ERROR",
        "-i", $PrivateKeyPath,
        "-p", [string]$Port,
        "root@$KindleIp",
        $RemoteCommand
    )
}

function Assert-ValidKindleIp {
    param([Parameter(Mandatory = $true)][string] $Value)

    $address = $null
    if (-not [Net.IPAddress]::TryParse($Value, [ref]$address) -or
        $address.Equals([Net.IPAddress]::Any) -or
        $address.Equals([Net.IPAddress]::IPv6Any) -or
        [Net.IPAddress]::IsLoopback($address)) {
        throw "KindleIp must be a non-loopback numeric IP address."
    }
    return $address.ToString()
}

$normalizedIp = Assert-ValidKindleIp $KindleIp
$ssh = (Get-Command ssh.exe -CommandType Application -ErrorAction Stop).Source
$adminPrivate = Resolve-RequiredLocalFile $AdminPrivateKeyPath "Admin recovery private key"
$portablePrivate = Resolve-RequiredLocalFile $PortablePrivateKeyPath "Portable sender private key"
$adminPublic = Read-ExactOpenSshPublicKeyFile $AdminPublicKeyPath "Admin recovery public key"
$portablePublicPath = Resolve-RequiredLocalFile $PortablePublicKeyPath "Portable sender public key"
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $portablePublicPath).Hash.ToLowerInvariant() -cne $PortablePublicKeySha256) {
    throw "The portable sender public key is not the pinned published Handoff key."
}
$portablePublic = Read-ExactOpenSshPublicKeyFile $portablePublicPath "Portable sender public key"
$managed = New-ManagedAuthorizedKeySet $adminPublic $portablePublic

$knownHostsParent = Split-Path ([IO.Path]::GetFullPath($KnownHostsPath)) -Parent
if ((Test-Path -LiteralPath $knownHostsParent) -and -not (Test-Path -LiteralPath $knownHostsParent -PathType Container)) {
    throw "The known_hosts parent path is not a directory."
}
New-Item -ItemType Directory -Path $knownHostsParent -Force | Out-Null
$knownHosts = [IO.Path]::GetFullPath($KnownHostsPath)

$readCommand = Get-RemoteAuthorizedKeysReadCommand
$readArgs = New-SshArguments $adminPrivate $knownHosts $normalizedIp $Port $readCommand
$initial = Invoke-CapturedProcess $ssh $readArgs $null "Admin SSH authorized_keys read" $TimeoutSeconds
$envelope = ConvertFrom-RemoteKeyEnvelope $initial.stdout
$existing = @(ConvertFrom-AuthorizedKeysText $envelope.content "Remote authorized_keys")
Assert-RemoteManagedSubset $existing $managed

$currentMd5 = if ($envelope.state -eq "present") { Get-AsciiMd5 $envelope.content } else { $null }
$desiredMd5 = Get-AsciiMd5 $managed.content
$installCommand = New-RemoteAuthorizedKeysInstallCommand $envelope.state $currentMd5 $desiredMd5
$installArgs = New-SshArguments $adminPrivate $knownHosts $normalizedIp $Port $installCommand
Invoke-CapturedProcess $ssh $installArgs $managed.content "Admin SSH authorized_keys install" $TimeoutSeconds | Out-Null

$verify = Invoke-CapturedProcess $ssh $readArgs $null "Admin SSH authorized_keys verification" $TimeoutSeconds
$verifiedEnvelope = ConvertFrom-RemoteKeyEnvelope $verify.stdout
if ($verifiedEnvelope.state -cne "present" -or
    -not [StringComparer]::Ordinal.Equals([string]$verifiedEnvelope.content, [string]$managed.content)) {
    throw "Remote authorized_keys does not match the exact canonical managed set after installation."
}
$verifiedRecords = @(ConvertFrom-AuthorizedKeysText $verifiedEnvelope.content "Verified remote authorized_keys")
Assert-RemoteManagedSubset $verifiedRecords $managed
if ($verifiedRecords.Count -ne 2) {
    throw "Verified remote authorized_keys does not contain exactly two managed keys."
}

$portableArgs = New-SshArguments $portablePrivate $knownHosts $normalizedIp $Port "true"
Invoke-CapturedProcess $ssh $portableArgs $null "Portable sender BatchMode login test" $TimeoutSeconds | Out-Null

[ordered]@{
    status = "paired"
    managedKeyCount = 2
    adminRecoveryPreserved = $true
    portableSharedKey = "verified"
    portableLogin = "verified"
} | ConvertTo-Json -Depth 3
