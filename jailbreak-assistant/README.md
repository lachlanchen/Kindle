# Kindle Jailbreak Assistant

A cross-platform LazyingArt desktop assistant for matching a Kindle model and firmware to a documented jailbreak route, then automating the reversible host-side work.

## What it automates

- Discovers mounted Kindle filesystems on Windows, Linux, and macOS.
- Resolves serial prefixes using the live KindleModding model matrix.
- Routes current and legacy models using firmware and prerequisite rules.
- Downloads only official packages and verifies published SHA-256 digests.
- Rejects archive traversal, links, and device-special files.
- Backs up every conflicting file before staging payloads.
- Runs the official SpringBreak helper for the current host platform.
- Stages Nosebleed, WinterBreak, WinterBreak2, AdBreak, and the universal hotfix.
- Creates and removes a clearly marked, reversible low-space OTA guard.
- Refreshes the compatibility catalog without requiring a new binary.

## What it deliberately does not automate

- Unknown or unsupported firmware.
- Factory resets or firmware downgrades.
- Deleting books or arbitrary Kindle folders.
- Account registration, ads, browser taps, Store timing, or success confirmation.
- Serial-pin wiring, partition flashing, or hardware jailbreaks.

Those boundaries prevent a friendly GUI from turning uncertainty into a brick.

## Run from source

Windows:

```powershell
cd jailbreak-assistant
.\run-windows.bat
```

Ubuntu/Linux:

```sh
cd jailbreak-assistant
chmod +x run-linux.sh
./run-linux.sh
```

macOS:

```sh
cd jailbreak-assistant
chmod +x run-macos.command
./run-macos.command
```

## Build

```sh
python -m pip install -r requirements-build.txt
python build.py --clean-output
```

Release binaries are built for Windows x64, Linux x64/ARM64, macOS Intel, and macOS Apple Silicon by `.github/workflows/release-jailbreak-assistant.yml`.

## Compatibility maintenance

The embedded catalog is `compatibility.json`. Released apps refresh it from the repository and refresh model/serial data from `https://kindlemodding.org/models.json`. Update the catalog when upstream prerequisites, assets, or digests change; do not loosen a firmware rule without an authoritative source.

This project is an independent convenience layer. Kindle and Amazon are trademarks of Amazon.com, Inc. Upstream jailbreak methods remain the work of their respective authors.

