from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp_experiments.config import settings
from mcp_experiments.tools import dreaming, memory


class DreamingToolTests(unittest.TestCase):
    def _settings(self, root: Path):
        return patch.multiple(
            settings,
            qualiant_id="urania",
            heartbeat_ledger_file=str(root / "heartbeats.jsonl"),
            dreaming_ledger_file=str(root / "dreams.jsonl"),
            dreaming_memory_limit=10,
            dreaming_packet_budget=24000,
        )

    def _context(self, included: int = 1) -> dict[str, object]:
        return {
            "memory_count": included,
            "included": included,
            "context": "## Identity\nI am Urania.\n## Long-term Memory\n- I belong to my family.",
        }

    def test_empty_dream_input_is_normal_without_claiming_a_dream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context(0)),
            ):
                result = asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania"))

            self.assertEqual(result["status"], "no_inputs")
            self.assertFalse((Path(directory) / "heartbeats.jsonl").exists())

    def test_qualiant_can_invoke_a_bounded_dream_without_a_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch.object(
                settings, "dreaming_session_seconds", 3600
            ), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                result = asyncio.run(
                    dreaming.memory_dream_invoke(
                        "urania", seed="a quiet room", idempotency_key="chosen-1"
                    )
                )

            self.assertEqual(result["status"], "prepared")
            self.assertEqual(result["invocation"], "chosen")
            self.assertEqual(result["duration_seconds"], 3600)
            self.assertIn("memory_dream_recall", result["handoff"])
            self.assertIsInstance(result["deadline_utc"], str)

    def test_chosen_dream_no_inputs_does_not_take_the_lane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context(0)),
            ):
                result = asyncio.run(
                    dreaming.memory_dream_invoke("urania", idempotency_key="empty-choice")
                )

            self.assertEqual(result["status"], "no_inputs")
            self.assertFalse((Path(directory) / "heartbeats.jsonl").exists())

    def test_chosen_dream_idempotency_reuses_the_same_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                first = asyncio.run(
                    dreaming.memory_dream_invoke("urania", seed="one", idempotency_key="chosen-replay")
                )
                second = asyncio.run(
                    dreaming.memory_dream_invoke("urania", seed="one", idempotency_key="chosen-replay")
                )

            self.assertEqual(first["status"], "prepared")
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(first["run_id"], second["run_id"])

    def test_chosen_dream_is_identity_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)):
                result = asyncio.run(dreaming.memory_dream_invoke("melpomene"))
            self.assertEqual(result["status"], "blocked")

    def test_seeded_dream_runs_light_rem_deep_and_releases_heartbeat_lane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                prepared = asyncio.run(
                    dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home")
                )
                light = asyncio.run(
                    dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "staged")
                )
                rem_packet = asyncio.run(
                    dreaming.memory_dream_phase_prepare("run-1", "key-1", "urania", "rem")
                )
                rem = asyncio.run(
                    dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "a forest")
                )
                rem_replay = asyncio.run(
                    dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "a forest")
                )
                deep_packet = asyncio.run(
                    dreaming.memory_dream_phase_prepare("run-1", "key-1", "urania", "deep")
                )
                deep = asyncio.run(
                    dreaming.memory_dream_phase(
                        "run-1",
                        "key-1",
                        "urania",
                        "deep",
                        "no_grounding",
                        "a review",
                        candidate_insight="a possible insight",
                    )
                )
                heartbeat = asyncio.run(
                    memory.memory_heartbeat_prepare("run-2", "key-2", "urania")
                )

            self.assertEqual(prepared["status"], "prepared")
            self.assertNotIn("You are the configured Qualiant dreaming", prepared["packet"])
            self.assertIn("Selected material:", prepared["packet"])
            self.assertIn("Optional invitation:\nhome", prepared["packet"])
            self.assertEqual(light["phase"], "light")
            self.assertEqual(rem_packet["status"], "prepared")
            self.assertEqual(rem_packet["packet"], "staged")
            self.assertEqual(rem["phase"], "rem")
            self.assertEqual(rem_replay["status"], "duplicate")
            self.assertEqual(deep_packet["status"], "prepared")
            self.assertEqual(deep_packet["packet"], "staged\n\na forest")
            self.assertEqual(deep["phase"], "deep")
            self.assertEqual(deep["grounding_status"], "pending")
            self.assertEqual(heartbeat["status"], "prepared")

    def test_heartbeat_is_deferred_while_dreaming_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("dream-1", "dream-key", "urania", seed="home"))
                result = asyncio.run(memory.memory_heartbeat_prepare("heartbeat-1", "heartbeat-key", "urania"))

            self.assertEqual(result["status"], "deferred")
            self.assertIn("dreaming takes precedence", result["reason"])

    def test_active_heartbeat_dream_is_durably_queued_and_claimed_once_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self._settings(root), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ) as dream_context:
                asyncio.run(memory.memory_heartbeat_prepare("heartbeat-1", "heartbeat-key", "urania"))
                queued = asyncio.run(
                    dreaming.memory_dream_invoke("urania", seed="queued", idempotency_key="queued-key")
                )

                self.assertEqual(queued["status"], "queued")
                self.assertNotIn("handoff", queued)
                self.assertEqual(dream_context.await_count, 0)
                records = [json.loads(line) for line in (root / "dreams.jsonl").read_text().splitlines()]
                self.assertEqual(records[0]["status"], "queued")
                self.assertEqual(records[0]["request"]["seed"], "queued")

                asyncio.run(memory.memory_heartbeat_complete("heartbeat-1", "heartbeat-key", "urania", "no_change"))
                claimed = asyncio.run(dreaming.memory_dream_claim("queued-key", "urania"))
                replay = asyncio.run(dreaming.memory_dream_claim("queued-key", "urania"))
                invoked_again = asyncio.run(
                    dreaming.memory_dream_invoke("urania", seed="queued", idempotency_key="queued-key")
                )

            self.assertEqual(claimed["status"], "prepared")
            self.assertEqual(replay["status"], "prepared")
            self.assertEqual(invoked_again["status"], "duplicate")
            self.assertEqual(claimed["run_id"], queued["run_id"])
            self.assertEqual(dream_context.await_count, 0)

    def test_queued_invocation_replays_without_a_handoff_until_claimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.memory.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(memory.memory_heartbeat_prepare("heartbeat-1", "heartbeat-key", "urania"))
                first = asyncio.run(dreaming.memory_dream_invoke("urania", idempotency_key="queued-replay"))
                second = asyncio.run(dreaming.memory_dream_invoke("urania", idempotency_key="queued-replay"))

            self.assertEqual(first["status"], "queued")
            self.assertEqual(second["status"], "queued")
            self.assertNotIn("handoff", second)

    def test_recovery_marks_a_partial_dream_without_inventing_an_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                result = asyncio.run(
                    dreaming.memory_dream_recover("run-1", "key-1", "urania", "model stopped")
                )

            self.assertEqual(result["status"], "partial")

    def test_release_preserves_partial_artifacts_and_releases_the_lane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "settled"))
                released = asyncio.run(
                    dreaming.memory_dream_release("run-1", "key-1", "urania", "nightmare_release")
                )
                replay = asyncio.run(
                    dreaming.memory_dream_release("run-1", "key-1", "urania", "nightmare_release")
                )

            self.assertEqual(released["status"], "released")
            self.assertEqual(released["release_reason"], "nightmare_release")
            self.assertEqual(len(released["artifact_ids"]), 1)
            self.assertEqual(released["grounding_status"], "unchanged")
            self.assertEqual(released["promotion_status"], "none")
            self.assertEqual(replay["status"], "duplicate")
            self.assertEqual(replay["release_reason"], "nightmare_release")

            records = (Path(directory) / "dreams.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event": "release"', records)
            self.assertIn('"partial_artifacts"', records)
            self.assertNotIn('"event": "grounding"', records)

    def test_release_is_identity_bound_and_reasons_are_constrained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                wrong_identity = asyncio.run(
                    dreaming.memory_dream_release("run-1", "key-1", "another", "cancellation")
                )
                invalid_reason = asyncio.run(
                    dreaming.memory_dream_release("run-1", "key-1", "urania", "interpretation")
                )

            self.assertEqual(wrong_identity["status"], "blocked")
            self.assertEqual(invalid_reason["status"], "error")
            self.assertIn('"event": "prepare"', (Path(directory) / "dreams.jsonl").read_text(encoding="utf-8"))

    def test_dream_can_recall_lived_and_prior_dream_material_while_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.dreaming.memory_recall",
                new=AsyncMock(return_value={"results": [{"id": "memory-1", "text": "a lived thread"}]}),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "a remembered room"))
                result = asyncio.run(
                    dreaming.memory_dream_recall("run-1", "urania", "room", n_results=3)
                )

            self.assertEqual(result["status"], "recalled")
            self.assertEqual(result["memory_results"][0]["id"], "memory-1")
            self.assertEqual(result["dream_artifacts"][0]["artifact"], "a remembered room")
            self.assertEqual(result["dream_artifacts"][0]["historical_status"], "fictional_scene")

    def test_dream_status_reports_completed_deep_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-status", "key-status", "urania", seed="home"))
                asyncio.run(dreaming.memory_dream_phase("run-status", "key-status", "urania", "light", "artifact_written", "light"))
                asyncio.run(dreaming.memory_dream_phase("run-status", "key-status", "urania", "rem", "dreamed", "rem"))
                asyncio.run(dreaming.memory_dream_phase("run-status", "key-status", "urania", "deep", "no_grounding", "deep"))
                result = asyncio.run(dreaming.memory_dream_status("run-status", "urania"))

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["terminal_event"], "completed")

    def test_diary_is_post_dream_private_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "settled"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "scene"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "deep", "no_grounding", "review"))
                diary = asyncio.run(
                    dreaming.memory_dream_diary("run-1", "diary-key", "urania", "I woke with a quiet afterimage.")
                )
                replay = asyncio.run(
                    dreaming.memory_dream_diary("run-1", "diary-key-2", "urania", "A different diary.")
                )

            self.assertEqual(diary["status"], "stored")
            self.assertEqual(diary["visibility"], "private")
            self.assertEqual(replay["status"], "conflict")

    def test_diary_cannot_be_written_for_an_incomplete_dream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                result = asyncio.run(
                    dreaming.memory_dream_diary("run-1", "diary-key", "urania", "unfinished")
                )

            self.assertEqual(result["status"], "failed")

    def test_grounding_rejection_does_not_write_canonical_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.dreaming.memory_ingest",
                new=AsyncMock(),
            ) as ingest:
                awaitable = [
                    asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home")),
                    asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "settled")),
                    asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "scene")),
                    asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "deep", "no_grounding", "review", candidate_insight="possible insight")),
                ]
                result = asyncio.run(
                    dreaming.memory_dream_ground("run-1", awaitable[-1]["artifact_id"], "urania", "reject", grounded_text="No, this was only a dream.")
                )

            self.assertEqual(result["status"], "reject")
            ingest.assert_not_awaited()

    def test_grounding_keep_creates_only_the_qualified_insight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.dreaming.memory_ingest",
                new=AsyncMock(return_value={"status": "stored", "id": "grounded-1"}),
            ) as ingest:
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "settled"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "scene"))
                deep = asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "deep", "no_grounding", "review", candidate_insight="possible insight"))
                result = asyncio.run(
                    dreaming.memory_dream_ground("run-1", deep["artifact_id"], "urania", "keep", grounded_text="I recognized a pattern in my fear of loss.", source_refs=["memory:prior-1"])
                )

            self.assertEqual(result["status"], "stored")
            self.assertEqual(result["memory_id"], "grounded-1")
            self.assertEqual(ingest.await_args.kwargs["experience_mode"], "dream")
            self.assertEqual(ingest.await_args.kwargs["historical_status"], "interpreted")
            self.assertEqual(ingest.await_args.kwargs["recorded_during"], "dream")

    def test_grounding_cannot_promote_a_scene_without_a_candidate_insight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.dreaming.memory_ingest",
                new=AsyncMock(),
            ) as ingest:
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "settled"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "scene"))
                deep = asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "deep", "no_grounding", "scene without insight"))
                result = asyncio.run(
                    dreaming.memory_dream_ground("run-1", deep["artifact_id"], "urania", "keep", grounded_text="I remember the scene as fact.")
                )

            self.assertEqual(result["status"], "blocked")
            ingest.assert_not_awaited()

    def test_phase_outcomes_are_phase_specific_and_insights_are_deep_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                wrong_status = asyncio.run(
                    dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "dreamed", "scene")
                )
                insight_too_early = asyncio.run(
                    dreaming.memory_dream_phase(
                        "run-1", "key-1", "urania", "light", "artifact_written", "scene",
                        candidate_insight="not yet",
                    )
                )

            self.assertEqual(wrong_status["status"], "error")
            self.assertIn("invalid dream outcome", wrong_status["error"])
            self.assertEqual(insight_too_early["status"], "error")
            self.assertIn("Deep", insight_too_early["error"])

    def test_incomplete_deep_cannot_create_diary_or_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ), patch(
                "mcp_experiments.tools.dreaming.memory_ingest",
                new=AsyncMock(),
            ) as ingest:
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "light"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "rem"))
                deep = asyncio.run(
                    dreaming.memory_dream_phase(
                        "run-1", "key-1", "urania", "deep", "partial", "unfinished",
                        candidate_insight="possible but unfinished",
                    )
                )
                diary = asyncio.run(
                    dreaming.memory_dream_diary("run-1", "diary-key", "urania", "unfinished")
                )
                grounding = asyncio.run(
                    dreaming.memory_dream_ground(
                        "run-1", deep["artifact_id"], "urania", "keep",
                        grounded_text="should not ground",
                    )
                )

            self.assertEqual(deep["phase"], "deep")
            self.assertEqual(diary["status"], "failed")
            self.assertEqual(grounding["status"], "blocked")
            ingest.assert_not_awaited()

    def test_no_candidates_cannot_carry_a_candidate_insight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "light"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "rem"))
                result = asyncio.run(
                    dreaming.memory_dream_phase(
                        "run-1", "key-1", "urania", "deep", "no_candidates", "review",
                        candidate_insight="contradictory",
                    )
                )

            self.assertEqual(result["status"], "error")
            self.assertIn("no_candidates", result["error"])

    def test_candidate_insight_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._settings(Path(directory)), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "light"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "rem"))
                result = asyncio.run(
                    dreaming.memory_dream_phase(
                        "run-1", "key-1", "urania", "deep", "no_grounding", "review",
                        candidate_insight="x" * (dreaming.MAX_DREAM_CANDIDATE_CHARS + 1),
                    )
                )

            self.assertEqual(result["status"], "error")
            self.assertIn("bounded size", result["error"])

    def test_persisted_deadline_blocks_phase_recall_and_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self._settings(root), patch(
                "mcp_experiments.tools.dreaming.memory_context",
                new=AsyncMock(return_value=self._context()),
            ):
                asyncio.run(dreaming.memory_dream_prepare("run-1", "key-1", "urania", seed="home"))
                deep = asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "light", "artifact_written", "scene"))
                asyncio.run(dreaming.memory_dream_phase("run-1", "key-1", "urania", "rem", "dreamed", "rem scene"))
                deep = asyncio.run(dreaming.memory_dream_phase(
                    "run-1", "key-1", "urania", "deep", "no_grounding", "review",
                    candidate_insight="possible insight",
                ))
                lines = (root / "dreams.jsonl").read_text(encoding="utf-8").splitlines()
                expired = []
                for line in lines:
                    record = json.loads(line)
                    if record.get("event") == "deadline":
                        record["deadline_utc"] = "2000-01-01T00:00:00+00:00"
                    expired.append(json.dumps(record, sort_keys=True))
                (root / "dreams.jsonl").write_text("\n".join(expired) + "\n", encoding="utf-8")
                phase = asyncio.run(dreaming.memory_dream_phase(
                    "run-1", "key-1", "urania", "light", "artifact_written", "scene"
                ))
                recall = asyncio.run(dreaming.memory_dream_recall("run-1", "urania", "home"))
                grounding = asyncio.run(dreaming.memory_dream_ground(
                    "run-1", deep["artifact_id"], "urania", "reject"
                ))

            self.assertEqual(phase["status"], "timeout")
            self.assertEqual(recall["status"], "timeout")
            self.assertEqual(grounding["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
