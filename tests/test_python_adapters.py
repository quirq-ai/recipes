import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from qqsync.manifest import loads

from qqrecipes import loader, runner
from qqrecipes.adapters import python_service
from qqrecipes.contract import ContractError, State
from qqrecipes.plan import plan

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "python-service"


def manifest(extra_server="", version="3.14.8"):
    return loads(textwrap.dedent(f"""\
        schema = "quirq-repo/1"
        [qq]
        version = "0.1.0"
        [toolchains.python]
        version = "{version}"
        source = "https://example.invalid/py.tar"
        digest = "sha256:{'0' * 64}"
        [[targets]]
        name = "server"
        kind = "python-service"
        srcs = ["server.py", "greet.py", "requirements.txt"]
        {extra_server}
        [[targets]]
        name = "tests"
        kind = "pytest"
        srcs = ["tests/**", "requirements-dev.txt"]
        deps = ["server"]
        """))


def actions(plans, target, capability):
    return next(p for p in plans if p.target == target and p.capability == capability)


def test_capabilities_match_kinds_toml():
    implemented = lambda k: {c for c, s in loader.load(k).capabilities().items() if s is State.IMPLEMENTED}
    assert implemented("python-service") == {"fetch", "build", "run", "deploy"}
    assert implemented("pytest") == {"fetch", "test"}


def test_test_goal_plan():
    plans = plan(manifest(), "test", EXAMPLE)
    fetch = actions(plans, "server", "fetch").actions
    assert [a.name for a in fetch] == ["toolchain-check", "venv", "install"]
    assert fetch[0].argv[0] == "{toolchain:python}python3" and "'3.14'" in fetch[0].argv[2]
    assert fetch[2].argv[-1] == "requirements.txt"
    assert actions(plans, "tests", "fetch").actions[2].argv[-1] == "requirements-dev.txt"
    build = actions(plans, "server", "build").actions[0]
    assert build.argv[-2:] == ("server.py", "greet.py")  # requirements.txt is not compiled
    test = actions(plans, "tests", "test").actions[0]
    assert test.junit == "{out}/junit/tests.pytest.xml" and f"--junitxml={test.junit}" in test.argv


def test_service_actions():
    m = manifest('params = { ready_path = "/health", probes = ["/health", "/x"] }')
    for cap in ("run", "deploy"):
        a = actions(plan(m, cap, EXAMPLE, ["server"]), "server", cap).actions[0]
        assert a.argv[-1] == "server.py" and dict(a.env)["PORT"] == "{port}"
        assert a.service.ready_path == "/health" and a.service.probes == ("/health", "/x")
        assert not a.cacheable


def test_missing_requirements_is_a_clear_error(tmp_path):
    for f in ("server.py", "greet.py", "requirements.txt", "requirements-dev.txt"):
        (tmp_path / f).write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("")
    m = manifest()
    m["targets"][1]["params"] = {"requirements": "dev.txt"}
    with pytest.raises(ContractError, match="requirements file 'dev.txt' not found"):
        plan(m, "fetch", tmp_path)


def test_bad_pytest_args():
    m = manifest()
    m["targets"][1]["params"] = {"args": "-x"}
    with pytest.raises(ContractError, match="params.args must be a list"):
        plan(m, "test", EXAMPLE)


def test_compile_roots(tmp_path):
    (tmp_path / "requirements.txt").write_text("")
    assert python_service.compile_roots(tmp_path, ["a.py", "pkg/**", "./pkg/x.py", "requirements.txt"]) == ["a.py", "pkg"]
    assert python_service.compile_roots(tmp_path, ["*.py", "pkg/**"]) == ["."]


@pytest.mark.parametrize("version,ok", [(f"{sys.version_info[0]}.{sys.version_info[1]}.0", True), ("2.7.18", False)])
def test_toolchain_check_runs(tmp_path, version, ok):
    check = actions(plan(manifest(version=version), "fetch", EXAMPLE, ["server"]), "server", "fetch").actions[0]
    root = Path(sys.executable).parent.parent  # the running interpreter as the "toolchain"
    env = runner.Env(repo=EXAMPLE, out=tmp_path, toolchains={"python": root})
    argv, environ, cwd = env.command(check)
    if not Path(argv[0]).exists():
        pytest.skip(f"{argv[0]} not present in this interpreter's prefix")
    assert (subprocess.run(argv, env=environ, cwd=cwd).returncode == 0) is ok
