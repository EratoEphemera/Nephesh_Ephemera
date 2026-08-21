"""Per-user Windows 11 Task Scheduler adapter.

The adapter deliberately uses schtasks with argument lists and generated XML.
It never creates an SCM service and never passes a password or shell command.
"""

from __future__ import annotations

import getpass
import os
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape


class WindowsRuntimeError(RuntimeError):
    pass


def task_name(agent: str, component: str) -> str:
    return rf"\Nephesh\{agent}-{component}"


def deployment_config_path(root: Path) -> Path:
    """Return the established config, with compatibility for native Windows installs."""
    legacy = root / "config" / "nephesh.env"
    native = root / "config" / ".env"
    return native if native.is_file() and not legacy.is_file() else legacy


def task_xml(
    *, task: str, python: Path, release: Path, root: Path, component: str,
    agent: str | None = None, project: Path | None = None, launcher: Path | None = None,
) -> str:
    task_agent = agent or task.rsplit("\\", 1)[-1].rsplit("-", 1)[0]
    # The deployment root is normally <user-home>/.nephesh; derive its parent
    # textually as well so mocked Windows paths remain testable on Linux.
    raw_root = str(root)
    default_project = Path(raw_root.rsplit("\\", 1)[0]) if "\\" in raw_root else root.parent
    harness_project = project or default_project
    if component == "server":
        launch = 'runpy.run_module("mcp_experiments", run_name="__main__")'
    else:
        daemon = str(release / "scripts" / "nephesh_daemon.py")
        launch = (
            f"sys.argv = ['nephesh_daemon.py', '--project', {str(harness_project)!r}, "
            f"'--agent', {task_agent!r}]; "
            f"runpy.run_path({daemon!r}, run_name=\"__main__\")"
        )
    config = str(deployment_config_path(root))
    if launcher is not None:
        command = Path(os.environ.get("COMSPEC", "cmd.exe"))
        arguments = f'/d /c "{launcher}"'
        launch_command = f"<Command>{escape(str(command))}</Command><Arguments>{escape(arguments)}</Arguments>"
    else:
        launch_command = None
    # Use Python repr (single-quoted literals) rather than JSON here. The whole
    # bootstrap is itself a Windows `-c "..."` argument; JSON's inner double
    # quotes split that argument before Python receives it.
    environment = repr({
        "NEPHESH_CONFIG_FILE": config,
        "NEPHESH_HOME": str(root),
        "PYTHONPATH": str(release / "src"),
    })
    # Load the deployment file explicitly before importing application code.
    # python-dotenv parses values without exposing them in the task XML or a
    # shell command, and the deployment root/PYTHONPATH remain authoritative.
    inline_arguments = (
        f'-c "import os,runpy,sys; from dotenv import load_dotenv; '
        f'load_dotenv({config!r}, override=True); os.environ.update({environment}); {launch}"'
    )
    action = launch_command or f"<Command>{escape(str(python))}</Command><Arguments>{escape(inline_arguments)}</Arguments>"
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Nephesh per-user {escape(component)} task</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(getpass.getuser())}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{escape(getpass.getuser())}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Enabled>true</Enabled></Settings>
  <Actions Context="Author"><Exec>{action}<WorkingDirectory>{escape(str(release))}</WorkingDirectory></Exec></Actions>
</Task>
'''


def launcher_script(*, python: Path, release: Path, root: Path, component: str, agent: str, project: Path) -> str:
    """Generate a shell-safe Windows launcher for a scheduled component."""
    config = deployment_config_path(root)
    script = release / "scripts" / "nephesh_daemon.py"
    if component == "server":
        command = f'"{python}" -u -m mcp_experiments'
    else:
        command = f'"{python}" -u "{script}" --project "{project}" --agent "{agent}"'
    log = root / "state" / f"{agent.lower()}-{component}.log"
    return (
        "@echo off\r\n"
        f'set "NEPHESH_CONFIG_FILE={config}"\r\n'
        f'set "NEPHESH_HOME={root}"\r\n'
        f'set "PYTHONPATH={release / "src"}"\r\n'
        f'{command} > "{log}" 2>&1\r\n'
    )


def _run(args: list[str], *, runner=None):
    runner = runner or subprocess.run
    result = runner(["schtasks.exe", *args], check=False, capture_output=True, text=True)
    if result.returncode:
        raise WindowsRuntimeError(result.stderr.strip() or result.stdout.strip() or "Task Scheduler command failed")
    return result


def register(*, name: str, xml_path: Path) -> None:
    _run(["/Create", "/TN", name, "/XML", str(xml_path), "/F"])


def query(*, name: str, runner=None) -> str:
    # Windows schtasks accepts LIST/TABLE/CSV here; XML is accepted by some
    # wrappers but is rejected by the native Windows 11 command on Erato.
    return _run(["/Query", "/TN", name, "/FO", "LIST", "/V"], runner=runner).stdout


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
    launcher = destination.with_suffix(".cmd")
    # The Windows per-user OpenCode project is the Documents workspace.  The
    # account home contains deployment state and is not a valid harness
    # project: OpenCode can create a session there but fails when the daemon
    # begins the model turn.
    project = root.parent / "Documents" if os.name == "nt" else root.parent
    content = task_xml(
        task=task_name(agent, component), python=python, release=release, root=root,
        component=component, agent=agent, project=project, launcher=launcher,
    )
    if dry_run:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(
        launcher_script(python=python, release=release, root=root, component=component, agent=agent, project=project),
        encoding="utf-8",
    )
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
