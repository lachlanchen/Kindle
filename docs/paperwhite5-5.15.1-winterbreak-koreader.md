# Paperwhite 11th generation 5.15.1: WinterBreak2, Universal Hotfix, KOReader, and secure SSH

This runbook is for the audited Kindle Paperwhite 11th generation / PW5SE on
firmware `5.15.1`. It records only non-secret facts. The full serial number,
Wi-Fi name and password, fresh device-specific recovery private keys, and
other unpublished key contents do not belong in this repository. The
already-published Kindle-only shared sender identity is the intentional,
documented exception.

The Kindle is personally owned. This workflow enables homebrew such as
KOReader; it is not a DRM-removal procedure.

## Audited state

The USB-visible audit on 2026-08-08 found:

- Paperwhite 11th generation / PW5SE, 32 GB class device
- firmware `5.15.1`
- KOReader platform family `kindlepw2`
- no visible `documents/JAILBROKEN.txt`, KUAL, KOReader, MRPI, or `extensions`
  tree
- no USB network/RNDIS interface

The Store/Mesquito WinterBreak `2.1.0` route was then attempted with the full
official LocalStorage-replacement procedure. It ended cleanly at the ordinary
English-language Store: no jailbreak marker appeared, every staged Store
payload file remained unchanged, and no root OTA package appeared. That route
is closed for this commissioning attempt; do not repeat the Store trigger or
cache replacement. The guarded fallback is the official WinterBreak2 `1.0.0`
Experimental Browser route described below.

A seller's statement that the device was jailbroken is not proof. A root-only
hotfix cannot be disproved from USB storage, so the success marker and KMC/KPM
state must be checked after WinterBreak runs. Do not use the repository's old
PW2/PW4 recipes on this device.

## Pinned inputs

The helper verifies every downloaded artifact before using it:

| Input | Version / purpose | SHA-256 |
| --- | --- | --- |
| `WinterBreak-v2.1.0.tar.gz` | WinterBreak `2.1.0`; retained only as the exact record of the completed Store attempt | `dc04fff5fcb685834cba9f9e95d4818b473d4100b2d40b8bb7c598ad09eb850d` |
| `wb2.zip` | Official WinterBreak2 `1.0.0` browser fallback | `932ff113c414c9b0109b98d7f4b96da20815364fb4905e4483581b881b2ae2e2` |
| `Update_hotfix_universal.bin` | Universal Hotfix `2.5.0`, required after WinterBreak2 | `94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59` |
| `koreader-kindlepw2-v2026.07.1.zip` | KOReader `2026.07.1` for firmware at or below `5.16.2.1.1` | `ea1f575c54492a2c679d128b7f3210fd7d6a87e5f5a1ff1f7a7fe2080ff68f86` |

WinterBreak2 must be staged exactly from the verified `wb2.zip`. In particular,
keep the stock `jb.sh` that is inside that archive. Do not replace it with a
newer downloaded bootstrap, splice files from the Store-based WinterBreak
release, or combine the two execution paths. The stock script installs the
initial jailbreak state; Universal Hotfix `2.5.0` establishes persistence and
must be installed before KOReader.

From an ordinary PowerShell window in the repository:

```powershell
Set-Location "$env:USERPROFILE\Projects\Kindle"
.\scripts\pw5se-winterbreak.ps1 -Action Download
.\scripts\pw5se-winterbreak.ps1 -Action Diagnose
```

Stop if `Diagnose` does not report firmware `5.15.1` and family `kindlepw2`.
WinterBreak2 is compatible only below firmware `5.16.4`; the narrower exact
firmware and device fingerprint gates in this repository still apply.

## Phase 1: save Wi-Fi, then isolate the Kindle

WinterBreak2 needs a working, internet-connected Wi-Fi profile during its short
Experimental Browser step, but it does **not** require Amazon registration.
Before changing storage:

1. On the Kindle, connect to the intended network and verify that the Store can
   load. Do not write its password into a script, command history, or this repo.
2. Turn **Airplane Mode on**.
3. Restart the Kindle while Airplane Mode remains on.
4. After it finishes booting, reconnect its USB cable and wait for the storage
   volume to mount.

The preparation command must not be run until a person confirms all four
steps. The Wi-Fi profile remains saved; Airplane Mode merely keeps it offline
during staging.

## Phase 2: original Store preparation (completed; do not repeat)

The following command records how the original Store payload was prepared. It
has already completed on this device and must not be run again for the browser
fallback:

```powershell
.\scripts\pw5se-winterbreak.ps1 -Action Prepare -ConfirmedAirplaneMode
```

`Prepare` performs another USB-visible backup, copies the complete WinterBreak
tree including `.active_content_sandbox`, writes a rollback manifest and
backups for overwritten files, then creates `.kindle-ota-space-filler` until
only about 80 MiB remains. The filler folder carries a managed ownership marker,
so cleanup refuses a similarly named user folder. It refuses a different
firmware unless an operator uses the explicitly named firmware override after a
fresh compatibility audit.

The filler is deliberate OTA protection. Do not add books or other large files
while it is present. Confirm that free space finishes inside the helper's
50–98 MiB safety envelope, then eject cleanly:

```powershell
.\scripts\pw5se-winterbreak.ps1 -Action Eject
```

### Preserve the completed Store-attempt record

`UndoStage`, `RemoveFiller`, `RestoreStoreCache`, and `RestoreStoreSandbox` were
reversible exits while the Store route was active. They are no longer current
actions: the Store attempt is closed, its records are evidence for the clean
failure, and the owned filler remains the WB2 OTA guard. Use the separate
`UndoWinterBreak2` action below only if the browser payload has not executed.

## Phase 3: stage and run the official WinterBreak2 fallback

The final English-language Store still showed the ordinary Store. The last
offline audit found no `documents/JAILBROKEN.txt`, no root OTA package, and no
changes among all 17 staged Store-payload files. A Store cache had regenerated,
but no exploit code executed. This is a clean failure, not a partial jailbreak.
Do not open the Store payload again, reset LocalStorage again, or restore the
old Store sandbox while proceeding with WinterBreak2.

With Airplane Mode on and USB reconnected, stage the dedicated browser fallback:

```powershell
.\scripts\pw5se-winterbreak.ps1 -Action BindDeviceIdentity -ConfirmedAirplaneMode
.\scripts\pw5se-winterbreak.ps1 -Action StageWinterBreak2 -ConfirmedAirplaneMode
.\scripts\pw5se-winterbreak.ps1 -Action Eject
```

`BindDeviceIdentity` is an explicit, idempotent first-use guard. It stores only
a domain-separated SHA-256 identity hash derived from the Windows volume serial
and size. It never prints or records the raw volume identifier. Later WB2
actions refuse a different device rather than silently rebinding it.

`StageWinterBreak2` is the only authorized staging action for this fallback. It
must verify the official `wb2.zip` hash, copy its stock `jb.sh`,
`patchedUks.sqsh`, and `winterbreak2/dialoger.html`, write a separate reversible
manifest, preserve the earlier Store-attempt record, and finish with 50-90 MiB
free. Do not use the generic legacy `StageWinterBreak2` implementation in
`scripts/kindle-jailbreak.ps1`, `StagePostJailbreak`, a hand-edited `jb.sh`, or
files from another jailbreak release.

After safe eject:

1. Unplug USB, turn Airplane Mode off, and connect the already-saved Wi-Fi.
   Amazon registration is not required.
2. Open the Kindle's **Experimental Browser** and navigate exactly to
   `https://winterbreak2.now.sh/`. If that hosted page is unavailable, use the
   guarded LAN-only fallback below and navigate to `http://<PC-LAN-IP>/`
   instead (or `http://<PC-LAN-IP>:<PORT>/` for a non-default port).
3. Press **Jailbreak** once and wait for the completion message. Do not refresh,
   press repeatedly, or run the Store payload in parallel.
4. Immediately turn Airplane Mode on after completion.
5. Reconnect USB. If `update.bin.tmp.partial` is present at the root, remove
   only that incomplete OTA file before any post-jailbreak package is staged.

### Hosted-page outage: guarded LAN-only server

The fallback server is only for a hosted-page outage. The PC and Kindle must be
on the same trusted LAN. From this repository, first inspect without changing
any process or firewall state:

```powershell
.\scripts\winterbreak2-local-server.ps1 -Action Status
```

If `managed` and `occupied` are both false, start the pinned official server:

```powershell
.\scripts\winterbreak2-local-server.ps1 -Action Start
```

This validates the official clone at
`%USERPROFILE%\Projects\winterbreak2-local`, commit
`40a1425215cfb6a1394590208acfefae920e5811`, the pinned `api/index.js`
SHA-256, and Express `5.1.0`; refuses tracked changes or an occupied port; binds
only the selected RFC1918 address on a Windows **Private** network; launches
hidden; and keeps bounded state/logs under ignored `logs/`. By default it makes
no firewall change. If Windows Firewall blocks the Kindle and a new managed
run is needed, opt in at initial start with:

```powershell
.\scripts\winterbreak2-local-server.ps1 -Action Start -AllowPrivateSubnetFirewall
```

That switch creates only an exact managed TCP rule for the selected local
address and port, **Private** profile, and `LocalSubnet` remote scope. A custom
port or address may be passed explicitly as `-Port <PORT> -BindAddress
<PC-LAN-IP>`; the address still must be active, RFC1918, and on a Private
profile.

If `Status` reports `managed: false` and `occupied: true`, an external listener
already owns the port. The helper will neither adopt nor stop it, and `Start`
will refuse it. Review that separately before using its URL. `Stop` is valid
only when `Status` reports `managed: true`; it checks the recorded PID,
executable, creation time, and command-line hash before stopping exactly that
process and removes only its own recorded firewall rule:

```powershell
.\scripts\winterbreak2-local-server.ps1 -Action Stop
```

After the browser trigger, stop a helper-managed server; do not use this command
to try to stop an unmanaged listener.

Verify the WinterBreak2 result before continuing:

```powershell
.\scripts\pw5se-winterbreak.ps1 -Action VerifyWinterBreak2
```

Success requires `winterbreak.log` to record the completed jailbreak, including
successful developer-key installation, the developer flag, the `mntus` exec
flag, the final completion line, and the prompt to install the hotfix. File
presence alone is insufficient. The verification action also retires only the
matching WinterBreak2 rollback
pointer; it must not mislabel the failed Store attempt as executed.

If the browser step has not executed, cancel only the fallback with:

```powershell
.\scripts\pw5se-winterbreak.ps1 -Action UndoWinterBreak2 -ConfirmedAirplaneMode
```

`UndoWinterBreak2` restores/removes only unchanged files recorded by its own
manifest. Never run it after `winterbreak.log` shows execution.

## Phase 4: install Universal Hotfix before KOReader

Stock WinterBreak2 is only the initial jailbreak. Universal Hotfix `2.5.0` is
mandatory for persistence and must be installed before KOReader, SSH, KUAL,
MRPI, or any other post-jailbreak package. Use only
`Update_hotfix_universal.bin` with SHA-256
`94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59`.

After `VerifyWinterBreak2` succeeds and Airplane Mode is still on:

1. Stage only the verified hotfix and safely eject:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action StageHotfix -ConfirmedAirplaneMode
   .\scripts\pw5se-winterbreak.ps1 -Action Eject
   ```

   `StageHotfix` requires the matching executed-WB2 audit and exact package
   hash. Do not use the generic `StagePostJailbreak` action, which mixes old
   MRPI/KUAL/KOReader packages.
2. Open **Settings** and choose **Update Your Kindle**.
3. Wait through the update and reboot.
4. Open the **Run Hotfix** booklet when it appears and wait for it to finish.
5. Return to Airplane Mode and reconnect USB. The root
   `Update_hotfix_universal.bin` must have been consumed, no root update or
   partial OTA may exist, and `documents/Run Hotfix.run_hotfix` must contain
   the exact UTF-8 bytes `2.5.0\n`.
6. Stage only the nonce-bound verification document and safely eject:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action StageHotfixProbe -ConfirmedAirplaneMode
   .\scripts\pw5se-winterbreak.ps1 -Action Eject
   ```

   `StageHotfixProbe` requires the executed WB2 record, completed pinned
   `StageHotfix` record, matching stable device identity, exact runner marker,
   intact owned 50-90 MiB filler guard, and no root OTA. It substitutes a
   cryptographically random 16-byte nonce into the pinned LF/no-BOM template
   exactly once, pins the rendered script and expected result hashes in a
   separate ignored record, and atomically stages only
   `documents/Verify Hotfix.sh`. It refuses an unrecorded probe or a result that
   existed before the nonce was prepared.
7. Unplug USB and open **Verify Hotfix** once from the Kindle library. Wait for
   the `Universal Hotfix 2.5.0 verified` message. The document checks the
   persistent KMC/MKK and shell-integration files, developer and update keys,
   and the exact official 13-job hotfix log sequence before atomically writing
   one nonce-bound result.
8. Return to Airplane Mode, reconnect USB, and finalize the proof:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action VerifyHotfix -ConfirmedAirplaneMode
   ```

   `VerifyHotfix` requires the staged script to remain hash-exact and the
   `HOTFIX_VERIFIED_LAZYING_ART.txt` result to match the prepared nonce,
   version, runner state, final newline, and exact byte length. It then
   publishes a separate verified-hotfix record. Never create or edit that
   result manually.

   If every current persistence check passes but only the historical start-log
   check fails because `/var/log/messages` was rotated or routed elsewhere,
   preserve the failed original record and use its same nonce-bound diagnostic:

   ```powershell
   .\scripts\pw5se-winterbreak.ps1 -Action StageHotfixDiagnostic -ConfirmedAirplaneMode
   .\scripts\pw5se-winterbreak.ps1 -Action Eject
   # Open Diagnose Hotfix once, return to Airplane Mode, and reconnect USB.
   .\scripts\pw5se-winterbreak.ps1 -Action ReadHotfixDiagnostic -ConfirmedAirplaneMode
   .\scripts\pw5se-winterbreak.ps1 -Action AcceptHotfixPersistentState -ConfirmedAirplaneMode
   ```

   Acceptance is permitted only for the exact `START_LOG` result after all
   root/persistent files, keys, shell integration, runner, update, identity,
   and WB2 gates pass. It publishes `persistent-state-v2`; it explicitly does
   not claim that the historical 13-job sequence was observed. Do not rerun or
   wrap the root Hotfix script merely to manufacture historical log evidence.

Do not treat a `winterbreak.log`, consumed update, runner booklet, or file
presence alone as completed commissioning. Require either the full-history
nonce-bound proof or the narrowly defined `persistent-state-v2` acceptance.

## Phase 5: install the correct KOReader build

At the time of this audit, the KPM catalog exposed KOReader artifacts built for
`kindlehf`, but firmware `5.15.1` requires `kindlepw2`. Therefore, do **not**
run `;kpm install koreader` on this Kindle. Continue only after a matching
device-bound Hotfix proof is published, then use the verified direct USB
fallback:

```powershell
.\scripts\pw5se-winterbreak.ps1 -Action StageKOReader -ConfirmedAirplaneMode
.\scripts\pw5se-winterbreak.ps1 -Action VerifyKOReaderStage
```

This does not accept `JAILBROKEN.txt` as a sufficient gate. It validates the
official archive and required `kindlepw2` tree first, creates a separate
device-bound KOReader stage record, and durably records
`filler-removal-authorized` before removing only the exact owned OTA filler.
The public `RemoveFiller` action remains blocked after WB2. If power or USB is
interrupted after authorized removal, rerun `StageKOReader`: it resumes only
the KOReader layer with the filler absent and never recreates or rolls back the
filler. No root OTA is allowed before removal, copying, or completion. Every
copied destination file is SHA-256 checked. Expected visible paths include:

- `koreader/koreader.sh`
- `extensions/koreader/`
- `documents/KOReader.sh`

Keep Airplane Mode on while the filler is removed. Safely eject before opening
the KOReader launcher from the Kindle library.

## Phase 6: managed portable SSH commissioning

Commission the device-specific recovery key first. Its private half stays in
the Windows user SSH directory, outside this public repository and off the
Kindle. After that login works, the user explicitly wants the published
Handoff/PDF key as a portable GUI identity on every trusted computer. This is a
convenience choice: anyone holding the repository/PDF can use that key whenever
KOReader SSH is reachable. Never reuse it for anything except these Kindles.

With USB mounted after KOReader is staged, run:

```powershell
.\scripts\configure-koreader-usb.ps1 -Action Configure -ConfirmedAirplaneMode
.\scripts\configure-koreader-usb.ps1 -Action Status
```

`Configure` first reruns the read-only, device-bound `VerifyKOReaderStage` gate.
It then:

- enables KOReader's SSH plugin on TCP port `2222`
- requires exactly the fresh expected public key
- explicitly disables anonymous/empty-password authentication
- preserves the Kindle's saved Wi-Fi behavior
- refuses any root `emergency.sh`
- leaves boot autostart uninstalled during the USB commissioning stage

Eject, launch KOReader manually, turn Wi-Fi on, and test from Windows:

```powershell
ssh -i "$env:USERPROFILE\.ssh\kindle_pw5se" -p 2222 root@<kindle-ip>
```

The first connection may ask whether to trust the host key. Verify that prompt
on the intended local network. Authentication must succeed with the private key
and must not fall back to an account password or an empty password.

Also prove that password/empty-password authentication and a different private
key fail. Exit KOReader before USB storage work. Reboot, manually reopen
KOReader, and repeat the saved-Wi-Fi and SSH tests before calling commissioning
complete.

After the recovery login succeeds, pair the exact pinned portable identity:

```powershell
.\scripts\pair-kindle-book-sender.ps1 -KindleIp <kindle-ip>
```

The helper accepts only a current subset of the two expected identities,
publishes the canonical recovery-plus-portable set through a same-directory
temporary file, verifies it without printing key contents, and proves portable
BatchMode login. The superseded per-computer Book Sender key is not needed.

After the library migration, the v1 Upstart job documented in the
[guarded autostart design](pw5se-koreader-autostart-design.md) passed its full
live acceptance sequence with SHA-256
`2de0232b971926b7e70d913a27ba76168ed69760504ae2a90947e4402e7e5828`.
That accepted baseline was safely upgraded on 2026-08-13 after a live freeze
audit. The current v2 definition SHA-256 is
`87381c8cb810b3e8606c97b5ad913a1be5f49c7a4ba6f46f66b6ae3e28e95dbd`.
It retains the single launch, bounded recovery window, rename-only disable
switch, and no-respawn behavior, while adding explicit standard and lower-
memory framework-stop modes.

Framework-stop is selected for the next boot through the regular marker
`_DISABLE_KOREADER_AUTOSTART_FRAMEWORK_STOP`. The active
`DISABLE_KOREADER_AUTOSTART` marker and standard-mode marker are absent. The
root filesystem is read-only, `preventScreenSaver=0`, and
`/mnt/us/emergency.sh` remains absent. Installation did not restart the current
reader. The first v2 framework-stop reboot has not yet been observed, so the
accepted v1 result must not be misreported as v2 acceptance.

Disconnect USB **data** before any boot acceptance test. No cable, a wall
charger, or a charge-only cable is safe. A computer data cable can invoke USB
Drive Mode and export/make unavailable `/mnt/us`, where both KOReader and the
marker live; that is not an autostart failure.

## 2026-08-13 freeze and frontlight audit

The detailed evidence, reversible source guard, three boot modes, lighting
state, exact hashes, and user instructions are in the
[PW5SE stability and lighting runbook](pw5se-koreader-stability-and-lighting.md).

The concrete return-to-stock event was a KOReader wake-time crash in
`Contact:isTwoFingerTap`: a malformed touch frame had no `initial_tev` and the
reader terminated. A narrow exact-hash guard now ignores only incomplete
two-contact taps and loads on the next launch. The original source is retained
under `/mnt/us/koreader/.lazying-art-stability` and can be restored only by the
hash-gated manager. After disconnection, that repository manager was hardened
to resume every owned rollback interruption point and to refuse foreign
rollback-directory entries; the live guard was already in the clean
`patched:original` state, so this changes only future maintenance. The same
audit found repeated document-cache eviction at
roughly 19% free RAM while a very large PDF was open; keeping Amazon `cvm` and
`KPPMainApp` resident consumed roughly another 124 MiB, motivating the
provisional framework-stop selection. No OOM kill, panic, filesystem error, or
watchdog death was found.

Amazon ambient auto brightness was active even though KOReader AutoWarmth was
off. A pinned KOReader patch now defaults it to manual and reapplies that choice
after every resume. The exact regular file
`/mnt/us/ENABLE_AMAZON_AUTO_BRIGHTNESS` opts back into Amazon ambient control;
absence means manual brightness. KOReader AutoWarmth, Amazon warmth scheduling
and night light, and KOReader Automatic Dimmer were left off. Brightness and
warmth remain manually adjustable through **Settings -> Frontlight**.

## Book sync

The initial Nutstore-to-PW5SE migration snapshot completed on 2026-08-09. All
PDF bytes came from the local Nutstore sources: 239 LinguaLeaf black-and-white
PDFs and 10 PocketPolished PDFs. The old PW2 supplied only deterministic
relative-folder evidence; no PDF bytes came from it, and optional `.sdr` state
was not part of the initial PDF transfer.

The final idempotent apply confirmation reported `bookCount=249`, `copied=0`,
and `resumed=249`. The device audit matched the planned folder distribution,
found zero owned upload temporary files, and reported 22,910,896 KiB free. The
two noncanonical root copies of `A Brief History of Time` were absent; its
canonical copy is under `documents/LinguaLeaf/en-jp-zh-blackwhite`. Subsequent
source drift grew the live 2026-08-13 inventory to 256 LinguaLeaf plus 10
PocketPolished PDFs, for a desired total of 266. Later individually requested
books were copied, but a fresh full-device 266-book reconciliation has not run;
only the original 249-book snapshot is claimed fully reconciled. The
temporary `preventScreenSaver` value was restored to `0` before reboot. See the
[library migration reference](../references/lingualleaf-koreader-sync.md) for
the exact seven-folder counts, resumable SFTP behavior, and optional sidecar
rules.

A subsequent guarded sidecar apply copied 10 `.sdr` trees and skipped 239. The
249 detailed statuses were 10 `copied`, one
`skipped-destination-exists`, 161 `not-inspected`, 68 absent or ambiguous, and
nine checksum/current-PDF mismatches. An independent audit matched every file
in all 10 copied trees to the PW2 source by size and SHA-256 and found no owned
temporary files. Candidate identity used current PDF size and KOReader partial
MD5, not stale sidecar metadata checksums. Both guarded executions captured an
original `preventScreenSaver=0` and restored it to `0`.

*Zizhi Tongjian, Part 1* was the existing-destination skip and was **not**
overwritten. The PW5SE sidecar records `last_page=11` while the PW2 records
`last_page=4651`; both record `doc_pages=18079`, and the complete PDF SHA-256
matches Nutstore, PW2, and PW5SE. The default correctly preserved PW5SE state.
Its transactional explicit replacement is implemented and tested but has not run;
it awaits closing the book in KOReader/file browser and an explicit guarded
run. Differently named/edition *Shiji* sidecars remain deliberately unmapped
and were not copied.

### Superseded one-book staging record

The requested source PDF is:

`Nutstore/1/Share/LinguaLeaf/blackwhite/A Brief History of Time（日文・中文注）｜English-日本語-中文｜黑白.pdf`

Its verified SHA-256 is:

`2d12225ef4c37b6045e6fb7dc74c6c94d5d1b11334a7d5c46b51f4c4fbf7a0e4`

Before the full migration, it was copied without a `blackwhite` subfolder to
two temporary staging destinations. Those noncanonical paths are historical
only and were confirmed absent in the final migration audit:

- `documents/PocketPolished/A Brief History of Time（日文・中文注）｜English-日本語-中文｜黑白.pdf`
- `documents/LinguaLeaf/A Brief History of Time（日文・中文注）｜English-日本語-中文｜黑白.pdf`

The repeatable, hash-checking command is:

```powershell
$book = Join-Path $env:USERPROFILE 'Nutstore\1\Share\LinguaLeaf\blackwhite\A Brief History of Time（日文・中文注）｜English-日本語-中文｜黑白.pdf'
.\scripts\sync-kindle-book.ps1 -Source $book -ExpectedSha256 '2d12225ef4c37b6045e6fb7dc74c6c94d5d1b11334a7d5c46b51f4c4fbf7a0e4'
```

Exit KOReader before USB file transfer; KOReader does not provide Kindle USB
mass-storage mode while it is running.

## Recovery boundaries

- `device-backups/` contains USB-visible content only. It is not a raw firmware
  image and cannot undo root-level changes.
- The original Store attempt is closed. Preserve its backup, stage manifest,
  payload, and cache records for audit; do not rerun `ResetStoreCache`,
  `RestoreStoreCache`, or `RestoreStoreSandbox` during the WB2 path.
- Before the browser exploit runs, use only
  `UndoWinterBreak2 -ConfirmedAirplaneMode` to cancel the fallback. Its separate
  manifest must not roll back the earlier Store stage.
- After `winterbreak.log` records execution, never run `UndoWinterBreak2`.
  Return to Airplane Mode, remove only a root `update.bin.tmp.partial` if one
  exists, and complete Universal Hotfix before repairing any later layer.
- Before the hotfix probe executes, rerun `StageHotfixProbe` only to reconcile
  its exact active record. If a result is present, use `VerifyHotfix`; do not
  delete, edit, or manufacture it. A copied-probe/state-write interruption is
  reconciled from the exact script hash without changing its nonce.
- The filler must remain exact through hotfix proof. Only a verified-hotfix,
  device-bound KOReader stage record may authorize its removal. After that
  authorization, rerun `StageKOReader` to resume an interrupted copy; do not
  call public `RemoveFiller` or recreate the filler.
- Keep root `emergency.sh` absent. If one appears, identify its owner before
  changing it; do not run either exploit again simply because KOReader fails.
- The autostart recovery switch is rename-only. Exactly one regular file must
  exist: `DISABLE_KOREADER_AUTOSTART` is native/disabled,
  `_DISABLE_KOREADER_AUTOSTART` is standard, and
  `_DISABLE_KOREADER_AUTOSTART_FRAMEWORK_STOP` is lower-memory mode. Rename the
  selected underscore marker to the active name to disable over USB. Never
  enable without the manager's exact job-hash audit. Disconnect USB data before
  reboot, because USB Drive Mode can make `/mnt/us` unavailable.
- If KOReader itself is damaged, exit to the stock UI, reconnect USB, and rerun
  `StageKOReader` with the same verified archive.
- Do not use LanguageBreak or factory-reset as a casual troubleshooting step.
  Either route is destructive and needs a new, explicit compatibility and
  recovery decision. Preserve the backups and consult the current upstream
  recovery guidance before changing firmware or root state.
- The published Handoff key is intentionally authorized here at the user's
  request for portable Book Sender access. Keep it Kindle-only and retain the
  fresh device-specific recovery key.

## Operation log

Status after commissioning and library migration on 2026-08-09:

| State | Result |
| --- | --- |
| Device identification | Audited as PW5SE / Paperwhite 11th generation on firmware `5.15.1`; serial intentionally omitted. |
| Visible jailbreak state | WinterBreak2, Universal Hotfix, and KOReader are installed. The Store-route `JAILBROKEN.txt` marker remains absent by design; KUAL and MRPI were not needed for the direct shell-integration launcher. |
| USB backup | Initial audit backup completed at `device-backups/pw5se-5.15.1-20260808-182504/`; fresh pre-stage backup completed at `device-backups/pw5se-5.15.1-20260808-202155/` (both ignored by Git). |
| Downloads | Store WinterBreak, official WinterBreak2 `1.0.0`, Universal Hotfix `2.5.0`, and KOReader inputs are pinned by SHA-256 under ignored `downloads/`. |
| Full library migration | The initial 249-book snapshot finished with `copied=0`, `resumed=249` in its idempotent confirmation. The live 2026-08-13 source now contains 256 LinguaLeaf plus 10 PocketPolished PDFs (266 total); later individually requested books were copied, but a fresh full-device 266-book reconciliation has not run. Book bytes come only from Nutstore; the PW2 contributes folder mapping and guarded reading state only. The sidecar apply copied 10 and skipped 239: one existing destination, 161 not inspected, 68 absent/ambiguous, and nine checksum/current-PDF mismatches. Independent size/SHA-256 audit passed all 10 copied trees with no owned temporary files; both keep-awake guards restored their original value of `0`. *Zizhi Tongjian, Part 1* was deliberately preserved at the PW5SE's existing page 11 rather than overwritten with the PW2's page 4651 state; explicit transactional replacement has not run. Differently named/edition *Shiji* sidecars remain unmapped. |
| SSH identity | The fresh device-specific recovery key remains outside the repository. The explicitly selected published Handoff/PDF identity is the portable GUI key; both are authorized, while the former per-computer app key is revoked. |
| WinterBreak Store staging | Complete and hash-verified. Audit record: `device-backups/winterbreak-stage-5.15.1-20260808-202159/`; owned filler has 28 chunks with no unexpected entries and retained the guarded free-space envelope. |
| Full Store regeneration | Completed once. The original `.active_content_sandbox` is hash-backed up at `device-backups/winterbreak-store-sandbox-20260808-213054/`; the regenerated 1,384,448-byte cache is hash-backed up at `device-backups/winterbreak-store-cache-20260808-220738/`; all 17 reapplied WinterBreak files matched. The final English Store remained ordinary, so this route is closed. |
| Final Store-route audit | Clean failure: no `JAILBROKEN.txt`, no root OTA package, and all 17 staged payload files unchanged. No Store exploit execution is claimed. |
| WinterBreak2 fallback | The stock `1.0.0` browser path executed and its complete `winterbreak.log` gates were recorded against the bound device identity; no `JAILBROKEN.txt` marker was used as proof. |
| Universal Hotfix proof | Universal Hotfix `2.5.0` was consumed through **Update Your Kindle** and **Run Hotfix**. The same-record diagnostic passed UID 0, persistent/runtime files, keys, shell integration, runner, update, identity, and WB2 checks; only the historical start line was unavailable. The accepted proof mode is therefore explicitly `persistent-state-v2`; no full-history or 13-job-sequence claim is made. |
| KOReader stage | KOReader `kindlepw2` v2026.07.1 is complete and device/proof-bound. Independent source-to-device audit matched all 1,034 files / 86,579,284 bytes, including the pinned launcher; filler and root update artifacts are absent, and both PDFs remain hash-exact. |
| SSH policy | The pinned secure-SSH patch is verified and root `emergency.sh` is absent. Admin and portable GUI/PDF key logins on port `2222` passed; the canonical two-key set has no unknown identity. Empty-password/no-key and superseded per-computer-key attempts were rejected. Wi-Fi/SSH returned after the accepted enabled reboot. |
| KOReader autostart and stability | V1 hash `2de0232...` passed disconnected-USB boot, Wi-Fi/SSH return, clean exit, and 45-second no-respawn validation. On 2026-08-13 it was atomically upgraded to v2 hash `87381c8cb810b3e8606c97b5ad913a1be5f49c7a4ba6f46f66b6ae3e28e95dbd`; framework-stop is selected for the next boot, `/` is read-only, and the current reader was not restarted. The exact gesture guard, original rollback, and ambient-brightness patch are installed for the next launch. Runtime ambient auto brightness and every warmth/dimmer scheduler are off. V2's first reboot remains pending and is not claimed accepted. |
| Latest requested book | *Fathers and Sons* was copied atomically to `documents/LinguaLeaf/en-jp-zh-blackwhite`; device SHA-256 `bb922e485a882a957ee26e96ff4d23e76c6ece3f27c54538d019be7826337926` matched Nutstore, no owned temporary file remained, and `preventScreenSaver` was restored to `0`. |

The first filler process reached its Windows execution window after allocating
17 full chunks. Before resuming, the script verified the completed staging
manifest, device fingerprint, ownership marker, chunk boundaries, and absence
of a jailbreak marker. The idempotent `FillSpace` action resumed at the next
owned chunk and passed the final 50–98 MiB envelope check. A final read-only
audit verified every staged payload hash, both PDF hashes, all required
WinterBreak roots, zero unexpected filler entries, and no partial OTA file.

The first Store attempt opened the normal Kindle Store instead of Mesquito.
After Airplane Mode was restored and the Kindle rebooted, inspection showed a
fresh one-file `LocalStorage` cache, unchanged WinterBreak payload hashes, no
partial OTA, and 79.6 MiB free. `ResetStoreCache` backed the private cache up to
ignored `device-backups/winterbreak-store-cache-20260808-211843/`, verified its
copy without logging its contents, removed only the exact `LocalStorage`
directory, reapplied WinterBreak, and restored the guard to 80.0 MiB. The
payload, cache backup, device fingerprints, and free-space envelope all passed
post-reset verification before safe eject.

The retry still opened the normal Store, so the official full LocalStorage
Replacement procedure was started. The complete `.active_content_sandbox`
was copied to the ignored
`device-backups/winterbreak-store-sandbox-20260808-213054/` record and every
manifested backup hash passed before the exact device directory was removed.
The WinterBreak files outside that deliberately removed sandbox remained
hash-correct, the owned 28-chunk filler contained no unexpected entries, no
partial OTA or jailbreak marker existed, and the free-space guard remained
80.0 MiB. Windows then detached the media; the persistent empty `F:` drive
letter reported zero-byte media and was not a mounted Kindle filesystem.

The full-sandbox recovery code was then independently safety-reviewed and
hardened before the next live step. Restore now validates the fixed sandbox
path, exact file and directory set, and every hash before writing anything; a
resumed `prepared` record refuses changed or regenerated Store data; state
transitions and older cache-pointer retirement are crash-resumable; filler
ownership is rechecked; and root-level OTA packages stop cache reset for
operator review instead of being deleted automatically. The isolated
`tests/test-pw5se-store-sandbox.ps1` suite passed corruption, extra-file,
path-tampering, crash-recovery, transition, filler, OTA-refusal, and happy-path
restore cases without accessing removable storage.

During the physical regeneration, the ordinary Store could be browsed but a
free sample could not be downloaded because the Kindle requested registration,
and the registration attempt failed. This still generated one nonempty
1,384,448-byte `LocalStorage` file, compared with the earlier smaller cache.
Because generating that directory is the technical gate for the replacement
step, the helper accepted it only after rechecking firmware and device
fingerprints, the complete stage record, owned 28-chunk filler, 78.7 MiB free,
both PDF hashes, and absence of jailbreak and OTA files. `ResetStoreCache`
backed up and hash-verified the new cache, removed only `LocalStorage`,
reapplied and verified all 17 WinterBreak files, advanced the full-sandbox
record to `regenerated`, and restored exactly 80.0 MiB free before safe eject.
The final trigger was attempted after safe eject. In the prior language the
Store reported a load error; after switching the Kindle UI to English, it
loaded the ordinary Store rather than Mesquito. On the final Airplane-Mode USB
audit, `documents/JAILBROKEN.txt` was absent, there was no root OTA package,
and all 17 staged WinterBreak payload files still matched their original
hashes. A smaller Store cache had regenerated, but the unchanged payload proves
that the Store exploit did not execute. The Store route therefore ended
cleanly and will not be retried.

The successful fallback was the official WinterBreak2 `1.0.0` Experimental
Browser route with the stock archive `jb.sh`. Its `winterbreak.log` passed every
completion gate and Hotfix prompt. Universal Hotfix `2.5.0` then ran through
**Update Your Kindle** and **Run Hotfix**; current persistence was accepted in
the explicitly limited `persistent-state-v2` mode after exact diagnostic
verification. The proof-gated KOReader stage subsequently completed, removed
only the owned filler, and passed an independent exact-file audit. The SSH
policy, both managed identities, automatic KOReader launch, saved-Wi-Fi return,
SSH return, normal exit, and no-respawn behavior all passed live testing. Ten
guarded reading-state sidecars were copied and independently audited. The
existing PW5SE *Zizhi Tongjian, Part 1* state was preserved, and *Shiji* remains
unmapped; neither affects commissioning acceptance. The source has since grown
to 266 desired PDFs; later individually requested copies are recorded, but a
fresh full-device reconciliation remains pending.

## Upstream references

- [WinterBreak installation and troubleshooting](https://kindlemodding.org/jailbreaking/WinterBreak/)
- [WinterBreak v2.1.0 release](https://github.com/KindleModding/WinterBreak/releases/tag/v2.1.0)
- [WinterBreak2 installation](https://kindlemodding.org/jailbreaking/WinterBreak2/)
- [WinterBreak2 v1.0.0 release](https://github.com/KindleModding/Winterbreak2/releases/tag/v1.0.0)
- [Universal Hotfix installation](https://kindlemodding.org/jailbreaking/post-jailbreak/setting-up-a-hotfix/)
- [KOReader package-family guidance](https://kindlemodding.org/jailbreaking/post-jailbreak/koreader.html)
- [KOReader v2026.07.1 release](https://github.com/koreader/koreader/releases/tag/v2026.07.1)
