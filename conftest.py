"""pytest wiring: fixture materialization + adapter lifecycle.

The runner spawns the adapter **once per case group** (pytest module)
and speaks the wire directly. Cases that need lifecycle control
(FC-013, FC-050..052) restart or privately spawn children through the
same plumbing.

Provider selection (first match wins):
  1. ``FORGE_PROVIDER`` — shlex string, set by ``run``;
  2. ``PROVIDER`` — shlex string (``PROVIDER="my-adapter --flag" python3 -m pytest``);
  3. default: the vendored reference adapter ``python3 vendor/fs_provider.py``.

The materialized fixture directory is passed to the adapter as the
final argv element unless a ``{fixture}`` placeholder appears in the
command (substituted verbatim). It is always exported as
``FORGE_FIXTURE_DIR``. Set ``FORGE_NO_APPEND=1`` to suppress appending
(adapters that take no path argument).
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from forge import AdapterProc, Fixture  # noqa: E402

ROOT = Path(__file__).parent
FIXTURE_SRC = ROOT / "fixture"

#: rootle's defaults (§Handshake): the user's [cache] max_mb budget and
#: this provider's cache subtree, passed at every initialize.
CACHE_BYTES = 536870912


def provider_spec() -> list[str]:
    spec = os.environ.get("FORGE_PROVIDER") or os.environ.get("PROVIDER")
    if spec:
        return shlex.split(spec)
    return [sys.executable, str(ROOT / "vendor" / "fs_provider.py")]


def provider_argv(fixture_dir: Path) -> list[str]:
    argv = provider_spec()
    if any("{fixture}" in a for a in argv):
        return [a.replace("{fixture}", str(fixture_dir)) for a in argv]
    if os.environ.get("FORGE_NO_APPEND") == "1":
        return argv
    return argv + [str(fixture_dir)]


def materialize(dest: Path) -> Fixture:
    """Copy the canonical fixture and verify it against MANIFEST.sha256
    (content is frozen; a drifted fixture means broken expectations)."""
    shutil.copytree(FIXTURE_SRC, dest)
    manifest = dest / "MANIFEST.sha256"
    import hashlib
    for line in manifest.read_text().splitlines():
        digest, rel = line.split(None, 1)
        rel = rel.strip().lstrip("*").removeprefix("./")
        actual = hashlib.sha256((dest / rel).read_bytes()).hexdigest()
        assert actual == digest, (
            f"fixture drift: {rel} does not match MANIFEST.sha256 "
            f"({actual} != {digest}) — regenerate the manifest or restore "
            f"the canonical content"
        )
    manifest.unlink()  # not part of the served tree
    return Fixture(dest)


@pytest.fixture(scope="session")
def tmp_root():
    path = Path(tempfile.mkdtemp(prefix="forge-conf-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="module")
def forge(tmp_root, request):
    """A private materialized copy of the canonical fixture per case
    group (mutation cases — FC-011 — stay inside their module)."""
    dest = tmp_root / request.module.__name__.rsplit(".", 1)[-1]
    yield materialize(dest)


@pytest.fixture(scope="module")
def adapter(forge):
    """The group's shared adapter: spawned once, initialized with
    rootle's advisory cache params; torn down at module end."""
    proc = AdapterProc(provider_argv(forge.root), env=suite_env_for(forge))
    proc.initialize(cache_bytes=CACHE_BYTES,
                    cache_dir=str(forge.root.parent / "cache"))
    yield proc
    proc.close()


def suite_env_for(forge, hermetic=False, extra=None):
    from forge import suite_env
    return suite_env(forge.root, hermetic=hermetic, extra=extra)


@pytest.fixture
def spawn_adapter(forge):
    """Factory for case-private children (lifecycle group): each spawn
    is registered and killed at test end."""
    procs = []

    def spawn(hermetic=False, extra_env=None):
        proc = AdapterProc(provider_argv(forge.root),
                           env=suite_env_for(forge, hermetic=hermetic,
                                             extra=extra_env))
        procs.append(proc)
        return proc

    yield spawn
    for p in procs:
        p.close()
