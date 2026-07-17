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
    draw.ellipse((280, 190, 460, 370), fill="#17201C")
    draw.ellipse((564, 190, 744, 370), fill="#17201C")
    draw.rounded_rectangle((242, 165, 782, 850), radius=62, fill="#FBFAF6")
    draw.ellipse((330, 305, 465, 410), fill="#17201C")
    draw.ellipse((559, 305, 694, 410), fill="#17201C")
    draw.ellipse((479, 414, 545, 462), fill="#17201C")
    draw.line((355, 566, 669, 566), fill="#0D5C4B", width=28)
    draw.line((355, 650, 585, 650), fill="#0D5C4B", width=28)
    draw.line((385, 752, 640, 752), fill="#D78A2A", width=46)
    draw.line((575, 686, 640, 752), fill="#D78A2A", width=46)
    draw.line((575, 818, 640, 752), fill="#D78A2A", width=46)

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
