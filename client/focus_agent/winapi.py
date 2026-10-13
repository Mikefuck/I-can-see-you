import base64
import ctypes
import functools
import getpass
import logging
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from .tracker import Application


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Task Manager / Settings › Apps › Startup disable an entry here without removing the Run value.
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
STARTUP_NAME = "FocusLedger"
EVENT_WINDOW_TITLE = "Focus Ledger system events"
WM_SHOW_REQUEST = 0x8000 + 0x46  # WM_APP-based private message: "show the main window"
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def clean_text(text):
    """Replace unpaired surrogates (legal in NTFS names) so JSON and SQLite encoding never fail."""
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


class Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def protect_text(text, decrypt=False):
    raw = base64.b64decode(text, validate=True) if decrypt else text.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [ctypes.c_void_p], ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        output = ctypes.string_at(target.pbData, target.cbData)
        return output.decode("utf-8") if decrypt else base64.b64encode(output).decode("ascii")
    finally:
        kernel.LocalFree(target.pbData)


def encrypt(text):
    return protect_text(text)


def decrypt(text):
    return protect_text(text, True)


def startup_command():
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--startup"]
    else:
        executable = Path(sys.executable).with_name("pythonw.exe")
        command = [str(executable), str(Path(__file__).resolve().parents[1] / "main.py"), "--startup"]
    return subprocess.list2cmdline(command)


def registry_value(path, name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def startup_enabled():
    """Whether Windows will really launch the agent at sign-in (Run entry present and not disabled)."""
    if registry_value(RUN_KEY, STARTUP_NAME) is None:
        return False
    approved = registry_value(APPROVED_KEY, STARTUP_NAME)
    # An odd first byte marks the entry as disabled; a missing value means enabled.
    return not (isinstance(approved, bytes) and approved[:1] and approved[0] & 1)


def set_startup(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, STARTUP_NAME)
            except FileNotFoundError:
                pass
    # Without this, re-enabling here after a Task Manager "disable" silently has no effect.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, STARTUP_NAME)
    except FileNotFoundError:
        pass


def refresh_startup_path():
    """Point an existing startup entry at this executable, e.g. after the program folder was moved."""
    import winreg
    current = registry_value(RUN_KEY, STARTUP_NAME)
    # Source checkouts never rewrite the entry, so a dev run cannot hijack an installed copy.
    if not getattr(sys, "frozen", False) or current is None or current == startup_command():
        return False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, startup_command())
    return True


class SingleInstance:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateMutexW(None, False, "Local\\FocusLedger-" + getpass.getuser())
        error = ctypes.get_last_error()
        if not self.handle:
            raise ctypes.WinError(error)
        self.already_running = error == 183

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


@functools.lru_cache(maxsize=256)
def file_description(path):
    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype = wintypes.BOOL
    ignored = wintypes.DWORD()
    size = version.GetFileVersionInfoSizeW(path, ctypes.byref(ignored))
    if not size:
        return Path(path).stem
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, buffer):
        return Path(path).stem
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if version.VerQueryValueW(buffer, r"\VarFileInfo\Translation", ctypes.byref(pointer), ctypes.byref(length)) and length.value >= 4:
        language, codepage = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ushort))[:2]
        query = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\FileDescription"
        if version.VerQueryValueW(buffer, query, ctypes.byref(pointer), ctypes.byref(length)):
            description = ctypes.wstring_at(pointer, max(0, length.value - 1)).replace("\0", "").strip()
            return clean_text(description or Path(path).stem)[:200]
    return clean_text(Path(path).stem)[:200]


class LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),
        ("Reserved", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def power_status(ac_line, flag, percent, life_seconds):
    """Normalize SYSTEM_POWER_STATUS; every value must stay inside the server's accepted ranges,
    because one rejected record would hold back the whole upload batch."""
    unknown = flag == 255
    no_battery = not unknown and bool(flag & 128)
    return {
        "battery_percent": None if no_battery or not 0 <= percent <= 100 else int(percent),
        "charging": None if unknown or no_battery else bool(flag & 8),
        "ac_online": None if ac_line not in (0, 1) else bool(ac_line),
        "battery_life_seconds": None if no_battery or life_seconds == 0xFFFFFFFF else int(life_seconds),
    }


class BatteryReader:
    """Read the current Windows power state without requiring extra packages."""
    def __init__(self):
        self.kernel = None
        if sys.platform == "win32":
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
            self.kernel.GetSystemPowerStatus.restype = wintypes.BOOL

    def status(self):
        if self.kernel is None:
            return None
        value = SYSTEM_POWER_STATUS()
        if not self.kernel.GetSystemPowerStatus(ctypes.byref(value)):
            return None
        return power_status(value.ACLineStatus, value.BatteryFlag, value.BatteryLifePercent, value.BatteryLifeTime)


class ForegroundReader:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.EnumChildWindows.argtypes = [wintypes.HWND, ENUM_WINDOWS_PROC, wintypes.LPARAM]
        self.user.EnumChildWindows.restype = wintypes.BOOL
        self.user.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInput)]
        self.user.GetLastInputInfo.restype = wintypes.BOOL
        self.user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.user.OpenInputDesktop.restype = wintypes.HANDLE
        self.user.CloseDesktop.argtypes = [wintypes.HANDLE]
        self.user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetUserObjectInformationW.restype = wintypes.BOOL
        self.kernel.GetTickCount.restype = wintypes.DWORD
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.aliases = {}

    def set_aliases(self, aliases):
        self.aliases = {str(key).strip().casefold(): str(value).strip()
                        for key, value in (aliases or {}).items() if str(key).strip() and str(value).strip()}

    def alias_for(self, process):
        """Match "chrome.exe" by its full name first, then by "chrome" so the suffix may be omitted."""
        key = process.casefold()
        return self.aliases.get(key) or self.aliases.get(Path(key).stem)

    def _window_process(self, window):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        return pid.value

    def _process_path(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                return None
            return path.value or None
        finally:
            self.kernel.CloseHandle(handle)

    def _hosted_process(self, frame, host_pid):
        """Store (UWP) apps are framed by ApplicationFrameHost.exe; the app process owns a child window."""
        found = []

        def visit(child, _):
            pid = self._window_process(child)
            if pid and pid != host_pid:
                found.append(pid)
                return False
            return True

        self.user.EnumChildWindows(frame, ENUM_WINDOWS_PROC(visit), 0)
        return found[0] if found else None

    def sample(self, idle_seconds=300):
        if idle_seconds:
            info = LastInput(ctypes.sizeof(LastInput), 0)
            if not self.user.GetLastInputInfo(ctypes.byref(info)):
                return None, "暂时无法读取会话状态"
            idle = ((self.kernel.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000
            if idle >= idle_seconds:
                return None, "用户空闲，暂停计时"
        desktop = self.user.OpenInputDesktop(0, False, 0x0001)
        if not desktop:
            return None, "锁屏或安全桌面，暂停计时"
        try:
            name = ctypes.create_unicode_buffer(256)
            required = wintypes.DWORD()
            if not self.user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(required)):
                return None, "暂时无法读取桌面状态"
            if name.value.casefold() != "default":
                return None, "锁屏或安全桌面，暂停计时"
        finally:
            self.user.CloseDesktop(desktop)
        window = self.user.GetForegroundWindow()
        if not window:
            return None, "没有可读取的前台应用"
        pid = self._window_process(window)
        if not pid or pid == os.getpid():
            return None, "客户端设置界面不计时"
        path = self._process_path(pid)
        if path is None:
            return None, "前台进程不可读取，暂停计时"
        if Path(path).name.casefold() == "applicationframehost.exe":
            hosted = self._hosted_process(window, pid)
            path = (hosted and self._process_path(hosted)) or path
        process = clean_text(Path(path).name)[:200]
        display_name = self.alias_for(process) or file_description(path)
        return Application(display_name[:200], process), "正在记录前台应用"


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
    ]


class SystemEventWindow:
    """Hidden top-level window that receives session-end and power broadcasts.

    Qt creates native windows only for widgets that have been shown, so after a silent start
    nothing in the process would receive WM_QUERYENDSESSION or WM_POWERBROADCAST. Message-only
    windows do not receive broadcasts either, hence an ordinary window that is never shown.
    It must be created on the GUI thread; Qt's event loop dispatches its messages.
    """
    WM_QUERYENDSESSION = 0x0011
    WM_ENDSESSION = 0x0016
    WM_POWERBROADCAST = 0x0218
    PBT_APMSUSPEND = 0x0004
    PBT_APMRESUMESUSPEND = 0x0007
    PBT_APMPOWERSTATUSCHANGE = 0x000A
    PBT_APMRESUMEAUTOMATIC = 0x0012

    def __init__(self, callback):
        self.callback = callback
        self.user = user = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel.GetModuleHandleW.restype = wintypes.HMODULE
        user.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.DefWindowProcW.restype = LRESULT
        user.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user.RegisterClassW.restype = wintypes.ATOM
        user.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user.CreateWindowExW.restype = wintypes.HWND
        user.DestroyWindow.argtypes = [wintypes.HWND]
        self.instance = kernel.GetModuleHandleW(None)
        self.class_name = f"FocusLedgerSystemEvents-{os.getpid()}-{id(self):x}"
        self._procedure = WNDPROC(self._window_procedure)  # must outlive the window
        window_class = WNDCLASSW(lpfnWndProc=self._procedure, hInstance=self.instance, lpszClassName=self.class_name)
        if not user.RegisterClassW(ctypes.byref(window_class)):
            raise ctypes.WinError(ctypes.get_last_error())
        # WS_EX_TOOLWINDOW keeps it out of Alt+Tab even if something ever showed it.
        self.hwnd = user.CreateWindowExW(0x00000080, self.class_name, EVENT_WINDOW_TITLE, 0,
                                         0, 0, 0, 0, None, None, self.instance, None)
        if not self.hwnd:
            error = ctypes.get_last_error()
            user.UnregisterClassW(self.class_name, self.instance)
            raise ctypes.WinError(error)
        # Windows 8+: explicit suspend/resume subscription, also covers modern-standby systems.
        self.notification = None
        register = getattr(user, "RegisterSuspendResumeNotification", None)
        if register is not None:
            register.argtypes, register.restype = [wintypes.HANDLE, wintypes.DWORD], wintypes.HANDLE
            self.notification = register(self.hwnd, 0)  # DEVICE_NOTIFY_WINDOW_HANDLE

    @classmethod
    def translate(cls, message, wparam):
        if message == cls.WM_QUERYENDSESSION:
            return "query_end_session"
        if message == cls.WM_ENDSESSION:
            return "end_session" if wparam else "end_session_cancelled"
        if message == cls.WM_POWERBROADCAST:
            return {cls.PBT_APMSUSPEND: "suspend", cls.PBT_APMRESUMESUSPEND: "resume",
                    cls.PBT_APMRESUMEAUTOMATIC: "resume", cls.PBT_APMPOWERSTATUSCHANGE: "power_status"}.get(wparam)
        if message == WM_SHOW_REQUEST:
            return "show"
        return None

    def _window_procedure(self, hwnd, message, wparam, lparam):
        event = self.translate(message, wparam)
        if event is None:
            return self.user.DefWindowProcW(hwnd, message, wparam, lparam)
        try:
            self.callback(event)
        except Exception:
            logging.exception("System event handler failed: %s", event)
        # Never veto shutdown or sleep; WM_ENDSESSION and private messages return zero.
        return 1 if message in (self.WM_QUERYENDSESSION, self.WM_POWERBROADCAST) else 0

    def close(self):
        if self.notification:
            unregister = self.user.UnregisterSuspendResumeNotification
            unregister.argtypes, unregister.restype = [wintypes.HANDLE], wintypes.BOOL
            unregister(self.notification)
            self.notification = None
        if self.hwnd:
            self.user.DestroyWindow(self.hwnd)
            self.user.UnregisterClassW(self.class_name, self.instance)
            self.hwnd = None


def activate_running_instance():
    """Ask the agent already running in this session to show its main window."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostMessageW.restype = wintypes.BOOL
    window = user.FindWindowW(None, EVENT_WINDOW_TITLE)
    if not window:
        return False
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(window, ctypes.byref(pid))
    # We were just launched by the user, so we may hand foreground rights to the running copy.
    user.AllowSetForegroundWindow(pid.value)
    return bool(user.PostMessageW(window, WM_SHOW_REQUEST, 0, 0))
