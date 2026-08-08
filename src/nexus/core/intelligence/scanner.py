"""
nexus scan — project repo inspector.

Walks the project root, detects stack/frameworks/structure,
and writes the result to .nexus/project/context.json.

No external dependencies — pure stdlib + pathlib.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------

# file presence → (language, framework/role)
_FILE_SIGNALS: list[tuple[str, str, str]] = [
    # Python
    ("requirements.txt",      "Python", "pip project"),
    ("pyproject.toml",        "Python", "pyproject"),
    ("setup.py",              "Python", "setuptools"),
    ("Pipfile",               "Python", "pipenv"),
    ("poetry.lock",           "Python", "poetry"),
    ("conda.yml",             "Python", "conda"),
    ("environment.yml",       "Python", "conda"),
    # JavaScript / TypeScript
    ("package.json",          "JavaScript", "npm/node"),
    ("yarn.lock",             "JavaScript", "yarn"),
    ("pnpm-lock.yaml",        "JavaScript", "pnpm"),
    ("bun.lockb",             "JavaScript", "bun"),
    ("tsconfig.json",         "TypeScript", "typescript"),
    ("next.config.js",        "JavaScript", "Next.js"),
    ("next.config.ts",        "TypeScript", "Next.js"),
    ("vite.config.ts",        "TypeScript", "Vite"),
    ("vite.config.js",        "JavaScript", "Vite"),
    ("angular.json",          "TypeScript", "Angular"),
    ("svelte.config.js",      "JavaScript", "Svelte"),
    ("nuxt.config.ts",        "TypeScript", "Nuxt"),
    # Rust
    ("Cargo.toml",            "Rust", "cargo"),
    # Go
    ("go.mod",                "Go", "go modules"),
    # Java / Kotlin
    ("pom.xml",               "Java", "Maven"),
    ("build.gradle",          "Java/Kotlin", "Gradle"),
    ("build.gradle.kts",      "Kotlin", "Gradle KTS"),
    # C#
    ("*.csproj",              "C#", ".NET"),
    ("*.sln",                 "C#", ".NET solution"),
    # Ruby
    ("Gemfile",               "Ruby", "bundler"),
    # PHP
    ("composer.json",         "PHP", "composer"),
    # Docker / infrastructure
    ("Dockerfile",            "Docker", "dockerfile"),
    ("docker-compose.yml",    "Docker", "compose"),
    ("docker-compose.yaml",   "Docker", "compose"),
    (".terraform",            "Terraform", "terraform"),
    ("terraform.tf",          "Terraform", "terraform"),
    # Config / misc
    (".env",                  "Config", "dotenv"),
    ("Makefile",              "Build", "make"),
    (".github",               "CI", "GitHub Actions"),
    (".gitlab-ci.yml",        "CI", "GitLab CI"),
    ("Jenkinsfile",           "CI", "Jenkins"),
]

# package.json keys → framework
_NPM_FRAMEWORK_SIGNALS: dict[str, str] = {
    "react":          "React",
    "vue":            "Vue",
    "angular":        "@angular/core",
    "svelte":         "Svelte",
    "next":           "Next.js",
    "nuxt":           "Nuxt",
    "express":        "Express",
    "fastify":        "Fastify",
    "nestjs":         "@nestjs/core",
    "electron":       "Electron",
}

# pyproject.toml / requirements.txt → framework
_PY_FRAMEWORK_SIGNALS: list[tuple[str, str]] = [
    ("django",   "Django"),
    ("flask",    "Flask"),
    ("fastapi",  "FastAPI"),
    ("starlette","Starlette"),
    ("tornado",  "Tornado"),
    ("aiohttp",  "aiohttp"),
    ("pydantic", "Pydantic"),
    ("typer",    "Typer"),
    ("click",    "Click"),
    ("pytest",   "pytest"),
    ("sqlalchemy","SQLAlchemy"),
    ("alembic",  "Alembic"),
    ("celery",   "Celery"),
    ("pandas",   "Pandas"),
    ("numpy",    "NumPy"),
    ("torch",    "PyTorch"),
    ("tensorflow","TensorFlow"),
    ("sklearn",  "scikit-learn"),
]


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_info(root: Path) -> dict:
    """Return basic git metadata; empty dict if not a git repo."""
    def _run(args: list[str]) -> str:
        try:
            r = subprocess.run(
                ["git"] + args,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    branch   = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    commit   = _run(["rev-parse", "--short", "HEAD"])
    remote   = _run(["remote", "get-url", "origin"])
    is_dirty = bool(_run(["status", "--porcelain"]))

    if not branch:
        return {}

    return {
        "branch":    branch,
        "commit":    commit,
        "remote":    remote or None,
        "is_dirty":  is_dirty,
    }


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def _glob_exists(root: Path, pattern: str) -> bool:
    """Check if any file matching a glob pattern exists under root (non-recursive)."""
    if "*" in pattern:
        return any(True for _ in root.glob(pattern))
    return (root / pattern).exists()


def scan_project(root: Path) -> dict:
    """
    Inspect the project at `root` and return a context dict.
    Does NOT write anything — caller decides where to persist.
    """
    root = root.resolve()

    languages:  list[str] = []
    frameworks: list[str] = []
    tools:      list[str] = []

    # 1. File-signal detection
    for filename, lang, role in _FILE_SIGNALS:
        if _glob_exists(root, filename):
            if lang not in ("Docker", "CI", "Config", "Build", "Terraform"):
                if lang not in languages:
                    languages.append(lang)
            if role not in tools:
                tools.append(role)

    # 2. package.json deep inspection
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            all_deps = {
                **pkg.get("dependencies", {}),
                **pkg.get("devDependencies", {}),
            }
            for dep_key, framework_name in _NPM_FRAMEWORK_SIGNALS.items():
                if any(dep_key in k for k in all_deps):
                    if framework_name not in frameworks:
                        frameworks.append(framework_name)
        except Exception:
            pass

    # 3. Python dependency inspection
    for depfile in ("requirements.txt", "pyproject.toml", "Pipfile"):
        deppath = root / depfile
        if deppath.exists():
            try:
                text = deppath.read_text(encoding="utf-8").lower()
                for marker, name in _PY_FRAMEWORK_SIGNALS:
                    if marker in text and name not in frameworks:
                        frameworks.append(name)
            except Exception:
                pass

    # 4. Project structure
    top_level = sorted([
        p.name for p in root.iterdir()
        if not p.name.startswith(".") and p.is_dir()
    ])
    file_count = sum(1 for _ in root.rglob("*")
                     if _.is_file() and ".nexus" not in _.parts
                     and ".git" not in _.parts)

    # 5. Git
    git = _git_info(root)

    # 6. Test detection
    has_tests = any([
        (root / "tests").is_dir(),
        (root / "test").is_dir(),
        (root / "__tests__").is_dir(),
        (root / "spec").is_dir(),
        bool(list(root.glob("test_*.py"))[:1]),
        bool(list(root.glob("*.test.ts"))[:1]),
        bool(list(root.glob("*.spec.ts"))[:1]),
    ])

    return {
        "scanned_at":   datetime.now(timezone.utc).isoformat(),
        "root":         str(root),
        "languages":    languages,
        "frameworks":   frameworks,
        "tools":        tools,
        "structure": {
            "top_level_dirs": top_level,
            "file_count":     file_count,
            "has_tests":      has_tests,
        },
        "git": git,
    }


def scan_and_write(root: Path) -> dict:
    """
    Scan the project and write result to .nexus/project/context.json.
    Returns the context dict.
    Raises FileNotFoundError if .nexus/ has not been initialised yet.
    """
    nexus_dir = root / ".nexus"
    if not nexus_dir.exists():
        raise FileNotFoundError(
            f".nexus/ not found at {root}. Run `nexus init` first."
        )

    context = scan_project(root)
    out_path = nexus_dir / "project" / "context.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(context, indent=2), encoding="utf-8")
    return context
