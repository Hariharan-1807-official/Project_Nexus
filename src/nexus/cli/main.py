"""
Nexus CLI entry point.

Usage:
    nexus               — enter interactive shell (NEXUS >)
    nexus <subcommand>  — one-shot invocation
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from nexus.core.scaffold import init_project
from nexus.core.intelligence.scanner import scan_and_write
from nexus.core.intelligence.health import run_health_checks, CheckStatus
from nexus.core.intelligence.status import get_status, explain_project
from nexus.core.memory import Memory, EventType
import nexus.core.github as github_mod
import nexus.core.docker as docker_mod
from nexus.core.github import fetch_issue, create_pr
from nexus.core.docker import list_containers
from nexus.core.diagnostics import diagnose as run_diagnose
from nexus.models.diagnosis import InvestigationResult
from nexus.agents import REGISTRY
from nexus.agents.base import resolve_executable
from nexus.models.agent import AgentStatus

from nexus.core.warden.engine import WardenEngine
from nexus.models.warden import ActionCategory, PermissionState

app = typer.Typer(
    name="nexus",
    help="Nexus — control plane for AI coding agents.",
    invoke_without_command=True,
    no_args_is_help=False,
)

warden_app = typer.Typer(
    name="warden",
    help="Warden — security & permissions management.",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(warden_app, name="warden")

import sys as _sys
import io as _io

# Force UTF-8 output on Windows legacy consoles to prevent UnicodeEncodeError
# when printing Unicode symbols (✗, ✓, →, emoji) via Rich.
if _sys.stdout and hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console()

# ---------------------------------------------------------------------------
# Agent metadata — display labels and install hints
# ---------------------------------------------------------------------------

KNOWN_AGENTS: list[dict] = [
    {
        "name":       "codex",
        "label":      "Codex CLI",
        "executable": "codex",
        "note":       "OpenAI Codex CLI — free tier",
        "install":    "npm install -g @openai/codex",
    },
    {
        "name":       "antigravity",
        "label":      "Antigravity CLI",
        "executable": "agy",
        "note":       "Google Antigravity CLI — free preview",
        "install":    "irm https://antigravity.google/cli/install.ps1 | iex",
    },
    {
        "name":       "kiro",
        "label":      "Kiro",
        "executable": "kiro",
        "note":       "AWS Kiro — free tier",
        "install":    "https://kiro.dev",
    },
    {
        "name":       "cursor",
        "label":      "Cursor",
        "executable": "cursor",
        "note":       "Cursor — free Hobby tier",
        "install":    "https://cursor.com",
    },
]

# ADR-015 regression guard — these names must never appear
_EXCLUDED_AGENTS = {"claude", "gemini", "gemini-cli"}

# OPEN_COMMANDS keys — validated at import time (test TC-1.3 depends on this)
OPEN_COMMANDS: dict[str, list[str]] = {
    a["name"]: [a["executable"]] for a in KNOWN_AGENTS
}
# kiro and cursor open with "." so the IDE opens the current project
OPEN_COMMANDS["kiro"]   = ["kiro",   "."]
OPEN_COMMANDS["cursor"] = ["cursor", "."]

assert not (_EXCLUDED_AGENTS & set(OPEN_COMMANDS)), "ADR-015 violation in OPEN_COMMANDS"


def _safe_str(text: str) -> str:
    """Sanitise a string for Rich output on Windows legacy consoles.
    Strips characters that cp1252 cannot encode (emoji, non-BMP)."""
    try:
        text.encode("cp1252")
        return text
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text.encode("cp1252", errors="replace").decode("cp1252")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_markup(status: AgentStatus) -> str:
    return {
        AgentStatus.ready:       "[green]ready[/green]",
        AgentStatus.installed:   "[yellow]installed[/yellow]",
        AgentStatus.unreachable: "[red]unreachable[/red]",
    }.get(status, "[dim]unknown[/dim]")


def _extended_env() -> dict:
    """Merge conda process PATH with user-level PATH for subprocess calls."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            user_path, _ = winreg.QueryValueEx(key, "PATH")
    except Exception:
        user_path = ""
    current = os.environ.get("PATH", "")
    extra = ";".join(d for d in user_path.split(";") if d and d not in current)
    env = dict(os.environ)
    env["PATH"] = f"{current};{extra}" if extra else current
    return env


# ---------------------------------------------------------------------------
# Callback — no subcommand → interactive shell
# ---------------------------------------------------------------------------

@app.callback()
def root_callback(ctx: typer.Context) -> None:
    """Entry point. No subcommand → interactive shell."""
    if ctx.invoked_subcommand is None:
        _run_shell()


# ---------------------------------------------------------------------------
# nexus init
# ---------------------------------------------------------------------------

@app.command()
def init(
    path: Optional[Path] = typer.Argument(
        None,
        help="Project root to initialise. Defaults to current directory.",
    )
) -> None:
    """Initialise .nexus/ folder structure in a project directory."""
    project_root = (path or Path.cwd()).resolve()
    already_existed, created = init_project(project_root)

    if already_existed and not created:
        console.print(
            f"[yellow]•[/yellow] .nexus/ already exists at [bold]{project_root}[/bold] — nothing overwritten."
        )
    elif already_existed and created:
        console.print(
            f"[yellow]•[/yellow] .nexus/ already exists — added [bold]{len(created)}[/bold] missing file(s):"
        )
        for p in created:
            console.print(f"  [dim]{p}[/dim]")
    else:
        console.print(
            f"[green]✓[/green] Initialised .nexus/ at [bold]{project_root}[/bold]"
        )
        for p in created:
            console.print(f"  [dim]{p}[/dim]")


# ---------------------------------------------------------------------------
# nexus agents  — Phase 2: live status via adapter registry
# ---------------------------------------------------------------------------

@app.command()
def agents() -> None:
    """List all configured agents with live status."""
    console.print()
    console.print("[dim]Checking agent status…[/dim]")

    table = Table(
        title="Nexus Agents",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Agent",      style="bold")
    table.add_column("Command",    style="dim")
    table.add_column("Status",     justify="center")
    table.add_column("Version",    style="dim")
    table.add_column("Note",       style="dim")

    for meta in KNOWN_AGENTS:
        name = meta["name"]
        adapter_cls = REGISTRY.get(name)

        if adapter_cls is None:
            table.add_row(meta["label"], meta["executable"], "[red]no adapter[/red]", "", meta["note"])
            continue

        adapter = adapter_cls()
        live_status = adapter.status()
        version_str = ""
        if live_status == AgentStatus.ready and hasattr(adapter, "version"):
            version_str = adapter.version() or ""

        table.add_row(
            meta["label"],
            meta["executable"],
            _status_markup(live_status),
            version_str,
            meta["note"],
        )

    console.print()
    console.print(table)
    console.print(
        "[dim]Use [bold]nexus open <name>[/bold] to launch an agent.[/dim]\n"
    )


# ---------------------------------------------------------------------------
# nexus open  — Phase 2: use resolved executable path
# ---------------------------------------------------------------------------

@app.command()
def open(
    tool: str = typer.Argument(..., help="Agent name: codex | antigravity | kiro | cursor"),
) -> None:
    """Launch a named agent or IDE."""
    name = tool.lower().strip()

    if name not in OPEN_COMMANDS:
        known = ", ".join(OPEN_COMMANDS.keys())
        console.print(
            f"[red]✗[/red] Unknown tool [bold]{name!r}[/bold]. "
            f"Known agents: {known}"
        )
        raise typer.Exit(code=1)

    # Resolve the executable via the adapter (handles conda PATH shadowing)
    adapter_cls = REGISTRY.get(name)
    resolved_exe: Optional[str] = None
    if adapter_cls is not None:
        resolved_exe = adapter_cls()._exe()

    if resolved_exe is None:
        # Fall back to the bare command name — may work if PATH is fine
        base_cmd = OPEN_COMMANDS[name][0]
        resolved_exe = base_cmd

    # Build the full launch command — replace bare name with resolved path
    cmd_template = OPEN_COMMANDS[name]
    cmd = [resolved_exe] + cmd_template[1:]   # keep any trailing args (e.g. ".")

    console.print(f"[green]→[/green] Launching [bold]{name}[/bold]…")

    try:
        subprocess.Popen(
            cmd,
            env=_extended_env(),
        )
    except FileNotFoundError:
        meta = next((a for a in KNOWN_AGENTS if a["name"] == name), {})
        install_hint = meta.get("install", "")
        console.print(
            f"[red]✗[/red] Could not launch [bold]{name}[/bold]: "
            f"executable not found.\n"
            f"  Install: [dim]{install_hint}[/dim]"
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# nexus scan  — Phase 3
# ---------------------------------------------------------------------------

@app.command()
def scan(
    path: Optional[Path] = typer.Argument(
        None,
        help="Project root to scan. Defaults to current directory.",
    )
) -> None:
    """Scan the project and write stack/framework/structure to .nexus/project/context.json."""
    root = (path or Path.cwd()).resolve()

    if not (root / ".nexus").exists():
        console.print(
            f"[red]✗[/red] .nexus/ not found at [bold]{root}[/bold]. "
            "Run [bold]nexus init[/bold] first."
        )
        raise typer.Exit(code=1)

    with console.status("[dim]Scanning project…[/dim]"):
        try:
            ctx = scan_and_write(root)
        except Exception as exc:
            console.print(f"[red]✗[/red] Scan failed: {exc}")
            raise typer.Exit(code=1)

    Memory(root).log_event(
        EventType.scan,
        agent=None,
        action="nexus scan",
        result="ok",
        detail={"languages": ctx.get("languages"), "frameworks": ctx.get("frameworks")},
    )

    langs  = ", ".join(ctx.get("languages",  [])) or "none detected"
    frames = ", ".join(ctx.get("frameworks", [])) or "none detected"
    tools  = ", ".join(ctx.get("tools",      [])) or "none detected"
    struct = ctx.get("structure", {})
    git    = ctx.get("git", {})

    console.print(f"\n[green]✓[/green] Scan complete — [bold]{root.name}[/bold]\n")

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim", width=18)
    t.add_column()
    t.add_row("Languages",  langs)
    t.add_row("Frameworks", frames)
    t.add_row("Tools",      tools)
    t.add_row("Files",      str(struct.get("file_count", "?")))
    t.add_row("Tests",      "yes" if struct.get("has_tests") else "no")
    if git:
        dirty = " (dirty)" if git.get("is_dirty") else ""
        t.add_row("Git branch", f"{git.get('branch','?')} @ {git.get('commit','?')}{dirty}")
        if git.get("remote"):
            t.add_row("Git remote", git["remote"])
    console.print(t)
    console.print(f"[dim]Written to .nexus/project/context.json[/dim]\n")


# ---------------------------------------------------------------------------
# nexus health  — Phase 3
# ---------------------------------------------------------------------------

@app.command()
def health(
    path: Optional[Path] = typer.Argument(
        None,
        help="Project root to check. Defaults to current directory.",
    )
) -> None:
    """Run all health checks: git, build, tests, lint, deps, docker, security."""
    root = (path or Path.cwd()).resolve()

    with console.status("[dim]Running health checks…[/dim]"):
        report = run_health_checks(root)

    if (root / ".nexus").exists():
        Memory(root).log_event(
            EventType.health_check,
            agent=None,
            action="nexus health",
            result=report.overall.value,
            detail=report.as_dict(),
        )

    _icon = {
        CheckStatus.ok:      "[green]✓[/green]",
        CheckStatus.warning: "[yellow]⚠[/yellow]",
        CheckStatus.fail:    "[red]✗[/red]",
        CheckStatus.skip:    "[dim]–[/dim]",
    }
    _color = {
        CheckStatus.ok:      "green",
        CheckStatus.warning: "yellow",
        CheckStatus.fail:    "red",
        CheckStatus.skip:    "dim",
    }

    t = Table(box=box.ROUNDED, header_style="bold cyan", show_header=True)
    t.add_column("Check",  style="bold", width=16)
    t.add_column("Status", justify="center", width=10)
    t.add_column("Summary")

    for chk in report.checks:
        color = _color.get(chk.status, "white")
        t.add_row(
            chk.name,
            f"[{color}]{chk.status.value}[/{color}]",
            chk.summary,
        )

    overall_color = _color.get(report.overall, "white")
    console.print()
    console.print(t)
    console.print(
        f"\nOverall: [{overall_color}][bold]{report.overall.value.upper()}[/bold][/{overall_color}]\n"
    )

    for chk in report.checks:
        if chk.detail and chk.status in (CheckStatus.fail, CheckStatus.warning):
            console.print(f"[bold]{chk.name} detail:[/bold]")
            console.print(f"[dim]{chk.detail}[/dim]\n")


# ---------------------------------------------------------------------------
# nexus status  — Phase 3
# ---------------------------------------------------------------------------

@app.command()
def status(
    path: Optional[Path] = typer.Argument(
        None,
        help="Project root. Defaults to current directory.",
    )
) -> None:
    """Show current project state: context, git, recent events."""
    root = (path or Path.cwd()).resolve()
    snap = get_status(root)

    if "error" in snap:
        console.print(f"[red]✗[/red] {snap['error']}")
        raise typer.Exit(code=1)

    ctx = snap.get("context") or {}
    git = ctx.get("git", {})

    console.print()
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim", width=18)
    t.add_column()
    t.add_row("Project", Path(snap["project_root"]).name)
    if ctx.get("languages"):
        t.add_row("Stack",      ", ".join(ctx["languages"]))
    if ctx.get("frameworks"):
        t.add_row("Frameworks", ", ".join(ctx["frameworks"]))
    if git.get("branch"):
        dirty = " [yellow](dirty)[/yellow]" if git.get("is_dirty") else ""
        t.add_row("Branch", f"{git['branch']} @ {git.get('commit','')}{dirty}")
    if snap.get("last_scan"):
        from nexus.core.intelligence.status import _time_ago
        t.add_row("Last scan", _time_ago(snap["last_scan"]))
    else:
        t.add_row("Last scan", "[yellow]never — run nexus scan[/yellow]")
    console.print(t)

    events = snap.get("recent_events", [])
    if events:
        from nexus.core.intelligence.status import _time_ago
        console.print("[bold]Recent activity:[/bold]")
        for ev in reversed(events[-5:]):
            ts     = _time_ago(ev.get("timestamp", ""))
            agent  = ev.get("agent") or "nexus"
            action = ev.get("action", "")
            result = ev.get("result", "")
            color  = "green" if result == "ok" else ("red" if result == "fail" else "yellow")
            console.print(f"  [{color}]•[/{color}] [{ts}] {agent}: {action}")
    else:
        console.print("[dim]No activity yet.[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# nexus explain  — Phase 3
# ---------------------------------------------------------------------------

@app.command()
def explain(
    path: Optional[Path] = typer.Argument(
        None,
        help="Project root. Defaults to current directory.",
    )
) -> None:
    """Print a human-readable narrative of the project state and recent activity."""
    root = (path or Path.cwd()).resolve()
    console.print()
    console.print(explain_project(root))
    console.print()


# ---------------------------------------------------------------------------
# nexus repair  — fix corrupted .nexus/ config files
# ---------------------------------------------------------------------------

@app.command()
def repair(
    path: Optional[Path] = typer.Argument(
        None,
        help="Project root. Defaults to current directory.",
    )
) -> None:
    """Repair corrupted .nexus/config/ files by restoring their defaults.
    Never touches tasks/ or memory/ — those are append-only audit logs."""
    from nexus.core.scaffold import _DEFAULT_FILES
    import json as _json

    root = (path or Path.cwd()).resolve()
    nexus_dir = root / ".nexus"

    if not nexus_dir.exists():
        console.print(f"[red]✗[/red] .nexus/ not found at [bold]{root}[/bold]. Run [bold]nexus init[/bold] first.")
        raise typer.Exit(code=1)

    repaired: list[str] = []
    healthy:  list[str] = []
    skipped:  list[str] = []

    # Only repair config files — never tasks/ or memory/ (ADR-003)
    config_files = {k: v for k, v in _DEFAULT_FILES.items() if k.startswith(".nexus/config/")}

    for rel_path, default_content in config_files.items():
        target = root / rel_path
        if not target.exists():
            skipped.append(rel_path)
            continue

        content = target.read_text(encoding="utf-8").strip()
        if not content:
            # Empty file — restore default
            if default_content is not None:
                target.write_text(_json.dumps(default_content, indent=2), encoding="utf-8")
                repaired.append(rel_path)
            else:
                healthy.append(rel_path)
            continue

        try:
            _json.loads(content)
            healthy.append(rel_path)
        except _json.JSONDecodeError:
            if default_content is not None:
                target.write_text(_json.dumps(default_content, indent=2), encoding="utf-8")
                repaired.append(rel_path)
                console.print(f"[yellow]⚠[/yellow] Repaired [bold]{rel_path}[/bold] (was corrupt — restored default)")
            else:
                skipped.append(rel_path)

    # Check memory logs for corruption — warn but do NOT touch them
    mem = Memory(root)
    for logfile in ("events.jsonl", "decisions.jsonl", "agent-handoffs.jsonl"):
        bad = mem.corrupt_line_count(logfile)
        if bad > 0:
            console.print(
                f"[yellow]⚠[/yellow] [bold]memory/{logfile}[/bold] has {bad} corrupt line(s). "
                f"These are skipped when reading. The file is not modified (append-only log — ADR-003)."
            )

    if repaired:
        console.print(f"\n[green]✓[/green] Repaired {len(repaired)} file(s). Healthy: {len(healthy)}.")
    else:
        console.print(f"[green]✓[/green] All config files are valid JSON. Nothing to repair.")


def _resolve_root(p: Any) -> Path:
    """Safely resolve project_root whether called via Typer CLI or shell function call."""
    if isinstance(p, Path):
        return p.resolve()
    return Path(".").resolve()


# ---------------------------------------------------------------------------
# Phase 4 Commands — GitHub, Docker, Diagnostics
# ---------------------------------------------------------------------------

@app.command()
def issue(
    number: int = typer.Argument(..., help="GitHub issue number"),
    project_root: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root directory"),
) -> None:
    """Fetch and display a GitHub issue with recommended agent for execution."""
    root = _resolve_root(project_root)

    if not github_mod.gh_installed():
        console.print("[red]✗[/red] gh CLI is not installed. Install it from https://cli.github.com")
        raise typer.Exit(1)

    issue_data = github_mod.fetch_issue(number, cwd=root)
    if not issue_data:
        console.print(f"[red]✗[/red] Failed to fetch GitHub issue #{number}. Check authentication (`gh auth status`) or issue number.")
        raise typer.Exit(1)

    console.print()
    console.print(f"[bold cyan]Issue #{issue_data.number}:[/bold cyan] [bold]{issue_data.title}[/bold]")
    console.print(f"[dim]Status:[/dim] {issue_data.state} | [dim]URL:[/dim] {issue_data.url or 'N/A'}")
    if issue_data.labels:
        console.print(f"[dim]Labels:[/dim] {', '.join(issue_data.labels)}")
    if issue_data.assignees:
        console.print(f"[dim]Assignees:[/dim] {', '.join(issue_data.assignees)}")

    console.print()
    if issue_data.recommended_agent:
        console.print(f"[bold green]Recommended Agent:[/bold green] [cyan]{issue_data.recommended_agent}[/cyan]")
        console.print(f"[dim]Reason:[/dim] {issue_data.recommendation_reason}")

    if issue_data.body:
        console.print()
        console.print("[bold]Description:[/bold]")
        console.print(issue_data.body[:500] + ("..." if len(issue_data.body) > 500 else ""))

    # Log to memory if .nexus exists
    try:
        mem = Memory(root)
        mem.log_event(
            EventType.system,
            agent=None,
            action=f"nexus issue {number}",
            result="ok",
            detail={"number": number, "title": issue_data.title},
        )
    except Exception:
        pass


@app.command()
def investigate(
    number: int = typer.Argument(..., help="GitHub issue number to investigate"),
    project_root: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root directory"),
) -> None:
    """Read-only investigation of a GitHub issue. Generates root-cause hypothesis without modifying code."""
    root = _resolve_root(project_root)

    if not github_mod.gh_installed():
        console.print("[red]✗[/red] gh CLI is not installed.")
        raise typer.Exit(1)

    issue_data = github_mod.fetch_issue(number, cwd=root)
    if not issue_data:
        console.print(f"[red]✗[/red] Could not fetch issue #{number}.")
        raise typer.Exit(1)

    console.print(f"[bold cyan]Investigating Issue #{number}:[/bold cyan] {issue_data.title}...")

    # Perform read-only diagnostic pass
    diag = run_diagnose(root)

    # Build investigation result artifact
    inv = InvestigationResult(
        issue_number=number,
        hypothesis=diag.likely_root_cause,
        affected_files=[s for s in diag.sources_checked],
        proposed_approach=diag.suggested_fix,
        investigated_by="nexus-diagnostics",
    )

    console.print()
    console.print(f"[bold yellow]Root-Cause Hypothesis:[/bold yellow] {inv.hypothesis}")
    console.print(f"[bold yellow]Proposed Approach:[/bold yellow] {inv.proposed_approach}")
    if diag.evidence:
        console.print()
        console.print("[bold]Evidence Gathered:[/bold]")
        for ev in diag.evidence:
            console.print(f"  • {ev}")

    # Log event
    try:
        mem = Memory(root)
        mem.log_event(
            EventType.agent_action,
            agent="nexus",
            action=f"nexus investigate {number}",
            result="ok",
            detail={"hypothesis": inv.hypothesis},
        )
    except Exception:
        pass


@app.command()
def docker(
    project_root: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root directory"),
) -> None:
    """Show live status of Docker containers and compose configuration."""
    root = _resolve_root(project_root)

    if not docker_mod.docker_installed():
        console.print("[red]✗[/red] Docker CLI is not installed.")
        raise typer.Exit(1)

    if not docker_mod.docker_available():
        console.print("[yellow]⚠[/yellow] Docker daemon is not running.")
        raise typer.Exit(1)

    containers = docker_mod.list_containers(all_containers=True)
    if not containers:
        console.print("[dim]No Docker containers found.[/dim]")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Container Name")
    table.add_column("Image")
    table.add_column("Status")
    table.add_column("Ports")

    for c in containers:
        status_style = "green" if (c.state == "running" or "Up" in c.status) else "red"
        table.add_row(c.name, c.image, f"[{status_style}]{c.status}[/{status_style}]", c.ports)

    console.print(table)


@app.command()
def diagnose(
    project_root: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root directory"),
) -> None:
    """Run cross-source diagnostics (Git, Docker, project files, env) for root-cause analysis."""
    root = _resolve_root(project_root)

    console.print("[bold cyan]Running cross-source diagnostics...[/bold cyan]")
    diag = run_diagnose(root)

    console.print()
    console.print(f"[bold red]Problem Identified:[/bold red] {diag.problem}")
    console.print(f"[bold yellow]Likely Root Cause:[/bold yellow] {diag.likely_root_cause}")
    console.print(f"[bold green]Suggested Fix:[/bold green] {diag.suggested_fix}")

    console.print()
    console.print("[bold]Evidence:[/bold]")
    for ev in diag.evidence:
        console.print(f"  • {ev}")

    console.print()
    console.print(f"[dim]Sources checked: {', '.join(diag.sources_checked)}[/dim]")
    console.print(f"[dim]Note: {diag.confidence_note}[/dim]")

    try:
        mem = Memory(root)
        mem.log_event(
            EventType.health_check,
            agent=None,
            action="nexus diagnose",
            result="ok",
            detail={"problem": diag.problem},
        )
    except Exception:
        pass


@app.command()
def pr(
    title: str = typer.Option(..., "--title", "-t", prompt="PR Title", help="Pull request title"),
    body: str = typer.Option("", "--body", "-b", help="Pull request body"),
    base: Optional[str] = typer.Option(None, "--base", help="Target base branch"),
    project_root: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root directory"),
) -> None:
    """Create a GitHub pull request from current branch changes (always requires confirmation)."""
    root = _resolve_root(project_root)

    if not github_mod.gh_installed():
        console.print("[red]✗[/red] gh CLI is not installed.")
        raise typer.Exit(1)

    # ADR-002: Always stop at explicit confirmation prompt
    console.print(f"\n[bold yellow]Ready to create Pull Request:[/bold yellow]")
    console.print(f"  Title: {title}")
    console.print(f"  Body:  {body or '(default)'}")
    confirm = typer.confirm("Do you want to submit this Pull Request to GitHub?", default=False)

    if not confirm:
        console.print("[dim]PR creation cancelled.[/dim]")
        raise typer.Exit(0)

    res = create_pr(title=title, body=body, base=base, cwd=root)
    if res.created and res.url:
        console.print(f"[bold green]✓ Pull Request Created![/bold green] {res.url}")
    else:
        console.print(f"[red]✗ Failed to create PR:[/red] {res.error}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Phase 5 Commands — Warden Security System
# ---------------------------------------------------------------------------

@warden_app.callback(invoke_without_command=True)
def warden_callback(
    ctx: typer.Context,
    project_root: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root directory"),
) -> None:
    """Display Warden security capabilities and permission matrix for all agents."""
    if ctx.invoked_subcommand is not None:
        return

    root = _resolve_root(project_root)
    engine = WardenEngine(root)
    perms = engine.load_permissions()

    console.print()
    console.print("[bold yellow]🛡️  Warden Security Policy & Permission Matrix[/bold yellow]")
    console.print("[dim]Edit rules via `nexus warden set <agent> <action> <state>` or edit .nexus/config/permissions.json directly.[/dim]")
    console.print()

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Agent")
    for cat in ActionCategory:
        table.add_column(cat.value)

    known_agent_names = ["codex", "antigravity", "kiro", "cursor"]
    for agent_name in known_agent_names:
        agent_perms = perms.get(agent_name, {})
        row = [agent_name]
        for cat in ActionCategory:
            val = agent_perms.get(cat.value, "approval")
            if val == "allow":
                style_val = "[green]allow[/green]"
            elif val == "deny":
                style_val = "[red]deny[/red]"
            else:
                style_val = "[yellow]approval[/yellow]"
            row.append(style_val)
        table.add_row(*row)

    console.print(table)


@warden_app.command("set")
def warden_set(
    agent: str = typer.Argument(..., help="Agent name e.g. codex, antigravity, kiro, cursor"),
    action: str = typer.Argument(..., help="Action category e.g. execute_commands, git_push, delete_files"),
    state: str = typer.Argument(..., help="Permission state: allow, deny, approval"),
    project_root: Optional[Path] = typer.Option(None, "--path", "-p", help="Project root directory"),
) -> None:
    """Update permission setting in .nexus/config/permissions.json."""
    root = _resolve_root(project_root)
    engine = WardenEngine(root)

    agent_lower = agent.lower()
    if agent_lower not in ["codex", "antigravity", "kiro", "cursor"]:
        console.print(f"[red]✗[/red] Unknown agent '{agent}'. Known: codex, antigravity, kiro, cursor.")
        raise typer.Exit(1)

    try:
        action_cat = ActionCategory(action.lower())
    except ValueError:
        valid_cats = ", ".join(c.value for c in ActionCategory)
        console.print(f"[red]✗[/red] Unknown action '{action}'. Valid actions: {valid_cats}.")
        raise typer.Exit(1)

    try:
        perm_state = PermissionState(state.lower())
    except ValueError:
        console.print(f"[red]✗[/red] Unknown state '{state}'. Valid states: allow, deny, approval.")
        raise typer.Exit(1)

    success = engine.set_permission(agent_lower, action_cat, perm_state)
    if success:
        console.print(
            f"[bold green]✓ Updated Permission:[/bold green] "
            f"[cyan]{agent_lower}[/cyan] : [bold]{action_cat.value}[/bold] → [{perm_state.value}]{perm_state.value}[/{perm_state.value}]"
        )
    else:
        console.print(f"[red]✗ Failed to write permission configuration.[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Easter eggs
# ---------------------------------------------------------------------------

import random

_AGENT_ROASTS = [
    "Codex is still trying to figure out what a semicolon is for.",
    "Antigravity: 'I have a 1M token context.' Also Antigravity: forgets what you said two turns ago.",
    "Kiro wrote this roast. Then reviewed it. Then rewrote it. It's still not done.",
    "Cursor keeps asking if you meant to add a comma. You didn't. It added one anyway.",
    "Fun fact: if all four agents were in a room, they'd spend 40 minutes agreeing on a variable name.",
    "Codex once refactored a 'Hello World' into 47 files. It called it 'enterprise-ready'.",
    "Antigravity's context window is so large it remembers that embarrassing thing you typed in 2024.",
    "Kiro opened a PR to fix a typo in a comment. The PR had 12 review rounds.",
    "Cursor's autocomplete suggested 'pass' in production. You accepted it. We don't talk about that.",
]

_FORTUNES = [
    "Today you will write code that works on the first try. (Just kidding.)",
    "A bug you've been chasing for hours is a missing comma. It always is.",
    "Your future is bright — unless you forget to commit before closing the IDE.",
    "Good things come to those who read the error message fully.",
    "The stack trace is trying to tell you something. Listen to it.",
    "Today's lucky number: 42. Today's unlucky number: undefined.",
    "You will merge a PR that breaks staging. You will fix it before anyone notices. Maybe.",
    "An agent will suggest the perfect solution. You will reject it and do it manually. It will take three hours.",
    "The docs are lying. You already knew this.",
    "Ship it. What's the worst that could happen? (Don't answer that.)",
]

_HAIKU = [
    ("agents wait in dark", "context loads, tokens align", "git push denied: good"),
    ("nexus boots at dawn", "four agents, one purpose, calm", "the bug hides in tests"),
    ("warden says: not yet", "the push sits, patient and still", "you breathe — it's okay"),
    ("codex writes the code", "antigravity reviews it", "kiro disagrees"),
    ("one CLI rules", "to route them, plan and review", "and in the dark: ship"),
]

_MATRIX_FRAMES = [
    "01001110 01000101 01011000 01010101 01010011",
    "Loading agents... ▓▓▓▓▓▓▓▓▓▓ 100%",
    "Establishing control plane...",
    "All systems nominal. Welcome back.",
]

def _easter_egg(cmd: str, args: list[str]) -> bool:
    """
    Handle easter egg commands. Returns True if handled, False if not an egg.
    """
    full = (cmd + " " + " ".join(args)).strip().lower()

    # ── hello / hey / hi ────────────────────────────────────────────────
    if cmd in ("hello", "hi", "hey"):
        console.print("[bold cyan]NEXUS:[/bold cyan] Hey. Let's build something.")
        return True

    # ── roast (roast me / roast the agents) ─────────────────────────────
    if cmd == "roast":
        console.print(f"[bold yellow]🔥[/bold yellow] {random.choice(_AGENT_ROASTS)}")
        return True

    # ── fortune ─────────────────────────────────────────────────────────
    if cmd == "fortune":
        console.print(f"[bold magenta]🔮[/bold magenta]  {random.choice(_FORTUNES)}")
        return True

    # ── haiku ────────────────────────────────────────────────────────────
    if cmd == "haiku":
        h = random.choice(_HAIKU)
        console.print(f"\n[italic cyan]  {h[0]}[/italic cyan]")
        console.print(f"[italic cyan]  {h[1]}[/italic cyan]")
        console.print(f"[italic cyan]  {h[2]}[/italic cyan]\n")
        return True

    # ── matrix ───────────────────────────────────────────────────────────
    if cmd == "matrix":
        import time
        for frame in _MATRIX_FRAMES:
            console.print(f"[green]{frame}[/green]")
            time.sleep(0.4)
        return True

    # ── sudo ─────────────────────────────────────────────────────────────
    if cmd == "sudo":
        console.print("[red]✗[/red] Nice try. Warden says no. (ADR-002)")
        return True

    # ── rm -rf / del ─────────────────────────────────────────────────────
    if cmd in ("rm", "del", "format") or "rm -rf" in full:
        console.print("[red]✗[/red] Absolutely not. Have you met Warden?")
        return True

    # ── git push --force ─────────────────────────────────────────────────
    if "push" in full and "force" in full:
        console.print("[red]✗[/red] Force push? In this house? ADR-002 weeps.")
        return True

    # ── the answer / meaning of life ─────────────────────────────────────
    if "meaning" in full or "42" == cmd or "answer" in full:
        console.print("[bold]42.[/bold] [dim]You already knew that.[/dim]")
        return True

    # ── coffee ───────────────────────────────────────────────────────────
    if cmd in ("coffee", "☕"):
        console.print("[yellow]☕[/yellow] Brewing... done. You're welcome.")
        return True

    # ── who are you / what are you ───────────────────────────────────────
    if ("who" in full and "you" in full) or ("what" in full and "you" in full and "are" in full):
        console.print(
            "[bold cyan]NEXUS[/bold cyan] — control plane for AI coding agents.\n"
            "[dim]Not an agent. The thing above the agents.\n"
            "Think of it as the manager. The agents do the work. Nexus takes the credit.[/dim]"
        )
        return True

    # ── why ──────────────────────────────────────────────────────────────
    if cmd == "why":
        console.print(
            "[dim]Because switching between five CLI tools, two IDEs, and a GitHub tab\n"
            "while re-explaining your project to each of them was not a personality trait\n"
            "worth keeping.[/dim]"
        )
        return True

    # ── flip / tableflip ─────────────────────────────────────────────────
    if cmd in ("flip", "tableflip", "rage"):
        console.print("(╯°□°）╯︵ ┻━┻  [dim]...Warden has logged this.[/dim]")
        return True

    # ── zen ──────────────────────────────────────────────────────────────
    if cmd == "zen":
        console.print(
            "[italic]One CLI. One context. One source of truth.\n"
            "Agents are replaceable. Nexus is not.[/italic]"
        )
        return True

    # ── version easter egg ───────────────────────────────────────────────
    if cmd == "version" and "agents" in full:
        console.print("[dim]The agents have no version. They are eternal. And occasionally broken.[/dim]")
        return True

    return False  # not an egg


# ---------------------------------------------------------------------------
# Interactive shell
# ---------------------------------------------------------------------------

_SHELL_COMMANDS = {
    "init":        "Initialise .nexus/ in the current directory",
    "agents":      "List configured agents with live status",
    "open":        "Launch an agent (e.g. open kiro)",
    "scan":        "Scan project stack, frameworks, structure",
    "health":      "Run all health checks",
    "status":      "Show current project state",
    "explain":     "Narrative summary of project and recent activity",
    "repair":      "Repair corrupted .nexus/config/ files",
    "issue":       "Fetch and display a GitHub issue",
    "investigate": "Read-only analysis of a GitHub issue",
    "docker":      "Show live status of Docker containers",
    "diagnose":    "Run cross-source diagnostics engine",
    "pr":          "Create a GitHub pull request",
    "warden":      "View/manage security permissions matrix",
    "help":        "Show this help",
    "exit":        "Exit the shell",
    "quit":        "Exit the shell",
}


def _shell_help() -> None:
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column(style="dim")
    for cmd, desc in _SHELL_COMMANDS.items():
        table.add_row(cmd, desc)
    console.print(table)


def _dispatch_shell_line(line: str) -> bool:
    """
    Parse and execute one shell line.
    Returns False when the user wants to exit, True otherwise.
    """
    parts = line.strip().split()
    if not parts:
        return True

    # Allow "nexus <cmd>" or just "<cmd>" (FR-1 / TC-1.4)
    if parts[0].lower() == "nexus":
        parts = parts[1:]
    if not parts:
        return True

    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("exit", "quit"):
        return False

    if cmd == "help":
        _shell_help()
        return True

    if cmd == "init":
        _run_typer_command(init, Path(args[0]) if args else None)
        return True

    if cmd == "agents":
        _run_typer_command(agents)
        return True

    if cmd == "open":
        if not args:
            console.print("[red]✗[/red] Usage: open <agent>")
        else:
            _run_typer_command(open, args[0])
        return True

    if cmd == "scan":
        _run_typer_command(scan, Path(args[0]) if args else None)
        return True

    if cmd == "health":
        _run_typer_command(health, Path(args[0]) if args else None)
        return True

    if cmd == "status":
        _run_typer_command(status, Path(args[0]) if args else None)
        return True

    if cmd == "explain":
        _run_typer_command(explain, Path(args[0]) if args else None)
        return True

    if cmd == "repair":
        _run_typer_command(repair, Path(args[0]) if args else None)
        return True

    if cmd == "issue":
        if not args:
            console.print("[red]✗[/red] Usage: issue <number>")
        else:
            try:
                num = int(args[0])
                _run_typer_command(issue, num)
            except ValueError:
                console.print("[red]✗[/red] Issue number must be an integer.")
        return True

    if cmd == "investigate":
        if not args:
            console.print("[red]✗[/red] Usage: investigate <number>")
        else:
            try:
                num = int(args[0])
                _run_typer_command(investigate, num)
            except ValueError:
                console.print("[red]✗[/red] Issue number must be an integer.")
        return True

    if cmd == "docker":
        _run_typer_command(docker)
        return True

    if cmd == "diagnose":
        _run_typer_command(diagnose)
        return True

    if cmd == "pr":
        title = " ".join(args) if args else "Updates from Nexus"
        _run_typer_command(pr, title)
        return True

    if cmd == "warden":
        if args and args[0].lower() == "set":
            if len(args) < 4:
                console.print("[red]✗[/red] Usage: warden set <agent> <action> <state>")
            else:
                _run_typer_command(warden_set, args[1], args[2], args[3])
        else:
            ctx = typer.Context(warden_app)
            _run_typer_command(warden_callback, ctx)
        return True

    # Easter eggs — checked before the generic "not available" fallback
    if _easter_egg(cmd, args):
        return True

    # Unrecognised — natural-language stub (Router wired in Phase 5)
    safe_line = _safe_str(line.strip())
    console.print(
        f"[yellow]?[/yellow] [dim]'{safe_line}' — natural-language routing not yet available "
        f"(Phase 5+). Type [bold]help[/bold] for commands.[/dim]"
    )
    return True


def _run_typer_command(fn, *args) -> None:
    """Invoke a Typer command function directly from the shell loop."""
    try:
        fn(*args)
    except (SystemExit, typer.Exit):
        pass


def _run_shell() -> None:
    from nexus import __version__
    console.print()
    console.print(
        f"[bold cyan]NEXUS[/bold cyan] [dim]v{__version__} — "
        f"type [bold]help[/bold] for commands, [bold]exit[/bold] to quit[/dim]"
    )
    console.print()

    while True:
        try:
            line = console.input("[bold cyan]NEXUS >[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/dim]")
            break

        try:
            if not _dispatch_shell_line(line):
                console.print("[dim]Bye.[/dim]")
                break
        except UnicodeEncodeError:
            # Windows legacy console can't render certain characters (emoji, etc.)
            console.print("[yellow]?[/yellow] [dim]Input contains characters that can't be displayed. Try without emoji.[/dim]")
        except Exception as exc:
            console.print(f"[red]✗[/red] Shell error: {exc}")
