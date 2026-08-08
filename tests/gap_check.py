"""Gap analysis script — run: python tests/gap_check.py"""
import sys, json
sys.path.insert(0, "src")

from pathlib import Path
from nexus.core.intelligence.scanner import scan_project
from nexus.core.memory import Memory, EventType

ROOT = Path(".")
NEXUS = ROOT / ".nexus"

print("=" * 60)
print("GAP CHECK — Nexus Project")
print("=" * 60)

# ── GAP 1: Does scan count .nexus/ files? ────────────────────────
print("\n[1] .nexus/ file exclusion from scan count")
ctx = scan_project(ROOT)
nexus_files = sum(1 for p in NEXUS.rglob("*") if p.is_file())
reported    = ctx["structure"]["file_count"]
print(f"    .nexus/ file count  : {nexus_files}")
print(f"    scan reported count : {reported}")
# If scan is excluding .nexus correctly, reported << nexus_files
if reported < nexus_files * 2:
    print("    Result: LIKELY OK — scan count appears to exclude .nexus/")
else:
    print("    Result: WARNING — scan may be counting .nexus/ files")

# ── GAP 2: Corrupted permissions.json never auto-healed ──────────
print("\n[2] Corrupted config not auto-healed by init (by design, ADR-003)")
perms = NEXUS / "config" / "permissions.json"
content = perms.read_text(encoding="utf-8").strip()
try:
    json.loads(content)
    print("    permissions.json: VALID JSON")
except json.JSONDecodeError:
    print(f"    permissions.json: CORRUPT ({content[:40]!r})")
    print("    This is a real gap — needs nexus repair command")

# ── GAP 3: Memory corrupt lines skipped, not reported ────────────
print("\n[3] Corrupted events.jsonl — silent skip vs. reported")
mem = Memory(ROOT)
events = mem.read_events()
raw_lines = (NEXUS / "memory" / "events.jsonl").read_text(encoding="utf-8").splitlines()
valid_lines = [l for l in raw_lines if l.strip()]
failed = len(valid_lines) - len(events)
print(f"    Raw non-empty lines : {len(valid_lines)}")
print(f"    Successfully parsed : {len(events)}")
print(f"    Silently skipped    : {failed}")
if failed > 0:
    print("    Gap: corrupt lines are silently ignored — no warning to user")
else:
    print("    OK — all lines valid")

# ── GAP 4: health on a dir with no pyproject but .py files ───────
print("\n[4] Health build check on a dir with bare .py files (no pyproject)")
import tempfile, os
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    (tdp / "script.py").write_text("x = 1 + 1\n", encoding="utf-8")
    from nexus.core.intelligence.health import run_health_checks
    report = run_health_checks(tdp)
    build = next(c for c in report.checks if c.name == "build")
    print(f"    build status: {build.status.value} — {build.summary}")

# ── GAP 5: scan on a dir with 0 files ────────────────────────────
print("\n[5] Scan on a nearly empty dir")
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    ctx2 = scan_project(tdp)
    print(f"    languages : {ctx2['languages']}")
    print(f"    frameworks: {ctx2['frameworks']}")
    print(f"    file_count: {ctx2['structure']['file_count']}")
    print("    Result: OK — graceful empty result" if ctx2["languages"] == [] else "    Unexpected detection")

# ── GAP 6: Memory read_events limit parameter ────────────────────
print("\n[6] Memory read_events limit boundary")
with tempfile.TemporaryDirectory() as td:
    m = Memory(Path(td))
    for i in range(10):
        m.log_event(EventType.system, agent=None, action=f"action-{i}", result="ok")
    last3 = m.read_events(limit=3)
    print(f"    Requested 3 from 10: got {len(last3)}")
    assert len(last3) == 3, f"Expected 3, got {len(last3)}"
    assert last3[-1]["action"] == "action-9", "Should be most recent"
    print("    Result: OK — limit returns last N correctly")

print("\n" + "=" * 60)
print("Gap check complete.")
print("=" * 60)
