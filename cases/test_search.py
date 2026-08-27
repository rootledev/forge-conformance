"""FC-030..FC-034 — search (v1.3).

``search/code`` items carry matched substrings rootle locates for
previews; v1.3 added per-item 1-based ``line`` anchors, path-only hits
(empty matches are legal and must render), per-item ``located``,
top-level ``index.as_of``, and the ``file_search`` capability split.
"""

from cases.registry import C
from forge import check_code_item, fc_assert


def test_FC030_path_only_hit_empty_matches_legal(adapter, forge):
    """An item with empty matches is a legal path-only hit — "this file
    matched". A query with only an extension qualifier elicits them."""
    c = C("FC-030")
    result = adapter.request("search/code", {"q": "extension:txt"})
    items = result.get("items", [])
    fc_assert(isinstance(items, list) and items, *c,
              "extension:txt over the fixture must yield items (alpha has "
              f"three .txt files, beta one): {result!r}")
    canonical = {forge.repo_id("alpha"), forge.repo_id("beta")}
    for item in items:
        check_code_item(item, "FC-030", c[2], where=item.get("path", "?"))
        fc_assert(item["repo"] in canonical, *c,
                  "the fixture is closed-world — search must only report the "
                  "canonical repos (an adapter whose disk cache or scratch "
                  "leaks into the served tree shows up here): "
                  f"{item['repo']!r} not in {sorted(canonical)}")
    path_only = [i for i in items if i.get("matches", []) == []]
    fc_assert(path_only, *c,
              "the suite must observe at least one path-only hit (empty "
              "matches): every item carried non-empty matches — "
              f"{[i.get('path') for i in items]}")


def test_FC031_line_is_1_based_and_real(adapter, forge):
    """Optional per-item line (v1.3) is a provider-known anchor used
    as-is — when present it must equal the fixture's real 1-based line
    of the first match (the first substring occurrence is often the
    wrong one, which is exactly why the anchor exists)."""
    c = C("FC-031")
    marker = "needle_main"  # unique to alpha/src/main.rs in the fixture
    out = adapter.stream("search/code", {"q": marker})
    items = [i for p in out.partials for i in p.get("items", [])]
    if not items:
        items = adapter.request("search/code", {"q": marker}).get("items", [])
    fc_assert(items, *c, f"query {marker!r} must hit alpha/src/main.rs")
    for item in items:
        check_code_item(item, "FC-031", c[2], where=item.get("path", "?"))
        if "line" not in item:
            continue  # line is optional; absence is conforming
        needle = (item.get("matches") or [marker])[0]
        expected = forge.first_line_containing("alpha", item["path"], needle)
        fc_assert(expected is not None, *c,
                  f"fixture sanity: {needle!r} not found in alpha/{item['path']}")
        fc_assert(item["line"] == expected, *c,
                  f"line must be the real 1-based line of the first match in "
                  f"alpha/{item['path']}: got {item['line']}, want {expected}")


def test_FC032_located_false_tolerated(adapter):
    """Per-item located (v1.3): absent is the norm; when present it must
    be a boolean the client can act on (located:false hits self-heal
    placements via client-side locating)."""
    c = C("FC-032")
    result = adapter.request("search/code", {"q": "needle"})
    for item in result.get("items", []):
        check_code_item(item, "FC-032", c[2], where=item.get("path", "?"))
    out = adapter.stream("search/code", {"q": "needle"})
    for p in out.partials:
        for item in p.get("items", []):
            check_code_item(item, "FC-032", c[2], where=item.get("path", "?"))


def test_FC033_index_as_of_shape_when_present(adapter):
    """Optional top-level index (v1.3): when an indexed backend reports
    index freshness, index.as_of is what rootle shows next to the result
    count. Absent is conforming (non-indexed backends)."""
    c = C("FC-033")
    result = adapter.request("search/code", {"q": "needle"})
    if "index" in result:
        index = result["index"]
        fc_assert(isinstance(index, dict), *c,
                  f"index must be an object: {index!r}")
        fc_assert("as_of" in index and isinstance(index["as_of"], (str, int, float))
                  and not isinstance(index["as_of"], bool), *c,
                  f"index.as_of (when the index was built) must be a string "
                  f"or number: {index.get('as_of')!r}")


def test_FC034_file_search_inherits_code_search(adapter):
    """Optional file_search (v1.3) splits filename search from content
    search; absent inherits code_search. The suite derives the effective
    capability exactly as rootle does and pins the shape it needs."""
    c = C("FC-034")
    caps = adapter.init_reply.get("capabilities") or {}
    for key in ("orgs", "code_search", "file_search"):
        if key in caps:
            fc_assert(isinstance(caps[key], bool), *c,
                      f"capabilities.{key} must be a boolean: {caps[key]!r}")
    effective = caps.get("file_search", caps.get("code_search", True))
    fc_assert(isinstance(effective, bool), *c,
              "file_search absent must inherit code_search (itself defaulting "
              f"to true when capabilities are absent); effective value is "
              f"{effective!r}")
