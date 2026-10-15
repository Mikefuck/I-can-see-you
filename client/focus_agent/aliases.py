"""Process-name matching shared by settings, the picker and local record display."""
from pathlib import PureWindowsPath


def process_key(process):
    return str(process).strip().replace("/", "\\").rsplit("\\", 1)[-1].casefold()


def alias_for(aliases, process):
    key = process_key(process)
    return aliases.get(key) or aliases.get(PureWindowsPath(key).stem)
