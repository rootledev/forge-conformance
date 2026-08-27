"""FC-050..FC-054 — lifecycle (restart obligations).

rootle kills the child on exit and restarts it after any death,
re-running initialize before proceeding — only a child that passed the
handshake serves requests. Startup MUST be cheap and idempotent;
credentials are fetched lazily (first use, not at spawn). Reader
tolerance is normative in both directions (§Transport).

This group manages its own children (one per case) because each case
kills or spawns on its own schedule.
"""

import time

from cases.registry import C
from forge import (AdapterProc, ProviderDead, WireError, fc_assert, suite_env)
from conftest import CACHE_BYTES, provider_argv

INIT_TIMEOUT = 15.0  # "initialize completes again within the request timeout"


def _spawn(forge, hermetic=False, extra_env=None):
    proc = AdapterProc(provider_argv(forge.root),
                       env=suite_env(forge.root, hermetic=hermetic,
                                     extra=extra_env))
    return proc


def test_FC050_kill_mid_session_respawn_is_cheap_and_idempotent(forge):
    """rootle may kill and re-initialize the child an unbounded number
    of times within one session: respawn + handshake must complete well
    inside the request timeout, every time."""
    c = C("FC-050")
    repo = forge.repo_id("alpha")
    for generation in range(3):
        proc = _spawn(forge)
        t0 = time.monotonic()
        reply = proc.initialize(cache_bytes=CACHE_BYTES,
                                cache_dir=str(forge.cache_dir),
                                timeout=INIT_TIMEOUT)
        elapsed = time.monotonic() - t0
        fc_assert(reply.get("protocol") == 1, *c,
                  f"generation {generation}: initialize must complete with "
                  f"protocol 1 after a kill; got {reply!r}")
        fc_assert(elapsed < INIT_TIMEOUT, *c,
                  f"generation {generation}: respawn + initialize took "
                  f"{elapsed:.2f}s — startup must be cheap and idempotent")
        tree = proc.request("repo/tree", {"repo": repo})
        fc_assert(isinstance(tree.get("entries"), list) and tree["entries"], *c,
                  f"generation {generation}: only a child that passed the "
                  f"handshake serves requests — repo/tree got {tree!r}")
        proc.kill()  # mid-session death, exactly what rootle does on exit



def test_FC051_initialize_reruns_every_generation_with_same_cache_params(forge):
    """rootle passes cache_bytes/cache_dir at every initialize — spawns
    and respawns alike (§Handshake cache budget). With the fixture's
    API token unset, each generation must still handshake."""
    c = C("FC-051")
    cache_dir = str(forge.cache_dir)
    gen0 = _spawn(forge)
    r0 = gen0.initialize(cache_bytes=CACHE_BYTES, cache_dir=cache_dir,
                         timeout=INIT_TIMEOUT)
    gen0.kill()
    gen1 = _spawn(forge)
    r1 = gen1.initialize(cache_bytes=CACHE_BYTES, cache_dir=cache_dir,
                         timeout=INIT_TIMEOUT)
    for n, r in (("first", r0), ("second", r1)):
        fc_assert(r.get("protocol") == 1, *c,
                  f"the {n} generation must answer initialize (protocol 1) "
                  f"with the same advisory cache params; got {r!r}")
    gen1.close()


def test_FC052_no_network_io_during_initialize(forge):
    """Credentials are lazy — read on first use, never at spawn (restart
    obligations): with a hermetic environment and the fixture's API
    token unset, initialize must complete without touching anything
    outside stdio; setting a token later changes nothing at spawn."""
    c = C("FC-052")
    hermetic = _spawn(forge, hermetic=True)
    t0 = time.monotonic()
    reply = hermetic.initialize(cache_bytes=CACHE_BYTES,
                                cache_dir=str(forge.cache_dir),
                                timeout=INIT_TIMEOUT)
    fc_assert(reply.get("protocol") == 1, *c,
              f"initialize under a hermetic env (no credential vars, no "
              f"fixture token) must succeed — fetch credentials lazily; "
              f"got {reply!r}")
    fc_assert(time.monotonic() - t0 < INIT_TIMEOUT, *c,
              "initialize must not block on network I/O (a hung cred fetch "
              "at spawn would blow the handshake deadline)")
    tree = hermetic.request("repo/tree", {"repo": forge.repo_id("beta")})
    fc_assert(isinstance(tree.get("entries"), list), *c,
              f"the canonical fixture is servable with no credentials; got {tree!r}")
    hermetic.close()
    # ...and set later: a bogus token must not break spawn either (lazy).
    tok = _spawn(forge, hermetic=True, extra_env={"FORGE_TOKEN": "forge-invalid"})
    reply = tok.initialize(cache_bytes=CACHE_BYTES,
                           cache_dir=str(forge.cache_dir),
                           timeout=INIT_TIMEOUT)
    fc_assert(reply.get("protocol") == 1, *c,
              f"a token present-but-unvalidated at spawn must not break "
              f"initialize (credentials are lazy): {reply!r}")
    tok.close()


def test_FC053_unknown_fields_in_requests_are_ignored(forge):
    """Reader tolerance is normative in both directions: unknown fields
    in requests MUST be ignored (v1.1 additions are additive for
    exactly this reason)."""
    c = C("FC-053")
    proc = _spawn(forge)
    proc.initialize(cache_bytes=CACHE_BYTES, cache_dir=str(forge.cache_dir),
                    timeout=INIT_TIMEOUT, future_field={"a": [1]})
    tree = proc.request("repo/tree", {"repo": forge.repo_id("alpha"),
                                      "zorglub": 42, "partial": False})
    fc_assert(isinstance(tree.get("entries"), list) and tree["entries"], *c,
              f"repo/tree with unknown extra params must behave normally; "
              f"got {tree!r}")
    blob = proc.request("search/code", {"q": "needle", "limit": 2,
                                        "unknown_qualifier": "x"})
    fc_assert(isinstance(blob.get("items"), list), *c,
              f"search/code with unknown extra params must behave normally; "
              f"got {blob!r}")
    proc.close()


def test_FC054_unsolicited_notifications_are_ignored(forge):
    """Unsolicited notifications MUST be ignored: they carry no id, are
    never replied to, and must not wedge the child."""
    c = C("FC-054")
    proc = _spawn(forge)
    proc.initialize(cache_bytes=CACHE_BYTES, cache_dir=str(forge.cache_dir),
                    timeout=INIT_TIMEOUT)
    proc.notify("$/cancelRequest", {"id": 999999})   # cancel for unknown id
    proc.notify("window/logMessage", {"message": "unsolicited"})
    proc.notify("$/progress", {"token": "nobody-asked", "value": {"kind": "begin"}})
    tree = proc.request("repo/tree", {"repo": forge.repo_id("beta")})
    fc_assert(isinstance(tree.get("entries"), list), *c,
              f"the child must keep serving after unsolicited notifications; "
              f"got {tree!r}")
    strays = proc.silence(1.0)
    strays = [s for s in strays if s is not None]
    fc_assert(not strays, *c,
              f"notifications must never be replied to; stray output: {strays!r}")
    proc.close()
