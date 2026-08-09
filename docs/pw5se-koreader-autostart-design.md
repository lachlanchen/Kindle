# PW5SE 5.15.1 KOReader autostart: guarded design and recovery

This is the audited design for the personally owned Paperwhite 11th generation
/ PW5SE on firmware `5.15.1`. It is not a generic Kindle boot hook. Earlier job
revisions failed safely, were disabled, and were uninstalled. The
production bounded-polling job below has now passed automatic boot, normal exit,
and no-respawn validation with USB data disconnected.

## Decision

Use one independently owned Upstart service:

- repository asset:
  `assets/koreader-lazy/lazying-koreader-autostart.conf`
- installed path: `/etc/upstart/lazying-koreader.conf`
- production pinned SHA-256:
  `2de0232b971926b7e70d913a27ba76168ed69760504ae2a90947e4402e7e5828`
- guarded manager:
  `assets/koreader-lazy/manage-koreader-autostart.sh`
- active recovery marker: `/mnt/us/DISABLE_KOREADER_AUTOSTART`
- parked marker: `/mnt/us/_DISABLE_KOREADER_AUTOSTART`

Do not use `/mnt/us/emergency.sh`. Universal Hotfix treats that name as its own
escape hatch and returns before normal KMC/MKK repair work whenever it exists.
The manager and boot job only test for `emergency.sh`; neither creates, changes,
executes, or removes it.

The marker is never deleted. Disabling renames the parked marker to
`DISABLE_KOREADER_AUTOSTART`; enabling renames it back to
`_DISABLE_KOREADER_AUTOSTART`, and only after the exact job/runtime audit. The
file-or-directory type and any contents are preserved. Both names present,
neither name present, a symlink, or another special file is unsafe and blocks
enablement. The boot job checks only the active name, while the manager also
requires the parked name to prove a valid enabled state.

## Live validation and accepted status on 2026-08-09

- The 249-book Nutstore migration completed before the root installation.
- The original exact job, SHA-256
  `e2815566c94ca3bce41b1cd5ae567776991a5915720a168f2beb4a3833dd84a7`,
  was installed at the pinned path and registered with Upstart. The root
  filesystem was verified read-only again afterward.
- A reboot in that disabled state reached the native Kindle interface.
  KOReader did not start and TCP port `2222` was unavailable, which is the
  required native-only behavior for the marker path.
- After manual KOReader/SSH recovery, the original job was enabled and rebooted.
  It again reached the native interface, with no job log: Upstart never started
  the job. This was a safe failure, not a KOReader launch failure.
- Live inspection confirmed that stock `/etc/upstart/home_wait.conf`
  starts on `dbus_ready` and immediately subscribes for
  `com.lab126.appmgrd appStarted` with a 180-second timeout. The original custom
  condition waited for later GUI jobs, so it was both over-constrained for
  Upstart 0.6.6 and too late to mirror the stock event-listener boundary.
- The original job was put back into its disabled state and uninstalled. A
  second candidate, SHA-256
  `e3dba764ae08e2f95669a29997bd6d318d0615cf08c75a61dec0f3f52d40ed82`,
  started on `dbus_ready` and matched the stock 180-second LIPC wait. Its live
  reboot established that this event occurs before `/mnt/us` is ready on this
  Kindle, so its early USB launcher/marker gates failed closed before the
  userstore became available. It too was safely disabled and uninstalled.
- Later bounded-polling iterations exposed two more fail-closed boundaries:
  USB data/Drive Mode can export `/mnt/us` while the boot job needs the KOReader
  launcher and markers, and transient native jobs can change state during the
  30-second recovery window. The production job therefore uses the exact late
  `framework_ready` event, polls the complete native/userstore readiness set
  once, and rechecks only safety-critical gates immediately before launch.
- With the USB data connection removed before reboot, the exact production job
  emitted `phase=started`, `phase=native-ready`, and `phase=launching`; Upstart
  reported `lazying-koreader start/running`, and `reader.lua` was running.
  Wi-Fi and SSH returned. The enabled marker state was exactly a regular
  `/mnt/us/_DISABLE_KOREADER_AUTOSTART` file with the active
  `/mnt/us/DISABLE_KOREADER_AUTOSTART` name absent.
- The same audit found `/` read-only and `preventScreenSaver=0`.
- A controlled launch of the same exact job reached `phase=launching`. Choosing
  **Exit KOReader** returned the job to `stop/waiting`; `reader.lua` remained
  absent for a further 45 seconds. This proves the intended no-respawn behavior.
- Autostart is accepted for this exact firmware, job hash, and disconnected-USB
  boot procedure. Boot with a USB data cable attached is deliberately outside
  the accepted path; use a wall charger, charge-only cable, or no cable.

## Boot behavior

The production job uses one proven late boot trigger and bounded durable-state
checks:

1. Start once on `framework_ready`, the same one-shot boundary used by the
   audited KMC/Hotfix job on this firmware.
2. For at most 180 seconds, require `/mnt/us` to appear in `/proc/mounts` before
   evaluating the active recovery marker, `emergency.sh`, or KOReader launcher.
3. In the same bounded poll, require `lab126_gui` and `kppmainapp` to report
   `start/running` and require the durable `/tmp/kppmainapp_started` file.
4. Leave a further 30-second native-UI recovery window, then recheck the mounted
   userstore, both marker gates, launcher integrity, and duplicate-reader guard
   immediately before the single launch attempt. The native GUI jobs are not
   rechecked because they can briefly restart after readiness was already
   proven.

It checks the disable marker, absence of `emergency.sh`, the KOReader launcher,
both GUI jobs, the readiness file, and absence of an existing `reader.lua`
process before launch. Any timeout, missing file, changed safety state, or
failed check leaves the native Kindle interface running. Syslog tag
`lazying-koreader-autostart` and root-only transient trace file
`/tmp/lazying-koreader-autostart.trace` record bounded phase breadcrumbs:
`started`, `disabled`, `emergency-blocked`, `readiness-timeout`, `native-ready`,
`final-userstore-missing`, `final-disabled`, `final-emergency-blocked`,
`final-launcher-invalid`, `already-running`, and `launching`. The only launch is:

```sh
exec /bin/sh /mnt/us/koreader/koreader.sh --asap
```

The job is a service with no `task` and no `respawn` stanza. Upstart therefore
does not hold the boot event open while the reader is in use, and choosing
**Exit KOReader** returns to the native interface without launching KOReader
again during that boot.

## Why the common sample is not copied verbatim

A published Kindle 5 autostart example waits for the stock GUI and `home_wait`
LIPC event, but declares the long-running KOReader launch as an Upstart `task`.
The safe live failures showed that composing one-shot events is not reliable
enough on this firmware and that `dbus_ready` precedes the userstore. The
production job therefore uses the single audited `framework_ready` event and
polls bounded observable state. It is still a normal non-respawning service
because Upstart defines a task's start as unfinished until the task exits.
KOReader's own Kindle launcher is used unchanged; it already handles the Kindle
framework, Pillow, Awesome, `volumd`, and cleanup on normal exit.

## Fail-closed installation transaction

`manage-koreader-autostart.sh` supports these actions:

| Action | Persistent effect |
| --- | --- |
| `status` | None; reports firmware, owned/foreign/absent job state, both marker types, their switch state, `emergency.sh` presence, launcher presence, and next-boot state. |
| `audit` | None; requires exact firmware, expected stock jobs/events/tools, KMC, KOReader, no `emergency.sh`, and no foreign job. |
| `install` | Establishes/preserves the active disable marker first, then atomically publishes only the pinned job. It remains disabled. |
| `enable` | Atomically renames the active marker to the parked name, and only after the exact runtime/job audit. It never deletes the marker or starts the job immediately. |
| `disable` | Atomically renames the parked marker to the active name. Only the initial missing-both recovery case creates a zero-byte active marker. It does not kill a running KOReader; exit or reboot normally. |
| `uninstall` | Establishes/preserves the active disable marker first, then removes only the exact pinned owned job. A different job is never overwritten or removed. |

For a root-filesystem change, the manager records whether `/` was read-only,
uses `mntroot rw`, copies to an owned non-`.conf` temporary path, verifies the
pinned SHA-256, sets `root:root` and mode `0644`, renames atomically, calls
`sync`, and restores `mntroot ro` in an exit/signal trap when that was the prior
state. `initctl reload-configuration` only reloads definitions and does not
start a job. Firmware 5.15.1 ships Upstart 0.6.6, which has no `show-config`
command, so `initctl status lazying-koreader` must report the registered job
while the disable marker still exists.

## Exact guarded commands

Run these from the repository root only after KOReader SSH is available. Use
the dedicated recovery key when possible; the explicitly accepted portable
Kindle-only key can be selected instead. Never print either private key.

```powershell
$KindleIp = '<current-pw5-ip>'
$Port = 2222
$Key = "$env:USERPROFILE\.ssh\kindle_pw5se"
$Ssh = "$env:WINDIR\System32\OpenSSH\ssh.exe"
$Scp = "$env:WINDIR\System32\OpenSSH\scp.exe"
$Manager = (Resolve-Path '.\assets\koreader-lazy\manage-koreader-autostart.sh').Path
$Job = (Resolve-Path '.\assets\koreader-lazy\lazying-koreader-autostart.conf').Path
$Common = @('-i', $Key, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10')

# Read-only live gate. Stop if any check fails.
& $Scp @Common -P $Port $Manager "root@${KindleIp}:/tmp/manage-koreader-autostart.sh"
& $Ssh @Common -p $Port "root@$KindleIp" '/bin/sh /tmp/manage-koreader-autostart.sh audit'

# Stage the exact job; installation intentionally remains disabled.
& $Scp @Common -P $Port $Job "root@${KindleIp}:/tmp/lazying-koreader-autostart.conf"
& $Ssh @Common -p $Port "root@$KindleIp" '/bin/sh /tmp/manage-koreader-autostart.sh install'
& $Ssh @Common -p $Port "root@$KindleIp" '/bin/sh /tmp/manage-koreader-autostart.sh status'

# Only after the disabled reboot test passes, opt in for the next reboot.
& $Ssh @Common -p $Port "root@$KindleIp" '/bin/sh /tmp/manage-koreader-autostart.sh enable'
```

Every native process exit code must be checked. PowerShell does not throw for a
nonzero `ssh.exe` or `scp.exe` exit by itself; stop immediately unless
`$LASTEXITCODE` is `0` after each command. A future Windows wrapper should make
that check automatic before this is exposed as a one-click action.

The portable key, if deliberately selected for the existing Kindle-only trust
model, is:

```powershell
$Key = (Resolve-Path '.\Handoff\keys\kindle_handoff_rsa').Path
```

Recovery commands while SSH is reachable:

```powershell
& $Ssh @Common -p $Port "root@$KindleIp" '/bin/sh /tmp/manage-koreader-autostart.sh disable'
& $Ssh @Common -p $Port "root@$KindleIp" '/bin/sh /tmp/manage-koreader-autostart.sh uninstall'
```

The manager is intentionally placed in `/tmp`; after validation it may be
uploaded again whenever needed. The persistent control surface is the
active/parked marker switch plus the single exact Upstart job.

## Accepted live sequence and operating procedure

The migration, read-only audit, safe failed iterations, exact cleanup, enabled
automatic boot, Wi-Fi/SSH return, normal exit, and 45-second no-respawn watch
are complete. The accepted production invariant is:

1. Require the exact job SHA-256
   `2de0232b971926b7e70d913a27ba76168ed69760504ae2a90947e4402e7e5828`
   and a valid one-marker switch state.
2. To enable, use the audited manager to rename the active regular file
   `DISABLE_KOREADER_AUTOSTART` to the parked regular file
   `_DISABLE_KOREADER_AUTOSTART`. Do not delete it.
3. Before rebooting, disconnect USB **data**. No cable, a wall charger, or a
   charge-only cable is safe. A normal data cable can put the Kindle into USB
   Drive Mode and export `/mnt/us`, where both KOReader and its marker live.
4. After boot, the accepted trace is `started` -> `native-ready` -> `launching`.
   Wi-Fi/SSH may then be used normally.
5. To return to the native interface for the rest of that boot, choose
   **Exit KOReader**. The non-respawning Upstart service stops and waits.

The marker does not terminate an already running KOReader. While SSH is
available, run the manager's `disable` action before rebooting. If only native
USB storage is available, let the Kindle reach the native UI first, connect USB
data, rename `_DISABLE_KOREADER_AUTOSTART` to the exact active name
`DISABLE_KOREADER_AUTOSTART`, safely eject, disconnect USB data, and then
reboot. If the parked name is missing or both names exist, stop and audit rather
than creating, deleting, or guessing at marker state.

## Repository propagation

General handoff material may now describe autostart as accepted, but must carry
the exact production hash, rename-only marker semantics, and disconnected-USB
boot requirement. Relevant surfaces are:

- `README.md` status and contents table
- `docs/paperwhite5-5.15.1-winterbreak-koreader.md`, including its Phase 6
  deferral paragraph, recovery section, and operation log
- `docs/package-manifest.md`
- `skills/kindle-pw5se-commission/SKILL.md`
- both Handoff TeX sources and their rebuilt PDFs
- `scripts/configure-koreader-usb.ps1` status reporting and its offline test

The USB configurator may safely gain a **disable** action that only renames the
parked marker to the active visible name, refusing ambiguous or unsafe states.
It must not gain a USB-only **enable** action: USB storage
cannot inspect `/etc/upstart/lazying-koreader.conf`, so it cannot prove the
root job still matches the pin before parking recovery. Enabling remains an
SSH manager action with the exact runtime and job-hash audit.

## Firmware 5.15.1 risks and boundaries

- This adds one root-filesystem Upstart definition. It is reversible but still
  more invasive than manual launch. A power loss during the short remount/write
  transaction is the main installation risk.
- The stock job names, status output, event, and readiness file are
  firmware-specific.
  The manager blocks installation if its audited stock boundaries are absent.
  The production job waits at most 180 seconds for mounted-userstore and
  native-UI readiness; a timeout exits safely to the native UI and leaves a
  phase in syslog and the transient root-only trace.
- Do not boot the enabled job with a USB data connection. USB Drive Mode exports
  `/mnt/us`, so the job can no longer use the launcher and recovery marker stored
  there. Disconnect data before reboot; charging without data is safe.
- KOReader deliberately suspends parts of the stock UI and `volumd` while it is
  active. Normal exit restores them; an abrupt KOReader or system kill can
  require a reboot. Autostart does not change KOReader's existing cleanup code.
- A firmware update can replace jobs, events, or jailbreak persistence. Treat
  job disappearance as a safe native-UI fallback; do not reinstall after an
  update without a new firmware audit.
- Parking the marker after installing an unknown or edited job is forbidden.
  `enable` requires the pinned job hash and refuses a foreign file. Marker
  symlinks, special files, and ambiguous/missing switch states are also refused.
- `emergency.sh` must remain absent. Its presence blocks both audit and launch
  and must be investigated separately, never overwritten by this workflow.

## Sources used for the design

- The pinned [KOReader v2026.07.1 Kindle launcher](https://github.com/koreader/koreader/blob/v2026.07.1/platform/kindle/koreader.sh)
  is the primary source for its framework, Pillow, Awesome, `volumd`, and exit
  cleanup behavior.
- [Audited Universal Hotfix source commit](https://github.com/KindleModding/Hotfix/tree/82879f140fa808b9fb74bb46e9f7b522ca8133e5)
  staged under the ignored audit tree is the primary source for the
  `/etc/upstart` path, `framework_ready` KMC boundary, and the incompatible
  `emergency.sh` escape-hatch behavior.
- Upstart's official [`init(5)` documentation](https://manpages.ubuntu.com/manpages/xenial/en/man5/init.5.html)
  defines the service/task and respawn behavior; official
  [`initctl(8)` documentation](https://manpages.ubuntu.com/manpages/trusty/man8/start.8.html)
  states that `reload-configuration` does not start jobs.
- The external [Kindle 5 autostart example](https://gist.github.com/SuleMareVientu/822b2b51d1ea043ce2b190669c0df38b)
  is treated only as device-adjacent evidence for the stock GUI and
  `home_wait` event boundary, not as an installer, final trigger design, or
  safety authority.
- The [Kindle OS Upstart dependency diagram](https://kindlemodding.org/kindle-os/upstart-diagram.html)
  is secondary corroboration that `home_wait` starts at `dbus_ready`; the live
  5.15.1 audit and failed second reboot established that this is too early for
  direct access to `/mnt/us` on this device.
