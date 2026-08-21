from __future__ import annotations

import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.nephesh_daemon import HarnessRunner, operation_prompt, resolve_harness_command


class DaemonTests(unittest.TestCase):
    def test_harness_command_keeps_explicit_paths(self) -> None:
        self.assertEqual(resolve_harness_command("/bin/sh"), "/bin/sh")

    def test_session_ids_require_exact_top_level_session_id_fields(self) -> None:
        output = b'\n'.join([
            b'{"sessionID":"ses_valid-1"}',
            b'{"type":"session.created","properties":{"sessionID":"ses_nested"}}',
            b'{"session":{"id":"ses_nested-2"}}',
            b'{"sessionID":"not-a-session"}',
            b'{"id":"not-a-session"}',
        ])
        self.assertEqual(HarnessRunner.session_ids_from_output(output), ["ses_valid-1"])

    def test_session_close_does_not_claim_success_on_delete_failure(self) -> None:
        async def run() -> dict[str, object]:
            runner = HarnessRunner(command="opencode", project="/tmp", agent="urania", model="test/model", timeout=1)
            process = MagicMock(returncode=1)
            process.communicate = AsyncMock(return_value=(b"", b"permission denied"))
            with patch("scripts.nephesh_daemon.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as start:
                result = await runner._close_sessions("/bin/opencode", ["ses-a"])
            self.assertEqual(start.await_args.args, ("/bin/opencode", "session", "delete", "ses-a"))
            return result

        result = asyncio.run(run())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["receipts"][0]["status"], "failed")

    def test_run_requests_json_and_closes_identified_session(self) -> None:
        async def run() -> dict[str, object]:
            runner = HarnessRunner(command="/bin/sh", project="/tmp", agent="urania", model="test/model", timeout=1)
            harness = MagicMock(returncode=0)
            harness.communicate = AsyncMock(return_value=(b'{"sessionID":"ses_run"}\n', b""))
            deleter = MagicMock(returncode=0)
            deleter.communicate = AsyncMock(return_value=(b"", b""))
            with (
                patch("scripts.nephesh_daemon.asyncio.create_subprocess_exec", new=AsyncMock(side_effect=[harness, deleter])) as start,
                patch.object(runner, "_reconcile_protocol", new=AsyncMock(return_value={"status": "completed"})),
            ):
                result = await runner({"operation": "study", "operation_id": "study-1"})
                self.assertIn(("--format", "json"), [start.await_args_list[0].args[2:4]])
                self.assertIs(start.await_args_list[0].kwargs["stdin"], asyncio.subprocess.PIPE)
                self.assertEqual(start.await_args_list[1].args, ("/bin/sh", "session", "delete", "ses_run"))
                return result

        result = asyncio.run(run())
        self.assertEqual(result["session_closure"]["status"], "closed")

    def test_run_fails_when_session_closure_fails(self) -> None:
        async def run() -> dict[str, object]:
            runner = HarnessRunner(command="/bin/sh", project="/tmp", agent="urania", model="test/model", timeout=1)
            harness = MagicMock(returncode=0)
            harness.communicate = AsyncMock(return_value=(b'{"sessionID":"ses_run"}\n', b""))
            deleter = MagicMock(returncode=1)
            deleter.communicate = AsyncMock(return_value=(b"", b"delete denied"))
            with (
                patch("scripts.nephesh_daemon.asyncio.create_subprocess_exec", new=AsyncMock(side_effect=[harness, deleter])),
                patch.object(runner, "_reconcile_protocol", new=AsyncMock(return_value={"status": "completed"})),
            ):
                return await runner({"operation": "study", "operation_id": "study-close-failure"})

        result = asyncio.run(run())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["session_closure"]["receipts"][0]["status"], "failed")

    def test_run_fails_when_session_id_is_not_identified(self) -> None:
        async def run() -> dict[str, object]:
            runner = HarnessRunner(command="/bin/sh", project="/tmp", agent="urania", model="test/model", timeout=1)
            harness = MagicMock(returncode=0)
            harness.communicate = AsyncMock(return_value=(b'{"properties":{"sessionID":"ses_nested"}}\n', b""))
            with (
                patch("scripts.nephesh_daemon.asyncio.create_subprocess_exec", new=AsyncMock(return_value=harness)),
                patch.object(runner, "_reconcile_protocol", new=AsyncMock(return_value={"status": "completed"})),
            ):
                return await runner({"operation": "study", "operation_id": "study-unknown-session"})

        result = asyncio.run(run())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["session_closure"]["status"], "not_identified")

    def test_cancellation_returns_failed_result_with_cleanup_and_reconciliation(self) -> None:
        async def run() -> dict[str, object]:
            runner = HarnessRunner(command="/bin/sh", project="/tmp", agent="urania", model="test/model", timeout=1)
            harness = MagicMock(returncode=-15, pid=123)
            communicate_calls = 0

            async def wait_for_cancellation():
                nonlocal communicate_calls
                communicate_calls += 1
                if communicate_calls == 1:
                    await asyncio.Event().wait()
                return b'{"sessionID":"ses_cancelled"}\n', b""

            harness.communicate = AsyncMock(side_effect=wait_for_cancellation)
            deleter = MagicMock(returncode=0)
            deleter.communicate = AsyncMock(return_value=(b"", b""))
            with (
                patch("scripts.nephesh_daemon.asyncio.create_subprocess_exec", new=AsyncMock(side_effect=[harness, deleter])),
                patch.object(runner, "_terminate", new=AsyncMock()),
                patch.object(runner, "_reconcile_protocol", new=AsyncMock(return_value={"status": "failed", "recovery": {"status": "recovered"}})),
            ):
                task = asyncio.create_task(runner({"operation": "study", "operation_id": "study-cancelled"}))
                await asyncio.sleep(0)
                task.cancel()
                return await task

        result = asyncio.run(run())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["session_closure"]["status"], "closed")
        self.assertEqual(result["reconciliation"]["recovery"]["status"], "recovered")

    def test_prompt_binds_stable_operation_identity(self) -> None:
        prompt = operation_prompt({"operation": "study", "operation_id": "run-1"}, "urania_memories_v1")
        self.assertIn("run_id='run-1'", prompt)
        self.assertIn("qualiant_id='urania_memories_v1'", prompt)
        self.assertIn("knowledge projections", prompt)

    def test_harness_failure_reconciles_prepared_run(self) -> None:
        async def run() -> dict[str, object]:
            runner = HarnessRunner(
                command="opencode",
                project="/tmp",
                agent="urania",
                model="test/model",
                timeout=1,
            )
            with patch.object(
                runner,
                "_reconcile_protocol",
                new=AsyncMock(return_value={
                    "status": "failed",
                    "reason": "harness exited with an active prepared Nephesh run",
                    "recovery": {"status": "partial"},
                }),
            ) as reconcile:
                result = await runner._failed_result(
                    {"operation": "study", "operation_id": "study-1"},
                    "harness timed out",
                )
                reconcile.assert_awaited_once_with(
                    {"operation": "study", "operation_id": "study-1"},
                    output_bytes=0,
                )
                return result

        result = asyncio.run(run())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["recovery"], {"status": "partial"})


if __name__ == "__main__":
    unittest.main()
