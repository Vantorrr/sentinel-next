"""Idempotent Windows install via a visible Task Scheduler boot task.

The task is not hidden. Installing it needs an elevated token once, because
a boot trigger that runs without an interactive login cannot be created by a
normal user. The task account is Local Service (SID S-1-5-19), not an
administrator. Config stays in ProgramData and is not replaced if it exists.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from sentinel_edge.envfile import parse_env, render_env

TASK_NAME = r"\SentinelEdge"
LOCAL_SERVICE_SID = "S-1-5-19"


def stamp_material(requirements: str, torch: str, package: str = "") -> str:
    return requirements.rstrip() + "\n" + torch.rstrip() + "\n" + package.strip() + "\n"


def package_digest(root: Path) -> str:
    """Hash the agent sources so a bugfix zip is installed, not only a dep change."""
    parts: list[str] = []
    package = root / "sentinel_edge"
    if package.is_dir():
        for path in sorted(package.glob("*.py")):
            parts.append(path.name)
            parts.append(path.read_text(encoding="utf-8"))
    manifest = root / "pyproject.toml"
    if manifest.is_file():
        parts.append(manifest.read_text(encoding="utf-8"))
    return requirements_digest("\n".join(parts))


def requirements_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pip_needed(stamp_path: Path, requirements_text: str, venv_python: Path) -> bool:
    if not venv_python.exists():
        return True
    digest = requirements_digest(requirements_text)
    if not stamp_path.exists():
        return True
    return stamp_path.read_text(encoding="utf-8").strip() != digest


def migrate_config(legacy: Path | None, dest: Path, example_text: str) -> str:
    """Keep an existing config. Copy a legacy file only when dest is absent."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return "kept"
    if legacy is not None and legacy.exists():
        values = parse_env(legacy.read_text(encoding="utf-8"))
        dest.write_text(render_env(values), encoding="utf-8")
        return "copied"
    dest.write_text(example_text, encoding="utf-8")
    return "created"


def quote_arg(value: str) -> str:
    if any(ch.isspace() for ch in value) or '"' in value:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def task_command(python_exe: Path, config_path: Path) -> tuple[str, str]:
    # -I skips sitecustomize. -P keeps the working directory off sys.path.
    arguments = "-I -P -m sentinel_edge.cli run --config " + quote_arg(str(config_path))
    return str(python_exe), arguments


def render_task_xml(python_exe: Path, config_path: Path, workdir: Path) -> str:
    command, arguments = task_command(python_exe, config_path)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Sentinel Edge reads salon cameras and sends JSON events. It does not upload video.</Description>
    <URI>{TASK_NAME}</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="LocalService">
      <UserId>{LOCAL_SERVICE_SID}</UserId>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
  </Triggers>
  <Actions Context="LocalService">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def schtasks_create_argv(xml_path: Path) -> list[str]:
    return ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"]


def schtasks_query_argv() -> list[str]:
    return ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"]


def schtasks_run_argv() -> list[str]:
    return ["schtasks", "/Run", "/TN", TASK_NAME]


def schtasks_end_argv() -> list[str]:
    return ["schtasks", "/End", "/TN", TASK_NAME]


def schtasks_delete_argv() -> list[str]:
    return ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def acl_script() -> Path:
    base = Path(__file__).resolve().parents[1]
    for candidate in (base / "packaging" / "Set-SentinelAcl.ps1", base / "Set-SentinelAcl.ps1"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Set-SentinelAcl.ps1")


class UntrustedExistingData(RuntimeError):
    """A pre-existing config or model is not owned by Administrators.

    The file is left on disk and is not loaded. The installer does not
    delete it: that choice belongs to the operator.
    """

    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths
        listed = "\n".join(str(path) for path in paths)
        super().__init__(
            "These files exist and are not owned by Administrators. "
            "They were left unchanged and were not used. "
            "Move them aside, then run Install again.\n"
            "Файлы оставлены на месте и не использовались. "
            "Переместите их в сторону и снова запустите Install.\n"
            + listed
        )


def acl_commands(data: Path) -> list[list[str]]:
    """Replace each directory DACL. Secrets are locked before the data root.

    The data preset must not walk private, app, or models: that walk grants
    Users read access for the duration of the sweep.
    """
    script = str(acl_script())
    commands = []
    for name in ("private", "app", "models", "control", "logs", "data"):
        folder = data if name == "data" else data / name
        commands.append([
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", script, "-Path", str(folder), "-Preset", name,
        ])
    return commands


def administrators_own(path: Path) -> bool:
    """False on Windows unless the Administrators group owns the path.

    A venv created by a standard user before install must not be executed.
    Tests on other platforms treat an existing path as the one the fake
    installer just created.
    """
    if not path.exists():
        return False
    if sys.platform != "win32":
        return True
    import ctypes
    owner = ctypes.c_void_p()
    security = ctypes.c_void_p()
    error = ctypes.windll.advapi32.GetNamedSecurityInfoW(
        str(path), 1, 0x00000001, ctypes.byref(owner), None, None, None, ctypes.byref(security),
    )
    if error != 0 or not owner.value:
        return False
    text = ctypes.c_wchar_p()
    ctypes.windll.advapi32.ConvertSidToStringSidW(owner, ctypes.byref(text))
    value = text.value or ""
    ctypes.windll.kernel32.LocalFree(text)
    ctypes.windll.kernel32.LocalFree(security)
    return value == "S-1-5-32-544"


def resolve_package_root(start: Path) -> Path:
    """Install.bat may live in the package root or in packaging/."""
    start = start.resolve()
    for candidate in (start, start.parent):
        if (candidate / "sentinel_edge" / "cli.py").is_file() and (
            candidate / "requirements-windows.txt"
        ).is_file():
            return candidate
    raise FileNotFoundError(f"sentinel_edge package not found from {start}")


def example_env_path(root: Path) -> Path:
    for candidate in (root / "env.example", root / "packaging" / "env.example"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("env.example")


def config_source(root: Path) -> Path | None:
    for name in ("config.env", ".env"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _windows_absolute(value: str) -> bool:
    text = value.strip().strip('"')
    if len(text) >= 3 and text[0].isalpha() and text[1] == ":":
        return True
    return text.startswith("\\\\")


def installed_model_setting(current: str, model_file: Path) -> str:
    """A bare filename follows the weights file the installer actually wrote."""
    text = current.strip()
    if not text or not (Path(text).is_absolute() or _windows_absolute(text)):
        return str(model_file)
    return text


def retire_secret_source(path: Path) -> None:
    path.write_text(
        "# Moved to %ProgramData%\\SentinelEdge\\private\\config.env\n",
        encoding="utf-8",
    )


def pip_commands(python_exe: Path, torch_file: Path, requirements: Path) -> list[list[str]]:
    return [
        [str(python_exe), "-m", "pip", "install", "-U", "pip"],
        [
            str(python_exe), "-m", "pip", "install", "-r", str(torch_file),
            "--index-url", "https://download.pytorch.org/whl/cpu",
        ],
        [str(python_exe), "-m", "pip", "install", "-r", str(requirements)],
    ]


def install_actions(
    *,
    venv_python: Path,
    stamp_path: Path,
    requirements_text: str,
    model_path: Path,
    task_registered: bool,
) -> list[str]:
    actions: list[str] = []
    if pip_needed(stamp_path, requirements_text, venv_python):
        actions.append("pip")
    if not model_path.exists() or model_path.stat().st_size <= 0:
        actions.append("model")
    if not task_registered:
        actions.append("task")
    return actions


def reject_reparse(path: Path) -> None:
    """A junction or symlink would make later icacls lock the wrong tree."""
    if path.is_symlink():
        raise RuntimeError(f"refusing symlink: {path}")
    is_junction = getattr(path, "is_junction", None)
    if path.exists() and callable(is_junction) and is_junction():
        raise RuntimeError(f"refusing junction: {path}")


def ensure_real_dir(path: Path) -> None:
    reject_reparse(path)
    path.mkdir(parents=True, exist_ok=True)
    reject_reparse(path)


def discard_planted_imports(app: Path) -> None:
    """Remove import shadows. These names are code, not salon config.

    A junction is refused instead of deleted: removing it can follow the link.
    """
    import shutil
    for name in ("sitecustomize.py", "usercustomize.py", "sentinel_edge"):
        path = app / name
        reject_reparse(path)
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    for path in app.glob("*.pth"):
        reject_reparse(path)
        if path.is_file():
            path.unlink()


def apply_install(
    root: Path,
    data: Path,
    runner,
    base_python: Path,
    owner_check=None,
) -> list[str]:
    """Install into ProgramData. The boot task must not run a user-writable tree.

    Ownership is read before any ACL change. takeown would make a planted
    venv look trusted and the elevated installer would then run it.
    """
    check = owner_check or administrators_own
    ensure_real_dir(data)
    for name in ("private", "app", "models", "control", "logs"):
        ensure_real_dir(data / name)

    dest = data / "private" / "config.env"
    model = data / "models" / "yolo11n.pt"
    flat = data / "config.env"
    blocked: list[Path] = []
    if dest.exists() and not check(dest):
        blocked.append(dest)
    if flat.is_file() and not dest.exists() and not check(flat):
        blocked.append(flat)
    if model.exists() and model.stat().st_size > 0 and not check(model):
        blocked.append(model)
    if blocked:
        raise UntrustedExistingData(blocked)

    app = data / "app"
    venv_dir = app / ".venv"
    venv_python = venv_dir / "Scripts" / "python.exe"
    if venv_dir.exists() and not check(venv_dir):
        import shutil
        shutil.rmtree(venv_dir)
    discard_planted_imports(app)
    for command in acl_commands(data):
        runner(command)

    example = example_env_path(root).read_text(encoding="utf-8")
    source = config_source(root)
    chosen = flat if not dest.exists() and flat.is_file() else source
    action = migrate_config(chosen, dest, example)
    values = parse_env(dest.read_text(encoding="utf-8"))
    model = data / "models" / "yolo11n.pt"
    values["SENTINEL_DATA_DIR"] = str(data)
    values["SENTINEL_YOLO_MODEL"] = installed_model_setting(values.get("SENTINEL_YOLO_MODEL", ""), model)
    dest.write_text(render_env(values), encoding="utf-8")
    if action == "copied" and chosen is not None and chosen.name != "env.example":
        retire_secret_source(chosen)
    if flat.is_file() and flat.resolve() != dest.resolve() and "SENTINEL_" in flat.read_text(encoding="utf-8"):
        retire_secret_source(flat)

    venv_created = not venv_python.exists()
    if venv_created:
        runner([str(base_python), "-m", "venv", str(venv_dir)])
    torch_file = root / "requirements-torch-cpu.txt"
    requirements = root / "requirements-windows.txt"
    stamp = data / "install-stamp.txt"
    text = stamp_material(
        requirements.read_text(encoding="utf-8"),
        torch_file.read_text(encoding="utf-8"),
        package_digest(root),
    )
    done: list[str] = []
    if venv_created or pip_needed(stamp, text, venv_python):
        runner([str(venv_python), "-m", "pip", "install", "-U", "pip"])
        for command in pip_commands(venv_python, torch_file, requirements):
            if command[3:5] == ["install", "-U"]:
                continue
            runner(command)
        runner([str(venv_python), "-m", "pip", "install", str(root)])
        done.append("pip")
        stamp.write_text(requirements_digest(text), encoding="utf-8")
    if not model.exists() or model.stat().st_size <= 0:
        runner([
            str(venv_python), "-c",
            "from ultralytics import YOLO; YOLO(%r)" % str(model),
        ])
        done.append("model")
    xml_path = data / "SentinelEdge.xml"
    xml_path.write_text(render_task_xml(venv_python, dest, venv_dir), encoding="utf-16")
    runner(schtasks_create_argv(xml_path))
    for command in acl_commands(data):
        runner(command)
    done.append("task")
    return done


def main(argv: list[str] | None = None) -> int:
    import subprocess
    parser = argparse.ArgumentParser(description="Install Sentinel Edge on Windows")
    parser.add_argument("command", choices=["install", "status", "stop", "uninstall"])
    parser.add_argument("--root", default=".")
    parser.add_argument("--purge", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if sys.platform != "win32":
        print("Task Scheduler install runs on Windows.")
        return 2
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    data = program_data / "SentinelEdge"
    base_python = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Python312" / "python.exe"

    def runner(command: list[str]) -> None:
        subprocess.run(command, check=True)

    if args.command == "install":
        package = resolve_package_root(root)
        gate = package / "Assert-TrustedRoot.ps1"
        if not gate.is_file():
            gate = package / "packaging" / "Assert-TrustedRoot.ps1"
        checked = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(gate), "-Root", str(package)],
            check=False,
        )
        if checked.returncode != 0:
            return checked.returncode or 1
        apply_install(package, data, runner, base_python)
        runner(schtasks_run_argv())
        return 0
    if args.command == "status":
        runner(schtasks_query_argv())
        return 0
    if args.command == "stop":
        runner(schtasks_end_argv())
        return 0
    if args.command == "uninstall":
        runner(schtasks_end_argv())
        runner(schtasks_delete_argv())
        if args.purge and data.exists():
            import shutil
            shutil.rmtree(data)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
