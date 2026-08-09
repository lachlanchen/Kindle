[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$implementation = Join-Path $projectRoot "scripts\pair-kindle-book-sender.ps1"

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}

function Assert-Throws {
    param(
        [Parameter(Mandatory = $true)][scriptblock] $Action,
        [Parameter(Mandatory = $true)][string] $Pattern,
        [Parameter(Mandatory = $true)][string] $Message
    )
    $threw = $false
    try { & $Action } catch {
        if ($_.Exception.Message -notmatch $Pattern) {
            throw "$Message Unexpected: $($_.Exception.Message)"
        }
        $threw = $true
    }
    if (-not $threw) { throw $Message }
}

$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($implementation, [ref]$tokens, [ref]$parseErrors)
Assert-True ($parseErrors.Count -eq 0) "The pairing script does not parse."
foreach ($functionAst in $ast.FindAll({
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst]
        }, $true)) {
    Invoke-Expression $functionAst.Extent.Text
}

$source = Get-Content -LiteralPath $implementation -Raw
$RemoteAuthorizedKeys = "/mnt/us/koreader/settings/SSH/authorized_keys"
$PortablePublicKeySha256 = "2c855a602b748ba931123647a50d59d9fa43fd3acd6f1fb6acaf5fe7c1cbc2cf"

try {
    $parameter = $ast.ParamBlock.Parameters |
        Where-Object { $_.Name.VariablePath.UserPath -ceq "KindleIp" } |
        Select-Object -First 1
    Assert-True ($null -ne $parameter -and $parameter.StaticType.Name -ceq "String") "KindleIp parameter is missing."
    $kindleIpAttributes = (@($parameter.Attributes | ForEach-Object { $_.Extent.Text }) -join " ")
    Assert-True ($kindleIpAttributes -match 'Mandatory\s*=\s*\$true') "KindleIp is not mandatory."
    Assert-True ($source -match [regex]::Escape("Handoff\keys\kindle_handoff_rsa")) "Portable Handoff key is not the default."
    Assert-True ($source -notmatch "LOCALAPPDATA") "The obsolete per-PC app-key default remains."
    Assert-True ($source -match [regex]::Escape($PortablePublicKeySha256)) "The published portable public key is not pinned."
    Assert-True ($source -notmatch '(?m)^ssh-(rsa|ed25519)\s+[A-Za-z0-9+/]') "Public-key content is embedded in the script."
    Assert-True ($source -match 'StrictHostKeyChecking=accept-new') "accept-new host-key policy is missing."
    Assert-True ($source -match 'UserKnownHostsFile=') "Known-hosts isolation is missing."
    Assert-True ($source -match 'BatchMode=yes') "BatchMode is missing."
    $subsetIndex = $source.LastIndexOf('Assert-RemoteManagedSubset $existing', [StringComparison]::Ordinal)
    $installIndex = $source.LastIndexOf('New-RemoteAuthorizedKeysInstallCommand $envelope.state', [StringComparison]::Ordinal)
    $verifyIndex = $source.LastIndexOf('Admin SSH authorized_keys verification', [StringComparison]::Ordinal)
    $portableLoginIndex = $source.LastIndexOf('Portable sender BatchMode login test', [StringComparison]::Ordinal)
    Assert-True ($subsetIndex -ge 0 -and $subsetIndex -lt $installIndex -and $installIndex -lt $verifyIndex -and $verifyIndex -lt $portableLoginIndex) `
        "Pairing transaction order is not visibly fail-closed."

    $publishedPrivate = Join-Path $projectRoot "Handoff\keys\kindle_handoff_rsa"
    $publishedPublic = "$publishedPrivate.pub"
    Assert-True (Test-Path -LiteralPath $publishedPrivate -PathType Leaf) "The published portable private key is missing."
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $publishedPublic).Hash.ToLowerInvariant() -ceq $PortablePublicKeySha256) `
        "The published portable public key changed from its pin."
    Read-ExactOpenSshPublicKeyFile $publishedPublic "published portable public key" | Out-Null

    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("kindle-pair-test-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    try {
        $adminLine = "ssh-ed25519 QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE= admin-recovery"
        $portableLine = "ssh-rsa QkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkI= portable-shared"
        $unknownLine = "ssh-ed25519 Q0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0M= unknown"
        $adminFile = Join-Path $tempRoot "admin.pub"
        $portableFile = Join-Path $tempRoot "portable.pub"
        [IO.File]::WriteAllText($adminFile, ($adminLine + "`n"), [Text.Encoding]::ASCII)
        [IO.File]::WriteAllText($portableFile, ($portableLine + "`r`n"), [Text.Encoding]::ASCII)
        $admin = Read-ExactOpenSshPublicKeyFile $adminFile "admin test key"
        $portable = Read-ExactOpenSshPublicKeyFile $portableFile "portable test key"
        Assert-True ([string]$admin.line -ceq $adminLine) "Admin key line was not preserved canonically."
        Assert-True ([string]$portable.line -ceq $portableLine) "Portable key line was not preserved canonically."

        $multiple = Join-Path $tempRoot "multiple.pub"
        [IO.File]::WriteAllText($multiple, ($adminLine + "`n" + $portableLine + "`n"), [Text.Encoding]::ASCII)
        Assert-Throws { Read-ExactOpenSshPublicKeyFile $multiple "multiple test key" | Out-Null } "exactly one" "Multiple key lines were accepted."
        $blank = Join-Path $tempRoot "blank.pub"
        [IO.File]::WriteAllText($blank, ($adminLine + "`n`n"), [Text.Encoding]::ASCII)
        Assert-Throws { Read-ExactOpenSshPublicKeyFile $blank "blank test key" | Out-Null } "exactly one" "A trailing blank line was accepted."
        $bom = Join-Path $tempRoot "bom.pub"
        [IO.File]::WriteAllText($bom, ($adminLine + "`n"), (New-Object Text.UTF8Encoding($true)))
        Assert-Throws { Read-ExactOpenSshPublicKeyFile $bom "BOM test key" | Out-Null } "without a BOM" "A BOM public key was accepted."
        $invalid = Join-Path $tempRoot "invalid.pub"
        [IO.File]::WriteAllText($invalid, "command=x $adminLine`n", [Text.Encoding]::ASCII)
        Assert-Throws { Read-ExactOpenSshPublicKeyFile $invalid "invalid test key" | Out-Null } "OpenSSH public-key line" "An authorized_keys option was accepted as a public-key file."

        $managed = New-ManagedAuthorizedKeySet $admin $portable
        Assert-True ([string]$managed.content -ceq ($adminLine + "`n" + $portableLine + "`n")) "Managed key order or LF canonicalization is wrong."
        $duplicatePortable = ConvertFrom-OpenSshPublicKeyLine ($admin.identity + " another-comment") "duplicate expected key"
        Assert-Throws { New-ManagedAuthorizedKeySet $admin $duplicatePortable | Out-Null } "duplicates" "Duplicate expected identities were accepted."

        Assert-RemoteManagedSubset @() $managed
        Assert-RemoteManagedSubset @(ConvertFrom-AuthorizedKeysText ($adminLine + "`n") "admin subset") $managed
        Assert-RemoteManagedSubset @(ConvertFrom-AuthorizedKeysText ($portableLine + "`n") "portable subset") $managed
        Assert-RemoteManagedSubset @(ConvertFrom-AuthorizedKeysText $managed.content "full managed set") $managed
        Assert-Throws {
            Assert-RemoteManagedSubset @(ConvertFrom-AuthorizedKeysText ($unknownLine + "`n") "unknown remote") $managed
        } "unknown or noncanonical" "An unknown remote key was accepted."
        Assert-Throws {
            Assert-RemoteManagedSubset @(ConvertFrom-AuthorizedKeysText ($adminLine + "`n" + $adminLine + "`n") "duplicate remote") $managed
        } "duplicate" "A duplicate remote key was accepted."
        Assert-Throws {
            Assert-RemoteManagedSubset @(ConvertFrom-AuthorizedKeysText ($admin.identity + " changed-comment`n") "changed comment") $managed
        } "unknown or noncanonical" "A noncanonical expected key line was accepted."
        Assert-Throws { ConvertFrom-AuthorizedKeysText ($adminLine + "`n`n") "blank remote" | Out-Null } "blank line" "A blank remote line was accepted."

        $absent = ConvertFrom-RemoteKeyEnvelope "KBS1:ABSENT`n"
        Assert-True ([string]$absent.state -ceq "absent" -and [string]$absent.content -ceq "") "Absent envelope was parsed incorrectly."
        $present = ConvertFrom-RemoteKeyEnvelope ("KBS1:PRESENT`n" + $adminLine + "`n")
        Assert-True ([string]$present.state -ceq "present" -and [string]$present.content -ceq ($adminLine + "`n")) "Present envelope was parsed incorrectly."
        Assert-Throws { ConvertFrom-RemoteKeyEnvelope "KBS1:PRESENT-BAD`n" | Out-Null } "invalid envelope" "An invalid remote envelope was accepted."

        $desiredMd5 = Get-AsciiMd5 $managed.content
        $installCommand = New-RemoteAuthorizedKeysInstallCommand "absent" $null $desiredMd5
        Assert-True ($installCommand -match 'cat > "\$tmp"') "Remote install does not consume canonical keys from stdin."
        Assert-True ($installCommand -match 'mv -f "\$tmp" "\$p"') "Remote install is not a same-directory temp+mv transaction."
        Assert-True ($installCommand -match 'md5sum "\$tmp"') "Remote install does not verify stdin before publication."
        Assert-True ($installCommand -match "trap 'rm -f") "Remote install does not clean its temporary file."
        Assert-True ($installCommand -notmatch [regex]::Escape($adminLine) -and $installCommand -notmatch [regex]::Escape($portableLine)) `
            "Public-key content leaked into the remote command."
        Assert-Throws { New-RemoteAuthorizedKeysInstallCommand "present" "bad" $desiredMd5 | Out-Null } "hash preconditions" "An invalid remote snapshot hash was accepted."

        $sshArgs = New-SshArguments "C:\Keys\admin key" "C:\Users\Tester\known hosts" "192.0.2.10" 2222 "true"
        Assert-True ($sshArgs -contains "BatchMode=yes") "SSH arguments omit BatchMode."
        Assert-True ($sshArgs -contains "StrictHostKeyChecking=accept-new") "SSH arguments omit accept-new."
        Assert-True ($sshArgs -contains "UserKnownHostsFile=C:\Users\Tester\known hosts") "SSH arguments omit the requested known_hosts file."
        Assert-True ($sshArgs -contains "root@192.0.2.10" -and $sshArgs -contains "2222") "SSH target or port is wrong."
        Assert-True (($sshArgs -join " ") -notmatch [regex]::Escape($adminLine)) "Public-key content leaked into SSH arguments."
        Assert-True ((Assert-ValidKindleIp "192.0.2.10") -ceq "192.0.2.10") "A numeric Kindle IP was rejected."
        Assert-Throws { Assert-ValidKindleIp "host;command" | Out-Null } "numeric IP" "A command-like KindleIp was accepted."
        Assert-Throws { Assert-ValidKindleIp "127.0.0.1" | Out-Null } "non-loopback" "Loopback KindleIp was accepted."

        $mockSecret = "ssh-rsa PUBLIC_MATERIAL_MUST_NOT_ESCAPE"
        $success = Invoke-CapturedProcess $env:ComSpec @("/d", "/c", "more") ($mockSecret + "`n") "local capture test" 10
        Assert-True ($success.exitCode -eq 0 -and $success.stdout -match "PUBLIC_MATERIAL") "Captured-process stdin/stdout handling failed."
        $failureMessage = $null
        try {
            Invoke-CapturedProcess $env:ComSpec @("/d", "/c", "echo $mockSecret & exit /b 7") $null "local failure test" 10 | Out-Null
        } catch {
            $failureMessage = $_.Exception.Message
        }
        Assert-True ($failureMessage -match "exit code 7") "External nonzero exit was not surfaced."
        Assert-True ($failureMessage -notmatch "PUBLIC_MATERIAL") "Captured process output leaked through an error."
    } finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }

    "PASS: Kindle Book Sender portable-key pairing tests"
} catch {
    throw
}
