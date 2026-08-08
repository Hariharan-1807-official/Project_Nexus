"""
Groq LLM Router — Natural Language Intent Parsing & Prompt Routing.

Connects to Groq API (llama-3.3-70b-versatile) for instant natural language
command classification, goal decomposition, and agent selection.
Follows zero-cost API philosophy.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any


def load_groq_api_key(root: Optional[Path] = None) -> Optional[str]:
    """
    Load GROQ_API_KEY from .env file, environment, or .nexus/config/router.json.
    """
    # 1. Local .env file (if root provided)
    project_root = root or Path(".")
    env_file = project_root / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("GROQ_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except Exception:
            pass

    # 2. Environment Variable
    env_key = os.getenv("GROQ_API_KEY")
    if env_key:
        return env_key.strip()

    # 3. .nexus/config/router.json
    router_config = project_root / ".nexus" / "config" / "router.json"
    if router_config.exists():
        try:
            data = json.loads(router_config.read_text(encoding="utf-8"))
            if "groq_api_key" in data and data["groq_api_key"]:
                return data["groq_api_key"].strip()
        except Exception:
            pass

    return None


def route_natural_language(prompt: str, root: Optional[Path] = None) -> Dict[str, Any]:
    """
    Send natural language prompt to Groq LLM for intent classification & agent routing.
    
    Returns structured dict with:
      - 'intent': action command ('mission', 'investigate', 'diagnose', 'health', 'scan', etc.)
      - 'agent': recommended agent ('codex', 'antigravity', 'kiro', 'cursor')
      - 'summary': clean task goal summary
      - 'confidence': qualitative reasoning string (ADR-006)
    """
    api_key = load_groq_api_key(root)
    if not api_key:
        return {
            "status": "no_key",
            "intent": "mission",
            "agent": "codex",
            "summary": prompt,
            "reason": "GROQ_API_KEY not found in .env or environment.",
        }

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Nexus-Control-Plane/1.0",
    }

    system_prompt = (
        "You are Nexus Router, an AI intent classifier for a multi-agent developer system.\n"
        "Given a user prompt, classify the intent and pick the best agent.\n"
        "Known agents: codex (backend/docker/python/api), antigravity (frontend/ui/fullstack), kiro (testing/qa/verification), cursor (refactoring/docs).\n"
        "Known command intents: mission, swarm, investigate, diagnose, health, scan, warden, status, explain.\n"
        "Respond ONLY with a valid JSON object matching this schema:\n"
        "{\n"
        '  "intent": "<command>",\n'
        '  "agent": "<agent_name>",\n'
        '  "summary": "<clean task summary>",\n'
        '  "reasoning": "<qualitative reasoning>"\n'
        "}\n"
    )

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            parsed["status"] = "success"
            return parsed
    except Exception as exc:
        return {
            "status": "error",
            "intent": "mission",
            "agent": "codex",
            "summary": prompt,
            "reason": f"Groq API error: {exc}",
        }
