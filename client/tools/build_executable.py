"""Run PyInstaller with a controlled DLL search path inside the Python process."""
import os
from pathlib import Path
import sys


def main():
    # Some launchers restore PATH when starting Python. Sanitize it here so
    # PyInstaller never bundles unrelated tools' OpenSSL, ICU or UCRT DLLs.
    windows = Path(os.environ["SystemRoot"])
    os.environ["PATH"] = os.pathsep.join(map(str, [
        Path(sys.executable).parent,
        Path(sys.base_prefix),
        Path(sys.base_prefix) / "DLLs",
        windows / "System32",
        windows,
    ]))
    from PyInstaller.__main__ import run
    run(sys.argv[1:])


if __name__ == "__main__":
    main()
