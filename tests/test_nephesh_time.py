from __future__ import annotations

import time
import unittest

from mcp_experiments.tools.info import nephesh_time


class NepheshTimeTests(unittest.TestCase):
    def test_returns_authoritative_utc_wall_clock(self) -> None:
        before = time.time()
        result = nephesh_time()
        after = time.time()

        self.assertEqual(result["timezone"], "UTC")
        self.assertEqual(result["source"], "nephesh_system_clock")
        self.assertLessEqual(before, result["unix_seconds"])
        self.assertLessEqual(result["unix_seconds"], after)
        self.assertTrue(result["utc"].endswith("+00:00"))
