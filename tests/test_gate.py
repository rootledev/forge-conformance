"""The gate test (plans/0015 verification): the deliberately
nonconforming adapter fails exactly FC-013 and FC-043 — and nothing
else. A gate that missed those would be under-fitted; one that failed
more would be over-fitted."""

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
         "-ra", "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=900,
    )


def failed_cases(proc) -> set[str]:
    out = proc.stdout + proc.stderr
    failed = set()
    for m in re.finditer(r"^(?:FAILED|ERROR)\s+(\S+)", out, re.M):
        node = m.group(1)
        f = FC_IN_NODE.search(node)
        if f:
            failed.add(f"FC-{f.group(1)}")
    return failed


def test_nonconforming_adapter_fails_exactly_FC013_and_FC043():
    provider = shlex.join([sys.executable, str(ROOT / "tests" / "nonconforming.py")])
    proc = run_suite(provider)
    failed = failed_cases(proc)
    assert failed == {"FC-013", "FC-043"}, (
        f"the nonconforming adapter must fail exactly FC-013 (sha respawn "
        f"stability) and FC-043 (inactivity deadline) — it failed:\n"
        f"  {sorted(failed)}\n"
        f"missing: {sorted({'FC-013', 'FC-043'} - failed)} (gate under-fitted)\n"
        f"extra:   {sorted(failed - {'FC-013', 'FC-043'})} (gate over-fitted)\n"
        f"\npytest output:\n{proc.stdout[-4000:]}"
    )
    assert proc.returncode != 0, "the suite run must be red against it"
