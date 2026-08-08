"""
nexus status / nexus explain — human-readable project state surface.

status()  → compact one-screen summary (git, health, last scan, recent events)
explain() → narrative paragraph describing the project and recent activity
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from nexus.core.memory import Memory, EventType


def _load_context(root: Path) -> Optional[dict]:
    ctx_path = root / ".nexus" / "project" / "context.json"
    if not ctx_path.exists():
        return None
    try:
        return json.loads(ctx_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _time_ago(iso: str) -> str:
    """Convert ISO timestamp to human-readable relative time."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 60:              return f"{s}s ago"
        if s < 3600:            return f"{s // 60}m ago"
        if s < 86400:           return f"{s // 3600}h ago"
        return                         f"{s // 86400}d ago"
    except Exception:
        return iso


def get_status(root: Path) -> dict:
    """
    Return a structured status snapshot for the project at `root`.
    Used by both `nexus status` (display) and agents (context injection).
    """
    nexus_dir = root / ".nexus"
    if not nexus_dir.exists():
        return {"error": ".nexus/ not found — run `nexus init` first"}

    ctx  = _load_context(root)
    mem  = Memory(root)

    recent_events  = mem.read_events(limit=10)
    recent_decisions = mem.read_decisions(limit=5)
    recent_handoffs  = mem.read_handoffs(limit=5)

    # Last scan time
    last_scan = None
    scan_events = mem.read_events(event_type=EventType.scan, limit=1)
    if not scan_events and ctx:
        last_scan = ctx.get("scanned_at")
    elif scan_events:
        last_scan = scan_events[-1].get("timestamp")

    return {
        "project_root":     str(root),
        "initialised":      True,
        "last_scan":        last_scan,
        "context":          ctx,
        "recent_events":    recent_events,
        "recent_decisions": recent_decisions,
        "recent_handoffs":  recent_handoffs,
    }


def explain_project(root: Path) -> str:
    """
    Generate a human-readable narrative describing the project state
    and recent activity. Used by `nexus explain`.
    """
    status = get_status(root)

    if "error" in status:
        return status["error"]

    lines: list[str] = []
    ctx = status.get("context")

    # --- Project identity ---
    root_name = Path(status["project_root"]).name
    if ctx:
        langs  = ctx.get("languages", [])
        frames = ctx.get("frameworks", [])
        tools  = ctx.get("tools", [])
        git    = ctx.get("git", {})
        struct = ctx.get("structure", {})

        lang_str  = ", ".join(langs)  if langs  else "unknown stack"
        frame_str = ", ".join(frames) if frames else None
        tool_str  = ", ".join(tools)  if tools  else None

        desc = f"Project: {root_name} ({lang_str}"
        if frame_str:
            desc += f" · {frame_str}"
        desc += ")"
        lines.append(desc)

        if struct:
            fc = struct.get("file_count", "?")
            ht = "tests present" if struct.get("has_tests") else "no tests detected"
            lines.append(f"  {fc} files · {ht}")

        if git:
            branch = git.get("branch", "")
            commit = git.get("commit", "")
            dirty  = " (uncommitted changes)" if git.get("is_dirty") else ""
            if branch:
                lines.append(f"  Git: {branch} @ {commit}{dirty}")

        if status.get("last_scan"):
            lines.append(f"  Last scan: {_time_ago(status['last_scan'])}")
    else:
        lines.append(f"Project: {root_name} (not yet scanned — run `nexus scan`)")

    # --- Recent activity ---
    events = status.get("recent_events", [])
    if events:
        lines.append("")
        lines.append("Recent activity:")
        for ev in reversed(events[-5:]):
            ts     = _time_ago(ev.get("timestamp", ""))
            agent  = ev.get("agent") or "nexus"
            action = ev.get("action", "")
            result = ev.get("result", "")
            icon   = "✓" if result == "ok" else ("✗" if result == "fail" else "•")
            lines.append(f"  {icon} [{ts}] {agent}: {action}")

    # --- Recent decisions ---
    decisions = status.get("recent_decisions", [])
    if decisions:
        lines.append("")
        lines.append("Recent decisions:")
        for d in decisions[-3:]:
            ts   = _time_ago(d.get("timestamp", ""))
            desc = d.get("description", "")
            lines.append(f"  • [{ts}] {desc}")

    if not events and not decisions:
        lines.append("")
        lines.append("No activity recorded yet.")
        lines.append("Run `nexus scan` to inspect the project, then `nexus health` to check its state.")

    return "\n".join(lines)
