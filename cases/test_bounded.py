"""FC-070 — bounded compute (v1.4 advisory).

search/code MAY carry limit: N — the client's render budget. The
provider SHOULD stop scanning at ~N and set truncated: true, where
truncated means exactly what a provider's own cap means. Adapters may
honor limit today or ignore it (reader tolerance makes early
consumption safe) — what is nonconforming is claiming a cap without
taking it, or taking it without the flag.
"""

from cases.registry import C
from forge import fc_assert

QUERY = "needle"  # six fixture files carry it


def test_FC070_limit_stops_at_n_and_sets_truncated(adapter):
    c = C("FC-070")
    full = adapter.request("search/code", {"q": QUERY})
    total = len(full.get("items", []))
    fc_assert(total > 1, *c,
              f"fixture sanity: {QUERY!r} must match more than one file "
              f"(got {total}) for the limit probe to mean anything")
    capped = adapter.request("search/code", {"q": QUERY, "limit": 1})
    items = capped.get("items", [])
    truncated = capped.get("truncated", False)
    honored = len(items) <= 1 and truncated is True
    ignored = len(items) == total and not truncated
    fc_assert(honored or ignored, *c,
              "limit is advisory but not unconstrained: either stop at ~N "
              "and set truncated:true (a limit-stop means exactly a "
              "provider's own cap — provably fewer results than the query "
              "matches), or ignore it and return the full untruncated set. "
              f"Got len={len(items)} (full={total}, limit=1), "
              f"truncated={truncated!r}")
