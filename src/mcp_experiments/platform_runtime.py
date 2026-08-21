"""Small operating-system adapters used by the server and scheduler."""

from __future__ import annotations

import contextlib
import asyncio
import os
import subprocess
from pathlib import Path
from typing import Iterator


@contextlib.contextmanager
def exclusive_file_lock(path: str | Path) -> Iterator[object]:
    """Hold a deployment lock using the native advisory locking API."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt

            handle.write("0")
            handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BlockingIOError(str(exc)) from exc
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield handle
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            with contextlib.suppress(OSError):
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def process_spawn_kwargs(*, console: bool = False) -> dict[str, object]:
    """Return process setup supported by the current OS.

    OpenCode's Windows CLI opens ``CONIN$`` even for non-interactive ``run``
    calls. A daemon child therefore needs a hidden console allocation rather
    than a pipe-only process.
    """
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        startupinfo = None
        if console:
            flags |= getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
            startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
            if startupinfo_type is not None:
                startupinfo = startupinfo_type()
                startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
                startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        result: dict[str, object] = {"creationflags": flags}
        if startupinfo is not None:
            result["startupinfo"] = startupinfo
        return result
    return {"start_new_session": True}


async def terminate_process(process, *, timeout: float = 10.0) -> None:
    """Terminate a child and its descendants without assuming POSIX signals."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
    else:
        import signal

        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except Exception:
        if os.name != "nt":
            import signal

            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
            )
        await asyncio.wait_for(process.wait(), timeout=timeout)
