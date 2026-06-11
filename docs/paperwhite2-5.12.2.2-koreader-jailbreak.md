# Kindle PW2 5.12.2.2 Jailbreak and KOReader Setup

Date prepared: 2026-06-11

Device target: Kindle Paperwhite 6th generation / PW2  
Firmware: `5.12.2.2`

## Summary

Firmware `5.12.2.2` is below `5.16.4`, so the selected path is:

1. WinterBreak2
2. Universal Hotfix
3. MRPI
4. KUAL
5. KOReader `kindlepw2`

This workflow is for running homebrew such as KOReader on your own Kindle. It is
not for DRM removal.

## Current Computer Status

The Kindle was detected and staged successfully.

Observed on 2026-06-11:

- `lsblk` showed `/dev/sdc1`, label `Kindle`, mounted at
  `/media/lachlan/Kindle`.
- `lsusb` showed `1949:0004 Lab126, Inc. Amazon Kindle 3/4/Paperwhite`.
- A visible-root backup was saved in:
  `/home/lachlan/Projects/Kindle/device-backups/kindle-visible-root-20260611-170916`.
- WinterBreak2 was copied to Kindle root:
  - `jb.sh`
  - `patchedUks.sqsh`
  - `winterbreak2/dialoger.html`
- A temporary `.kindle-ota-space-filler.bin` was written to leave about 81 MiB
  free for the browser/jailbreak step.
- The Kindle filesystem was unmounted afterward.

Earlier connection issue:

- The cable is charge-only.
- The Kindle is not in USB Drive Mode.
- USB is connected to a remote/RDP machine but not passed through to Ubuntu.
- The Kindle is connected to the wrong physical computer or hub.

## Downloads

Files are stored in:

```bash
/home/lachlan/Projects/Kindle/downloads
```

Downloaded files:

| File | Purpose | SHA-256 |
| --- | --- | --- |
| `wb2.zip` | WinterBreak2 jailbreak files | `932ff113c414c9b0109b98d7f4b96da20815364fb4905e4483581b881b2ae2e2` |
| `Update_hotfix_universal.bin` | Universal jailbreak hotfix | `94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59` |
| `kual-mrinstaller-khf.zip` | MRPI installer package | `9974dfc2d1e7687b3fc74d68f6b5aeab2428f22d83ab82e6d600a0384c607d09` |
| `Update_KUALBooklet_HDRepack.bin` | KUAL package installed through MRPI | `a0cd1f490b2fc779457990cefa4a9ae53921fc8c2b5551f095500be3b55fc20a` |
| `koreader-kindlepw2-v2026.03.zip` | KOReader package for PW2/newer firmware <= 5.16.2.1.1 | `46e969bb13765b2630b5e14aa2e7fa2445ec551ccaa47db3efe644d0e34944b0` |

Verify:

```bash
/home/lachlan/Projects/Kindle/scripts/check-downloads.sh
```

## Why These Packages

The KindleModding WinterBreak2 guide says WinterBreak2 works on firmware below
`5.16.4`, and the install flow copies `jb.sh`, `patchedUks.sqsh`, and the
`winterbreak2` folder to the Kindle root before opening the Experimental
Browser.

The KindleModding KOReader guide says KOReader needs a jailbroken Kindle with
MRPI and KUAL, and that the `kindlepw2` package is for PW2 and newer models
running firmware `<= 5.16.2.1.1`.

The KUAL/MRPI guide says to copy MRPI's `extensions` and `mrpackages` folders to
the Kindle, put `Update_KUALBooklet_HDRepack.bin` in `mrpackages`, then run
`;log mrpi` from the Kindle search bar.

The Hotfix guide says to copy `Update_hotfix_universal.bin` to the Kindle root,
install it from `Update Your Kindle`, then run the `Run Hotfix` booklet.

Sources:

- WinterBreak2: https://kindlemodding.org/jailbreaking/WinterBreak2/
- Universal Hotfix: https://kindlemodding.org/jailbreaking/post-jailbreak/setting-up-a-hotfix/
- KUAL and MRPI: https://kindlemodding.org/jailbreaking/post-jailbreak/installing-kual-mrpi/
- KOReader: https://kindlemodding.org/jailbreaking/post-jailbreak/koreader.html
- Hotfix repository: https://github.com/KindleModding/Hotfix
- KOReader releases: https://github.com/koreader/koreader/releases

## Workspace Layout

```text
/home/lachlan/Projects/Kindle/
  downloads/              original package downloads
  packages/               extracted package cache
  staging/
    winterbreak2-root/    copy this to Kindle root before jailbreak
    post-jailbreak-root/  copy this after WinterBreak2 succeeds
  scripts/                helper scripts
  firmware/               firmware notes; no firmware file needed now
  logs/downloads.sha256   package hashes
```

## Step 1: Make the Kindle Visible

Connect the Kindle directly to this Ubuntu computer with a data-capable USB
cable. The Kindle should display USB Drive Mode.

Check from Ubuntu:

```bash
/home/lachlan/Projects/Kindle/scripts/detect-kindle.sh
lsblk -o NAME,MODEL,SIZE,FSTYPE,LABEL,MOUNTPOINTS,TRAN,TYPE
```

If the Kindle is connected through a remote Windows/RDP path, USB mass storage
must be explicitly redirected to Ubuntu. Otherwise Ubuntu cannot copy files to
it.

## Step 2: Stage WinterBreak2

Status: completed on 2026-06-11.

Once the Kindle is visible:

```bash
/home/lachlan/Projects/Kindle/scripts/stage-winterbreak2.sh
```

If needed, pass the mount path explicitly:

```bash
/home/lachlan/Projects/Kindle/scripts/stage-winterbreak2.sh /media/lachlan/Kindle
```

Expected Kindle root files after copy:

```text
jb.sh
patchedUks.sqsh
winterbreak2/
```

Eject:

```bash
/home/lachlan/Projects/Kindle/scripts/eject-kindle.sh
```

## Step 3: Run WinterBreak2 on the Kindle

Status: waiting for user action on the Kindle.

On the Kindle:

1. Connect to Wi-Fi.
2. Open Experimental Browser.
3. Go to `https://winterbreak2.now.sh/`.
4. Press the Jailbreak button.
5. Wait for completion.
6. Turn Airplane Mode on after the jailbreak completes.
7. If present, delete `update.bin.tmp.partial` from Kindle storage before the
   post-jailbreak stage.

## Step 4: Stage Hotfix, MRPI, KUAL, and KOReader

Status: not yet run.

Reconnect the Kindle to Ubuntu after WinterBreak2 succeeds:

```bash
/home/lachlan/Projects/Kindle/scripts/stage-post-jailbreak.sh
```

This copies:

- Removes `.kindle-ota-space-filler.bin` first.
- `Update_hotfix_universal.bin` to Kindle root.
- MRPI `extensions/` and `mrpackages/` to Kindle root.
- `Update_KUALBooklet_HDRepack.bin` into `mrpackages/`.
- KOReader `extensions/` and `koreader/` to Kindle root.

Eject again:

```bash
/home/lachlan/Projects/Kindle/scripts/eject-kindle.sh
```

## Step 5: Finish on the Kindle

On the Kindle:

1. Open Settings.
2. Use the menu and select `Update Your Kindle` to install the hotfix.
3. After reboot, open the `Run Hotfix` booklet if it appears.
4. In the Kindle search bar, enter `;log mrpi` and press enter.
5. Wait for MRPI to install KUAL.
6. Open KUAL from the library.
7. Launch KOReader.

If KUAL/MRPI does not run, check free space. The KindleModding guide warns that
installing KUAL and MRPI may require about 220 MB of available space.

## Maintenance Notes

- Keep Airplane Mode on unless Wi-Fi is needed.
- Avoid Amazon OTA updates unless you intentionally update and understand the
  jailbreak impact.
- After any OTA update, run the `Run Hotfix` booklet again if it is present.
- KOReader can block normal USB mass storage while running; exit KOReader before
  connecting for file transfer.
