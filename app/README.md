# Kindle Book Sender

A cross-platform desktop app for sending books to KOReader without asking a
layperson to find an IP address or use SSH commands.

## User flow

1. On first use, connect a KOReader Kindle by USB.
2. The app generates an RSA key unique to the local computer and appends only
   its public key to koreader/settings/SSH/authorized_keys.
3. Safely eject the Kindle.
4. Put the computer and Kindle on the same trusted Wi-Fi.
5. In KOReader, start Tools > SSH server.
6. Click We're on the same Wi-Fi - Find my Kindle.
7. Drag in books and click Send books.

Discovery scans only active private IPv4 networks for TCP port 2222, then
authenticates with the app-specific key and verifies /mnt/us/koreader.
Transfers use SFTP when the server provides it and automatically fall back to
SCP otherwise.

The private key and remembered IP are stored in the current user's application
data directory. No key is bundled into public downloads.

## Run from source

    python -m venv .venv
    python -m pip install -r app/requirements.txt
    python app/kindle_sender.py

## Build

PyInstaller must run separately on each target operating system:

    python -m pip install -r app/requirements-build.txt
    python app/build.py

GitHub Actions produces Windows x64, Linux x64, macOS Apple Silicon, and macOS
Intel release downloads.
