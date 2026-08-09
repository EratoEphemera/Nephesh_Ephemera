"""MCP boundary for the always-on memory-processing schedule."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..compliance import ComplianceLevel
from ..config import settings
from ..schedule import ScheduleStore


def _store() -> ScheduleStore:
    return ScheduleStore(settings.schedule_config_file, settings.schedule_events_file)


async def memory_schedule_status(now: str | None = None) -> dict[str, Any]:
    """Return the durable default/adjusted schedule and current lifecycle state."""
    parsed = datetime.fromisoformat(now) if now else None
    if parsed is not None and parsed.tzinfo is None:
        return {"status": "failed", "error": "schedule timestamps must include a timezone"}
    return _store().status(parsed)


async def memory_schedule_update(
    authored_by: str,
    expected_revision: int,
    heartbeat_interval_seconds: int | None = None,
    study_interval_seconds: int | None = None,
    dreaming_interval_seconds: int | None = None,
    dreaming_window_seconds: int | None = None,
    dreaming_local_time: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Amend the always-on schedule with optimistic revision protection."""
    changes = {
        key: value
        for key, value in {
            "heartbeat_interval_seconds": heartbeat_interval_seconds,
            "study_interval_seconds": study_interval_seconds,
            "dreaming_interval_seconds": dreaming_interval_seconds,
            "dreaming_window_seconds": dreaming_window_seconds,
            "dreaming_local_time": dreaming_local_time,
            "timezone": timezone,
        }.items()
        if value is not None
    }
    try:
        result = _store().update(changes, authored_by=authored_by, expected_revision=expected_revision)
        return {"status": "updated", "schedule": result.__dict__}
    except (OSError, TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}


async def memory_schedule_pause(authored_by: str, expected_revision: int) -> dict[str, Any]:
    """Pause scheduled processing without disabling the installed features."""
    try:
        result = _store().set_paused(True, authored_by=authored_by, expected_revision=expected_revision)
        return {"status": "paused", "schedule": result.__dict__}
    except (OSError, TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}


async def memory_schedule_resume(authored_by: str, expected_revision: int) -> dict[str, Any]:
    """Resume scheduled processing without changing its configuration."""
    try:
        result = _store().set_paused(False, authored_by=authored_by, expected_revision=expected_revision)
        return {"status": "resumed", "schedule": result.__dict__}
    except (OSError, TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}


async def memory_schedule_claim(now: str | None = None) -> dict[str, Any]:
    """Claim one due operation for the external harness/supervisor to execute."""
    parsed = datetime.fromisoformat(now) if now else None
    if parsed is not None and parsed.tzinfo is None:
        return {"status": "failed", "error": "schedule timestamps must include a timezone"}
    try:
        return _store().claim_due(now=parsed)
    except (OSError, TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}


async def memory_schedule_complete(operation_id: str, outcome: str, reason: str | None = None) -> dict[str, Any]:
    """Record a terminal outcome for a harness-claimed scheduled operation."""
    try:
        event = _store().finish(operation_id, outcome=outcome, reason=reason)
        return {"status": outcome, "operation_id": operation_id, "recorded_at": event.recorded_at}
    except (OSError, TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}


TOOL_DEFINITIONS = [
    {"fn": memory_schedule_status, "name": "memory_schedule_status", "description": "Inspect the always-on heartbeat and dreaming schedule.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": memory_schedule_update, "name": "memory_schedule_update", "description": "Adjust the durable heartbeat and dreaming schedule with revision protection.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": memory_schedule_pause, "name": "memory_schedule_pause", "description": "Pause scheduled heartbeat and dreaming without disabling the installed features.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": memory_schedule_resume, "name": "memory_schedule_resume", "description": "Resume the durable heartbeat and dreaming schedule.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": memory_schedule_claim, "name": "memory_schedule_claim", "description": "Claim one due heartbeat or dreaming operation for an external harness.", "compliance": ComplianceLevel.NON_COMPLIANT},
    {"fn": memory_schedule_complete, "name": "memory_schedule_complete", "description": "Record a terminal outcome for a harness-claimed scheduled operation.", "compliance": ComplianceLevel.NON_COMPLIANT},
]
