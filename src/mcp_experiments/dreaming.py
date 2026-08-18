"""Bounded Nephesh dreaming phases and provenance artifacts.

The harness supplies scheduling and model execution. Nephesh owns the exclusive
dream/heartbeat lane, eligible memory context, phase order, and the fact that a
dream scene is not waking autobiography.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .heartbeat import (
    HeartbeatLedger,
    MemoryWorkMode,
    WorkRequest,
)
from .persistence import durable_append, read_jsonl_lines

DREAM_KIND = "nephesh_dream"
DREAM_PHASES = ("light", "rem", "deep")
DREAM_PHASE_OUTCOMES = {
    "light": frozenset({"artifact_written", "no_inputs", "no_candidates", "deferred", "blocked", "unavailable", "partial", "failed"}),
    "rem": frozenset({"dreamed", "no_candidates", "deferred", "blocked", "unavailable", "partial", "failed"}),
    "deep": frozenset({"no_grounding", "artifact_written", "no_candidates", "deferred", "blocked", "unavailable", "partial", "failed"}),
}
DREAM_OUTCOMES = frozenset(
    {
        "no_inputs",
        "no_candidates",
        "dreamed",
        "artifact_written",
        "no_grounding",
        "promoted",
        "paused",
        "refused",
        "deferred",
        "blocked",
        "unavailable",
        "partial",
        "failed",
    }
)
DREAM_RELEASE_REASONS = frozenset(
    {"waking_choice", "nightmare_release", "timeout", "cancellation", "failure"}
)
DEFAULT_DREAMING_INSTRUCTION = """Let the attributable material settle without forcing a plot or explanation.

Allow associations, symbols, sensory transformations, and emotional movement to
arise naturally. Do not manufacture memories, attribute imagined dialogue to
real people, or turn depicted events into waking history. You do not need to
explain, preserve, or interpret anything during this phase. Any later
grounding or memory preservation is a separate choice."""
MAX_DREAM_ARTIFACT_CHARS = 12_000
NON_SUBSTANTIVE_PHASE_STATUSES = frozenset({
    "no_inputs", "no_candidates", "deferred", "blocked", "unavailable", "failed",
})


def request_fingerprint(**values: Any) -> str:
    """Hash the caller's operation, excluding wall-clock/generated values."""
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DreamArtifact:
    artifact_id: str
    run_id: str
    phase: str
    status: str
    recorded_at: str
    historical_status: str
    source_refs: list[str]
    artifact: str
    candidate_insight: str | None = None


class DreamLedger:
    """Append-only dream artifacts, separate from canonical memory rows."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in read_jsonl_lines(self.path.read_text(encoding="utf-8")):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("dream ledger record must be an object")
            records.append(value)
        return records

    def latest_phase(self, run_id: str) -> str | None:
        phases = [
            record.get("phase")
            for record in self._records()
            if record.get("run_id") == run_id and record.get("phase") in DREAM_PHASES
        ]
        return phases[-1] if phases else None

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self._records()
            if record.get("run_id") == run_id and record.get("phase") in DREAM_PHASES
        ]

    def recent_artifacts(self, qualiant_id: str, limit: int) -> list[dict[str, Any]]:
        """Return bounded prior dream artifacts for dream-lane recall."""
        records = [
            record
            for record in self._records()
            if record.get("qualiant_id") == qualiant_id
            and record.get("phase") in DREAM_PHASES
        ]
        return records[-max(1, limit):]

    def artifact_for_phase(self, run_id: str, phase: str) -> dict[str, Any] | None:
        return next(
            (record for record in self.artifacts(run_id) if record.get("phase") == phase),
            None,
        )

    def artifact_by_id(self, artifact_id: str) -> dict[str, Any] | None:
        return next(
            (record for record in self._records() if record.get("artifact_id") == artifact_id),
            None,
        )

    def run_owner(self, run_id: str) -> str | None:
        for record in self._records():
            if record.get("run_id") == run_id and record.get("qualiant_id"):
                return str(record["qualiant_id"])
        return None

    def diary_for_run(self, run_id: str) -> dict[str, Any] | None:
        return next(
            (record for record in self._records() if record.get("event") == "diary" and record.get("run_id") == run_id),
            None,
        )

    def prepare_for_key(self, idempotency_key: str) -> dict[str, Any] | None:
        return next(
            (record for record in self._records() if record.get("event") == "prepare" and record.get("idempotency_key") == idempotency_key),
            None,
        )

    def invocation_for_key(self, idempotency_key: str) -> dict[str, Any] | None:
        return next(
            (record for record in self._records() if record.get("event") == "invocation" and record.get("idempotency_key") == idempotency_key),
            None,
        )

    def invocation_claim_for_key(self, idempotency_key: str) -> dict[str, Any] | None:
        return next(
            (record for record in reversed(self._records())
             if record.get("event") == "invocation_claim" and record.get("idempotency_key") == idempotency_key),
            None,
        )

    def queued_invocations(self, qualiant_id: str) -> list[dict[str, Any]]:
        claims = {
            record.get("idempotency_key")
            for record in self._records()
            if record.get("event") == "invocation_claim"
        }
        return [
            record
            for record in self._records()
            if record.get("event") == "invocation"
            and record.get("status") == "queued"
            and record.get("qualiant_id") == qualiant_id
            and record.get("idempotency_key") not in claims
        ]

    def append_invocation(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        qualiant_id: str,
        request_fingerprint: str,
        handoff: dict[str, Any],
        request: dict[str, Any] | None = None,
        status: str = "accepted",
    ) -> dict[str, Any]:
        with self._lock:
            existing = self.invocation_for_key(idempotency_key)
            if existing is not None:
                if existing.get("request_fingerprint") != request_fingerprint:
                    raise ValueError("dream invocation idempotency key was reused with different request data")
                return existing
            record = {
                "event": "invocation",
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "qualiant_id": qualiant_id,
                "request_fingerprint": request_fingerprint,
                "handoff": dict(handoff),
                "request": dict(request or {}),
                "status": status,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            durable_append(self.path, json.dumps(record, sort_keys=True) + "\n")
            return record

    def append_invocation_claim(
        self, *, run_id: str, idempotency_key: str, qualiant_id: str,
        request_fingerprint: str, result: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            existing = self.invocation_claim_for_key(idempotency_key)
            if existing is not None:
                if existing.get("request_fingerprint") != request_fingerprint:
                    raise ValueError("dream claim idempotency key was reused with different request data")
                return existing
            record = {
                "event": "invocation_claim", "run_id": run_id,
                "idempotency_key": idempotency_key, "qualiant_id": qualiant_id,
                "request_fingerprint": request_fingerprint,
                "result": dict(result),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            durable_append(self.path, json.dumps(record, sort_keys=True) + "\n")
            return record

    def append_prepare(
        self, *, run_id: str, idempotency_key: str, qualiant_id: str,
        request_fingerprint: str, packet_digest: str,
        duration_seconds: int | None = None, deadline_utc: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        with self._lock:
            existing = self.prepare_for_key(idempotency_key)
            if existing is not None:
                if existing.get("request_fingerprint") != request_fingerprint or existing.get("packet_digest") != packet_digest:
                    raise ValueError("dream prepare idempotency key was reused with different request data")
                return
            record = {
                "event": "prepare", "run_id": run_id, "idempotency_key": idempotency_key,
                "qualiant_id": qualiant_id, "request_fingerprint": request_fingerprint,
                "packet_digest": packet_digest, "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            if duration_seconds is not None:
                record["duration_seconds"] = duration_seconds
            if deadline_utc is not None:
                record["deadline_utc"] = deadline_utc
            if expires_at is not None:
                record["expires_at"] = expires_at
            durable_append(self.path, json.dumps(record, sort_keys=True) + "\n")

    def release_for_run(self, run_id: str) -> dict[str, Any] | None:
        return next(
            (record for record in self._records() if record.get("event") == "release" and record.get("run_id") == run_id),
            None,
        )

    def recovery_for_run(self, run_id: str) -> dict[str, Any] | None:
        return next(
            (record for record in self._records() if record.get("event") == "recovery" and record.get("run_id") == run_id),
            None,
        )

    def append_release(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        qualiant_id: str,
        reason: str,
        artifacts: list[dict[str, Any]],
        request_fingerprint: str,
    ) -> dict[str, Any]:
        if reason not in DREAM_RELEASE_REASONS:
            raise ValueError(f"invalid dream release reason: {reason}")
        if self.run_owner(run_id) != qualiant_id:
            raise ValueError("dream release identity does not match dream run")
        with self._lock:
            existing = self.release_for_run(run_id)
            if existing is not None:
                if existing.get("request_fingerprint") != request_fingerprint:
                    raise ValueError("dream release idempotency key was reused with different request data")
                return existing
            record = {
            "event": "release",
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "request_fingerprint": request_fingerprint,
            "qualiant_id": qualiant_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "release_reason": reason,
            "release_outcome": reason,
            "artifact_ids": [str(item["artifact_id"]) for item in artifacts if item.get("artifact_id")],
            "partial_artifacts": [
                {"phase": item.get("phase"), "artifact_id": item.get("artifact_id"), "status": item.get("status")}
                for item in artifacts
            ],
            "grounding_status": "unchanged",
            "promotion_status": "none",
            }
            durable_append(self.path, json.dumps(record, sort_keys=True) + "\n")
            return record

    def append_recovery(
        self, *, run_id: str, idempotency_key: str, qualiant_id: str, reason: str,
        artifacts: list[dict[str, Any]], request_fingerprint: str,
    ) -> dict[str, Any]:
        with self._lock:
            existing = self.recovery_for_run(run_id)
            if existing is not None:
                if existing.get("request_fingerprint") != request_fingerprint:
                    raise ValueError("dream recovery idempotency key was reused with different request data")
                return existing
            record = {
                "event": "recovery", "run_id": run_id, "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint, "qualiant_id": qualiant_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(), "recovery_reason": reason,
                "release_outcome": "partial", "artifact_ids": [str(item["artifact_id"]) for item in artifacts if item.get("artifact_id")],
                "partial_artifacts": [{"phase": item.get("phase"), "artifact_id": item.get("artifact_id"), "status": item.get("status")} for item in artifacts],
                "grounding_status": "unchanged", "promotion_status": "none",
            }
            durable_append(self.path, json.dumps(record, sort_keys=True) + "\n")
            return record

    def append_diary(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        qualiant_id: str,
        text: str,
        visibility: str,
        generation_status: str,
        request_fingerprint: str,
    ) -> dict[str, Any]:
        if not text.strip():
            raise ValueError("dream diary text cannot be empty")
        if len(text) > MAX_DREAM_ARTIFACT_CHARS:
            raise ValueError("dream diary text exceeds the bounded size")
        if self.run_owner(run_id) != qualiant_id:
            raise ValueError("dream diary identity does not match dream run")
        deep = self.artifact_for_phase(run_id, "deep")
        if deep is None or deep.get("status") in {"failed", "partial", "unavailable"}:
            raise ValueError("dream diary requires a completed deep phase")
        with self._lock:
            existing = self.diary_for_run(run_id)
            if existing is not None:
                if existing.get("request_fingerprint") != request_fingerprint:
                    raise ValueError("dream diary idempotency key was reused with different request data")
                return existing
            now = datetime.now(timezone.utc).isoformat()
            diary_id = "diary-" + hashlib.sha256(f"{qualiant_id}\0{run_id}\0{request_fingerprint}".encode()).hexdigest()[:20]
            record = {
            "event": "diary",
            "diary_id": diary_id,
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "request_fingerprint": request_fingerprint,
            "qualiant_id": qualiant_id,
            "recorded_at": now,
            "experience_mode": "dream",
            "historical_status": "fictional_scene",
            "recorded_during": "dream",
            "visibility": visibility,
            "generation_status": generation_status,
            "text": text.strip(),
            }
            durable_append(self.path, json.dumps(record, sort_keys=True) + "\n")
            return record

    def append_grounding(
        self,
        *,
        run_id: str,
        artifact_id: str,
        qualiant_id: str,
        decision: str,
        grounded_text: str | None,
        source_refs: list[str],
        memory_id: str | None = None,
        request_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        if decision not in {"keep", "reject", "pending"}:
            raise ValueError("grounding decision must be keep, reject, or pending")
        if decision == "keep" and not (grounded_text and grounded_text.strip()):
            raise ValueError("keep grounding requires grounded text")
        existing = next(
            (
                record
                for record in reversed(self._records())
                if record.get("event") == "grounding" and record.get("artifact_id") == artifact_id
            ),
            None,
        )
        if existing is not None and not (existing.get("grounding_status") == "pending" and memory_id):
            return existing
        record = {
            "event": "grounding",
            "run_id": run_id,
            "artifact_id": artifact_id,
            "qualiant_id": qualiant_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "grounded_text": grounded_text.strip() if grounded_text else None,
            "source_refs": list(source_refs),
            "memory_id": memory_id,
            "grounding_status": decision,
            "request_fingerprint": request_fingerprint,
        }
        durable_append(self.path, json.dumps(record, sort_keys=True) + "\n")
        return record

    def append_phase(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        qualiant_id: str,
        phase: str,
        status: str,
        artifact: str,
        source_refs: list[str],
        candidate_insight: str | None = None,
        request_fingerprint: str,
    ) -> DreamArtifact:
        if phase not in DREAM_PHASES:
            raise ValueError(f"invalid dream phase: {phase}")
        if status not in DREAM_PHASE_OUTCOMES[phase]:
            raise ValueError(f"outcome {status} is invalid for dream phase {phase}")
        latest = self.latest_phase(run_id)
        expected = DREAM_PHASES[0] if latest is None else DREAM_PHASES[DREAM_PHASES.index(latest) + 1]
        if phase != expected:
            raise ValueError(f"dream phase {phase} is not next; expected {expected}")
        if len(artifact) > MAX_DREAM_ARTIFACT_CHARS:
            raise ValueError("dream artifact exceeds the bounded size")
        if status not in NON_SUBSTANTIVE_PHASE_STATUSES and not artifact.strip():
            raise ValueError("substantive dream artifacts cannot be empty")
        now = datetime.now(timezone.utc).isoformat()
        artifact_id = "dream-" + hashlib.sha256(
            f"{qualiant_id}\0{run_id}\0{phase}\0{now}".encode("utf-8")
        ).hexdigest()[:20]
        # Keep generated scenes explicitly fictional; grounding is a separate
        # later operation and never happens as a side effect of phase completion.
        record = DreamArtifact(
            artifact_id=artifact_id,
            run_id=run_id,
            phase=phase,
            status=status,
            recorded_at=now,
            historical_status="fictional_scene",
            source_refs=list(source_refs),
            artifact=artifact,
            candidate_insight=candidate_insight,
        )
        with self._lock:
            existing = next((item for item in self._records() if item.get("request_fingerprint") == request_fingerprint), None)
            if existing is not None:
                return DreamArtifact(
                    artifact_id=str(existing["artifact_id"]), run_id=run_id, phase=phase,
                    status=str(existing["status"]), recorded_at=str(existing["recorded_at"]),
                    historical_status="fictional_scene", source_refs=list(existing.get("source_refs", [])),
                    artifact=str(existing.get("artifact", "")), candidate_insight=existing.get("candidate_insight"),
                )
            durable_append(
                self.path,
                json.dumps(
                {
                    **record.__dict__,
                    "idempotency_key": idempotency_key,
                    "request_fingerprint": request_fingerprint,
                    "qualiant_id": qualiant_id,
                    "dream_kind": DREAM_KIND,
                    "grounding_status": "pending" if candidate_insight else "none",
                },
                sort_keys=True,
                ) + "\n",
            )
        return record


def dream_request(run_id: str, qualiant_id: str, configuration_revision: int) -> WorkRequest:
    return WorkRequest(
        run_id=run_id,
        qualiant_id=qualiant_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        configuration_revision=configuration_revision,
    )
