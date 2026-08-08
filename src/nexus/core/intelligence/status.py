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


def explain_project(root: Optional[Path] = None) -> str:
    """
    Generate an intelligent narrative summary of the project.
    
    Reads documentation files (README.md, document/README.md, pyproject.toml)
    and uses LLM API to summarize project purpose, architecture, and current status.
    """
    r = (root or Path.cwd()).resolve()
    status = get_status(r)
    root_name = r.name

    # 1. Search for project documentation files
    doc_content = ""
    candidate_docs = [
        r / "README.md",
        r / "document" / "README.md",
        r / "pyproject.toml",
        r / "package.json",
    ]
    for doc_path in candidate_docs:
        if doc_path.exists():
            try:
                text = doc_path.read_text(encoding="utf-8").strip()
                if text:
                    doc_content += f"--- {doc_path.name} ---\n{text[:1500]}\n\n"
            except Exception:
                pass

    # 2. Try LLM API summary if key is available
    from nexus.core.router.llm_router import load_groq_api_key
    api_key = load_groq_api_key(r)
    if api_key:
        try:
            llm_summary = _explain_with_llm(root_name, status, doc_content, api_key)
            if llm_summary:
                return llm_summary
        except Exception:
            pass

    # 3. Structural fallback summary
    return _explain_fallback(root_name, status)


def _explain_with_llm(root_name: str, status: dict, doc_content: str, api_key: str) -> Optional[str]:
    """Call LLM API to generate executive summary based on documentation and project status."""
    import json
    import urllib.request
    import urllib.error

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Nexus-Control-Plane/1.0",
    }

    system_prompt = (
        "You are Nexus Intelligence Assistant. Provide a concise, professional executive summary of the software project.\n"
        "Summarize:\n"
        "1. Project Purpose & Core Architecture (based on README/docs provided).\n"
        "2. Stack & Framework Highlights.\n"
        "3. Current Status & Recent Activity.\n"
        "Keep the output clean, structured, and easy to read. Do not include markdown codeblocks or quotes."
    )

    user_content = (
        f"Project Name: {root_name}\n"
        f"Status Context: {json.dumps(status)}\n\n"
        f"Documentation Excerpts:\n{doc_content if doc_content else 'No README.md found.'}"
    )

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": 450,
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=12) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        summary = body["choices"][0]["message"]["content"].strip()
        return summary

    return None


def _explain_fallback(root_name: str, status: dict) -> str:
    """Structural narrative summary when LLM is unavailable."""
    lines = []
    ctx   = status.get("context") or {}

    if "languages" in ctx:
        langs  = ctx.get("languages", [])
        frames = ctx.get("frameworks", [])
        tools  = ctx.get("tools", [])
        struct = ctx.get("structure", {})
        git    = ctx.get("git", {})

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
