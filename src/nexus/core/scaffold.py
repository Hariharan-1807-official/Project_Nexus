"""
nexus init — creates the .nexus/ folder structure for a project.

Rules (ADR-003):
- If .nexus/ already exists, existing files are never overwritten.
- New directories and missing stub files are created silently.
"""

from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Canonical .nexus/ structure
# ---------------------------------------------------------------------------

# Directories that must exist (created if absent, never removed)
_REQUIRED_DIRS = [
    ".nexus/project",
    ".nexus/tasks",
    ".nexus/memory",
    ".nexus/config",
]

# Files that are created only when they don't already exist.
# Values are the default JSON content (None = empty file).
_DEFAULT_FILES: dict[str, object] = {
    # project context — written by `nexus scan`; stub here so the key exists
    ".nexus/project/context.json": None,
    # human-authored notes — start empty
    ".nexus/project/architecture.md": None,
    ".nexus/project/conventions.md": None,
    # config stubs — real content written by user or later commands
    ".nexus/config/agents.json": {
        "agents": [
            {"name": "codex",       "enabled": True,  "executable": "codex"},
            {"name": "antigravity", "enabled": True,  "executable": "agy"},
            {"name": "kiro",        "enabled": True,  "executable": "kiro"},
            {"name": "cursor",      "enabled": False, "executable": "cursor"},
        ]
    },
    ".nexus/config/router.json": {
        "rules": [
            {
                "task_type": "backend_coding",
                "signals": ["api", "backend", "database", "server", "endpoint"],
                "preferred_agents": ["codex", "antigravity"],
            },
            {
                "task_type": "frontend_ui",
                "signals": ["component", "ui", "layout", "styling", "frontend"],
                "preferred_agents": ["kiro", "cursor", "antigravity"],
            },
            {
                "task_type": "research",
                "signals": ["research", "compare", "investigate options", "what should we use"],
                "preferred_agents": ["antigravity"],
            },
            {
                "task_type": "github_issue",
                "signals": ["issue", "bug report", "github"],
                "preferred_agents": ["codex", "antigravity"],
            },
            {
                "task_type": "testing",
                "signals": ["test", "coverage", "unit test", "integration test"],
                "preferred_agents": ["codex"],
            },
            {
                "task_type": "documentation",
                "signals": ["docs", "readme", "documentation", "comment"],
                "preferred_agents": ["antigravity", "codex"],
            },
            {
                "task_type": "review",
                "signals": ["review", "audit", "check this"],
                "preferred_agents": ["antigravity", "codex"],
            },
            {
                "task_type": "devops",
                "signals": ["docker", "deploy", "ci", "pipeline", "compose"],
                "preferred_agents": ["codex", "antigravity"],
            },
        ],
        "default_agent": "codex",
        "fallback_on_unavailable": True,
    },
    ".nexus/config/permissions.json": {
        "codex": {
            "read_source":       "allow",
            "write_source":      "approval",
            "execute_commands":  "approval",
            "git_push":          "approval",
            "delete_files":      "approval",
            "network":           "deny",
        },
        "antigravity": {
            "read_source":       "allow",
            "write_source":      "approval",
            "execute_commands":  "approval",
            "git_push":          "approval",
            "delete_files":      "approval",
            "network":           "deny",
        },
        "kiro": {
            "read_source":       "allow",
            "write_source":      "approval",
            "execute_commands":  "approval",
            "git_push":          "approval",
            "delete_files":      "approval",
            "network":           "deny",
        },
        "cursor": {
            "read_source":       "allow",
            "write_source":      "approval",
            "execute_commands":  "approval",
            "git_push":          "approval",
            "delete_files":      "approval",
            "network":           "deny",
        },
    },
    ".nexus/config/daemon.json": {
        "watchers": {
            "git":          {"mode": "event",    "trigger": "on_commit"},
            "tests":        {"mode": "interval", "interval_seconds": 300},
            "dependencies": {"mode": "interval", "interval_seconds": 86400},
            "security":     {"mode": "interval", "interval_seconds": 86400},
            "github":       {"mode": "interval", "interval_seconds": 120},
            "docker":       {"mode": "interval", "interval_seconds": 30},
        },
        "global": {
            "enabled":           False,
            "auto_fix_attempt":  False,
        },
    },
}


def init_project(project_root: Path) -> tuple[bool, list[str]]:
    """
    Create the .nexus/ structure under `project_root`.

    Returns:
        (already_existed, created_paths)
        already_existed — True if .nexus/ was already present before this call
        created_paths   — list of paths actually created this call
    """
    nexus_dir = project_root / ".nexus"
    already_existed = nexus_dir.exists()
    created: list[str] = []

    # 1. Create required directories
    for rel_dir in _REQUIRED_DIRS:
        target = project_root / rel_dir
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(target.relative_to(project_root)))

    # 2. Create default files only if they don't already exist
    for rel_path, content in _DEFAULT_FILES.items():
        target = project_root / rel_path
        if not target.exists():
            if content is None:
                target.touch()
            else:
                target.write_text(
                    json.dumps(content, indent=2),
                    encoding="utf-8",
                )
            created.append(str(Path(rel_path)))

    return already_existed, created
