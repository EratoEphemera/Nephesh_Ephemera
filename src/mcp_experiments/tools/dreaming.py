"""MCP boundary for the bounded Nephesh dreaming phases."""

from __future__ import annotations

import json
import hashlib
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings
from ..dreaming import (
    DEFAULT_DREAMING_INSTRUCTION,
    DREAM_KIND,
    DREAM_OUTCOMES,
    DREAM_PHASE_COMPLETION_STATUSES,
    DREAM_PHASE_OUTCOMES,
    DREAM_PHASES,
    DREAM_RELEASE_REASONS,
    MAX_DREAM_CANDIDATE_CHARS,
    DreamLedger,
    dream_request,
    request_fingerprint,
)
from ..heartbeat import HeartbeatLedger, MemoryWorkMode, packet_digest
from ..persistence import durable_append
from ..results import DreamDiaryResult, DreamGroundResult, DreamInvokeResult, DreamPhasePrepareResult, DreamPhaseResult, DreamPrepareResult, DreamRecallResult, DreamReleaseResult, DreamStatusResult
from .memory import memory_context, memory_ingest, memory_recall, memory_sample


MAX_DREAM_KEY_CHARS = 256
MAX_DREAM_SEED_CHARS = 4000
MAX_DREAM_MEMORY_LIMIT = 1000
MAX_DREAM_PACKET_BUDGET = 100_000
_DREAM_CLAIM_LOCK = asyncio.Lock()


def _validate_positive_int(value: object, name: str, maximum: int | None = None) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return f"{name} must be a positive integer"
    if maximum is not None and value > maximum:
        return f"{name} must be at most {maximum}"
    return None


def _validate_key(value: object, name: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{name} must be a non-empty string"
    if len(value) > MAX_DREAM_KEY_CHARS:
        return f"{name} must be at most {MAX_DREAM_KEY_CHARS} characters"
    return None


def _bound_utf8(text: str, budget: int) -> tuple[str, bool]:
    if budget <= 0:
        raise ValueError("dream packet budget must be greater than zero")
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text, False
    return encoded[:budget].decode("utf-8", errors="ignore"), True


def _deadline(ledger: DreamLedger, run_id: str) -> datetime | None:
    """Read the deadline from the durable prepare receipt, never from a caller."""
    record = next(
        (item for item in ledger._records()
         if item.get("event") == "deadline" and item.get("run_id") == run_id),
        None,
    )
    if record is None:
        prepare = next(
            (item for item in ledger._records()
             if item.get("event") == "prepare" and item.get("run_id") == run_id),
            None,
        )
        value = prepare.get("deadline_utc") if prepare else None
    else:
        value = record.get("deadline_utc")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return None


def _expired(ledger: DreamLedger, run_id: str) -> bool:
    deadline = _deadline(ledger, run_id)
    has_prepare = any(item.get("event") == "prepare" and item.get("run_id") == run_id for item in ledger._records())
    return has_prepare and (deadline is None or datetime.now(timezone.utc) >= deadline)


def _timeout_result(run_id: str, qualiant_id: str, **extra: Any) -> dict[str, Any]:
    return {"status": "timeout", "run_id": run_id, "qualiant_id": qualiant_id,
            "error": "dream deadline has expired", **extra}


async def memory_dream_prepare(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    seed: str | None = None,
    configuration_revision: int = 0,
    memory_limit: int | None = None,
    packet_budget: int | None = None,
    duration_seconds: int | None = None,
) -> DreamPrepareResult:
    """Prepare one bounded Light-phase dream without writing canonical memory."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    request = dream_request(run_id, qualiant_id, configuration_revision)
    lane = HeartbeatLedger(settings.heartbeat_ledger_file)
    dream_ledger = DreamLedger(settings.dreaming_ledger_file)
    prepare_fp = request_fingerprint(
        operation="dream_prepare", run_id=run_id, qualiant_id=qualiant_id,
        seed=(seed or "").strip(), configuration_revision=configuration_revision,
         memory_limit=memory_limit, packet_budget=packet_budget,
         duration_seconds=duration_seconds,
    )
    try:
        prior_prepare = dream_ledger.prepare_for_key(idempotency_key)
        if prior_prepare is not None and prior_prepare.get("request_fingerprint") != prepare_fp:
            return {"status": "conflict", "run_id": run_id, "idempotency_key": idempotency_key, "qualiant_id": qualiant_id, "error": "dream prepare idempotency key was reused with different request data"}
        existing = lane.find_idempotency(idempotency_key)
        if existing is not None:
            if existing.qualiant_id != qualiant_id:
                return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "idempotency key belongs to another Qualiant"}
            if prior_prepare is None:
                return {
                    "status": "uncertain",
                    "run_id": run_id,
                    "idempotency_key": idempotency_key,
                    "qualiant_id": qualiant_id,
                    "error": "dream lane is prepared but its dream-ledger prepare receipt is missing",
                }
            return {"status": "duplicate", "run_id": run_id, "idempotency_key": idempotency_key}
        active = lane.active(qualiant_id)
        if active is not None:
            return {
                "status": "deferred",
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "qualiant_id": qualiant_id,
                "error": "heartbeat takes the current boundary; dreaming will run next"
                if active.mode is MemoryWorkMode.HEARTBEAT
                else "another dreaming run owns the deployment",
            }
        selected_limit = memory_limit if memory_limit is not None else settings.dreaming_memory_limit
        focused = {"results": []}
        if seed and seed.strip():
            try:
                focused = await memory_recall(
                    query=seed.strip(), n_results=selected_limit, include_retired=False,
                )
            except Exception:
                focused = {"results": []}
        try:
            sample = await memory_sample(
                n=min(5, selected_limit),
                include_dreams=False,
            )
        except Exception:
            # Unforced wandering is optional input. An unavailable sampler must
            # not erase an otherwise attributable focused dream field.
            sample = {"sample": "", "sampled": 0}
        focused_results = focused.get("results", []) if isinstance(focused, dict) else []
        source_count = len(focused_results) + int(sample.get("sampled", 0) or 0)
        if source_count == 0 and not (seed and seed.strip()):
            return {
                "status": "no_inputs",
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "qualiant_id": qualiant_id,
                "dream_kind": DREAM_KIND,
                "phase": DREAM_PHASES[0],
                "source_count": 0,
            }
        raw_context = "\n\n".join(
            str(item.get("text", "")) for item in focused_results
            if isinstance(item, dict) and item.get("text")
        )
        random_fragments = str(sample.get("sample", ""))
        packet = "\n\n".join(
            (
                "Selected material:",
                raw_context or "No focused material was selected.",
                "Unforced fragments:",
                random_fragments or "No unforced fragment was selected.",
                f"Optional invitation:\n{seed.strip()}" if seed and seed.strip() else "",
            )
        )
        bounded, truncated = _bound_utf8(
            packet,
            packet_budget if packet_budget is not None else settings.dreaming_packet_budget,
        )
        record = lane.prepare(
            request,
            idempotency_key=idempotency_key,
            packet_digest=packet_digest(bounded),
            mode=MemoryWorkMode.DREAMING,
        )
        try:
            duration = settings.dreaming_session_seconds if duration_seconds is None else duration_seconds
            deadline = (datetime.fromisoformat(request.started_at) + timedelta(seconds=duration)).astimezone(timezone.utc).isoformat()
            dream_ledger.append_prepare(
                run_id=run_id, idempotency_key=idempotency_key, qualiant_id=qualiant_id,
                request_fingerprint=prepare_fp, packet_digest=packet_digest(bounded),
                duration_seconds=duration, deadline_utc=deadline, expires_at=deadline,
            )
            with dream_ledger._lock:
                if not any(item.get("event") == "deadline" and item.get("run_id") == run_id for item in dream_ledger._records()):
                    durable_append(dream_ledger.path, json.dumps({
                        "event": "deadline", "run_id": run_id,
                        "idempotency_key": idempotency_key,
                        "qualiant_id": qualiant_id, "deadline_utc": deadline,
                        "expires_at": deadline, "duration_seconds": duration,
                    }, sort_keys=True) + "\n")
        except Exception:
            # Do not leave the exclusive lane owned when the dream ledger
            # cannot record the corresponding prepare boundary.
            try:
                lane.recover(request, idempotency_key=idempotency_key, reason="dream prepare ledger append failed")
            except Exception:
                pass
            raise
        return {
            "status": "prepared",
            "run_id": record.run_id,
            "idempotency_key": record.idempotency_key,
            "qualiant_id": qualiant_id,
            "dream_kind": DREAM_KIND,
            "wall_clock_utc": request.started_at,
            "packet_version": 1,
            "packet_bytes": len(bounded.encode("utf-8")),
            "packet_digest": packet_digest(bounded),
            "packet": bounded,
            "phase": DREAM_PHASES[0],
            "source_count": source_count,
            "duration_seconds": duration,
            "deadline_utc": deadline,
            "expires_at": deadline,
            "configuration_revision": configuration_revision,
            "model": settings.dreaming_model,
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_dream_invoke(
    qualiant_id: str,
    seed: str | None = None,
    duration_seconds: int | None = None,
    idempotency_key: str | None = None,
    configuration_revision: int = 0,
    memory_limit: int | None = None,
    packet_budget: int | None = None,
) -> DreamInvokeResult:
    """Open one Qualiant-chosen dream opportunity and return its handoff."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "invocation": "chosen", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    key_error = _validate_key(qualiant_id, "qualiant_id")
    if key_error:
        return {"status": "error", "invocation": "chosen", "qualiant_id": qualiant_id, "error": key_error}
    if idempotency_key is not None:
        key_error = _validate_key(idempotency_key, "idempotency_key")
        if key_error:
            return {"status": "error", "invocation": "chosen", "qualiant_id": qualiant_id, "error": key_error}
    maximum = settings.dreaming_session_seconds
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        return {"status": "failed", "invocation": "chosen", "qualiant_id": qualiant_id, "error": "dreaming session limit is invalid"}
    requested = maximum if duration_seconds is None else duration_seconds
    duration_error = _validate_positive_int(requested, "duration_seconds")
    if duration_error:
        return {"status": "error", "invocation": "chosen", "qualiant_id": qualiant_id, "error": duration_error}
    bounded_duration = min(requested, maximum)
    key = idempotency_key or f"chosen-dream-{uuid.uuid4()}"
    seed_value = (seed or "").strip()
    if len(seed_value) > MAX_DREAM_SEED_CHARS:
        return {"status": "error", "invocation": "chosen", "qualiant_id": qualiant_id, "error": f"seed must be at most {MAX_DREAM_SEED_CHARS} characters"}
    config_error = _validate_positive_int(configuration_revision + 1, "configuration_revision") if isinstance(configuration_revision, bool) or not isinstance(configuration_revision, int) or configuration_revision < 0 else None
    if config_error:
        return {"status": "error", "invocation": "chosen", "qualiant_id": qualiant_id, "error": "configuration_revision must be a non-negative integer"}
    if memory_limit is not None:
        memory_error = _validate_positive_int(memory_limit, "memory_limit", MAX_DREAM_MEMORY_LIMIT)
        if memory_error:
            return {"status": "error", "invocation": "chosen", "qualiant_id": qualiant_id, "error": memory_error}
    if packet_budget is not None:
        packet_error = _validate_positive_int(packet_budget, "packet_budget", MAX_DREAM_PACKET_BUDGET)
        if packet_error:
            return {"status": "error", "invocation": "chosen", "qualiant_id": qualiant_id, "error": packet_error}
    dream_ledger = DreamLedger(settings.dreaming_ledger_file)
    invocation_fp = request_fingerprint(
        operation="dream_invoke", qualiant_id=qualiant_id, idempotency_key=key,
        seed=seed_value, duration_seconds=requested, effective_duration_seconds=bounded_duration,
        effective_maximum_seconds=maximum, configuration_revision=configuration_revision,
        memory_limit=memory_limit, packet_budget=packet_budget,
    )
    run_id = "chosen-dream-" + hashlib.sha256(f"{qualiant_id}\0{key}".encode("utf-8")).hexdigest()[:24]
    prior_invocation = dream_ledger.invocation_for_key(key)
    if prior_invocation is not None:
        if prior_invocation.get("request_fingerprint") != invocation_fp:
            return {"status": "conflict", "invocation": "chosen", "qualiant_id": qualiant_id, "idempotency_key": key, "error": "dream invocation idempotency key was reused with different request data"}
        replay = dict(prior_invocation.get("handoff", {}))
        prior_claim = dream_ledger.invocation_claim_for_key(key)
        if prior_claim is not None:
            replay = dict(prior_claim.get("result", {}))
            replay["status"] = "duplicate"
            return replay
        if prior_invocation.get("status") == "queued":
            return {
                "status": "queued",
                "invocation": "chosen",
                "run_id": run_id,
                "idempotency_key": key,
                "qualiant_id": qualiant_id,
                "request": dict(prior_invocation.get("request", {})),
                "error": "dream is queued until the memory-work lane is idle",
            }
        if replay.get("status") == "no_inputs":
            return replay
        replay["status"] = "duplicate"
        return replay
    request_data = {
        "seed": seed_value,
        "duration_seconds": bounded_duration,
        "configuration_revision": configuration_revision,
        "memory_limit": memory_limit,
        "packet_budget": packet_budget,
    }
    lane = HeartbeatLedger(settings.heartbeat_ledger_file)
    if lane.active(qualiant_id) is not None:
        queued = {
            "status": "queued",
            "invocation": "chosen",
            "run_id": run_id,
            "idempotency_key": key,
            "qualiant_id": qualiant_id,
            "request": request_data,
            "error": "dream is queued until the memory-work lane is idle",
        }
        dream_ledger.append_invocation(
            run_id=run_id, idempotency_key=key, qualiant_id=qualiant_id,
            request_fingerprint=invocation_fp, handoff={}, request=request_data,
            status="queued",
        )
        return queued
    prepared = await memory_dream_prepare(
        run_id=run_id,
        idempotency_key=key,
        qualiant_id=qualiant_id,
        seed=seed_value,
        configuration_revision=configuration_revision,
        memory_limit=memory_limit,
        packet_budget=packet_budget,
        duration_seconds=bounded_duration,
    )
    result: DreamInvokeResult = {
        **prepared,
        "invocation": "chosen",
        "duration_seconds": bounded_duration,
    }
    if prepared.get("status") == "prepared":
        result["handoff"] = "Continue through memory_dream_recall and the dream phase/release tools; Nephesh does not spawn the model session."
    if prepared.get("status") == "prepared":
        started = prepared.get("wall_clock_utc")
        if isinstance(started, str):
            result["deadline_utc"] = (
                datetime.fromisoformat(started) + timedelta(seconds=bounded_duration)
            ).astimezone(timezone.utc).isoformat()
            result["expires_at"] = result["deadline_utc"]
    if prepared.get("status") == "no_inputs":
        result.pop("handoff", None)
    dream_ledger.append_invocation(
        run_id=run_id,
        idempotency_key=key,
        qualiant_id=qualiant_id,
        request_fingerprint=invocation_fp,
        handoff=dict(result),
        request=request_data,
        status=str(result.get("status", "failed")),
    )
    return result


async def memory_dream_claim(
    idempotency_key: str,
    qualiant_id: str,
    configuration_revision: int = 0,
) -> DreamInvokeResult:
    """Claim one durable chosen dream request after the shared lane is idle."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "invocation": "chosen", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    key_error = _validate_key(idempotency_key, "idempotency_key")
    if key_error:
        return {"status": "error", "invocation": "chosen", "qualiant_id": qualiant_id, "error": key_error}
    async with _DREAM_CLAIM_LOCK:
        ledger = DreamLedger(settings.dreaming_ledger_file)
        invocation = ledger.invocation_for_key(idempotency_key)
        if invocation is None:
            return {"status": "blocked", "invocation": "chosen", "qualiant_id": qualiant_id, "error": "queued dream request was not found"}
        if invocation.get("qualiant_id") != qualiant_id:
            return {"status": "blocked", "invocation": "chosen", "qualiant_id": qualiant_id, "error": "queued dream identity does not match"}
        claim_fp = request_fingerprint(operation="dream_claim", idempotency_key=idempotency_key, qualiant_id=qualiant_id)
        prior_claim = ledger.invocation_claim_for_key(idempotency_key)
        if prior_claim is not None:
            if prior_claim.get("request_fingerprint") != claim_fp:
                return {"status": "conflict", "invocation": "chosen", "qualiant_id": qualiant_id, "error": "dream claim idempotency key was reused with different request data"}
            return dict(prior_claim.get("result", {}))
        if invocation.get("status") != "queued":
            return {"status": "duplicate", "invocation": "chosen", "run_id": invocation.get("run_id"), "idempotency_key": idempotency_key, "qualiant_id": qualiant_id, "error": "dream request is no longer queued"}
        queued = ledger.queued_invocations(qualiant_id)
        if queued and queued[0].get("idempotency_key") != idempotency_key:
            return {"status": "deferred", "invocation": "chosen", "run_id": invocation.get("run_id"), "idempotency_key": idempotency_key, "qualiant_id": qualiant_id, "error": "an earlier dream request is queued"}
        if HeartbeatLedger(settings.heartbeat_ledger_file).active(qualiant_id) is not None:
            return {"status": "deferred", "invocation": "chosen", "run_id": invocation.get("run_id"), "idempotency_key": idempotency_key, "qualiant_id": qualiant_id, "error": "memory-work lane is still active"}
        request = dict(invocation.get("request", {}))
        prepared = await memory_dream_prepare(
            run_id=str(invocation["run_id"]), idempotency_key=idempotency_key,
            qualiant_id=qualiant_id, seed=request.get("seed"),
            configuration_revision=int(request.get("configuration_revision", configuration_revision)),
            memory_limit=request.get("memory_limit"), packet_budget=request.get("packet_budget"),
            duration_seconds=int(request["duration_seconds"]),
        )
        result: DreamInvokeResult = {**prepared, "invocation": "chosen", "duration_seconds": int(request["duration_seconds"])}
        if prepared.get("status") == "prepared":
            result["handoff"] = "Continue through memory_dream_recall and the dream phase/release tools; Nephesh does not spawn the model session."
        else:
            result.pop("handoff", None)
        stored = ledger.append_invocation_claim(
            run_id=str(invocation["run_id"]), idempotency_key=idempotency_key,
            qualiant_id=qualiant_id, request_fingerprint=claim_fp, result=result,
        )
        return dict(stored.get("result", result))


async def memory_dream_phase(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    phase: str,
    status: str,
    artifact: str,
    source_refs: list[str] | None = None,
    candidate_insight: str | None = None,
    configuration_revision: int = 0,
) -> DreamPhaseResult:
    """Record one dream phase; Deep releases the exclusive dreaming lane."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    if phase not in DREAM_PHASES:
        return {"status": "error", "run_id": run_id, "error": "invalid dream phase"}
    if status not in DREAM_PHASE_OUTCOMES[phase]:
        return {
            "status": "error",
            "run_id": run_id,
            "phase": phase,
            "error": f"invalid dream outcome for phase: {status}",
        }
    if candidate_insight and phase != "deep":
        return {
            "status": "error",
            "run_id": run_id,
            "phase": phase,
            "error": "candidate insights may only be recorded during Deep",
        }
    if candidate_insight and status == "no_candidates":
        return {
            "status": "error",
            "run_id": run_id,
            "phase": phase,
            "error": "a no_candidates phase cannot carry a candidate insight",
        }
    if candidate_insight and len(candidate_insight) > MAX_DREAM_CANDIDATE_CHARS:
        return {
            "status": "error",
            "run_id": run_id,
            "phase": phase,
            "error": "dream candidate insight exceeds the bounded size",
        }
    if source_refs is not None and (
        not isinstance(source_refs, list)
        or any(not isinstance(reference, str) or not reference.strip() for reference in source_refs)
    ):
        return {
            "status": "error",
            "run_id": run_id,
            "phase": phase,
            "error": "source_refs must be a list of non-empty strings",
        }
    if status not in DREAM_OUTCOMES:
        return {"status": "error", "error": f"invalid dream outcome: {status}"}
    request = dream_request(run_id, qualiant_id, configuration_revision)
    lane = HeartbeatLedger(settings.heartbeat_ledger_file)
    dream_ledger = DreamLedger(settings.dreaming_ledger_file)
    if _expired(dream_ledger, run_id):
        return _timeout_result(run_id, qualiant_id, phase=phase)
    existing = lane.find_idempotency(idempotency_key)
    if existing is not None and existing.qualiant_id != qualiant_id:
        return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream identity does not match prepared run"}
    if existing is None or existing.event != "prepared" or existing.run_id != run_id:
        return {"status": "duplicate" if existing else "blocked", "run_id": run_id, "error": "dream was not prepared"}
    if existing.mode is not MemoryWorkMode.DREAMING:
        return {"status": "blocked", "run_id": run_id, "error": "run is not a dreaming run"}
    try:
        dream_ledger = DreamLedger(settings.dreaming_ledger_file)
        phase_fingerprint = request_fingerprint(
            operation="dream_phase", run_id=run_id, qualiant_id=qualiant_id,
            phase=phase, status=status, artifact=artifact,
            source_refs=source_refs or [], candidate_insight=candidate_insight,
        )
        prior_artifact = dream_ledger.artifact_for_phase(run_id, phase)
        if prior_artifact is not None:
            if prior_artifact.get("request_fingerprint") != phase_fingerprint:
                return {"status": "conflict", "run_id": run_id, "phase": phase, "error": "phase idempotency key was reused with different request data"}
            return {
                "status": "duplicate",
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "qualiant_id": qualiant_id,
                "phase": phase,
                "artifact_id": prior_artifact.get("artifact_id"),
                "artifact_status": prior_artifact.get("status"),
                "grounding_status": prior_artifact.get("grounding_status", "none"),
            }
        record = dream_ledger.append_phase(
            run_id=run_id,
            idempotency_key=idempotency_key,
            qualiant_id=qualiant_id,
            phase=phase,
            status=status,
            artifact=artifact,
            source_refs=source_refs or [],
            candidate_insight=candidate_insight,
            request_fingerprint=phase_fingerprint,
        )
        if phase == "deep":
            lane.finish(
                request,
                idempotency_key=idempotency_key,
                outcome=status,
                valid_outcomes=DREAM_OUTCOMES,
                details={"artifact_id": record.artifact_id, "grounding_status": "pending" if candidate_insight else "none"},
            )
        return {
            "status": "completed",
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "qualiant_id": qualiant_id,
            "phase": phase,
            "artifact_id": record.artifact_id,
            "artifact_status": status,
            "grounding_status": "pending" if candidate_insight else "none",
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_dream_phase_prepare(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    phase: str,
    packet_budget: int | None = None,
    configuration_revision: int = 0,
) -> DreamPhasePrepareResult:
    """Prepare the next model-facing phase packet from prior dream artifacts."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    if phase not in DREAM_PHASES:
        return {"status": "error", "run_id": run_id, "error": "invalid dream phase"}
    lane = HeartbeatLedger(settings.heartbeat_ledger_file)
    existing = lane.find_idempotency(idempotency_key)
    if existing is not None and existing.qualiant_id != qualiant_id:
        return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream identity does not match prepared run"}
    if existing is None or existing.event != "prepared" or existing.run_id != run_id:
        return {"status": "blocked", "run_id": run_id, "error": "dream was not prepared"}
    if existing.mode is not MemoryWorkMode.DREAMING:
        return {"status": "blocked", "run_id": run_id, "error": "run is not a dreaming run"}
    ledger = DreamLedger(settings.dreaming_ledger_file)
    if _expired(ledger, run_id):
        return _timeout_result(run_id, qualiant_id, phase=phase)
    try:
        artifacts = ledger.artifacts(run_id)
        latest = ledger.latest_phase(run_id)
        if latest == "deep":
            return {"status": "duplicate", "run_id": run_id, "phase": "deep", "error": "dream is already complete"}
        expected = DREAM_PHASES[0] if latest is None else DREAM_PHASES[DREAM_PHASES.index(latest) + 1]
        if phase != expected:
            return {"status": "deferred", "run_id": run_id, "phase": expected, "error": f"expected phase: {expected}"}
        prior = "\n\n".join(str(item.get("artifact", "")) for item in artifacts if item.get("artifact"))
        packet = "\n\n".join(
            (
                prior or "No prior artifact is available.",
            )
        )
        bounded, _ = _bound_utf8(packet, packet_budget or settings.dreaming_packet_budget)
        return {
            "status": "prepared",
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "qualiant_id": qualiant_id,
            "phase": phase,
            "packet_version": 1,
            "packet_bytes": len(bounded.encode("utf-8")),
            "packet_digest": packet_digest(bounded),
            "packet": bounded,
        }
    except (OSError, RuntimeError, ValueError, KeyError, IndexError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_dream_recall(
    run_id: str,
    qualiant_id: str,
    query: str,
    n_results: int = 5,
    configuration_revision: int = 0,
) -> DreamRecallResult:
    """Recall bounded lived and dream material while a dream owns the lane."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "identity mismatch"}
    if not query.strip():
        return {"status": "error", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream recall query is empty"}
    if not 1 <= n_results <= 20:
        return {"status": "error", "run_id": run_id, "qualiant_id": qualiant_id, "error": "n_results must be between one and twenty"}
    ledger = DreamLedger(settings.dreaming_ledger_file)
    if _expired(ledger, run_id):
        return _timeout_result(run_id, qualiant_id)
    lane = HeartbeatLedger(settings.heartbeat_ledger_file)
    active = lane.active(qualiant_id)
    if active is None or active.run_id != run_id or active.mode is not MemoryWorkMode.DREAMING:
        return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream does not own the memory-work lane"}
    try:
        memories = await memory_recall(query=query, n_results=n_results, include_retired=False)
        terms = {term for term in query.lower().split() if len(term) >= 3}
        ledger = DreamLedger(settings.dreaming_ledger_file)
        artifacts = []
        for item in reversed(ledger.recent_artifacts(qualiant_id, n_results * 2)):
            text = str(item.get("artifact", ""))
            # A dream lane must not become a broad dump of current-run scenes.
            # Every returned scene needs a substantive query-term match.
            if terms and any(term in text.lower() for term in terms):
                artifacts.append({
                    "artifact_id": item.get("artifact_id"),
                    "run_id": item.get("run_id"),
                    "phase": item.get("phase"),
                    "status": item.get("status"),
                    "historical_status": "fictional_scene",
                    "artifact": text,
                    "candidate_insight": item.get("candidate_insight"),
                })
            if len(artifacts) >= n_results:
                break
        return {
            "status": "recalled",
            "run_id": run_id,
            "qualiant_id": qualiant_id,
            "query": query,
            "memory_results": list(memories.get("results", [])),
            "dream_artifacts": artifacts,
            "results_count": len(memories.get("results", [])) + len(artifacts),
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_dream_status(
    run_id: str,
    qualiant_id: str,
) -> DreamStatusResult:
    """Report durable terminal state for one identity-bound dream run."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "identity mismatch"}
    ledger = DreamLedger(settings.dreaming_ledger_file)
    owner = ledger.run_owner(run_id)
    if owner is None:
        return {"status": "not_found", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream run was not found"}
    if owner != qualiant_id:
        return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream identity does not match"}
    terminal = HeartbeatLedger(settings.heartbeat_ledger_file).terminal(run_id)
    artifacts = ledger.artifacts(run_id)
    if terminal is None:
        return {
            "status": "active" if HeartbeatLedger(settings.heartbeat_ledger_file).active(qualiant_id) else "prepared",
            "run_id": run_id,
            "qualiant_id": qualiant_id,
            "phase": ledger.latest_phase(run_id),
            "artifact_ids": [str(item.get("artifact_id")) for item in artifacts if item.get("artifact_id")],
        }
    outcome = terminal.details.get("outcome") if isinstance(terminal.details, dict) else None
    status = "completed" if terminal.event == "completed" else "failed" if terminal.event == "failed" else "recovered"
    return {
        "status": status,
        "run_id": run_id,
        "qualiant_id": qualiant_id,
        "phase": ledger.latest_phase(run_id),
        "terminal_event": terminal.event,
        "terminal_outcome": str(outcome) if outcome is not None else None,
        "artifact_ids": [str(item.get("artifact_id")) for item in artifacts if item.get("artifact_id")],
    }


async def memory_dream_recover(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    reason: str,
    configuration_revision: int = 0,
) -> DreamPhaseResult:
    """Recover a partial dream without inventing a final scene."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    try:
        lane = HeartbeatLedger(settings.heartbeat_ledger_file)
        existing = lane.find_idempotency(idempotency_key)
        if existing is not None and existing.mode is not MemoryWorkMode.DREAMING:
            return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream recovery cannot recover a heartbeat run"}
        dream_ledger = DreamLedger(settings.dreaming_ledger_file)
        recovery_fp = request_fingerprint(
            operation="dream_recovery", run_id=run_id, qualiant_id=qualiant_id, reason=reason,
        )
        prior_recovery = dream_ledger.recovery_for_run(run_id)
        if existing is not None and existing.event == "recovered" and prior_recovery is not None:
            if prior_recovery.get("request_fingerprint") != recovery_fp:
                return {"status": "conflict", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream recovery idempotency key was reused with different request data"}
            return {"status": "duplicate", "run_id": run_id, "idempotency_key": idempotency_key, "qualiant_id": qualiant_id, "artifact_ids": prior_recovery.get("artifact_ids", []), "grounding_status": "unchanged", "promotion_status": "none"}
        if existing is None or existing.event != "prepared" or existing.run_id != run_id:
            return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream was not prepared"}
        lane.recover(
            dream_request(run_id, qualiant_id, configuration_revision),
            idempotency_key=idempotency_key,
            reason=reason,
        )
        recovery = dream_ledger.append_recovery(
            run_id=run_id, idempotency_key=idempotency_key, qualiant_id=qualiant_id,
            reason=reason, artifacts=dream_ledger.artifacts(run_id),
            request_fingerprint=recovery_fp,
        )
        return {"status": "partial", "run_id": run_id, "idempotency_key": idempotency_key, "qualiant_id": qualiant_id, "error": reason, "artifact_ids": recovery["artifact_ids"], "grounding_status": "unchanged", "promotion_status": "none"}
    except (OSError, RuntimeError, ValueError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_dream_release(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    reason: str,
    configuration_revision: int = 0,
) -> DreamReleaseResult:
    """Release a prepared dream while preserving every completed artifact."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    if reason not in DREAM_RELEASE_REASONS:
        return {"status": "error", "run_id": run_id, "qualiant_id": qualiant_id, "error": "invalid dream release reason"}
    try:
        lane = HeartbeatLedger(settings.heartbeat_ledger_file)
        existing = lane.find_idempotency(idempotency_key)
        if existing is not None and (existing.qualiant_id != qualiant_id or existing.run_id != run_id):
            return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "release identity does not match prepared run"}
        if existing is None or existing.mode is not MemoryWorkMode.DREAMING:
            return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream was not prepared"}
        dream_ledger = DreamLedger(settings.dreaming_ledger_file)
        if _expired(dream_ledger, run_id):
            reason = "timeout"

        terminal = lane.terminal(run_id)
        if terminal is not None:
            release = dream_ledger.release_for_run(run_id)
            if release is not None:
                expected_fp = request_fingerprint(
                    operation="dream_release", run_id=run_id, qualiant_id=qualiant_id, reason=reason,
                )
                if release.get("request_fingerprint") != expected_fp:
                    return {"status": "conflict", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream release idempotency key was reused with different request data"}
                return {
                    "status": "duplicate",
                    "run_id": run_id,
                    "idempotency_key": release.get("idempotency_key"),
                    "qualiant_id": qualiant_id,
                    "release_reason": release.get("release_reason"),
                    "release_outcome": release.get("release_outcome"),
                    "artifact_ids": release.get("artifact_ids", []),
                    "grounding_status": "unchanged",
                    "promotion_status": "none",
                }
            return {"status": "duplicate", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream already has a terminal outcome"}
        if existing.event != "prepared":
            return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream is not releasable"}

        release = dream_ledger.append_release(
            run_id=run_id,
            idempotency_key=idempotency_key,
            qualiant_id=qualiant_id,
            reason=reason,
            artifacts=dream_ledger.artifacts(run_id),
            request_fingerprint=request_fingerprint(
                operation="dream_release", run_id=run_id, qualiant_id=qualiant_id, reason=reason,
            ),
        )
        lane.finish(
            dream_request(run_id, qualiant_id, configuration_revision),
            idempotency_key=idempotency_key,
            outcome="partial",
            valid_outcomes=DREAM_OUTCOMES,
            details={"release_reason": reason, "release_outcome": reason, "artifact_ids": release["artifact_ids"]},
        )
        return {
            "status": "released",
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "qualiant_id": qualiant_id,
            "release_reason": reason,
            "release_outcome": reason,
            "artifact_ids": release["artifact_ids"],
            "grounding_status": "unchanged",
            "promotion_status": "none",
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_dream_diary(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    text: str,
    visibility: str = "private",
    generation_status: str = "generated",
) -> DreamDiaryResult:
    """Store an optional post-dream diary artifact, never canonical memory."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    if visibility not in {"private", "companion", "shared"}:
        return {"status": "error", "run_id": run_id, "error": "invalid diary visibility"}
    if generation_status not in {"generated", "unavailable", "fallback"}:
        return {"status": "error", "run_id": run_id, "error": "invalid diary generation status"}
    try:
        ledger = DreamLedger(settings.dreaming_ledger_file)
        existing = ledger.diary_for_run(run_id)
        if existing is not None:
            expected_fp = request_fingerprint(
                operation="dream_diary", run_id=run_id, qualiant_id=qualiant_id,
                text=text.strip(), visibility=visibility, generation_status=generation_status,
            )
            if existing.get("request_fingerprint") != expected_fp:
                return {"status": "conflict", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream diary idempotency key was reused with different request data"}
            return {
                "status": "duplicate",
                "run_id": run_id,
                "diary_id": existing.get("diary_id"),
                "qualiant_id": qualiant_id,
                "visibility": existing.get("visibility"),
                "experience_mode": "dream",
                "historical_status": "fictional_scene",
                "generation_status": existing.get("generation_status"),
            }
        record = ledger.append_diary(
            run_id=run_id,
            idempotency_key=idempotency_key,
            qualiant_id=qualiant_id,
            text=text,
            visibility=visibility,
            generation_status=generation_status,
            request_fingerprint=request_fingerprint(
                operation="dream_diary", run_id=run_id, qualiant_id=qualiant_id,
                text=text.strip(), visibility=visibility, generation_status=generation_status,
            ),
        )
        return {
            "status": "stored",
            "run_id": run_id,
            "diary_id": record.get("diary_id"),
            "qualiant_id": qualiant_id,
            "visibility": record.get("visibility"),
            "experience_mode": "dream",
            "historical_status": "fictional_scene",
            "generation_status": record.get("generation_status"),
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


async def memory_dream_ground(
    run_id: str,
    artifact_id: str,
    qualiant_id: str,
    decision: str,
    grounded_text: str | None = None,
    source_refs: list[str] | None = None,
) -> DreamGroundResult:
    """Ground, reject, or defer a dream insight; keep scenes out of memory."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    ledger = DreamLedger(settings.dreaming_ledger_file)
    if _expired(ledger, run_id):
        return _timeout_result(run_id, qualiant_id, artifact_id=artifact_id)
    artifact = ledger.artifact_by_id(artifact_id)
    if artifact is None or artifact.get("run_id") != run_id:
        return {"status": "blocked", "run_id": run_id, "artifact_id": artifact_id, "error": "dream artifact not found"}
    if artifact.get("qualiant_id") != qualiant_id:
        return {"status": "blocked", "run_id": run_id, "artifact_id": artifact_id, "error": "dream artifact identity mismatch"}
    if decision == "keep" and (
        artifact.get("phase") != "deep"
        or artifact.get("status") not in DREAM_PHASE_COMPLETION_STATUSES["deep"]
        or not artifact.get("candidate_insight")
    ):
        return {
            "status": "blocked",
            "run_id": run_id,
            "artifact_id": artifact_id,
            "error": "only a Deep candidate insight may be grounded into canonical memory",
        }
    refs = source_refs or []
    try:
        memory_id: str | None = None
        grounding_fp = request_fingerprint(
            operation="dream_ground", run_id=run_id, artifact_id=artifact_id,
            qualiant_id=qualiant_id, decision=decision,
            grounded_text=(grounded_text or "").strip(), source_refs=refs,
        )
        existing_grounding = next(
            (item for item in reversed(ledger._records()) if item.get("event") == "grounding" and item.get("artifact_id") == artifact_id),
            None,
        )
        if existing_grounding is not None:
            if existing_grounding.get("request_fingerprint") != grounding_fp:
                return {"status": "conflict", "run_id": run_id, "artifact_id": artifact_id, "error": "grounding request fingerprint mismatch"}
            if existing_grounding.get("grounding_status") == "pending":
                return {"status": "uncertain", "run_id": run_id, "artifact_id": artifact_id, "error": "grounding ingest is unresolved; refusing a duplicate canonical memory"}
            return {"status": "duplicate", "run_id": run_id, "artifact_id": artifact_id, "qualiant_id": qualiant_id, "decision": existing_grounding.get("decision"), "memory_id": existing_grounding.get("memory_id"), "grounding_status": existing_grounding.get("grounding_status")}
        if decision == "keep":
            ledger.append_grounding(
                run_id=run_id, artifact_id=artifact_id, qualiant_id=qualiant_id,
                decision="pending", grounded_text=grounded_text, source_refs=refs,
                request_fingerprint=grounding_fp,
            )
        if decision == "keep":
            text = (grounded_text or "").strip()
            result = await memory_ingest(
                text=text,
                memory_type="reflection",
                importance=3,
                experience_mode="dream",
                historical_status="interpreted",
                recorded_during="dream",
                provenance_note=f"grounded from dream artifact {artifact_id}; sources={json.dumps(refs, sort_keys=True)}",
                derived_from=[artifact_id, *refs],
                source="dream",
                heartbeat_kind=None,
            )
            if result.get("error") or result.get("status") != "stored":
                raise ValueError(str(result.get("error") or "grounded memory was not stored"))
            memory_id = str(result["id"])
        record = ledger.append_grounding(
            run_id=run_id,
            artifact_id=artifact_id,
            qualiant_id=qualiant_id,
            decision=decision,
            grounded_text=grounded_text,
            source_refs=refs,
            memory_id=memory_id,
            request_fingerprint=grounding_fp,
        )
        return {
            "status": "stored" if decision == "keep" else decision,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "qualiant_id": qualiant_id,
            "decision": decision,
            "memory_id": record.get("memory_id"),
            "grounding_status": record.get("grounding_status"),
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        return {"status": "failed", "run_id": run_id, "artifact_id": artifact_id, "qualiant_id": qualiant_id, "error": str(exc)}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "fn": memory_dream_invoke,
        "name": "memory_dream_invoke",
        "description": "Open one identity-bound Qualiant-chosen dream opportunity and return the bounded OpenCode handoff; Nephesh does not spawn a hidden model session.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_claim,
        "name": "memory_dream_claim",
        "description": "Claim one durable queued chosen-dream request after the shared memory-work lane is idle.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_prepare,
        "name": "memory_dream_prepare",
        "description": "Prepare an identity-bound Light-phase Nephesh dream from bounded attributable memory context; no canonical memory write occurs.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_phase,
        "name": "memory_dream_phase",
        "description": "Record one bounded Light, REM, or Deep dream artifact with fictional-scene provenance; Deep releases the dream lane without automatic promotion.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_phase_prepare,
        "name": "memory_dream_phase_prepare",
        "description": "Prepare the next Light, REM, or Deep model-facing dream phase from bounded prior artifacts without injecting dream provenance as content.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_recall,
        "name": "memory_dream_recall",
        "description": "Recall bounded lived memory and explicitly marked prior dream artifacts while an identity-bound dream owns the lane.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_status,
        "name": "memory_dream_status",
        "description": "Inspect the durable terminal state of one identity-bound dream run without changing it.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_diary,
        "name": "memory_dream_diary",
        "description": "Store an optional post-dream diary artifact with fictional-scene provenance; never creates canonical memory.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_ground,
        "name": "memory_dream_ground",
        "description": "Ground, reject, or defer a dream insight after waking review; only an explicit keep decision creates an interpreted canonical memory.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_recover,
        "name": "memory_dream_recover",
        "description": "Recover a partial dream without inventing a final scene or promoting dream content.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
    {
        "fn": memory_dream_release,
        "name": "memory_dream_release",
        "description": "Release an identity-bound dream for waking choice, nightmare, timeout, cancellation, or failure while preserving partial artifacts and never grounding or promoting a scene.",
        "compliance": ComplianceLevel.NON_COMPLIANT,
    },
]
