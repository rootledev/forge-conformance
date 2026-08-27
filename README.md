# forge-conformance

The canonical conformance suite for [rootle](https://github.com/rootledev/rootle)
stdio providers (rootledev/rootle plans/0015). One repo, the protocol's
gotchas as a numbered test matrix — every adapter runs against it and
must pass to integrate. Case IDs are stable and citable across
adapters, docs, and bug reports (like Atlassian's CHANGE numbers, the
case never renames).

The authoritative protocol document is
[`doc/provider-protocol.md`](https://github.com/rootledev/rootle/blob/main/doc/provider-protocol.md)
(v1.3) in rootledev/rootle; every case cites the section it encodes in
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
(two repos, `alpha` and `beta`) and hands it to your adapter:

- the fixture directory is **appended as the final argv element**, or
  substituted for a `{fixture}` placeholder in your command;
- it is always exported as `FORGE_FIXTURE_DIR`;
- set `FORGE_NO_APPEND=1` if your adapter takes no path argument;
- your adapter serves the two repos as `<org>/alpha` and `<org>/beta`,
  where `<org>` is `FORGE_ORG` (default `local`);
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

37 cases. `cases/` holds one module per group; `cases/registry.py` is
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

## The gate proves the gate

`tests/nonconforming.py` is a deliberately-nonconforming adapter (it
wraps the vendored reference and violates exactly FC-013 — per-process
salted ids — and FC-043 — a 4s silent gap mid-stream).
`tests/test_gate.py` runs the whole suite against it and asserts it
fails **exactly** FC-013 and FC-043 and nothing else: a gate that
missed those would be under-fitted, one that failed more would be
over-fitted. `tests/test_registry.py` pins the case set against the
plan-0015 enumeration so numbering cannot silently drift.

## The reference adapter

[`vendor/fs_provider.py`](vendor/fs_provider.py) is a verbatim copy of
rootle's reference stdio provider (see
[vendor/README.md](vendor/README.md) for provenance). The suite runs
green against it on every push — a red suite against the reference
means the suite is wrong, not the adapter.

## Layout

```
run                     entry: python3 run -- <provider-command...>
forge.py                wire client (mirrors rootle's StdioProvider) + helpers
cases/                  one module per case group; registry.py = case table
fixture/                the canonical mini-backend dataset (+ MANIFEST.sha256)
FIXTURES.md             what the fixture encodes and why
vendor/fs_provider.py   vendored reference adapter
tests/                  the nonconforming gate + registry pins
```
