"""
Diagnostics Engine — cross-source evidence correlation + root-cause hypothesis.

This is one of Nexus's two first-class components (alongside Review Handoff).
It correlates evidence from Git, Docker, project files, and environment in
one pass to produce a structured diagnosis.

Rules:
- No numeric confidence score (ADR-006).
- Output is a DiagnosisArtifact (Pydantic model).
- Feeds directly into the Agent Layer via `run(task)` for "[Ask agent to fix]".
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from nexus.models.diagnosis import DiagnosisArtifact
from nexus.core.docker import (
    docker_available, list_containers, get_container_logs,
    find_compose_file, inspect_compose,
)


# ---------------------------------------------------------------------------
# Evidence collectors
# ---------------------------------------------------------------------------

def _git_evidence(root: Path) -> list[str]:
    """Collect git-related evidence: status, recent commits, diff stats."""
    evidence = []

    def _run(args: list[str]) -> str:
        try:
            r = subprocess.run(
                ["git"] + args,
                cwd=str(root), capture_output=True, text=True, timeout=10,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    # Git status
    status = _run(["status", "--porcelain"])
    if status:
        changed = len(status.splitlines())
        evidence.append(f"Git has {changed} uncommitted change(s)")
    else:
        st = _run(["status"])
        if st:
            evidence.append("Git working tree is clean")

    # Recent commits
    log = _run(["log", "-5", "--oneline"])
    if log:
        evidence.append(f"Recent commits: {log.splitlines()[0]}")

    # Diff stat
    diff = _run(["diff", "--stat"])
    if diff:
        last_line = diff.strip().splitlines()[-1]
        evidence.append(f"Uncommitted diff: {last_line}")

    return evidence


def _project_evidence(root: Path) -> list[str]:
    """Collect project-file evidence: config, dependencies, errors."""
    evidence = []

    # Check for common config files
    for name in ("package.json", "pyproject.toml", "requirements.txt", ".env"):
        if (root / name).exists():
            evidence.append(f"Found {name}")

    # Check for missing .env vars referenced in configs
    env_file = root / ".env"
    if not env_file.exists():
        for name in ("docker-compose.yml", "docker-compose.yaml"):
            compose = root / name
            if compose.exists():
                text = compose.read_text(encoding="utf-8", errors="replace")
                if "${" in text or "$" in text:
                    evidence.append(f"{name} references env vars but no .env file found")
                break

    # Check for Python syntax errors
    py_files = list(root.rglob("*.py"))
    # Only check top-level .py files + src/ — skip .nexus, .git, node_modules
    filtered = [
        f for f in py_files
        if ".nexus" not in f.parts
        and ".git" not in f.parts
        and "node_modules" not in f.parts
        and "__pycache__" not in f.parts
    ]

    for py_file in filtered[:50]:  # cap to prevent slowness on huge repos
        try:
            compile(py_file.read_text(encoding="utf-8"), str(py_file), "exec")
        except SyntaxError as e:
            evidence.append(f"Syntax error in {py_file.name}: {e.msg} (line {e.lineno})")

    return evidence


def _docker_evidence(root: Path) -> list[str]:
    """Collect Docker-related evidence: container state, logs, compose analysis."""
    evidence = []

    if not docker_available():
        evidence.append("Docker daemon is not running or not installed")
        return evidence

    # Container states
    containers = list_containers()
    running = [c for c in containers if c.state == "running" or "Up" in c.status]
    exited  = [c for c in containers if c.state == "exited" or "Exited" in c.status]

    if containers:
        evidence.append(f"Docker: {len(running)} running, {len(exited)} exited container(s)")
    else:
        evidence.append("Docker: no containers found")

    # Exited container logs — look for error patterns
    for c in exited[:3]:  # cap at 3 to avoid slowness
        logs = get_container_logs(c.name, lines=20)
        if logs:
            lower = logs.lower()
            if any(kw in lower for kw in ("error", "fatal", "refused", "failed", "exception")):
                # Extract the most relevant error line
                for line in logs.splitlines():
                    ll = line.lower()
                    if any(kw in ll for kw in ("error", "fatal", "refused", "failed")):
                        evidence.append(f"Container {c.name} log: {line.strip()[:120]}")
                        break

    # Compose analysis
    compose_info = inspect_compose(root)
    if compose_info.get("found"):
        services = compose_info.get("services", {})
        if services:
            evidence.append(f"docker-compose defines {len(services)} service(s): {', '.join(services.keys())}")

            # Check for missing healthchecks on dependencies
            for svc_name, svc in services.items():
                deps = svc.get("depends_on", [])
                if deps:
                    for dep in deps:
                        dep_svc = services.get(dep, {})
                        if dep_svc and not dep_svc.get("healthcheck"):
                            evidence.append(
                                f"Service '{svc_name}' depends on '{dep}' which has no healthcheck"
                            )

    return evidence


def _env_evidence() -> list[str]:
    """Check for common environment variable issues."""
    evidence = []

    important_vars = [
        "DATABASE_URL", "REDIS_URL", "NODE_ENV", "PYTHONPATH",
        "PORT", "HOST", "API_KEY", "SECRET_KEY",
    ]
    set_vars = [v for v in important_vars if os.environ.get(v)]
    if set_vars:
        evidence.append(f"Environment has: {', '.join(set_vars)}")

    return evidence


# ---------------------------------------------------------------------------
# Diagnosis rules (v1 — rule-based, no ML)
# ---------------------------------------------------------------------------

def _analyze_evidence(
    git_ev: list[str],
    project_ev: list[str],
    docker_ev: list[str],
    env_ev: list[str],
) -> tuple[str, str, str]:
    """
    Analyze collected evidence and produce a (problem, root_cause, fix) tuple.
    
    Rule-based pattern matching in v1. No ML classifier.
    """
    all_evidence = git_ev + project_ev + docker_ev + env_ev
    all_text = " ".join(all_evidence).lower()

    # --- Docker startup order / healthcheck issue ---
    if ("exited" in all_text or "refused" in all_text) and "depends" in all_text:
        return (
            "Service dependency startup issue detected.",
            "A service starts before its dependency is ready. Missing healthcheck on the dependency.",
            "Add a healthcheck to the dependency service in docker-compose and configure depends_on with condition: service_healthy.",
        )

    # --- Docker container crash ---
    if "exited" in all_text and ("error" in all_text or "fatal" in all_text):
        return (
            "Docker container exited with errors.",
            "One or more containers crashed. Check container logs for the specific error.",
            "Review the container logs above, fix the error, and restart with `docker compose up`.",
        )

    # --- Python syntax error ---
    if "syntax error" in all_text:
        return (
            "Python syntax error detected in source files.",
            "One or more Python files have syntax errors preventing compilation.",
            "Fix the syntax error(s) listed in the evidence above.",
        )

    # --- Missing env vars ---
    if "env var" in all_text and "no .env" in all_text:
        return (
            "Missing environment configuration.",
            "Compose file references environment variables but no .env file exists.",
            "Create a .env file with the required variables, or set them in your shell.",
        )

    # --- Uncommitted changes with issues ---
    if "uncommitted" in all_text and ("error" in all_text or "fail" in all_text):
        return (
            "Uncommitted changes may be causing issues.",
            "There are uncommitted changes that may have introduced errors.",
            "Review the uncommitted changes, fix any issues, and commit or stash.",
        )

    # --- Docker not running ---
    if "docker daemon is not running" in all_text:
        return (
            "Docker is not running.",
            "The Docker daemon is not responding.",
            "Start Docker Desktop or run `dockerd` to start the daemon.",
        )

    # --- No clear issue ---
    if not any("error" in e.lower() or "fail" in e.lower() for e in all_evidence):
        return (
            "No obvious issues detected.",
            "All checked sources appear healthy.",
            "If you're experiencing a specific problem, provide more context with `nexus ask`.",
        )

    # --- Generic fallback ---
    return (
        "Issue detected — see evidence below.",
        "Multiple signals suggest a problem. Review the evidence list for specifics.",
        "Address the issues listed in the evidence, starting with the most recent changes.",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def diagnose(root: Path) -> DiagnosisArtifact:
    """
    Run a full diagnostic pass: collect evidence from Git, project files,
    Docker, and environment, then produce a structured DiagnosisArtifact.
    
    No numeric confidence score — qualitative only (ADR-006).
    """
    sources_checked = []

    git_ev = _git_evidence(root)
    if git_ev:
        sources_checked.append("git")

    project_ev = _project_evidence(root)
    if project_ev:
        sources_checked.append("project")

    docker_ev = _docker_evidence(root)
    if docker_ev:
        sources_checked.append("docker")

    env_ev = _env_evidence()
    if env_ev:
        sources_checked.append("environment")

    problem, root_cause, fix = _analyze_evidence(git_ev, project_ev, docker_ev, env_ev)

    return DiagnosisArtifact(
        problem           = problem,
        evidence          = git_ev + project_ev + docker_ev + env_ev,
        likely_root_cause = root_cause,
        suggested_fix     = fix,
        sources_checked   = sources_checked,
        diagnosed_at      = datetime.now(timezone.utc),
    )
