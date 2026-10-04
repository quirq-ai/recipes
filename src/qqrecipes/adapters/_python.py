"""Shared by the Python kinds (python-service, pytest): one virtualenv per repo checkout, made
from the pinned CPython, under `.qq/venv` so it is never an input."""
from __future__ import annotations

from pathlib import Path

from qqrecipes.contract import Action, Adapter, ContractError, Context, Target

TOOLCHAIN = "python"
INTERPRETER = "{toolchain:python}python3"
VENV_PYTHON = "{repo}/.qq/venv/bin/python"


def pinned_minor(ctx: Context) -> str | None:
    """`3.14` from the manifest's `[toolchains.python] version = "3.14.8"`, if pinned."""
    version = str(ctx.toolchains.get(TOOLCHAIN, {}).get("version", ""))
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]) else None


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


def version_check(minor: str) -> str:
    return (f"import sys; v='%d.%d' % sys.version_info[:2]; "
            f"sys.exit(0 if v == '{minor}' else 'pinned CPython {minor}, found ' + v + ' at ' + sys.executable)")


def venv_actions(adapter: Adapter, target: Target, ctx: Context) -> list[Action]:
    """Check the interpreter is the pinned minor version, create (or reuse) the venv, check it too."""
    actions = []
    minor = pinned_minor(ctx)
    if minor:
        # TODO(expert): check the full version and digest once quirq-ai/toolchains publishes
        # CPython (V0-TCH-01); until then CI provides it with actions/setup-python.
        actions.append(adapter.action(target, ctx, "fetch", "toolchain-check",
                                      [INTERPRETER, "-c", version_check(minor)]))
    actions.append(adapter.action(target, ctx, "fetch", "venv",
                                  [INTERPRETER, "-c", MAKE_VENV, "{repo}/.qq/venv"], cacheable=False))
    if minor:
        actions.append(adapter.action(target, ctx, "fetch", "venv-check",
                                      [VENV_PYTHON, "-c", version_check(minor)], cacheable=False))
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
