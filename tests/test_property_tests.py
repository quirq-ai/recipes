"""V0-REC-04: property tests run as ordinary tests, deterministic and time-boxed."""
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from qqsync.manifest import loads

from qqrecipes import loader
from qqrecipes.plan import plan

ROOT = Path(__file__).resolve().parent.parent
PY_EXAMPLE = ROOT / "examples" / "python-service"
NODE_EXAMPLE = ROOT / "examples" / "node-app"


def step(plans, target, capability):
    return next(p for p in plans if p.target == target and p.capability == capability).actions


def test_pytest_loads_the_gate_plugin():
    from qqsync.manifest import load
    a = step(plan(load(PY_EXAMPLE / "infra/repo.toml"), "test", PY_EXAMPLE), "tests", "test")[0]
    assert ("-p", "qq_hypothesis") == a.argv[a.argv.index("qq_hypothesis") - 1: a.argv.index("qq_hypothesis") + 1]
    assert dict(a.env)["PYTHONPATH"] == "{adapter}"
    assert (loader.adapter_dir(loader.load("pytest")) / "qq_hypothesis.py").is_file()


def test_gate_profile_is_deterministic_and_bounded(tmp_path):
    pytest.importorskip("hypothesis")
    (tmp_path / "test_p.py").write_text(textwrap.dedent("""\
        from hypothesis import given, settings, strategies as st

        def test_profile():
            s = settings()
            assert s.derandomize and s.database is None and s.max_examples == 7 and s.deadline is None

        @given(st.integers())
        def test_runs(x):
            assert isinstance(x, int)
        """))
    plugin_dir = loader.adapter_dir(loader.load("pytest"))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "qq_hypothesis",
                        str(tmp_path)], env={"PYTHONPATH": str(plugin_dir), "QQ_PROPERTY_EXAMPLES": "7",
                                             "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def node_manifest():
    return loads(textwrap.dedent("""\
        schema = "quirq-repo/1"
        [qq]
        version = "0.1.0"
        [[targets]]
        name = "app"
        kind = "node-app"
        srcs = ["package.json"]
        """))


@pytest.mark.parametrize("deps,names", [
    ({"vitest": "5"}, ["typecheck", "vitest"]),
    ({"vitest": "5", "fast-check": "4"}, ["typecheck", "property-setup", "vitest"]),
])
def test_node_property_setup_only_with_fast_check(tmp_path, deps, names):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "next build", "typecheck": "tsc"}, "devDependencies": deps}))
    (tmp_path / "pnpm-lock.yaml").write_text("")
    acts = step(plan(node_manifest(), "test", tmp_path), "app", "test")
    assert [a.name for a in acts] == names
    if "fast-check" in deps:
        assert acts[-1].argv[-2:] == ("--config", ".qq/vitest.config.mjs")
        assert acts[1].argv == ("{toolchain:node}node", "{adapter}/qq_property_setup.mjs")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("base", [None, "vitest.config.ts"])
def test_property_setup_script_writes_config(tmp_path, base):
    if base:
        (tmp_path / base).write_text("export default {}\n")
    script = loader.adapter_dir(loader.load("node-app")) / "qq_property_setup.mjs"
    subprocess.run(["node", str(script)], cwd=tmp_path, check=True, capture_output=True)
    config = (tmp_path / ".qq" / "vitest.config.mjs").read_text()
    assert "./.qq/qq-fast-check.mjs" in config
    assert ('import base from "../vitest.config.ts"' in config) == bool(base)
    assert "fc.configureGlobal" in (tmp_path / ".qq" / "qq-fast-check.mjs").read_text()


def test_examples_have_property_tests():
    assert "hypothesis" in (PY_EXAMPLE / "requirements-dev.txt").read_text()
    assert "fast-check" in json.loads((NODE_EXAMPLE / "package.json").read_text())["devDependencies"]


def test_repo_profile_is_respected(tmp_path):
    pytest.importorskip("hypothesis")
    (tmp_path / "conftest.py").write_text(
        "from hypothesis import settings\nsettings.register_profile('repo', max_examples=3)\n"
        "settings.load_profile('repo')\n")
    (tmp_path / "test_p.py").write_text(
        "from hypothesis import settings\ndef test_p():\n    assert settings().max_examples == 3\n")
    plugin_dir = loader.adapter_dir(loader.load("pytest"))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "qq_hypothesis",
                        str(tmp_path)], env={"PYTHONPATH": str(plugin_dir), "PATH": "/usr/bin:/bin"},
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
