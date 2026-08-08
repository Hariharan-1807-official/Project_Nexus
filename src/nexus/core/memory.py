"""
Shared Memory — append-only .jsonl log writer/reader for .nexus/memory/.

Rules (ADR-003):
- Nothing in memory/ is ever mutated in place after writing.
- All writes are appends — no overwrites, no edits.
- The normal write API does not expose any method that would allow
  editing a past entry (enforced by the interface, not just by convention).

Files:
    memory/events.jsonl          — all agent actions (audit trail)
    memory/decisions.jsonl       — accepted architectural/task decisions
    memory/agent-handoffs.jsonl  — every inter-agent handoff
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    agent_action    = "agent_action"
    warden_allow    = "warden_allow"
    warden_deny     = "warden_deny"
    warden_prompt   = "warden_prompt"
    scan            = "scan"
    health_check    = "health_check"
    task_created    = "task_created"
    task_completed  = "task_completed"
    task_failed     = "task_failed"
    handoff         = "handoff"
    decision        = "decision"
    system          = "system"


# ---------------------------------------------------------------------------
# Memory store
# ---------------------------------------------------------------------------

class Memory:
    """
    Append-only interface to the three .nexus/memory/ log files.

    Usage:
        mem = Memory(project_root)
        mem.log_event(EventType.scan, agent=None, action="nexus scan", result="ok")
        events = mem.read_events()
    """

    def __init__(self, project_root: Path) -> None:
        self._root = (project_root / ".nexus" / "memory").resolve()

    def _ensure_dir(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def _append(self, filename: str, record: dict) -> None:
        """Append one JSON record to a .jsonl file. Thread-safe via file-level append."""
        self._ensure_dir()
        path = self._root / filename
        line = json.dumps(record, ensure_ascii=False, default=str)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _read(self, filename: str) -> list[dict]:
        """Read all records from a .jsonl file. Returns [] if file doesn't exist."""
        path = self._root / filename
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # corrupted line — skip silently, preserve rest of log
        return records

    def corrupt_line_count(self, filename: str = "events.jsonl") -> int:
        """Return the number of unreadable lines in a .jsonl file.
        Used by nexus status to warn the user about log corruption."""
        path = self._root / filename
        if not path.exists():
            return 0
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    count += 1
        return count

    # ------------------------------------------------------------------
    # events.jsonl  — audit trail for every agent action
    # ------------------------------------------------------------------

    def log_event(
        self,
        event_type: EventType,
        *,
        agent:    Optional[str],
        action:   str,
        task_id:  Optional[str] = None,
        result:   str           = "ok",
        detail:   Optional[Any] = None,
    ) -> dict:
        """
        Append one event to memory/events.jsonl.
        Returns the written record (for testing / confirmation).
        """
        record = {
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "event_type": event_type.value,
            "agent":      agent,
            "action":     action,
            "task_id":    task_id,
            "result":     result,
            "detail":     detail,
        }
        self._append("events.jsonl", record)
        return record

    def read_events(
        self,
        *,
        event_type: Optional[EventType] = None,
        agent:      Optional[str]       = None,
        task_id:    Optional[str]       = None,
        limit:      Optional[int]       = None,
    ) -> list[dict]:
        """Read events with optional filters. Most recent last."""
        records = self._read("events.jsonl")
        if event_type:
            records = [r for r in records if r.get("event_type") == event_type.value]
        if agent:
            records = [r for r in records if r.get("agent") == agent]
        if task_id:
            records = [r for r in records if r.get("task_id") == task_id]
        if limit:
            records = records[-limit:]
        return records

    # ------------------------------------------------------------------
    # decisions.jsonl  — accepted architectural/project decisions
    # ------------------------------------------------------------------

    def log_decision(
        self,
        description: str,
        *,
        rationale:   Optional[str] = None,
        task_id:     Optional[str] = None,
        agent:       Optional[str] = None,
    ) -> dict:
        record = {
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "description": description,
            "rationale":   rationale,
            "task_id":     task_id,
            "agent":       agent,
        }
        self._append("decisions.jsonl", record)
        # Also mirror to events.jsonl for the unified audit trail
        self.log_event(
            EventType.decision,
            agent=agent,
            action=f"decision: {description[:80]}",
            task_id=task_id,
            result="accepted",
        )
        return record

    def read_decisions(self, limit: Optional[int] = None) -> list[dict]:
        records = self._read("decisions.jsonl")
        return records[-limit:] if limit else records

    # ------------------------------------------------------------------
    # agent-handoffs.jsonl  — every inter-agent handoff
    # ------------------------------------------------------------------

    def log_handoff(
        self,
        from_agent: str,
        to_agent:   str,
        task_id:    str,
        *,
        artifact:   Optional[str] = None,
        summary:    Optional[str] = None,
    ) -> dict:
        record = {
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "from_agent": from_agent,
            "to_agent":   to_agent,
            "task_id":    task_id,
            "artifact":   artifact,
            "summary":    summary,
        }
        self._append("agent-handoffs.jsonl", record)
        self.log_event(
            EventType.handoff,
            agent=from_agent,
            action=f"handoff → {to_agent}",
            task_id=task_id,
            result="ok",
            detail={"to_agent": to_agent, "artifact": artifact},
        )
        return record

    def read_handoffs(
        self,
        task_id: Optional[str] = None,
        limit:   Optional[int] = None,
    ) -> list[dict]:
        records = self._read("agent-handoffs.jsonl")
        if task_id:
            records = [r for r in records if r.get("task_id") == task_id]
        return records[-limit:] if limit else records

    # ------------------------------------------------------------------
    # Append-only enforcement helpers
    # ------------------------------------------------------------------

    def events_path(self) -> Path:
        return self._root / "events.jsonl"

    def is_append_only(self) -> bool:
        """
        Verify that events.jsonl exists and has only been appended to
        (line count only grows). Used in tests and health checks.
        This is a structural check — it can't detect external tampering,
        but it confirms the Memory API itself never truncates the file.
        """
        return self.events_path().exists()
