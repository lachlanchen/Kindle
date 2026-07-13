from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "kindle_sender.py"
ASSET_DIRECTORY = ROOT / "build-assets"


def create_icon() -> Path:
    ASSET_DIRECTORY.mkdir(parents=True, exist_ok=True)
    size = 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (28, 28, size - 28, size - 28),
        radius=210,
        fill="#073C32",
    )
    draw.rounded_rectangle(
        (270, 190, 754, 818),
        radius=56,
        fill="#FBFAF6",
    )
    for y in (350, 450, 550):
        draw.line((360, y, 664, y), fill="#0D5C4B", width=30)
    draw.line((390, 700, 635, 700), fill="#D78A2A", width=45)
    draw.line((570, 635, 635, 700), fill="#D78A2A", width=45)
    draw.line((570, 765, 635, 700), fill="#D78A2A", width=45)

    system = platform.system()
    if system == "Windows":
        path = ASSET_DIRECTORY / "kindle-book-sender.ico"
        image.save(
            path,
            sizes=[
                (16, 16),
                (32, 32),
                (48, 48),
                (64, 64),
                (128, 128),
                (256, 256),
            ],
        )
    elif system == "Darwin":
        path = ASSET_DIRECTORY / "kindle-book-sender.icns"
        image.save(path, format="ICNS")
    else:
        path = ASSET_DIRECTORY / "kindle-book-sender.png"
        image.save(path)
    return path


def main() -> None:
    icon = create_icon()
    system = platform.system()
    arguments = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "Kindle Book Sender",
        "--icon",
        str(icon),
        "--collect-all",
        "paramiko",
        "--collect-all",
        "scp",
    ]

    if system == "Darwin":
        arguments.extend(
            [
                "--onedir",
                "--osx-bundle-identifier",
                "art.lazying.flow.kindle-book-sender",
            ]
        )
    else:
        arguments.append("--onefile")

    arguments.append(str(ENTRY))
    subprocess.run(arguments, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
