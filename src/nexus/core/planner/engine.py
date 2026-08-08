"""
Mission Planner Engine — Production-grade LLM-powered mission decomposition.

Decomposes high-level user goals into structured, executable task steps using Groq API
(llama-3.3-70b-versatile) and live repository context (.nexus/project/context.json).
Follows ADR-006 (qualitative reasoning, no numeric confidence scores).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from nexus.models.planner import MissionPlan, TaskStep, StepStatus
from nexus.models.warden import ActionCategory
from nexus.core.router.llm_router import load_groq_api_key
import urllib.request
import urllib.error


def decompose_mission(goal: str, root: Optional[Path] = None) -> MissionPlan:
    """
    Decompose a high-level goal into structured task steps using Groq LLM and project context.
    
    If Groq API key is unavailable, falls back to structural signal-based decomposition.
    """
    project_root = root or Path(".")
    mission_id = f"mission-{uuid.uuid4().hex[:8]}"
    api_key = load_groq_api_key(project_root)

    # Read project context if available
    context_data = {}
    context_file = project_root / ".nexus" / "project" / "context.json"
    if context_file.exists():
        try:
            context_data = json.loads(context_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    if api_key:
        try:
            plan = _decompose_with_llm(mission_id, goal, context_data, api_key)
            if plan and len(plan.steps) > 0:
                return plan
        except Exception:
            pass

    # Fallback rule-based structural decomposition
    return _decompose_fallback(mission_id, goal, context_data)


def _decompose_with_llm(mission_id: str, goal: str, context: dict, api_key: str) -> Optional[MissionPlan]:
    """Call Groq API to decompose goal into JSON task steps."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    system_prompt = (
        "You are Nexus Mission Planner. Decompose the user's software engineering goal into 3-5 sequential executable steps.\n"
        "Available Agents: codex (backend, python, docker, DB), antigravity (frontend, UI, React, fullstack), kiro (testing, QA, verification), cursor (refactoring, docs).\n"
        "Available Action Categories: read_source, write_source, execute_commands, git_push, delete_files, network.\n"
        "Project Context: " + json.dumps(context) + "\n"
        "Respond ONLY with a valid JSON object with format:\n"
        "{\n"
        '  "notes": "<qualitative plan overview>",\n'
        '  "steps": [\n'
        '    {\n'
        '      "description": "<step description>",\n'
        '      "preferred_agent": "<agent_name>",\n'
        '      "action_category": "<category>"\n'
        '    }\n'
        '  ]\n'
        "}\n"
    )

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Decompose goal: {goal}"},
        ],
        "temperature": 0.2,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=12) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        steps: list[TaskStep] = []
        for i, s in enumerate(parsed.get("steps", []), 1):
            agent = s.get("preferred_agent", "codex").lower()
            if agent not in ("codex", "antigravity", "kiro", "cursor"):
                agent = "codex"
            
            try:
                cat = ActionCategory(s.get("action_category", "execute_commands"))
            except ValueError:
                cat = ActionCategory.execute_commands

            steps.append(
                TaskStep(
                    step_id=f"{mission_id}-step-{i}",
                    description=s.get("description", f"Step {i}"),
                    preferred_agent=agent,
                    action_category=cat,
                    status=StepStatus.pending,
                )
            )

        if steps:
            return MissionPlan(
                mission_id=mission_id,
                goal=goal,
                steps=steps,
                notes=parsed.get("notes", "LLM-generated mission plan via Groq API."),
            )

    return None


def _decompose_fallback(mission_id: str, goal: str, context: dict) -> MissionPlan:
    """Fallback structural decomposition if LLM is unreachable."""
    goal_lower = goal.lower()
    steps: list[TaskStep] = []

    steps.append(
        TaskStep(
            step_id=f"{mission_id}-step-1",
            description=f"Inspect workspace and gather context for: {goal}",
            preferred_agent="antigravity",
            action_category=ActionCategory.read_source,
            status=StepStatus.pending,
        )
    )

    if any(w in goal_lower for w in ("frontend", "ui", "component", "css", "layout", "react")):
        impl_agent = "antigravity"
        action_cat = ActionCategory.write_source
    elif any(w in goal_lower for w in ("docker", "deploy", "ci", "compose", "container")):
        impl_agent = "codex"
        action_cat = ActionCategory.execute_commands
    else:
        impl_agent = "codex"
        action_cat = ActionCategory.write_source

    steps.append(
        TaskStep(
            step_id=f"{mission_id}-step-2",
            description=f"Implement core logic for: {goal}",
            preferred_agent=impl_agent,
            action_category=action_cat,
            status=StepStatus.pending,
        )
    )

    steps.append(
        TaskStep(
            step_id=f"{mission_id}-step-3",
            description=f"Run test suite and verify changes for: {goal}",
            preferred_agent="kiro" if impl_agent != "kiro" else "codex",
            action_category=ActionCategory.execute_commands,
            status=StepStatus.pending,
        )
    )

    return MissionPlan(
        mission_id=mission_id,
        goal=goal,
        steps=steps,
        notes="Structural decomposition fallback (qualitative ADR-006 compliance).",
    )
