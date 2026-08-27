"""The conformance case registry — single source of truth.

Every case is a stable, citable ID (plans/0015: "like Atlassian's
CHANGE numbers, the case never renames"). The table below drives the
README index and the registry completeness gate (tests/test_registry.py);
case modules import their entries so test bodies and docs cannot drift.

Layout: FC-id -> (group module, title, spec section in
doc/provider-protocol.md v1.5).
"""

# Handshake (v1)
HANDSHAKE = "§Handshake"

# Revisions (v1.5, plans/0016 M1)
REVISIONS = "§Methods (Revisions, v1.5)"

CASES = {
    # -- Handshake (v1) -----------------------------------------------------
    "FC-001": ("test_handshake", "protocol=1 echoes", HANDSHAKE),
    "FC-002": ("test_handshake", "name present or absent", HANDSHAKE),
    "FC-003": ("test_handshake", "capabilities shape", HANDSHAKE),
    "FC-004": ("test_handshake", "icon is a builtin name or a single glyph or absent",
               HANDSHAKE + " (icon, v1.3)"),
    "FC-005": ("test_handshake", "cache budget params tolerated when absent",
               HANDSHAKE + " (cache budget, v1.2)"),
    # -- Content ids --------------------------------------------------------
    "FC-010": ("test_content_ids", "same bytes -> same sha across two calls",
               "§Content ids"),
    "FC-011": ("test_content_ids", "changed bytes -> different sha",
               "§Content ids"),
    "FC-012": ("test_content_ids", "different content -> different sha (no path-keyed collisions)",
               "§Content ids"),
    "FC-013": ("test_content_ids", "sha stability across respawns",
               "§Content ids + §Transport (restart obligations)"),
    # -- Trees & blobs ------------------------------------------------------
    "FC-020": ("test_trees_blobs", "recursive walk covers every fixture path",
               "§Methods repo/tree"),
    "FC-021": ("test_trees_blobs", "dir vs blob typing",
               "§Methods repo/tree"),
    "FC-022": ("test_trees_blobs", "truncated flag past a cap",
               "§Methods repo/tree"),
    "FC-023": ("test_trees_blobs", "blob >1 MiB refused (any error, provider kind preferred)",
               "§Methods repo/blob"),
    "FC-024": ("test_trees_blobs", "binary bytes served raw, base64 valid",
               "§Methods repo/blob"),
    "FC-025": ("test_trees_blobs", "tree at missing repo -> not_found",
               "§Methods repo/tree + §Errors"),
    # -- Search (v1.3) ------------------------------------------------------
    "FC-030": ("test_search", "path-only hit: empty matches legal, must render",
               "§Methods search/code"),
    "FC-031": ("test_search", "line is 1-based and equals the fixture's real line",
               "§Methods search/code (line, v1.3)"),
    "FC-032": ("test_search", "located:false tolerated",
               "§Methods search/code + §Progressive results (located, v1.3)"),
    "FC-033": ("test_search", "index.as_of shape when present",
               "§Methods search/code (index, v1.3)"),
    "FC-034": ("test_search", "file_search inherits code_search when absent",
               HANDSHAKE + " (capabilities, v1.3)"),
    # -- Streaming (v1.3) ---------------------------------------------------
    "FC-040": ("test_streaming", "every $/partial carries the request's id",
               "§Progressive results (v1.3)"),
    "FC-041": ("test_streaming", "all partials precede the reply, no partial after it",
               "§Progressive results (v1.3)"),
    "FC-042": ("test_streaming", "reply is metadata-only when streamed (items empty, truncated authoritative)",
               "§Progressive results (v1.3)"),
    "FC-043": ("test_streaming", "inactivity deadline: a batch every 1.2s must not trip a 2s timeout",
               "§Transport (progressive results — per-inactivity deadline, v1.3)"),
    "FC-044": ("test_streaming", "a batch larger than the client's render budget is accepted",
               "§Progressive results (v1.3)"),
    "FC-045": ("test_streaming", "stream stops cleanly on $/cancelRequest (advisory; must not error)",
               "§Cancellation + §Progressive results (v1.3)"),
    # -- Lifecycle ----------------------------------------------------------
    "FC-050": ("test_lifecycle", "kill mid-session: respawn is cheap and idempotent",
               "§Transport (restart, v1.2)"),
    "FC-051": ("test_lifecycle", "initialize re-runs every generation with the same cache params",
               "§Transport (restart obligations)"),
    "FC-052": ("test_lifecycle", "no network I/O during initialize (credentials are lazy)",
               "§Transport (restart obligations) + §Configuration (credential conventions)"),
    "FC-053": ("test_lifecycle", "unknown fields in requests are ignored",
               "§Transport (reader tolerance, normative both directions)"),
    "FC-054": ("test_lifecycle", "unsolicited notifications ignored",
               "§Transport (reader tolerance, normative both directions)"),
    # -- Errors (taxonomy) --------------------------------------------------
    "FC-060": ("test_errors", "auth for credential failures", "§Errors (kinds, v1.1)"),
    "FC-061": ("test_errors", "rate_limited with retry_after_s when applicable",
               "§Errors (kinds, v1.1)"),
    "FC-062": ("test_errors", "not_found for missing repo/blob", "§Errors (kinds, v1.1)"),
    "FC-063": ("test_errors", "unknown kinds tolerated (suite asserts shape, not kind set)",
               "§Errors (kinds, v1.1 — open enum)"),
    # -- Bounded compute (advisory) ------------------------------------------
    "FC-070": ("test_bounded", "honoring limit stops at ~N and sets truncated: true",
               "§Methods search/code (bounded compute, advisory)"),
    # -- Icons (v1.3) --------------------------------------------------------
    "FC-080": ("test_icons", "icon is absent, a builtin name, or a single glyph",
               HANDSHAKE + " (icon, v1.3)"),
    # -- Revisions (v1.5) ----------------------------------------------------
    "FC-090": ("test_revisions", "refs shape: branches/tags arrays, sha present, at most one default",
               HANDSHAKE + " (capabilities, v1.5) + " + REVISIONS),
    "FC-091": ("test_revisions", "tree at ref serves that ref (diverging file differs; branch echoes)",
               REVISIONS),
    "FC-092": ("test_revisions", "tree at unknown ref -> error (not_found preferred)",
               REVISIONS + " + §Errors"),
    "FC-093": ("test_revisions", "sha discipline across refs: different content -> different ids, same content -> same id",
               REVISIONS + " + §Content ids"),
    "FC-094": ("test_revisions", "log shape: newest-first, ISO-8601 dates, path filter narrows",
               REVISIONS),
    "FC-095": ("test_revisions", "log limit stops at ~N and sets truncated: true",
               REVISIONS + " (bounded compute)"),
    "FC-096": ("test_revisions", "blob_at serves the ref's bytes; sha matches the tree-at-ref entry",
               REVISIONS),
    "FC-097": ("test_revisions", "blob_at unknown path/ref -> not_found",
               REVISIONS + " + §Errors"),
    "FC-098": ("test_revisions", "blame ranges: 1-based, cover every line, same-sha coalesced, right shas",
               REVISIONS),
    "FC-099": ("test_revisions", "capability honesty: refs/log/blame are booleans; false is never asked",
               HANDSHAKE + " (capabilities, v1.5)"),
}


def C(cid):
    """``(cid, title, spec)`` — splat directly into fc_assert."""
    return (cid,) + CASES[cid][1:]

#: Builtin icon names rootle maps to Nerd Font glyphs (§Handshake, v1.3).
BUILTIN_ICONS = ("github", "gitlab", "bitbucket", "folder")

#: A conforming icon value (rootle's shape rule): absent, a builtin
#: name, or a single literal glyph the terminal can render.
def icon_conforms(icon):
    if icon is None:
        return True
    return isinstance(icon, str) and (icon in BUILTIN_ICONS or len(icon) == 1)
