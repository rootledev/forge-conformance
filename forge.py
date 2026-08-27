"""forge-conformance harness: NDJSON-RPC wire client + fixture helpers.

The client mirrors rootle's StdioProvider semantics
(rootledev/rootle src/provider/stdio.rs) so the suite enforces what
rootle actually enforces:

- a dedicated reader thread owns the child's stdout; replies are
  id-matched, unsolicited notifications and stale/late replies are
  discarded, never fatal;
- streaming requests (params carry ``"partial": true``) read with a
  per-line **inactivity** deadline: every ``$/partial`` or the reply
  resets it (spec §Transport, v1.3);
- errors map through the v1.1 taxonomy (§Errors): known kinds map to
  themselves, unknown or absent kinds degrade to Other, and
  ``retry_after_s`` is honored only as a non-negative number.

Spec: doc/provider-protocol.md in rootledev/rootle, v1.3.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import namedtuple
from pathlib import Path

#: Citation prefix printed in every case failure.
SPEC = "spec: rootledev/rootle doc/provider-protocol.md"

#: Whole-call read deadline (seconds). Mirrors rootle's [provider]
#: timeout_ms (default 30s) — a per-round-trip bound, not end-to-end.
DEADLINE_S = float(os.environ.get("FORGE_DEADLINE_S", "30"))

#: Inactivity window (seconds) for FC-043: a streamer emitting one
#: batch per window must never trip it (rootle's read deadline resets
#: per $/partial; the suite pins 2s so violations are caught fast).
INACTIVITY_S = float(os.environ.get("FORGE_INACTIVITY_S", "2"))

#: Env vars scrubbed from the adapter environment: the canonical
#: fixture must be servable with no credentials present (FC-052 —
#: credentials are lazy, §Transport restart obligations).
CREDENTIAL_VARS = (
    "FORGE_TOKEN",
    "GITLAB_TOKEN",
    "GL_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "BITBUCKET_TOKEN",
    "BB_TOKEN",
    "GITEA_TOKEN",
    "GITEA_TOKEN",
)

_EOF = object()  # reader-thread sentinel: child closed its output

StreamResult = namedtuple("StreamResult", "reply partials max_gap stale_ids")


def fc_assert(cond, cid, title, spec, detail=""):
    """Assert a case, citing the spec section it encodes on failure."""
    if not cond:
        raise AssertionError(f"[{cid}] {title}\n  {SPEC} {spec}\n  {detail}")


# --------------------------------------------------------------------------
# Error taxonomy (§Errors, v1.1/v1.2) — mirrors rootle's ProviderError map.
# --------------------------------------------------------------------------

KNOWN_KINDS = ("auth", "rate_limited", "not_found", "network", "timeout", "provider")


def map_error(err):
    """Map a wire ``error`` object to ``(kind, retry_after_s)``.

    Known kinds map to themselves; unknown or absent kinds degrade to
    ``None`` (rootle's Other bucket); ``retry_after_s`` counts only as
    a non-negative number. Never raises — unknown shapes degrade.
    """
    kind = None
    retry = None
    data = err.get("data") if isinstance(err, dict) else None
    if isinstance(data, dict):
        k = data.get("kind")
        if isinstance(k, str) and k in KNOWN_KINDS:
            kind = k
        r = data.get("retry_after_s")
        if isinstance(r, (int, float)) and not isinstance(r, bool) and r >= 0:
            retry = r
    return kind, retry


def check_error_shape(err, cid, spec, where):
    """The taxonomy contract every adapter error reply must satisfy.

    FC-060..FC-063 assert shape, not kind set (the enum is open): code
    is a positive int, message a non-empty string, data an optional
    object with optional string kind and optional non-negative
    retry_after_s.
    """
    where = f"{where}: " if where else ""
    fc_assert(
        isinstance(err, dict),
        cid, "error reply shape", spec,
        f"{where}error is not a JSON object: {err!r}",
    )
    code = err.get("code")
    fc_assert(
        isinstance(code, int) and not isinstance(code, bool) and code > 0,
        cid, "error reply shape", spec,
        f"{where}error.code must be a positive int (any value of the "
        f"provider's choosing; -32xxx reserved): {code!r}",
    )
    msg = err.get("message")
    fc_assert(
        isinstance(msg, str) and msg.strip(),
        cid, "error reply shape", spec,
        f"{where}error.message must be a non-empty string (it becomes the "
        f"one-line status/toast the UI shows): {msg!r}",
    )
    data = err.get("data")
    if data is not None:
        fc_assert(
            isinstance(data, dict),
            cid, "error reply shape", spec,
            f"{where}error.data must be an object (kind/retry_after_s live there): {data!r}",
        )
        k = data.get("kind")
        if k is not None:
            fc_assert(
                isinstance(k, str) and k,
                cid, "error reply shape", spec,
                f"{where}error.data.kind must be a non-empty string from the open enum "
                f"{KNOWN_KINDS} (unknown values degrade to the message toast): {k!r}",
            )
        r = data.get("retry_after_s")
        if r is not None:
            fc_assert(
                isinstance(r, (int, float)) and not isinstance(r, bool) and r >= 0,
                cid, "error reply shape", spec,
                f"{where}error.data.retry_after_s must be a non-negative number "
                f"(rate_limited backoff seconds): {r!r}",
            )
    map_error(err)  # must degrade, never raise


# --------------------------------------------------------------------------
# Wire client
# --------------------------------------------------------------------------

class ProviderDead(RuntimeError):
    """The child closed its output (spec §Transport restart)."""


class CallTimeout(RuntimeError):
    """No reply within the whole-call deadline."""


class InactivityExceeded(RuntimeError):
    """Silence longer than the inactivity window mid-stream (FC-043)."""

    def __init__(self, window, silent_s):
        super().__init__(
            f"no $/partial or reply for {silent_s:.2f}s (window {window:.2f}s)"
        )
        self.window = window
        self.silent_s = silent_s


class WireError(RuntimeError):
    """The adapter replied with a JSON-RPC error for our request."""

    def __init__(self, rid, err):
        super().__init__(err.get("message", str(err)))
        self.rid = rid
        self.error = err
        self.kind, self.retry_after_s = map_error(err)


class AdapterProc:
    """One live provider child speaking NDJSON-RPC over stdio."""

    def __init__(self, cmd, env=None, cwd=None, stderr=None):
        self.cmd = list(cmd)
        self.env = env
        self.cwd = cwd
        self.stderr = stderr
        self.init_params = None
        self.init_reply = None
        #: $/partial notifications observed for foreign request ids
        #: (late/stale traffic rootle discards; cases inspect for leaks).
        self.dropped_partials = []
        self._spawn()

    # -- process plumbing ---------------------------------------------------

    def _spawn(self):
        self._q = queue.Queue()
        self._next_id = 1
        self.dead = False
        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr if self.stderr is not None else subprocess.DEVNULL,
            env=self.env,
            cwd=self.cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_forever, daemon=True)
        self._reader.start()

    def _read_forever(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._q.put(json.loads(line))
            except ValueError:
                continue  # non-JSON stdout is nonconformance; cases that
                # care assert on structured replies never matching it.
        self._q.put(_EOF)

    def _send(self, payload):
        try:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            raise ProviderDead(f"provider stdin closed: {e}") from e

    def _alloc_id(self):
        rid = self._next_id
        self._next_id += 1
        return rid

    def kill(self):
        """Hard-kill the child (rootle kills it on exit; §Transport)."""
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=10)

    def close(self):
        self.kill()

    def restart(self):
        """Kill and respawn with the same command/env; re-initialize with
        the same advisory cache params (restart obligations, §Transport).
        Returns the new initialize reply."""
        self.kill()
        self._spawn()
        if self.init_params is not None:
            self.init_reply = self.request("initialize", self.init_params)
        return self.init_reply

    # -- protocol ------------------------------------------------------------

    def initialize(self, cache_bytes=None, cache_dir=None, timeout=None, **extra):
        params = {"protocol": 1}
        if cache_bytes is not None:
            params["cache_bytes"] = cache_bytes
            params["cache_dir"] = cache_dir or ""
        params.update(extra)
        self.init_params = params
        self.init_reply = self.request("initialize", params, timeout=timeout)
        return self.init_reply

    def request(self, method, params=None, timeout=None):
        """Send a request; return its ``result``. Error replies raise
        WireError; notifications and stale replies are discarded."""
        timeout = DEADLINE_S if timeout is None else timeout
        rid = self._alloc_id()
        self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                    "params": params if params is not None else {}})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CallTimeout(f"no reply to {method!r} within {timeout}s")
            try:
                msg = self._q.get(timeout=remaining)
            except queue.Empty:
                raise CallTimeout(f"no reply to {method!r} within {timeout}s") from None
            if msg is _EOF:
                self.dead = True
                raise ProviderDead("provider closed its output")
            if self._is_reply(msg, rid):
                if "error" in msg:
                    raise WireError(rid, msg["error"])
                return msg["result"]
    def notify(self, method, params=None):
        """Send a notification (no id, never replied to)."""
        self._send({"jsonrpc": "2.0", "method": method,
                    "params": params if params is not None else {}})

    def stream(self, method, params, inactivity=None, timeout=None, on_sent=None):
        """Progressive request (``partial: true`` forced): collect
        ``$/partial`` batches until the reply.

        With ``inactivity`` set, every line (partial or reply) must
        arrive within that many seconds of the previous one — the
        deadline resets per batch (§Transport, v1.3). Without it, the
        whole call gets ``timeout`` (default DEADLINE_S) — the
        generous deadline. Only FC-043 pins the window.
        """
        rid = self._alloc_id()
        payload = dict(params or {})
        payload["partial"] = True
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": payload})
        if on_sent is not None:
            on_sent(rid)
        partials = []
        gaps = []
        stale = []
        last = time.monotonic()
        overall = None if inactivity is not None else time.monotonic() + (
            DEADLINE_S if timeout is None else timeout)
        while True:
            if inactivity is not None:
                wait = inactivity
            else:
                wait = overall - time.monotonic()
                if wait <= 0:
                    raise CallTimeout(f"stream {method!r} exceeded whole-call deadline")
            try:
                msg = self._q.get(timeout=wait)
            except queue.Empty:
                silent = time.monotonic() - last
                if inactivity is not None:
                    raise InactivityExceeded(inactivity, silent) from None
                raise CallTimeout(f"stream {method!r} exceeded whole-call deadline") from None
            now = time.monotonic()
            gaps.append(now - last)
            last = now
            if msg is _EOF:
                self.dead = True
                raise ProviderDead("provider closed its output")
            if isinstance(msg, dict) and msg.get("method") == "$/partial":
                p = msg.get("params") or {}
                if p.get("id") == rid:
                    partials.append(p)
                else:
                    stale.append(p.get("id"))
                    self.dropped_partials.append(p)
                continue
            if self._is_reply(msg, rid):
                if "error" in msg:
                    raise WireError(rid, msg["error"])
                return StreamResult(msg["result"], partials,
                                    max(gaps, default=0.0), stale)
            self._drop(msg)

    def silence(self, seconds):
        """Return messages arriving within a silence window (FC-041/054)."""
        seen = []
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return seen
            try:
                msg = self._q.get(timeout=remaining)
            except queue.Empty:
                return seen
            if msg is _EOF:
                self.dead = True
                return seen + [_EOF]
            seen.append(msg)

    @staticmethod
    def _is_reply(msg, rid):
        return (isinstance(msg, dict) and "method" not in msg
                and msg.get("id") == rid
                and ("result" in msg or "error" in msg))

    def _drop(self, msg):
        if isinstance(msg, dict) and msg.get("method") == "$/partial":
            self.dropped_partials.append(msg.get("params") or {})


# --------------------------------------------------------------------------
# Fixture
# --------------------------------------------------------------------------

class Fixture:
    """The materialized canonical fixture the adapter serves.

    Content is frozen and manifest-hashed, so the suite can compute
    expectations (real line numbers, exact blob bytes, mutated vs
    original content) without assuming anything about the adapter's
    content-id scheme — ids stay opaque per §Content ids.
    """

    def __init__(self, root, org=None):
        self.root = Path(root)
        self.org = org or os.environ.get("FORGE_ORG", "local")
        #: Where the adapter's disk cache is rooted at every initialize
        #: (§Handshake cache budget): a SIBLING of the materialized
        #: fixture, never inside it — the served tree must stay exactly
        #: the canonical fixture, or a caching adapter serves its own
        #: cache as a repo.
        self.cache_dir = Path(f"{self.root}-cache")

    def repo_id(self, name):
        return f"{self.org}/{name}"

    def dir(self, name):
        return self.root / name

    def path(self, name, rel):
        return self.dir(name) / rel

    def read(self, name, rel):
        return self.path(name, rel).read_bytes()

    def text(self, name, rel):
        return self.read(name, rel).decode("utf-8")

    def walk(self, name):
        """Every path under a repo → "tree" | "blob" (the protocol's
        recursive default-branch walk, §Methods repo/tree)."""
        out = {}
        base = self.dir(name)
        for dirpath, dirnames, filenames in os.walk(base):
            for d in sorted(dirnames):
                rel = os.path.relpath(os.path.join(dirpath, d), base)
                out[rel] = "tree"
            for f in sorted(filenames):
                rel = os.path.relpath(os.path.join(dirpath, f), base)
                out[rel] = "blob"
        return out

    def first_line_containing(self, name, rel, needle):
        """1-based number of the first line containing needle (FC-031)."""
        for n, line in enumerate(self.text(name, rel).splitlines(), start=1):
            if needle in line:
                return n
        return None

    def replace(self, name, rel, data):
        self.path(name, rel).write_bytes(data)


def check_code_item(item, cid, spec, where=""):
    """Shape of one search/code item (§Methods search/code): repo, path,
    sha strings; optional branch str, matches [str], line int ≥ 1 (v1.3),
    located bool (v1.3)."""
    where = f"{where}: " if where else ""
    fc_assert(isinstance(item, dict), cid, "search item shape", spec,
              f"{where}item is not an object: {item!r}")
    for f in ("repo", "path", "sha"):
        fc_assert(isinstance(item.get(f), str), cid, "search item shape", spec,
                  f"{where}item.{f} must be a string: {item.get(f)!r}")
    if "branch" in item:
        fc_assert(isinstance(item["branch"], str), cid, "search item shape", spec,
                  f"{where}item.branch must be a string: {item['branch']!r}")
    if "matches" in item:
        fc_assert(isinstance(item["matches"], list)
                  and all(isinstance(m, str) for m in item["matches"]),
                  cid, "search item shape", spec,
                  f"{where}item.matches must be a list of strings: {item['matches']!r}")
    if "line" in item:
        fc_assert(isinstance(item["line"], int) and not isinstance(item["line"], bool)
                  and item["line"] >= 1,
                  cid, "search item shape (line is 1-based, v1.3)", spec,
                  f"{where}item.line must be an int ≥ 1: {item['line']!r}")
    if "located" in item:
        fc_assert(isinstance(item["located"], bool), cid, "search item shape (located, v1.3)",
                  spec, f"{where}item.located must be a boolean: {item['located']!r}")


def check_partial_batch(params, cid, spec, where=""):
    """Shape of one $/partial params object (§Progressive results)."""
    fc_assert(isinstance(params, dict), cid, "$/partial shape", spec,
              f"{where}params is not an object: {params!r}")
    fc_assert("id" in params, cid, "$/partial shape", spec,
              f"{where}params.id missing (the batch must carry the request id)")
    fc_assert(isinstance(params.get("items"), list), cid, "$/partial shape", spec,
              f"{where}params.items must be a list: {params.get('items')!r}")


def suite_env(fixture_dir, hermetic=False, extra=None):
    """Environment for the adapter child: credentials scrubbed (they are
    lazy — §Transport restart obligations), fixture location exported.
    Hermetic strips everything but the bare OS minimum (FC-052)."""
    if hermetic:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(Path.home()),
            "LANG": "C.UTF-8",
            "FORGE_FIXTURE_DIR": str(fixture_dir),
        }
    else:
        env = dict(os.environ)
        for var in CREDENTIAL_VARS:
            env.pop(var, None)
        env["FORGE_FIXTURE_DIR"] = str(fixture_dir)
    if extra:
        env.update(extra)
    return env
