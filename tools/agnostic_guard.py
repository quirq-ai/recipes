#!/usr/bin/env python3
"""Agnosticism guard (plan §5.1): no core file names a language, build tool, test runner or deploy
target. Core is every module under src/qqrecipes except the adapter packages and modules under
src/qqrecipes/adapters/ (that tree's own __init__.py is core). Also, no core module imports an
adapter: core reaches adapters only through the loader.

    tools/agnostic_guard.py [ROOT]     exit 1 and every hit, or PASS

TODO(expert): share one guard across qq repos (depot, sync, gate, ...) instead of one per repo.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Words only an adapter may say. Kept to unambiguous names: "go" or "rust" would match prose.
BANNED = (
    "python", "python3", "cpython", "pypy", "pip", "pipx", "venv", "virtualenv", "pytest", "unittest",
    "hypothesis", "uvicorn", "gunicorn", "django", "flask", "fastapi", "compileall",
    "node", "nodejs", "npm", "npx", "pnpm", "yarn", "corepack", "next.js", "nextjs", "typescript",
    "javascript", "tsc", "vitest", "jest", "fast-check",
    "golang", "gotestsum", "cargo", "rustc", "jvm", "gradle", "maven", "bazel", "buck2", "pants",
    "docker", "podman", "dockerfile", "kubectl", "helm",
)
WORD = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(map(re.escape, BANNED)) + r")(?![A-Za-z0-9_-])",
                  re.IGNORECASE)
ADAPTERS = "qqrecipes.adapters"


def core_files(root: Path) -> list[Path]:
    src = root / "src" / "qqrecipes"
    adapters = src / "adapters"
    return sorted(p for p in src.rglob("*.py")
                  if adapters not in p.parents or p == adapters / "__init__.py")


def check(root: Path) -> list[str]:
    hits = []
    for path in core_files(root):
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            for m in WORD.finditer(line):
                hits.append(f"{rel}:{n}: names {m.group(1)!r}; move it into an adapter")
        for node in ast.walk(ast.parse(text, str(rel))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for name in names:
                if name.startswith(ADAPTERS + "."):
                    hits.append(f"{rel}:{node.lineno}: imports {name}; reach adapters through the loader")
    return hits


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    hits = check(root)
    for h in hits:
        print(h, file=sys.stderr)
    print("FAIL" if hits else "PASS")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
