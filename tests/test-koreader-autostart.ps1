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
$expectedJobSha256 = "2de0232b971926b7e70d913a27ba76168ed69760504ae2a90947e4402e7e5828"

Assert-True (Test-Path -LiteralPath $jobPath -PathType Leaf) "The owned Upstart job asset is missing."
Assert-True (Test-Path -LiteralPath $managerPath -PathType Leaf) "The fail-closed manager asset is missing."
Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $jobPath).Hash.ToLowerInvariant() -ceq $expectedJobSha256) `
    "The owned Upstart job changed without updating its pin and audit."

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

Assert-True ($job -match '(?m)^# Owner: lazying\.art kindle-pw5se-koreader-autostart v1$') `
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
Assert-True (([regex]::Matches($job, 'if \[ -e "\$\{DISABLE_MARKER\}" \] \|\| \[ -L "\$\{DISABLE_MARKER\}" \]; then')).Count -eq 2) `
    "The disable marker must be checked before and after the recovery delay."
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
$lastDisableIndex = $job.LastIndexOf('if [ -e "${DISABLE_MARKER}" ] || [ -L "${DISABLE_MARKER}" ]; then', [StringComparison]::Ordinal)
$execIndex = $job.LastIndexOf('exec /bin/sh "${KOREADER_LAUNCHER}" --asap', [StringComparison]::Ordinal)
Assert-True ($sleepIndex -ge 0 -and $sleepIndex -lt $lastDisableIndex -and $lastDisableIndex -lt $execIndex) `
    "The final disable-marker gate must remain after the delay and before launch."
Assert-True ($job -notmatch '(?m)^\s*(chmod|chown|rm|mv|cp|touch)\b') `
    "The boot job must not mutate persistent files."

Assert-True ($manager -match ('JOB_SHA256="' + [regex]::Escape($expectedJobSha256) + '"')) `
    "The manager does not pin the exact owned job."
Assert-True ($manager -match 'EXPECTED_FIRMWARE="5\.15\.1"') `
    "The manager is not gated to firmware 5.15.1."
Assert-True ($manager -match 'JOB_PATH="/etc/upstart/\$\{JOB_NAME\}\.conf"') `
    "The manager targets an unexpected Upstart path."
Assert-True ($manager -match 'DISABLE_MARKER="/mnt/us/DISABLE_KOREADER_AUTOSTART"' -and
    $manager -match 'PARKED_DISABLE_MARKER="/mnt/us/_DISABLE_KOREADER_AUTOSTART"') `
    "The active and parked marker names are not exact."
Assert-True ($manager -match 'assert_owned_or_absent_job' -and $manager -match 'foreign_upstart_job_refused') `
    "The manager does not visibly refuse foreign job content."
Assert-True ($manager -match 'trap cleanup 0' -and $manager -match 'mntroot ro') `
    "The manager lacks its root-filesystem restoration trap."
Assert-True ($manager -notmatch '(?m)^\s*(start|restart)\s+[^#]') `
    "The manager must never start KOReader or the Upstart job during installation."
Assert-True ($manager -notmatch '(?m)^\s*(rm|mv|cp|chmod|chown)[^\r\n]*emergency') `
    "The manager mutates emergency.sh."
Assert-True ($manager -notmatch '(?m)^\s*(rm|rmdir)[^\r\n]*(DISABLE_MARKER|PARKED_DISABLE_MARKER)') `
    "Enable/disable deletes a marker instead of parking it."
Assert-True ($manager -match 'ambiguous_both_present' -and
    $manager -match 'ambiguous_both_markers_refused' -and
    $manager -match 'unsafe_marker_type_refused_') `
    "The marker switch does not visibly refuse ambiguous or unsafe types."
Assert-True ($manager -match 'parked_disable_marker=\$\{parked_marker\}' -and
    $manager -match 'marker_switch=\$\{switch_state\}') `
    "Status does not expose both parked-marker state and the resolved switch state."

$installStart = $manager.IndexOf("install_job()", [StringComparison]::Ordinal)
$enableStart = $manager.IndexOf("enable_job()", [StringComparison]::Ordinal)
$disableStart = $manager.IndexOf("disable_job()", [StringComparison]::Ordinal)
$uninstallStart = $manager.IndexOf("uninstall_job()", [StringComparison]::Ordinal)
Assert-True ($installStart -ge 0 -and $enableStart -gt $installStart -and $disableStart -gt $enableStart -and $uninstallStart -gt $disableStart) `
    "Manager action functions are missing."
$installBody = $manager.Substring($installStart, $enableStart - $installStart)
$enableBody = $manager.Substring($enableStart, $disableStart - $enableStart)
$uninstallBody = $manager.Substring($uninstallStart, $manager.IndexOf("usage()", $uninstallStart, [StringComparison]::Ordinal) - $uninstallStart)
Assert-True ($installBody.IndexOf("ensure_disabled", [StringComparison]::Ordinal) -lt $installBody.IndexOf("begin_root_write", [StringComparison]::Ordinal)) `
    "Install must create/preserve the recovery marker before any root write."
Assert-True ($enableBody.IndexOf("assert_audited_runtime", [StringComparison]::Ordinal) -lt $enableBody.IndexOf("ensure_enabled", [StringComparison]::Ordinal) -and
    $enableBody.IndexOf("assert_owned_job", [StringComparison]::Ordinal) -lt $enableBody.IndexOf("ensure_enabled", [StringComparison]::Ordinal)) `
    "Enable must validate the runtime and exact owned job before parking recovery."
Assert-True ($uninstallBody.IndexOf("ensure_disabled", [StringComparison]::Ordinal) -lt $uninstallBody.IndexOf("begin_root_write", [StringComparison]::Ordinal)) `
    "Uninstall must restore the recovery marker before any root write."
Assert-True ($uninstallBody -match 'job_state' -and $uninstallBody -match 'foreign_upstart_job_refused') `
    "Uninstall must refuse foreign job content."
Assert-True ($manager -match 'initctl reload-configuration' -and $manager -match 'initctl status "\$\{JOB_NAME\}"') `
    "The manager does not verify that Upstart registered the installed job without starting it."
Assert-True ($manager -match 'initctl status kmc') `
    "The manager does not check the live firmware's supported Upstart 0.6.6 status command."

$renameStart = $manager.IndexOf("rename_marker_exact()", [StringComparison]::Ordinal)
$ensureEnabledStart = $manager.IndexOf("ensure_enabled()", [StringComparison]::Ordinal)
$statusStart = $manager.IndexOf("print_status()", [StringComparison]::Ordinal)
Assert-True ($renameStart -ge 0 -and $ensureEnabledStart -gt $renameStart -and $statusStart -gt $ensureEnabledStart) `
    "The parked-marker transaction functions are missing."
$renameBody = $manager.Substring($renameStart, $ensureEnabledStart - $renameStart)
$ensureEnabledBody = $manager.Substring($ensureEnabledStart, $statusStart - $ensureEnabledStart)
Assert-True ($renameBody -match 'mv "\$\{marker_from\}" "\$\{marker_to\}"' -and
    $renameBody -notmatch '(?m)^\s*(rm|rmdir)\b') `
    "Marker switching is not a preserving rename transaction."
Assert-True ($ensureEnabledBody -match '"\$\{DISABLE_MARKER\}"\s+\\\s*\r?\n\s*"\$\{PARKED_DISABLE_MARKER\}"' -and
    $ensureEnabledBody -match 'marker_switch_missing_refusing_enable') `
    "Enable does not rename active to parked or refuses a missing switch."
Assert-True ($manager -match '"\$\{PARKED_DISABLE_MARKER\}"\s+\\\s*\r?\n\s*"\$\{DISABLE_MARKER\}"' ) `
    "Disable does not rename parked back to active."

$shell = @(
    "C:\Program Files\Git\usr\bin\sh.exe",
    "C:\Program Files\Git\bin\bash.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($shell) {
    & $shell -n $managerPath
    Assert-True ($LASTEXITCODE -eq 0) "The manager failed shell syntax validation."
}

"PASS: fail-closed KOReader autostart asset tests"
