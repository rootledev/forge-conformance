"""FC-010..FC-013 — content ids, the contract that breaks caches.

Every sha is an opaque content id that MUST change when content changes
(§Content ids). rootle's cache is content-keyed and immutable — a
provider that reuses a sha for different bytes serves stale content.
The suite never assumes a hash scheme (ids are opaque); it observes
them across calls, mutations, and respawns.
"""

from cases.registry import C
from forge import fc_assert

REPO = "alpha"
REL = "src/lib.rs"


def _blob_sha(adapter, repo, rel):
    result = adapter.request("repo/tree", {"repo": repo})
    for e in result.get("entries", []):
        if e.get("path") == rel and e.get("type") == "blob":
            return e.get("sha")
    raise AssertionError(f"no blob entry for {rel!r} in repo/tree of {repo!r}: {result!r}")


def test_FC010_same_bytes_same_sha_across_two_calls(adapter, forge):
    c = C("FC-010")
    repo = forge.repo_id(REPO)
    sha1 = _blob_sha(adapter, repo, REL)
    sha2 = _blob_sha(adapter, repo, REL)
    fc_assert(isinstance(sha1, str) and sha1 != "", *c,
              f"sha must be a non-empty string: {sha1!r}")
    fc_assert(sha1 == sha2, *c,
              "two repo/tree calls over unchanged bytes must agree on the "
              "content id (content-keyed caching depends on it): "
              f"{sha1!r} != {sha2!r}")


def test_FC011_changed_bytes_different_sha(adapter, forge):
    c = C("FC-011")
    repo = forge.repo_id(REPO)
    original = forge.read(REPO, REL)
    try:
        before = _blob_sha(adapter, repo, REL)
        forge.replace(REPO, REL, original + b"\n// forge-conformance mutation\n")
        after = _blob_sha(adapter, repo, REL)
        fc_assert(before != after, *c,
                  "the content id MUST change when content changes — rootle "
                  "caches by sha and never invalidates; an id keyed on path "
                  f"alone would serve stale bytes: {before!r} survived a mutation")
        forge.replace(REPO, REL, original)
        restored = _blob_sha(adapter, repo, REL)
        fc_assert(restored == before, *c,
                  "restoring the original bytes must restore the original "
                  f"content id: {before!r} != {restored!r} (ids are deterministic)")
    finally:
        forge.replace(REPO, REL, original)


def test_FC012_different_content_different_sha(adapter, forge):
    c = C("FC-012")
    repo = forge.repo_id(REPO)
    result = adapter.request("repo/tree", {"repo": repo})
    blobs = {e["path"]: e.get("sha") for e in result.get("entries", [])
             if e.get("type") == "blob"}
    # The fixture's content map: every file is unique except the
    # deliberately duplicated pair (see FIXTURES.md).
    dup = {"dup_a.txt", "src/dup_b.txt"}
    shas = [sha for path, sha in blobs.items() if path not in dup]
    fc_assert(len(set(shas)) == len(shas), *c,
              "files with different content must carry different content ids "
              "(no path-keyed collisions); repeated ids: "
              f"{sorted({s for s in shas if shas.count(s) > 1})}")


def test_FC013_sha_stable_across_respawns(adapter, forge):
    """rootle kills the child on exit and restarts it after any death,
    re-initializing each generation (§Transport restart obligations).
    A sha that drifts across respawns splits the cache by generation —
    the exact bug rootle's content-keyed cache cannot tolerate."""
    c = C("FC-013")
    repo = forge.repo_id(REPO)
    before = _blob_sha(adapter, repo, REL)
    adapter.restart()
    after = _blob_sha(adapter, repo, REL)
    fc_assert(before == after, *c,
              "content ids must be stable across process generations — "
              "rootle respawns the child unboundedly within one session and "
              "its cache is content-keyed, not process-keyed: "
              f"{before!r} (gen 1) != {after!r} (gen 2)")
