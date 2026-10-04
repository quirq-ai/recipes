"""pytest: a Python test suite run with pytest on the pinned CPython, writing JUnit XML.

params (all optional):
    requirements  test requirements file, which must include pytest (default "requirements-dev.txt")
    args          extra pytest arguments, a list (default [])
    shards        accepted and ignored in v0. TODO(expert): shard with pytest-xdist or by file.

Property tests (V0-REC-04): Hypothesis tests run as ordinary tests. The adapter loads its
`qq_hypothesis` plugin, which makes them deterministic and time-boxed in the gate.
"""
from __future__ import annotations

from qqrecipes.adapters import _python
from qqrecipes.contract import Adapter, ContractError


class Pytest(Adapter):
    kind = "pytest"
    toolchain = _python.TOOLCHAIN

    def fetch(self, target, ctx):
        return [*_python.venv_actions(self, target, ctx),
                _python.install(self, target, ctx, "requirements-dev.txt")]

    def test(self, target, ctx):
        args = target.params.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ContractError(f"target {target.name!r} (pytest): params.args must be a list of strings")
        junit = f"{{out}}/junit/{target.name}.pytest.xml"
        argv = [_python.VENV_PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "qq_hypothesis",
                f"--junitxml={junit}", "-o", "junit_family=xunit2", *args]
        # {adapter} holds the qq_hypothesis plugin. TODO(expert): append to a PYTHONPATH the repo sets.
        return [self.action(target, ctx, "test", "pytest", argv, junit=junit,
                            env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "{adapter}"})]


ADAPTER = Pytest()
