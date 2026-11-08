"""Parse edge config as data. Values are never executed."""

from __future__ import annotations

import re

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FORBIDDEN = ("$(", "`", "\x00")


class EnvError(ValueError):
    pass


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            raise EnvError(f"line {lineno}: export is not allowed")
        if "=" not in line:
            raise EnvError(f"line {lineno}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY.fullmatch(key):
            raise EnvError(f"line {lineno}: invalid key")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        for token in _FORBIDDEN:
            if token in value:
                raise EnvError(f"line {lineno}: commands are not allowed in values")
        values[key] = value
    return values


def render_env(values: dict[str, str]) -> str:
    lines = [f"{key}={values[key]}" for key in values]
    return "\n".join(lines) + ("\n" if lines else "")
