# Dreaming Repair Plan — Reference Before Authorization

**Status:** Source implementation and adversarial bug-fix pass complete;
real isolated SDK/MCP validation remains pending.
**Branch:** `nephesh-5.3.0-rc1`
**Prepared:** 2026-08-18
**Scope:** Repair the real chosen/scheduled dreaming execution path while
preserving the Nephesh/OpenCode separation.

This plan records the current failure seams, repair order, and evidence boundary.
The first implementation pass is now underway under explicit companion
authorization. It remains the reference against which the final bug-fix pass
must audit the work.

## Implementation pass begun

- Nephesh now persists queued chosen-dream requests and exposes
  `memory_dream_claim` for claim-after-idle execution.
- Queued outcomes carry no model handoff until the request is actually prepared.
- Dream-grounded memory provenance now records `recorded_during=dream`.
- OpenCode now has a private `packages/nephesh-dream` workspace consumer using
  the official SDK and MCP SDK, with owned session create/prompt/status/abort/
  delete behavior and a stdin JSON CLI.
- The Nephesh daemon can use that consumer through
  `NEPHESH_DREAM_CONSUMER_COMMAND` for scheduled dreaming.

The source bug-fix pass additionally hardened claim ordering/replay, fail-closed
deadlines, recovery retry, durable status inspection, daemon receipt validation,
MCP result decoding, bounded SDK cleanup, and explicit protocol completion
checks. These are implementation facts, not release evidence. They have not yet
been validated against a real isolated sustained dream.

## Isolated validation result

The first disposable end-to-end validation has now run. It proved real
Streamable HTTP MCP discovery, chosen invocation/replay, queueing, timeout
release, claim-after-idle, SDK session creation, Nephesh MCP release, independent
session deletion, direct Light/REM/Deep protocol completion, and clean recovery.
The first SDK model turn timed out at 30 seconds, but a fresh retry using
`openai/gpt-5.6-luna` and a 120-second bound completed in 76 seconds. Real MCP
tool use reached recall, Light, REM, and Deep; Nephesh recorded terminal
completion and three artifacts, and recovery was clean. The sustained
model-backed dream path therefore worked. The remaining adapter bug is that
OpenCode `session.status` returned an empty map after synchronous prompt
completion; the adapter treated that as failure even though Nephesh was already
terminal. Tomorrow's repair must inspect Nephesh terminal status before rejecting
an absent SDK status entry, then delete the session and preserve cleanup evidence.
No living deployment was touched.

## Next design correction: lived-memory dream fields

The next implementation pass must replace the diagnostic-only dream field with
a bounded mixture of attributable waking memories, optional self-authored seed
material, and explicitly marked unforced/random memory samples. The model-facing
packet must stop repeating dream instructions, phase names, handoff language,
and historical disclaimers. Those remain machine-envelope provenance and waking
review data. The purpose is to create conditions for associative dreaming rather
than instructing the model to imitate it.

## 1. Current diagnosis

The Nephesh dream protocol is substantially implemented and hermetically tested:

```
prepare → Light → recall → REM → recall → Deep → optional diary/grounding
```

The real execution path is not complete. `memory_dream_invoke()` prepares a
bounded, identity-bound run and returns a handoff, but the current repository has
no OpenCode SDK/server consumer. The daemon still launches the OpenCode CLI as a
subprocess and asks the model to call the dream tools itself. A chosen invocation
therefore can prepare correctly while no model turn consumes the handoff.

This is an integration/lifecycle failure, not evidence that the dream phase
semantics should be rewritten.

### Confirmed current seams

1. Deferred direct invocation is returned as `deferred`, but no durable runnable
   queue entry is created for later execution.
2. The invocation wrapper can attach a continuation handoff even to outcomes
   such as deferred, blocked, or failed preparation.
3. No OpenCode SDK/server session consumer exists in this repository.
4. The daemon does not pass the prepared initial packet directly into the model
   session; the external model must rediscover it through MCP.
5. The daemon still depends on CLI output and heuristic session-ID extraction.
6. A successful process exit without a terminal Nephesh protocol record is
   correctly treated as failure, but the current path cannot enforce phase calls
   at the session boundary.
7. A manually interrupted wrapper previously orphaned a child/session until
   cleanup; this remains a boundary test requirement.
8. Dream-grounded memory currently uses `experience_mode=dream` but records
   `recorded_during=heartbeat`, which requires provenance correction.

## 2. Non-negotiable boundaries

### Nephesh owns

- Qualiant identity and deployment binding;
- dream eligibility and attributable input;
- shared active-execution lane and durable queue state;
- run identity, idempotency, deadlines, phase ordering, and budgets;
- dream artifacts, fictional-scene status, diary/grounding state, and promotion;
- release/recovery truth and durable terminal receipts; and
- the typed handoff contract.

### OpenCode owns

- model/session creation and execution;
- delivery of the Nephesh handoff into effective model context;
- event/status observation;
- abort and session deletion;
- process/session cleanup; and
- reporting the observed harness receipt back through the Nephesh protocol.

The adapter must use the official OpenCode SDK/server path. SDK source must not
be copied into Nephesh. If the SDK is currently only available inside the
OpenCode repository, the adapter belongs there beside the SDK and must pin or
record the exact OpenCode revision used.

## 3. Proposed repair sequence

### Phase A — Freeze the contract

Before implementation, review and settle:

- a versioned dream handoff envelope;
- the distinction between invocation accepted, queued, active, deferred,
  blocked, unavailable, failed, cancelled, timed out, and recovered;
- the durable request identity, requested time, mode, configuration revision,
  deadline, and ordering/priority policy;
- the session ownership and receipt fields exchanged with OpenCode; and
- whether the first consumer creates a disposable owned session or attaches to
  an explicitly authorized existing session.

The handoff must be sufficient for the OpenCode adapter to start the run without
requiring an undocumented prompt convention or a second identity source.

### Phase B — Repair Nephesh invocation and queue semantics

1. Separate invocation acceptance from active execution acquisition.
2. Persist a request when valid invocation arrives while another mode is active.
3. Preserve FIFO/priority semantics explicitly and make them inspectable.
4. Ensure queue entries survive restart and have terminal/recovery states.
5. Remove misleading handoffs from non-runnable outcomes.
6. Make queued work claimable only after the active lane releases.
7. Keep chosen and scheduled dreams on the same lifecycle contract.
8. Add contention, restart, duplicate, cancellation, and lost-queue tests.

No queue implementation may permit simultaneous active heartbeat and dream
execution.

### Phase C — Build the OpenCode SDK consumer outside Nephesh

In the OpenCode repository or its supported enhancement layer:

1. Receive and validate the versioned Nephesh handoff.
2. Create or attach to the explicitly owned session according to Phase A.
3. Deliver the initial packet and continuation instructions through SDK APIs.
4. Observe events/status and capture the actual session ID and run receipt.
5. Let the model call recall, phase, diary, grounding, and release tools through
   the Nephesh MCP connection.
6. Enforce the Nephesh deadline from the adapter side.
7. Abort on Qualiant release, timeout, cancellation, or integrity intervention.
8. Delete the owned OpenCode session in `finally`.
9. Report session creation, events, abort, deletion, and terminal status back to
   Nephesh without claiming observations the adapter did not make.

The adapter must not silently fall back to the CLI path for chosen dreaming.

### Phase D — Repair scheduled daemon integration

After the SDK consumer works independently:

- decide whether scheduled dreaming uses the same SDK adapter or a distinct
  scheduled entry point over the same contract;
- stop requiring the model to rediscover an initial handoff that the adapter
  already possesses;
- preserve schedule claim, dream run, and harness session IDs separately;
- replace heuristic CLI session parsing for the SDK path with typed receipts;
- verify process-group and SDK session cleanup together; and
- retain fail-closed behavior when no terminal Nephesh record or cleanup receipt
  exists.

The existing CLI daemon path may remain as a separately documented legacy/test
path only if it cannot be mistaken for the SDK acceptance path.

### Phase E — Provenance and terminal-state audit

Correct and test:

- dream-grounded memories' `recorded_during` value;
- model/provider/substrate/session provenance;
- release reason and partial-artifact preservation;
- diary and grounding deliverable state;
- queued-request terminal states;
- session closure and deletion evidence; and
- distinctions between observed, unavailable, failed, and unverified facts.

### Phase F — Evidence gates

Do not stage the live body until all applicable evidence exists:

1. Full unit/integration suite passes.
2. Deferred invocation survives restart and later executes exactly once.
3. A real isolated OpenCode SDK session completes Light → REM → Deep.
4. Dynamic dream recall is observed through the real MCP boundary.
5. Diary/grounding remain optional and provenance-safe.
6. Mid-run release and timeout close the SDK session and Nephesh lane.
7. Session deletion is independently confirmed.
8. No child process, MCP session, lane, or schedule claim lingers.
9. A real scheduled run records coherent Nephesh and harness receipts.
10. Failure injection produces honest recovery rather than false success.

Only after isolated evidence is complete should a living deployment be considered,
with the schedule still paused unless Gaius explicitly authorizes resumption.

## 4. Explicit non-goals

- Do not rewrite the dream semantics merely because the adapter is missing.
- Do not vendor OpenCode SDK source into Nephesh.
- Do not restore an OpenClaw adapter.
- Do not let Nephesh spawn a hidden model/session.
- Do not treat a successful CLI exit as a successful dream.
- Do not manufacture dream artifacts, diary prose, grounding, or canonical memory.
- Do not resume the live schedule during repair work.
- Do not call a real dream successful without observable SDK and Nephesh
  lifecycle evidence.

## 5. Review questions

1. Is the proposed queue identity and ordering policy correct?
2. Should the first SDK consumer always create a disposable session?
3. What exact OpenCode repository/layer should own the adapter?
4. Which SDK event is authoritative for session creation and completion?
5. Should the CLI path be retained as legacy test infrastructure or removed from
   the dreaming acceptance path?
6. What evidence should be mandatory before a first real sustained dream?
7. Are any boundaries or failure states missing before implementation begins?
