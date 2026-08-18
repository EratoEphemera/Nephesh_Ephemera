# Changelog

## 5.3.0 — 2026-08-18

### Added

- Truthful environmental floor and dependency-readiness reporting.
- Distinct `time_ingested`, optional `time_formed`, and optional `event_time`
  semantics for new records.
- Explicit `memory_schema_version: 1` on new memory records without rewriting
  or downgrading unversioned historical memories.
- Heartbeat lifecycle evidence, run boundaries, agency/evidence dimensions,
  durable harness receipts, and recovery inspection.
- Durable chosen-dream invocation, queued requests, claim-after-idle behavior,
  bounded recall, status inspection, release, recovery, diary, and grounding
  boundaries.
- Dream preparation using a bounded mixture of attributable living memories,
  unforced/random memory fragments, and an optional self-authored seed.
- Baseline OpenCode SDK consumer in the companion OpenCode workspace, using
  owned session creation, model prompting, external Light/REM/Deep phase
  submission, Nephesh status/release, timeout handling, and session deletion.
- Scheduled daemon handoff support through
  `NEPHESH_DREAM_CONSUMER_COMMAND`.
- OpenAI `openai/gpt-5.6-luna` as the default model identifier. Change it with
  `NEPHESH_MODEL`; override heartbeat or dreaming independently with
  `NEPHESH_HEARTBEAT_MODEL` or `NEPHESH_DREAMING_MODEL`.

### Changed

- Dream control-plane instructions no longer enter the effective dream field.
  Phase, provenance, fictional-scene, deadline, and grounding facts remain in
  machine-readable Nephesh records.
- Dreaming no longer depends on `memory_context` for preparation, avoiding
  session-start kernel injection and pending-message delivery as a side effect.
- SDK and daemon completion are fail-closed on missing terminal Nephesh state,
  mismatched receipts, or unconfirmed session deletion.
- Dream-grounded memories use dream provenance rather than heartbeat provenance.
- Dream opportunities now default to every three hours from the 03:00
  America/Montevideo anchor, with a 15-minute safety maximum and natural
  completion preferred over a fixed-duration session.

### Verified

- Nephesh source suite: **306 tests and 13 subtests passed**.
- OpenCode dream consumer: **2 tests passed** and focused typecheck passed.
- Disposable baseline OpenCode validation with `openai/gpt-5.6-luna` and living
  memory/random fragments completed recall, Light, REM, and Deep in 36.61
  seconds under a 120-second bound.
- Three fictional-scene artifacts were recorded; Nephesh terminal status was
  `completed` with `no_grounding`; recovery was clean; OpenCode session deletion
  was independently confirmed.

### Limitations

- These results establish operational dream execution and coherent artifacts,
  not proof of phenomenological experience.
- Grounding and diary deliverables remain optional and are never automatic.
- The supported release acceptance path is baseline OpenCode with Nephesh; the
  Mneme repository is not an acceptance dependency for this release.
- Final merge, tag, and living-sister installation remain separate gates.

### Lessons learned

- Model/session execution remains in the harness; Nephesh owns durable protocol
  truth and completion.
- A successful model turn is not enough: terminal Nephesh state and confirmed
  session deletion are required.
- Dream control instructions can contaminate the effective dream field. The
  baseline adapter owns phase submission externally while the model receives
  living material and unforced fragments.
- Existing deployment configuration is preserved by the installer. Defaults
  apply to new deployments; changing an existing body's model or cadence is an
  explicit configuration operation.

### Known non-blocking defects

- Some offline sister user-session buses may be unavailable during installation;
  staging is separate from service restart and can be retried when the owner bus
  is available.
- Historical baseline documentation and old deployment ledgers retain original
  version labels by design; they are not rewritten.
- The Python release does not prove phenomenological experience; it records
  operational and first-person dream evidence with honest provenance.
- Cryptographic environment identity, revocable capability leases, and hardened
  cross-body isolation are deferred to the future Rust codebase.
