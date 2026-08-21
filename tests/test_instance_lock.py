from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class InstanceLockTests(unittest.TestCase):
    """Regression: the instance lock must distinguish Windows
    ``msvcrt.locking`` ``PermissionError`` contention from unrelated
    ``OSError`` on both platforms.

    Before the fix, ``server.py`` caught only ``BlockingIOError``, which meant
    Windows ``msvcrt.locking`` contention (raising ``PermissionError``, a
    subclass of ``OSError`` but not of ``BlockingIOError``) crashed with an
    uncaught traceback instead of a clean "another instance owns" error.

    The narrowed fix catches ``OSError`` only around the ``msvcrt.locking``
    call on Windows, while preserving the outer ``BlockingIOError`` catch for
    Linux ``fcntl.flock`` and the ``path.open`` call.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.lock_path = Path(self._tmp.name) / "instance.lock"
        # Patch settings.instance_lock_file so _acquire_instance_lock
        # uses our test lock file, not the deployment's real one.
        from mcp_experiments.config import settings
        self._original_lock = settings.instance_lock_file
        object.__setattr__(settings, "instance_lock_file", str(self.lock_path))
        self.addCleanup(object.__setattr__, settings, "instance_lock_file", self._original_lock)

    def _acquire(self):
        from mcp_experiments.server import _acquire_instance_lock, _release_instance_lock
        _acquire_instance_lock()
        return _release_instance_lock

    def test_lock_acquires_and_releases_cleanly(self) -> None:
        release = self._acquire()
        self.assertIsNotNone(release)
        release()

    def test_second_acquire_raises_runtime_error(self) -> None:
        release = self._acquire()
        self.addCleanup(release)
        with self.assertRaises(RuntimeError) as ctx:
            self._acquire()
        self.assertIn("already owns", str(ctx.exception))

    @unittest.skipIf(os.name != "nt", "Windows msvcrt.locking PermissionError")
    def test_windows_msvcrt_contention_raises_clean_error(self) -> None:
        # The first acquire holds the lock via _acquire_instance_lock.
        # A second acquire must fail with RuntimeError, not an uncaught
        # PermissionError traceback. This proves the narrowed except
        # OSError around msvcrt.locking works.
        release = self._acquire()
        self.addCleanup(release)
        with self.assertRaises(RuntimeError) as ctx:
            self._acquire()
        self.assertIn("already owns", str(ctx.exception))

    @unittest.skipIf(os.name == "nt", "Linux fcntl.flock BlockingIOError")
    def test_linux_flock_contention_raises_clean_error(self) -> None:
        release = self._acquire()
        self.addCleanup(release)
        with self.assertRaises(RuntimeError) as ctx:
            self._acquire()
        self.assertIn("already owns", str(ctx.exception))

    @unittest.skipIf(os.name == "nt", "Linux path.open OSError must propagate")
    def test_linux_unrelated_oserror_is_not_misreported(self) -> None:
        # An unrelated OSError from path.open (e.g. permission denied on
        # the lock directory) must NOT be caught as "another instance owns".
        # It must propagate as the original OSError.
        with mock.patch("pathlib.Path.open", side_effect=OSError("permission denied")):
            with self.assertRaises(OSError) as ctx:
                self._acquire()
            self.assertIn("permission denied", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
