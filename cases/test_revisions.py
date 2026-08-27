"""FC-090..FC-099 — revisions (v1.5, plans/0016 M1).

The revision surface: ``repo/refs``, ``ref`` on ``repo/tree``,
``repo/log``, ``repo/blob_at``, ``repo/blame`` — gated by the
handshake capabilities ``refs`` / ``log`` / ``blame`` (all default
**false**: absent means default-branch-only, since many backends
can't answer them; a backend that can, says so).

The fixture for this group is ``fixture/vcs`` — a real git repo the
suite materializes deterministically (see FIXTURES.md). Expectations
are computed from that repo via git (commit ids, author dates, blob
bytes), never hard-coded; ids on the wire stay opaque (§Content
ids), so the cases assert bytes and id *behavior*, exactly like the
alpha/beta groups.

Skip rules (read capabilities first — the suite never asks a
capability the adapter honestly declined, FC-099):

- git unavailable in this environment → the whole group except
  FC-099 skips (fixture/vcs could not be materialized);
- ``refs`` false/absent → FC-090..093, FC-096, FC-097 skip;
- ``log`` false/absent → FC-094, FC-095 skip;
- ``blame`` false/absent → FC-098 skips;
- FC-099 always runs: the flags themselves must be honest.
"""

import base64
import datetime

import pytest

from cases.registry import C
from forge import WireError, check_error_shape, fc_assert

#: The revision fixture repo and the paths its history encodes.
VCS = "vcs"
DIVERGES = "DIVERGES.md"       # differs between main and feature
HISTORY = "HISTORY.md"         # three commits of history (the log file)
BLAME = "BLAME.md"             # two commits, one line each side of blame
TAG = "v1.0"
UNKNOWN_REF = "forge-conformance-no-such-ref"
UNKNOWN_PATH = "forge/no-such-file.md"

#: Skip reasons carry the case id and the rule that fired, so `-ra`
#: output says exactly why a group did not run.
def _skip_git(cid):
    pytest.skip(
        f"[{cid}] git is not available — fixture/vcs (the revision repo) "
        "could not be materialized; FC-090..098 require it (FIXTURES.md)")


def _caps(adapter):
    caps = adapter.init_reply.get("capabilities")
    return caps if isinstance(caps, dict) else {}


def _skip_cap(adapter, cap, cid):
    val = _caps(adapter).get(cap)
    if val is not True:
        pytest.skip(
            f"[{cid}] adapter declares capabilities.{cap}={val!r} — absent/"
            "false means default-branch-only (§Handshake, v1.5): the suite "
            "never asks (FC-099)")


def _need(adapter, forge, cap, cid):
    """Common guard: fixture first (no repo to ask about otherwise),
    then the capability the case exercises."""
    if forge.vcs is None:
        _skip_git(cid)
    _skip_cap(adapter, cap, cid)


def _iso(datestr, cid, where):
    """Parse an ISO-8601 date (the spec's wire form; `Z` tolerated —
    Python <3.11 fromisoformat rejects it, adapters may emit it)."""
    text = datestr.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        fc_assert(False, cid, "date must be ISO-8601", C(cid)[2],
                  f"{where}: cannot parse {datestr!r} as ISO-8601 "
                  "(git's %aI shape, e.g. 2026-01-06T10:00:00+00:00)")


def _tree_entry(result, path, cid):
    for e in result.get("entries", []):
        if e.get("path") == path and e.get("type") == "blob":
            return e
    fc_assert(False, cid, "tree must carry the fixture path", C(cid)[2],
              f"no blob entry for {path!r} in {result!r}")


# -- refs --------------------------------------------------------------------

def test_FC090_refs_shape(adapter, forge):
    _need(adapter, forge, "refs", "FC-090")
    c = C("FC-090")
    result = adapter.request("repo/refs", {"repo": forge.repo_id(VCS)})
    branches, tags = result.get("branches"), result.get("tags")
    fc_assert(isinstance(branches, list) and branches, *c,
              f"branches must be a non-empty list (fixture/vcs has two): "
              f"{result!r}")
    fc_assert(isinstance(tags, list), *c,
              f"tags must be a list (defaults to [] when empty): {result!r}")
    names = set()
    for b in branches:
        fc_assert(isinstance(b, dict), *c, f"branch entry: {b!r}")
        fc_assert(isinstance(b.get("name"), str) and b["name"], *c,
                  f"branch.name must be a non-empty string: {b!r}")
        fc_assert(isinstance(b.get("sha"), str) and b["sha"], *c,
                  f"branch.sha must be a non-empty string: {b!r}")
        fc_assert("default" not in b or isinstance(b["default"], bool), *c,
                  f"default is optional and boolean (at most one branch): {b!r}")
        names.add(b["name"])
    defaults = [b for b in branches if b.get("default") is True]
    fc_assert(len(defaults) <= 1, *c,
              "at most one branch carries default:true — it names the "
              f"branch the UI opens by default: {branches!r}")
    if defaults:
        fc_assert(defaults[0]["name"] == forge.vcs.head_branch(), *c,
                  "the marked default must be HEAD's branch (the fixture's "
                  f"HEAD is {forge.vcs.head_branch()!r}): {defaults[0]!r}")
    fc_assert({"main", "feature"} <= names, *c,
              "the fixture repo carries branches main and feature — refs "
              f"must list them: got {sorted(names)}")
    tag_names = set()
    for t in tags:
        fc_assert(isinstance(t, dict), *c, f"tag entry: {t!r}")
        fc_assert(isinstance(t.get("name"), str) and t["name"], *c,
                  f"tag.name must be a non-empty string: {t!r}")
        fc_assert(isinstance(t.get("sha"), str) and t["sha"], *c,
                  f"tag.sha must be a non-empty string: {t!r}")
        tag_names.add(t["name"])
    fc_assert(TAG in tag_names, *c,
              f"the fixture repo carries tag {TAG!r}: got {sorted(tag_names)}")


# -- tree at ref ---------------------------------------------------------------

def test_FC091_tree_at_ref_serves_that_ref(adapter, forge):
    _need(adapter, forge, "refs", "FC-091")
    c = C("FC-091")
    repo = forge.repo_id(VCS)
    main_tree = adapter.request("repo/tree", {"repo": repo})
    feat_tree = adapter.request("repo/tree", {"repo": repo, "ref": "feature"})
    fc_assert(feat_tree.get("branch") == "feature", *c,
              "the reply's branch names what was actually served — with "
              f"ref=feature it must echo \"feature\": {feat_tree.get('branch')!r}")
    main_entry = _tree_entry(main_tree, DIVERGES, "FC-091")
    feat_entry = _tree_entry(feat_tree, DIVERGES, "FC-091")
    fc_assert(main_entry["sha"] != feat_entry["sha"], *c,
              "DIVERGES.md differs between main and feature — its content "
              "id must differ between the two trees (§Content ids): "
              f"{main_entry['sha']!r} == {feat_entry['sha']!r}")
    main_bytes = forge.vcs.show_bytes("main", DIVERGES)
    feat_bytes = forge.vcs.show_bytes("feature", DIVERGES)
    fc_assert(main_bytes != feat_bytes, *c, "fixture sanity: DIVERGES.md "
              "must differ between the branches")
    for ref, want in (("main", main_bytes), ("feature", feat_bytes)):
        got = adapter.request("repo/blob_at", {"repo": repo, "path": DIVERGES,
                                               "ref": ref})
        data = base64.b64decode(got.get("bytes_b64", ""))
        fc_assert(data == want, *c,
                  f"blob_at at ref={ref!r} must serve exactly that ref's "
                  f"bytes ({len(want)} expected, got {len(data)})")


def test_FC092_tree_at_unknown_ref_is_not_found(adapter, forge):
    _need(adapter, forge, "refs", "FC-092")
    c = C("FC-092")
    try:
        result = adapter.request("repo/tree", {"repo": forge.repo_id(VCS),
                                               "ref": UNKNOWN_REF})
        fc_assert(False, *c,
                  f"an unknown ref must produce a JSON-RPC error, not a "
                  f"result: {result!r}")
    except WireError as e:
        check_error_shape(e.error, "FC-092", c[2], "repo/tree unknown ref")
        fc_assert(e.kind in (None, "not_found"), *c,
                  "not_found is the preferred kind for an unknown ref (any "
                  f"error is legal; kind must be not_found or absent): {e.error!r}")


def test_FC093_sha_discipline_across_refs(adapter, forge):
    _need(adapter, forge, "refs", "FC-093")
    c = C("FC-093")
    repo = forge.repo_id(VCS)
    main_tree = adapter.request("repo/tree", {"repo": repo})
    feat_tree = adapter.request("repo/tree", {"repo": repo, "ref": "feature"})
    main_hist = _tree_entry(main_tree, HISTORY, "FC-093")
    feat_hist = _tree_entry(feat_tree, HISTORY, "FC-093")
    fc_assert(main_hist["sha"] != feat_hist["sha"], *c,
              "the cache invariant (plans/0016 M1a): the same path at two "
              "refs with different content must carry different content "
              "ids — rootle caches both trees content-keyed; an id shared "
              f"across differing bytes serves stale content")
    main_readme = _tree_entry(main_tree, "README.md", "FC-093")
    feat_readme = _tree_entry(feat_tree, "README.md", "FC-093")
    fc_assert(main_readme["sha"] == feat_readme["sha"], *c,
              "ids are content-keyed, not ref-keyed: README.md is "
              "byte-identical on both branches, so its id must be the "
              "same in both trees (a ref-keyed id would split the cache "
              "for no reason)")


# -- log -----------------------------------------------------------------------

def test_FC094_log_shape_newest_first_iso_path_filter(adapter, forge):
    _need(adapter, forge, "log", "FC-094")
    c = C("FC-094")
    repo = forge.repo_id(VCS)
    expected_all = forge.vcs.log_shas("main")
    expected_hist = forge.vcs.log_shas("main", HISTORY)
    full = adapter.request("repo/log", {"repo": repo})
    items = full.get("items", [])
    _assert_log_items(items, expected_all, full.get("truncated", False), c)
    _iso(items[0]["date"], "FC-094", "items[0]")  # sanity: parses

    pathed = adapter.request("repo/log", {"repo": repo, "path": HISTORY})
    pitems = pathed.get("items", [])
    _assert_log_items(pitems, expected_hist, pathed.get("truncated", False), c)
    fc_assert(len(pitems) < len(items), *c,
              "path filters the log to commits touching it — HISTORY.md "
              f"has {len(expected_hist)} commits of the repo's "
              f"{len(expected_all)}, so the filtered log must be narrower: "
              f"got {len(pitems)} vs {len(items)}")
    fc_assert([i["sha"] for i in pitems] == expected_hist, *c,
              "the filtered log must be exactly the commits that touched "
              f"HISTORY.md, newest first (git order): "
              f"{[i['sha'][:8] for i in pitems]} vs "
              f"{[s[:8] for s in expected_hist]}")


def _assert_log_items(items, expected, truncated, c):
    fc_assert(isinstance(items, list) and items, *c,
              f"items must be a non-empty list (fixture/vcs has history): {items!r}")
    shas = [i.get("sha") for i in items]
    if truncated is True:
        fc_assert(shas == expected[:len(shas)], *c,
                  "a provider-chosen budget is fine (truncated:true) but "
                  "the items must be a newest-first prefix of the log")
    else:
        fc_assert(shas == expected, *c,
                  "without truncated:true the log must be the full "
                  "newest-first commit list (fixture-known from git): "
                  f"{[str(s)[:8] for s in shas]} vs "
                  f"{[s[:8] for s in expected]}")
    previous = None
    for n, item in enumerate(items):
        for f in ("sha", "subject", "author"):
            fc_assert(isinstance(item.get(f), str) and item[f], *c,
                      f"items[{n}].{f} must be a non-empty string: {item!r}")
        when = _iso(item.get("date", ""), "FC-094", f"items[{n}]")
        if previous is not None:
            fc_assert(when <= previous, *c,
                      "items are newest first — dates must never go up: "
                      f"items[{n - 1}] {previous.isoformat()} -> "
                      f"items[{n}] {when.isoformat()}")
        previous = when


def test_FC095_log_limit_stops_at_n_and_sets_truncated(adapter, forge):
    _need(adapter, forge, "log", "FC-095")
    c = C("FC-095")
    expected_hist = forge.vcs.log_shas("main", HISTORY)  # exactly 3 commits
    result = adapter.request("repo/log", {"repo": forge.repo_id(VCS),
                                          "path": HISTORY, "limit": 2})
    items = result.get("items", [])
    fc_assert(1 <= len(items) <= 2, *c,
              "limit rides the bounded-compute contract: stop at ~N — "
              f"limit=2 must yield at most 2 items (got {len(items)}); "
              "never compute results the client would clip")
    fc_assert(result.get("truncated") is True, *c,
              "stopping at the cap MUST set truncated:true — it means "
              "provably fewer results than the query matches (HISTORY.md "
              f"has {len(expected_hist)} commits, the cap was 2): "
              f"{result!r}")
    fc_assert([i["sha"] for i in items] == expected_hist[:len(items)], *c,
              "the capped log stays newest-first from the top")


# -- blob_at -------------------------------------------------------------------

def test_FC096_blob_at_serves_ref_bytes_and_tree_sha(adapter, forge):
    _need(adapter, forge, "refs", "FC-096")
    c = C("FC-096")
    repo = forge.repo_id(VCS)
    feat_tree = adapter.request("repo/tree", {"repo": repo, "ref": "feature"})
    entry = _tree_entry(feat_tree, DIVERGES, "FC-096")
    got = adapter.request("repo/blob_at", {"repo": repo, "path": DIVERGES,
                                           "ref": "feature"})
    data = base64.b64decode(got.get("bytes_b64", ""))
    fc_assert(data == forge.vcs.show_bytes("feature", DIVERGES), *c,
              "blob_at at ref must serve exactly that ref's bytes — the "
              "'open the file at this commit' call")
    fc_assert(got.get("sha") == entry["sha"], *c,
              "blob_at's sha must match the tree-at-ref entry for the "
              "same path (the id names the same bytes the tree promised): "
              f"{got.get('sha')!r} vs {entry['sha']!r}")
    default = adapter.request("repo/blob_at", {"repo": repo, "path": DIVERGES})
    fc_assert(base64.b64decode(default.get("bytes_b64", ""))
              == forge.vcs.show_bytes("main", DIVERGES), *c,
              "absent ref resolves to the default branch — the fixture's "
              "worktree, which equals main")


def test_FC097_blob_at_unknown_path_is_not_found(adapter, forge):
    _need(adapter, forge, "refs", "FC-097")
    c = C("FC-097")
    repo = forge.repo_id(VCS)
    probes = (
        ("unknown path", {"repo": repo, "path": UNKNOWN_PATH}),
        ("unknown ref", {"repo": repo, "path": "README.md",
                         "ref": UNKNOWN_REF}),
    )
    for where, params in probes:
        try:
            result = adapter.request("repo/blob_at", params)
            fc_assert(False, *c,
                      f"{where} must produce a JSON-RPC error, not a "
                      f"result: {result!r}")
        except WireError as e:
            check_error_shape(e.error, "FC-097", c[2], f"repo/blob_at {where}")
            fc_assert(e.kind in (None, "not_found"), *c,
                      f"not_found is the preferred kind for {where} (any "
                      f"error is legal; kind must be not_found or absent): "
                      f"{e.error!r}")


# -- blame ---------------------------------------------------------------------

def test_FC098_blame_ranges_cover_coalesce_attribute(adapter, forge):
    _need(adapter, forge, "blame", "FC-098")
    c = C("FC-098")
    result = adapter.request("repo/blame", {"repo": forge.repo_id(VCS),
                                            "path": BLAME})
    ranges = result.get("ranges", [])
    lines = forge.vcs.show_bytes("main", BLAME).decode().splitlines()
    fc_assert(isinstance(ranges, list) and ranges, *c,
              f"ranges must be a non-empty list: {result!r}")
    fc_assert(ranges[0].get("start_line") == 1, *c,
              "ranges are 1-based and must start at line 1")
    for n, r in enumerate(ranges):
        fc_assert(isinstance(r.get("start_line"), int) and
                  isinstance(r.get("end_line"), int) and
                  1 <= r["start_line"] <= r["end_line"], *c,
                  f"ranges[{n}] must be 1-based inclusive: {r!r}")
        fc_assert(isinstance(r.get("sha"), str) and r["sha"], *c,
                  f"ranges[{n}].sha must be a non-empty string: {r!r}")
        if n:
            fc_assert(r["start_line"] == ranges[n - 1]["end_line"] + 1, *c,
                      "ranges must tile every line with no gaps or "
                      f"overlaps: {ranges!r}")
            fc_assert(r["sha"] != ranges[n - 1]["sha"], *c,
                      "adjacent ranges sharing a sha must be coalesced "
                      "into one — unmerged neighbors are a protocol "
                      "violation, not a style choice")
    fc_assert(ranges[-1]["end_line"] == len(lines), *c,
              f"ranges must cover every line of the file ({len(lines)}): "
              f"ended at {ranges[-1]['end_line']}")
    # The two-commit file: lines 1-2 from the seed commit, line 3 from
    # the follow-up — git's own blame is the expectation.
    blame_log = forge.vcs.log_shas("main", BLAME)  # newest first
    seed, followup = blame_log[-1], blame_log[0]
    fc_assert([(r["start_line"], r["end_line"], r["sha"]) for r in ranges]
              == [(1, 2, seed), (3, 3, followup)], *c,
              "blame must attribute BLAME.md to the commits that actually "
              "touched it — lines 1-2 to the seed, line 3 to the "
              "follow-up: "
              f"{[(r['start_line'], r['end_line'], r['sha'][:8]) for r in ranges]}")
    expected_dates = {seed: forge.vcs.author_date_iso(seed),
                      followup: forge.vcs.author_date_iso(followup)}
    for r in ranges:
        fc_assert(isinstance(r.get("author"), str) and r["author"].strip(), *c,
                  f"author feeds the UI verbatim and must be a string: {r!r}")
        when = _iso(r.get("date", ""), "FC-098", f"range {r['sha'][:8]}")
        fc_assert(when == _iso(expected_dates[r["sha"]], "FC-098", "git"), *c,
                  "date feeds the UI verbatim — the range's instant must "
                  f"be the commit's author date: {r.get('date')!r} vs "
                  f"{expected_dates[r['sha']]!r}")


# -- capability honesty ----------------------------------------------------------

def test_FC099_revision_capabilities_are_honest_booleans(adapter):
    """refs/log/blame default false and must be declared as booleans —
    the UI degrades on false and the suite never asks a declined
    capability (the skip guards above ARE the never-asked rule; this
    case pins the handshake side of the honesty contract)."""
    c = C("FC-099")
    caps = _caps(adapter)
    for cap in ("refs", "log", "blame"):
        val = caps.get(cap)
        fc_assert(val is None or (isinstance(val, bool)), *c,
                  f"capabilities.{cap} is optional (default false — "
                  "default-branch-only) but when present MUST be a "
                  "boolean: the trio gates real UI surfaces "
                  f"(refs popup, history lens, blame lens); got {val!r}")
