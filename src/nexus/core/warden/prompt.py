"""
Warden Interactive Approval Prompt — asks human for approval before
allowing sensitive agent actions (ADR-002).
"""

from __future__ import annotations

from rich.console import Console
import typer

from nexus.models.warden import ActionCategory, PermissionRequest

console = Console()

DESTRUCTIVE_ACTIONS = {ActionCategory.git_push, ActionCategory.delete_files}


def prompt_approval(request: PermissionRequest) -> tuple[bool, bool]:
    """
    Prompt the human user for approval.
    
    Returns (approved: bool, session_grant: bool).
    
    Safety rule (ADR-002 / ADR-012): Destructive actions (git_push, delete_files)
    NEVER offer session approval — they always require 'Allow once'.
    """
    is_destructive = request.action_category in DESTRUCTIVE_ACTIONS

    console.print()
    console.print(f"[bold yellow]🛡️  Warden Approval Required[/bold yellow]")
    console.print(f"  [dim]Agent:[/dim]    [cyan]{request.agent}[/cyan]")
    console.print(f"  [dim]Action:[/dim]   [bold]{request.action_category.value}[/bold]")
    console.print(f"  [dim]Detail:[/dim]   {request.description}")
    if request.target_path:
        console.print(f"  [dim]Target:[/dim]   {request.target_path}")

    if is_destructive:
        console.print("[dim italic]Note: Destructive action — session allow disabled by safety policy (ADR-002).[/dim italic]")
        choice = typer.prompt(
            "Allow this action? [y] Yes once / [n] Deny",
            default="n",
        ).strip().lower()

        if choice in ("y", "yes"):
            return True, False  # approved once, no session grant
        return False, False

    else:
        choice = typer.prompt(
            "Allow this action? [y] Yes once / [s] Session allow for task / [n] Deny",
            default="n",
        ).strip().lower()

        if choice in ("y", "yes"):
            return True, False
        if choice in ("s", "session"):
            return True, True  # approved + session grant
        return False, False
