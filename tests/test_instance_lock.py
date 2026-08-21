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
        import msvcrt

        release = self._acquire()
        self.addCleanup(release)

        # Open the same lock file and attempt to lock it with msvcrt.
        handle = self.lock_path.open("a+", encoding="utf-8")
        handle.write("pid=999\n")
        handle.flush()
        handle.seek(0)
        with self.assertRaises(OSError):
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        handle.close()

        # The server's _acquire_instance_lock must catch this and raise RuntimeError.
        with self.assertRaises(RuntimeError) as ctx:
            self._acquire()
        self.assertIn("already owns", str(ctx.exception))

    @unittest.skipIf(os.name == "nt", "Linux fcntl.flock BlockingIOError")
    def test_linux_flock_contention_raises_clean_error(self) -> None:
        import fcntl

        release = self._acquire()
        self.addCleanup(release)

        # Open the same lock file and attempt to lock it with fcntl.
        handle = self.lock_path.open("a+", encoding="utf-8")
        with self.assertRaises(BlockingIOError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.close()

        # The server's _acquire_instance_lock must catch BlockingIOError.
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
