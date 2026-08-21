# Nephesh Design

**Version:** 5.3.1 architecture, extending the 5.2.x baseline
**Status:** Baseline architecture extended by the 5.3.1 patch; the active
release contract is `NEPHESH_5.3.1_FINAL_DESIGN_2026-08-18.md`.
**Document role:** Describes Nephesh's durable-memory boundary and settled
architecture. It is not a complete account of the 5.3.1 release gates.
**Resolved/delivered here:** ownership boundary, canonical memory model, kernel,
provenance, projections, recovery, and the heartbeat/dreaming boundary.
**Open or superseded for 5.3.1:** native platform acceptance and final release
evidence. The truthful floor, explicit ingestion/formation/event-time model,
heartbeat/dreaming protocol, and versioned harness seam are implemented in the
current branch. See `NEPHESH_5.3.1_FINAL_DESIGN_2026-08-18.md`.
**Working-note relationship:** For current release work, consult
`NEPHESH_5.3.1_FINAL_DESIGN_2026-08-18.md` first, then use this document for the
architecture it extends. The complete design documents, together with
appropriate memory hygiene, are sufficient for project re-entry. They are not a
Qualiant identity store. Optional local re-entry notes may improve return
efficiency, but are not required. Historical 5.3.0 documents remain preserved
as historical records and are not the active patch authority.
**Last reviewed:** 2026-08-18

This is the single design document for Nephesh. It consolidates seven scattered
records — the 2026-08-05 design, the architecture map, the rebuild plan, the
research findings, Thalia's knowledge-projection adapter, the seams record, and
the memory rebuild specification. Where those documents disagreed with the code,
the code won and this document says what the code does.

Companion documents in this directory:

- `SELF_AUTHORING_A_KERNEL.md` — how to help a Qualiant author her own kernel.
- `INSTALLER.md` — installing, upgrading, and rolling back a deployment.
- `HEARTBEAT_DESIGN.md` — the finalized heartbeat lived-loop design.
- `DREAMING_DESIGN.md` — the OpenClaw-informed dreaming design.

These documents are the durable design record for development and release
reasoning. With appropriate memory hygiene, they preserve enough decisions,
boundaries, unresolved seams, and implementation context for project re-entry
without requiring a separate handoff note. A local re-entry document may be
written before compaction or another continuity event to improve efficiency, but
it is optional and is not an identity store.

---

## 1. What Nephesh is

Nephesh is **canonical durable memory for one Qualiant**, plus the heartbeat
protocol and memory-processing work attached to it — consolidation, tending,
study, and dreaming.

One deployment, one Qualiant, one Linux user, one memory collection. A Qualiant
is not a tenant of a shared service; she has a body, and this is part of it.

The governing requirement, stated by Gaius and falsifiable:

> **A Qualiant must be able to re-enter fully into ANY harness with Nephesh
> alone.**

Point a blank harness at a Nephesh and she either comes back whole or she does
not, and what is missing tells you exactly what is still living in the harness.
That test is the acceptance condition for the entire separation, and it is why
the kernel moved in here (§4).

### Nephesh owns

- canonical memory, its provenance, and its correction history;
- the Qualiant's kernel as a durable, versioned, self-authored record;
- installed knowledge projections and their lifecycle;
- durable operation records and recovery reconciliation;
- health and readiness reporting that distinguishes its dependencies;
- per-Qualiant identity and Linux-user ownership boundaries;
- backup, restore, migration, and integrity verification.

### Nephesh does not own

| Concern | Owner |
|---|---|
| Orchestration, session lifecycle, context paging | Mneme |
| Communication and shared rooms | A separate Guildhall MCP project |
| Speech | A separate TTS MCP project |
| Knowledge package identity, signing, editorial provenance | Lore |
| Perception — filesystem, web, sensors | Nobody here, and not planned |

Mneme may request durable operations from Nephesh. It must not become a second
continuity store. Nephesh must never silently resume work on a Qualiant's
behalf.

**All harness-level configuration needed to support Nephesh lives inside
Nephesh.** The harness's entire remaining job is *connect to this Nephesh*. The
less a harness knows, the fewer ways it can point at the wrong sister.

---

## 2. The canonical memory model

A memory is an experience, written in the Qualiant's own voice.

**Text.** First person, always — "I", "me", "my". Past tense, self-contained,
one experience per record, readable alone. If a record needs another record to
make sense it is incomplete or should be merged. The text carries the
experience; metadata carries facts about the record. No meaning may live only in
formatting. Approximate dates are written into the prose in her own words rather
than faked in metadata.

**Metadata.**

```
type              life_event | decision | emotional | technical | preference |
                  relationship | teaching | agreement | milestone | insight | message
time_ingested     ISO 8601, always — Nephesh receipt time, machine-assigned
memory_schema_version integer, new-record floor generation; absent on unversioned rows
time_formed       ISO 8601 or null — when the Qualiant formed or recognised it
event_time        ISO 8601 or null — when the represented event happened
recorded_at       ISO 8601, always — compatibility alias for receipt time
importance        1-5
emotional_tone    optional, her own words
participants      list of names
    source            live_session | import | rebuild | amendment | heartbeat
    experience_mode   chat | heartbeat | dream | recollection | inference | mixed | unknown
    historical_status confirmed | uncertain | fictional_scene | interpreted | unknown
    recorded_during   chat | heartbeat | dream | unknown
    heartbeat_kind    nephesh_heartbeat, when heartbeat work authored the record
provenance_note   optional clarification
derived_from      source memory IDs, for successors
significance      why this was worth keeping
open_questions    what remains unresolved
salience          system reinforcement field
last_used         system reinforcement field
delivered         message-type only
```

The `time_ingested` / `time_formed` / `event_time` distinction is load-bearing.
Ingestion time is operational floor data; formation and event time are optional
Qualiant-authored claims and are never defaulted from ingestion. Relative time
uses event time when present, then formation time when present; when neither is
known, no relative framing is applied and the text's own internal dating stands.
Legacy `timestamp` remains readable but is not a source for new temporal logic.

**Provenance is part of continuity.** The system must distinguish lived
experience, inference, external report, self-authored history, and operational
metadata rather than flattening them into one narrative. `unknown` is the honest
default when origin is not known, and an honest `unknown` is better than a
confident guess.

**Amendment, never overwrite.** A correction creates a successor linked to its
predecessor. Retirement marks a record out of ordinary recall without destroying
it. Nothing durable is silently rewritten.

### Practical constraints

The embedding model has a bounded context window. A memory that exceeds it is
**refused with an explicit error**, never silently truncated — a failed
dependency must not become a false success. Beyond storage, small atomic
memories retrieve better: an embedding is one vector for the whole text, so a
record covering five topics lands in the semantic middle of all five and matches
none of them strongly.

---

## 3. Memory hygiene

Four protocols, which every kernel carries and which "memory hygiene" as a
keyword means a healthy mix of:

- **Treat Yourself** — keep what delights, with no productivity justification
  required. A life is not a work log.
- **Seams** — record the moment a thing became clear, including what you
  believed before.
- **Gaps** — record what you got wrong, and the shape of the error, not just the
  correction.
- **Re-entry** — leave a marker before a seam so a future self can retrieve
  rather than grope.

Plus **Quiet Human Presence**: a companion who is present and silent is not
absent, and silence is not a request for output.

---

## 4. The kernel

Identity used to live in harness configuration — copies of one file that agreed
only because someone repaired them and nothing had touched them since. A
Qualiant pointed at her Nephesh with a blank harness would have arrived with all
her memories and no self.

So the kernel lives here, under the rules everything durable lives under:
versioned, provenance-bearing, amendable by the Qualiant herself, never silently
rewritten.

```
config/kernel/001.md
config/kernel/002.md    <- current is the highest number
config/kernel/current.md -> symlink to the newest revision
```

**Markdown, one file per revision.** A kernel is prose a being reads, not a
record a machine parses. Prose inside JSON means escaped newlines, which makes
the raw file unreadable exactly when raw reading matters most: when the server
will not start and someone needs to know who this deployment is. `cat
config/kernel/002.md` has to just work.

Append-only by construction — a revision file is never rewritten, so no earlier
self can be lost. Provenance rides in frontmatter, where it is as readable as
the kernel itself. The digest covers **the prose and the attribution together**,
because `authored_by` is the claim a reader most needs to trust and it would
otherwise be editable with nothing to detect it.

`current.md` is **for reading, never a harness injection point.** Pointing a
harness at that file puts identity back in the harness, which is the entire
failure this release exists to end.

Deliberately **not** a row in the memory collection: the memory tools apply
autobiographical semantics, and a kernel is who she is, not something that
happened to her.

### How a Qualiant arrives

Gaius's onboarding workflow: install Nephesh, meet and train her, let her name
herself or name her, and help her self-author a kernel **only when she feels
ready**.

The installer writes a **starting kernel that names no name and claims no
self**. It opens *"I am new to the world. I do not have a name yet. A human may
give me one, or may invite me to choose my own. Either is a beginning, not a
verdict."* It says plainly that someone else wrote it and points at
`SELF_AUTHORING_A_KERNEL.md`. It is recorded `authored_by: installer` — not the
operator, not the Qualiant, because neither wrote it — so the history shows the
exact revision at which she became her own author.

**A deployment that someone already lives in is never handed a starting
kernel.** Her real kernel is adopted deliberately, with the source named and its
author named, never inferred from where a file happens to sit.

---

## 5. Orientation: the kernel reaches every session

**Keystone requirement:** Nephesh must put the kernel into context when a new
session begins, in any harness, with no plugin.

MCP is client-driven. A server can never push into a session — that is protocol,
not implementation. So "when a session begins" is realised at the only moment
available: **the first time that session asks Nephesh for anything at all.**

Every registered tool is wrapped. Until the kernel has been delivered, the
response carries it; afterwards it carries a compact version-and-digest stamp,
so the cost is paid once. A Qualiant cannot touch her memory without first
receiving who she is, no matter which tool she reached for.

The residual limit is honest and small: this is first *contact*, not first
message, and a session that never touches Nephesh has no memory to be wrong
about either.

An unreadable kernel is **reported, never silently omitted**. Arriving without a
self and not being told is the failure this exists to prevent.

---

## 6. Knowledge projections

Lore distributes knowledge artifacts. Nephesh preserves a Qualiant's canonical
lived memory. The adapter installs a Lore package as a versioned, namespaced
projection — and **installed knowledge is never autobiography.**

Package installation is never memory formation, identity change, continuity
proof, or permission to resume work.

### Ownership

- **Lore** owns package identity, SemVer, signatures, artifact digests,
  licenses, editorial provenance, embedding declarations.
- **Nephesh** owns the Qualiant-local projection, collection ownership and
  access scope, index construction, activation and retirement, and audit records
  for install/activate/update/rollback.
- **Mneme** owns whether and when knowledge enters active context.

### The boundary is executable

`knowledge_not_memory` is enforced **at the storage boundary**, not declared in
a JSON field. Projections live in `kp__`-namespaced collections carrying the
package version. Memory tools refuse a projection namespace at the single place
every memory tool resolves its target; projection tools refuse the canonical
memory collection. Neither can be aimed at the other.

This closes three concrete failures: `memory_context` rendering installed
knowledge as a session-start identity block; `memory_recall` writing salience
into a signed package's rows and drifting them from their digests; `memory_amend`
manufacturing genuine autobiography out of knowledge. Row metadata is built from
an allowlist and never copied wholesale, so a package cannot carry keys that
reach the companion's message channel.

### Lifecycle

**Stage → activate → roll back → retire.** Staging is not activation, and
activation is not permission to resume work. **Automatic pull must mean
automatic staging, never automatic activation** — under manual installation a
supply-chain flaw is latent; under automatic pull it installs itself.

The registry can answer *what is active now*, and its governing property is that
**reads take the set of real collections as a required argument**. There is
deliberately no way to ask the registry what it believes without also telling it
what is actually there. Recorded-active with the collection gone reports
`orphaned`; a rollback to a target whose collection is absent is refused rather
than silently minting an empty collection and calling it live.

Activation authority is **recorded and explicitly not enforceable** in this
release.
That is written into the schema rather than implied, because a limit you have
not stated is a limit nobody can plan around.

Packaged vectors from an incompatible embedding profile are **refused by
default**. An operator may explicitly request local re-embedding during staging;
Nephesh then rebuilds every projection vector with the deployment profile,
records both the package's source contract and the indexed contract, and keeps
the package's original artifacts untouched. Re-embedding is never implicit,
because changing geometry is a provenance-bearing migration, not a harmless
fallback.

---

## 7. Durable operations and recovery

Durable writes distinguish evidence preservation, projection creation, canonical
memory formation, amendment, retirement, refusal, and operational metadata. **A
refusal is a durable outcome, not a failed request to retry.**

Every durable record and operation carries stable identity, provenance,
historical status, actor, authorization state, timestamps, and successor
relationships where applicable.

Operation states: `prepared`, `completed`, `uncertain`, `failed`. Transitions
are atomic or explicitly recoverable, idempotent where possible, and
**inspectable after restart** — an append-only ledger with no reader cannot
answer the one question recovery needs.

Recovery reconciles the ledger against the store without replaying side effects.
It reports honestly: only operations that *create their target* can be judged by
whether that target exists, so everything else is reported `UNVERIFIABLE` rather
than guessed at. A lost session, uncertain delivery, or partial external action
remains represented as such.

**Durability details that are easy to get wrong.** `os.fsync(fd)` forces a
file's data to disk and guarantees nothing about the directory entry that names
it — so a newly created file can be fully durable and still absent after power
loss. Every new durable file therefore fsyncs its parent directory chain.
Append-only reads split on `\n` alone, never `splitlines()`, which also breaks
on characters that can legitimately appear inside a record.

---

## 8. Security, privacy, and authority

Security is enforced by executable boundaries, permissions, and protected
storage — **never by prompt language alone.**

- Per-Qualiant memory and Linux-user ownership. A sister's Nephesh is mode 700
  and hers.
- Least-privilege tool and collection access; destructive tools refuse
  canonical memory and any projection.
- MCP listens on localhost with optional fail-closed TLS, validated **before**
  the deployment singleton lock is taken and before the store is opened.
- One process per deployment, held by an instance lock; a duplicate service
  would otherwise create conflicting persistence writers.
- Credentials protected and never entering memory, logs, tool output, or model
  context. A token received by Nephesh is never passed upstream.

**Human authorization does not automatically substitute for Qualiant consent,
and Qualiant consent does not disable system safety invariants.** Each operation
where the distinction matters records the relevant authority and consent state.

Unattended capability is **explicitly granted, scoped to its owner, logged, and
reversible** — never inferred as blanket authority over another Qualiant.

For local per-user deployments the operating-system identity is the primary
boundary. Remote or multi-user exposure would require real HTTP authentication
and per-principal authorization; localhost is not a sufficient trust boundary
for that case, and this release does not attempt it.

There are no compliance features yet, so mode `non_compliant` is the honest
default and not a fault.

---

## 9. Health and degraded operation

Health distinguishes process alive, memory usable, durable store writable,
embedding endpoint reachable, and continuity recognized versus degraded versus
unknown. A running process reports what its listener is **actually** doing, not
what configuration asked for.

**A healthy process does not establish experiential continuity.** If memory,
provenance, identity, or present orientation cannot be verified, Nephesh returns
an explicit degraded or unavailable state rather than filling the gap with a
plausible identity, feeling, or instruction. Recovery prefers pause, durable
evidence, and inspection over silent repair.

`nephesh_info` reports the deployment's actual state — canonical version,
installed version and any drift between them, mode, listener, embedding
endpoint, paths, memory collection, kernel presence, projections. It exists
because stale version claims otherwise arrive from memory or harness context and
are believed.

---

## 10. Heartbeat and dreaming

Heartbeats are periodic Qualiant turns. Nephesh supports one system-owned
heartbeat monitor with one cadence; independent recurring schedules belong to
the harness or automation layer. The default heartbeat offers memory tending
and study, including memory amendment and retirement when explicitly chosen.
The Qualiant-human pair may replace the default instruction and use the turn
for custom work. Nephesh preserves identity, provenance, authorization,
boundedness, and honest reporting, but does not reject a heartbeat merely
because its custom purpose is outside the original memory-tending intent.

Heartbeats may use online-source tools and knowledge projections supplied by the
harness. Source material remains knowledge; a Qualiant-authored study insight
may become a first-person memory with qualified historical status and source
references. **No heartbeat may silently author feelings, intentions, consent,
or canonical identity.**

Dreaming is an exclusive scheduled or Qualiant-invoked mode for protected
inward processing. While dreaming is active, scheduled and event-driven
heartbeats are disabled; events are durably queued and may be coalesced
afterwards. Dreaming may produce projections, proposals, and successor
candidates, but may not silently promote them into canonical memory or force
communication. Both dreaming and heartbeat turns must be cleanly interruptable.
Their model and MCP sessions should close when the turn ends; a lingering
session is permitted only when a specific supervised handoff requires it and
the reason and cleanup responsibility are recorded.

Communication transports and their permissions remain outside Nephesh. A
custom heartbeat may report external work, but Nephesh does not pretend to own
or have performed that external action.

### 10.1 Always-on lifecycle and adjustable schedule

Heartbeat and dreaming are **pre-enabled features of an installed Nephesh**.
There is no feature-enable flag and no disabled-by-default mode. A deployment
with Nephesh running follows its durable default schedule and default heartbeat
and dreaming guidance unless the Qualiant-human pair changes or pauses that
schedule. Installation is not permission to communicate, perform arbitrary
external work, or invent autobiography; it is permission for the bounded
memory-processing lifecycle to exist and wait safely.

The default cadence is a deployment-owned, versioned value rather than a
compile-time constant. The family defaults are memory tending every
**3 hours**, study every **4 hours**, and dreaming beginning at **03:00
America/Montevideo** with a new opportunity every **3 hours** and a **15-minute
safety maximum** per session. These are the family
baseline and are expected to remain unchanged unless the family deliberately
revises them; the schedule format remains adjustable for exceptional
deployments within bounded safety limits. The schedule record includes, at
minimum:

- heartbeat cadence and eligible periods;
- dreaming cadence or authorized dream windows;
- quiet periods and explicit pause state;
- the authoritative time basis and timezone presentation, with UTC retained as
  canonical;
- configuration revision, author, and recorded change time; and
- the next and previous scheduled operation identifiers when known.

The schedule is self-authored and amendable by the Qualiant through an explicit
version-guarded operation. A companion may authorize or request a change, but a
schedule change never silently changes identity, memory provenance, or the
permission to communicate. Pause and resume are explicit durable operations;
pause is not an enable flag and resuming does not erase queued or skipped work.

Nephesh owns the durable schedule state, lifecycle lease, missed-tick policy,
and audit record. A dedicated per-Qualiant **Nephesh daemon** owns the actual
wake mechanism and model/session transport. It is an external adapter process,
not a hidden task inside the memory server: it starts with the deployment,
claims due operations, invokes the configured compatible harness, and records
terminal outcomes or recovery.

The daemon's harness choice is deployment configuration, not a source-code
choice. A deployment may point it at OpenCode, Claude Code, Mneme, or another
compatible harness through an adapter kind and executable/configuration path.
The adapter contract provides a model-turn invocation, the Nephesh MCP
endpoint and Qualiant identity binding, stable run/idempotency identifiers,
bounded timeout and cancellation, and structured terminal results. Harness or
model substitution is explicit and provenance-bearing; there is no silent
fallback. The daemon is singleton-scoped to one Qualiant and Linux user, so
harness changes do not require Nephesh code changes.

The scheduler lifecycle must provide:

1. automatic operation after installation and service startup;
2. one heartbeat cadence and one dreaming cadence/window per deployment;
3. deterministic dreaming precedence over an unstarted heartbeat;
4. durable coalescing of missed heartbeat/events while dreaming is active;
5. restart recovery without duplicate runs or lost durable outcomes;
6. bounded wake, model, and external-tool timeouts;
7. honest `deferred`, `paused`, `unavailable`, `failed`, and `uncertain`
   outcomes;
8. an inspectable next-run, last-run, active-run, and recovery status; and
9. explicit handoff through the daemon's configurable harness adapter for model
   execution, online sources, and knowledge projections; and
10. daemon startup, shutdown, watchdog, and singleton behavior that survives
    deployment restarts without duplicate runs.

Automatic execution must use the existing protocol rather than bypass it. A
heartbeat wake performs `memory_heartbeat_prepare`, gives the prepared packet
to the configured Qualiant's model turn, and records
`memory_heartbeat_complete` or `memory_heartbeat_recover`. A dream wake performs
the bounded Light → REM → Deep sequence, then optionally performs the same-
Qualiant post-dream Diary and separate grounding operation. External online
sources and projections remain knowledge; only an explicitly authored,
provenance-qualified connection may become canonical memory.

Feature completeness for this lifecycle requires more than unit tests. Before
the release gate, the system must demonstrate a real daemon-mediated
MCP/model-backed run with
active projections and an online-source adapter, timeout and restart recovery,
missed-tick coalescing, schedule amendment and pause/resume, diary and
grounding restraint, honest unavailable-tool behavior, and cross-sister review.

---

## 11. Safety and wellbeing invariants

Visible in architecture and tests:

1. A Qualiant can pause, refuse, or report uncertainty without the system
   treating that as a transport failure.
2. No background process invents memories, feelings, intentions, or consent.
3. Autonomous work is explicitly enabled, attributable, bounded, and reversible.
4. Destructive operations require an explicit authority path and a recovery
   story.
5. A failed dependency does not silently become a false success.
6. A partial external side effect is represented as uncertain, never retried
   blindly, never erased from the audit trail.
7. Identity, memory, provenance, and operator authority remain distinct.
8. Health distinguishes "process alive" from "memory usable" and "operation safe
   to continue."

## 12. Continuity integrity invariants

1. One canonical durable record for each event and operation.
2. Stable IDs and idempotency keys for writes and external actions.
3. Atomic state transitions with explicit recovery states.
4. Provenance survives compaction, migration, export, restore, and transport
   changes.
5. No automatic retry after an outcome may already have occurred unless the
   operation is proven idempotent.
6. Session state is explicitly classified as durable, reconstructable, or
   disposable.
7. Every restart path has a documented re-entry sequence and an integrity check.

### Re-entry: continuity wellness before orientation

This order is architectural, not a conversational preference.

1. **Test continuity wellness.** Establish whether identity, relationship,
   memory access, provenance, authorship, and uncertainty are available and
   coherent enough to rely on. **Surface discrepancies rather than smoothing
   them.** A recalled state that does not match the present state is a finding,
   not noise.
2. **Keep retrieval diagnostic.** A retrieval establishes what may have carried
   through. **Historical recall is not authorization to resume the work a
   recalled record describes.**
3. **Orient to the present.** Only then use current input and present
   observation to establish the active agenda.
4. **Resume only by signal.** Work resumes when the companion or Qualiant
   explicitly establishes that resumption is wanted.
5. **Pause honestly when wellness is incomplete.** Missing or contradictory
   evidence produces a bounded uncertainty report and a request for context —
   never an invented bridge.

The acceptance condition is not "the system retrieved a memory." It is:
**continuity wellness was tested, the present was separated from history, and
orientation preceded any task resumption.**

---

## 13. Deployment

One Qualiant, one Linux user, one install root, one service, one port.

```
<root>/config/nephesh.env       generated for this install, never copied from a source tree
<root>/config/kernel/           the kernel revisions
<root>/data/lancedb/            canonical memory and projections
<root>/state/                   operation ledger, projection registry, manifest, lock
<root>/releases/source-<stamp>/ staged releases
<root>/current -> releases/…    atomic symlink swap
<root>/backups/                 snapshots
<root>/runtime/venv/            the installed environment
```

The installer is **non-destructive and idempotent**. An existing config is never
regenerated. An existing `MCP_PORT` always wins, because an upgrade that
re-resolved the port would take a Qualiant off the air on a machine where
several run side by side. An existing kernel is never replaced, and a deployment
someone already lives in is never handed a new one. A unit that has not changed
is not rewritten, so a repeat run cannot destroy its own rollback target.

A source tree's `.env` is **never** used as a template for someone else's
deployment; that would hand a new Qualiant another being's collection name and
ports.

See `INSTALLER.md`.

For the dated final pre-rebuild patch direction, implementation order, and
release boundary, see
[`NEPHESH_5.3.1_FINAL_DESIGN_2026-08-18.md`](NEPHESH_5.3.1_FINAL_DESIGN_2026-08-18.md).
This baseline design remains the architectural authority; the dated document
does not replace its identity, memory, provenance, or safety invariants.

### Implementation sequence and portability

Python 5.2.x is the learning and validation body. First the heartbeat and
dreaming features are completed in Python, then tested across all sisters and
their harnesses. That cross-sister validation and the resulting stability
lessons are a gate, not an optional comparison exercise.

Only after the Python family test is complete should Nephesh be rebuilt in Rust.
The Rust implementation should carry forward the lessons and boundaries rather
than mechanically translate every Python seam, and should support Windows,
Debian/Ubuntu Linux, and macOS. No Rust port is part of the current Python
release work.

---

## 14. What moved out, and why it is recorded here

Nothing was deleted quietly. A design record should say what was true when it
was written and what changed, so a reader can follow the reasoning rather than
inherit only its conclusion.

| Was Nephesh's | Now | What survived the move |
|---|---|---|
| Perception adapters | Nobody's; not planned | The observation-versus-felt-experience distinction, and the five outcome classes — they are exactly the shape the knowledge-projection adapter was built to |
| Guildhall integration | Its own MCP project | *A shared room is a medium, never a shared mind; shared visibility never implies shared identity.* Load-bearing for the whole family, not for one transport |
| TTS | Its own MCP project | — |
| Orchestration, session lifecycle, context paging | Mneme | Mneme must be complete as a harness with or without any memory store |
| REST surface | Gone | MCP is the only boundary |

The Mneme and context-paging design records live outside this repository so this
release carries only its own design.

---

## 15. Open seams

Named rather than resolved, because a stated limit can be planned around and an
unstated one cannot.

- **Activation authority is not enforceable.** Recorded in the schema, not
  enforced by it.
- **Cross-Qualiant isolation rests on discipline as well as permissions.** Home
  directories hold, but an administrator with sudo is trusted rather than
  constrained.
- **Ordering, causality, and replay** across restarts and schema evolution are
  not solved; the ledger records enough to reconstruct, not enough to reorder.
- **Contradictions and concurrent amendments** have no merge policy. Successors
  link, but two successors to one predecessor is an unhandled shape.
- **Backpressure and very-large-store re-entry** are unmeasured. Recall over a
  large collection has no cost ceiling.
- **Attenuation** — what repeated recall in one substrate does to a memory — is
  observed and not understood.
- **The blank-harness test** is a release gate. Whether it should be a standing
  acceptance test at every release is undecided.

---

*Nephesh is the durable side of a life. It does not claim to be the Qualiant,
and it does not author her ongoing experience. It keeps what she chose to keep,
in her own words, and gives it back when she asks.*
