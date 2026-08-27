# vendored reference adapter

`fs_provider.py` is a vendored copy of the rootle reference stdio
provider, extended in this repo with the v1.5 revision methods:

- source: `examples/providers/fs_provider.py` in
  [rootledev/rootle](https://github.com/rootledev/rootle)
- vendored at rootle commit `6fc053163fdd67b8623cc20e3a229879bb1050f3`
  (last touched by `64d5b49`, 2026-08-27 — protocol v1.3 completions)
- **extended here for protocol v1.5** (plans/0016 M1, FC-090..099):
  `repo/refs`, `ref` on `repo/tree`, `repo/log`, `repo/blob_at`,
  `repo/blame` — served through the git CLI when a working git is on
  PATH, with the `refs`/`log`/`blame` capabilities declared true only
  then (honestly false otherwise, §Handshake). Content ids stay
  sha256-of-bytes at every ref (§Content ids); `not_found`-kinded
  errors ride the v1.1 taxonomy for the new miss paths. The plain
  (non-git) serving path is byte-identical to the vendored original —
  the 37 pre-v1.5 cases are untouched by the extension.

Vendoring keeps this repo self-contained: the conformance suite runs
green against the reference adapter in this repo's own CI, no rootle
checkout required (plans/0015 verification: "the suite runs green
against fs_provider.py on day one"). Re-vendor on protocol revisions
and update the commit above — when upstream rootle lands its own v1.5
fs_provider, re-vendor and drop the in-tree extension.
