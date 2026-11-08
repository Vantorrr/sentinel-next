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


def requirements_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pip_needed(stamp_path: Path, requirements_text: str, venv_python: Path) -> bool:
    if not venv_python.exists():
        return True
    if not stamp_path.exists():
        return True
    return stamp_path.read_text(encoding="utf-8").strip() != requirements_digest(requirements_text)


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
    arguments = "-m sentinel_edge.cli run --config " + quote_arg(str(config_path))
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


def acl_argv(folder: Path) -> list[str]:
    """Replace inheritance and grant only SYSTEM, Administrators, Local Service."""
    return [
        "icacls",
        str(folder),
        "/inheritance:r",
        "/grant:r",
        "NT AUTHORITY\\SYSTEM:(OI)(CI)F",
        "BUILTIN\\Administrators:(OI)(CI)F",
        "NT AUTHORITY\\LOCAL SERVICE:(OI)(CI)M",
    ]


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


def apply_install(root: Path, data: Path, runner) -> list[str]:
    """Run install steps. `runner` is subprocess.run-compatible and gets an argv list."""
    import os
    data.mkdir(parents=True, exist_ok=True)
    (data / "logs").mkdir(exist_ok=True)
    (data / "models").mkdir(exist_ok=True)
    example = (root / "packaging" / "env.example").read_text(encoding="utf-8")
    legacy = root / ".env"
    dest = data / "config.env"
    migrate_config(legacy if legacy.exists() else None, dest, example)
    values = parse_env(dest.read_text(encoding="utf-8"))
    model = data / "models" / "yolo11n.pt"
    if "SENTINEL_DATA_DIR" not in values:
        values["SENTINEL_DATA_DIR"] = str(data)
    if "SENTINEL_YOLO_MODEL" not in values:
        values["SENTINEL_YOLO_MODEL"] = str(model)
    dest.write_text(render_env(values), encoding="utf-8")

    venv_python = root / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        runner([sys.executable, "-m", "venv", str(root / ".venv")])
    torch_file = root / "requirements-torch-cpu.txt"
    requirements = root / "requirements-windows.txt"
    stamp = data / "install-stamp.txt"
    text = requirements.read_text(encoding="utf-8") + torch_file.read_text(encoding="utf-8")
    done: list[str] = []
    if pip_needed(stamp, text, venv_python):
        for command in pip_commands(venv_python, torch_file, requirements):
            runner(command)
        done.append("pip")
        stamp.write_text(requirements_digest(text), encoding="utf-8")
    if not model.exists() or model.stat().st_size <= 0:
        runner([
            str(venv_python), "-c",
            "from ultralytics import YOLO; YOLO(%r)" % str(model),
        ])
        done.append("model")
    xml_path = data / "SentinelEdge.xml"
    xml_path.write_text(render_task_xml(venv_python, dest, root), encoding="utf-16")
    runner(schtasks_create_argv(xml_path))
    runner(acl_argv(data))
    done.append("task")
    os.environ["SENTINEL_EDGE_INSTALLED"] = "1"
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

    def runner(command: list[str]) -> None:
        subprocess.run(command, check=True)

    if args.command == "install":
        apply_install(root, data, runner)
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
