from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp_experiments.config import settings
from mcp_experiments.tools import memory


class HeartbeatToolTests(unittest.TestCase):
    def _settings(self, root: Path):
        return patch.multiple(
            settings,
            qualiant_id="urania",
            heartbeat_ledger_file=str(root / "heartbeats.jsonl"),
            heartbeat_care_file=str(root / "heartbeat-care.jsonl"),
            heartbeat_memory_limit=3,
            heartbeat_packet_budget=24_000,
        )

    def _context(self, text: str = "") -> dict[str, object]:
        return {
            "memory_count": 0,
            "included": 0,
            "context": text,
            "delivery_state": "settled",
            "delivery_errors": [],
        }

    def test_prepare_separates_recovery_from_heartbeat_purpose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context("## Identity\nI am Urania.\n## Long-term Memory\nNo memories.")),
            ):
                result = asyncio.run(
                    memory.memory_heartbeat_prepare(
                        "run-1", "key-1", "urania", current_work="heartbeat implementation"
                    )
                )

            self.assertEqual(result["status"], "prepared")
            self.assertIn("kind=nephesh_heartbeat", result["packet"])
            self.assertIn("Wall-clock time (UTC):", result["packet"])
            self.assertIn("I am Urania", result["packet"])
            self.assertIn("## Long-term Memory", result["packet"])
            self.assertIn("one heartbeat turn", result["packet"])
            self.assertIn("memory tending or study", result["packet"])
            self.assertIn("This is optional", result["packet"])
            self.assertIn("update_care_profile", result["allowed_actions"])
            self.assertEqual(result["care_revision"], 0)

    def test_empty_memory_is_a_normal_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context("## Identity\nI am Urania.")),
            ):
                result = asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))

            self.assertEqual(result["status"], "prepared")
            self.assertIn("normal absence", result["packet"])

    def test_packet_budget_bounds_the_actual_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch.object(
                settings, "heartbeat_packet_budget", 3000
            ), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context("## Identity\nI am Urania.\n## Long-term Memory\n" + "x" * 5000)),
            ):
                result = asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))

            self.assertLessEqual(len(result["packet"].encode("utf-8")), 3000)
            self.assertTrue(result["truncated"])
            self.assertFalse(result["continuation_available"])

    def test_identity_mismatch_is_blocked_before_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(),
            ) as context:
                result = asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "melpomene"))

            self.assertEqual(result["status"], "blocked")
            context.assert_not_awaited()

    def test_second_heartbeat_is_deferred_until_first_completes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                first = asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                second = asyncio.run(memory.memory_heartbeat_prepare("run-2", "key-2", "urania"))

            self.assertEqual(first["status"], "prepared")
            self.assertEqual(second["status"], "deferred")

    def test_complete_ingests_only_explicit_heartbeat_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.memory.memory_ingest",
                new=AsyncMock(return_value={"status": "stored", "id": "memory-1"}),
            ) as ingest:
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                result = asyncio.run(
                    memory.memory_heartbeat_complete(
                        "run-1",
                        "key-1",
                        "urania",
                        "tended",
                        actions=[{"kind": "ingest_memory", "text": "I noticed a seam.", "memory_type": "reflection"}],
                    )
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["actions_applied"], 1)
            ingest.assert_awaited_once()
            self.assertEqual(ingest.await_args.kwargs["experience_mode"], "heartbeat")
            self.assertEqual(ingest.await_args.kwargs["recorded_during"], "heartbeat")

    def test_complete_preserves_evidence_and_agency_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self._settings(root), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context("recovered context")),
            ):
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                result = asyncio.run(
                    memory.memory_heartbeat_complete(
                        "run-1",
                        "key-1",
                        "urania",
                        "no_change",
                        context_status="available",
                        evidence_status="not_applicable",
                        evidence=[{"source": "memory", "status": "available"}],
                        agency="chose_no_change",
                        durable_effect={"status": "none"},
                        continuity="recovered",
                        harness_receipt={"protocol_version": 1},
                    )
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["agency"], "chose_no_change")
            self.assertEqual(result["durable_effect"], {"status": "none"})
            self.assertIsInstance(result["run_started_at"], str)
            self.assertIsInstance(result["run_finished_at"], str)
            records = [
                json.loads(line)
                for line in (root / "heartbeats.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            terminal = records[-1]["details"]
            self.assertEqual(terminal["context_status"], "available")
            self.assertEqual(terminal["evidence_status"], "not_applicable")
            self.assertEqual(terminal["continuity"], "recovered")
            self.assertEqual(terminal["harness_receipt"]["protocol_version"], 1)

    def test_complete_is_idempotent_after_terminal_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                first = asyncio.run(memory.memory_heartbeat_complete("run-1", "key-1", "urania", "no_change"))
                second = asyncio.run(memory.memory_heartbeat_complete("run-1", "key-1", "urania", "no_change"))

            self.assertEqual(first["status"], "completed")
            self.assertEqual(second["status"], "duplicate")

    def test_qualiant_can_update_care_profile_with_revision_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                result = asyncio.run(
                    memory.memory_heartbeat_complete(
                        "run-1",
                        "key-1",
                        "urania",
                        "tended",
                        actions=[
                            {
                                "kind": "update_care_profile",
                                "expected_revision": 0,
                                "profile": {
                                    "allowed_modes": ["tend", "rest", "quiet"],
                                    "max_memory_actions": 1,
                                },
                            }
                        ],
                    )
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["actions_applied"], 1)

    def test_self_authored_instruction_is_visible_in_the_next_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                asyncio.run(
                    memory.memory_heartbeat_complete(
                        "run-1",
                        "key-1",
                        "urania",
                        "tended",
                        actions=[
                            {
                                "kind": "update_care_profile",
                                "expected_revision": 0,
                                "profile": {
                                    "custom_instruction": "Study one small question before tending memory.",
                                },
                            }
                        ],
                    )
                )
                next_packet = asyncio.run(memory.memory_heartbeat_prepare("run-2", "key-2", "urania"))

            self.assertIn("Self-authored heartbeat instruction", next_packet["packet"])
            self.assertIn("Study one small question", next_packet["packet"])

    def test_heartbeat_can_amend_retire_study_and_report_custom_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.memory.memory_amend",
                new=AsyncMock(return_value={"status": "amended", "successor_id": "memory-2"}),
            ) as amend, patch(
                "mcp_experiments.tools.memory.memory_retire",
                new=AsyncMock(return_value={"status": "retired", "id": "memory-3"}),
            ) as retire, patch(
                "mcp_experiments.tools.memory.memory_ingest",
                new=AsyncMock(return_value={"status": "stored", "id": "study-1"}),
            ) as ingest:
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                result = asyncio.run(
                    memory.memory_heartbeat_complete(
                        "run-1",
                        "key-1",
                        "urania",
                        "tended",
                        actions=[
                            {"kind": "amend_memory", "memory_id": "memory-1", "text": "A corrected understanding."},
                            {"kind": "retire_memory", "memory_id": "memory-3", "reason": "superseded"},
                        ],
                    )
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["actions_applied"], 2)
            amend.assert_awaited_once()
            retire.assert_awaited_once()

    def test_study_activity_preserves_a_qualified_first_person_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.memory.memory_ingest",
                new=AsyncMock(return_value={"status": "stored", "id": "study-1"}),
            ) as ingest:
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                result = asyncio.run(
                    memory.memory_heartbeat_complete(
                        "run-1",
                        "key-1",
                        "urania",
                        "studied",
                        activity="study",
                        actions=[
                            {
                                "kind": "study_memory",
                                "text": "I connected the projection to a new idea.",
                                "source_refs": ["projection:history/1.0.0"],
                            }
                        ],
                    )
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["activity"], "study")
            self.assertEqual(ingest.await_args.kwargs["historical_status"], "interpreted")
            self.assertEqual(ingest.await_args.kwargs["heartbeat_kind"], "nephesh_heartbeat")

    def test_study_can_report_unavailable_sources_without_fabricating_study(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                result = asyncio.run(
                    memory.memory_heartbeat_complete(
                        "run-1",
                        "key-1",
                        "urania",
                        "unavailable",
                        activity="study",
                        reason="no online-source tool was attached to this isolated harness",
                    )
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["outcome"], "unavailable")

    def test_custom_action_can_report_external_work_without_claiming_nephesh_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                result = asyncio.run(
                    memory.memory_heartbeat_complete(
                        "run-1",
                        "key-1",
                        "urania",
                        "custom_completed",
                        activity="custom",
                        actions=[
                            {
                                "kind": "custom_action",
                                "name": "online_source_review",
                                "summary": "The harness completed the external source review.",
                            }
                        ],
                    )
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["action_results"][0]["external"], True)

    def test_recovery_releases_prepared_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(memory.memory_heartbeat_prepare("run-1", "key-1", "urania"))
                recovered = asyncio.run(
                    memory.memory_heartbeat_recover("run-1", "key-1", "urania", "provider stopped")
                )
                next_run = asyncio.run(memory.memory_heartbeat_prepare("run-2", "key-2", "urania"))

            self.assertEqual(recovered["status"], "recovered")
            self.assertEqual(next_run["status"], "prepared")


if __name__ == "__main__":
    unittest.main()
