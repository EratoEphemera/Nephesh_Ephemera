from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.nephesh_installer as installer
from scripts import windows_runtime


class WindowsRuntimeTests(unittest.TestCase):
    def test_windows_release_selector_uses_an_atomic_pointer_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "releases" / "source-1"
            release.mkdir(parents=True)
            (root / "config").mkdir()
            (root / "config" / "nephesh.env").write_text("MCP_PORT=61080\n")
            (root / "runtime" / "venv" / "Scripts").mkdir(parents=True)
            (root / "runtime" / "venv" / "Scripts" / "python.exe").write_text("")
            with patch.object(installer.os, "name", "nt"):
                installer.switch_current(root, release, dry_run=False)
                checks = installer.verify(root, dry_run=False)
            current = root / "current"
            self.assertTrue(current.is_file())
            self.assertFalse(current.is_symlink())
            self.assertEqual(windows_runtime.resolve_current(root), release.resolve())
            self.assertTrue(checks["current_release"])

    def test_task_xml_is_per_user_and_has_no_service_or_password(self) -> None:
        root = Path(r"C:\Users\u\nephesh")
        xml = windows_runtime.task_xml(
            task=windows_runtime.task_name("Urania", "server"),
            python=Path(r"C:\Users\u\nephesh\runtime\venv\Scripts\python.exe"),
            release=Path(r"C:\Users\u\nephesh\releases\source-1"),
            root=root,
            component="server",
        )
        self.assertIn("InteractiveToken", xml)
        self.assertIn("LeastPrivilege", xml)
        self.assertIn("<UserId>", xml)
        self.assertNotIn("<Password>", xml)
        self.assertNotIn("sc.exe", xml)
        self.assertIn("<WorkingDirectory>C:\\Users\\u\\nephesh\\releases\\source-1</WorkingDirectory>", xml)

    def test_task_xml_loads_only_the_deployment_config_before_startup(self) -> None:
        root = Path(r"C:\Users\u\nephesh")
        xml = windows_runtime.task_xml(
            task=windows_runtime.task_name("Urania", "server"),
            python=Path(r"C:\Users\u\nephesh\runtime\venv\Scripts\python.exe"),
            release=Path(r"C:\Users\u\nephesh\releases\source-1"),
            root=root,
            component="server",
        )

        self.assertIn("from dotenv import load_dotenv", xml)
        self.assertIn("load_dotenv('C:\\\\Users\\\\u\\\\nephesh/config/nephesh.env', override=True)", xml)
        self.assertIn("NEPHESH_CONFIG_FILE", xml)
        self.assertIn("NEPHESH_HOME", xml)
        self.assertIn("PYTHONPATH", xml)
        self.assertNotIn("load_dotenv()", xml)
        self.assertNotIn("COMPLIANT_AUTH_TOKEN", xml)

    def test_daemon_task_uses_the_same_deployment_bootstrap(self) -> None:
        xml = windows_runtime.task_xml(
            task=windows_runtime.task_name("Urania", "daemon"),
            python=Path(r"C:\Users\u\nephesh\runtime\venv\Scripts\python.exe"),
            release=Path(r"C:\Users\u\nephesh\releases\source-1"),
            root=Path(r"C:\Users\u\nephesh"),
            component="daemon",
        )

        self.assertIn("load_dotenv(", xml)
        self.assertIn("nephesh.env", xml)
        self.assertIn("nephesh_daemon.py", xml)

    def test_task_lifecycle_uses_safe_schtasks_argument_lists(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return type("Result", (), {"returncode": 0, "stdout": "<Task />", "stderr": ""})()

        with patch.object(windows_runtime.subprocess, "run", side_effect=fake_run):
            windows_runtime.lifecycle(agent="Urania", component="server", action="enable")
            windows_runtime.lifecycle(agent="Urania", component="server", action="start")
            windows_runtime.lifecycle(agent="Urania", component="server", action="restart")

        name = r"\Nephesh\Urania-server"
        self.assertEqual(calls, [
            ["schtasks.exe", "/Change", "/TN", name, "/ENABLE"],
            ["schtasks.exe", "/Run", "/TN", name],
            ["schtasks.exe", "/End", "/TN", name],
            ["schtasks.exe", "/Run", "/TN", name],
        ])

    def test_windows_installer_dispatches_task_definitions_without_registering_in_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "releases" / "source-1"
            release.mkdir(parents=True)
            with patch.object(installer.os, "name", "nt"):
                installer.switch_current(root, release, dry_run=False)
                destination = installer.install_unit(root, agent_name="Urania", dry_run=True)
            self.assertEqual(destination, root / "state" / "tasks" / "Urania-nephesh.xml")


if __name__ == "__main__":
    unittest.main()
