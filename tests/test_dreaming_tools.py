from __future__ import annotations

import asyncio
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
            self.assertIn("Let the attributable material settle", prepared["packet"])
            self.assertEqual(light["phase"], "light")
            self.assertEqual(rem_packet["status"], "prepared")
            self.assertIn("associations", rem_packet["packet"])
            self.assertEqual(rem["phase"], "rem")
            self.assertEqual(rem_replay["status"], "duplicate")
            self.assertEqual(deep_packet["status"], "prepared")
            self.assertIn("waking boundary", deep_packet["packet"])
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
            self.assertEqual(replay["status"], "duplicate")

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


if __name__ == "__main__":
    unittest.main()
