"""Durable always-on heartbeat and dreaming schedule.

Nephesh owns the schedule and its lifecycle state. A harness owns waking the
model and external tools. This module never starts a hidden background task;
the explicit scheduler boundary keeps tests, restarts, and handoff inspectable.
"""

from __future__ import annotations

import threading
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import settings
from .persistence import durable_append, read_jsonl_lines


DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 3 * 60 * 60
DEFAULT_STUDY_INTERVAL_SECONDS = 4 * 60 * 60
DEFAULT_DREAMING_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_DREAMING_WINDOW_SECONDS = 60 * 60
DEFAULT_DREAMING_LOCAL_TIME = "03:00"
DEFAULT_SCHEDULE_TIMEZONE = "America/Montevideo"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("schedule timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ScheduleConfig:
    revision: int = 0
    authored_by: str = "default"
    heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    study_interval_seconds: int = DEFAULT_STUDY_INTERVAL_SECONDS
    dreaming_interval_seconds: int = DEFAULT_DREAMING_INTERVAL_SECONDS
    dreaming_window_seconds: int = DEFAULT_DREAMING_WINDOW_SECONDS
    dreaming_local_time: str = DEFAULT_DREAMING_LOCAL_TIME
    timezone: str = DEFAULT_SCHEDULE_TIMEZONE
    paused: bool = False
    updated_at: str = ""

    def validate(self) -> None:
        if self.revision < 0:
            raise ValueError("schedule revision must be non-negative")
        if not self.authored_by.strip():
            raise ValueError("schedule author is required")
        if self.heartbeat_interval_seconds < 300:
            raise ValueError("memory-tending interval must be at least five minutes")
        if self.study_interval_seconds < 300:
            raise ValueError("study interval must be at least five minutes")
        if self.dreaming_interval_seconds < 900:
            raise ValueError("dreaming interval must be at least fifteen minutes")
        if not 60 <= self.dreaming_window_seconds <= self.dreaming_interval_seconds:
            raise ValueError("dreaming window must be between one minute and its interval")
        if not self.timezone.strip():
            raise ValueError("schedule timezone is required")
        try:
            hour, minute = (int(part) for part in self.dreaming_local_time.split(":", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("dreaming local time must be HH:MM") from exc
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("dreaming local time must be HH:MM")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown schedule timezone: {self.timezone}") from exc


@dataclass(frozen=True)
class ScheduleEvent:
    event: str
    operation_id: str | None
    operation: str | None
    recorded_at: str
    due_at: str | None = None
    reason: str | None = None


class ScheduleStore:
    """Append-only schedule configuration and lifecycle history."""

    _lock = threading.RLock()

    def __init__(self, config_path: str | Path, events_path: str | Path):
        self.config_path = Path(config_path)
        self.events_path = Path(events_path)

    def current(self) -> ScheduleConfig:
        with self._lock:
            if not self.config_path.exists():
                config = ScheduleConfig(updated_at=_now().isoformat())
                config.validate()
                import json
                durable_append(self.config_path, json.dumps(asdict(config), sort_keys=True) + "\n")
                return config
            records = [json for json in read_jsonl_lines(self.config_path.read_text(encoding="utf-8")) if json.strip()]
            if not records:
                config = ScheduleConfig(updated_at=_now().isoformat())
                config.validate()
                import json as json_module
                durable_append(self.config_path, json_module.dumps(asdict(config), sort_keys=True) + "\n")
                return config
            import json as json_module
            raw = json_module.loads(records[-1])
            config = ScheduleConfig(**raw)
            config.validate()
            return config

    def update(self, changes: dict[str, Any], *, authored_by: str, expected_revision: int) -> ScheduleConfig:
        with self._lock:
            current = self.current()
            if current.revision != expected_revision:
                raise ValueError("schedule revision changed; reread before updating")
            allowed = {
                "heartbeat_interval_seconds",
                "study_interval_seconds",
                "dreaming_interval_seconds",
                "dreaming_window_seconds",
                "dreaming_local_time",
                "timezone",
            }
            unknown = set(changes) - allowed
            if unknown:
                raise ValueError(f"unsupported schedule fields: {sorted(unknown)}")
            values = asdict(current)
            values.update(changes)
            values.update({
                "revision": current.revision + 1,
                "authored_by": authored_by,
                "updated_at": _now().isoformat(),
            })
            result = ScheduleConfig(**values)
            result.validate()
            import json
            durable_append(self.config_path, json.dumps(asdict(result), sort_keys=True) + "\n")
            return result

    def set_paused(self, paused: bool, *, authored_by: str, expected_revision: int) -> ScheduleConfig:
        with self._lock:
            current = self.current()
            if current.revision != expected_revision:
                raise ValueError("schedule revision changed; reread before pausing or resuming")
            import json
            result = ScheduleConfig(
                **{
                    **asdict(current),
                    "revision": current.revision + 1,
                    "authored_by": authored_by,
                    "paused": paused,
                    "updated_at": _now().isoformat(),
                }
            )
            durable_append(self.config_path, json.dumps(asdict(result), sort_keys=True) + "\n")
            self.record("paused" if paused else "resumed", reason=f"authored_by={authored_by}")
            return result

    def _events(self) -> list[ScheduleEvent]:
        if not self.events_path.exists():
            return []
        import json
        result = []
        for line in read_jsonl_lines(self.events_path.read_text(encoding="utf-8")):
            if line.strip():
                result.append(ScheduleEvent(**json.loads(line)))
        return result

    def record(self, event: str, *, operation_id: str | None = None, operation: str | None = None,
               due_at: str | None = None, reason: str | None = None) -> ScheduleEvent:
        with self._lock:
            import json
            result = ScheduleEvent(event, operation_id, operation, _now().isoformat(), due_at, reason)
            durable_append(self.events_path, json.dumps(asdict(result), sort_keys=True) + "\n")
            return result

    def status(self, now: datetime | None = None) -> dict[str, Any]:
        now = (now or _now()).astimezone(timezone.utc)
        config = self.current()
        events = self._events()
        claimed = {event.operation_id for event in events if event.event == "claimed"}
        completed = {event.operation_id for event in events if event.event in {"completed", "failed", "recovered"}}
        active = next((event for event in reversed(events) if event.event == "claimed" and event.operation_id not in completed), None)
        last: dict[str, ScheduleEvent] = {}
        for event in events:
            if event.operation and event.event in {"completed", "failed", "recovered"}:
                last[event.operation] = event
        def next_at(operation: str, interval: int) -> str:
            previous = last.get(operation)
            base = _parse(previous.recorded_at) if previous else now
            if previous is None:
                return now.isoformat()
            return (base + timedelta(seconds=interval)).isoformat()
        def next_dreaming_at() -> str:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(config.timezone)
            previous = last.get("dreaming")
            local = (_parse(previous.recorded_at) if previous else now).astimezone(zone)
            hour, minute = (int(part) for part in config.dreaming_local_time.split(":", 1))
            candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= local:
                candidate += timedelta(days=1)
            return candidate.astimezone(timezone.utc).isoformat()
        tending_at = next_at("tending", config.heartbeat_interval_seconds)
        study_at = next_at("study", config.study_interval_seconds)
        return {
            "enabled": True,
            "model": settings.model,
            "heartbeat_model": settings.heartbeat_model,
            "dreaming_model": settings.dreaming_model,
            "harness": settings.harness,
            "harness_command": settings.harness_command,
            "paused": config.paused,
            "revision": config.revision,
            "authored_by": config.authored_by,
            "heartbeat_interval_seconds": config.heartbeat_interval_seconds,
            "tending_interval_seconds": config.heartbeat_interval_seconds,
            "study_interval_seconds": config.study_interval_seconds,
            "dreaming_interval_seconds": config.dreaming_interval_seconds,
            "dreaming_window_seconds": config.dreaming_window_seconds,
            "dreaming_local_time": config.dreaming_local_time,
            "timezone": config.timezone,
            "active_operation": asdict(active) if active else None,
            "next_tending_at": None if config.paused else tending_at,
            "next_study_at": None if config.paused else study_at,
            "next_heartbeat_at": None if config.paused else min(tending_at, study_at),
            "next_dreaming_at": None if config.paused else next_dreaming_at(),
            "last_operations": {key: asdict(value) for key, value in last.items()},
            "coalesced_events": sum(1 for event in events if event.event == "coalesced"),
        }

    def claim_due(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = (now or _now()).astimezone(timezone.utc)
        status = self.status(now)
        if status["paused"]:
            return {"status": "paused", "reason": "schedule is paused"}
        if status["active_operation"] is not None:
            return {"status": "deferred", "reason": "another scheduled operation is active"}
        candidates = []
        for operation, key in (("tending", "next_tending_at"), ("study", "next_study_at"), ("dreaming", "next_dreaming_at")):
            due = _parse(status[key])
            if due <= now:
                candidates.append((due, operation))
        if not candidates:
            return {"status": "not_due", "next_heartbeat_at": status["next_heartbeat_at"], "next_dreaming_at": status["next_dreaming_at"]}
        # Dreaming has precedence whenever both modes are due, not merely when
        # their timestamps happen to tie. This prevents a heartbeat from
        # stealing the boundary while a scheduled dream is waiting.
        if any(operation == "dreaming" for _, operation in candidates):
            due_at, operation = next(item for item in candidates if item[1] == "dreaming")
        else:
            due_at, operation = min(candidates, key=lambda item: item[0])
        operation_id = f"{operation}-{now.strftime('%Y%m%dT%H%M%S%fZ')}"
        self.record("claimed", operation_id=operation_id, operation=operation, due_at=due_at.isoformat())
        if operation == "dreaming":
            for queued_operation, key in (("tending", "next_tending_at"), ("study", "next_study_at")):
                if status[key] and _parse(status[key]) <= now:
                    self.record("coalesced", operation_id=operation_id, operation=queued_operation, due_at=status[key], reason="dreaming precedence")
        return {"status": "due", "operation": operation, "operation_id": operation_id, "due_at": due_at.isoformat()}

    def finish(self, operation_id: str, *, outcome: str, reason: str | None = None) -> ScheduleEvent:
        if outcome not in {"completed", "failed", "recovered"}:
            raise ValueError("schedule outcome must be completed, failed, or recovered")
        with self._lock:
            events = self._events()
            claimed = next((event for event in reversed(events) if event.operation_id == operation_id and event.event == "claimed"), None)
            if claimed is None:
                raise ValueError("schedule operation was not claimed")
            existing = next(
                (event for event in events if event.operation_id == operation_id and event.event in {"completed", "failed", "recovered"}),
                None,
            )
            if existing is not None:
                return existing
            return self.record(
                outcome,
                operation_id=operation_id,
                operation=claimed.operation,
                due_at=claimed.due_at,
                reason=reason,
            )


class ScheduleSupervisor:
    """Harness-side loop that wakes a callback for due operations.

    The callback owns model/MCP execution. The supervisor only claims one due
    operation, records its terminal outcome, and sleeps using the monotonic
    event-loop clock. Cancellation is propagated after the current callback's
    durable terminal record is attempted.
    """

    def __init__(self, store: ScheduleStore, on_due, *, poll_seconds: float = 30.0):
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be greater than zero")
        self.store = store
        self.on_due = on_due
        self.poll_seconds = poll_seconds

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            claim = self.store.claim_due()
            if claim.get("status") == "due":
                operation_id = str(claim["operation_id"])
                try:
                    outcome = await self.on_due(claim)
                    self.store.finish(operation_id, outcome=str(outcome.get("status", "completed")), reason=outcome.get("reason"))
                except asyncio.CancelledError:
                    self.store.finish(operation_id, outcome="recovered", reason="scheduler cancelled")
                    raise
                except Exception as exc:
                    self.store.finish(operation_id, outcome="failed", reason=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
