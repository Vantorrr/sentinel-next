"""Stop signals. Windows consoles do not implement add_signal_handler."""

from __future__ import annotations

from typing import Any, Callable


def install_stop_handlers(
    setter: Callable[[], None],
    *,
    platform_name: str,
    loop: Any,
    signal_module: Any,
) -> str:
    if platform_name == "win32":
        signal_module.signal(signal_module.SIGINT, lambda *_args: setter())
        sigbreak = getattr(signal_module, "SIGBREAK", None)
        if sigbreak is not None:
            signal_module.signal(sigbreak, lambda *_args: setter())
        return "win32-console"
    for sig in (signal_module.SIGINT, signal_module.SIGTERM):
        loop.add_signal_handler(sig, setter)
    return "unix"
