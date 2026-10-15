"""Device-scoped display names; uploaded events remain immutable for safe retries."""
import json
from pathlib import PureWindowsPath


def display_name(aliases, process, original):
    key = process.strip().replace("/", "\\").rsplit("\\", 1)[-1].casefold()
    return aliases.get(key) or aliases.get(PureWindowsPath(key).stem) or original


def device_aliases(db, device_id):
    row = db.execute("SELECT aliases FROM device_app_aliases WHERE device_id=?", (device_id,)).fetchone()
    return json.loads(row[0]) if row else {}
