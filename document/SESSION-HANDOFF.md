# Nexus — Session Handoff

> This file captures the current state of the project so any new session (or agent) can pick up exactly where we left off.

**Last updated:** 2026-08-08

---

## Current Phase: Phase 4 — GitHub + Docker + Diagnostics Engine

### What's Done (Phases 1–4)

- **Phase 1 — CLI Core:** `nexus init`, `agents`, `open`, interactive shell with easter eggs, `repair` command. 31 tests.
- **Phase 2 — Agent Abstraction:** 4 adapters (Codex, Antigravity, Kiro, Cursor), `Agent` base class, `AgentCapabilities` model, live status detection, PATH resolution for conda. 70 tests.
- **Phase 3 — Project Intelligence:** `nexus scan`, `health`, `status`, `explain`. Shared Memory (`events.jsonl`, `decisions.jsonl`, `agent-handoffs.jsonl`). 53 tests.
- **Phase 4 — GitHub + Docker + Diagnostics:** `nexus issue`, `investigate`, `docker`, `diagnose`, `pr`. Diagnostics engine, models, gh/docker integration. 13 tests.
- **All 167 tests pass.** No known failures.

### What's In Progress (Phase 5 — Warden)

Setting up capability profiles, approval prompts, and security enforcement layer.

### Commands Tested Live & Verified

- `nexus issue 1` — Successfully fetched real issue from `Hariharan-1807-official/Project_Nexus#1` via `gh` CLI, evaluated routing signals, recommended Codex.
- `nexus investigate 1` — Ran read-only analysis on Issue #1, correlated evidence across Git + Docker + Project files without modifying code (ADR-011).
- `nexus docker` — Rendered live container status table (1 running Redis container, 4 exited containers).
- `nexus diagnose` — Gathered cross-source evidence, qualitative output without numeric scores (ADR-006).
- `nexus solve 42` — Negative test confirmed command absence (ADR-011). engine

### Critical Constraints

- `nexus solve` does **NOT** exist yet (ADR-011 — requires Warden from Phase 5)
- `nexus diagnose` output must have **no numeric confidence score** (ADR-006)
- `nexus pr` must **always** stop at confirmation prompt (ADR-002)
- Uses `gh` CLI and `docker` CLI via subprocess (argument lists, never shell strings — ADR-010)

---

## Recent Fixes

| Fix | Description | Date |
|---|---|---|
| Unicode crash | Rich legacy Windows console (`cp1252`) couldn't render emoji/symbols. Fixed with `stdout.reconfigure(encoding="utf-8")` + `_safe_str()` helper + try/except safety net in shell loop. | 2026-08-08 |
| `nexus repair` | Verified working — restores corrupted config files to defaults, warns about corrupt memory logs without touching them (ADR-003). | 2026-08-08 |

---

## Known Gaps (from gap_check.py)

| # | Gap | Severity | Status |
|---|---|---|---|
| 1 | Scan file count might include `.nexus/` files | Low | Warning only — cosmetic |
| 2 | Corrupted config files | Fixed | `nexus repair` handles this |
| 3 | Corrupt `.jsonl` lines silently skipped | Low | `repair` warns, `read_events` skips |
| 4 | Health build check skips bare `.py` dirs | By design | No build system = skip |
| 5 | Scan on empty dir | OK | Graceful empty result |
| 6 | `read_events(limit=N)` boundary | OK | Returns last N correctly |

---

## Test Commands

```powershell
# All tests
python -m pytest tests/ -v

# Phase-specific
python -m pytest tests/test_phase1.py -v
python -m pytest tests/test_phase2.py -v
python -m pytest tests/test_phase3.py -v
python -m pytest tests/test_phase4.py -v    # once built

# Adversarial probe (manual)
python tests/adversarial_probe.py

# Gap check (manual)
python tests/gap_check.py
```

---

## File Map (key files)

| File | Purpose |
|---|---|
| `src/nexus/cli/main.py` | All CLI commands + interactive shell (~820 lines) |
| `src/nexus/agents/base.py` | Agent ABC — the one contract (ADR-005) |
| `src/nexus/agents/{codex,antigravity,kiro,cursor}.py` | One adapter per agent |
| `src/nexus/core/scaffold.py` | `nexus init` logic |
| `src/nexus/core/memory.py` | Append-only `.jsonl` log store |
| `src/nexus/core/intelligence/scanner.py` | `nexus scan` — project detection |
| `src/nexus/core/intelligence/health.py` | `nexus health` — 7 health checks |
| `src/nexus/core/intelligence/status.py` | `nexus status` + `nexus explain` |
| `src/nexus/models/agent.py` | AgentCapabilities, AgentStatus, AgentResult |
| `src/nexus/models/task.py` | Task model with UUID, status, timestamps |
| `src/nexus/models/config.py` | AgentConfig, NexusConfig |
| `document/02-adr.md` | 15 architecture decision records — **read before changing anything** |

---

## ADRs to Remember

| ADR | One-liner |
|---|---|
| ADR-002 | No autonomous destructive actions, ever |
| ADR-003 | Structured artifacts, not conversation |
| ADR-005 | Agent interface is the one contract |
| ADR-006 | No fabricated confidence scores |
| ADR-010 | Python + Typer + Pydantic + subprocess with arg lists |
| ADR-011 | `investigate` (read-only) and `solve` (write) are separate commands |
| ADR-012 | Warden approval scoped to task_id; push/delete always Allow once |
| ADR-015 | Free-only agents: Codex, Antigravity, Kiro, Cursor |
