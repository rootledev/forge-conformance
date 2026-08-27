"""FC-099's gate (the gate proves the gate, again): an adapter that
honestly declares refs/log/blame=false must sail through the suite —
the revision group skips with a reason, FC-099 itself runs and pins
the flags, and nothing else changes. The stub (tests/incapable.py)
hard-fails every revision ask, so a missing skip-guard anywhere turns
into a loud case failure here rather than a silent over-ask in
production adapters."""

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FC_IN_NODE = re.compile(r"test_FC(\d{3})_")


def run_suite(provider: str):
    env = dict(os.environ)
    env["FORGE_PROVIDER"] = provider
    env.pop("PROVIDER", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "cases", "-q", "--tb=no",
         "-ra", "-rs", "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=900,
    )


def skipped_cases(proc) -> set[str]:
    """Skip summaries in pytest's short form carry the location and the
    reason, not the node id — and every revision skip reason cites its
    case id as ``[FC-0xx]`` (that is why the guards format it so)."""
    out = proc.stdout + proc.stderr
    skipped = set()
    for m in re.finditer(r"^SKIPPED\s+\[[^\]]*\]\s*(.*)$", out, re.M):
        for f in re.finditer(r"\[(FC-\d{3})\]", m.group(1)):
            skipped.add(f.group(1))
    return skipped


def test_refs_false_adapter_is_never_asked_and_still_green():
    provider = shlex.join([sys.executable, str(ROOT / "tests" / "incapable.py")])
    proc = run_suite(provider)
    skipped = skipped_cases(proc)
    want_skipped = {f"FC-{n:03d}" for n in range(90, 99)}
    assert proc.returncode == 0, (
        "the suite must be fully green against an adapter that honestly "
        "declares refs/log/blame=false — any failure means the suite asked "
        "a declined capability (the stub errors on every revision ask):\n"
        f"{proc.stdout[-4000:]}"
    )
    assert skipped == want_skipped, (
        "exactly FC-090..FC-098 must skip (capability-gated group); "
        f"FC-099 must run (it pins the handshake flags):\n"
        f"  skipped:  {sorted(skipped)}\n"
        f"  expected: {sorted(want_skipped)}\n"
        f"  missing:  {sorted(want_skipped - skipped)} (asked anyway?)\n"
        f"  extra:    {sorted(skipped - want_skipped)}\n"
        f"\npytest output:\n{proc.stdout[-4000:]}"
    )
