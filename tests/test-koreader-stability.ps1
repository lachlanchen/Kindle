[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$managerPath = Join-Path $projectRoot "assets\koreader-lazy\manage-koreader-stability.sh"
$expectedManagerSha256 = "dec93aa616d09587328af68e87efcd0d17e6119d8313186d51690128b5f93706"
$originalSha256 = "3a2d733a66f94e5cb1cc003c7ba736a03006e7c9242211adc243d74bc2c67db8"
$patchedSha256 = "8abc677d5eee22ae59f5454530eb79831f0e0f96717536edb76589de40f84ad5"

Assert-True (Test-Path -LiteralPath $managerPath -PathType Leaf) "The stability manager is missing."
Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $managerPath).Hash.ToLowerInvariant() -ceq
    $expectedManagerSha256) "The stability manager changed without updating its pin and audit."

$bytes = [IO.File]::ReadAllBytes($managerPath)
Assert-True ($bytes.Length -gt 0 -and $bytes[-1] -eq 10) "The stability manager must end with LF."
for ($index = 0; $index -lt ($bytes.Length - 1); $index++) {
    Assert-True (-not ($bytes[$index] -eq 13 -and $bytes[$index + 1] -eq 10)) `
        "The stability manager contains CRLF."
}

$manager = Get-Content -LiteralPath $managerPath -Raw
Assert-True ($manager -match 'EXPECTED_FIRMWARE="5\.15\.1"' -and
    $manager -match 'TARGET="/mnt/us/koreader/frontend/device/gesturedetector\.lua"') `
    "The manager is not gated to the audited firmware and exact source."
Assert-True ($manager -match ('ORIGINAL_SHA256="' + $originalSha256 + '"') -and
    $manager -match ('PATCHED_SHA256="' + $patchedSha256 + '"')) `
    "The exact original and patched source hashes are not pinned."
Assert-True ($manager -match 'ROLLBACK_DIR="/mnt/us/koreader/\.lazying-art-stability"' -and
    $manager -match 'gesturedetector-v2026\.07\.1\.original\.lua') `
    "The exact private rollback location is missing."
Assert-True ($manager -match 'if \[ -L "\$\{path\}" \]' -and
    $manager -match 'source_state_refused_' -and
    $manager -match 'rollback_state_refused_') `
    "The source and rollback type/hash gates are incomplete."
Assert-True ($manager -match 'empty_directory' -and
    $manager -match 'staged_original' -and
    $manager -match 'staged_partial' -and
    $manager -match 'unsafe_directory_contents') `
    "The durable rollback transaction states are incomplete."
Assert-True ($manager -match 'not self\.current_tev or not self\.initial_tev or' -and
    $manager -match 'not buddy_contact or not buddy_contact\.current_tev or not buddy_contact\.initial_tev' -and
    $manager -match 'return false') `
    "The narrow incomplete-contact guard is missing."
Assert-True ($manager -match 'matches != 1' -and
    $manager -match 'patched_candidate_hash_mismatch' -and
    $manager -match 'source_changed_before_publish') `
    "Patch generation or pre-publication validation is incomplete."
Assert-True ($manager -match 'mv -f "\$\{TARGET_TMP\}" "\$\{TARGET\}"' -and
    $manager -match 'trap cleanup 0' -and $manager -match 'sync') `
    "The same-directory atomic publication and cleanup transaction is incomplete."
Assert-True ($manager -match 'original:original\|original:empty_directory\|original:staged_original\|original:staged_partial' -and
    $manager -match 'finish_rollback_cleanup' -and
    $manager -match 'uninstall_final_state_not_exact' -and
    $manager -match 'rollback_directory_not_exactly_empty') `
    "Interrupted uninstall cannot resume to the exact original:absent state."
Assert-True ($manager -notmatch '(?m)^\s*(kill|killall|start|stop|restart|reboot|poweroff)\b') `
    "The stability manager can interrupt the running reader or device."

$sourcePath = Join-Path $projectRoot `
    "staging\koreader-kindlepw2-v2026.07.1\koreader\frontend\device\gesturedetector.lua"
$shell = @(
    "C:\Program Files\Git\usr\bin\sh.exe",
    "C:\Program Files\Git\bin\bash.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ceq
        $originalSha256) "The staged source no longer matches the pinned original."
    $source = [IO.File]::ReadAllText($sourcePath)
    $needle = "function Contact:isTwoFingerTap(buddy_contact)`n    local gesture_detector = self.ges_dec"
    $replacement = "function Contact:isTwoFingerTap(buddy_contact)`n" +
        "    if not self.current_tev or not self.initial_tev or`n" +
        "       not buddy_contact or not buddy_contact.current_tev or not buddy_contact.initial_tev then`n" +
        "        logger.warn(`"Contact:isTwoFingerTap ignored incomplete contact state`")`n" +
        "        return false`n    end`n`n    local gesture_detector = self.ges_dec"
    Assert-True (([regex]::Matches($source, [regex]::Escape($needle))).Count -eq 1) `
        "The guarded function is not unique in the staged source."
    $patchedBytes = [Text.Encoding]::UTF8.GetBytes($source.Replace($needle, $replacement))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $actualPatchedHash = ([BitConverter]::ToString($sha.ComputeHash($patchedBytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
    Assert-True ($actualPatchedHash -ceq $patchedSha256) `
        "The independently generated patched source does not match the manager pin."
}

if ($shell) {
        function Convert-ToGitShellPath {
            param([Parameter(Mandatory)][string] $Path)
            $full = [IO.Path]::GetFullPath($Path).Replace("\", "/")
            if ($full -match '^([A-Za-z]):(.*)$') {
                return "/$($Matches[1].ToLowerInvariant())$($Matches[2])"
            }
            return $full
        }

        $transactionRoot = Join-Path ([IO.Path]::GetTempPath()) `
            ("kindle-stability-transaction-" + [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $transactionRoot | Out-Null

        # Use a tiny deterministic source so interruption tests run in every
        # clean checkout; the real ignored upstream source is checked above
        # when available.
        $transactionSourcePath = Join-Path $transactionRoot "synthetic-gesturedetector.lua"
        $transactionManager = $manager
        $syntheticSource = "function Contact:isTwoFingerTap(buddy_contact)`n" +
            "    return true`nend`n"
        $syntheticGuard = "function Contact:isTwoFingerTap(buddy_contact)`n" +
            "    if not self.current_tev or not self.initial_tev or`n" +
            "       not buddy_contact or not buddy_contact.current_tev or not buddy_contact.initial_tev then`n" +
            "        logger.warn(`"Contact:isTwoFingerTap ignored incomplete contact state`")`n" +
            "        return false`n    end`n`n"
        $syntheticPatched = $syntheticSource.Replace(
            "function Contact:isTwoFingerTap(buddy_contact)`n",
            $syntheticGuard)
        [IO.File]::WriteAllText(
            $transactionSourcePath,
            $syntheticSource,
            [Text.UTF8Encoding]::new($false))
        $transactionOriginalSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $transactionSourcePath).Hash.ToLowerInvariant()
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $transactionPatchedSha256 = ([BitConverter]::ToString(
                $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($syntheticPatched)))).Replace("-", "").ToLowerInvariant()
        } finally {
            $sha.Dispose()
        }
        $transactionManager = $transactionManager.Replace(
            "ORIGINAL_SHA256=`"$originalSha256`"",
            "ORIGINAL_SHA256=`"$transactionOriginalSha256`"").Replace(
            "PATCHED_SHA256=`"$patchedSha256`"",
            "PATCHED_SHA256=`"$transactionPatchedSha256`"")

        function New-StabilityFixture {
            param([Parameter(Mandatory)][string] $Name)

            $caseRoot = Join-Path $transactionRoot $Name
            $target = Join-Path $caseRoot "koreader\frontend\device\gesturedetector.lua"
            $rollbackDir = Join-Path $caseRoot "koreader\.lazying-art-stability"
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath $transactionSourcePath -Destination $target

            $targetShell = Convert-ToGitShellPath $target
            $rollbackShell = Convert-ToGitShellPath $rollbackDir
            $harness = $transactionManager.Replace(
                'TARGET="/mnt/us/koreader/frontend/device/gesturedetector.lua"',
                "TARGET=`"$targetShell`"").Replace(
                'ROLLBACK_DIR="/mnt/us/koreader/.lazying-art-stability"',
                "ROLLBACK_DIR=`"$rollbackShell`"")
            $harness = [regex]::Replace(
                $harness,
                '(?ms)^firmware_version\(\) \{\r?\n.*?^\}\r?\n',
                "firmware_version() {`n    say `"5.15.1`"`n}`n")
            $harness = $harness.Replace(
                "    grep -q ' /mnt/us ' /proc/mounts || die `"userstore_not_mounted`"",
                "    : # test harness: isolated userstore is mounted")
            $harness = $harness.Replace("#!/bin/sh`n", "#!/bin/sh`nPATH=/usr/bin:/bin`n")
            $script = Join-Path $caseRoot "manage-koreader-stability.sh"
            [IO.File]::WriteAllText(
                $script,
                $harness,
                [Text.UTF8Encoding]::new($false))

            [pscustomobject]@{
                Root = $caseRoot
                Script = $script
                Target = $target
                RollbackDir = $rollbackDir
                Rollback = Join-Path $rollbackDir "gesturedetector-v2026.07.1.original.lua"
                Stage = Join-Path $rollbackDir ".gesturedetector-v2026.07.1.original.lua.stage"
            }
        }

        function Invoke-StabilityFixture {
            param(
                [Parameter(Mandatory)] $Fixture,
                [Parameter(Mandatory)][string] $Action,
                [int] $ExpectedExit = 0
            )
            $oldPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                $output = @(& $shell $Fixture.Script $Action 2>&1 | ForEach-Object { "$_" })
                $exitCode = $LASTEXITCODE
            } finally {
                $ErrorActionPreference = $oldPreference
            }
            Assert-True ($exitCode -eq $ExpectedExit) `
                "$Action exited $exitCode instead of $ExpectedExit. Output: $($output -join '; ')"
            return ($output -join "`n")
        }

        try {
            # Normal publication plus cleanup is the baseline transaction.
            $fixture = New-StabilityFixture "normal"
            $output = Invoke-StabilityFixture $fixture install
            Assert-True ($output -match 'result=installed_for_next_koreader_launch') `
                "Normal guard installation did not complete."
            Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $fixture.Target).Hash.ToLowerInvariant() -ceq
                $transactionPatchedSha256) "Normal installation did not publish the exact patch."
            Invoke-StabilityFixture $fixture uninstall | Out-Null
            Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $fixture.Target).Hash.ToLowerInvariant() -ceq
                $transactionOriginalSha256) "Normal uninstall did not restore the exact original."
            Assert-True (-not (Test-Path -LiteralPath $fixture.RollbackDir)) `
                "Normal uninstall did not reach exact original:absent."

            # Fault point: mkdir is durable, but no rollback file exists yet.
            $fixture = New-StabilityFixture "after-mkdir"
            New-Item -ItemType Directory -Path $fixture.RollbackDir | Out-Null
            Invoke-StabilityFixture $fixture install | Out-Null
            Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $fixture.Target).Hash.ToLowerInvariant() -ceq
                $transactionPatchedSha256) "Install did not resume after rollback-directory creation."

            # Fault point: a partial fixed staging copy survived hard interruption.
            $fixture = New-StabilityFixture "partial-stage"
            New-Item -ItemType Directory -Path $fixture.RollbackDir | Out-Null
            [IO.File]::WriteAllText($fixture.Stage, "partial", [Text.UTF8Encoding]::new($false))
            Invoke-StabilityFixture $fixture install | Out-Null
            Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $fixture.Target).Hash.ToLowerInvariant() -ceq
                $transactionPatchedSha256) "Install did not safely replace a partial owned stage."

            # Fault point: the exact staged original exists but was not renamed.
            $fixture = New-StabilityFixture "exact-stage"
            New-Item -ItemType Directory -Path $fixture.RollbackDir | Out-Null
            Copy-Item -LiteralPath $transactionSourcePath -Destination $fixture.Stage
            Invoke-StabilityFixture $fixture install | Out-Null
            Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $fixture.Target).Hash.ToLowerInvariant() -ceq
                $transactionPatchedSha256) "Install did not resume exact staged rollback publication."

            # Fault point: target restore completed, rollback cleanup did not.
            $fixture = New-StabilityFixture "after-target-restore"
            New-Item -ItemType Directory -Path $fixture.RollbackDir | Out-Null
            Copy-Item -LiteralPath $transactionSourcePath -Destination $fixture.Rollback
            Invoke-StabilityFixture $fixture uninstall | Out-Null
            Assert-True (-not (Test-Path -LiteralPath $fixture.RollbackDir)) `
                "Uninstall did not resume after exact target restoration."

            # Fault point: rollback was deleted, but the empty directory remained.
            $fixture = New-StabilityFixture "after-rollback-delete"
            New-Item -ItemType Directory -Path $fixture.RollbackDir | Out-Null
            Invoke-StabilityFixture $fixture uninstall | Out-Null
            Assert-True (-not (Test-Path -LiteralPath $fixture.RollbackDir)) `
                "Uninstall did not resume after rollback deletion."

            # A foreign entry must be preserved and must block a success result.
            $fixture = New-StabilityFixture "foreign-entry"
            New-Item -ItemType Directory -Path $fixture.RollbackDir | Out-Null
            Copy-Item -LiteralPath $transactionSourcePath -Destination $fixture.Rollback
            $foreign = Join-Path $fixture.RollbackDir "keep-foreign.txt"
            [IO.File]::WriteAllText($foreign, "foreign", [Text.UTF8Encoding]::new($false))
            $output = Invoke-StabilityFixture $fixture uninstall 1
            Assert-True ($output -match 'unsafe_directory_contents' -and
                (Test-Path -LiteralPath $foreign -PathType Leaf) -and
                (Test-Path -LiteralPath $fixture.Rollback -PathType Leaf)) `
                "Foreign rollback-directory content was not refused and preserved."
        } finally {
            $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
            $fullTransactionRoot = [IO.Path]::GetFullPath($transactionRoot)
            Assert-True ($fullTransactionRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase)) `
                "Refusing to clean a transaction fixture outside the temporary directory."
            Remove-Item -LiteralPath $fullTransactionRoot -Recurse -Force
        }
}

if ($shell) {
    & $shell -n $managerPath
    Assert-True ($LASTEXITCODE -eq 0) "The stability manager failed shell syntax validation."
}

"PASS: reversible KOReader gesture-stability guard tests"
