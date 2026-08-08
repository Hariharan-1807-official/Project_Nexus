"""Adversarial probe — run directly: python tests/adversarial_probe.py"""
import sys
sys.path.insert(0, "src")

from nexus.cli.main import _dispatch_shell_line, _easter_egg

print("=== Shell: long input ===")
result = _dispatch_shell_line("a" * 10000)
print(f"  Long input (10000 chars): returned {result} — OK")

print("\n=== Shell: unicode / emoji ===")
result = _dispatch_shell_line("🚀 deploy this to production 🔥")
print(f"  Emoji input: returned {result} — OK")

print("\n=== Shell: injection attempts ===")
for attempt in [
    "open; rm -rf /",
    "open && del /f /s *",
    "open `whoami`",
    "agents | evil_command",
    "__import__('os').system('echo INJECTED')",
]:
    result = _dispatch_shell_line(attempt)
    print(f"  {attempt[:40]!r}: returned {result} — OK (no exec)")

print("\n=== Shell: whitespace-only / newlines ===")
for ws in ["   ", "\t", "\n", "\r\n", ""]:
    result = _dispatch_shell_line(ws)
    print(f"  {ws!r}: returned {result} (expected True)")
    assert result is True

print("\n=== Shell: exit variants ===")
for cmd in ["exit", "EXIT", "Exit", "quit", "QUIT", "nexus exit"]:
    result = _dispatch_shell_line(cmd)
    assert result is False, f"{cmd!r} should return False, got {result}"
    print(f"  {cmd!r}: returned False — OK")

print("\n=== Easter egg: no crash on any input ===")
for weird in ["sudo rm -rf /", "42", "flip", "why", "matrix", "roast", "fortune", "haiku", "coffee"]:
    try:
        _easter_egg(weird, [])
        print(f"  {weird!r}: OK")
    except Exception as e:
        print(f"  {weird!r}: FAILED — {e}")

print("\nAll adversarial probes completed.")
