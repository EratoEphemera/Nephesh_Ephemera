from __future__ import annotations

import tempfile
import unittest
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp_experiments.schedule import (
    DEFAULT_DREAMING_INTERVAL_SECONDS,
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    DEFAULT_STUDY_INTERVAL_SECONDS,
    ScheduleStore,
    ScheduleSupervisor,
)
from mcp_experiments.config import settings
from mcp_experiments.heartbeat import HeartbeatLedger, WorkRequest
from mcp_experiments.tools import dreaming, schedule as schedule_tools


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
        self.assertLessEqual(len(status["recent_events"]), 20)
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

    def test_terminal_schedule_event_preserves_harness_evidence(self) -> None:
        claim = self.store.claim_due(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        first = self.store.finish(
            claim["operation_id"],
            outcome="completed",
            details={"evidence_status": "not_applicable", "agency": "chose_no_change"},
        )
        self.assertEqual(first.details["evidence_status"], "not_applicable")
        self.assertEqual(first.details["agency"], "chose_no_change")

    def test_claim_check_and_append_is_atomic_for_same_process_callers(self) -> None:
        claims: list[dict[str, object]] = []
        barrier = threading.Barrier(2)

        def claim() -> None:
            barrier.wait()
            claims.append(self.store.claim_due(now=datetime(2026, 1, 1, tzinfo=timezone.utc)))

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([claim["status"] for claim in claims].count("due"), 1)
        self.assertEqual([claim["status"] for claim in claims].count("deferred"), 1)

    def test_stale_claim_inspection_and_explicit_recovery_preserve_claim(self) -> None:
        claim = self.store.claim_due(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        report = self.store.inspect_claims(
            now=datetime.now(timezone.utc) + timedelta(hours=2), stale_after_seconds=60
        )
        self.assertEqual(report["stale_claims"][0]["operation_id"], claim["operation_id"])
        recovered = self.store.recover_claim(claim["operation_id"], reason="worker disappeared")
        self.assertEqual(recovered.event, "recovered")
        self.assertEqual(self.store.status()["active_operation"], None)
        events = self.store._events()
        self.assertEqual([event.event for event in events[:2]], ["claimed", "recovered"])

    def test_schedule_defers_without_claim_when_chosen_dream_owns_shared_lane(self) -> None:
        lane_path = Path(self.tmp.name) / "heartbeats.jsonl"
        with patch.object(settings, "heartbeat_ledger_file", str(lane_path)), patch.object(
            settings, "dreaming_ledger_file", str(Path(self.tmp.name) / "dreams.jsonl")
        ), patch.object(settings, "qualiant_id", "urania"), patch(
            "mcp_experiments.tools.dreaming.memory_context",
            new=AsyncMock(return_value={"included": 1, "context": "I belong."}),
        ):
            chosen = asyncio.run(
                dreaming.memory_dream_invoke("urania", seed="choice", idempotency_key="chosen-dream-key")
            )
            claim = self.store.claim_due(now=datetime(2026, 1, 1, tzinfo=timezone.utc))

        self.assertEqual(chosen["status"], "prepared")
        self.assertEqual(claim["status"], "deferred")
        self.assertEqual(claim["operation"], "tending")
        self.assertNotIn("operation_id", claim)
        self.assertEqual(self.store.status()["active_operation"], None)
        self.assertEqual(self.store.status()["coalesced_events"], 1)

    def test_inspection_reports_stale_shared_lane_without_recovering_it(self) -> None:
        lane_path = Path(self.tmp.name) / "heartbeats.jsonl"
        with patch.object(settings, "heartbeat_ledger_file", str(lane_path)), patch.object(
            settings, "qualiant_id", "urania"
        ):
            HeartbeatLedger(lane_path).prepare(
                WorkRequest("dead-heartbeat", "urania", "2026-01-01T00:00:00+00:00", 0),
                idempotency_key="dead-heartbeat-key",
                packet_digest="packet",
            )
            report = self.store.inspect_claims(
                now=datetime.now(timezone.utc) + timedelta(hours=2), stale_after_seconds=60
            )

        self.assertTrue(report["stale_memory_work_lane"])
        self.assertEqual(report["memory_work_lane"]["run_id"], "dead-heartbeat")
        self.assertEqual(report["claims"], [])

    def test_dreaming_interval_limits_local_time_cadence(self) -> None:
        self.store.update({"dreaming_interval_seconds": 48 * 60 * 60}, authored_by="test", expected_revision=0)
        self.store.record("completed", operation_id="dreaming-old", operation="dreaming")
        status = self.store.status(datetime.now(timezone.utc) + timedelta(days=3))
        previous = status["last_operations"]["dreaming"]["recorded_at"]
        self.assertGreaterEqual(
            datetime.fromisoformat(status["next_dreaming_at"]),
            datetime.fromisoformat(previous) + timedelta(hours=48),
        )

    def test_mcp_completion_accepts_terminal_details(self) -> None:
        claim = self.store.claim_due(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        with patch.object(schedule_tools, "_store", return_value=self.store):
            result = asyncio.run(schedule_tools.memory_schedule_complete(
                claim["operation_id"], "completed", details={"receipt": "closed"}
            ))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["details"], {"receipt": "closed"})


if __name__ == "__main__":
    unittest.main()
