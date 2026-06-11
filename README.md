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
- A temporary OTA space filler was written, leaving about 81 MiB free.
- The Kindle filesystem was unmounted after staging.

Run this after reconnecting the Kindle:

```bash
/home/lachlan/Projects/Kindle/scripts/detect-kindle.sh
```

## Main Commands

Verify downloads:

```bash
/home/lachlan/Projects/Kindle/scripts/check-downloads.sh
```

Rebuild extracted package cache and copy-ready staging trees:

```bash
/home/lachlan/Projects/Kindle/scripts/build-staging.sh
```

Stage WinterBreak2 to the Kindle root:

```bash
/home/lachlan/Projects/Kindle/scripts/stage-winterbreak2.sh
```

After the on-device jailbreak succeeds, stage Hotfix, MRPI, KUAL, and KOReader:

```bash
/home/lachlan/Projects/Kindle/scripts/stage-post-jailbreak.sh
```

The post-jailbreak staging script removes `.kindle-ota-space-filler.bin`
automatically before copying Hotfix/KUAL/MRPI/KOReader.

If auto-detection fails but you know the mount root:

```bash
/home/lachlan/Projects/Kindle/scripts/stage-winterbreak2.sh /media/lachlan/Kindle
/home/lachlan/Projects/Kindle/scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## Layout

- `downloads/`: original downloaded packages.
- `packages/`: extracted packages.
- `staging/winterbreak2-root/`: files copied to Kindle root before jailbreak.
- `staging/post-jailbreak-root/`: files copied after WinterBreak2 succeeds.
- `firmware/`: reserved for firmware notes or official firmware files.
- `docs/`: local procedure notes.
- `logs/downloads.sha256`: hashes for the downloaded packages.

See `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` for the full procedure.
