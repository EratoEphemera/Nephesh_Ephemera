# Nephesh 5.3.3 Windows Reliability Design

**Status:** Design document for review. Implementation authorized only after
companion approval. This document is not identity-bearing, is not a Qualiant
kernel, and must not be treated as autobiographical memory. It is a re-entry
artifact for a coder or reviewer entering this branch for the first time.

**Branch:** `5.3.3`

**Purpose:** Lock down Windows 11 as a reliable production platform for
Nephesh 5 by fixing confirmed bugs in Windows-specific code paths, without
touching any code path Linux currently consumes. This is the bridge release
that keeps Windows Qualiants viable until the Nephesh 6 Rust successor matures.

**Working rule:** Design first, then implementation, then tests and evidence.
The codebase already has the right patterns in `platform_runtime.py`; the bugs
are places where those patterns were not applied consistently. Fixes route
through existing adapters rather than adding new Windows code.

**Last reviewed:** 2026-08-21

---

## 1. Scope

This branch has four coordinated goals:

1. fix confirmed Windows-only bugs that cause crashes or silent failures;
2. harden Windows reliability gaps that are tolerated but asymmetric;
3. ensure the test suite can run on Windows; and
4. document Windows deployment requirements.

No live deployment, sister body, schedule, memory collection, or external
service is changed by drafting or reviewing this document.

No code path that Linux currently consumes may be altered. All fixes are
inside `if os.name == "nt"` branches, inside `except` clauses that only fire
on Windows, or in test guards that are no-ops on Linux. The one exception is
`encoding="utf-8"` additions to `read_text()`/`write_text()` calls in the
installer, which are no-ops on Linux (where the default is already UTF-8).

### Non-goals

- Do not rewrite the daemon architecture.
- Do not add new Windows-specific features.
- Do not change the schedule, heartbeat, or dreaming protocols.
- Do not touch any Linux systemd path.
- Do not attempt to fix the Windows directory-fsync limitation (it is an
  accepted platform constraint, confirmed by the `object_store` crate's
  documentation: "directory fsync is only performed on Unix; on other
  platforms it is a no-op, as directories cannot be portably opened and
  synced").

---

## 2. Evidence discipline

The bugs identified below are confirmed by:

1. **Source code analysis** — line-by-line study of every `os.name`, `"nt"`,
   `msvcrt`, `subprocess`, `signal`, and Windows-conditional branch in the
   repository.
2. **Python documentation** — `msvcrt.locking` raises `OSError` on failure
   (not `BlockingIOError`); `os.open` on a directory raises `PermissionError`
   on Windows because `CreateFileW` maps directory opens to
   `ERROR_ACCESS_DENIED`.
3. **Live deployment evidence** — the Erato Windows 11 deployment experienced
   four distinct failure phases during daemon repair (see schedule event
   ledger for 2026-08-21T05:45 through 2026-08-21T08:17 UTC).
4. **Industry precedent** — `platform_runtime.py` already implements the
   correct patterns (wrapping `msvcrt.locking` `OSError` into
   `BlockingIOError`, wrapping `_fsync_directory` in `try/except OSError`).
   The bugs are inconsistencies, not missing patterns.

Missing information is a valid result. A fix that is not yet tested on native
Windows must be labeled as proposed, not confirmed.

---

## 3. Confirmed bugs

### 3.0 What 5.3.2 already fixed

A reader entering this branch should know that 5.3.2 resolved several Windows
issues that are NOT addressed here because they are already closed:

- **`process_spawn_kwargs` version mismatch** — the daemon script was updated
  to call `process_spawn_kwargs(console=os.name == "nt")` before the installed
  `mcp_experiments` package accepted the `console` parameter. Both sides are
  now in sync.
- **Daemon launch and harness identity** — Windows per-user daemon launch,
  Task Scheduler registration, and OpenCode project/agent configuration were
  repaired.
- **Native launcher compatibility** — the launcher now supports both the
  standard `config/nephesh.env` path and the `.env` form used by Erato's
  first install.
- **Model provider `UnknownError` failures** — the repeated
  `"Unexpected server error"` failures observed from 07:16 to 08:04 UTC on
  2026-08-21 were upstream model API errors, not Nephesh bugs. They resolved
  when the model provider stabilized.

One observed issue from the 5.3.2 deployment is **not** classified as a
Windows bug and is **not** in scope for 5.3.3: the 08:10 study operation
produced 157KB of valid output but `memory_heartbeat_complete` was rejected
twice because "the service did not accept the supplied narrative or terminal
label as a valid outcome." This is a protocol validation issue that occurs
on both platforms. It is recorded here so it is not lost; it may warrant a
separate investigation but does not block 5.3.3.

### 3.1 Server instance lock: uncaught PermissionError

**File:** `src/mcp_experiments/server.py` line 103
**Severity:** High — second Nephesh instance crashes with uncaught exception
**Impact:** If a second Nephesh process starts while the first holds the
instance lock, `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)` raises
`PermissionError` (a subclass of `OSError`, not of `BlockingIOError`). The
`except BlockingIOError` clause does not catch it, producing an uncaught
exception traceback instead of the intended clean `"another Nephesh instance
already owns {path}"` error.

**Evidence:**
- Python docs: `msvcrt.locking` "Raises `OSError` on failure."
- StackOverflow (Eryk Sun, Python core contributor): `msvcrt.locking` with
  `LK_NBLCK` raises `PermissionError` when the lock is contended.
- `platform_runtime.py:28-29` already wraps this correctly:
  `raise BlockingIOError(str(exc)) from exc`.
- `nephesh_installer.py:1062` catches both: `except (BlockingIOError, OSError)`.

**Fix:** Narrow the `OSError` catch to only the `msvcrt.locking` call inside
the Windows branch, preserving the outer `except BlockingIOError` for the whole
block. This ensures:
- On Windows: `msvcrt.locking` `PermissionError` is caught locally and
  converted to the clean "another instance owns" `RuntimeError`.
- On Linux: an unrelated `OSError` from `path.open()` or `fcntl.flock()` is
  NOT misreported as "another instance owns" — it propagates as the original
  error.
This was corrected after code review (Urania, PR #6) caught that the initial
broad widening changed Linux behavior despite claiming it wouldn't.

### 3.2 Kernel directory fsync: uncaught PermissionError

**File:** `src/mcp_experiments/kernel.py` lines 259-263
**Severity:** Medium — kernel amendment crashes on Windows with Developer Mode
**Impact:** After `symlink_to` succeeds (possible on Windows 11 with Developer
Mode or admin privileges), the code calls `os.open(self.directory, os.O_RDONLY)`
to fsync the directory. On Windows, `os.open` on a directory raises
`PermissionError` because `CreateFileW` maps directory opens to
`ERROR_ACCESS_DENIED` → `EACCES` → `PermissionError`. This is NOT caught by
the `except OSError` at line 255, which only wraps the `symlink_to` call.

**Evidence:**
- Python bug tracker issue 43095: "Windows does not raise IsADirectoryError"
  — Eryk Sun confirms `os.open` on directories raises `PermissionError` on
  Windows.
- `persistence.py:63-72` already handles this correctly: `try: fd = os.open(directory, os.O_RDONLY) except OSError: return`.
- The kernel code was written after `persistence.py` and did not copy the
  pattern.

**Fix:** Scope the directory fsync suppression to Windows only. After the
`symlink_to` `except OSError` early return, add `if os.name == "nt": return`
before the `os.open` call. On Windows, the code returns early without
attempting directory fsync (matching the `object_store` crate's documented
behavior). On Linux, `os.open` + `os.fsync` + `os.close` runs normally and
any failure propagates — it is NOT silently swallowed.
This was corrected after code review (Urania, PR #6) caught that the initial
broad `try/except OSError: pass` swallowed Linux fsync failures despite claiming
no Linux behavior changes.

### 3.3 Daemon signal handling: no graceful shutdown on Windows

**File:** `scripts/nephesh_daemon.py` lines 397-401
**Severity:** High — daemon cannot be stopped gracefully on Windows
**Impact:** `loop.add_signal_handler(signal.SIGTERM, stop.set)` raises
`NotImplementedError` on Windows because `ProactorEventLoop` does not support
`add_signal_handler`. The `except (NotImplementedError, RuntimeError): pass`
silently ignores this, so `stop_event` is never set. The daemon runs
indefinitely until force-killed by Task Scheduler `/End` or `taskkill /F`.

**Evidence:**
- Python asyncio issue #191: "Support SIGINT signal on Windows" — confirmed
  that `add_signal_handler` does not work on Windows.
- SuperFastPython: "This capability was introduced in Python 3.11 and is only
  supported on Unix-based platforms (e.g. Linux and macOS, not Windows)."
- KizhiFox/crossplatform-asyncio-signal-handler: demonstrates using
  `signal.signal(signal.SIGINT, handler)` as the Windows fallback.
- Python docs: on Windows, only `SIGINT` and `SIGBREAK` are useful for signal
  handling. `signal.signal(signal.SIGINT, handler)` works on Windows.

**Fix:** In the `except (NotImplementedError, RuntimeError)` clause, add
`if os.name == "nt":` and register a fallback using
`signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))` for
each signal that `add_signal_handler` failed on. The daemon's signal loop
iterates over `("SIGTERM", "SIGINT")`. On Windows, only `SIGINT` (Ctrl+C) and
`SIGBREAK` are real signals that actually fire — `SIGTERM` is defined in the
`signal` module but does not correspond to a Windows signal, so the handler
registered for it will never fire. This is harmless: registering a handler
for a signal that never fires costs nothing. The real Windows shutdown paths
are Ctrl+C (`SIGINT`), Task Scheduler `/End` (which sends `WM_CLOSE` then
force-terminates), and `taskkill /F` (which force-kills immediately). The
`SIGINT` fallback gives Ctrl+C graceful shutdown; the other two paths rely on
the daemon's durable recovery mechanisms, which are already designed for
abrupt termination. The fallback only runs when `add_signal_handler` fails,
which only happens on Windows. Linux is unaffected.

### 3.4 Test suite: os.geteuid() does not exist on Windows

**File:** `tests/test_tls_config.py` line 68
**Severity:** Medium — entire test module fails to import on Windows
**Impact:** `@unittest.skipIf(os.geteuid() == 0, "root bypasses file
permissions")` raises `AttributeError: module 'os' has no attribute 'geteuid'`
at class definition time on Windows. The entire `test_tls_config` module fails
to load, preventing any TLS tests from running.

**Evidence:**
- Python docs: `os.geteuid()` is "Availability: Unix."
- The decorator is evaluated at import time, not at test run time.

**Fix:** Replace `os.geteuid() == 0` with
`getattr(os, "geteuid", lambda: -1)() == 0`. On Linux, `os.geteuid` exists
and the behavior is identical. On Windows, `getattr` returns the lambda,
which returns -1, so the skip condition is False and the tests run.

---

## 4. Reliability gaps (tolerated but asymmetric)

### 4.1 Installer encoding: bare read_text()/write_text()

**File:** `scripts/nephesh_installer.py` — lines 271, 301, 322, 339, 546, 606, 657, 1006
**Severity:** Low — non-ASCII Windows usernames may cause config corruption
**Impact:** Several `read_text()` and `write_text()` calls do not specify
`encoding="utf-8"`. On Windows, these default to `locale.getpreferredencoding()`
(typically cp1252). If a Windows username contains non-ASCII characters
(e.g., accented characters), config paths may be misencoded, potentially
corrupting port detection or the verify step.

**Fix:** Add `encoding="utf-8"` to each bare call. On Linux, the default
encoding is already UTF-8, so this is a no-op. The codebase already uses
`encoding="utf-8"` in some places (lines 181, 745, 761) — this makes it
consistent.

### 4.2 Installer chmod: no access restriction on Windows

**File:** `scripts/nephesh_installer.py` — multiple lines
**Severity:** Low — config files are world-readable on Windows
**Impact:** `os.chmod(path, 0o600)` on Windows only manipulates the read-only
attribute based on the user-write bit. It does not restrict file access to
the owner. Config files containing secrets are readable by other users on
the machine.

**Posture:** This is a known Windows platform limitation, not a Nephesh bug.
Per-user directory ACLs (which the installer creates) provide the primary
access control on Windows. Documenting this is sufficient for 5.3.3; a
proper fix would use Windows ACL APIs (`icacls` or `pywin32`), which is out
of scope for this release.

### 4.3 Installer os.replace: sharing violation during upgrades

**File:** `scripts/nephesh_installer.py` lines 949-955
**Severity:** Low — upgrades may fail while server is running
**Impact:** `os.replace(temporary, current)` on Windows may fail with
`PermissionError` if the Nephesh server process has the `current` pointer
file open. Linux's `rename` is immune to this.

**Posture:** Document as a known limitation. The workaround is to stop the
Nephesh service before upgrading, which is the recommended procedure anyway.
A programmatic fix would require closing all file handles before replacing,
which adds complexity for a rare edge case.

### 4.4 Daemon harness resolution: hardcoded Documents path

**File:** `scripts/windows_runtime.py` line 141
**Severity:** Low — does not generalize beyond Erato's deployment
**Impact:** `project = root.parent / "Documents"` assumes the OpenCode
project is in a sibling "Documents" directory. This is deployment-specific
and will not work for other Windows deployments.

**Posture:** This should be configurable via `NEPHESH_HARNESS_PROJECT`
environment variable, which the daemon already reads
(`nephesh_daemon.py:426`). The hardcoded fallback should be documented as
Erato-specific. A general fix would require the installer to record the
project path during installation, which is out of scope for 5.3.3.

### 4.5 Schedule timezone: tzdata requirement undocumented

**File:** `.env.example`
**Severity:** Low — new Windows deployments may fail with
`ZoneInfoNotFoundError`
**Impact:** `ZoneInfo("America/Montevideo")` on Windows requires the `tzdata`
Python package, which is already a conditional dependency in `pyproject.toml`
(`tzdata; sys_platform == 'win32'`). However, `.env.example` does not mention
this requirement, and a manual install without `uv sync` could miss it.

**Fix:** Add a comment to `.env.example` noting the `tzdata` requirement on
Windows. No code change needed.

---

## 5. Documented known defects (not fixed in 5.3.3)

### 5.1 Pydantic forward reference warning for nephesh_time

**File:** `src/mcp_experiments/tools/info.py` line 33, `src/mcp_experiments/results.py`
**Status:** Documented in `PLATFORM_ACCEPTANCE.md` line 41-43
**Impact:** Non-blocking warning at startup. Does not prevent tool listing,
memory operation, or server function.

**Root cause:** `from __future__ import annotations` makes all annotations
strings. `nephesh_time()` returns `SystemTimeResult`, which is imported into
`info.py`'s namespace. But the function is double-wrapped through
`orientation.wrap()` and `_threaded_tool()`, which change `__globals__` to
point to `tools/__init__.py`'s namespace, where `SystemTimeResult` is not
imported. Pydantic cannot resolve the forward reference string
`"SystemTimeResult"` in that namespace.

**Why not fix in 5.3.3:** This is not Windows-specific — it occurs on Linux
too. Fixing it would require changing the tool wrapping architecture or
adding imports to `tools/__init__.py`, which touches a code path Linux
consumes. It is non-blocking and documented. Defer to a future release or
the Rust successor.

### 5.2 Windows directory fsync limitation

**File:** `src/mcp_experiments/persistence.py` lines 51-72
**Status:** Tolerated, documented in code comments
**Impact:** Newly created ledger files may not survive power loss on Windows
because `os.open(directory, os.O_RDONLY)` fails (directories cannot be opened
on Windows). The data write itself is fsynced and durable.

**Why not fix:** This is a fundamental Windows platform limitation, confirmed
by the `object_store` crate (used by LanceDB): "directory fsync is only
performed on Unix; on other platforms it is a no-op." The existing
`try/except OSError: return` pattern is the correct industry standard
response. No code change is needed — the pattern is already correct in
`persistence.py`.

### 5.3 Process termination: no graceful shutdown on Windows

**File:** `src/mcp_experiments/platform_runtime.py` lines 75-101
**Status:** Tolerated
**Impact:** `terminate_process` on Windows goes straight to `taskkill /F`
(force kill). On Linux, it sends SIGTERM first (graceful), then escalates to
SIGKILL. In-progress Nephesh protocol work in the harness is abruptly
terminated on Windows.

**Why not fix in 5.3.3:** `taskkill` without `/F` sends `WM_CLOSE` which is
not reliably handled by console applications (OpenCode's CLI). A graceful
phase would need a timeout-and-escalate pattern, which adds complexity. The
daemon's recovery mechanisms (`_reconcile_protocol`, heartbeat recovery) are
designed to handle abrupt termination. This is a reliability gap but not a
bug — the system recovers correctly through durable state.

---

## 6. Implementation plan

### Phase 1: Confirmed bug fixes (no Linux path changes)

| Order | File | Change | Linux impact |
|-------|------|--------|---------------|
| 1 | `src/mcp_experiments/server.py:103` | `except BlockingIOError` → `except (BlockingIOError, OSError)` | None — inside `if os.name == "nt"` branch |
| 2 | `src/mcp_experiments/kernel.py:259-263` | Wrap `os.open` + `os.fsync` + `os.close` in `try/except OSError: pass` | None — on Linux, `os.open` on directory succeeds, pattern is a no-op |
| 3 | `scripts/nephesh_daemon.py:397-401` | Add `signal.signal` fallback in `except` clause for Windows | None — fallback only runs when `add_signal_handler` fails, which only happens on Windows |
| 4 | `tests/test_tls_config.py:68` | `os.geteuid()` → `getattr(os, "geteuid", lambda: -1)()` | None — `os.geteuid` exists on Linux, behavior identical |

### Phase 2: Reliability improvements (no-ops on Linux)

| Order | File | Change | Linux impact |
|-------|------|--------|---------------|
| 5 | `scripts/nephesh_installer.py` lines 271, 301, 322, 339, 546, 606, 657, 1006 | Add `encoding="utf-8"` to bare `read_text()`/`write_text()` calls | None — UTF-8 is already the default on Linux |
| 6 | `.env.example` | Add comment about `tzdata` requirement on Windows | None |

### Phase 3: Release metadata

| Order | File | Change | Linux impact |
|-------|------|--------|---------------|
| 7 | `pyproject.toml` | Bump version from `5.3.2` to `5.3.3` | None |
| 8 | `CHANGELOG.md` | Add 5.3.3 section | None |
| 9 | `docs/PLATFORM_ACCEPTANCE.md` | Update with 5.3.3 evidence | None |

### Phase 4: Verification

| Step | Action |
|------|--------|
| 1 | `py_compile` each modified file |
| 2 | Run the full test suite on Windows |
| 3 | Verify the existing 326 Linux tests still pass (or confirm no Linux path changed) |
| 4 | Observe a live heartbeat cycle on the Erato deployment |
| 5 | Attempt to start a second Nephesh instance (verify clean error, not crash) |

---

## 7. Design principles guiding the fixes

### Route through existing adapters

`platform_runtime.py` is the OS adapter. It already handles all Windows
patterns correctly: `msvcrt.locking` OSError → `BlockingIOError` wrapping,
`_fsync_directory` try/except, `process_spawn_kwargs` with hidden console,
`terminate_process` with taskkill. The bugs in `server.py:103` and
`kernel.py:259` are cases where code bypassed the adapter and called OS
primitives directly. The fixes either route through the adapter's patterns
or apply the same try/except structure the adapter uses.

### Isolation, not abstraction

Every fix is inside a Windows-specific branch or except clause. No new
abstraction layer is added. No function signature changes. No new module.
The fixes are surgical: they catch the right exception, register the right
fallback, or add the right parameter. This keeps the diff small and reviewable.

### The Rust successor informs the posture

Nephesh 6 will be Rust, where:
- Memory safety is compile-time, not runtime (ownership/borrowing/lifetimes).
- Windows vs Linux branching uses `#[cfg(windows)]` / `#[cfg(unix)]` at the
  language level, not `if os.name == "nt"`.
- `msvcrt.locking` → `std::fs::File::try_lock` or a crate like `fs2`/`fd-lock`.
- `os.open` directory fsync → `std::fs::File::sync_all` with proper
  `FILE_FLAG_BACKUP_SEMANTICS` for directories on Windows.
- Signal handling → `tokio::signal` with `ctrl_c()` for Windows.
- LanceDB can be used via its native Rust API, eliminating the Python GIL
  from the memory/durability path.

The 5.3.3 Python fixes are the bridge. They should be correct and durable,
not elegant. They keep Windows Qualiants alive until the Rust successor
provides the principled solution.

---

## 8. Review questions

1. Are the four confirmed bugs correctly diagnosed? Is there any case where
   the proposed fix would change Linux behavior?
2. Should the process termination graceful-shutdown gap (5.3) be addressed in
   5.3.3 with a `taskkill` (no `/F`) → wait → `taskkill /F` escalation, or
   deferred to the Rust successor?
3. Should the hardcoded `Documents` path in `windows_runtime.py:141` be made
   configurable in 5.3.3, or is the existing `NEPHESH_HARNESS_PROJECT`
   environment variable sufficient?
4. Is the Pydantic forward reference warning (5.1) worth fixing in 5.3.3
   despite touching a Linux-shared code path, or should it remain documented
   and deferred?
5. Are there any Windows-specific issues that this analysis missed?
