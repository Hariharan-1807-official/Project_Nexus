"""
Docker integration — container status, logs, compose inspection.

Uses `docker` CLI via subprocess (argument lists, never shell strings — ADR-010).
Degrades gracefully if Docker is not installed or daemon not running.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from nexus.models.diagnosis import ContainerStatus


# ---------------------------------------------------------------------------
# Docker availability
# ---------------------------------------------------------------------------

def docker_available() -> bool:
    """Check if Docker CLI is installed and the daemon is responding."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def docker_installed() -> bool:
    """Check if the docker command exists on PATH (daemon may not be running)."""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Container listing
# ---------------------------------------------------------------------------

def list_containers(all_containers: bool = True) -> list[ContainerStatus]:
    """
    Return a list of ContainerStatus for running (or all) containers.
    Uses `docker ps --format json` for structured output.
    """
    cmd = ["docker", "ps", "--format", "{{json .}}"]
    if all_containers:
        cmd.append("-a")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    containers = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            containers.append(ContainerStatus(
                name    = data.get("Names", data.get("Name", "?")),
                image   = data.get("Image", "?"),
                status  = data.get("Status", "?"),
                state   = data.get("State"),
                ports   = data.get("Ports", ""),
                created = data.get("CreatedAt", data.get("Created")),
            ))
        except (json.JSONDecodeError, Exception):
            continue

    return containers


# ---------------------------------------------------------------------------
# Container logs
# ---------------------------------------------------------------------------

def get_container_logs(name: str, lines: int = 50) -> str:
    """
    Fetch the last N lines of logs from a container.
    Returns the log text, or an error message.
    """
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), name],
            capture_output=True, text=True, timeout=15,
        )
        # docker logs sends output to both stdout and stderr depending on the stream
        return (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return "Docker CLI not found."
    except subprocess.TimeoutExpired:
        return "Timeout reading container logs."
    except OSError as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Compose inspection
# ---------------------------------------------------------------------------

def find_compose_file(root: Path) -> Optional[Path]:
    """Find docker-compose file in the project root."""
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        path = root / name
        if path.exists():
            return path
    return None


def inspect_compose(root: Path) -> dict:
    """
    Parse docker-compose file for service definitions, depends_on,
    healthcheck config.  Returns a structured dict.
    
    Uses `docker compose config` for normalized output, falls back
    to raw YAML parsing.
    """
    compose_file = find_compose_file(root)
    if compose_file is None:
        return {"found": False, "file": None, "services": {}}

    # Try `docker compose config` for canonical representation
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
            capture_output=True, text=True, timeout=15,
            cwd=str(root),
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            services = {}
            for svc_name, svc in data.get("services", {}).items():
                services[svc_name] = {
                    "image":       svc.get("image"),
                    "build":       svc.get("build"),
                    "ports":       svc.get("ports", []),
                    "depends_on":  list(svc.get("depends_on", {}).keys())
                                   if isinstance(svc.get("depends_on"), dict)
                                   else svc.get("depends_on", []),
                    "healthcheck": svc.get("healthcheck"),
                    "environment": list(svc.get("environment", {}).keys())
                                   if isinstance(svc.get("environment"), dict)
                                   else [e.split("=")[0] for e in svc.get("environment", [])
                                         if isinstance(e, str)],
                }
            return {
                "found": True,
                "file":  str(compose_file),
                "services": services,
            }
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass

    # Fallback: basic text parsing (no YAML dependency)
    try:
        text = compose_file.read_text(encoding="utf-8")
        return {
            "found":    True,
            "file":     str(compose_file),
            "services": _parse_compose_text(text),
        }
    except Exception:
        return {"found": True, "file": str(compose_file), "services": {}}


def _parse_compose_text(text: str) -> dict:
    """
    Very basic text-level extraction of service names and depends_on
    from a docker-compose YAML file.  Not a full YAML parser — just
    enough for diagnostics evidence.
    """
    services = {}
    current_service = None
    in_depends = False

    for line in text.splitlines():
        stripped = line.strip()

        # Top-level services block detection
        if stripped == "services:" or stripped.startswith("services:"):
            continue

        # Service name (2-space indent, ends with colon)
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            current_service = stripped[:-1].strip()
            services[current_service] = {
                "depends_on": [],
                "healthcheck": None,
                "has_healthcheck": "healthcheck:" in text,  # rough signal
            }
            in_depends = False
            continue

        if current_service and "depends_on:" in stripped:
            in_depends = True
            continue

        if in_depends and stripped.startswith("- "):
            dep = stripped[2:].strip().rstrip(":")
            services[current_service]["depends_on"].append(dep)
            continue

        if in_depends and not stripped.startswith("-") and stripped:
            in_depends = False

    return services
