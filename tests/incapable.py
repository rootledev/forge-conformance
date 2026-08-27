#!/usr/bin/env python3
"""Capability-honesty stub adapter (FC-099's gate, plans/0016 M1).

Wraps the vendored reference fs_provider but declares the v1.5
revision trio **false** at the handshake — the honest answer for a
backend that cannot serve refs/log/blame — and fails every revision
ask with a hard error:

  - repo/refs, repo/log, repo/blame, repo/blob_at: always an error;
  - repo/tree carrying a ref param: always an error.

If the suite ever asks one of these of an adapter that said false,
this stub makes it loud: the case fails with `asked-despite-false`
and tests/test_capability_gating.py turns red. If the suite is honest
(skip-guards first, §Handshake capabilities v1.5), the stub is never
asked and the whole suite runs green with the revision group skipped.

Everything else delegates verbatim to the reference adapter — so a
green run here also proves the skip machinery costs nothing on the
v1 paths.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "vendor"))
import fs_provider  # noqa: E402

#: Methods that must never arrive when the trio is declared false.
REVISION_METHODS = ("repo/refs", "repo/log", "repo/blame", "repo/blob_at")


def asked_despite_false(what):
    return {"code": 1,
            "message": f"incapable adapter was asked {what} despite "
                       "declaring the capability false (FC-099)",
            "data": {"kind": "provider"}}


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    root = os.path.abspath(sys.argv[1])
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(req.get("id"), int):
            continue  # notifications are never replied to (conforming)
        try:
            params = req.get("params") or {}
            method = req.get("method", "")
            if method == "initialize":
                result = fs_provider.handle(root, method, params)
                caps = dict(result.get("capabilities") or {})
                caps.update({"refs": False, "log": False, "blame": False})
                result["capabilities"] = caps
            elif method in REVISION_METHODS or (
                    method == "repo/tree" and params.get("ref") is not None):
                reply = {"jsonrpc": "2.0", "id": req["id"],
                         "error": asked_despite_false(method)}
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()
                continue
            elif method == "search/code" and params.get("partial"):
                # v1.3 streaming, delegated verbatim to the reference
                # (this stub violates nothing — its only point is the
                # capability honesty of the v1.5 trio).
                for batch in fs_provider.search_code_batches(
                        root, params.get("q", "")):
                    note = {"jsonrpc": "2.0", "method": "$/partial",
                            "params": {"id": req["id"], "items": batch}}
                    sys.stdout.write(json.dumps(note) + "\n")
                    sys.stdout.flush()
                result = {"items": [], "truncated": False}
            else:
                result = fs_provider.handle(root, method, params)
            reply = {"jsonrpc": "2.0", "id": req.get("id"), "result": result}
        except Exception as e:  # noqa: BLE001 — surfaced like the reference
            reply = {"jsonrpc": "2.0", "id": req.get("id"),
                     "error": {"code": 1, "message": str(e)}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
