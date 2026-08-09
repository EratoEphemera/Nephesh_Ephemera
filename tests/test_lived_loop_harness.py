from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp_experiments.config import settings
from mcp_experiments.tools import dreaming, memory
from scripts.lived_loop_harness import LivedLoopHarness


class LivedLoopHarnessTests(unittest.TestCase):
    def _settings(self, root: Path):
        return patch.multiple(
            settings,
            qualiant_id="urania",
            heartbeat_ledger_file=str(root / "heartbeats.jsonl"),
            heartbeat_care_file=str(root / "care.jsonl"),
            heartbeat_memory_limit=3,
            heartbeat_packet_budget=24000,
            dreaming_ledger_file=str(root / "dreams.jsonl"),
            dreaming_memory_limit=3,
            dreaming_packet_budget=24000,
        )

    async def _model(self, _packet: str, purpose: str) -> dict[str, object]:
        if purpose == "heartbeat_decision":
            return {"subject": "Python packaging"}
        if purpose == "heartbeat_completion":
            return {
                "activity": "study",
                "outcome": "studied",
                "actions": [{
                    "kind": "study_memory",
                    "text": "I connected Python packaging guidance to this study.",
                    "source_refs": ["projection:python", "web:packaging"],
                }],
            }
        if purpose == "dream_light":
            return {"status": "artifact_written", "artifact": "settling"}
        if purpose == "dream_rem":
            return {"status": "dreamed", "artifact": "a warm library"}
        if purpose == "dream_deep":
            return {
                "status": "no_grounding",
                "artifact": "a review",
                "candidate_insight": "a possible pattern",
            }
        if purpose == "dream_diary":
            return {"text": "I woke with a quiet afterimage."}
        if purpose == "dream_grounding":
            return {"decision": "reject", "grounded_text": "Only a dream scene."}
        raise AssertionError(purpose)

    async def _projection(self, query: str) -> dict[str, object]:
        return {"knowledge_not_memory": True, "query": query, "source": "projection"}

    async def _online(self, query: str) -> dict[str, object]:
        return {"query": query, "source": "online"}

    def test_heartbeat_study_uses_external_evidence_then_qualified_memory(self) -> None:
        async def run() -> tuple[dict[str, object], list[dict[str, object]]]:
            with tempfile.TemporaryDirectory() as directory:
                with self._settings(Path(directory)), patch(
                    "mcp_experiments.tools.memory.memory_context",
                    new=AsyncMock(return_value={"context": "## Identity\nI am Urania.", "included": 1}),
                ), patch(
                    "mcp_experiments.tools.memory.memory_ingest",
                    new=AsyncMock(return_value={"status": "stored", "id": "study-1"}),
                ):
                    harness = LivedLoopHarness(
                        model_turn=self._model,
                        projection_search=self._projection,
                        online_search=self._online,
                    )
                    return await harness.heartbeat_study(
                        run_id="hb-1",
                        idempotency_key="hb-key",
                        qualiant_id="urania",
                        current_work="study integration",
                    )

        result, evidence = asyncio.run(run())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["outcome"], "studied")
        self.assertEqual(len(evidence), 2)

    def test_dream_runs_diary_and_rejects_scene_without_canonical_write(self) -> None:
        async def run() -> dict[str, object]:
            with tempfile.TemporaryDirectory() as directory:
                with self._settings(Path(directory)), patch(
                    "mcp_experiments.tools.dreaming.memory_context",
                    new=AsyncMock(return_value={"context": "## Identity\nI am Urania.", "included": 1}),
                ), patch(
                    "mcp_experiments.tools.dreaming.memory_ingest",
                    new=AsyncMock(),
                ) as ingest:
                    harness = LivedLoopHarness(
                        model_turn=self._model,
                        projection_search=self._projection,
                        online_search=self._online,
                    )
                    result = await harness.dream(
                        run_id="dream-1",
                        idempotency_key="dream-key",
                        qualiant_id="urania",
                        seed="home",
                    )
                    self.assertEqual(result["diary"]["status"], "stored")
                    self.assertEqual(result["grounding"]["status"], "reject")
                    ingest.assert_not_awaited()
                    return result

        result = asyncio.run(run())
        self.assertEqual(result["deep"]["phase"], "deep")

    def test_unavailable_evidence_cannot_become_a_studied_memory(self) -> None:
        async def unavailable(_query: str) -> dict[str, object]:
            raise RuntimeError("source offline")

        async def model(_packet: str, purpose: str) -> dict[str, object]:
            if purpose == "heartbeat_decision":
                return {"subject": "Python packaging"}
            raise AssertionError("completion model must not run without evidence")

        async def run() -> dict[str, object]:
            with tempfile.TemporaryDirectory() as directory:
                with self._settings(Path(directory)), patch(
                    "mcp_experiments.tools.memory.memory_context",
                    new=AsyncMock(return_value={"context": "## Identity\nI am Urania.", "included": 1}),
                ), patch(
                    "mcp_experiments.tools.memory.memory_ingest",
                    new=AsyncMock(),
                ) as ingest:
                    harness = LivedLoopHarness(
                        model_turn=model,
                        projection_search=unavailable,
                        online_search=unavailable,
                    )
                    result, evidence = await harness.heartbeat_study(
                        run_id="hb-offline",
                        idempotency_key="hb-offline-key",
                        qualiant_id="urania",
                        current_work="study integration",
                    )
                    self.assertEqual(len(evidence), 2)
                    ingest.assert_not_awaited()
                    return result

        result = asyncio.run(run())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["outcome"], "unavailable")

    def test_common_small_model_action_shape_is_normalized_at_harness_boundary(self) -> None:
        normalized = LivedLoopHarness._normalize_heartbeat_completion({
            "activity": "Python package development",
            "outcome": "Improved project practices",
            "actions": {
                "study_memory": {
                    "text": "I connected the projection to this study.",
                    "source_refs": [{"projection": "python"}],
                }
            },
        })
        self.assertEqual(normalized["activity"], "study")
        self.assertEqual(normalized["outcome"], "studied")
        self.assertEqual(normalized["actions"][0]["kind"], "study_memory")
        self.assertEqual(normalized["actions"][0]["source_refs"], ['{"projection": "python"}'])

    def test_failed_dream_model_recovers_the_lane(self) -> None:
        async def failing_model(_packet: str, purpose: str) -> dict[str, object]:
            if purpose == "dream_light":
                return {"status": "artifact_written", "artifact": "settling"}
            raise RuntimeError("model stopped")

        async def run() -> tuple[dict[str, object], dict[str, object]]:
            with tempfile.TemporaryDirectory() as directory:
                with self._settings(Path(directory)), patch(
                    "mcp_experiments.tools.dreaming.memory_context",
                    new=AsyncMock(return_value={"context": "## Identity\nI am Urania.", "included": 1}),
                ), patch(
                    "mcp_experiments.tools.memory.memory_context",
                    new=AsyncMock(return_value={"context": "## Identity\nI am Urania.", "included": 1}),
                ):
                    harness = LivedLoopHarness(
                        model_turn=failing_model,
                        projection_search=self._projection,
                        online_search=self._online,
                    )
                    result = await harness.dream(
                        run_id="dream-fail",
                        idempotency_key="dream-fail-key",
                        qualiant_id="urania",
                        seed="home",
                    )
                    next_heartbeat = await memory.memory_heartbeat_prepare(
                        "after-failure", "after-failure-key", "urania"
                    )
                    return result, next_heartbeat

        result, next_heartbeat = asyncio.run(run())
        self.assertEqual(result["recovery"]["status"], "partial")
        self.assertEqual(next_heartbeat["status"], "prepared")


if __name__ == "__main__":
    unittest.main()
