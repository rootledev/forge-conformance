#!/usr/bin/env python3
"""rootle stdio provider over a local directory (plans/0005).

Reference implementation of the rootle provider protocol: NDJSON-RPC 2.0
on stdin/stdout. Serves <root>/<repo> as repos under the "local" org —
useful as a template for wrapping internal systems, as an offline dev
backend, and as documentation-by-example of the protocol.

    python3 fs_provider.py ~/code            # serve ~/code/* as repos
    rootle --config provider.toml               # [provider] kind="stdio"

Protocol v1 methods:
    initialize            -> {protocol, name, capabilities}
    search/repos  {query} -> {items: [{full_name} | {org}]}
    org/repos     {org}   -> {repos: [name]}
    repo/tree     {repo, ref?} -> {entries, truncated, branch}
    repo/blob     {repo, sha} -> {bytes_b64}
    repo/blob_at  {repo, path, ref?} -> {bytes_b64, sha}   (v1.5)
    repo/refs     {repo}  -> {branches, tags}               (v1.5, git)
    repo/log      {repo, path?, ref?, limit?} -> {items}    (v1.5, git)
    repo/blame    {repo, path, ref?} -> {ranges}            (v1.5, git)
    search/code   {q}     -> {items: [{repo, path, sha, branch, matches}]}

Contract: blob shas are content hashes (sha256) — they change when
content changes, which is what rootle's cache requires.
"""

import base64
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Iterator


ORG = "local"
SKIP_DIRS = {".git", "__pycache__", "target", "node_modules"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class NotFound(ValueError):
    """A miss the UI should render as not_found (§Errors kinds, v1.1)."""


_git_checked = False
_git_ok = False


def git_available() -> bool:
    """True when a working git binary is on PATH (probed once).

    The v1.5 revision trio (refs/log/blame) is served through git
    when present and honestly declared false otherwise (§Handshake:
    absent means default false — a backend that can, says so)."""
    global _git_checked, _git_ok
    if not _git_checked:
        _git_ok = False
        path = shutil.which("git")
        if path:
            try:
                subprocess.run([path, "--version"], capture_output=True,
                               check=True, timeout=15)
                _git_ok = True
            except (OSError, subprocess.SubprocessError):
                pass
        _git_checked = True
    return _git_ok


def _git(repo_path: str, *args: str) -> bytes:
    """Run git in a repo dir; git's failure text becomes NotFound."""
    if not git_available():
        raise NotFound("git is not available")
    proc = subprocess.run(["git", "-C", repo_path, *args],
                          capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise NotFound(detail[-1] if detail else f"git {args[0]} failed")
    return proc.stdout


def _safe_ref(ref) -> str:
    """Refs ride argv: refuse option-looking or empty values (an
    unknown ref is the caller's NotFound, never an option injection)."""
    if not isinstance(ref, str) or not ref.strip() or ref.lstrip().startswith("-"):
        raise NotFound(f"unknown ref {ref!r}")
    return ref.strip()


def _safe_path(path) -> str:
    """Normalize a repo-relative path; traversal and absolutes miss."""
    if not isinstance(path, str) or not path.strip():
        raise NotFound(f"no path {path!r}")
    parts = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise NotFound(f"no path {path!r}")
        parts.append(part)
    if not parts:
        raise NotFound(f"no path {path!r}")
    return "/".join(parts)


def _default_branch(repo_path: str) -> str:
    """HEAD's branch name ("" when detached or not a git repo)."""
    if not git_available():
        return ""
    proc = subprocess.run(
        ["git", "-C", repo_path, "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True)
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def _is_git_repo(repo_path: str) -> bool:
    if not git_available():
        return False
    proc = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--is-inside-work-tree"],
        capture_output=True)
    return proc.returncode == 0 and proc.stdout.strip() == b"true"


def _resolve_commit(repo_path: str, ref: str) -> str:
    """Peel ref to a commit id (tags peel); unknown ref -> NotFound."""
    proc = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--verify", "--quiet",
         f"{ref}^{{commit}}"], capture_output=True)
    sha = proc.stdout.decode().strip()
    if proc.returncode != 0 or not sha:
        raise NotFound(f"unknown ref {ref!r}")
    return sha


def _iso_date(ts: str, tz: str) -> str:
    """git author-time/author-tz -> ISO-8601 (same shape as %aI)."""
    off = timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5]))
    if tz.startswith("-"):
        off = -off
    return datetime.fromtimestamp(int(ts), timezone(off)).isoformat()



def list_repos(root: str) -> list[str]:
    """Repo names under ORG, nested paths included ("nested/sub"):
    a directory is a repo when it holds files directly; directories
    with only subdirectories keep descending (bounded). Multi-slash
    ids are legal — rootle treats repos as opaque strings."""
    def walk(dir: str, rel: str, depth: int) -> list[str]:
        out: list[str] = []
        for d in sorted(os.listdir(dir)):
            full = os.path.join(dir, d)
            if not os.path.isdir(full) or d in SKIP_DIRS:
                continue
            child_rel = f"{rel}/{d}" if rel else d
            entries = os.listdir(full)
            has_file = any(os.path.isfile(os.path.join(full, e)) for e in entries)
            is_worktree = ".git" in entries
            if has_file or is_worktree:
                # A directory with files — or a git worktree, whose root
                # may hold only subdirs — is a repo (a forge project
                # root); never descend into one.
                out.append(child_rel)
            elif depth < 3:
                out.extend(walk(full, child_rel, depth + 1))
        return out

    return walk(root, "", 0)


def repo_dir(root: str, repo: str) -> str:
    if "/" not in repo:
        raise ValueError(f"bad repo id {repo!r}")
    path = os.path.join(root, repo.split("/", 1)[1])
    if not os.path.isdir(path):
        raise ValueError(f"unknown repo {repo!r}")
    return path


def walk_tree(root: str, repo: str, ref: str | None = None) -> list[dict]:
    """Recursive entries: blobs content-hashed, dirs path-hashed.

    v1.5: ``ref`` serves that branch/tag/sha's tree through git
    ls-tree. Content ids stay sha256-of-bytes — an id means the same
    bytes at every ref, which is what rootle's content-keyed cache
    requires (§Content ids)."""
    base = repo_dir(root, repo)
    if ref is not None:
        return _walk_tree_at_ref(base, _safe_ref(ref))
    entries = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base)
            entries.append({"path": rel, "type": "tree", "sha": sha256(rel.encode())})
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base)
            with open(full, "rb") as f:
                data = f.read()
            entries.append(
                {"path": rel, "type": "blob", "sha": sha256(data), "size": len(data)}
            )
    return entries


def _walk_tree_at_ref(base: str, ref: str) -> list[dict]:
    _resolve_commit(base, ref)
    out = _git(base, "ls-tree", "-r", "-t", "--long", "-z", ref)
    entries = []
    for record in out.decode("utf-8", "surrogateescape").split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        _mode, otype, osha, size = meta.split()
        if otype == "tree":
            entries.append({"path": path, "type": "tree", "sha": sha256(path.encode())})
        else:
            data = _git(base, "cat-file", "blob", osha)
            entries.append({"path": path, "type": "blob",
                            "sha": sha256(data), "size": int(size)})
    return entries


def blob_by_sha(root: str, repo: str, sha: str) -> bytes:
    for entry in walk_tree(root, repo):
        if entry["type"] == "blob" and entry["sha"] == sha:
            with open(os.path.join(repo_dir(root, repo), entry["path"]), "rb") as f:
                return f.read()
    # v1.5: a git-backed repo can hold the bytes at another ref the
    # worktree no longer shows (fixture-scale sweep, never hit on the
    # plain path — the worktree walk above is unchanged).
    base = repo_dir(root, repo)
    if _is_git_repo(base):
        out = _git(base, "for-each-ref", "--format=%(refname)",
                   "refs/heads", "refs/tags").decode()
        for ref in filter(None, out.splitlines()):
            ls = _git(base, "ls-tree", "-r", "-z", ref)
            for record in ls.decode("utf-8", "surrogateescape").split("\0"):
                if not record:
                    continue
                meta = record.partition("\t")[0]
                _mode, otype, osha = meta.split()[:3]
                if otype != "blob":
                    continue
                data = _git(base, "cat-file", "blob", osha)
                if sha256(data) == sha:
                    return data
    raise ValueError(f"no blob {sha} in {repo}")


def blob_at(root: str, repo: str, path: str, ref: str | None = None) -> tuple[bytes, str]:
    """v1.5 repo/blob_at: bytes + content id of path at ref (the
    default branch — for fs, the worktree — when ref is absent)."""
    base = repo_dir(root, repo)
    rel = _safe_path(path)
    if ref is None:
        full = os.path.join(base, rel)
        if not os.path.isfile(full):
            raise NotFound(f"no path {path!r} in {repo}")
        with open(full, "rb") as f:
            data = f.read()
        return data, sha256(data)
    data = _git(base, "show", f"{_safe_ref(ref)}:{rel}")
    return data, sha256(data)


def list_refs(root: str, repo: str) -> dict:
    """v1.5 repo/refs: branches (HEAD's branch marked default — at
    most one) and tags, from the repo git actually holds."""
    base = repo_dir(root, repo)
    if not _is_git_repo(base):
        raise NotFound(f"{repo} has no refs (not a git repo)")
    head = _default_branch(base)

    def listing(prefix: str) -> list[tuple[str, str]]:
        out = _git(base, "for-each-ref",
                   "--format=%(refname:short)%09%(objectname)", prefix)
        pairs = []
        for line in out.decode().splitlines():
            if line:
                name, _, osha = line.partition("\t")
                pairs.append((name, osha.strip()))
        return pairs

    branches = [{"name": n, "sha": s, "default": True} if n == head
                else {"name": n, "sha": s}
                for n, s in listing("refs/heads")]
    tags = [{"name": n, "sha": s} for n, s in listing("refs/tags")]
    return {"branches": branches, "tags": tags}


_LOG_FORMAT = "%H%x1f%s%x1f%an%x1f%aI%x1e"


def repo_log(root: str, repo: str, path: str | None = None,
             ref: str | None = None, limit=None) -> dict:
    """v1.5 repo/log: newest first, ISO-8601 dates; limit rides the
    bounded-compute contract — stop at ~N and set truncated: true."""
    base = repo_dir(root, repo)
    rev = _safe_ref(ref) if ref is not None else (_default_branch(base) or "HEAD")
    rev = _resolve_commit(base, rev)
    capped = isinstance(limit, int) and not isinstance(limit, bool) and limit > 0
    args = ["log", f"--format={_LOG_FORMAT}"]
    if capped:
        args += ["-n", str(limit)]
    args.append(rev)
    if path is not None:
        args += ["--", _safe_path(path)]
    items = []
    for record in _git(base, *args).decode("utf-8", "surrogateescape").split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, subject, author, date = record.split("\x1f")
        items.append({"sha": sha, "subject": subject, "author": author, "date": date})
    truncated = False
    if capped:
        count_args = ["rev-list", "--count", rev]
        if path is not None:
            count_args += ["--", _safe_path(path)]
        total = int(_git(base, *count_args).decode().strip() or "0")
        truncated = total > len(items)
    return {"items": items, "truncated": truncated}


def repo_blame(root: str, repo: str, path: str, ref: str | None = None) -> dict:
    """v1.5 repo/blame: 1-based inclusive ranges covering every line,
    adjacent same-sha ranges coalesced (git --line-porcelain)."""
    base = repo_dir(root, repo)
    rev = _safe_ref(ref) if ref is not None else (_default_branch(base) or "HEAD")
    _resolve_commit(base, rev)
    out = _git(base, "blame", "--line-porcelain", rev, "--",
               _safe_path(path)).decode("utf-8", "surrogateescape")
    lines = []
    cur = None
    for raw in out.splitlines():
        if raw.startswith("\t"):
            if cur is not None:
                lines.append(cur)
                cur = None
            continue
        if cur is None:
            cur = {"sha": raw.split(" ", 1)[0]}
        elif raw.startswith("author-time "):
            cur["ts"] = raw.split(" ", 1)[1].strip()
        elif raw.startswith("author-tz "):
            cur["tz"] = raw.split(" ", 1)[1].strip()
        elif raw.startswith("author "):
            cur["author"] = raw.split(" ", 1)[1]
    if not lines:
        raise NotFound(f"no path {path!r} in {repo}")
    ranges = []
    for n, info in enumerate(lines, start=1):
        if ranges and ranges[-1]["sha"] == info["sha"]:
            ranges[-1]["end_line"] = n  # coalesce adjacent same-sha
        else:
            ranges.append({"start_line": n, "end_line": n, "sha": info["sha"],
                           "author": info.get("author", ""),
                           "date": _iso_date(info.get("ts", "0"),
                                             info.get("tz", "+0000"))})
    return {"ranges": ranges}


def parse_query(q: str) -> tuple[str, str | None, str | None, str | None]:
    """Split a rootle code query into (terms, repo, org, extension)."""
    repo = org = ext = None
    terms = []
    for token in q.split():
        if token.startswith("repo:"):
            repo = token[5:]
        elif token.startswith("org:"):
            org = token[4:]
        elif token.startswith("extension:"):
            ext = token[10:]
        elif token.startswith("path:"):
            terms.append(token[5:])  # path match ≈ term match for fs
        else:
            terms.append(token)
    return " ".join(terms), repo, org, ext


def search_code(root: str, q: str) -> list[dict]:
    terms, repo_scope, _org, ext = parse_query(q)
    needles = [t.lower() for t in terms.split() if t]
    repos = [f"{ORG}/{repo_scope.split('/', 1)[1]}"] if repo_scope else [
        f"{ORG}/{d}" for d in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, d)) and d not in SKIP_DIRS
    ]
    items = []
    for repo in repos:
        if not os.path.isdir(os.path.join(root, repo.split("/", 1)[1])):
            continue
        for entry in walk_tree(root, repo):
            if entry["type"] != "blob":
                continue
            if ext and not entry["path"].lower().endswith("." + ext.lstrip(".")):
                continue
            full = os.path.join(repo_dir(root, repo), entry["path"])
            try:
                text = open(full, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if text.startswith("\x00") or "\x00" in text[:8192]:
                continue  # binary
            matched = [n for n in needles if n in text.lower()]
            if needles and not matched:
                continue
            items.append(
                {
                    "repo": repo,
                    "path": entry["path"],
                    "sha": entry["sha"],
                    "branch": "main",
                    "matches": matched,
                }
            )
    return items


def search_code_batches(root: str, q: str) -> Iterator[list[dict]]:
    """v1.3 progressive search: yield per-repo batches; the caller
    streams each as a $/partial notification."""
    terms, repo_scope, _org, ext = parse_query(q)
    needles = [t.lower() for t in terms.split() if t]
    repos = [f"{ORG}/{repo_scope.split('/', 1)[1]}"] if repo_scope else [
        f"{ORG}/{d}" for d in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, d)) and d not in SKIP_DIRS
    ]
    for repo in repos:
        if not os.path.isdir(os.path.join(root, repo.split("/", 1)[1])):
            continue
        batch = []
        for entry in walk_tree(root, repo):
            if entry["type"] != "blob":
                continue
            if ext and not entry["path"].lower().endswith("." + ext.lstrip(".")):
                continue
            full = os.path.join(repo_dir(root, repo), entry["path"])
            try:
                text = open(full, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if text.startswith("\x00") or "\x00" in text[:8192]:
                continue  # binary
            matched = [n for n in needles if n in text.lower()]
            if needles and not matched:
                continue
            # v1.3: we know the real line — first one matching the first
            # needle (the backend hands us offsets nobody has).
            line = 1
            if matched:
                lowered = text.lower()
                for n, ln in enumerate(lowered.splitlines(), start=1):
                    if matched[0] in ln:
                        line = n
                        break
            batch.append(
                {
                    "repo": repo,
                    "path": entry["path"],
                    "sha": entry["sha"],
                    "branch": "main",
                    "matches": matched,
                    "line": line,
                }
            )
        if batch:
            yield batch


def handle(root: str, method: str, params: dict) -> dict:
    if method == "initialize":
        git_ok = git_available()
        return {
            "protocol": 1,
            "name": "fs",
            # v1.3: the modeline icon — a builtin name rootle maps to
            # its Nerd Font glyph when nerd_font is on.
            "icon": "folder",
            "capabilities": {
                "orgs": True, "code_search": True,
                # v1.5 revision trio, honest: served through git when
                # a working git is on PATH, else default-branch-only.
                "refs": git_ok, "log": git_ok, "blame": git_ok,
            },
        }
    if method == "search/repos":
        query = params.get("query", "").lower()
        items = [
            {"full_name": f"{ORG}/{d}"}
            for d in list_repos(root)
            if query in d.lower()
        ]
        if not items:
            items.append({"org": ORG})
        return {"items": items[:20]}
    if method == "org/repos":
        return {"repos": list_repos(root)}
    if method == "repo/tree":
        repo = params["repo"]
        ref = params.get("ref")
        return {
            "entries": walk_tree(root, repo, ref=ref),
            "truncated": False,
            # v1.5: branch names what was actually served — the ref
            # when one was given (unknown ref -> NotFound above).
            "branch": ref if ref is not None else "main",
        }
    if method == "repo/refs":
        return list_refs(root, params["repo"])
    if method == "repo/log":
        return repo_log(root, params["repo"], path=params.get("path"),
                        ref=params.get("ref"), limit=params.get("limit"))
    if method == "repo/blob_at":
        data, sha = blob_at(root, params["repo"], params.get("path", ""),
                            ref=params.get("ref"))
        return {"bytes_b64": base64.b64encode(data).decode(), "sha": sha}
    if method == "repo/blame":
        return repo_blame(root, params["repo"], params.get("path", ""),
                          ref=params.get("ref"))
    if method == "repo/clone_url":
        # Cloning a local dir: the filesystem path IS the remote.
        return {"clone_url": repo_dir(root, params["repo"])}
    if method == "repo/web_url":
        base = pathlib.Path(repo_dir(root, params["repo"])).resolve().as_uri()
        path = params.get("path", "")
        line = params.get("line")
        is_file = params.get("is_file", False)
        url = f"{base}/{path}" if path else base
        if is_file and line:
            url += f"#L{line}"
        return {"url": url}
    if method == "org/url":
        return {"url": pathlib.Path(root).resolve().as_uri()}
    if method == "repo/blob":
        data = blob_by_sha(root, params["repo"], params["sha"])
        return {"bytes_b64": base64.b64encode(data).decode()}
    if method == "search/code":
        return {"items": search_code(root, params.get("q", ""))}
    raise ValueError(f"unknown method {method!r}")


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
            # Notification (e.g. $/cancelRequest) — never reply.
            continue
        partial = None
        try:
            params = req.get("params") or {}
            if req.get("method") == "search/code" and params.get("partial"):
                # v1.3: stream batches as $/partial notifications keyed
                # by the request id; the reply is metadata-only.
                partial = req.get("id")
                for batch in search_code_batches(root, params.get("q", "")):
                    note = {
                        "jsonrpc": "2.0",
                        "method": "$/partial",
                        "params": {"id": partial, "items": batch},
                    }
                    sys.stdout.write(json.dumps(note) + "\n")
                    sys.stdout.flush()
                result = {"items": [], "truncated": False}
            else:
                result = handle(root, req.get("method", ""), params)
            reply = {"jsonrpc": "2.0", "id": req.get("id"), "result": result}
        except NotFound as e:
            # v1.1 kinds: not_found renders precisely (§Errors).
            reply = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": 1, "message": str(e),
                          "data": {"kind": "not_found"}},
            }
        except Exception as e:  # noqa: BLE001 — surfaced to the TUI
            reply = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": 1, "message": str(e)},
            }
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
