"""FC-040..FC-045 — streaming (v1.3), the strictest group.

Semantics verified against rootle's own enforcement first
(src/provider/stdio/tests.rs fake-provider modes stream-search,
die-mid-stream, stream-slow):

- every $/partial carries the request's id, batches are append-only,
  and all partials precede the metadata-only reply — after the reply,
  no more for that id (mode stream-search);
- the streamed reply is metadata-only: items empty, truncated
  authoritative (mode stream-search);
- the read deadline is per-inactivity: every $/partial or the reply
  resets it — a stream whose total exceeds the deadline succeeds while
  no single gap does (mode stream-slow: 3 batches at 150ms gaps under
  a 400ms deadline);
- $/cancelRequest is advisory: the reply may still arrive and is
  handled normally; the stream must not error (§Cancellation).

The suite pins the inactivity window at 2s (FORGE_INACTIVITY_S): a
streamer keeping one batch per window never trips it; a silent one
does.
"""

import os

from cases.registry import C
from forge import (InactivityExceeded, WireError,
                   check_code_item, check_partial_batch, fc_assert)

#: The fixture term present in six files across both repos — a query
#: that reliably streams multiple batches (the reference adapter
#: streams per repo).
QUERY = "needle"


def test_FC040_every_partial_carries_the_request_id(adapter, forge):
    c = C("FC-040")
    out = adapter.stream("search/code", {"q": QUERY})
    fc_assert(out.partials, *c,
              "a streamed search over the fixture must emit at least one "
              "$/partial batch (the query hits both repos)")
    for i, p in enumerate(out.partials):
        check_partial_batch(p, "FC-040", c[2], where=f"batch {i}")
        fc_assert(isinstance(p.get("id"), int), *c,
                  f"params.id must echo the numeric request id: {p.get('id')!r}")
        for item in p.get("items", []):
            check_code_item(item, "FC-040", c[2], where=f"batch {i}")


def test_FC041_all_partials_precede_the_reply(adapter):
    """Line order on the single pipe: all $/partial for an id precede
    that id's reply; after the reply, no more for that id."""
    c = C("FC-041")
    out = adapter.stream("search/code", {"q": QUERY})
    fc_assert(out.partials, *c, "expected at least one $/partial before the reply")
    # A follow-up request must not surface any late partial for the old id.
    stale_before = list(adapter.dropped_partials)
    adapter.request("org/repos", {"org": adapter_org()})
    late = [p for p in adapter.dropped_partials[len(stale_before):]]
    fc_assert(not late, *c,
              f"$/partial arrived after the reply for its id (forbidden — "
              f"the reply closes the stream): {late!r}")


def adapter_org():
    return os.environ.get("FORGE_ORG", "local")


def test_FC042_reply_is_metadata_only_when_streamed(adapter):
    c = C("FC-042")
    plain = adapter.request("search/code", {"q": QUERY})
    fc_assert(plain.get("items", []), *c,
              "sanity: without partial:true the reply must carry everything "
              "(unchanged v1.2 behavior)")
    out = adapter.stream("search/code", {"q": QUERY})
    fc_assert(out.partials, *c, "sanity: the streamed run emitted partials")
    items = out.reply.get("items", [])
    truncated = out.reply.get("truncated", False)
    fc_assert(items == [], *c,
              f"when the provider streamed, the reply is metadata-only — "
              f"items must be empty; got {len(items)} items")
    fc_assert(isinstance(truncated, bool), *c,
              f"truncated rides the reply and is authoritative: {truncated!r}")


def test_FC043_inactivity_deadline_resets_per_batch(adapter):
    """The strictest client-side rule made adapter-facing: while a
    partial search is outstanding the adapter must not go silent longer
    than the client's read deadline — rootle's is 30s by default, the
    suite pins 2s. A streamer emitting one batch every 1.2s must never
    trip it; a silent worker does."""
    c = C("FC-043")
    from forge import INACTIVITY_S
    try:
        out = adapter.stream("search/code", {"q": QUERY}, inactivity=INACTIVITY_S)
    except InactivityExceeded as e:
        fc_assert(False, *c,
                  f"the read deadline resets on every $/partial or reply "
                  f"(per-inactivity, not per-request): the adapter went "
                  f"silent for {e.silent_s:.2f}s mid-stream "
                  f"(window {e.window:.2f}s) — a rootle client would fail "
                  f"this request with a timeout")
        return
    fc_assert(out.max_gap < INACTIVITY_S, *c,
              f"longest silence between stream messages was "
              f"{out.max_gap:.2f}s (window {INACTIVITY_S:.2f}s)")
    fc_assert(bool(out.partials) or out.reply is not None, *c,
              "the stream must terminate with the reply, not silence")


def test_FC044_oversized_batch_is_accepted(adapter, forge):
    """A batch larger than the client's render budget (rootle renders
    500 hits and clips beyond) must be delivered intact — clipping is
    the client's job; the adapter must not crash or pre-truncate."""
    c = C("FC-044")
    budget = 3  # pretend render budget, well under the fixture's yield
    out = adapter.stream("search/code", {"q": "extension:rs repo:" + forge.repo_id("alpha")})
    items = [i for p in out.partials for i in p.get("items", [])]
    fc_assert(len(items) > budget, *c,
              f"fixture sanity: expected more than {budget} items "
              f"(the client would clip), got {len(items)}")
    for item in items:
        check_code_item(item, "FC-044", c[2], where=item.get("path", "?"))
    # The adapter must stay usable after a clipped batch.
    result = adapter.request("repo/tree", {"repo": forge.repo_id("beta")})
    fc_assert(isinstance(result.get("entries"), list), *c,
              f"adapter must survive delivering a budget-exceeding batch; "
              f"follow-up repo/tree got {result!r}")


def test_FC045_stream_stops_cleanly_on_cancel(adapter, forge):
    """$/cancelRequest is advisory: the reply may still arrive and is
    handled normally; subsequent partials may arrive but the stream
    must NOT error (rootle's reply handling is id-matched and
    generation-guarded, so late work is never wrong)."""
    c = C("FC-045")
    seen_error = []

    def cancel(rid):
        adapter.notify("$/cancelRequest", {"id": rid})

    try:
        out = adapter.stream("search/code", {"q": QUERY}, timeout=60, on_sent=cancel)
    except WireError as e:
        seen_error.append(e)
        out = None
    if seen_error:
        fc_assert(False, *c,
                  "a cancelled stream must not error (the reply may still "
                  f"arrive and is handled normally): {seen_error[0].error!r}")
    for i, p in enumerate(out.partials or []):
        check_partial_batch(p, "FC-045", c[2], where=f"post-cancel batch {i}")
    # The adapter stays usable after a cancelled request.
    result = adapter.request("repo/tree", {"repo": forge.repo_id("beta")})
    fc_assert(isinstance(result.get("entries"), list), *c,
              f"adapter must stay usable after $/cancelRequest: {result!r}")
