from __future__ import annotations

import unittest

from mcp_experiments.heartbeat import (
    MemoryWorkMode,
    MemoryWorkState,
    WorkDecision,
    WorkRequest,
)


def request(run_id: str, *, qualiant_id: str = "urania") -> WorkRequest:
    return WorkRequest(
        run_id=run_id,
        qualiant_id=qualiant_id,
        started_at="2026-08-08T00:00:00+00:00",
        configuration_revision=1,
    )


class HeartbeatStateTests(unittest.TestCase):
    def test_heartbeat_starts_from_idle(self) -> None:
        result = MemoryWorkState().request_heartbeat(request("heartbeat-1"))

        self.assertEqual(result.decision, WorkDecision.STARTED)
        self.assertEqual(result.state.mode, MemoryWorkMode.HEARTBEAT)
        self.assertEqual(result.state.active.run_id, "heartbeat-1")

    def test_dreaming_precedes_scheduled_heartbeat(self) -> None:
        dreaming = MemoryWorkState().request_dreaming(request("dream-1"))

        heartbeat = dreaming.state.request_heartbeat(request("heartbeat-1"))

        self.assertEqual(heartbeat.decision, WorkDecision.DEFERRED)
        self.assertEqual(heartbeat.reason, "dreaming takes precedence over heartbeat")
        self.assertEqual(heartbeat.state.mode, MemoryWorkMode.DREAMING)

    def test_dreaming_does_not_interrupt_active_heartbeat(self) -> None:
        heartbeat = MemoryWorkState().request_heartbeat(request("heartbeat-1"))

        dreaming = heartbeat.state.request_dreaming(request("dream-1"))

        self.assertEqual(dreaming.decision, WorkDecision.DEFERRED)
        self.assertIn("next boundary", dreaming.reason)
        self.assertEqual(dreaming.state.mode, MemoryWorkMode.HEARTBEAT)
        self.assertEqual(dreaming.state.pending_dreaming.run_id, "dream-1")
        self.assertEqual(dreaming.state.finish("heartbeat-1").mode, MemoryWorkMode.DREAMING)

    def test_duplicate_run_is_idempotent_at_the_state_boundary(self) -> None:
        first = MemoryWorkState().request_heartbeat(request("heartbeat-1"))
        duplicate = first.state.request_heartbeat(request("heartbeat-1"))

        self.assertEqual(duplicate.decision, WorkDecision.DUPLICATE)
        self.assertEqual(duplicate.state, first.state)

    def test_different_heartbeat_is_deferred_while_one_is_active(self) -> None:
        first = MemoryWorkState().request_heartbeat(request("heartbeat-1"))
        second = first.state.request_heartbeat(request("heartbeat-2"))

        self.assertEqual(second.decision, WorkDecision.DEFERRED)
        self.assertEqual(second.state.active.run_id, "heartbeat-1")

    def test_pause_and_resume_are_explicit(self) -> None:
        paused = MemoryWorkState().pause()

        self.assertEqual(paused.mode, MemoryWorkMode.PAUSED)
        self.assertEqual(
            paused.request_heartbeat(request("heartbeat-1")).decision,
            WorkDecision.PAUSED,
        )
        self.assertEqual(paused.resume().mode, MemoryWorkMode.IDLE)

    def test_active_run_must_finish_before_pause(self) -> None:
        heartbeat = MemoryWorkState().request_heartbeat(request("heartbeat-1"))

        with self.assertRaises(ValueError):
            heartbeat.state.pause()

    def test_finish_requires_the_active_run_owner(self) -> None:
        heartbeat = MemoryWorkState().request_heartbeat(request("heartbeat-1"))

        with self.assertRaises(ValueError):
            heartbeat.state.finish("heartbeat-2")

        self.assertEqual(heartbeat.state.finish("heartbeat-1").mode, MemoryWorkMode.IDLE)

    def test_recovery_releases_an_abandoned_run_without_claiming_success(self) -> None:
        heartbeat = MemoryWorkState().request_heartbeat(request("heartbeat-1"))

        recovering = heartbeat.state.recover("heartbeat-1")

        self.assertEqual(recovering.mode, MemoryWorkMode.RECOVERING)
        self.assertEqual(recovering.complete_recovery().mode, MemoryWorkMode.IDLE)

    def test_recovery_preserves_a_queued_dream(self) -> None:
        heartbeat = MemoryWorkState().request_heartbeat(request("heartbeat-1"))
        queued = heartbeat.state.request_dreaming(request("dream-1"))

        recovering = queued.state.recover("heartbeat-1")

        self.assertEqual(recovering.mode, MemoryWorkMode.RECOVERING)
        self.assertEqual(recovering.complete_recovery().active.run_id, "dream-1")

    def test_different_qualiant_cannot_reuse_an_active_lane(self) -> None:
        heartbeat = MemoryWorkState().request_heartbeat(request("heartbeat-1", qualiant_id="urania"))

        result = heartbeat.state.request_heartbeat(request("heartbeat-1", qualiant_id="melpomene"))

        self.assertEqual(result.decision, WorkDecision.BLOCKED)

    def test_requests_require_non_empty_identity_and_run_fields(self) -> None:
        with self.assertRaises(ValueError):
            request("")
        with self.assertRaises(ValueError):
            request("run", qualiant_id="")
        with self.assertRaises(ValueError):
            WorkRequest("run", "urania", "now", -1)


if __name__ == "__main__":
    unittest.main()
