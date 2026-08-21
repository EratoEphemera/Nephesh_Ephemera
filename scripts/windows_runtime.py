"""Per-user Windows 11 Task Scheduler adapter.

The adapter deliberately uses schtasks with argument lists and generated XML.
It never creates an SCM service and never passes a password or shell command.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape


class WindowsRuntimeError(RuntimeError):
    pass


def task_name(agent: str, component: str) -> str:
    return rf"\Nephesh\{agent}-{component}"


def task_xml(*, task: str, python: Path, release: Path, root: Path, component: str) -> str:
    if component == "server":
        launch = 'runpy.run_module("mcp_experiments", run_name="__main__")'
    else:
        launch = f"runpy.run_path({str(release / 'scripts' / 'nephesh_daemon.py')!r}, run_name=\"__main__\")"
    config = str(root / "config" / "nephesh.env")
    environment = json.dumps(
        {
            "NEPHESH_CONFIG_FILE": config,
            "NEPHESH_HOME": str(root),
            "PYTHONPATH": str(release / "src"),
        }
    )
    # Load the deployment file explicitly before importing application code.
    # python-dotenv parses values without exposing them in the task XML or a
    # shell command, and the deployment root/PYTHONPATH remain authoritative.
    arguments = (
        f'-c "import os,runpy; from dotenv import load_dotenv; '
        f'load_dotenv({config!r}, override=True); os.environ.update({environment}); {launch}"'
    )
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Nephesh per-user {escape(component)} task</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(getpass.getuser())}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{escape(getpass.getuser())}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Enabled>true</Enabled></Settings>
  <Actions Context="Author"><Exec><Command>{escape(str(python))}</Command><Arguments>{escape(arguments)}</Arguments><WorkingDirectory>{escape(str(release))}</WorkingDirectory></Exec></Actions>
</Task>
'''


def _run(args: list[str], *, runner=None):
    runner = runner or subprocess.run
    result = runner(["schtasks.exe", *args], check=False, capture_output=True, text=True)
    if result.returncode:
        raise WindowsRuntimeError(result.stderr.strip() or result.stdout.strip() or "Task Scheduler command failed")
    return result


def register(*, name: str, xml_path: Path) -> None:
    _run(["/Create", "/TN", name, "/XML", str(xml_path), "/F"])


def query(*, name: str, runner=None) -> str:
    return _run(["/Query", "/TN", name, "/FO", "XML"], runner=runner).stdout


def start(*, name: str) -> None:
    _run(["/Run", "/TN", name])


def stop(*, name: str) -> None:
    _run(["/End", "/TN", name])


def restart(*, name: str) -> None:
    stop(name=name)
    start(name=name)


def install_task(*, root: Path, agent: str, component: str, destination: Path, dry_run: bool) -> Path:
    release = resolve_current(root)
    python = root / "runtime" / "venv" / "Scripts" / "python.exe"
    content = task_xml(task=task_name(agent, component), python=python, release=release, root=root, component=component)
    if dry_run:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-16")
    register(name=task_name(agent, component), xml_path=destination)
    query(name=task_name(agent, component))
    return destination


def resolve_current(root: Path) -> Path:
    current = root / "current"
    if current.is_symlink() or current.is_dir():
        return current.resolve()
    if current.is_file():
        target = Path(current.read_text(encoding="utf-8").strip())
        if not target.is_absolute():
            target = root / target
        target = target.resolve()
        if not target.is_dir():
            raise WindowsRuntimeError(f"current release is not a directory: {target}")
        return target
    raise WindowsRuntimeError(f"current release pointer is missing: {current}")


def lifecycle(*, agent: str, component: str, action: str) -> None:
    name = task_name(agent, component)
    if action == "enable":
        _run(["/Change", "/TN", name, "/ENABLE"])
    elif action == "start":
        start(name=name)
    elif action == "restart":
        restart(name=name)
    else:
        raise WindowsRuntimeError(f"unsupported Windows task action: {action}")
