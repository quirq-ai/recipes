"""Content digests for input roots and outputs. Core file: names no language or tool.

v0 digests a set of files as sha256 over its sorted `path NUL file-sha256 LF` lines. It is stable
across machines but is not the REAPI Merkle `Directory` encoding.
TODO(expert): switch to REAPI Directory digests when remote-build adds a CAS (V0-RBE-01/P3).
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

SKIP_DIRS = {".git", ".qq"}  # never inputs: version control and qq's own working state


class NoMatch(ValueError):
    """A source glob matched no file: almost always a typo, and it would silently drop inputs."""

    def __init__(self, globs: list[str]):
        self.globs = globs
        super().__init__(f"glob{'s' if len(globs) > 1 else ''} {', '.join(map(repr, globs))} match no file")


def normalize(pattern: str) -> str:
    return pattern[2:] if pattern.startswith("./") else pattern


def _translate(pattern: str) -> re.Pattern:
    """Glob to regex. `**` spans path segments, `*` and `?` stay within one. Root-relative."""
    pattern = normalize(pattern)
    pattern = pattern.strip("/") + ("/**" if pattern.endswith("/") else "")
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[" and "]" in pattern[i + 2:]:
            end = pattern.index("]", i + 2)
            body = pattern[i + 1:end]
            negate = body.startswith("!")
            body = body[1:] if negate else body
            # Escape each character but keep an interior `-` as a range, as fnmatch does.
            cls = "".join("-" if c == "-" and 0 < k < len(body) - 1 else re.escape(c)
                          for k, c in enumerate(body))
            out.append("[" + ("^" if negate else "") + cls + "]")
            i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + "(?:/.*)?" + r"\Z")


def matches(pattern: str, relpath: str) -> bool:
    """True if `relpath` is matched by `pattern`, or lies under a directory it matches."""
    return _translate(pattern).match(relpath) is not None


def list_files(repo: Path) -> list[str]:
    """Every file under `repo` that could be an input, relative to it.

    In a git work tree (also when `repo` is a subdirectory of one) this is git's view: tracked files
    plus untracked ones that are not ignored, so local edits are inputs too. Otherwise a walk.
    """
    repo = Path(repo)
    inside = subprocess.run(["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True, check=False)
    if inside.returncode == 0 and inside.stdout.strip() == "true":
        r = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=False)
        if r.returncode == 0:
            files = [f for f in r.stdout.decode().split("\0") if f]
            return sorted(f for f in files if f.split("/", 1)[0] not in SKIP_DIRS
                          and (repo / f).is_file())
    found = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        rel = Path(root).relative_to(repo)
        found.extend((rel / n).as_posix() for n in names)
    return sorted(found)


@lru_cache(maxsize=4096)
def _file_sha(path: Path, mtime_ns: int, size: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_sha(path: Path) -> str:
    st = path.stat()
    return _file_sha(path, st.st_mtime_ns, st.st_size)


def files_digest(repo: Path, relpaths: Iterable[str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(set(relpaths)):
        h.update(f"{rel}\0{file_sha(Path(repo) / rel)}\n".encode())
    return "sha256:" + h.hexdigest()


def input_root(repo: Path, globs: Iterable[str]) -> str:
    """Digest of every repo file matched by `globs`. No globs means an empty input root.

    Raises NoMatch naming every glob that matches no file.
    """
    globs = tuple(globs)
    if not globs:
        return files_digest(repo, ())
    files = list_files(repo)
    unmatched = [g for g in globs if not any(matches(g, f) for f in files)]
    if unmatched:
        raise NoMatch(unmatched)
    return files_digest(repo, (f for f in files if any(matches(g, f) for g in globs)))


def path_digest(path: Path) -> str | None:
    """Digest of a file, or of every file under a directory. None if it does not exist."""
    path = Path(path)
    if path.is_file():
        return "sha256:" + file_sha(path)
    if path.is_dir():
        rels = [p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()]
        return files_digest(path, rels)
    return None
