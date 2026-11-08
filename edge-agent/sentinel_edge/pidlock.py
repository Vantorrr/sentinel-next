"""Single instance lock. A dead pid does not block the next start."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        query = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(query, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_pid_lock(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = -1
        if pid_alive(pid) and pid != os.getpid():
            return False
    path.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_pid_lock(path: Path) -> None:
    if not path.exists():
        return
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        pid = -1
    if pid == os.getpid():
        path.unlink(missing_ok=True)
