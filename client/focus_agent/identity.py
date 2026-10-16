"""A version-independent Windows computer identity; never transmit the registry value."""

import hashlib
import sys
from functools import lru_cache
from uuid import UUID


def _windows_machine_guid():
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                        winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
    return str(UUID(value.strip()))


@lru_cache(maxsize=1)
def machine_identity():
    if sys.platform != "win32":
        return ""
    try:
        value = _windows_machine_guid()
    except (OSError, ValueError, AttributeError) as exc:
        raise RuntimeError("无法读取本机电脑识别值，请检查 Windows 系统权限后重试") from exc
    return hashlib.sha256(("FocusLedger/computer/v1|" + value).encode("utf-8")).hexdigest()
