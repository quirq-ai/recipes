"""Shared by the Python kinds (python-service, pytest): one virtualenv per repo checkout, made
from the pinned CPython, under `.qq/venv` so it is never an input."""
from __future__ import annotations

from pathlib import Path

from qqrecipes.contract import Action, Adapter, ContractError, Context, Target

TOOLCHAIN = "python"
INTERPRETER = "{toolchain:python}python3"
VENV_PYTHON = "{repo}/.qq/venv/bin/python"


def pinned_version(ctx: Context) -> str | None:
    """`3.14.8` from the manifest's `[toolchains.python] version`; `3.14` if only that much is a
    plain number (`3.14`, `3.14.8rc1`), so the check never silently turns off."""
    parts = str(ctx.toolchains.get(TOOLCHAIN, {}).get("version", "")).split(".")
    numeric = []
    for p in parts[:3]:
        if not p.isdigit():
            break
        numeric.append(p)
    return ".".join(numeric) if len(numeric) >= 2 else None


# Reuse .qq/venv only if this very interpreter made it; otherwise rebuild it from scratch, so a
# changed pin or toolchain root never leaves the venv on another Python.
MAKE_VENV = """\
import os, sys, venv
path = sys.argv[1]
cfg = os.path.join(path, "pyvenv.cfg")
want = "executable = " + os.path.realpath(sys.executable)
try:
    with open(cfg, encoding="utf-8") as f:
        same = any(line.strip() == want for line in f)
except OSError:
    same = False
if same and os.path.exists(os.path.join(path, "bin", "python")):
    print("qq: reusing", path)
else:
    venv.EnvBuilder(with_pip=True, clear=True).create(path)
    print("qq: created", path, "from", sys.executable)
"""


def version_check(version: str) -> str:
    """Exit non-zero unless this interpreter is the pinned version, to as many places as pinned."""
    n = len(version.split("."))
    return (f"import sys; v='.'.join(map(str, sys.version_info[:{n}])); "
            f"sys.exit(0 if v == '{version}' else 'pinned CPython {version}, found ' + v + ' at ' + sys.executable)")


def venv_actions(adapter: Adapter, target: Target, ctx: Context) -> list[Action]:
    """Check the interpreter is the pinned version, create (or reuse) the venv, check it too."""
    actions = []
    version = pinned_version(ctx)
    if version:
        # TODO(expert): also check the toolchain digest once CI runs quirq-ai/toolchains' CPython
        # (V0-TCH-01) instead of actions/setup-python at the same version.
        actions.append(adapter.action(target, ctx, "fetch", "toolchain-check",
                                      [INTERPRETER, "-c", version_check(version)]))
    actions.append(adapter.action(target, ctx, "fetch", "venv",
                                  [INTERPRETER, "-c", MAKE_VENV, "{repo}/.qq/venv"], cacheable=False))
    if version:
        actions.append(adapter.action(target, ctx, "fetch", "venv-check",
                                      [VENV_PYTHON, "-c", version_check(version)], cacheable=False))
    return actions


def install(adapter: Adapter, target: Target, ctx: Context, default: str) -> Action:
    """pip-install the target's requirements file into the venv. It must exist."""
    requirements = str(target.params.get("requirements", default))
    if not (Path(ctx.repo) / requirements).is_file():
        raise ContractError(
            f"target {target.name!r} ({adapter.kind}): requirements file {requirements!r} not found;"
            f" add it or set params.requirements")
    return adapter.action(target, ctx, "fetch", "install",
                          [VENV_PYTHON, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                           "-r", requirements], cacheable=False)
