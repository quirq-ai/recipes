"""Repo-shape checks that hold from the first commit."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_codeowners_has_no_owners_yet():
    # suraj assigns owners (V0-ORG-02); agents must not fill this in.
    lines = (ROOT / ".github" / "CODEOWNERS").read_text().splitlines()
    assert all(not line.strip() or line.lstrip().startswith("#") for line in lines)


def test_workflow_actions_are_pinned_to_commit_shas():
    # A tag can be moved to other code; a full commit SHA cannot.
    for wf in (ROOT / ".github" / "workflows").glob("*.y*ml"):
        for n, line in enumerate(wf.read_text().splitlines(), 1):
            m = re.match(r"\s*-?\s*uses:\s*(\S+)", line)
            if m and not m.group(1).startswith("./"):
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", m.group(1)), f"{wf.name}:{n} pins {m.group(1)} by tag"
