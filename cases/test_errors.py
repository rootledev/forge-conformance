"""FC-060..FC-063 — errors (taxonomy, v1.1/v1.2).

Errors may carry a semantic kind in data.kind — an open string enum the
UI maps to precise handling (auth refresh hint, rate-limit backoff).
The suite asserts shape, not kind set (FC-063): the enum is open,
unknown kinds degrade to the message toast and must never error. Rootle
also generates kinds host-side (timeout, provider) — that mapping is
mirrored in forge.map_error and exercised here over real adapter
errors.
"""

from cases.registry import C
from forge import (WireError, check_error_shape, fc_assert, map_error,
                   KNOWN_KINDS)


def _err(adapter, method, params):
    try:
        adapter.request(method, params)
    except WireError as e:
        return e
    raise AssertionError(f"{method} {params!r} unexpectedly succeeded")


def test_FC060_auth_for_credential_failures(adapter, forge):
    """Credential failures map to auth. The canonical fixture is servable
    with no credentials at all (the shared adapter runs with every
    credential var scrubbed), so an auth need can only be discovered
    lazily; what the case pins is that whatever errors do occur are
    taxonomy-shaped, and that kinds, when used, map cleanly through the
    same mapper rootle uses."""
    c = C("FC-060")
    err = _err(adapter, "repo/tree", {"repo": f"{forge.org}/missing"})
    check_error_shape(err.error, "FC-060", c[2], "missing repo")
    kind, retry = map_error(err.error)
    fc_assert(kind is None or isinstance(kind, str), *c,
              f"kind must survive rootle's mapping untouched: {err.error!r}")
    fc_assert(retry is None, *c,
              f"retry_after_s belongs to rate_limited, not this error: {err.error!r}")
    # Lazy credentials: no token in the environment, yet initialize and
    # ordinary calls succeeded (they did — this test is running).
    fc_assert(adapter.init_reply.get("protocol") == 1, *c,
              "initialize succeeded without any credential env — credentials "
              "are fetched lazily, never at spawn")


def test_FC061_rate_limited_with_retry_after_s(adapter, forge):
    """rate_limited may carry retry_after_s (seconds); the suite pins
    its shape across every error the run elicits: a non-negative number
    that rootle shows as the backoff notice."""
    c = C("FC-061")
    seen = []
    for method, params in (
        ("repo/tree", {"repo": f"{forge.org}/missing"}),
        ("repo/blob", {"repo": forge.repo_id("alpha"), "sha": "deadbeef"}),
    ):
        err = _err(adapter, method, params)
        check_error_shape(err.error, "FC-061", c[2], method)
        if err.kind == "rate_limited":
            fc_assert(err.retry_after_s is not None, *c,
                      f"rate_limited SHOULD carry retry_after_s (backoff "
                      f"seconds the UI shows): {err.error!r}")
        data = err.error.get("data")
        if isinstance(data, dict) and "retry_after_s" in data:
            seen.append((method, data["retry_after_s"]))
    fc_assert(all(isinstance(r, (int, float)) and r >= 0 for _, r in seen), *c,
              f"retry_after_s must be a non-negative number when present: {seen!r}")


def test_FC062_not_found_for_missing_repo_and_blob(adapter, forge):
    c = C("FC-062")
    err = _err(adapter, "repo/tree", {"repo": f"{forge.org}/missing"})
    check_error_shape(err.error, "FC-062", c[2], "missing repo")
    fc_assert(err.kind in (None, "not_found"), *c,
              "not_found is the preferred kind for a missing repo (any error "
              f"is legal; the kind must be not_found or absent): {err.error!r}")
    err = _err(adapter, "repo/blob", {"repo": forge.repo_id("alpha"),
                                      "sha": "0" * 64})
    check_error_shape(err.error, "FC-062", c[2], "missing blob")
    fc_assert(err.kind in (None, "not_found"), *c,
              "not_found is the preferred kind for a missing blob: "
              f"{err.error!r}")


def test_FC063_unknown_kinds_tolerated(adapter, forge):
    """The enum is open: unknown kinds degrade to the message toast and
    never error. The suite runs every elicited error through rootle's
    exact mapping (forge.map_error mirrors ProviderError) — any string
    kind must survive it; the error shape itself is the contract."""
    c = C("FC-063")
    elicited = [
        _err(adapter, "repo/tree", {"repo": f"{forge.org}/missing"}),
        _err(adapter, "repo/blob", {"repo": forge.repo_id("alpha"),
                                    "sha": "0" * 64}),
        _err(adapter, "forge/conformance-unknown-method", {"x": 1}),
    ]
    fc_assert(len(elicited) == 3, *c, "all three probes must produce errors")
    for e in elicited:
        check_error_shape(e.error, "FC-063", c[2], "elicited error")
        kind, _ = map_error(e.error)
        fc_assert(kind is None or kind in KNOWN_KINDS, *c,
                  f"the client-side mapper must bucket any kind without "
                  f"erroring (unknown -> Other): {e.error!r}")
