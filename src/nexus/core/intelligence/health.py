"""
nexus health — project health checker.

Checks: git, build/test/lint (auto-detected), dependencies, Docker, GitHub CI.
Returns a structured HealthReport with per-check status and details.
No external dependencies — pure stdlib + subprocess.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class CheckStatus(str, Enum):
    ok      = "ok"
    warning = "warning"
    fail    = "fail"
    skip    = "skip"      # tool not present / not applicable


@dataclass
class HealthCheck:
    name:    str
    status:  CheckStatus
    summary: str
    detail:  Optional[str] = None


@dataclass
class HealthReport:
    checks: list[HealthCheck] = field(default_factory=list)

    def add(self, check: HealthCheck) -> None:
        self.checks.append(check)

    @property
    def overall(self) -> CheckStatus:
        statuses = {c.status for c in self.checks}
        if CheckStatus.fail    in statuses: return CheckStatus.fail
        if CheckStatus.warning in statuses: return CheckStatus.warning
        if all(s == CheckStatus.skip for s in statuses): return CheckStatus.skip
        return CheckStatus.ok

    def as_dict(self) -> dict:
        return {
            "overall": self.overall.value,
            "checks": [
                {
                    "name":    c.name,
                    "status":  c.status.value,
                    "summary": c.summary,
                    "detail":  c.detail,
                }
                for c in self.checks
            ],
        }


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def _run(args: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    """Run a command, return (rc, stdout, stderr). Never raises."""
    try:
        r = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", f"command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"timeout after {timeout}s"
    except Exception as exc:
        return -1, "", str(exc)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_git(root: Path) -> HealthCheck:
    if not (root / ".git").exists():
        return HealthCheck("git", CheckStatus.skip, "not a git repository")

    rc, out, err = _run(["git", "status", "--porcelain"], root)
    if rc != 0:
        return HealthCheck("git", CheckStatus.fail, "git status failed", err.strip())

    dirty_files = [l for l in out.splitlines() if l.strip()]
    if dirty_files:
        return HealthCheck(
            "git", CheckStatus.warning,
            f"{len(dirty_files)} uncommitted change(s)",
            "\n".join(dirty_files[:10]) + ("…" if len(dirty_files) > 10 else ""),
        )
    return HealthCheck("git", CheckStatus.ok, "working tree clean")


def _check_build_python(root: Path) -> Optional[HealthCheck]:
    """Try to detect and run the Python build/compile check."""
    # pyproject with pytest → run python -m py_compile on src
    if (root / "pyproject.toml").exists():
        src = root / "src"
        target = str(src) if src.is_dir() else str(root)
        rc, out, err = _run(
            ["python", "-m", "py_compile"] +
            [str(p) for p in Path(target).rglob("*.py") if ".nexus" not in str(p)][:50],
            root, timeout=20,
        )
        if rc != 0:
            return HealthCheck("build", CheckStatus.fail, "Python syntax error(s)", err.strip())
        return HealthCheck("build", CheckStatus.ok, "Python syntax OK")

    if (root / "setup.py").exists() or (root / "requirements.txt").exists():
        rc, _, err = _run(["python", "-c", "import ast; print('ok')"], root, timeout=5)
        if rc == 0:
            return HealthCheck("build", CheckStatus.ok, "Python environment OK")

    return None


def _check_build_node(root: Path) -> Optional[HealthCheck]:
    """Run npm/yarn build if a build script exists."""
    pkg = root / "package.json"
    if not pkg.exists():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})
    except Exception:
        return None

    if "build" not in scripts:
        return HealthCheck("build", CheckStatus.skip, "no build script in package.json")

    # Detect package manager
    pm = "npm"
    if (root / "yarn.lock").exists():    pm = "yarn"
    if (root / "pnpm-lock.yaml").exists(): pm = "pnpm"
    if (root / "bun.lockb").exists():    pm = "bun"

    rc, out, err = _run([pm, "run", "build", "--if-present"], root, timeout=120)
    if rc != 0:
        return HealthCheck("build", CheckStatus.fail, f"{pm} build failed", (out + err)[-500:])
    return HealthCheck("build", CheckStatus.ok, f"{pm} build passed")


def _check_tests(root: Path) -> HealthCheck:
    """Auto-detect and run the test suite."""
    # pytest
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() \
            or (root / "setup.cfg").exists() or (root / "tests").is_dir():
        rc, out, err = _run(
            ["python", "-m", "pytest", "--tb=short", "-q", "--no-header", "--disable-warnings"],
            root, timeout=180,
        )
        combined = (out + err).strip()
        # Parse summary line e.g. "12 passed" / "1 failed"
        for line in reversed(combined.splitlines()):
            if "passed" in line or "failed" in line or "error" in line:
                if "failed" in line or "error" in line:
                    return HealthCheck("tests", CheckStatus.fail, line.strip(), combined[-600:])
                return HealthCheck("tests", CheckStatus.ok, line.strip())
        if rc == 0:
            return HealthCheck("tests", CheckStatus.ok, "pytest passed")
        return HealthCheck("tests", CheckStatus.fail, "pytest failed", combined[-400:])

    # jest / vitest
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            test_cmd = scripts.get("test", "")
        except Exception:
            test_cmd = ""

        if test_cmd:
            pm = "yarn" if (root / "yarn.lock").exists() else "npm"
            rc, out, err = _run([pm, "test", "--", "--run"], root, timeout=120)
            combined = (out + err).strip()
            if rc == 0:
                return HealthCheck("tests", CheckStatus.ok, "test suite passed")
            return HealthCheck("tests", CheckStatus.fail, "test suite failed", combined[-400:])

    return HealthCheck("tests", CheckStatus.skip, "no test runner detected")


def _check_lint(root: Path) -> HealthCheck:
    """Run ruff (Python) or eslint (JS/TS) if available."""
    if (root / "pyproject.toml").exists() or (root / "ruff.toml").exists():
        rc, out, err = _run(["python", "-m", "ruff", "check", "--quiet", "."], root, timeout=30)
        if rc == -1:  # ruff not installed
            pass
        elif rc == 0:
            return HealthCheck("lint", CheckStatus.ok, "ruff: no issues")
        else:
            issues = (out + err).strip().splitlines()
            return HealthCheck(
                "lint", CheckStatus.warning,
                f"ruff: {len(issues)} issue(s)",
                "\n".join(issues[:20]),
            )

    # eslint
    eslint = root / "node_modules" / ".bin" / "eslint"
    if eslint.exists() or (root / ".eslintrc.json").exists() or (root / ".eslintrc.js").exists():
        rc, out, err = _run(["npx", "--no", "eslint", "--max-warnings=0", "."], root, timeout=60)
        if rc == 0:
            return HealthCheck("lint", CheckStatus.ok, "eslint: no issues")
        if rc != -1:
            return HealthCheck("lint", CheckStatus.warning, "eslint: issues found", (out + err)[:400])

    return HealthCheck("lint", CheckStatus.skip, "no linter detected")


def _check_dependencies(root: Path) -> HealthCheck:
    """Check for obviously outdated or broken deps (quick check only)."""
    # Python — check if packages importable
    if (root / "requirements.txt").exists():
        rc, out, err = _run(
            ["pip", "check"], root, timeout=20,
        )
        if rc == 0:
            return HealthCheck("dependencies", CheckStatus.ok, "pip: no conflicts")
        return HealthCheck("dependencies", CheckStatus.warning, "pip: dependency conflicts", err.strip())

    if (root / "pyproject.toml").exists():
        rc, out, err = _run(["pip", "check"], root, timeout=20)
        if rc == 0:
            return HealthCheck("dependencies", CheckStatus.ok, "pip: no conflicts")
        return HealthCheck("dependencies", CheckStatus.warning, "pip: dependency conflicts", (out + err)[:300])

    # Node — check node_modules exists
    if (root / "package.json").exists():
        if not (root / "node_modules").exists():
            return HealthCheck(
                "dependencies", CheckStatus.warning,
                "node_modules not found — run npm install",
            )
        return HealthCheck("dependencies", CheckStatus.ok, "node_modules present")

    return HealthCheck("dependencies", CheckStatus.skip, "no dependency file detected")


def _check_docker(root: Path) -> HealthCheck:
    """Check Docker daemon and any compose file."""
    # Is Docker available?
    rc, out, err = _run(["docker", "info", "--format", "{{.ServerVersion}}"], root, timeout=10)
    if rc != 0:
        return HealthCheck("docker", CheckStatus.skip, "Docker not running or not installed")

    docker_ver = out.strip()

    # Compose file?
    compose = None
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        if (root / name).exists():
            compose = root / name
            break

    if compose is None:
        return HealthCheck("docker", CheckStatus.ok, f"Docker {docker_ver} — no compose file")

    # Check running containers
    rc2, out2, _ = _run(
        ["docker", "compose", "-f", str(compose), "ps", "--format", "json"],
        root, timeout=15,
    )
    if rc2 != 0:
        return HealthCheck("docker", CheckStatus.ok, f"Docker {docker_ver} — compose file present, no containers running")

    try:
        containers = [json.loads(line) for line in out2.splitlines() if line.strip()]
        running = [c for c in containers if isinstance(c, dict) and "running" in str(c.get("State", "")).lower()]
        return HealthCheck(
            "docker", CheckStatus.ok,
            f"Docker {docker_ver} — {len(running)}/{len(containers)} container(s) running",
        )
    except Exception:
        return HealthCheck("docker", CheckStatus.ok, f"Docker {docker_ver} — compose present")


def _check_security(root: Path) -> HealthCheck:
    """Quick pip-audit / npm audit check."""
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        rc, out, err = _run(["python", "-m", "pip_audit", "--desc", "-q"], root, timeout=30)
        if rc == -1:
            return HealthCheck("security", CheckStatus.skip, "pip-audit not installed")
        if rc == 0:
            return HealthCheck("security", CheckStatus.ok, "pip-audit: no known vulnerabilities")
        return HealthCheck("security", CheckStatus.warning, "pip-audit: vulnerabilities found", (out + err)[:400])

    if (root / "package.json").exists():
        rc, out, err = _run(["npm", "audit", "--audit-level=high"], root, timeout=30)
        if rc == 0:
            return HealthCheck("security", CheckStatus.ok, "npm audit: no high/critical issues")
        if rc != -1:
            return HealthCheck("security", CheckStatus.warning, "npm audit: issues found", (out + err)[:400])

    return HealthCheck("security", CheckStatus.skip, "no security scanner detected")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_health_checks(root: Path) -> HealthReport:
    """
    Run all health checks against `root` and return a HealthReport.
    Checks are independent — one failure does not stop the rest.
    """
    report = HealthReport()

    report.add(_check_git(root))

    build = _check_build_python(root) or _check_build_node(root)
    if build:
        report.add(build)
    else:
        report.add(HealthCheck("build", CheckStatus.skip, "no build system detected"))

    report.add(_check_tests(root))
    report.add(_check_lint(root))
    report.add(_check_dependencies(root))
    report.add(_check_docker(root))
    report.add(_check_security(root))

    return report
