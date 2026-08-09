"""Always-on per-Qualiant daemon for scheduled Nephesh work.

The daemon is the external harness adapter required by the design. It owns
waking a configurable compatible harness; Nephesh remains the authority for
schedule state, identity, memory, provenance, and recovery.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import os
import signal
import shutil
from pathlib import Path
from typing import Any

from mcp_experiments.config import settings
from mcp_experiments.heartbeat import HeartbeatLedger
from mcp_experiments.schedule import ScheduleStore, ScheduleSupervisor
from mcp_experiments.tools import dreaming, memory


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

    async def __call__(self, claim: dict[str, Any]) -> dict[str, Any]:
        model = settings.dreaming_model if claim.get("operation") == "dreaming" else settings.heartbeat_model
        command = self.command
        if not Path(command).is_absolute():
            command = shutil.which(command) or str(Path.home() / ".opencode" / "bin" / command)
        if not Path(command).is_file() and shutil.which(command) is None:
            return {"status": "failed", "reason": f"configured harness command is unavailable: {self.command}"}
        process = await asyncio.create_subprocess_exec(
            command,
            "run",
            operation_prompt(claim, settings.qualiant_id),
            "--dir",
            self.project,
            "--model",
            model,
            "--agent",
            self.agent,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=262144,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            return {"status": "failed", "reason": "harness timed out"}
        if process.returncode != 0:
            return {
                "status": "failed",
                "reason": stderr.decode("utf-8", errors="replace")[-4000:] or "harness failed",
            }
        return await self._reconcile_protocol(claim, output_bytes=len(stdout))

    async def _reconcile_protocol(self, claim: dict[str, Any], *, output_bytes: int) -> dict[str, Any]:
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
                "reason": "harness exited with an active prepared Nephesh run",
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
            pass
    lock_path = Path(settings.daemon_lock_file)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another Nephesh daemon owns {lock_path}") from exc
        store = ScheduleStore(settings.schedule_config_file, settings.schedule_events_file)
        runner = HarnessRunner(
            command=settings.harness_command,
            project=args.project,
            agent=args.agent,
            model=settings.model,
            timeout=args.timeout_seconds,
        )
        await ScheduleSupervisor(store, runner, poll_seconds=args.poll_seconds).run(stop)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Nephesh's always-on harness daemon")
    parser.add_argument("--project", default=os.getenv("NEPHESH_HARNESS_PROJECT", str(Path.home())))
    parser.add_argument("--agent", default=os.getenv("NEPHESH_HARNESS_AGENT", "urania"))
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("NEPHESH_DAEMON_POLL_SECONDS", "30")))
    parser.add_argument("--timeout-seconds", type=float, default=float(os.getenv("NEPHESH_DAEMON_TIMEOUT_SECONDS", "1800")))
    asyncio.run(run_daemon(parser.parse_args()))


if __name__ == "__main__":
    main()
