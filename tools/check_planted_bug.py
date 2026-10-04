#!/usr/bin/env python3
"""V0-REC-04 done-when, for one kind: a planted input-handling bug is caught by a property test.

Copies an example repo, checks its `test` goal passes, plants a bug (replace OLD with NEW in FILE),
then checks the goal fails and that TEST is among the failing JUnit test cases.

    tools/check_planted_bug.py EXAMPLE FILE OLD NEW TEST [-- qqrecipes execute args...]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

SKIP = shutil.ignore_patterns(".qq", "node_modules", ".next", "__pycache__")


def run_tests(repo: Path, out: Path, extra: list[str]) -> int:
    cmd = ["qqrecipes", "execute", "test", "--repo", str(repo), "--out", str(out), "--keep-going", *extra]
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def failing_cases(out: Path) -> set[str]:
    names = set()
    for xml in (out / "junit").rglob("*.xml"):
        for case in ET.parse(xml).getroot().iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                names.add(case.get("name", ""))
    return names


def main(argv: list[str]) -> int:
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[: argv.index("--")] if "--" in argv else argv
    if len(argv) != 6:
        print(__doc__, file=sys.stderr)
        return 2
    _, example, file, old, new, test = argv
    with tempfile.TemporaryDirectory(prefix="qq-planted-") as tmp:
        repo = Path(tmp) / "repo"
        shutil.copytree(example, repo, ignore=SKIP)
        if run_tests(repo, Path(tmp) / "clean", extra) != 0:
            print(f"FAIL: {example} does not pass before the bug is planted", file=sys.stderr)
            return 1
        target = repo / file
        text = target.read_text()
        if text.count(old) != 1:
            print(f"FAIL: {old!r} must occur exactly once in {file}", file=sys.stderr)
            return 1
        target.write_text(text.replace(old, new))
        print(f"planted in {file}: {old!r} -> {new!r}")
        if run_tests(repo, Path(tmp) / "planted", extra) == 0:
            print("FAIL: the planted bug was not caught", file=sys.stderr)
            return 1
        failed = failing_cases(Path(tmp) / "planted")
        if not any(test in name for name in failed):
            print(f"FAIL: caught, but not by {test!r}; failing cases: {sorted(failed)}", file=sys.stderr)
            return 1
        print(f"PASS: the planted bug was caught by {test}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
