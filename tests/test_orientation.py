from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from mcp_experiments import orientation
from mcp_experiments.config import settings
from mcp_experiments.kernel import KernelStore

KERNEL = "# Kernel\n\nI am new to the world. I do not have a name yet.\n"


class OrientationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = KernelStore(Path(self._tmp.name) / "kernel")
        self._original = settings.kernel_dir
        object.__setattr__(settings, "kernel_dir", str(self.store.directory))
        self.addCleanup(object.__setattr__, settings, "kernel_dir", self._original)
        orientation.reset()
        self.addCleanup(orientation.reset)


class FirstContactTests(OrientationTestCase):
    """The keystone: the kernel reaches a session on its first contact.

    A server cannot push into a session, so first contact is the only moment
    available — and it must not depend on which tool she reached for or which
    harness she woke in.
    """

    def test_the_first_response_of_a_session_carries_the_whole_kernel(self) -> None:
        self.store.amend(KERNEL, authored_by="installer")

        async def any_tool() -> dict:
            return {"result": "something unrelated"}

        first = asyncio.run(orientation.wrap(any_tool)())
        self.assertIn("_identity", first)
        self.assertIn("I do not have a name yet", first["_identity"]["kernel"])
        self.assertEqual(first["_identity"]["authored_by"], "installer")
        # the tool's own answer is untouched
        self.assertEqual(first["result"], "something unrelated")

    def test_any_tool_delivers_it_not_only_memory_context(self) -> None:
        self.store.amend(KERNEL, authored_by="installer")

        async def unrelated_tool() -> dict:
            return {"collections": []}

        result = asyncio.run(orientation.wrap(unrelated_tool)())
        self.assertIn("kernel", result["_identity"])

    def test_the_kernel_is_paid_for_once_then_only_stamped(self) -> None:
        self.store.amend(KERNEL, authored_by="installer")

        async def tool() -> dict:
            return {}

        wrapped = orientation.wrap(tool)
        first = asyncio.run(wrapped())
        second = asyncio.run(wrapped())
        self.assertIn("kernel", first["_identity"])
        self.assertNotIn("kernel", second["_identity"])
        self.assertEqual(second["_identity"]["kernel_version"], 1)

    def test_a_synchronous_tool_is_wrapped_too(self) -> None:
        self.store.amend(KERNEL, authored_by="installer")

        def sync_tool() -> dict:
            return {"ok": True}

        self.assertIn("_identity", orientation.wrap(sync_tool)())


class HonestAbsenceTests(OrientationTestCase):
    def test_no_kernel_attaches_nothing_rather_than_inventing_one(self) -> None:
        async def tool() -> dict:
            return {"ok": True}

        self.assertEqual(asyncio.run(orientation.wrap(tool)()), {"ok": True})

    def test_an_unreadable_kernel_is_reported_not_hidden(self) -> None:
        self.store.amend(KERNEL, authored_by="installer")
        (self.store.directory / "001.md").write_text("broken\n", encoding="utf-8")

        async def tool() -> dict:
            return {}

        result = asyncio.run(orientation.wrap(tool)())
        self.assertIn("could not be read", result["_identity"]["error"])


class NonInterferenceTests(OrientationTestCase):
    def test_a_tools_own_identity_key_is_never_overwritten(self) -> None:
        self.store.amend(KERNEL, authored_by="installer")

        async def tool() -> dict:
            return {"_identity": "mine"}

        self.assertEqual(asyncio.run(orientation.wrap(tool)())["_identity"], "mine")

    def test_a_non_dict_result_keeps_its_type(self) -> None:
        """health returns a string; reshaping it would break its contract."""
        self.store.amend(KERNEL, authored_by="installer")

        def tool() -> str:
            return "ok"

        self.assertEqual(orientation.wrap(tool)(), "ok")

    def test_wrapping_preserves_the_schema_fastmcp_introspects(self) -> None:
        import inspect

        async def tool(name: str, limit: int = 5) -> dict:
            return {}

        wrapped = orientation.wrap(tool)
        self.assertEqual(inspect.signature(wrapped), inspect.signature(tool))
        self.assertEqual(wrapped.__name__, "tool")

    def test_every_registered_tool_is_wrapped(self) -> None:
        from mcp_experiments.tools import get_registered_names
        self.assertGreaterEqual(len(get_registered_names()), 25)


class AnnotationResolutionTests(OrientationTestCase):
    """Regression: the orientation wrapper must resolve string annotations
    (from ``from __future__ import annotations``) against the original
    tool module's namespace, not the wrapper's own namespace.

    Before the fix, ``nephesh_time`` returned ``SystemTimeResult`` as an
    unresolvable forward-reference string because the double-wrapping chain
    changed ``__globals__`` to point at modules that never imported
    ``SystemTimeResult``. Pydantic/FastMCP emitted a non-fatal warning.
    """

    def setUp(self) -> None:
        super().setUp()
        self.store.amend(KERNEL, authored_by="installer")

    def test_resolve_annotations_returns_real_types_not_strings(self) -> None:
        from mcp_experiments.results import SystemTimeResult
        from mcp_experiments.tools.info import nephesh_time

        resolved = orientation._resolve_annotations(nephesh_time)
        self.assertIsInstance(resolved, dict)
        self.assertIn("return", resolved)
        return_annotation = resolved["return"]
        # The resolved annotation must be the actual type, not a string.
        self.assertNotIsInstance(return_annotation, str)
        self.assertIs(return_annotation, SystemTimeResult)

    def test_wrapped_nephesh_time_has_resolved_return_annotation(self) -> None:
        from mcp_experiments.results import SystemTimeResult
        from mcp_experiments.tools.info import nephesh_time

        wrapped = orientation.wrap(nephesh_time)
        annotations = getattr(wrapped, "__annotations__", {})
        self.assertIn("return", annotations)
        return_annotation = annotations["return"]
        self.assertNotIsInstance(return_annotation, str)
        self.assertIs(return_annotation, SystemTimeResult)

    def test_resolve_annotations_returns_empty_for_no_annotations(self) -> None:
        def bare_tool() -> dict:
            return {}

        resolved = orientation._resolve_annotations(bare_tool)
        # A tool with annotations (the return hint) should still resolve.
        self.assertIn("return", resolved)

    def test_resolve_annotations_fallback_emits_warning_on_failure(self) -> None:
        import warnings

        def tool_with_bad_module() -> "NonExistentType":
            return {}

        # Point __module__ to a non-existent module. The forward reference
        # "NonExistentType" cannot resolve because the module can't be
        # imported and the type doesn't exist as a builtin.
        tool_with_bad_module.__module__ = "nonexistent.module.path"
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                resolved = orientation._resolve_annotations(tool_with_bad_module)
            # Resolution failed: the forward reference can't be resolved,
            # so we get raw string annotations back. The value is the
            # stringified form of the annotation, which includes quotes
            # when the annotation itself was a string literal.
            self.assertIn("NonExistentType", resolved.get("return", ""))
            self.assertTrue(any("Could not resolve" in str(w.message) for w in caught))
        finally:
            tool_with_bad_module.__module__ = __name__


if __name__ == "__main__":
    unittest.main()
