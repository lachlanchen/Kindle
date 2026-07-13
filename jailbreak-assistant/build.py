from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="Kindle-Jailbreak-Assistant")
    parser.add_argument("--clean-output", action="store_true")
    args = parser.parse_args()
    if args.clean_output:
        for path in (ROOT / "build", ROOT / "dist"):
            if path.exists():
                shutil.rmtree(path)
    separator = ";" if sys.platform == "win32" else ":"
    options = [
        str(ROOT / "main.py"),
        "--name",
        args.name,
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
        "--add-data",
        f"{ROOT / 'compatibility.json'}{separator}.",
        "--collect-all",
        "PySide6",
    ]
    if sys.platform == "darwin":
        options.extend(["--onedir", "--osx-bundle-identifier", "art.lazying.kindle-jailbreak-assistant"])
    else:
        options.append("--onefile")
    PyInstaller.__main__.run(options)


if __name__ == "__main__":
    main()

