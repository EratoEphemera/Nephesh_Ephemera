from __future__ import annotations

"""Regression rites for recall time filtering.

The bug: time_start/time_end values that parsed to None (date-only, naive,
or garbage strings) were silently dropped, so the filter never applied and
the caller received an unfiltered stream while believing it was
time-bounded.  The fix refuses such values loudly.  These rites pin both
halves: loud refusal of tz-less bounds, and honest filtering for
timezone-aware bounds.
"""

import asyncio
import json
import unittest
from unittest.mock import patch

from mcp_experiments.tools import memory


def _row(row_id: str, event_time_iso: str) -> dict:
    return {
        "id": row_id,
        "text": "memory under test",
        "metadata_json": json.dumps({"type": "decision", "event_time": event_time_iso}),
        # Keep base similarity below the reinforcement threshold so the
        # fake repository never needs salience-mutation machinery.
        "_distance": 0.9,
    }


class _FakeEmbedder:
    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 0.0]


class _FakeRepository:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.embedder_instance = _FakeEmbedder()

    def embedder(self) -> _FakeEmbedder:
        return self.embedder_instance

    def collection(self, name: str) -> str:
        return name

    def collection_exists(self, name: str) -> bool:
        return True

    def nearest(self, table: str, vector: list[float], k: int) -> list[dict]:
        return self._rows[:k]


class RecallTimeFilterTests(unittest.TestCase):
    def _recall(self, **kwargs) -> dict:
        return asyncio.run(memory.memory_recall("query", n_results=5, **kwargs))

    def test_timezone_aware_bounds_filter_honestly(self) -> None:
        rows = [
            _row("kept", "2026-08-25T10:00:00+00:00"),
            _row("excluded-old", "2026-08-20T10:00:00+00:00"),
            _row("excluded-new", "2026-08-30T10:00:00+00:00"),
        ]
        with patch.object(memory, "repository", _FakeRepository(rows)):
            result = self._recall(
                time_start="2026-08-23T00:00:00+00:00",
                time_end="2026-08-29T00:00:00+00:00",
            )
        ids = [hit["id"] for hit in result["results"]]
        self.assertEqual(ids, ["kept"])

    def test_date_only_bounds_are_refused_loudly(self) -> None:
        with patch.object(memory, "repository", _FakeRepository([])):
            result = self._recall(time_start="2026-08-23")
        self.assertIn("error", result)
        self.assertIn("expected an ISO 8601", result["error"])

    def test_garbage_bounds_are_refused_loudly(self) -> None:
        with patch.object(memory, "repository", _FakeRepository([])):
            result = self._recall(time_end="garbage")
        self.assertIn("error", result)
        self.assertIn("expected an ISO 8601", result["error"])

    def test_naive_bounds_are_refused_loudly(self) -> None:
        with patch.object(memory, "repository", _FakeRepository([])):
            result = self._recall(
                time_start="2026-08-23 12:00:00",
                time_end="2026-08-29 12:00:00",
            )
        self.assertIn("error", result)

    def test_valid_bounds_reach_the_store(self) -> None:
        # Even an empty instance gives the honest empty-answer, never an error,
        # when the bounds are well-formed.
        with patch.object(memory, "repository", _FakeRepository([])):
            result = self._recall(time_start="2026-08-20T00:00:00+00:00")
        self.assertNotIn("error", result)
        self.assertEqual(result["results_count"], 0)


if __name__ == "__main__":
    unittest.main()
