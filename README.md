# forge-conformance

The canonical conformance suite for [rootle](https://github.com/rootledev/rootle)
stdio providers (rootledev/rootle plans/0015). One repo, the protocol's
gotchas as a numbered test matrix — every adapter runs against it and
must pass to integrate. Case IDs are stable and citable across
adapters, docs, and bug reports (like Atlassian's CHANGE numbers, the
case never renames).

The authoritative protocol document is
[`doc/provider-protocol.md`](https://github.com/rootledev/rootle/blob/main/doc/provider-protocol.md)
(v1.5) in rootledev/rootle; every case cites the section it encodes in
its failure output.

## Usage

```console
$ python3 run                            # suite vs the vendored reference adapter
$ python3 run -- my-adapter --flag       # suite vs your adapter
```

or directly through pytest:

```console
$ PROVIDER="my-adapter --flag" python3 -m pytest cases
```

The runner spawns your adapter once per case group, speaks NDJSON-RPC
over stdio itself (no TUI, no rootle binary), and reports per-case
pass/fail with the spec section on failure. Python 3.10+ stdlib +
[pytest](https://pytest.org) are the only dependencies.

### Adapter contract for running the suite

The suite materializes a private copy of the canonical [`fixture/`](FIXTURES.md)
— two frozen repos (`alpha`, `beta`) plus a real git repo (`vcs`,
built at materialization from frozen inputs with deterministic
commits) — and hands it to your adapter:

- the fixture directory is **appended as the final argv element**, or
  substituted for a `{fixture}` placeholder in your command;
- it is always exported as `FORGE_FIXTURE_DIR`;
- set `FORGE_NO_APPEND=1` if your adapter takes no path argument;
- your adapter serves the repos as `<org>/alpha`, `<org>/beta`, and
  `<org>/vcs`, where `<org>` is `FORGE_ORG` (default `local`) — the
  revision group (FC-090..098) asks its questions against `vcs`, a
  real git repo built offline at materialization (skip-gated on the
  `refs`/`log`/`blame` capabilities and on git being present);
- all credential environment variables are scrubbed from the child's
  environment (`FORGE_TOKEN`, `GITLAB_TOKEN`, `GITHUB_TOKEN`, …) — the
  canonical fixture must be servable with no credentials (they are
  lazy, per the protocol's restart obligations).

### Knobs

| Env | Default | Meaning |
|---|---|---|
| `FORGE_PROVIDER` / `PROVIDER` | vendored `fs_provider.py` | provider command (shlex) |
| `FORGE_ORG` | `local` | org prefix of the fixture repos |
| `FORGE_DEADLINE_S` | `30` | whole-call read deadline (rootle's `[provider] timeout_ms` analog) |
| `FORGE_INACTIVITY_S` | `2` | inactivity window FC-043 enforces |
| `FORGE_NO_APPEND` | unset | suppress appending the fixture dir to argv |

## The case matrix

47 cases. `cases/` holds one module per group; `cases/registry.py` is
the single source of truth (the table below mirrors it; tests gate the
two against each other). Failure output always carries the case ID,
its title, and the spec citation.

| Case | Encodes | Spec |
|---|---|---|
| **Handshake (v1)** | | |
| FC-001 | protocol=1 echoes | §Handshake |
| FC-002 | name present or absent | §Handshake |
| FC-003 | capabilities shape | §Handshake |
| FC-004 | icon is a builtin name or a single glyph or absent | §Handshake (icon, v1.3) |
| FC-005 | cache budget params tolerated when absent | §Handshake (cache budget, v1.2) |
| **Content ids** | | |
| FC-010 | same bytes -> same sha across two calls | §Content ids |
| FC-011 | changed bytes -> different sha | §Content ids |
| FC-012 | different content -> different sha (no path-keyed collisions) | §Content ids |
| FC-013 | sha stability across respawns | §Content ids + §Transport (restart obligations) |
| **Trees & blobs** | | |
| FC-020 | recursive walk covers every fixture path | §Methods repo/tree |
| FC-021 | dir vs blob typing | §Methods repo/tree |
| FC-022 | truncated flag past a cap | §Methods repo/tree |
| FC-023 | blob >1 MiB refused (any error, provider kind preferred) | §Methods repo/blob |
| FC-024 | binary bytes served raw, base64 valid | §Methods repo/blob |
| FC-025 | tree at missing repo -> not_found | §Methods repo/tree + §Errors |
| **Search (v1.3)** | | |
| FC-030 | path-only hit: empty matches legal, must render | §Methods search/code |
| FC-031 | line is 1-based and equals the fixture's real line | §Methods search/code (line, v1.3) |
| FC-032 | located:false tolerated | §Methods search/code + §Progressive results (located, v1.3) |
| FC-033 | index.as_of shape when present | §Methods search/code (index, v1.3) |
| FC-034 | file_search inherits code_search when absent | §Handshake (capabilities, v1.3) |
| **Streaming (v1.3)** | | |
| FC-040 | every $/partial carries the request's id | §Progressive results (v1.3) |
| FC-041 | all partials precede the reply, no partial after it | §Progressive results (v1.3) |
| FC-042 | reply is metadata-only when streamed (items empty, truncated authoritative) | §Progressive results (v1.3) |
| FC-043 | inactivity deadline: a batch every 1.2s must not trip a 2s timeout | §Transport (progressive results — per-inactivity deadline, v1.3) |
| FC-044 | a batch larger than the client's render budget is accepted | §Progressive results (v1.3) |
| FC-045 | stream stops cleanly on $/cancelRequest (advisory; must not error) | §Cancellation + §Progressive results (v1.3) |
| **Lifecycle** | | |
| FC-050 | kill mid-session: respawn is cheap and idempotent | §Transport (restart, v1.2) |
| FC-051 | initialize re-runs every generation with the same cache params | §Transport (restart obligations) |
| FC-052 | no network I/O during initialize (credentials are lazy) | §Transport (restart obligations) + §Configuration (credential conventions) |
| FC-053 | unknown fields in requests are ignored | §Transport (reader tolerance, normative both directions) |
| FC-054 | unsolicited notifications ignored | §Transport (reader tolerance, normative both directions) |
| **Errors (taxonomy)** | | |
| FC-060 | auth for credential failures | §Errors (kinds, v1.1) |
| FC-061 | rate_limited with retry_after_s when applicable | §Errors (kinds, v1.1) |
| FC-062 | not_found for missing repo/blob | §Errors (kinds, v1.1) |
| FC-063 | unknown kinds tolerated (suite asserts shape, not kind set) | §Errors (kinds, v1.1 — open enum) |
| **Bounded compute (advisory)** | | |
| FC-070 | honoring limit stops at ~N and sets truncated: true | §Methods search/code (bounded compute, advisory) |
| **Icons (v1.3)** | | |
| FC-080 | icon is absent, a builtin name, or a single glyph | §Handshake (icon, v1.3) |
| **Revisions (v1.5)** | | |
| FC-090 | refs shape: branches/tags arrays, sha present, at most one default | §Handshake (capabilities, v1.5) + §Methods (Revisions, v1.5) |
| FC-091 | tree at ref serves that ref (diverging file differs; branch echoes) | §Methods (Revisions, v1.5) |
| FC-092 | tree at unknown ref -> error (not_found preferred) | §Methods (Revisions, v1.5) + §Errors |
| FC-093 | sha discipline across refs: content differs -> ids differ (change rule, both directions); same-content sharing advisory | §Methods (Revisions, v1.5) + §Content ids |
| FC-094 | log shape: newest-first, ISO-8601 dates, path filter narrows | §Methods (Revisions, v1.5) |
| FC-095 | log limit stops at ~N and sets truncated: true | §Methods (Revisions, v1.5) (bounded compute) |
| FC-096 | blob_at serves the ref's bytes; sha matches the tree-at-ref entry | §Methods (Revisions, v1.5) |
| FC-097 | blob_at unknown path/ref -> not_found | §Methods (Revisions, v1.5) + §Errors |
| FC-098 | blame ranges: 1-based, cover every line, same-sha coalesced, right shas | §Methods (Revisions, v1.5) |
| FC-099 | capability honesty: refs/log/blame are booleans; false is never asked | §Handshake (capabilities, v1.5) |

### Case semantics worth knowing

- **Ids are opaque.** The suite never assumes `sha == sha256(bytes)` —
  §Content ids makes ids opaque, only *change-on-content-change* is
  normative. Deterministic fixture bytes let the suite assert on bytes
  and mutations instead, so git-blob-id adapters pass as readily as
  sha256 adapters.
- **FC-011 mutates the fixture copy** (rewrites one file, restores it).
  An adapter serving a snapshot it cannot observe mutating will need an
  adapter-specific hook for this case; everything else is read-only.
- **FC-023 accepts both legal outcomes**: rootle refuses >1 MiB blobs
  at its own boundary; adapters *MAY* refuse earlier (provider kind
  preferred) or serve the blob whole — hanging, truncating, or
  corrupting the bytes is what fails.
- **FC-070 accepts both legal outcomes**: honoring `limit` (stop at ~N,
  `truncated: true`) or ignoring it (full set, no flag). Claiming a cap
  without taking it — or taking it without the flag — fails.
- **FC-043 pins the inactivity window at 2s** (`FORGE_INACTIVITY_S`).
  rootle's default read deadline is 30s; a streamer slower than 2s
  between batches should raise the knob rather than stream sparsely —
  the deadline resets per `$/partial`, it is not an end-to-end bound.
- **Streaming cases were verified against rootle's own enforcement
  first** (`src/provider/stdio/tests.rs` fake-provider modes
  `stream-search`, `stream-slow`, `die-mid-stream`), so case semantics
  match what rootle actually enforces.
- **The revision group reads capabilities first** (FC-099): an adapter
  declaring `refs`/`log`/`blame` false (or omitting them — default
  false) is never asked the corresponding methods; those cases skip
  with a reason citing the case id. When git is unavailable in the
  environment the `vcs` repo is not built and FC-090..098 skip with a
  reason saying exactly that.
- **FC-093's change rule is one-directional** (owner call,
  rootle-bitbucket#6): an id MUST change when content changes —
  asserted normatively, in both directions the fixture can diverge
  two refs (main advancing past the fork; feature rewriting at it).
  The converse — same bytes at two refs sharing one id — is a
  cache-sharing optimization, **advisory**: commit-keyed adapters
  (e.g. Bitbucket Cloud, no git blob ids on the wire) can't honor it
  without fetching every blob per tree walk, so when the suite
  detects differing ids for byte-identical content it reports the
  adapter as commit-keyed informationally (a warning, never a
  failure). Content-keyed adapters pass the strict form.
- **FC-095 requires the honor path** (unlike FC-070's dual outcome):
  the v1.5 spec couples `repo/log`'s `limit` to bounded compute — stop
  at ~N and set `truncated: true` when more provably exists (the
  fixture's 3-commit file makes "more" provable at limit 2).
- **FC-094/FC-098 compute expectations from git itself** (commit ids,
  author dates, blob bytes at refs) — the suite never hard-codes shas,
  so the cases hold for any deterministic build of `fixture/vcs`.

## The gate proves the gate

`tests/nonconforming.py` is a deliberately-nonconforming adapter (it
wraps the vendored reference and violates exactly FC-013 — per-process
salted ids — and FC-043 — a 4s silent gap mid-stream).
`tests/test_gate.py` runs the whole suite against it and asserts it
fails **exactly** FC-013 and FC-043 and nothing else: a gate that
missed those would be under-fitted, one that failed more would be
over-fitted. `tests/test_registry.py` pins the case set against the
plan-0015 enumeration plus the v1.5 revision group (plans/0016 M1) so
numbering cannot silently drift. `tests/incapable.py` is the inverse
gate: it declares the revision trio false and hard-fails every
revision ask — `tests/test_capability_gating.py` proves the suite
skips the group and stays green against it (the "never asked" half of
FC-099).

## The reference adapter

[`vendor/fs_provider.py`](vendor/fs_provider.py) is the vendored
reference adapter — the plan-0015 verbatim copy of rootle's
`examples/providers/fs_provider.py`, **extended in-tree with the v1.5
revision methods** (refs / tree-at-ref / blob_at / log / blame via
the git CLI, capabilities declared honestly per git availability; see
[vendor/README.md](vendor/README.md) for provenance and the delta).
The suite runs green against it on every push — a red suite against
the reference means the suite is wrong, not the adapter.

## Layout

```
run                     entry: python3 run -- <provider-command...>
forge.py                wire client (mirrors rootle's StdioProvider) + helpers
                        + fixture/vcs builder (deterministic git repo)
cases/                  one module per case group; registry.py = case table
fixture/                the canonical mini-backend dataset (+ MANIFEST.sha256;
                        vcs/ holds frozen inputs, materialized into a git repo)
FIXTURES.md             what the fixture encodes and why
vendor/fs_provider.py   vendored reference adapter (+ v1.5 revision extension)
tests/                  the nonconforming + capability gates, registry pins
