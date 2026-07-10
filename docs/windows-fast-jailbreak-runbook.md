# Windows Fast Jailbreak Runbook

Date added: 2026-07-10

This runbook preserves the repeatable jailbreak journey as a Windows-first
script. It is designed for the next run: detect the connected Kindle, pick the
safe method from firmware, download the right packages, stage files, and leave
only the unavoidable on-device taps to the user.

## Current connected device note

On 2026-07-10, the connected Kindle mounted as `F:\` and reported:

```text
Volume: Kindle
Firmware: Kindle 5.18.1
Serial: G0016Q03019705VN
```

That firmware is not safe for the old PW2 `5.12.2.2` WinterBreak2 path.
KindleModding says WinterBreak2 only works below `5.16.4`; their current
method map says firmware `5.18.1+` should use AdBreak, while Nosebleed is also
available for some models/firmware combinations. The script therefore blocks
WinterBreak2 on this device unless `-Force` is explicitly supplied.

## One-script workflow

From PowerShell:

```powershell
cd C:\Users\Administrator\Projects\Kindle

# Identify the Kindle, firmware, recommended method, and KOReader package.
powershell -ExecutionPolicy Bypass -File .\scripts\kindle-jailbreak.ps1 -Action Diagnose

# Download all current helper packages used by this workspace.
powershell -ExecutionPolicy Bypass -File .\scripts\kindle-jailbreak.ps1 -Action DownloadModern

# Prepare a below-5.16.4 Kindle with WinterBreak2 and OTA-space filler.
powershell -ExecutionPolicy Bypass -File .\scripts\kindle-jailbreak.ps1 -Action Prepare

# Stage AdBreak assets for a registered ad-supported 5.18.1-5.18.5.0.1 Kindle.
# This rewrites the Kindle ad .assets folder and requires an original backup.
powershell -ExecutionPolicy Bypass -File .\scripts\kindle-jailbreak.ps1 -Action StageAdBreak -Force

# After the on-device jailbreak completes, stage hotfix/MRPI/KUAL/KOReader.
powershell -ExecutionPolicy Bypass -File .\scripts\kindle-jailbreak.ps1 -Action StagePostJailbreak -Force

# Safely request eject.
powershell -ExecutionPolicy Bypass -File .\scripts\kindle-jailbreak.ps1 -Action Eject
```

## Action map

| Action | Purpose |
| --- | --- |
| `Diagnose` | Detect Kindle root, firmware, serial, free space, installed folders, and recommended jailbreak method. |
| `DownloadLegacy` | Download the pinned PW2/WinterBreak2 package set from the manifest and verify SHA-256. |
| `DownloadModern` | Download legacy packages plus AdBreak, PEKI, and KOReader `kindlehf` for firmware `>=5.16.3`. |
| `BuildLegacy` | Build the old `staging/winterbreak2-root` and `staging/post-jailbreak-root` trees. |
| `Prepare` | Auto-stage WinterBreak2 only when firmware is below `5.16.4`; otherwise prints the safe method. |
| `StageWinterBreak2` | Copy WinterBreak2 root files. Blocks on incompatible firmware unless `-Force` is used. |
| `StageAdBreak` | Backup and rewrite `.assets` for AdBreak. Requires `-Force` to prevent accidental destructive copy. |
| `StagePostJailbreak` | Copy hotfix, MRPI, PEKI/KUAL, and KOReader. Blocks until a jailbreak marker is seen unless `-Force` is used. |
| `FillOtaSpace` | Fill the FAT32 Kindle storage with 1 GiB chunks, leaving `-LeaveMiB` free. |
| `RemoveOtaFiller` | Remove `.kindle-ota-space-filler` and the legacy single filler file. |
| `Eject` | Request Windows safe eject for the Kindle drive. |

## Firmware routing encoded in the script

| Firmware | Script routing | Notes |
| --- | --- | --- |
| `< 5.16.4` | `winterbreak2` | Uses the original repository path: WinterBreak2, hotfix, MRPI, KUAL, KOReader. |
| `5.16.4` to `< 5.18.1` | `winterbreak` | Documented, but not automated here yet because it uses a different package tree. |
| `5.18.1` to `5.18.5.0.1` | `adbreak-or-nosebleed` | AdBreak requires a registered Kindle with ads enabled; Nosebleed depends on model support. |
| Newer/unknown | `check-current-kindlemodding` | Do not stage blindly; check KindleModding first. |

## On-device steps that cannot be automated over USB mass storage

For WinterBreak2:

1. Eject the Kindle.
2. Connect Wi-Fi only when ready.
3. Open Experimental Browser.
4. Visit `https://winterbreak2.now.sh/`.
5. Press Jailbreak and wait.
6. Turn Airplane Mode on.
7. Reconnect and run `StagePostJailbreak`.

For AdBreak:

1. Confirm the Kindle is registered and has ads/special offers enabled.
2. Let ads download.
3. Enable Airplane Mode.
4. Run `StageAdBreak -Force`.
5. Eject and unplug.
6. Use `View all ads`, open an ad, and proceed through the popups until the jailbreak runs.
7. Keep Airplane Mode on.
8. Reconnect and run `StagePostJailbreak -Force`.

For post-jailbreak:

1. If hotfix is required, use Settings -> Update Your Kindle.
2. Run the `Run Hotfix` booklet if it appears.
3. Open `KUAL.sh`/PEKI from the library to install or launch KUAL on modern devices.
4. Launch KOReader from KUAL.

## Package notes

The Windows script keeps both generations:

| Package | Use |
| --- | --- |
| `wb2.zip` | Legacy WinterBreak2 staging for firmware below `5.16.4`. |
| `Update_hotfix_universal.bin` | Hotfix after compatible jailbreak methods that require it. |
| `kual-mrinstaller-khf.zip` | MRPI root folders. |
| `Update_KUALBooklet_HDRepack.bin` | Legacy KUAL booklet package for the old PW2 path. |
| `PEKI-latest.zip` | Modern KUAL launcher path: copy `KUAL.jar` and `KUAL.sh` into `documents`. |
| `koreader-kindlepw2-v2026.03.zip` | KOReader for PW2/newer firmware `<=5.16.2.1.1`. |
| `koreader-kindlehf-v2026.03.zip` | KOReader for firmware `>=5.16.3`. |
| `AdBreak-latest.zip` | AdBreak assets for supported registered ad-enabled firmware. |

## Safety rules

- Do not run WinterBreak2 on the current `5.18.1` Kindle.
- Do not run `StageAdBreak -Force` unless ads are enabled and visible on the Kindle.
- Keep Airplane Mode on whenever a script frees OTA-blocking space.
- Exit KOReader before USB transfers; KOReader can block USB mass storage mode.
- Backups of rewritten AdBreak assets go under `device-backups/` and remain ignored by git.

## Sources

- KindleModding home: https://kindlemodding.org/
- WinterBreak2: https://kindlemodding.org/jailbreaking/WinterBreak2/
- WinterBreak: https://kindlemodding.org/jailbreaking/WinterBreak/
- AdBreak: https://kindlemodding.org/jailbreaking/AdBreak/
- Nosebleed: https://kindlemodding.org/jailbreaking/Nosebleed/
- Hotfix: https://kindlemodding.org/jailbreaking/post-jailbreak/setting-up-a-hotfix/
- KUAL/MRPI: https://kindlemodding.org/jailbreaking/post-jailbreak/installing-kual-mrpi/
- KOReader: https://kindlemodding.org/jailbreaking/post-jailbreak/koreader.html
