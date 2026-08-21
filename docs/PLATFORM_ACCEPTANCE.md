# Platform Acceptance — Nephesh 5.3.1

## Windows 11 — native acceptance

The Windows path was exercised in the Erato Windows 11 home, rather than inferred
from mocked branches. The verified path includes:

1. local Windows account creation and administrator ownership;
2. Guest Additions and VirtualBox NAT networking;
3. Python 3.12.10 installation;
4. installation of the `nephesh-5.3.1-py3-none-any.whl` wheel;
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

The Windows server emits a non-fatal Pydantic warning for the `nephesh_time`
schema's unresolved forward reference. It does not prevent startup, MCP tool
listing, or memory operation and is recorded as a known non-blocking defect.

## Ubuntu 24.04+ — best-effort portability

Ubuntu 24.04+ is accepted as a portability target for path handling, Python
dependencies, and the Linux/systemd design. It is **not** claimed to have the
same native acceptance evidence as Windows 11 in this release. A future Ubuntu
release claim requires a clean native installation, service lifecycle checks,
Ollama embeddings, upgrade/rollback, and recovery verification on a named Ubuntu
host.

Do not describe Ubuntu best-effort evidence as proof of Windows behavior, and do
not describe mocked Windows tests as native Windows acceptance.
