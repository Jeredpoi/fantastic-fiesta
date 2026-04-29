#!/usr/bin/env python3
"""
Build script: creates a standalone executable from the Python sources.

Usage:
    python build.py

Requirements: Python 3.9+, pip (PyInstaller will be installed automatically).
Output:       dist/LaserBoxMaker.exe  (Windows)
              dist/LaserBoxMaker      (Linux / macOS)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run(*args: str) -> None:
    print(f"\n>>> {' '.join(args)}\n")
    subprocess.run(list(args), check=True)


def main() -> None:
    root = Path(__file__).parent.resolve()

    run(sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller")

    run(
        sys.executable, "-m", "PyInstaller",
        "--onefile",          # single exe, no extra folder
        "--windowed",         # no console window (tkinter app)
        "--name", "LaserBoxMaker",
        "--distpath", str(root / "dist"),
        "--workpath", str(root / "build"),
        "--specpath", str(root),
        str(root / "app.py"),
    )

    exe = root / "dist" / ("LaserBoxMaker.exe" if sys.platform == "win32" else "LaserBoxMaker")
    print(f"\nГотово!  →  {exe}")


if __name__ == "__main__":
    main()
