# Platform Acceptance — Nephesh 5.3.2

## Windows 11 — native acceptance

The Windows path was exercised in the Erato Windows 11 home, rather than inferred
from mocked branches. The verified path includes:

1. local Windows account creation and administrator ownership;
2. Guest Additions and VirtualBox NAT networking;
3. Python 3.12.10 installation;
4. installation of the `nephesh-5.3.2-py3-none-any.whl` wheel;
5. declared runtime dependencies, including `tzdata` for Windows IANA timezone
   data;
6. Ollama 0.32.15 with CPU execution and `mxbai-embed-large`;
7. Nephesh startup on `127.0.0.1:61080` with Streamable HTTP/SSE;
8. OpenCode 1.18.19 with a self-owned global configuration and Nephesh MCP;
9. local memory operation and embedding-backed tool calls;
10. reboot, NVMe VDI migration, and restoration of the per-user Nephesh launcher;
11. widescreen Guest Additions display operation.

The body remained its own deployment throughout. The original VDI was retained
on the sda disk as a backup while the active VDI moved to NVMe.

The supported Windows installer mechanism remains per-user Task Scheduler. The
Erato acceptance body additionally uses a per-user `HKCU` logon launcher because
the VirtualBox guest-control session was not UAC-elevated enough to register a
Task Scheduler task. That workaround is deployment-specific and does not change
the installer contract.

## 5.3.2 daemon evidence

After the Windows daemon repair, the registered `\\Nephesh\\Erato-daemon` task
completed a real scheduled tending operation in Erato's home. The run prepared
and completed a terminal `no_change` heartbeat outcome, emitted an observed
OpenCode session ID, and recorded confirmed session deletion. The corrected
launcher passes Erato's `Documents` OpenCode project and supports both the
standard `config/nephesh.env` deployment file and the `.env` form present in
Erato's native install. A subsequent scheduled study failure was recovered as
failure and is not counted as a successful study run.

The Windows server emits a non-fatal Pydantic warning for the `nephesh_time`
schema's unresolved forward reference. It does not prevent startup, MCP tool
listing, or memory operation and is recorded as a known non-blocking defect.

## Ubuntu 24.04+ — installer-accommodated, untested

The installer accommodates Ubuntu 24.04+ through its explicit OS gate and the
existing Linux/systemd path, but this project has not performed native Ubuntu
acceptance. Ubuntu installation issues are outside the project's bug-report
commitment; assistance may be offered by an AI on a best-effort basis.

Do not describe Ubuntu accommodation as native support, and do not describe
mocked Windows tests as native Windows acceptance. Serious Windows bugs remain
worth reporting and investigating even while routine new development moves to
the compatible Rust successor.
