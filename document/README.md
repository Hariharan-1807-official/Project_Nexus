# Nexus

> One CLI. One shared context. Every AI coding agent you already have.

**Nexus** is a control plane that coordinates heterogeneous AI coding agents through shared project context, structured handoffs, diagnostics, and development workflows — through a single CLI.

It is **not** another coding agent. It is the layer that manages the coding agents you already have.

```
         YOU
          │
          ▼
     ┌─────────┐
     │  NEXUS  │
     └────┬────┘
          │
  ┌───────┼───────────┐
  ▼       ▼           ▼
Agents  GitHub      Docker
  │
  ├── Codex CLI
  ├── Antigravity CLI
  ├── Kiro
  └── Cursor
```

---

## Quick Start

```powershell
# Install (dev mode)
pip install -e .

# Initialise a project
cd my-project
nexus init

# Check agent status
nexus agents

# Scan project stack
nexus scan

# Run health checks
nexus health

# Interactive shell
nexus
```

---

## Agent Roster (v1 — free only)

| Agent | Command | Context | Status |
|---|---|---|---|
| Codex CLI | `codex` | 200k tokens | ✅ Supported |
| Antigravity CLI | `agy` | 1M tokens | ✅ Supported |
| Kiro | `kiro` | 128k tokens | ✅ Supported |
| Cursor | `cursor` | 200k tokens | ✅ Supported |

**Not included:** Claude Code (paid, $20/mo minimum), Gemini CLI (retired June 2026).

---

## Build Status

| Phase | Scope | Status | Tests |
|---|---|---|---|
| Phase 1 — CLI Core | `init`, `agents`, `open`, interactive shell | ✅ Complete | 31 |
| Phase 2 — Agent Abstraction | 4 adapters, live status, capabilities | ✅ Complete | 70 |
| Phase 3 — Project Intelligence | `scan`, `health`, `status`, `explain`, memory | ✅ Complete | 53 |
| Phase 4 — GitHub + Docker + Diagnostics | `issue`, `investigate`, `docker`, `diagnose`, `pr` | 🔨 In Progress | — |
| Phase 5 — Warden | Permission system, approval prompts, audit | 🔜 | — |
| Phase 6 — Planner + Swarm + Review | `mission`, `swarm`, `review`, `solve` | 🔜 | — |
| Phase 7 — Daemon | Background watchers, auto-diagnose | 🔜 | — |
| Phase 8 — IDE Control | `nexus ide` | 🔜 | — |

**Total tests: 154 passing** (as of Phase 3 completion)

---

## Tech Stack

- **Language:** Python 3.11+
- **CLI:** Typer
- **Schemas:** Pydantic
- **Testing:** pytest
- **Packaging:** `pip install -e .`

---

## Project Structure

```
Project_Nexus/
├── document/                    ← specs, ADRs, architecture, usage guide
├── src/nexus/
│   ├── agents/                  ← one adapter per agent + base class
│   ├── cli/main.py              ← all CLI commands + interactive shell
│   ├── core/
│   │   ├── scaffold.py          ← nexus init
│   │   ├── memory.py            ← append-only .jsonl logs
│   │   ├── github.py            ← GitHub integration (gh CLI)
│   │   ├── docker.py            ← Docker inspection
│   │   ├── diagnostics.py       ← cross-source diagnostics engine
│   │   └── intelligence/        ← scanner, health, status
│   └── models/                  ← Pydantic schemas
├── tests/
│   ├── test_phase1.py
│   ├── test_phase2.py
│   ├── test_phase3.py
│   └── test_phase4.py
├── .nexus/                      ← project's own nexus data
└── pyproject.toml
```

---

## Key Principles

1. **Safety over autonomy** — every destructive action requires explicit approval, forever
2. **Agent-agnostic** — no agent-specific logic outside adapter files
3. **Structured artifacts** — agents communicate through `.nexus/` files, not conversation
4. **Config over code** — routing rules and permissions are editable JSON
5. **Inspectable** — every workflow is reconstructable from `.nexus/` alone

---

## Documentation

| Document | Description |
|---|---|
| [Vision & Concept](00-vision-and-concept.md) | What Nexus is and why it exists |
| [PRD](01-prd.md) | Product requirements |
| [ADRs](02-adr.md) | Architecture decision records |
| [System Architecture](03-system-architecture.md) | Component diagram, schemas, contracts |
| [Implementation Plan](04-implementation-plan.md) | Build order with test cases |
| [Usage Guide](USAGE.md) | How to use every command |
| [Session Handoff](SESSION-HANDOFF.md) | Current state for session continuity |

---

*Last updated: Phase 4 in progress.*
