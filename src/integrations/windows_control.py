"""
windows_control.py - Windows system control: apps, volume, brightness, windows management
"""
import os
import subprocess
import logging

logger = logging.getLogger(__name__)

APP_MAP = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "vscode": "code", "visual studio code": "code", "vs code": "code",
    "terminal": "wt.exe", "windows terminal": "wt.exe",
    "explorer": "explorer.exe", "file explorer": "explorer.exe",
    "notepad": "notepad.exe",
    "spotify": "spotify.exe",
    "discord": "discord.exe",
    "steam": "steam.exe",
    "calculator": "calc.exe",
    "word": "winword.exe", "microsoft word": "winword.exe",
    "excel": "excel.exe", "microsoft excel": "excel.exe",
    "outlook": "outlook.exe",
    "teams": "teams.exe", "microsoft teams": "teams.exe",
    "paint": "mspaint.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:", "windows settings": "ms-settings:",
    "snipping tool": "SnippingTool.exe",
}


def open_app(app_name: str) -> str:
    name = app_name.lower().strip()
    exe = APP_MAP.get(name)
    try:
        if exe:
            if exe.startswith("ms-"):
                subprocess.Popen(["start", exe], shell=True)
            else:
                subprocess.Popen(exe, shell=True)
        else:
            subprocess.Popen(["start", "", app_name], shell=True)
        return f"Opening {app_name}."
    except Exception as e:
        return f"Couldn't open {app_name}: {e}"


def close_app(app_name: str) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-Command", f'Stop-Process -Name "{app_name}" -Force'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return f"Closed {app_name}."
        return f"Couldn't close {app_name}: {result.stderr.strip()}"
    except Exception as e:
        return f"Close error: {e}"


def set_volume(level: int) -> str:
    level = max(0, min(100, level))
    try:
        # Try via pycaw
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        import math
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        return f"Volume set to {level}%."
    except Exception:
        # Fallback via PowerShell
        try:
            script = (
                f"$vol=[math]::Round({level}/100*65535);"
                "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
                "[System.Windows.Forms.SendKeys]::SendWait('%{F4}')"
            )
            subprocess.run(["powershell", "-Command",
                           f"$wscript = New-Object -ComObject WScript.Shell; "
                           f"for ($i=0; $i -lt 50; $i++) {{ $wscript.SendKeys([char]175) }}"],
                          timeout=3)
            return f"Volume adjusted to approximately {level}%."
        except Exception as e:
            return f"Volume error: {e}"


def get_volume() -> str:
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        level = int(volume.GetMasterVolumeLevelScalar() * 100)
        return f"Volume is at {level}%."
    except Exception as e:
        return f"Volume check error: {e}"


def set_brightness(level: int) -> str:
    level = max(0, min(100, level))
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(level)
        return f"Brightness set to {level}%."
    except Exception as e:
        return f"Brightness error: {e}"


def lock_workstation() -> str:
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return "Workstation locked."
    except Exception as e:
        return f"Lock error: {e}"


def take_screenshot(filename: str = None) -> str:
    try:
        import mss
        from PIL import Image
        import os
        from datetime import datetime
        if not filename:
            filename = f"Screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        dest = os.path.join(os.path.expanduser("~"), "Desktop", filename)
        with mss.mss() as sct:
            sct.shot(output=dest)
        return f"Screenshot saved to {dest}."
    except Exception as e:
        return f"Screenshot error: {e}"


def focus_window(title: str) -> str:
    try:
        import win32gui
        import win32con

        def enum_callback(hwnd, result):
            if title.lower() in win32gui.GetWindowText(hwnd).lower():
                result.append(hwnd)

        handles = []
        win32gui.EnumWindows(enum_callback, handles)
        if handles:
            win32gui.ShowWindow(handles[0], win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(handles[0])
            return f"Focused window: {win32gui.GetWindowText(handles[0])}"
        return f"No window found matching '{title}'."
    except Exception as e:
        return f"Focus error: {e}"
