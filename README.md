# Kindle Paperwhite 2 / 6th Gen Workspace

This workspace is for Lachlan's Kindle Paperwhite 6th generation / PW2 on
firmware `5.12.2.2`.

The goal is a clean WinterBreak2 jailbreak path, then Hotfix, MRPI, KUAL, and
KOReader.

## Current Status

- Downloads are complete in `downloads/`.
- Package staging trees are built in `staging/`.
- Helper scripts are in `scripts/`.
- The Kindle was detected at `/media/lachlan/Kindle`.
- A visible-root backup was saved under `device-backups/`.
- WinterBreak2 files were copied to the Kindle root.
- WinterBreak completed on the Kindle; `winterbreak.log` confirms developer
  keys were installed and the jailbreak finished.
- Hotfix, MRPI, KUAL, and KOReader were copied to the Kindle.
- The temporary OTA space filler was removed.
- The Kindle filesystem was unmounted after post-jailbreak staging.

Run this after reconnecting the Kindle:

```bash
./scripts/detect-kindle.sh
```

## Main Commands

Verify downloads:

```bash
./scripts/check-downloads.sh
```

Rebuild extracted package cache and copy-ready staging trees:

```bash
./scripts/build-staging.sh
```

Stage WinterBreak2 to the Kindle root:

```bash
./scripts/stage-winterbreak2.sh
```

After the on-device jailbreak succeeds, stage Hotfix, MRPI, KUAL, and KOReader:

```bash
./scripts/stage-post-jailbreak.sh
```

This has already been run. The next required action is on the Kindle:

1. Install `Update_hotfix_universal.bin` with `Update Your Kindle`.
2. After reboot, open the `Run Hotfix` booklet if it appears.
3. Search for `;log mrpi` to install KUAL.
4. Open KUAL and launch KOReader.

Sync LinguaLeaf color PDFs to a KOReader-friendly folder:

```bash
./scripts/sync-lingualleaf-books.sh
```

The books are copied to:

```text
documents/LinguaLeaf/en-main-color/
```

If auto-detection fails but you know the mount root:

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## Layout

- `downloads/`: original downloaded packages.
- `packages/`: extracted packages.
- `staging/winterbreak2-root/`: files copied to Kindle root before jailbreak.
- `staging/post-jailbreak-root/`: files copied after WinterBreak2 succeeds.
- `firmware/`: reserved for firmware notes or official firmware files.
- `docs/`: local procedure notes.
- `references/`: command and file references for repeatable workflows.
- `logs/downloads.sha256`: hashes for the downloaded packages.

See `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` for the full procedure.
