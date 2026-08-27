#!/usr/bin/env python3
"""Deliberately nonconforming fixture adapter (plans/0015 verification).

Wraps the vendored reference fs_provider and violates exactly two
contract points, so the suite's gate can be proven to catch what it
claims and nothing it doesn't:

  FC-013 — content ids are salted with a per-process random nonce:
           stable within one process (FC-010/011/012 still pass — the
           salt never changes mid-process, and mutations still move
           the id) but different after every respawn, splitting rootle's
           content-keyed cache by generation.

  FC-043 — the streaming path goes silent for 4s between the first and
           second $/partial batch: every other streaming rule is obeyed
           (ids, ordering, metadata-only reply, cancel tolerance), but a
           2s inactivity deadline trips mid-stream.

Everything else behaves exactly like the reference adapter — that is
the point: a gate that failed more than FC-013/FC-043 against this
adapter would be over-fitted.
"""

import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "vendor"))
import fs_provider  # noqa: E402

SALT = os.urandom(16).hex()
SILENCE_S = 4.0  # > FORGE_INACTIVITY_S default (2s), < any whole-call deadline


def salted(sha):
    return fs_provider.sha256((SALT + ":" + sha).encode())


def salted_tree(root, repo):
    return [dict(e, sha=salted(e["sha"])) for e in fs_provider.walk_tree(root, repo)]


def salted_items(items):
    return [dict(i, sha=salted(i["sha"])) if i.get("sha") else i for i in items]


def salted_blob(root, repo, sha):
    for entry in salted_tree(root, repo):
        if entry["type"] == "blob" and entry["sha"] == sha:
            with open(os.path.join(fs_provider.repo_dir(root, repo),
                                   entry["path"]), "rb") as f:
                return f.read()
    raise ValueError(f"no blob {sha} in {repo}")


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
        partial = None
        try:
            params = req.get("params") or {}
            method = req.get("method", "")
            if method == "repo/tree":
                result = {"entries": salted_tree(root, params["repo"]),
                          "truncated": False, "branch": "main"}
            elif method == "repo/blob":
                data = salted_blob(root, params["repo"], params["sha"])
                result = {"bytes_b64": base64.b64encode(data).decode()}
            elif method == "search/code" and params.get("partial"):
                # FC-043 violation: a >2s silent gap between batch 1 and
                # batch 2 of a multi-batch stream. Ids, ordering, and the
                # metadata-only reply all stay conforming.
                partial = req.get("id")
                first = True
                for batch in fs_provider.search_code_batches(root, params.get("q", "")):
                    if not first:
                        time.sleep(SILENCE_S)
                    first = False
                    note = {"jsonrpc": "2.0", "method": "$/partial",
                            "params": {"id": partial,
                                       "items": salted_items(batch)}}
                    sys.stdout.write(json.dumps(note) + "\n")
                    sys.stdout.flush()
                result = {"items": [], "truncated": False}
            elif method == "search/code":
                result = {"items": salted_items(
                    fs_provider.search_code(root, params.get("q", "")))}
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
