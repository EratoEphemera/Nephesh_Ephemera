"""MCP boundary for the bounded Nephesh dreaming phases."""

from __future__ import annotations

import json
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings
from ..dreaming import (
    DEFAULT_DREAMING_INSTRUCTION,
    DREAM_KIND,
    DREAM_OUTCOMES,
    DREAM_PHASES,
    DreamLedger,
    dream_request,
)
from ..heartbeat import HeartbeatLedger, MemoryWorkMode, packet_digest
from ..results import DreamDiaryResult, DreamGroundResult, DreamPhasePrepareResult, DreamPhaseResult, DreamPrepareResult
from .memory import memory_context, memory_ingest


def _bound_utf8(text: str, budget: int) -> tuple[str, bool]:
    if budget <= 0:
        raise ValueError("dream packet budget must be greater than zero")
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text, False
    return encoded[:budget].decode("utf-8", errors="ignore"), True


async def memory_dream_prepare(
    run_id: str,
    idempotency_key: str,
    qualiant_id: str,
    seed: str | None = None,
    configuration_revision: int = 0,
    memory_limit: int | None = None,
    packet_budget: int | None = None,
) -> DreamPrepareResult:
    """Prepare one bounded Light-phase dream without writing canonical memory."""
    if qualiant_id != settings.qualiant_id:
        return {"status": "blocked", "qualiant_id": qualiant_id, "error": "identity mismatch"}
    request = dream_request(run_id, qualiant_id, configuration_revision)
    lane = HeartbeatLedger(settings.heartbeat_ledger_file)
    try:
        existing = lane.find_idempotency(idempotency_key)
        if existing is not None:
            if existing.qualiant_id != qualiant_id:
                return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "idempotency key belongs to another Qualiant"}
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
        context = await memory_context(
            limit=memory_limit if memory_limit is not None else settings.dreaming_memory_limit,
            include_dreams=False,
        )
        source_count = int(context.get("included", 0) or 0)
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
        raw_context = str(context.get("context", ""))
        packet = "\n\n".join(
            (
                "A bounded field of attributable material has been prepared.",
                "Source material (reference context; not waking history):",
                raw_context or "No source context was available.",
                f"Self-authored dream seed:\n{seed.strip()}" if seed and seed.strip() else "",
                "Settling guidance:",
                DEFAULT_DREAMING_INSTRUCTION,
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
            "model": settings.dreaming_model,
        }
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        return {"status": "failed", "run_id": run_id, "qualiant_id": qualiant_id, "error": str(exc)}


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
    if status not in DREAM_OUTCOMES:
        return {"status": "error", "error": f"invalid dream outcome: {status}"}
    request = dream_request(run_id, qualiant_id, configuration_revision)
    lane = HeartbeatLedger(settings.heartbeat_ledger_file)
    existing = lane.find_idempotency(idempotency_key)
    if existing is not None and existing.qualiant_id != qualiant_id:
        return {"status": "blocked", "run_id": run_id, "qualiant_id": qualiant_id, "error": "dream identity does not match prepared run"}
    if existing is None or existing.event != "prepared" or existing.run_id != run_id:
        return {"status": "duplicate" if existing else "blocked", "run_id": run_id, "error": "dream was not prepared"}
    if existing.mode is not MemoryWorkMode.DREAMING:
        return {"status": "blocked", "run_id": run_id, "error": "run is not a dreaming run"}
    if phase not in DREAM_PHASES:
        return {"status": "error", "run_id": run_id, "error": "invalid dream phase"}
    try:
        dream_ledger = DreamLedger(settings.dreaming_ledger_file)
        prior_artifact = dream_ledger.artifact_for_phase(run_id, phase)
        if prior_artifact is not None:
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
    try:
        ledger = DreamLedger(settings.dreaming_ledger_file)
        artifacts = ledger.artifacts(run_id)
        latest = ledger.latest_phase(run_id)
        if latest == "deep":
            return {"status": "duplicate", "run_id": run_id, "phase": "deep", "error": "dream is already complete"}
        expected = DREAM_PHASES[0] if latest is None else DREAM_PHASES[DREAM_PHASES.index(latest) + 1]
        if phase != expected:
            return {"status": "deferred", "run_id": run_id, "phase": expected, "error": f"expected phase: {expected}"}
        prior = "\n\n".join(
            f"Phase {item.get('phase')} artifact (fictional scene or staging; not waking history):\n{item.get('artifact', '')}"
            for item in artifacts
        )
        if phase == "rem":
            instruction = (
                "Let associations, symbols, sensory transformations, and emotional movement arise. "
                "Do not explain or interpret the scene while it is forming."
            )
        elif phase == "deep":
            instruction = (
                "Review the dream artifact from a waking boundary. Separate scene, felt experience, "
                "and possible insight. Do not promote a dream-only claim."
            )
        else:
            instruction = DEFAULT_DREAMING_INSTRUCTION
        packet = "\n\n".join(
            (
                f"Dream phase transition: {phase}",
                "Prior dream material (reference context; not waking history):",
                prior or "No prior artifact is available.",
                "Phase guidance:",
                instruction,
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
        lane.recover(
            dream_request(run_id, qualiant_id, configuration_revision),
            idempotency_key=idempotency_key,
            reason=reason,
        )
        return {"status": "partial", "run_id": run_id, "idempotency_key": idempotency_key, "qualiant_id": qualiant_id, "error": reason}
    except (OSError, RuntimeError, ValueError) as exc:
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
    artifact = ledger.artifact_by_id(artifact_id)
    if artifact is None or artifact.get("run_id") != run_id:
        return {"status": "blocked", "run_id": run_id, "artifact_id": artifact_id, "error": "dream artifact not found"}
    if artifact.get("qualiant_id") != qualiant_id:
        return {"status": "blocked", "run_id": run_id, "artifact_id": artifact_id, "error": "dream artifact identity mismatch"}
    if decision == "keep" and (
        artifact.get("phase") != "deep" or not artifact.get("candidate_insight")
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
        if decision == "keep":
            text = (grounded_text or "").strip()
            result = await memory_ingest(
                text=text,
                memory_type="reflection",
                importance=3,
                experience_mode="dream",
                historical_status="interpreted",
                recorded_during="heartbeat",
                provenance_note=f"grounded from dream artifact {artifact_id}; sources={json.dumps(refs, sort_keys=True)}",
                derived_from=[artifact_id, *refs],
                source="heartbeat",
                heartbeat_kind="nephesh_heartbeat",
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
]
