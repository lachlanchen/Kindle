# Kindle Book Sender

A cross-platform desktop app for sending books to KOReader without asking a
layperson to find an IP address or use SSH commands.

## User flow

1. On first use for a Kindle, connect its KOReader storage by USB.
2. The app verifies the bundled shared Kindle-only RSA identity against the
   pinned fingerprint below and appends only its derived public line to
   `koreader/settings/SSH/authorized_keys`. If that identity is already present,
   a different trailing comment is accepted and no duplicate line is added.
3. Safely eject the Kindle.
4. Put the computer and Kindle on the same trusted Wi-Fi.
5. In KOReader, start Tools > SSH server.
6. Click We're on the same Wi-Fi - Find my Kindle.
7. Drag in books and click Send books.

Discovery scans only active private IPv4 networks for TCP port 2222, then
authenticates with the shared Kindle-only key and verifies `/mnt/us/koreader`.
Transfers use SFTP when the server provides it and automatically fall back to
SCP otherwise.

## Shared key identity and migration

This app deliberately uses the already-published repository identity at
`Handoff/keys/kindle_handoff_rsa` on every computer. Frozen builds bundle that
same tracked file at `Handoff/keys/kindle_handoff_rsa`; source runs reference it
in place. The app derives the public line from the private key in memory and
refuses any asset whose OpenSSH SHA-256 fingerprint is not:

`SHA256:Q/RgMY4wzHjQYuC3sfHDykwp8ejp9C7wyfAZLE8OMJE`

This private key is public and is **not a secret**. Anyone with the repository
or a packaged app can use it to authenticate to a Kindle that authorizes its
public half. Use it only for the dedicated Kindle/KOReader workflow on a trusted
LAN, and stop KOReader SSH when finished. Never reuse it for another account,
computer login, or service.

Older releases generated a per-computer pair named `kindle_sender_rsa` under
the current user's application-data `keys` directory. Before using the shared
identity, this release moves any prior pair into a private
`keys/legacy-key-backups/legacy-*` directory. It neither prints nor overwrites
the old key. The remembered IP and other preferences remain in the application
data directory; no setting can silently select a different SSH identity.

## Run from source

    python -m venv .venv
    python -m pip install -r app/requirements.txt
    python app/kindle_sender.py

## Build

PyInstaller must run separately on each target operating system:

    python -m pip install -r app/requirements-build.txt
    python app/build.py

To build from the reviewed spec without regenerating it:

    cd app
    python -m PyInstaller --noconfirm --clean "Kindle Book Sender.spec"

Local key and packaging tests do not access a Kindle or the network:

    python -m unittest discover -s app/tests -v

GitHub Actions produces Windows x64, Linux x64, macOS Apple Silicon, and macOS
Intel release downloads. `app/build.py` and `app/Kindle Book Sender.spec` both
include the existing tracked Handoff private-key asset; they do not maintain a
second source copy.
