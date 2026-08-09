from __future__ import annotations

import tempfile
import unittest
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp_experiments.schedule import (
    DEFAULT_DREAMING_INTERVAL_SECONDS,
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    DEFAULT_STUDY_INTERVAL_SECONDS,
    ScheduleStore,
    ScheduleSupervisor,
)


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = ScheduleStore(root / "config.jsonl", root / "events.jsonl")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_install_default_is_on_and_immediately_due(self) -> None:
        status = self.store.status(datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(status["enabled"])
        self.assertFalse(status["paused"])
        self.assertEqual(status["heartbeat_interval_seconds"], DEFAULT_HEARTBEAT_INTERVAL_SECONDS)
        self.assertEqual(status["study_interval_seconds"], DEFAULT_STUDY_INTERVAL_SECONDS)
        self.assertEqual(status["dreaming_interval_seconds"], DEFAULT_DREAMING_INTERVAL_SECONDS)
        claim = self.store.claim_due(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(claim["status"], "due")
        self.assertEqual(claim["operation"], "tending")

    def test_schedule_update_and_pause_use_revision_guards(self) -> None:
        updated = self.store.update(
            {"heartbeat_interval_seconds": 1800}, authored_by="urania", expected_revision=0
        )
        self.assertEqual(updated.revision, 1)
        with self.assertRaises(ValueError):
            self.store.update({"heartbeat_interval_seconds": 3600}, authored_by="urania", expected_revision=0)
        paused = self.store.set_paused(True, authored_by="urania", expected_revision=1)
        self.assertTrue(paused.paused)
        self.assertEqual(self.store.claim_due()["status"], "paused")

    def test_invalid_timezone_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.update({"timezone": "not/a_timezone"}, authored_by="urania", expected_revision=0)

    def test_dreaming_precedence_coalesces_due_heartbeat(self) -> None:
        # Seed both historical slots, then make both intervals due. Dreaming
        # must win even though heartbeat is shorter.
        self.store.record("completed", operation_id="tending-old", operation="tending")
        self.store.record("completed", operation_id="study-old", operation="study")
        self.store.record("completed", operation_id="dreaming-old", operation="dreaming")
        claim = self.store.claim_due(now=datetime.now(timezone.utc) + timedelta(days=2))
        self.assertEqual(claim["status"], "due")
        self.assertEqual(claim["operation"], "dreaming")
        self.assertEqual(self.store.status()["coalesced_events"], 2)

    def test_supervisor_wakes_callback_and_records_terminal_outcome(self) -> None:
        calls: list[str] = []

        async def on_due(claim: dict[str, object]) -> dict[str, object]:
            calls.append(str(claim["operation"]))
            stop.set()
            return {"status": "completed", "reason": "quiet cycle"}

        stop = asyncio.Event()
        supervisor = ScheduleSupervisor(self.store, on_due, poll_seconds=0.001)
        asyncio.run(supervisor.run(stop))
        self.assertEqual(calls, ["tending"])
        self.assertEqual(self.store.status()["active_operation"], None)

    def test_terminal_schedule_completion_is_idempotent(self) -> None:
        claim = self.store.claim_due(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        first = self.store.finish(claim["operation_id"], outcome="completed")
        second = self.store.finish(claim["operation_id"], outcome="failed")
        self.assertEqual(first.recorded_at, second.recorded_at)
        self.assertIsNone(self.store.status()["active_operation"])


if __name__ == "__main__":
    unittest.main()
