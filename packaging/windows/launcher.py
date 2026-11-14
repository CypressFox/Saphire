"""Entry point PyInstaller freezes into Sapphire.exe (it needs a script, not -m).

Build (on Windows, Python 3.13):
    pip install . pyinstaller pillow
    pyinstaller packaging/windows/launcher.py --name Sapphire --onefile --windowed ^
        --icon sapphire/assets/sapphire-512.png ^
        --collect-data sapphire --collect-submodules sapphire --noconfirm

The GitHub Actions workflow (.github/workflows/windows.yml) does exactly this on
every push and attaches the .exe to tagged releases.
"""

import sys

from sapphire.__main__ import _main

if __name__ == "__main__":
    sys.exit(_main())
