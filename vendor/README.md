# vendored reference adapter

`fs_provider.py` is a verbatim copy of the rootle reference stdio
provider:

- source: `examples/providers/fs_provider.py` in
  [rootledev/rootle](https://github.com/rootledev/rootle)
- vendored at rootle commit `6fc053163fdd67b8623cc20e3a229879bb1050f3`
  (last touched by `64d5d49`, 2026-08-27 — protocol v1.3 completions)

Vendoring keeps this repo self-contained: the conformance suite runs
green against the reference adapter in this repo's own CI, no rootle
checkout required (plans/0015 verification: "the suite runs green
against fs_provider.py on day one"). Re-vendor on protocol revisions
and update the commit above.
