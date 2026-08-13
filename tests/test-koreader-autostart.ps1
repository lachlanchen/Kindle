[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$jobPath = Join-Path $projectRoot "assets\koreader-lazy\lazying-koreader-autostart.conf"
$managerPath = Join-Path $projectRoot "assets\koreader-lazy\manage-koreader-autostart.sh"
$expectedJobSha256 = "87381c8cb810b3e8606c97b5ad913a1be5f49c7a4ba6f46f66b6ae3e28e95dbd"
$expectedManagerSha256 = "453e7b368e270bdf7e540c9242538c0dfd43b1cfe854672944b124eed94493ff"
$legacyJobSha256 = "2de0232b971926b7e70d913a27ba76168ed69760504ae2a90947e4402e7e5828"

Assert-True (Test-Path -LiteralPath $jobPath -PathType Leaf) "The owned Upstart job asset is missing."
Assert-True (Test-Path -LiteralPath $managerPath -PathType Leaf) "The fail-closed manager asset is missing."
Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $jobPath).Hash.ToLowerInvariant() -ceq $expectedJobSha256) `
    "The owned Upstart job changed without updating its pin and audit."
Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $managerPath).Hash.ToLowerInvariant() -ceq $expectedManagerSha256) `
    "The autostart manager changed without updating its pin and audit."

foreach ($path in @($jobPath, $managerPath)) {
    $bytes = [IO.File]::ReadAllBytes($path)
    Assert-True ($bytes.Length -gt 0 -and $bytes[-1] -eq 10) "$path must end with LF."
    for ($index = 0; $index -lt ($bytes.Length - 1); $index++) {
        Assert-True (-not ($bytes[$index] -eq 13 -and $bytes[$index + 1] -eq 10)) `
            "$path contains CRLF; Kindle shell assets must use LF."
    }
}

$job = Get-Content -LiteralPath $jobPath -Raw
$manager = Get-Content -LiteralPath $managerPath -Raw

Assert-True ($job -match '(?m)^# Owner: lazying\.art kindle-pw5se-koreader-autostart v2$') `
    "The Upstart job lacks its exact ownership marker."
Assert-True ($job -match '(?m)^start on framework_ready$') `
    "The Upstart job no longer uses KMC's proven late one-shot boundary."
Assert-True ($job -match '(?m)^stop on stopping system$') "The Upstart job lacks a shutdown boundary."
Assert-True ($job -notmatch '(?m)^\s*(task|respawn)(\s|$)') `
    "The Upstart job must neither block boot as a task nor respawn after KOReader exits."
Assert-True ($job -match 'remaining=180' -and
    $job -match "grep -q ' /mnt/us ' /proc/mounts" -and
    $job -match 'initctl status lab126_gui' -and
    $job -match 'initctl status kppmainapp' -and
    $job -match '\[ -f /tmp/kppmainapp_started \]') `
    "The bounded mount and native-GUI readiness poll is incomplete."
Assert-True ($job -match '(?m)^\s*sleep 30 \|\| exit 0\s*$') "The required fail-closed post-ready recovery delay is missing."
Assert-True ($job -match 'DISABLE_MARKER="/mnt/us/DISABLE_KOREADER_AUTOSTART"' -and
    $job -match 'STANDARD_MARKER="/mnt/us/_DISABLE_KOREADER_AUTOSTART"' -and
    $job -match 'FRAMEWORK_STOP_MARKER="/mnt/us/_DISABLE_KOREADER_AUTOSTART_FRAMEWORK_STOP"') `
    "The exact disabled, standard, and framework-stop marker names are missing."
Assert-True (([regex]::Matches($job, 'mode="\$\(resolve_mode\)"')).Count -eq 2 -and
    $job -match 'present=\$\(\(present \+ 1\)\)' -and
    $job -match 'unsafe_count' -and $job -match 'unsafe_type') `
    "The job does not resolve exactly one regular-file mode before and after the delay."
Assert-True (([regex]::Matches($job, 'if \[ -e "\$\{EMERGENCY_SCRIPT\}" \] \|\| \[ -L "\$\{EMERGENCY_SCRIPT\}" \]; then')).Count -eq 2) `
    "The job must refuse a root emergency script before and after the delay."
Assert-True (([regex]::Matches($job, 'initctl status lab126_gui[^\r\n]*start/running')).Count -eq 1 -and
    ([regex]::Matches($job, 'initctl status kppmainapp[^\r\n]*start/running')).Count -eq 1) `
    "The native GUI jobs must be proven by the bounded initial readiness poll."
Assert-True (([regex]::Matches($job, 'pidof reader\.lua')).Count -eq 1) `
    "The job must reject an existing KOReader process immediately before launch."
Assert-True ($job -match 'phase=started' -and $job -match 'phase=native-ready' -and
    $job -match 'phase=readiness-timeout' -and $job -match 'phase=final-disabled' -and
    $job -match 'phase=final-emergency-blocked' -and $job -match 'phase=final-launcher-invalid' -and
    $job -match 'phase=already-running' -and $job -match 'phase=launching') `
    "The non-blocking syslog phase diagnostics are incomplete."
Assert-True ($job -match 'TRACE_FILE="/tmp/lazying-koreader-autostart\.trace"' -and
    $job -match '\[ -L "\$\{TRACE_FILE\}" \]' -and
    $job -notmatch 'TRACE_FILE="/mnt/') `
    "The reboot-scoped phase trace is missing or targets persistent user storage."
$sleepIndex = $job.IndexOf("sleep 30", [StringComparison]::Ordinal)
$lastModeIndex = $job.LastIndexOf('mode="$(resolve_mode)"', [StringComparison]::Ordinal)
$execIndex = $job.LastIndexOf('exec /bin/sh "${KOREADER_LAUNCHER}" "${launch_arg}"', [StringComparison]::Ordinal)
Assert-True ($sleepIndex -ge 0 -and $sleepIndex -lt $lastModeIndex -and $lastModeIndex -lt $execIndex) `
    "The final fail-closed mode gate must remain after the delay and before launch."
Assert-True ($job -match 'launch_arg="--asap"' -and $job -match 'launch_arg="--framework_stop"' -and
    $job -match 'phase=launching mode=\$\{mode\}') `
    "The two explicit launch modes or their trace are missing."
Assert-True ($job -match 'AMBIENT_AUTO_MARKER="/mnt/us/ENABLE_AMAZON_AUTO_BRIGHTNESS"' -and
    $job -match 'lipc-set-prop -iq -- com\.lab126\.powerd flAuto "\$\{ambient_auto\}"' -and
    $job -match 'phase=ambient-brightness-marker-unsafe' -and
    $job -match 'phase=ambient-brightness-applied mode=\$\{ambient_auto\}' -and
    $job -match 'phase=ambient-brightness-apply-failed mode=\$\{ambient_auto\}') `
    "Managed launches do not enforce manual ambient brightness with an exact regular-file opt-in."
Assert-True ($job -notmatch '(?m)^\s*(chmod|chown|rm|mv|cp|touch)\b') `
    "The boot job must not mutate persistent files."

Assert-True ($manager -match ('JOB_SHA256="' + [regex]::Escape($expectedJobSha256) + '"')) `
    "The manager does not pin the exact owned job."
Assert-True ($manager -match ('LEGACY_JOB_SHA256="' + [regex]::Escape($legacyJobSha256) + '"') -and
    $manager -match 'owned_legacy' -and $manager -match 'result=upgraded_disabled') `
    "The manager cannot safely recognize and upgrade the exact v1 owned job."
Assert-True ($manager -match 'ensure_legacy_fail_closed_before_marker_validation' -and
    $manager -match 'legacy_job_fail_closed_before_invalid_marker_refusal' -and
    $manager -match '\[ ! -e "\$\{DISABLE_MARKER\}" \] && \[ ! -L "\$\{DISABLE_MARKER\}" \]' -and
    $manager -match 'legacy_job_could_not_be_fail_closed') `
    "A malformed v2 marker topology can leave the exact legacy job boot-enabled."
Assert-True ($manager -match 'EXPECTED_FIRMWARE="5\.15\.1"') `
    "The manager is not gated to firmware 5.15.1."
Assert-True ($manager -match 'JOB_PATH="/etc/upstart/\$\{JOB_NAME\}\.conf"') `
    "The manager targets an unexpected Upstart path."
Assert-True ($manager -match 'DISABLE_MARKER="/mnt/us/DISABLE_KOREADER_AUTOSTART"' -and
    $manager -match 'STANDARD_MARKER="/mnt/us/_DISABLE_KOREADER_AUTOSTART"' -and
    $manager -match 'FRAMEWORK_STOP_MARKER="/mnt/us/_DISABLE_KOREADER_AUTOSTART_FRAMEWORK_STOP"') `
    "The disabled, standard, and framework-stop marker names are not exact."
Assert-True ($manager -match 'assert_owned_or_absent_job' -and $manager -match 'foreign_upstart_job_refused') `
    "The manager does not visibly refuse foreign job content."
Assert-True ($manager -match 'trap cleanup 0' -and $manager -match 'mntroot ro') `
    "The manager lacks its root-filesystem restoration trap."
Assert-True ($manager -notmatch '(?m)^\s*(start|restart)\s+[^#]') `
    "The manager must never start KOReader or the Upstart job during installation."
Assert-True ($manager -notmatch '(?m)^\s*(rm|mv|cp|chmod|chown)[^\r\n]*emergency') `
    "The manager mutates emergency.sh."
Assert-True ($manager -notmatch '(?m)^\s*(rm|rmdir)[^\r\n]*(DISABLE_MARKER|STANDARD_MARKER|FRAMEWORK_STOP_MARKER)') `
    "Enable/disable deletes a marker instead of parking it."
Assert-True ($manager -match 'ambiguous_multiple_present' -and
    $manager -match 'ambiguous_multiple_markers_refused' -and
    $manager -match 'unsafe_marker_type_refused_') `
    "The marker switch does not visibly refuse ambiguous or unsafe types."
Assert-True ($manager -match 'standard_marker=\$\{standard_marker\}' -and
    $manager -match 'framework_stop_marker=\$\{framework_stop_marker\}' -and
    $manager -match 'marker_switch=\$\{switch_state\}') `
    "Status does not expose both launch markers and the resolved switch state."

$installStart = $manager.IndexOf("install_job()", [StringComparison]::Ordinal)
$enableStart = $manager.IndexOf("enable_job()", [StringComparison]::Ordinal)
$disableStart = $manager.IndexOf("disable_job()", [StringComparison]::Ordinal)
$uninstallStart = $manager.IndexOf("uninstall_job()", [StringComparison]::Ordinal)
Assert-True ($installStart -ge 0 -and $enableStart -gt $installStart -and $disableStart -gt $enableStart -and $uninstallStart -gt $disableStart) `
    "Manager action functions are missing."
$installBody = $manager.Substring($installStart, $enableStart - $installStart)
$enableBody = $manager.Substring($enableStart, $disableStart - $enableStart)
$disableBody = $manager.Substring($disableStart, $uninstallStart - $disableStart)
$uninstallBody = $manager.Substring($uninstallStart, $manager.IndexOf("usage()", $uninstallStart, [StringComparison]::Ordinal) - $uninstallStart)
$installBridgeCall = $installBody.IndexOf("ensure_legacy_fail_closed_before_marker_validation", [StringComparison]::Ordinal)
$installDisableCall = $installBody.IndexOf("ensure_disabled", [StringComparison]::Ordinal)
$installRootWriteCall = $installBody.IndexOf("begin_root_write", [StringComparison]::Ordinal)
Assert-True ($installBridgeCall -ge 0 -and $installDisableCall -ge 0 -and
    $installRootWriteCall -ge 0 -and $installBridgeCall -lt $installDisableCall -and
    $installDisableCall -lt $installRootWriteCall) `
    "Install must create/preserve the recovery marker before any root write."
$legacyBridgeStart = $manager.IndexOf("ensure_legacy_fail_closed_before_marker_validation()", [StringComparison]::Ordinal)
$renameStart = $manager.IndexOf("rename_marker_exact()", [StringComparison]::Ordinal)
Assert-True ($legacyBridgeStart -ge 0 -and $renameStart -gt $legacyBridgeStart) `
    "The legacy fail-closed bridge is missing."
$legacyBridgeBody = $manager.Substring($legacyBridgeStart, $renameStart - $legacyBridgeStart)
Assert-True ($legacyBridgeBody -match ': >"\$\{DISABLE_MARKER\}"' -and
    $legacyBridgeBody -notmatch '(?m)^\s*(rm|rmdir|mv)\b') `
    "The legacy bridge must create an active stop marker without deleting or moving suspect markers."
Assert-True ($enableBody.IndexOf("assert_audited_runtime", [StringComparison]::Ordinal) -lt $enableBody.IndexOf("ensure_mode", [StringComparison]::Ordinal) -and
    $enableBody.IndexOf("assert_owned_job", [StringComparison]::Ordinal) -lt $enableBody.IndexOf("ensure_mode", [StringComparison]::Ordinal)) `
    "Enable must validate the runtime and exact owned job before parking recovery."
$disableBridgeCall = $disableBody.IndexOf("ensure_legacy_fail_closed_before_marker_validation", [StringComparison]::Ordinal)
$disableEnsureCall = $disableBody.IndexOf("ensure_disabled", [StringComparison]::Ordinal)
Assert-True ($disableBridgeCall -ge 0 -and $disableEnsureCall -ge 0 -and
    $disableBridgeCall -lt $disableEnsureCall) `
    "Disable must fail-close an exact legacy job before strict marker validation."
$uninstallBridgeCall = $uninstallBody.IndexOf("ensure_legacy_fail_closed_before_marker_validation", [StringComparison]::Ordinal)
$uninstallDisableCall = $uninstallBody.IndexOf("ensure_disabled", [StringComparison]::Ordinal)
$uninstallRootWriteCall = $uninstallBody.IndexOf("begin_root_write", [StringComparison]::Ordinal)
Assert-True ($uninstallBridgeCall -ge 0 -and $uninstallDisableCall -ge 0 -and
    $uninstallRootWriteCall -ge 0 -and $uninstallBridgeCall -lt $uninstallDisableCall -and
    $uninstallDisableCall -lt $uninstallRootWriteCall) `
    "Uninstall must restore the recovery marker before any root write."
Assert-True ($uninstallBody -match 'job_state' -and $uninstallBody -match 'foreign_upstart_job_refused') `
    "Uninstall must refuse foreign job content."
Assert-True ($manager -match 'initctl reload-configuration' -and $manager -match 'initctl status "\$\{JOB_NAME\}"') `
    "The manager does not verify that Upstart registered the installed job without starting it."
Assert-True ($manager -match 'initctl status kmc') `
    "The manager does not check the live firmware's supported Upstart 0.6.6 status command."

$ensureModeStart = $manager.IndexOf("ensure_mode()", [StringComparison]::Ordinal)
$statusStart = $manager.IndexOf("print_status()", [StringComparison]::Ordinal)
Assert-True ($renameStart -ge 0 -and $ensureModeStart -gt $renameStart -and $statusStart -gt $ensureModeStart) `
    "The parked-marker transaction functions are missing."
$renameBody = $manager.Substring($renameStart, $ensureModeStart - $renameStart)
$ensureModeBody = $manager.Substring($ensureModeStart, $statusStart - $ensureModeStart)
Assert-True ($renameBody -match 'mv "\$\{marker_from\}" "\$\{marker_to\}"' -and
    $renameBody -notmatch '(?m)^\s*(rm|rmdir)\b') `
    "Marker switching is not a preserving rename transaction."
Assert-True ($ensureModeBody -match '"\$\{DISABLE_MARKER\}"\s+\\\s*\r?\n\s*"\$\{requested_marker\}"' -and
    $ensureModeBody -match 'marker_switch_missing_refusing_enable' -and
    $ensureModeBody -match 'standard' -and $ensureModeBody -match 'framework_stop') `
    "Mode enablement cannot rename disabled to either explicit mode or refuses a missing switch."
Assert-True ($manager -match '"\$\{STANDARD_MARKER\}"\s+\\\s*\r?\n\s*"\$\{DISABLE_MARKER\}"' -and
    $manager -match '"\$\{FRAMEWORK_STOP_MARKER\}"\s+\\\s*\r?\n\s*"\$\{DISABLE_MARKER\}"') `
    "Disable cannot rename either enabled mode back to the active recovery marker."

$shell = @(
    "C:\Program Files\Git\usr\bin\sh.exe",
    "C:\Program Files\Git\bin\bash.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($shell) {
    & $shell -n $managerPath
    Assert-True ($LASTEXITCODE -eq 0) "The manager failed shell syntax validation."
}

"PASS: fail-closed KOReader autostart asset tests"
