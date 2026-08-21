"""Always-on per-Qualiant daemon for scheduled Nephesh work.

The daemon is the external harness adapter required by the design. It owns
waking a configurable compatible harness; Nephesh remains the authority for
schedule state, identity, memory, provenance, and recovery.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import shutil
import shlex
from pathlib import Path
from typing import Any

from mcp_experiments.config import settings
from mcp_experiments.heartbeat import HeartbeatLedger
from mcp_experiments.schedule import ScheduleStore, ScheduleSupervisor
from mcp_experiments.tools import dreaming, memory
from mcp_experiments.platform_runtime import process_spawn_kwargs, terminate_process


def resolve_harness_command(command: str) -> str:
    """Resolve Windows app-managed OpenCode installs outside scheduled PATH."""
    if Path(command).is_file() or (shutil.which(command) and os.name != "nt"):
        return command
    if os.name == "nt" and command.casefold() == "opencode":
        candidates = [
            Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "opencode.exe",
            Path.home() / "AppData" / "Local" / "Programs" / "opencode" / "opencode.exe",
        ]
        packages = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        candidates.extend(sorted(packages.glob("SST.opencode*/opencode.exe")))
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    resolved = shutil.which(command)
    return resolved or command


def operation_prompt(claim: dict[str, Any], qualiant_id: str) -> str:
    operation = claim["operation"]
    run_id = claim["operation_id"]
    common = f"run_id='{run_id}', idempotency_key='{run_id}', qualiant_id='{qualiant_id}'."
    if operation == "tending":
        return f"Perform one scheduled Nephesh memory-tending heartbeat. Use {common} Call memory_heartbeat_prepare first, preserve Treat Yourself, Seams, Gaps, and Re-entry, perform only bounded authorized tending, then complete or recover. Do not invent work."
    if operation == "study":
        return f"Perform one scheduled Nephesh study heartbeat. Use {common} Call memory_heartbeat_prepare first, use installed knowledge projections and available online-source tools, preserve only a qualified first-person connection, then complete or recover honestly."
    return f"Perform one scheduled Nephesh dream. Use {common} Complete Light, REM, and Deep with the dreaming MCP tools. Optionally write a private Diary and ground only supported waking insight. Recover partial work honestly."


class HarnessRunner:
    def __init__(self, *, command: str, project: str, agent: str, model: str, timeout: float):
        self.command = command
        self.project = project
        self.agent = agent
        self.model = model
        self.timeout = timeout

    @staticmethod
    async def _terminate(process) -> None:
        await terminate_process(process)

    @staticmethod
    def session_ids_from_output(output: bytes | str) -> list[str]:
        """Find conservative, exact top-level OpenCode sessionID event fields."""
        text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else output
        found: list[str] = []
        session_id_pattern = re.compile(r"ses_[A-Za-z0-9][A-Za-z0-9_-]*\Z")

        for line in text.splitlines():
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(event, dict):
                continue
            session_id = event.get("sessionID")
            if isinstance(session_id, str) and session_id_pattern.fullmatch(session_id) and session_id not in found:
                found.append(session_id)
        return found

    async def _close_sessions(self, command: str, session_ids: list[str]) -> dict[str, Any]:
        """Delete only session IDs observed in this invocation's JSON output."""
        receipts: list[dict[str, Any]] = []
        if not session_ids:
            return {
                "status": "not_identified",
                "reason": "harness output did not identify a session ID",
                "receipts": receipts,
            }
        for session_id in session_ids:
            try:
                process = await asyncio.create_subprocess_exec(
                    command,
                    "session",
                    "delete",
                    session_id,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=262144,
                    **process_spawn_kwargs(console=os.name == "nt"),
                )
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
                except asyncio.TimeoutError:
                    await self._terminate(process)
                    receipts.append({"session_id": session_id, "status": "failed", "reason": "session deletion timed out"})
                    continue
                if process.returncode != 0:
                    receipts.append({
                        "session_id": session_id,
                        "status": "failed",
                        "returncode": process.returncode,
                        "reason": stderr.decode("utf-8", errors="replace")[-4000:] or "session deletion failed",
                    })
                else:
                    receipts.append({"session_id": session_id, "status": "closed", "output_bytes": len(stdout)})
            except (OSError, ValueError) as exc:
                receipts.append({"session_id": session_id, "status": "failed", "reason": str(exc)})
        status = "closed" if all(receipt["status"] == "closed" for receipt in receipts) else "failed"
        return {"status": status, "receipts": receipts}

    async def _failed_result(
        self, claim: dict[str, Any], reason: str, *, output_bytes: int = 0,
        session_closure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record harness failure while releasing any prepared Nephesh run."""
        reconciliation = await self._reconcile_protocol(claim, output_bytes=output_bytes)
        result = {
            "status": "failed",
            "reason": reason,
            "output_bytes": output_bytes,
            "session_closure": session_closure or {
                "status": "not_identified",
                "reason": "harness session was not identified",
                "receipts": [],
            },
        }
        result["details"] = {
            "session_closure": result["session_closure"],
            "output_bytes": output_bytes,
        }
        if "recovery" in reconciliation:
            result["recovery"] = reconciliation["recovery"]
        if reconciliation.get("reason") != reason:
            result["protocol_reconciliation"] = reconciliation
        return result

    async def _cancelled_result(self, claim: dict[str, Any], command: str, process, stdout: bytes) -> dict[str, Any]:
        """Finish cancellation cleanup while retaining its reconciliation evidence."""
        await self._terminate(process)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            stdout = b""
        closure = await self._close_sessions(command, self.session_ids_from_output(stdout))
        reconciliation = await self._reconcile_protocol(
            claim, output_bytes=len(stdout), reason="harness cancelled"
        )
        result = {
            "status": "failed",
            "reason": "harness cancelled",
            "output_bytes": len(stdout),
            "session_closure": closure,
            "reconciliation": reconciliation,
        }
        result["details"] = {
            "session_closure": closure,
            "output_bytes": len(stdout),
            "protocol_reconciliation": reconciliation,
        }
        if "recovery" in reconciliation:
            result["recovery"] = reconciliation["recovery"]
        return result

    async def __call__(self, claim: dict[str, Any]) -> dict[str, Any]:
        if claim.get("operation") == "dreaming" and settings.dreaming_consumer_command.strip():
            return await self._sdk_dream(claim)
        model = settings.dreaming_model if claim.get("operation") == "dreaming" else settings.heartbeat_model
        command = resolve_harness_command(self.command)
        if not Path(command).is_file() and shutil.which(command) is None:
            return await self._failed_result(
                claim,
                f"configured harness command is unavailable: {self.command}",
            )
        try:
            process = await asyncio.create_subprocess_exec(
                command,
                "run",
                "--format",
                "json",
                "--dir",
                self.project,
                "--model",
                model,
                "--agent",
                self.agent,
                # OpenCode's Windows CLI reads Bun.stdin even for a prompt
                # supplied as an argument. A real closed pipe yields EOF;
                # Windows NUL produces EUNKNOWN: read instead.
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=262144,
                **process_spawn_kwargs(console=os.name == "nt"),
            )
            if process.stdin is not None:
                process.stdin.write(operation_prompt(claim, settings.qualiant_id).encode("utf-8"))
                process.stdin.close()
        except (OSError, ValueError) as exc:
            return await self._failed_result(claim, f"harness process could not start: {exc}")
        stdout = b""
        timeout = (
            settings.dreaming_session_seconds
            if claim.get("operation") == "dreaming"
            else self.timeout
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            await self._terminate(process)
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                stdout = b""
            closure = await self._close_sessions(command, self.session_ids_from_output(stdout))
            return await self._failed_result(claim, "harness timed out", output_bytes=len(stdout), session_closure=closure)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(self._cancelled_result(claim, command, process, stdout))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            return cleanup.result()
        session_closure = await self._close_sessions(command, self.session_ids_from_output(stdout))
        if process.returncode != 0:
            reason = (
                stderr.decode("utf-8", errors="replace")[-4000:]
                or stdout.decode("utf-8", errors="replace")[-4000:]
                or "harness failed"
            )
            return await self._failed_result(claim, reason, output_bytes=len(stdout), session_closure=session_closure)
        result = await self._reconcile_protocol(claim, output_bytes=len(stdout))
        result["session_closure"] = session_closure
        if session_closure["status"] != "closed":
            result["status"] = "failed"
            result["reason"] = (
                f"session closure {session_closure['status']}: "
                f"{session_closure.get('reason', 'session cleanup failed')}"
            )
        result["details"] = {
            "session_closure": session_closure,
            "output_bytes": len(stdout),
            "protocol_status": result.get("status"),
        }
        return result

    async def _sdk_dream(self, claim: dict[str, Any]) -> dict[str, Any]:
        """Run a prepared dream through an OpenCode-side SDK consumer."""
        run_id = str(claim["operation_id"])
        qualiant_id = settings.qualiant_id
        prepared = await dreaming.memory_dream_prepare(
            run_id=run_id,
            idempotency_key=run_id,
            qualiant_id=qualiant_id,
            duration_seconds=settings.dreaming_session_seconds,
        )
        if prepared.get("status") != "prepared":
            return {
                "status": "failed",
                "reason": "scheduled dream could not prepare its Nephesh handoff",
                "protocol": prepared,
            }
        handoff = {
            **prepared,
            "invocation": "chosen",
            "duration_seconds": settings.dreaming_session_seconds,
            "handoff": "Continue through memory_dream_recall and the dream phase/release tools; Nephesh does not spawn the model session.",
        }
        command = shlex.split(settings.dreaming_consumer_command, posix=os.name != "nt")
        if not command:
            return await self._failed_result(claim, "dream SDK consumer command is empty")
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=262144,
                 **process_spawn_kwargs(console=os.name == "nt"),
            )
        except (OSError, ValueError) as exc:
            await dreaming.memory_dream_release(run_id, run_id, qualiant_id, "failure")
            return await self._failed_result(claim, f"dream SDK consumer could not start: {exc}")
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(handoff, sort_keys=True).encode("utf-8")),
                timeout=settings.dreaming_session_seconds + 30,
            )
        except asyncio.TimeoutError:
            await self._terminate(process)
            await dreaming.memory_dream_release(run_id, run_id, qualiant_id, "timeout")
            return await self._failed_result(claim, "dream SDK consumer timed out", output_bytes=0)
        except asyncio.CancelledError:
            await self._terminate(process)
            await dreaming.memory_dream_release(run_id, run_id, qualiant_id, "cancellation")
            raise
        output = stdout.decode("utf-8", errors="replace")
        receipt = None
        for line in reversed(output.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                receipt = candidate
                break
        receipt_valid = (
            isinstance(receipt, dict)
            and receipt.get("status") == "completed"
            and receipt.get("run_id") == run_id
            and receipt.get("qualiant_id") == qualiant_id
            and isinstance(receipt.get("session_id"), str)
            and receipt.get("session_status") == "deleted"
        )
        if process.returncode != 0 or not receipt_valid:
            await dreaming.memory_dream_release(run_id, run_id, qualiant_id, "failure")
            return await self._failed_result(
                claim,
                stderr.decode("utf-8", errors="replace")[-4000:] or "dream SDK consumer failed",
                output_bytes=len(stdout),
                session_closure=receipt or {"status": "not_identified", "reason": "SDK receipt missing", "receipts": []},
            )
        reconciliation = await self._reconcile_protocol(claim, output_bytes=len(stdout))
        reconciliation["session_closure"] = receipt
        reconciliation["details"] = {"session_closure": receipt, "output_bytes": len(stdout)}
        if reconciliation.get("status") != "completed":
            await dreaming.memory_dream_release(run_id, run_id, qualiant_id, "failure")
            reconciliation["status"] = "failed"
            reconciliation["reason"] = reconciliation.get("reason", "dream protocol did not complete")
        return reconciliation

    async def _reconcile_protocol(
        self,
        claim: dict[str, Any],
        *,
        output_bytes: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Require a terminal Nephesh protocol record before green status."""
        run_id = str(claim["operation_id"])
        operation = str(claim.get("operation"))
        ledger = HeartbeatLedger(settings.heartbeat_ledger_file)
        active = ledger.active(settings.qualiant_id)
        if active is not None and active.run_id == run_id:
            if operation == "dreaming":
                recovery = await dreaming.memory_dream_recover(
                    run_id, run_id, settings.qualiant_id, "harness exited before terminal dream phase"
                )
            else:
                recovery = await memory.memory_heartbeat_recover(
                    run_id, run_id, settings.qualiant_id, "harness exited before terminal heartbeat outcome"
                )
            return {
                "status": "failed",
                "reason": reason or "harness exited with an active prepared Nephesh run",
                "recovery": recovery,
                "output_bytes": output_bytes,
            }
        terminal = ledger.terminal(run_id)
        if terminal is None:
            return {
                "status": "failed",
                "reason": "harness exited without a terminal Nephesh protocol record",
                "output_bytes": output_bytes,
            }
        if terminal.event != "completed":
            return {
                "status": "failed",
                "reason": f"Nephesh protocol ended as {terminal.event}",
                "output_bytes": output_bytes,
            }
        return {"status": "completed", "output_bytes": output_bytes}


async def run_daemon(args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(getattr(signal, name), stop.set)
        except (NotImplementedError, RuntimeError):
            if os.name == "nt":
                sig = getattr(signal, name, None)
                if sig is not None:
                    signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    lock_path = Path(settings.daemon_lock_file)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    from mcp_experiments.platform_runtime import exclusive_file_lock
    try:
        lock_context = exclusive_file_lock(lock_path)
        lock = lock_context.__enter__()
    except BlockingIOError as exc:
        raise RuntimeError(f"another Nephesh daemon owns {lock_path}") from exc
    try:
        store = ScheduleStore(settings.schedule_config_file, settings.schedule_events_file)
        runner = HarnessRunner(
            command=settings.harness_command,
            project=args.project,
            agent=args.agent,
            model=settings.model,
            timeout=args.timeout_seconds,
        )
        await ScheduleSupervisor(store, runner, poll_seconds=args.poll_seconds).run(stop)
    finally:
        lock_context.__exit__(None, None, None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Nephesh's always-on harness daemon")
    parser.add_argument("--project", default=os.getenv("NEPHESH_HARNESS_PROJECT", str(Path.home())))
    parser.add_argument("--agent", default=os.getenv("NEPHESH_HARNESS_AGENT", "urania"))
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("NEPHESH_DAEMON_POLL_SECONDS", "30")))
    parser.add_argument("--timeout-seconds", type=float, default=float(os.getenv("NEPHESH_DAEMON_TIMEOUT_SECONDS", "1800")))
    asyncio.run(run_daemon(parser.parse_args()))


if __name__ == "__main__":
    main()
