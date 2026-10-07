"""'Przypnij do belki' of the tray menu: a Start menu shortcut of the program.

Windows has no supported call that pins a program to the taskbar (since Windows 10 only the user can do it, from the right-click menu of a
shortcut / of the running program's taskbar button). What the program CAN do is to keep a shortcut in the user's Start menu, which Windows
then offers for pinning and which stays when the program is closed. `pin` creates it, `unpin` removes it, `is_pinned` tells which one the
tray menu offers (the two items alternate)."""
from __future__ import annotations

import os
import subprocess

NAME = "S7Trace"


def shortcut_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", NAME + ".lnk")


def is_pinned() -> bool:
    return os.path.exists(shortcut_path())


def pin(target: str, args: str, workdir: str, icon: str = "") -> bool:
    """Create the shortcut (WScript.Shell through PowerShell, values in the environment so no quoting problems). True = created."""
    if os.name != "nt":
        return False
    path = shortcut_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        env = dict(os.environ, S7T_LNK=path, S7T_TARGET=target, S7T_ARGS=args, S7T_DIR=workdir, S7T_ICON=icon or target, S7T_NAME=NAME)
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:S7T_LNK);$s.TargetPath=$env:S7T_TARGET;$s.Arguments=$env:S7T_ARGS;"
              "$s.WorkingDirectory=$env:S7T_DIR;$s.IconLocation=$env:S7T_ICON;$s.Description=$env:S7T_NAME;$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env, capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return is_pinned()


def unpin() -> bool:
    try:
        os.remove(shortcut_path())
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return not is_pinned()
