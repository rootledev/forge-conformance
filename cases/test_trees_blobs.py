"""FC-020..FC-025 — trees & blobs.

``repo/tree`` is one recursive walk over the default branch, unpaginated
on the wire (§Methods); ``repo/blob`` serves standard base64 file
content, and rootle refuses blobs over 1 MiB at its own boundary —
adapters MAY refuse earlier with a provider-kinded error.
"""

import base64

from cases.registry import C
from forge import fc_assert


def test_FC020_recursive_walk_covers_every_fixture_path(adapter, forge):
    c = C("FC-020")
    repo = forge.repo_id("alpha")
    result = adapter.request("repo/tree", {"repo": repo})
    entries = result.get("entries", [])
    fc_assert(isinstance(entries, list) and entries, *c,
              f"entries must be a non-empty list for the fixture repo: {result!r}")
    got = [e.get("path") for e in entries]
    expected = set(forge.walk("alpha"))
    fc_assert(set(got) == expected, *c,
              "repo/tree is one recursive walk over the default branch — it "
              "must cover every fixture path exactly once:\n"
              f"  missing: {sorted(expected - set(got))}\n"
              f"  extra:   {sorted(set(got) - expected)}")
    fc_assert(len(got) == len(set(got)), *c, f"duplicate paths in entries: {got}")


def test_FC021_dir_vs_blob_typing(adapter, forge):
    c = C("FC-021")
    repo = forge.repo_id("alpha")
    entries = adapter.request("repo/tree", {"repo": repo}).get("entries", [])
    by_path = {e.get("path"): e.get("type") for e in entries}
    for path, want in sorted(forge.walk("alpha").items()):
        fc_assert(by_path.get(path) == want, *c,
                  f"type must be \"blob\" for files and \"tree\" for "
                  f"directories (\"tree\" renders as a directory): "
                  f"{path!r} is {by_path.get(path)!r}, want {want!r}")
    for e in entries:
        if e.get("type") == "blob":
            fc_assert(isinstance(e.get("sha"), str) and e["sha"], *c,
                      f"blob entries must carry a sha: {e!r}")
            if "size" in e:
                fc_assert(isinstance(e["size"], int) and e["size"] >= 0, *c,
                          f"size is optional (blobs only) and a non-negative int: {e!r}")


def test_FC022_truncated_flag_past_a_cap(adapter, forge):
    """The fixture sits below any sane adapter budget, so truncated must
    be a boolean (absent defaults to false). Past-a-cap behavior is the
    same flag; the suite pins its shape and default here."""
    c = C("FC-022")
    repo = forge.repo_id("alpha")
    result = adapter.request("repo/tree", {"repo": repo})
    truncated = result.get("truncated", False)
    fc_assert(isinstance(truncated, bool), *c,
              "truncated defaults to false and flags that the adapter capped "
              f"the walk past its own budget; it must be a boolean: {truncated!r}")
    fc_assert(truncated is False, *c,
              "the canonical fixture is tiny — no conforming adapter caps "
              "below it, so truncated must be false here")


def test_FC023_blob_over_1MiB(adapter, forge):
    """rootle refuses blobs over 1 MiB at its own boundary regardless of
    provider (preview-pane policy). An adapter MAY refuse earlier with a
    provider-kinded error, or serve the blob — both conforming; what is
    nonconforming is hanging, truncating, or corrupting the bytes."""
    c = C("FC-023")
    repo = forge.repo_id("alpha")
    big = _fetch(adapter, repo, forge, "big.bin")
    if isinstance(big, dict) and "bytes_b64" in big:
        data = base64.b64decode(big["bytes_b64"])
        fc_assert(len(data) > 1024 * 1024, *c,
                  f"the fixture blob big.bin is 1.5 MiB; served bytes came "
                  f"back {len(data)} bytes — content must arrive whole")
        fc_assert(data == forge.read("alpha", "big.bin"), *c,
                  "served bytes must equal the fixture content exactly")


def test_FC024_binary_bytes_served_raw(adapter, forge):
    c = C("FC-024")
    repo = forge.repo_id("alpha")
    result = _fetch(adapter, repo, forge, "icon.png")
    raw = base64.b64decode(result["bytes_b64"], validate=True)
    want = forge.read("alpha", "icon.png")
    fc_assert(b"\x00" in raw, *c, "binary bytes must be served raw, not transcoded")
    fc_assert(raw == want, *c,
              f"bytes_b64 must decode to the exact fixture bytes "
              f"({len(want)} bytes, NULs intact); got {len(raw)}")


def test_FC025_tree_at_missing_repo_is_not_found(adapter, forge):
    c = C("FC-025")
    from forge import WireError, check_error_shape
    repo = f"{forge.org}/forge-conformance-no-such-repo"
    try:
        result = adapter.request("repo/tree", {"repo": repo})
        fc_assert(False, *c,
                  f"a missing repo must produce a JSON-RPC error, not a "
                  f"result: {result!r}")
    except WireError as e:
        check_error_shape(e.error, "FC-025", c[2], "repo/tree missing repo")
        fc_assert(e.kind in (None, "not_found"), *c,
                  "not_found is the preferred kind for a missing repo (any "
                  f"error is legal; kind must be not_found or absent): {e.error!r}")


def _sha_of(adapter, repo, forge, rel):
    entries = adapter.request("repo/tree", {"repo": repo}).get("entries", [])
    for e in entries:
        if e.get("path") == rel and e.get("type") == "blob":
            return e["sha"]
    raise AssertionError(f"no blob entry for {rel!r}")


def _fetch(adapter, repo, forge, rel):
    """Fetch a blob; if the adapter refuses (its right for >1 MiB),
    return the error object for the case to judge."""
    from forge import WireError
    sha = _sha_of(adapter, repo, forge, rel)
    try:
        return adapter.request("repo/blob", {"repo": repo, "sha": sha})
    except WireError as e:
        if rel == "big.bin":
            from forge import check_error_shape
            check_error_shape(e.error, "FC-023", C("FC-023")[2], "repo/blob big.bin")
            return e.error
        raise
