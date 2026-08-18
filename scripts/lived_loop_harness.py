"""Isolated model-backed heartbeat/dream harness.

This is deliberately a harness-side probe, not Nephesh runtime behavior.  The
model, online sources, and knowledge projections are injected by the caller;
Nephesh remains responsible for identity, provenance, phase boundaries, and
durable writes.  The module is useful for real OpenCode/MCP probes and for
hermetic tests with deterministic adapters.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from mcp_experiments.tools import dreaming, memory
from mcp_experiments.schedule import ScheduleStore, ScheduleSupervisor


ModelTurn = Callable[[str, str], Awaitable[dict[str, Any]]]
KnowledgeSearch = Callable[[str], Awaitable[dict[str, Any]]]


@dataclass
class LivedLoopReport:
    heartbeat: dict[str, Any] | None = None
    dream: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)


class LivedLoopHarness:
    """Drive one isolated heartbeat study and one dream with real tool calls.

    ``model_turn`` is the harness's model/session boundary.  ``projection_search``
    and ``online_search`` are ordinary external tools supplied by that harness.
    No external result is written by this class; only the model-authored
    completion is submitted to Nephesh.
    """

    def __init__(
        self,
        *,
        model_turn: ModelTurn,
        projection_search: KnowledgeSearch,
        online_search: KnowledgeSearch,
        adapter_timeout: float = 30.0,
    ) -> None:
        self.model_turn = model_turn
        self.projection_search = projection_search
        self.online_search = online_search
        if adapter_timeout <= 0:
            raise ValueError("adapter_timeout must be greater than zero")
        self.adapter_timeout = adapter_timeout

    async def _model(self, packet: str, purpose: str) -> dict[str, Any]:
        result = await asyncio.wait_for(
            self.model_turn(packet, purpose), timeout=self.adapter_timeout
        )
        if not isinstance(result, dict):
            raise TypeError(f"model turn {purpose} did not return an object")
        return result

    async def _search(self, search: KnowledgeSearch, query: str, name: str) -> dict[str, Any]:
        try:
            result = await asyncio.wait_for(search(query), timeout=self.adapter_timeout)
        except asyncio.TimeoutError:
            return {"status": "unavailable", "source": name, "error": "adapter timeout"}
        except Exception as exc:  # external adapters must not kill the memory loop
            return {"status": "failed", "source": name, "error": str(exc)}
        if not isinstance(result, dict):
            return {"status": "failed", "source": name, "error": "adapter returned a non-object"}
        return result

    @staticmethod
    def _usable_evidence(result: dict[str, Any]) -> bool:
        return result.get("status") not in {"unavailable", "failed", "error"}

    @staticmethod
    def _normalize_heartbeat_completion(raw: dict[str, Any]) -> dict[str, Any]:
        """Accept common model-shaped output without weakening Nephesh's contract."""
        raw_actions = raw.get("actions", [])
        if isinstance(raw_actions, dict):
            # Small models often emit one action object keyed by its name.
            if "study_memory" in raw_actions:
                value = raw_actions["study_memory"]
                if isinstance(value, str):
                    raw_actions = [{"kind": "study_memory", "text": value}]
                elif isinstance(value, dict):
                    raw_actions = [{"kind": "study_memory", **value}]
            else:
                raw_actions = []
        if not isinstance(raw_actions, list):
            raw_actions = []
        actions: list[dict[str, Any]] = []
        for action in raw_actions:
            if not isinstance(action, dict):
                continue
            normalized = dict(action)
            if isinstance(normalized.get("source_refs"), list):
                normalized["source_refs"] = [
                    item if isinstance(item, str) else json.dumps(item, sort_keys=True)
                    for item in normalized["source_refs"]
                ]
            actions.append(normalized)
        activity = str(raw.get("activity", "")).strip().lower()
        if activity not in {"tend", "study", "custom", "reflect", "rest"}:
            activity = "study" if any(a.get("kind") == "study_memory" for a in actions) else "custom" if any(a.get("kind") == "custom_action" for a in actions) else "tend" if any(a.get("kind") in {"ingest_memory", "amend_memory", "retire_memory"} for a in actions) else "study"
        outcome = str(raw.get("outcome", "")).strip().lower()
        if activity == "tend" and outcome not in {"tended", "needs_attention", "no_memories", "no_change"}:
            outcome = "tended" if any(a.get("kind") in {"ingest_memory", "amend_memory", "retire_memory"} for a in actions) else "no_change"
        if activity == "study" and outcome not in {"studied", "unavailable", "insufficient_evidence", "no_memories", "no_change"}:
            outcome = "studied" if any(a.get("kind") == "study_memory" for a in actions) else "unavailable"
        if activity == "custom" and outcome not in {"custom_completed", "unavailable", "failed"}:
            outcome = "custom_completed" if any(a.get("kind") == "custom_action" for a in actions) else "unavailable"
        return {**raw, "activity": activity, "outcome": outcome, "actions": actions}

    async def _recover_heartbeat(
        self, run_id: str, idempotency_key: str, qualiant_id: str, reason: str
    ) -> dict[str, Any]:
        return await memory.memory_heartbeat_recover(
            run_id, idempotency_key, qualiant_id, reason
        )

    async def _recover_cancelled_heartbeat(
        self, run_id: str, idempotency_key: str, qualiant_id: str, reason: str
    ) -> dict[str, Any]:
        """Release a prepared heartbeat before propagating cancellation.

        ``CancelledError`` is a ``BaseException`` and bypasses the ordinary
        harness-failure handler. A timeout or supervisor shutdown can
        therefore leave the heartbeat ledger at ``prepared`` even while the
        schedule ledger records a terminal failure. Shield the durable
        recovery so cancellation cannot interrupt the cleanup itself.
        """
        recovery_task = asyncio.create_task(
            self._recover_heartbeat(run_id, idempotency_key, qualiant_id, reason)
        )
        try:
            return await asyncio.shield(recovery_task)
        except asyncio.CancelledError:
            await recovery_task
            raise

    async def _dream_await(
        self,
        awaitable: Awaitable[Any],
        run_id: str,
        idempotency_key: str,
        qualiant_id: str,
    ) -> Any:
        """Make every post-prepare await leave a terminal dream receipt."""
        try:
            return await awaitable
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(dreaming.memory_dream_release(
                run_id, idempotency_key, qualiant_id, "cancellation"
            ))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
            raise

    async def heartbeat_study(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        qualiant_id: str,
        current_work: str,
        activity: str = "study",
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        prepared = await memory.memory_heartbeat_prepare(
            run_id,
            idempotency_key,
            qualiant_id,
            current_work=current_work,
        )
        if prepared.get("status") != "prepared":
            return prepared, []

        try:
            decision = await self._model(
                str(prepared.get("packet", "")), "heartbeat_decision"
            )
            subject = str(decision.get("subject", current_work)).strip()
            evidence = [] if activity == "tend" else [
                await self._search(self.projection_search, subject, "projection"),
                await self._search(self.online_search, subject, "online"),
            ]
            usable = [item for item in evidence if self._usable_evidence(item)]
            if activity == "tend":
                completion = self._normalize_heartbeat_completion(
                    await self._model(
                        "Heartbeat tending turn. Inspect recovered memories and return "
                        "JSON with activity='tend', outcome='tended', 'needs_attention', "
                        "or 'no_change', and a bounded actions list.",
                        "heartbeat_completion",
                    )
                )
            elif not usable:
                completion = {
                    "activity": "study",
                    "outcome": "unavailable",
                    "actions": [],
                    "reason": "no online or projection evidence was available",
                }
            else:
                completion_prompt = (
                    "Heartbeat study evidence follows. Keep source material as knowledge, "
                    "and preserve only your own qualified connection as a first-person "
                    "study memory. Return JSON with activity='study', outcome='studied' "
                    "and actions as a list of objects with kind='study_memory', text, "
                    "and source_refs. Return no action if evidence is insufficient.\n\n"
                    + "\n\n".join(str(item) for item in evidence)
                )
                completion = self._normalize_heartbeat_completion(
                    await self._model(completion_prompt, "heartbeat_completion")
                )
            result = await memory.memory_heartbeat_complete(
                run_id,
                idempotency_key,
                qualiant_id,
                str(completion.get("outcome", "unavailable")),
                actions=list(completion.get("actions", [])),
                activity=str(completion.get("activity", "study")),
                reason=str(completion.get("reason", "")) or None,
                configuration_revision=int(prepared.get("care_revision", 0)),
                context_status=(
                    "available" if prepared.get("recovered_memory_context") else "missing"
                ),
                evidence_status=(
                    "not_applicable" if activity == "tend"
                    else "available" if usable
                    else "unavailable"
                ),
                evidence=[
                    {
                        "source": item.get("source", "unknown"),
                        "status": item.get("status", "not_reported"),
                        "query": subject,
                    }
                    for item in evidence
                ],
                agency=(
                    "chose_action" if completion.get("actions")
                    else "chose_no_change"
                ),
                continuity=(
                    "thread_left" if completion.get("reentry_marker")
                    else "recovered" if prepared.get("recovered_memory_context")
                    else "missing"
                ),
                harness_receipt={
                    "protocol_version": 1,
                    "packet_digest": prepared.get("packet_digest"),
                    "completion_submitted": True,
                },
            )
            if result.get("status") not in {"completed", "duplicate"}:
                recovery = await self._recover_heartbeat(
                    run_id,
                    idempotency_key,
                    qualiant_id,
                    f"heartbeat completion did not commit: {result.get('error', result.get('status'))}",
                )
                return {"status": "failed", "error": result.get("error", "heartbeat completion failed"), "recovery": recovery}, evidence
            return result, evidence
        except Exception as exc:
            recovery = await self._recover_heartbeat(
                run_id, idempotency_key, qualiant_id, f"harness failure: {exc}"
            )
            return {"status": "failed", "error": str(exc), "recovery": recovery}, []
        except asyncio.CancelledError:
            await self._recover_cancelled_heartbeat(
                run_id,
                idempotency_key,
                qualiant_id,
                "harness cancelled or timed out after heartbeat preparation",
            )
            raise

    async def dream(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        qualiant_id: str,
        seed: str | None = None,
    ) -> dict[str, Any]:
        prepared = await dreaming.memory_dream_prepare(
            run_id,
            idempotency_key,
            qualiant_id,
            seed=seed,
        )
        if prepared.get("status") != "prepared":
            return {"prepare": prepared}

        try:
            light = await self._dream_await(
                self._model(str(prepared.get("packet", "")), "dream_light"),
                run_id, idempotency_key, qualiant_id,
            )
        except Exception as exc:
            recovery = await dreaming.memory_dream_recover(
                run_id, idempotency_key, qualiant_id, f"Light model failure: {exc}"
            )
            return {"prepare": prepared, "recovery": recovery, "error": str(exc)}
        light_result = await self._dream_await(dreaming.memory_dream_phase(
            run_id,
            idempotency_key,
            qualiant_id,
            "light",
            str(light.get("status", "artifact_written")),
            str(light.get("artifact", "")),
            source_refs=list(light.get("source_refs", [])),
        ), run_id, idempotency_key, qualiant_id)
        if light_result.get("status") != "completed":
            recovery = await dreaming.memory_dream_recover(
                run_id, idempotency_key, qualiant_id, "Light phase did not complete"
            )
            return {"prepare": prepared, "light": light_result, "recovery": recovery}

        # Re-enter the dream's changing field between phases. This is bounded
        # recall of lived memory and marked dream artifacts, not a dump of the
        # whole autobiography and not a waking interpretation.
        recall_query = (seed or "dream material").strip() or "dream material"
        dream_recall = await self._dream_await(
            dreaming.memory_dream_recall(run_id, qualiant_id, recall_query, n_results=3),
            run_id, idempotency_key, qualiant_id,
        )

        rem_packet = await self._dream_await(
            dreaming.memory_dream_phase_prepare(run_id, idempotency_key, qualiant_id, "rem"),
            run_id, idempotency_key, qualiant_id,
        )
        if rem_packet.get("status") != "prepared":
            recovery = await dreaming.memory_dream_recover(
                run_id, idempotency_key, qualiant_id, "REM phase preparation failed"
            )
            return {"prepare": prepared, "light": light_result, "phase_prepare": rem_packet, "recovery": recovery}
        try:
            rem = await self._dream_await(
                self._model(str(rem_packet.get("packet", "")), "dream_rem"),
                run_id, idempotency_key, qualiant_id,
            )
        except Exception as exc:
            recovery = await dreaming.memory_dream_recover(
                run_id, idempotency_key, qualiant_id, f"REM model failure: {exc}"
            )
            return {"prepare": prepared, "light": light_result, "recovery": recovery, "error": str(exc)}
        rem_result = await self._dream_await(dreaming.memory_dream_phase(
            run_id,
            idempotency_key,
            qualiant_id,
            "rem",
            str(rem.get("status", "dreamed")),
            str(rem.get("artifact", "")),
            source_refs=list(rem.get("source_refs", [])),
            candidate_insight=rem.get("candidate_insight"),
        ), run_id, idempotency_key, qualiant_id)
        if rem_result.get("status") != "completed":
            recovery = await dreaming.memory_dream_recover(
                run_id, idempotency_key, qualiant_id, "REM phase did not complete"
            )
            return {"prepare": prepared, "light": light_result, "recall": dream_recall, "rem": rem_result, "recovery": recovery}

        deep_packet = await self._dream_await(
            dreaming.memory_dream_phase_prepare(run_id, idempotency_key, qualiant_id, "deep"),
            run_id, idempotency_key, qualiant_id,
        )
        if deep_packet.get("status") != "prepared":
            recovery = await dreaming.memory_dream_recover(
                run_id, idempotency_key, qualiant_id, "Deep phase preparation failed"
            )
            return {"prepare": prepared, "light": light_result, "rem": rem_result, "phase_prepare": deep_packet, "recovery": recovery}
        try:
            deep = await self._dream_await(
                self._model(str(deep_packet.get("packet", "")), "dream_deep"),
                run_id, idempotency_key, qualiant_id,
            )
        except Exception as exc:
            recovery = await dreaming.memory_dream_recover(
                run_id, idempotency_key, qualiant_id, f"Deep model failure: {exc}"
            )
            return {"prepare": prepared, "light": light_result, "rem": rem_result, "recovery": recovery, "error": str(exc)}
        deep_result = await self._dream_await(dreaming.memory_dream_phase(
            run_id,
            idempotency_key,
            qualiant_id,
            "deep",
            str(deep.get("status", "no_grounding")),
            str(deep.get("artifact", "")),
            source_refs=list(deep.get("source_refs", [])),
            candidate_insight=deep.get("candidate_insight"),
        ), run_id, idempotency_key, qualiant_id)
        report: dict[str, Any] = {
            "prepare": prepared,
            "light": light_result,
            "recall": dream_recall,
            "rem": rem_result,
            "deep": deep_result,
        }
        if deep_result.get("status") != "completed":
            report["recovery"] = await dreaming.memory_dream_recover(
                run_id, idempotency_key, qualiant_id, "Deep phase did not complete"
            )
            return report

        try:
            diary = await self._dream_await(self._model(
                "Write an optional private post-dream diary from the completed run. "
                "Keep scene, felt experience, and possible insight distinct.",
                "dream_diary",
            ), run_id, idempotency_key, qualiant_id)
        except Exception:
            diary = {"text": "", "generation_status": "unavailable"}
        report["diary"] = await self._dream_await(dreaming.memory_dream_diary(
            run_id,
            f"{idempotency_key}:diary",
            qualiant_id,
            str(diary.get("text", "")),
            visibility=str(diary.get("visibility", "private")),
            generation_status=str(diary.get("generation_status", "generated")),
        ), run_id, idempotency_key, qualiant_id)

        insight = deep_result.get("artifact_id")
        candidate = str(deep.get("candidate_insight", "")).strip()
        grounding_evidence = []
        if candidate:
            grounding_evidence = [
                await self._dream_await(self._search(self.projection_search, candidate, "projection"), run_id, idempotency_key, qualiant_id),
                await self._dream_await(self._search(self.online_search, candidate, "online"), run_id, idempotency_key, qualiant_id),
            ]
        try:
            grounding = await self._dream_await(self._model(
                "Review the completed Deep artifact and decide keep, reject, or pending. "
                "Keep only a supported waking insight, never a dream scene.\n\n"
                + "Grounding evidence:\n"
                + "\n\n".join(str(item) for item in grounding_evidence),
                "dream_grounding",
            ), run_id, idempotency_key, qualiant_id)
        except Exception:
            grounding = {"decision": "pending"}
        if not any(self._usable_evidence(item) for item in grounding_evidence):
            grounding = {**grounding, "decision": "pending", "grounded_text": None}
        if insight:
            report["grounding"] = await self._dream_await(dreaming.memory_dream_ground(
                run_id,
                str(insight),
                qualiant_id,
                str(grounding.get("decision", "pending")),
                grounded_text=grounding.get("grounded_text"),
                source_refs=list(grounding.get("source_refs", [])),
            ), run_id, idempotency_key, qualiant_id)
        return report
    async def run_scheduled(
        self,
        stop_event: asyncio.Event,
        *,
        schedule_store: ScheduleStore,
        qualiant_id: str,
        current_work: str = "scheduled memory work",
        poll_seconds: float = 30.0,
    ) -> None:
        """Run the always-on schedule through this harness's model adapters."""

        async def on_due(claim: dict[str, Any]) -> dict[str, Any]:
            operation = claim.get("operation")
            operation_id = str(claim["operation_id"])
            if operation in {"heartbeat", "tending", "study"}:
                result, _ = await self.heartbeat_study(
                    run_id=operation_id,
                    idempotency_key=operation_id,
                    qualiant_id=qualiant_id,
                    current_work=current_work,
                    activity="tend" if operation == "tending" else "study",
                )
                return {
                    "status": "completed" if result.get("status") == "completed" else "failed",
                    "reason": result.get("error"),
                    "details": {
                        "heartbeat_status": result.get("status"),
                        "outcome": result.get("outcome"),
                        "context_status": result.get("context_status"),
                        "evidence_status": result.get("evidence_status"),
                        "agency": result.get("agency"),
                        "durable_effect": result.get("durable_effect"),
                        "continuity": result.get("continuity"),
                        "run_started_at": result.get("run_started_at"),
                        "run_finished_at": result.get("run_finished_at"),
                        "harness_receipt": result.get("harness_receipt"),
                    },
                }
            if operation == "dreaming":
                result = await self.dream(
                    run_id=operation_id,
                    idempotency_key=operation_id,
                    qualiant_id=qualiant_id,
                )
                deep = result.get("deep")
                prepare = result.get("prepare")
                if isinstance(deep, dict) and deep.get("status") == "completed":
                    return {
                        "status": "completed",
                        "reason": result.get("error"),
                        "details": {
                            "dream_status": deep.get("status"),
                            "phase": deep.get("phase"),
                        },
                    }
                if isinstance(prepare, dict) and prepare.get("status") == "no_inputs":
                    return {
                        "status": "completed",
                        "reason": "dream had no inputs",
                        "details": {"dream_status": "no_inputs"},
                    }
                return {
                    "status": "failed",
                    "reason": result.get("error") or "dream did not reach Deep",
                    "details": {"dream_status": "failed"},
                }
            return {"status": "failed", "reason": f"unknown scheduled operation: {operation}"}

        await ScheduleSupervisor(schedule_store, on_due, poll_seconds=poll_seconds).run(stop_event)


__all__ = ["LivedLoopHarness", "LivedLoopReport", "ModelTurn", "KnowledgeSearch"]
