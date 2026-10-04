"""Repo-shape checks that hold from the first commit."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_codeowners_names_suraj_for_exactly_the_trust_paths():
    # suraj names the owners (V0-ORG-02); agents must not change them.
    rules = {}
    for line in (ROOT / ".github" / "CODEOWNERS").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            path, *owners = line.split()
            rules[path] = owners
    # Exactly these paths: no catch-all and no later line that could leave one unowned (the last
    # match wins).
    owned = {"/.github/", "/pyproject.toml", "/tools/"}
    assert rules == {path: ["@sharmasuraj0123"] for path in owned}
    # A renamed path would leave its rule matching nothing.
    assert all((ROOT / path.strip("/")).exists() for path in owned)


def test_workflow_actions_are_pinned_to_commit_shas():
    # A tag can be moved to other code; a full commit SHA cannot.
    for wf in (ROOT / ".github" / "workflows").glob("*.y*ml"):
        for n, line in enumerate(wf.read_text().splitlines(), 1):
            m = re.match(r"\s*-?\s*uses:\s*(\S+)", line)
            if m and not m.group(1).startswith("./"):
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", m.group(1)), f"{wf.name}:{n} pins {m.group(1)} by tag"
