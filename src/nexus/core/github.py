"""
GitHub integration — issue fetch, PR creation, repo info.

Uses `gh` CLI (GitHub's official CLI) via subprocess (argument lists, never
shell strings — ADR-010).  Degrades gracefully if `gh` is not installed or
not authenticated.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from nexus.models.diagnosis import GitHubIssue, PRResult


# ---------------------------------------------------------------------------
# gh CLI availability
# ---------------------------------------------------------------------------

def gh_available() -> bool:
    """Check if `gh` CLI is installed and authenticated."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def gh_installed() -> bool:
    """Check if `gh` command exists on PATH."""
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Repo info
# ---------------------------------------------------------------------------

def get_repo_info(cwd: Optional[Path] = None) -> dict:
    """
    Get current repository info: name, default branch, remote URL.
    Returns empty dict if not in a git repo or gh not available.
    """
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "name,defaultBranchRef,url,owner"],
            capture_output=True, text=True, timeout=15,
            cwd=str(cwd) if cwd else None,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        return {
            "name":           data.get("name", ""),
            "owner":          data.get("owner", {}).get("login", ""),
            "url":            data.get("url", ""),
            "default_branch": data.get("defaultBranchRef", {}).get("name", "main"),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Issue fetching
# ---------------------------------------------------------------------------

def fetch_issue(number: int, cwd: Optional[Path] = None) -> Optional[GitHubIssue]:
    """
    Fetch a GitHub issue by number using `gh issue view`.
    Returns a GitHubIssue model, or None on failure.
    """
    try:
        result = subprocess.run(
            ["gh", "issue", "view", str(number),
             "--json", "number,title,body,labels,state,assignees,url"],
            capture_output=True, text=True, timeout=15,
            cwd=str(cwd) if cwd else None,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)

        labels = []
        for lbl in data.get("labels", []):
            if isinstance(lbl, dict):
                labels.append(lbl.get("name", str(lbl)))
            else:
                labels.append(str(lbl))

        assignees = []
        for a in data.get("assignees", []):
            if isinstance(a, dict):
                assignees.append(a.get("login", str(a)))
            else:
                assignees.append(str(a))

        issue = GitHubIssue(
            number    = data.get("number", number),
            title     = data.get("title", ""),
            body      = data.get("body"),
            labels    = labels,
            state     = data.get("state", "open"),
            assignees = assignees,
            url       = data.get("url"),
        )

        # Add agent recommendation
        agent, reason = recommend_agent_for_issue(issue)
        issue.recommended_agent = agent
        issue.recommendation_reason = reason

        return issue

    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Agent recommendation (signal-based, matches router.json)
# ---------------------------------------------------------------------------

# Default routing signals — mirrors router.json from System Architecture §6a
_ROUTING_SIGNALS: list[tuple[str, list[str], str]] = [
    ("backend_coding", ["api", "backend", "database", "server", "endpoint", "auth"], "codex"),
    ("frontend_ui",    ["component", "ui", "layout", "styling", "frontend", "css"], "antigravity"),
    ("research",       ["research", "compare", "investigate", "evaluate", "options"], "antigravity"),
    ("github_issue",   ["issue", "bug", "error", "crash", "fix"], "codex"),
    ("testing",        ["test", "coverage", "unit test", "integration test"], "codex"),
    ("documentation",  ["docs", "readme", "documentation", "comment"], "antigravity"),
    ("devops",         ["docker", "deploy", "ci", "pipeline", "compose", "kubernetes"], "codex"),
]


def recommend_agent_for_issue(issue: GitHubIssue) -> tuple[str, str]:
    """
    Simple signal-based routing: match issue title + labels against signals.
    Returns (agent_name, reason).
    """
    text = f"{issue.title} {' '.join(issue.labels)}".lower()

    best_match = None
    best_score = 0

    for task_type, signals, default_agent in _ROUTING_SIGNALS:
        score = sum(1 for s in signals if s in text)
        if score > best_score:
            best_score = score
            best_match = (default_agent, f"Matched {task_type} (signals: {score} hits)")

    if best_match:
        return best_match

    return ("codex", "Default agent — no strong signal match")


# ---------------------------------------------------------------------------
# PR creation
# ---------------------------------------------------------------------------

def get_current_branch(cwd: Optional[Path] = None) -> Optional[str]:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
            cwd=str(cwd) if cwd else None,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def get_unpushed_commits(cwd: Optional[Path] = None) -> list[str]:
    """Get list of unpushed commit messages on the current branch."""
    try:
        result = subprocess.run(
            ["git", "log", "@{u}..HEAD", "--oneline"],
            capture_output=True, text=True, timeout=10,
            cwd=str(cwd) if cwd else None,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()
        return []
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def create_pr(
    title: str,
    body: str = "",
    base: Optional[str] = None,
    cwd: Optional[Path] = None,
) -> PRResult:
    """
    Create a PR using `gh pr create`.
    
    NOTE: This function must ONLY be called after explicit user confirmation.
    The CLI layer is responsible for the confirmation prompt (ADR-002).
    """
    branch = get_current_branch(cwd)
    if not branch:
        return PRResult(
            title=title, branch="?", base=base or "?",
            error="Could not determine current branch.",
        )

    if base is None:
        repo_info = get_repo_info(cwd)
        base = repo_info.get("default_branch", "main")

    cmd = [
        "gh", "pr", "create",
        "--title", title,
        "--body", body or f"Created by Nexus from branch {branch}",
        "--base", base,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=str(cwd) if cwd else None,
        )

        if result.returncode == 0:
            url = result.stdout.strip()
            # gh pr create prints the PR URL on success
            return PRResult(
                title=title, branch=branch, base=base,
                url=url, created=True,
            )
        else:
            return PRResult(
                title=title, branch=branch, base=base,
                error=result.stderr.strip() or "PR creation failed.",
            )

    except FileNotFoundError:
        return PRResult(
            title=title, branch=branch, base=base,
            error="gh CLI not found. Install: https://cli.github.com",
        )
    except subprocess.TimeoutExpired:
        return PRResult(
            title=title, branch=branch, base=base,
            error="Timeout creating PR.",
        )
    except OSError as exc:
        return PRResult(
            title=title, branch=branch, base=base,
            error=str(exc),
        )
