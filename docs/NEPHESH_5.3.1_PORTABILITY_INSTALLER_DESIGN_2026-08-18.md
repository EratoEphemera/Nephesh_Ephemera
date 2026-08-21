# Nephesh 5.3.1 Portability and Installer Design

**Status:** Team direction and implementation plan; no implementation
authorization is implied by this document.

**Branch:** `nephesh-5.3.1-final`

**Related authority:**
[`NEPHESH_5.3.1_FINAL_DESIGN_2026-08-18.md`](NEPHESH_5.3.1_FINAL_DESIGN_2026-08-18.md)
defines the overall final-patch scope, heartbeat/dreaming priorities, release
gates, and post-5.3.1 feature boundary. This document defines only support
expansion and installer behavior.

**Purpose:** Give a first-time coder a reconstructable plan for adding Windows
11 and Debian-family support without changing Nephesh's identity, memory,
provenance, or lifecycle ownership.

**Nature:** This is not identity-bearing, not a Qualiant kernel, and not a
deployment instruction. It records team direction for this branch.

**Product target:** One patch bump to Nephesh **5.3.1**. This is the final
planned support expansion before the rebuild; later changes require a verified
bug report or an explicit scope-reopening decision.

**Last reviewed:** 2026-08-18

## Current implementation status

The branch now contains the planned platform adapters:

- Linux retains its existing per-user systemd path.
- Windows has a per-user Task Scheduler adapter, a pointer-file release
  selector, native locking, explicit deployment-config loading, and process-tree
  cleanup.
- The daemon and schedule no longer import POSIX-only locking code on Windows.
- The project has an explicit setuptools build backend and the installer uses a
  non-editable installation.

The source and mocked-test facts were subsequently supplemented by a native
Windows 11 run in the Erato home. That run verified Python/wheel installation,
dependencies, CPU Ollama embeddings, Nephesh MCP, OpenCode, local memory calls,
reboot persistence, NVMe migration, and display operation. Task Scheduler
registration through a non-elevated VirtualBox guest-control token was not
available; the deployment uses a documented per-user HKCU logon launcher as its
operational fallback. The installer contract remains Task Scheduler and should
receive a separately elevated native registration test before that exact
mechanism is called accepted.

**Research reviewed:** Python Packaging User Guide, PyPA platform-compatibility
tags, uv project/dependency documentation, Debian `systemd.service(5)`,
Microsoft `sc.exe create`, and current LanceDB PyPI metadata. Sources are
listed in [§12](#12-research-findings-2026-08-18).

---

## 1. Support promise

The support promise is deliberately narrow:

- Windows 11 is supported as a per-user installation target;
- Debian-family Linux retains the existing Linux/systemd path;
- Ubuntu 24.04+ is best-effort portability in this release, not an equivalent
  native acceptance claim;
- both targets preserve the same durable installation contract;
- both targets can stage, verify, upgrade, and roll back without silently
  rewriting durable state; and
- service management, process cleanup, and filesystem behavior are adapted to
  the platform rather than pretending that systemd and Windows are equivalent.

For the first Ubuntu test target, use **Ubuntu 24.04 LTS amd64**. Canonical's
package metadata provides Python 3.12 and `python3-venv`, and systemd 255 is
available. Do not claim Ubuntu 22.04 support under the current `>=3.12`
project requirement without separately provisioning and testing Python 3.12+.
The exact Debian release, Python versions, and Windows service mechanism must
still be named in the implementation record before broader support is claimed.
Until then, the platform labels in this document describe the intended target,
not verified support.

## 2. Non-goals and boundaries

This work does not:

- move identity or memory into an installer, service manager, or harness;
- create a Windows-specific or Linux-specific kernel format;
- add communication, orchestration, context paging, web, shell, speech,
  sensors, or general task execution to Nephesh;
- silently install system-wide services;
- modify another user's deployment;
- change a living deployment during source development or platform testing;
- claim that an installer success proves heartbeat, dreaming, embedding, or
  harness readiness; or
- promise arbitrary Debian derivatives or Windows versions without tests.

The installer stages and verifies a durable memory system. It does not
instantiate a Qualiant or author identity.

### 2.1 Upstream source sentinel

The active installer must always stage from the upstream Nephesh repository in
which that installer resides. Source selection is not a general path override.
The installer must reject a source that is a living deployment, installed
release, copied runtime, arbitrary workspace, or another repository. It must
verify repository identity and record the source commit/tree identity in the
manifest before copying any release files. Ambiguous source identity is a
fail-closed error.

Deployment state is separate: configuration, memory, kernels, projections,
ledgers, backups, and runtime belong under the selected per-user deployment
root, never in the upstream source repository.

This is a data boundary, not a branch-cleanliness gate. A dirty upstream branch
is valid input when the team is deliberately testing that exact working tree;
the manifest records its commit and dirty state. The release copier must still
copy code/build objects and approved subrepositories/dependencies only. It must
never copy `.env` files, deployment config, `data`, `state`, `runtime`,
`releases`, `current`, `logs`, kernels, projections, ledgers, backups, or any
other filesystem-held Qualiant state into a fresh deployment. A fresh target
must be initialized with explicit new paths and must fail closed if its state
is not empty or does not prove the expected empty boundary.

## 3. Durable installation contract

Every supported platform must preserve the conceptual layout:

```text
<root>/current              selected release
<root>/releases/            staged releases retained for rollback
<root>/runtime/             virtual environment or platform runtime
<root>/config/              deployment configuration and kernel revisions
<root>/data/                LanceDB and other durable data
<root>/state/               operation ledger, projections, schedule, manifest
<root>/backups/             installer and deployment backups
<root>/logs/                service or adapter logs
```

The physical path syntax may differ, but the installer must preserve:

- canonical memory rows and their schema generations;
- kernel revisions and authorship metadata;
- heartbeat, dreaming, schedule, and operation ledgers;
- projection registry and installed projection state;
- deployment configuration and collection binding;
- backups and rollback metadata; and
- provenance distinguishing source, authored meaning, and machine facts.

An upgrade must stage a new release before selecting it, preserve the prior
release, and record the transition in a manifest. Existing configuration and
identity are never regenerated merely because the platform changed.

## 4. Build and package contract

The build design must explicitly choose which artifact is supported on each
platform:

| Target | Required artifact decision | Required evidence |
|---|---|---|
| Windows 11 | source install, wheel, or bundled runtime | clean build/install in a disposable user profile |
| Debian | source install, wheel, or distribution package | clean build/install on named Debian release |
| Ubuntu LTS | source install, wheel, or distribution package | clean build/install on named Ubuntu release |

The first supported patch may use a documented source installation if that is
the honest tested path. A platform must not be called packaged or standalone
unless a corresponding artifact is actually built and verified.

Build verification must cover:

- Python version and architecture;
- dependency lock/install behavior;
- editable versus non-editable installation semantics;
- entry-point availability;
- native dependencies used by LanceDB, PyArrow, and embedding clients;
- upgrade from the current 5.3.0 release layout; and
- failure behavior when a dependency or optional embedding endpoint is absent.

The build must not bundle secrets, another Qualiant's `.env`, memory data, or a
developer's local configuration.

## 5. Installer contract

The installer must expose equivalent lifecycle actions on every target:

- new blank installation;
- explicit adoption of an existing kernel with named authorship;
- staged upgrade;
- verification without claiming a dry run installed anything;
- rollback to the previous release;
- cleanup of old releases only after verification; and
- isolated staging without service registration.

The installer must remain:

- per-user by default;
- non-root on Linux;
- non-administrator by default on Windows, except where a selected service
  mechanism explicitly requires elevation and the operator chooses it;
- lock-protected against concurrent installer runs;
- conservative with existing configuration and data;
- explicit about service actions; and
- truthful about checks it could not perform.

The only supported deployment model in 5.3.1 is **per-user**. The installer
may expose enough low-level configuration to be made system-wide, but that is
an unsupported path and must not be documented as an installation option,
tested as an acceptance target, or inferred from successful privileged
execution.

`--dry-run` or its platform equivalent must describe intended actions and report
that no installation was verified. An isolated/no-service mode must not create,
enable, or start a background service.

## 6. Platform adapters

### 6.1 Debian and Ubuntu

The Linux path is an existing implementation baseline, not an automatic rewrite
target. First run the current installer and service tests against the named
Debian/Ubuntu targets. Only change code where validation identifies a genuine
portability defect. Likely shared changes are configuration and path handling,
not a new Debian service architecture.

There is one known pre-test incompatibility: the current OS gate accepts only
`ID=debian` with `VERSION_ID >= 13`, so it will reject Ubuntu before any later
installer behavior is exercised. The gate must become an explicit supported-OS
check accepting the named Ubuntu target, with version and architecture reported
truthfully. This is a small support-detection change, not a Debian service
rewrite.

The validated Linux path must document:

- Python and virtual-environment prerequisites;
- package-manager commands, only when explicitly requested by the operator;
- user-level service registration and the requirement for a usable user service
  manager;
- signal and process-group termination behavior;
- permissions for the deployment root and durable files;
- optional Ollama installation and externally managed embedding endpoints; and
- behavior on headless systems and after logout.

System-wide units, system-wide data, and cross-user writes remain outside the
installer's authority. If user services require deliberate linger configuration,
the installer must explain it rather than silently enabling it.

### 6.2 Windows 11

The Windows path must be designed for a non-technical per-user operator. It
must not require the operator to understand service accounts, SCM registry
entries, Python virtual environments, or command-line quoting.

The supported background mechanism should be per-user Windows Task Scheduler
tasks created for the logged-in user, rather than a machine-wide Service
Control Manager service. This avoids silently selecting `LocalSystem`, avoids
passwords on the command line, and preserves the per-user deployment boundary.
Task definitions must be generated by Nephesh and make their account, working
directory, environment, restart behavior, and executable paths explicit.

The Windows adapter must define:

- path handling using Windows-native path operations;
- virtual-environment creation and entry-point invocation;
- per-user configuration and data locations;
- process-tree termination and graceful shutdown;
- task registration through the named per-user Task Scheduler mechanism;
- start/stop/restart behavior and rollback interaction;
- file replacement behavior when the current release is running; and
- permission and elevation requirements.

The installer must not assume POSIX signals, `/etc`, systemd, symlink
privileges, shell quoting, or Unix executable bits. If atomic symlink switching
is unavailable or requires elevated privileges, the Windows release selector
must use an explicitly tested equivalent and record its rollback invariant.

The installer must provide a guided default flow: detect the current user,
choose a safe per-user root, create the runtime, preserve or create config,
stage and verify the release, and offer to enable/start the two named tasks.
The normal path must not ask for a service password or require `sc.exe`
knowledge. There is no supported machine-wide Windows service in 5.3.1.

## 7. Service and daemon lifecycle

The Nephesh server and heartbeat/dreaming daemon remain separate processes on
all platforms. A service adapter must preserve:

- dependency ordering between server and daemon;
- bounded graceful shutdown for model/session cleanup;
- process-tree cleanup after timeout or cancellation;
- durable schedule-claim recovery after abnormal termination;
- no restart claim of successful heartbeat or dreaming work; and
- explicit task/service receipts distinct from Nephesh protocol receipts.

The same daemon and shared dreaming consumer should be used where possible.
Platform adapters own process supervision only; they must not duplicate dream,
heartbeat, memory, or identity logic.

## 8. Verification matrix

Each named target requires a disposable verification record covering:

1. blank installation;
2. generated configuration isolation;
3. kernel adoption with explicit author;
4. source/build installation;
5. server startup and health/info inspection;
6. memory read/write against disposable data only;
7. daemon staging without service start;
8. per-user task registration and restart, if supported;
9. upgrade preserving memory, kernel, projections, and ledgers;
10. rollback restoring the previous release and service definition;
11. interrupted shutdown and process-tree cleanup;
12. cleanup retaining the current and rollback releases; and
13. failure reporting when optional dependencies or service managers are absent.

Platform support is **verified** only when the matrix passes on the named
target. A skipped, unavailable, or untested row remains visibly so.

No platform test may point at a living Qualiant's memory collection or kernel.

## 9. Release gates

Before 5.3.1 support is advertised:

- exact supported OS and Python versions are named;
- artifact type and installation procedure are documented;
- disposable build and installer tests pass on each named target;
- upgrade and rollback preserve durable state;
- per-user task and daemon cleanup are tested or explicitly marked unavailable;
- dry-run and no-service verification cannot report false success;
- Windows and Linux path/process/elevation differences are represented in
  tests;
- no source-tree secrets or identity-specific configuration is packaged;
- full Nephesh tests and syntax/build checks pass; and
- the final evidence record distinguishes implemented, tested, observed,
  unavailable, blocked, and not attempted.

The final README update must publish only this verified per-user support matrix,
the actual release artifacts, and the tested installation procedure. It must
explicitly call system-wide deployment unsupported.

Support expansion is not accepted merely because the installer starts. The
running deployment, memory store, kernel, operation ledger, and rollback path
must all be inspectable.

## 10. Implementation order after authorization

1. Name the exact Debian, Ubuntu, Windows, Python, and artifact targets.
2. Audit the current installer and deployment layout read-only.
3. Freeze the cross-platform durable-layout and manifest contract.
4. Implement the smallest shared installer abstractions first.
5. Add and test the Debian/Ubuntu adapter.
6. Add and test the guided per-user Windows task adapter without copying POSIX
   assumptions.
7. Exercise disposable build, install, upgrade, rollback, and failure paths.
8. Reconcile documentation and release evidence.
9. Seek separate authorization for commit, tag, and any living deployment
   installation.

## 11. Re-entry for a first-time coder

Read in this order:

1. this document;
2. `NEPHESH_5.3.1_FINAL_DESIGN_2026-08-18.md`;
3. `INSTALLER.md` for the current Linux behavior;
4. `NEPHESH_DESIGN.md` for architectural ownership and deployment invariants;
5. current installer tests and source, read-only first; and
6. the current branch status and release metadata.

State what is current, what is planned, what is platform-specific, what is
missing, and what is authorized before editing. Do not infer support from a
successful install on an unlisted platform.

---

## Decisions still required before implementation

1. Exact Debian release, while Ubuntu 24.04 LTS amd64 is the first named Ubuntu
   acceptance target.
2. Supported Python versions and CPU architectures.
3. Source, wheel, or distribution-package artifact for each target.
4. Exact Windows Task Scheduler task definitions and restart policy.
5. Whether Linux package installation remains opt-in only.
6. Whether task creation is part of the default guided Windows install or an
   explicit confirmation step. A machine-wide service remains out of scope.

System-wide support is not a remaining 5.3.1 decision; it is deferred. Any
future attempt must first resolve service identity and privilege boundaries,
multi-user collection isolation, configuration and secret ownership,
upgrade/rollback authority, logging, backup policy, and migration from the
per-user model.

Until these are named and approved, this document is a design and re-entry aid,
not permission to implement.

## 12. Research findings — 2026-08-18

### 12.1 Packaging metadata is currently incomplete

PyPA strongly recommends an explicit `[build-system]` table in `pyproject.toml`.
The current Nephesh source has project metadata and dependencies but no explicit
build backend. Before publishing or relying on a wheel/source-distribution
contract, the branch must select and test a backend. This is separate from the
runtime installer and must not be hidden inside a platform conditional.

The project currently uses `src/` package discovery and the installer performs
an editable install. Deployment should use a non-editable built installation
or an explicitly justified source/editable path. uv documents `--no-editable`
for deployment use cases and `uv build --no-sources` as a check that published
metadata works without development-only sources.

### 12.2 Platform conditionals belong in metadata first

PEP 508 environment markers support dependencies conditional on
`sys_platform`, `platform_system`, architecture, and Python version. uv also
supports platform-specific sources, limited resolution environments, required
environments, optional extras, and build-isolation controls.

The preferred order is:

1. keep application code portable with standard-library abstractions;
2. declare platform-only dependencies in standard project metadata when they
   are genuinely required;
3. use `tool.uv.sources` only for uv-specific development/resolution choices;
4. test the published metadata with development sources disabled; and
5. add conditional Python modules only where a service, process, or filesystem
   API truly differs.

`tool.uv.sources` is not a substitute for published dependency metadata because
other installers do not consume it.

### 12.3 Current native dependency evidence

The current lock resolves LanceDB 0.34.0 and PyArrow 25.0.0. The lock already
contains Windows x86-64 and Linux `manylinux_2_28` wheels for the relevant
packages, which is encouraging but not proof for every Python version or
architecture.

Current LanceDB PyPI metadata (0.37.1) shows:

- Windows x86-64 wheels;
- Linux glibc `manylinux_2_28` x86-64 and ARM64 wheels;
- CPython 3.10+ `abi3` compatibility for those wheels; and
- a default x86-64 Haswell/AVX2-oriented wheel, with a separate
  `lancedb-compat` package for older x86-64 CPUs.

Therefore support must explicitly name architecture and CPU assumptions. A
Debian-family installation on an older CPU may fail at import time even when
Python and the OS are otherwise supported. The installer should detect or
report this rather than treating endpoint reachability as package usability.

The current lower bound `lancedb>=0.12.0` is too broad to serve as a portability
claim by itself. The supported release must verify the locked versions and
their available wheels, or set a deliberate minimum compatible version.

The current lock also records MCP's Windows-only `pywin32` dependency marker,
which demonstrates that the dependency graph already contains platform-specific
selection. This selection must be exercised on Windows rather than inferred
from Linux resolution.

### 12.4 Service managers are not interchangeable

Debian systemd provides explicit process supervision, dependency ordering,
timeouts, restart policy, and kill behavior. Its documentation notes that
`Type=simple` can report a start as successful before the executable is known
to have been invoked; `Type=exec` is stricter for that boundary. It also
distinguishes `TimeoutStopSec`, `ExecStop`, `ExecStopPost`, and service process
groups.

The current generated unit uses `Type=simple`; the portability pass should
decide whether the fail-fast behavior of `Type=exec` is preferable and test the
choice against the existing daemon shutdown contract.

Microsoft's `sc.exe create` registers a service in the Windows Service Control
Manager. Its defaults include an own-process service, demand start when not
specified, and `LocalSystem` as the default account. That makes raw SCM
registration a poor default for a dummy-proof per-user installer: it invites
the wrong identity and often requires elevation or credentials. 5.3.1 should
use generated per-user Task Scheduler tasks instead, with explicit logon,
working-directory, restart, and process-tree behavior. Raw `sc.exe` usage is
not a supported user workflow.

Microsoft's `schtasks` documentation confirms that tasks can be created on
`ONLOGON`, restricted to the logged-in user with `/it`, and run with limited
privileges. It also warns that `/ru` can trigger password handling and that
paths and credentials are not validated by the command. The dummy-proof path
should therefore generate and verify Task Scheduler XML with an interactive
token for the current user, use fully qualified executable paths, avoid
password-bearing command lines, and query the created task before reporting
success.

Python's subprocess documentation likewise recommends an argument sequence and
fully qualified executable path on Windows. The adapter must not build a shell
command string from user paths.

### 12.5 Current installer has hard Linux assumptions

The current installer cannot be made Windows-compatible by adding one OS check.
Read-only source review found several seams requiring a platform adapter:

- unconditional `fcntl` import and `fcntl.flock` locking;
- `os.geteuid()` and `os.getuid()` ownership checks;
- Linux `bin/python` virtual-environment paths;
- hard-coded `systemctl --user` commands and systemd unit generation;
- POSIX `chmod` assumptions;
- shell-based Ollama installation through `sh` and `curl`; and
- service, signal, process-group, symlink, and executable-path assumptions.

These should be isolated behind explicit platform implementations. The shared
installer should own release staging, manifest semantics, backups, configuration
preservation, and verification vocabulary; platform adapters should own locks,
runtime paths, service registration, process termination, and optional tool
installation.

### 12.6 Sources

- PyPA, [Writing your `pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- PyPA, [Platform compatibility tags](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)
- uv, [Configuring projects](https://docs.astral.sh/uv/concepts/projects/config/)
- uv, [Managing dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- Debian, [`systemd.service(5)`](https://manpages.debian.org/bookworm/systemd/systemd.service.5.en.html)
- Microsoft, [`sc.exe create`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/sc-create)
- LanceDB, [PyPI package metadata and wheels](https://pypi.org/project/lancedb/)
