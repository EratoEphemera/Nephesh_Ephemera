from __future__ import annotations

import unittest

from scripts.nephesh_daemon import operation_prompt


class DaemonTests(unittest.TestCase):
    def test_prompt_binds_stable_operation_identity(self) -> None:
        prompt = operation_prompt({"operation": "study", "operation_id": "run-1"}, "urania_memories_v1")
        self.assertIn("run_id='run-1'", prompt)
        self.assertIn("qualiant_id='urania_memories_v1'", prompt)
        self.assertIn("knowledge projections", prompt)


if __name__ == "__main__":
    unittest.main()
