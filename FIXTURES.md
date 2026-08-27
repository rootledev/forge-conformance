# The canonical fixture

The fixture is the mini-backend every adapter under test serves: two
repos under the adapter's org (`FORGE_ORG`, default `local` →
`local/alpha`, `local/beta`). Content is **frozen and
manifest-hashed** (`fixture/MANIFEST.sha256`): the suite verifies its
materialized copy against the manifest before every run, and
deterministic bytes mean expectations are computable without assuming
anything about the adapter's content-id scheme (ids stay opaque per
§Content ids — the suite compares bytes and id *behavior*, never id
values).

## alpha — the rust-ish repo

| Path | Encodes |
|---|---|
| `README.md` | plain prose, no search needles (line-number noise floor) |
| `Cargo.toml` | non-code text file, no needles |
| `src/main.rs` | `needle_main` on a known line — FC-031's 1-based anchor |
| `src/lib.rs` | `needle_lib`; the file FC-011 mutates and restores |
| `src/ünïcode.rs` | unicode filename crossing script boundaries |
| `src/nested/deep.rs` | nesting deeper than one level — recursive walk (FC-020) |
| `src/dup_b.txt`, `dup_a.txt` | identical content at two paths (content-keying contrast pair) |
| `empty.txt` | zero-byte blob (sha of empty content; base64 of `""`) |
| `big.bin` | 1,572,864 bytes (1.5 MiB) of a NUL-rich pattern — FC-023's >1 MiB blob |
| `icon.png` | 88 bytes of binary with NULs — FC-024's raw-bytes roundtrip, binary-skip in search |

## beta — the notes-only repo

| Path | Encodes |
|---|---|
| `notes.txt` | `needle` on line 2 — a second repo so streaming yields ≥2 batches (the reference adapter streams per repo) |
| `todo.md` | `needle` — another needle carrier |

## Search term distribution

`needle` appears in exactly six files (main.rs, lib.rs, ünïcode.rs,
deep.rs, notes.txt, todo.md) and nowhere else: FC-044's
budget-exceeding batch, FC-070's limit probe, and the streaming cases
all rely on that count. `extension:txt` / `extension:rs` queries select
known file sets; an extension-only query (no terms) elicits path-only
hits with empty `matches` (FC-030). The binaries are excluded from
search by the reference adapter's NUL sniff, so search sets stay exact.

## Why deterministic content matters

- FC-011 rewrites `src/lib.rs` and asserts the content id moves, then
  restores it and asserts the id returns — only byte-determinism makes
  "restore" exact.
- FC-024 and FC-023 compare served bytes to fixture bytes.
- The manifest (`sha256sum` format) makes accidental fixture edits loud
  at suite startup instead of silently shifting expectations.

To change the fixture deliberately: edit content, regenerate
`MANIFEST.sha256` (`find . -type f ! -name MANIFEST.sha256 -print0 |
sort -z | xargs -0 sha256sum > MANIFEST.sha256`), and update any case
that names the changed paths.
