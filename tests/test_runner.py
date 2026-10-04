import sys
from xml.etree import ElementTree as ET

from qqrecipes import runner
from qqrecipes.contract import Action

DIGEST = "sha256:" + "0" * 64


def act(argv, **kw):
    return Action(target="t", capability="test", name="n", argv=tuple(argv), input_root_digest=DIGEST, **kw)


def test_passing_action_gets_a_synthesized_junit_case(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    r = runner.run(act(["sh", "-c", "mkdir -p o && echo hi > o/f"], outputs=("o",)), env)
    assert r.ok and r.output_digests["o"].startswith("sha256:")
    case = ET.parse(r.junit).getroot().find("testcase")
    assert case.get("name") == "test:n" and case.find("failure") is None


def test_failing_action_records_failure_and_log_tail(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    r = runner.run(act(["sh", "-c", "echo boom; exit 3"]), env)
    assert r.exit_code == 3
    failure = ET.parse(r.junit).getroot().find("testcase/failure")
    assert failure.get("message") == "exit code 3" and "boom" in failure.text


def test_native_junit_is_kept(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    xml = '<testsuite tests="1"><testcase name="real"/></testsuite>'
    r = runner.run(act(["sh", "-c", f"mkdir -p \"$OUT\" && echo '{xml}' > \"$OUT/j.xml\""],
                       env=(("OUT", "{out}"),), junit="{out}/j.xml"), env)
    assert r.ok and r.junit.name == "j.xml"


def test_nonzero_exit_without_failures_in_native_junit_is_still_a_failure(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    r = runner.run(act(["sh", "-c", "mkdir -p \"$OUT\"; echo '<testsuite/>' > \"$OUT/j.xml\"; exit 2"],
                       env=(("OUT", "{out}"),), junit="{out}/j.xml"), env)
    assert ET.parse(r.junit).getroot().find("testcase/failure") is not None


def test_missing_command_and_timeout(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    assert runner.run(act(["qq-no-such-command"]), env).exit_code == 127
    assert runner.run(act(["sleep", "5"], timeout_s=1), env).exit_code == 124


def test_toolchain_placeholder(tmp_path):
    ambient = runner.Env(repo=tmp_path, out=tmp_path)
    assert ambient.resolve("{toolchain:sh}sh", "t") == "sh"
    pinned = runner.Env(repo=tmp_path, out=tmp_path, toolchains={"sh": tmp_path / "tc"})
    assert pinned.resolve("{toolchain:sh}sh", "t") == f"{(tmp_path / 'tc').resolve()}/bin/sh"
    assert pinned.resolve("{nothing}", "t") == "{nothing}"


def test_stale_junit_is_never_reported(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "j.xml").write_text('<testsuite><testcase name="old"><failure/></testcase></testsuite>')
    r = runner.run(act(["true"], junit="j.xml"), env)
    assert r.ok and r.junit.name != "j.xml"
    assert not (tmp_path / "out" / "j.xml").exists()


def test_relative_junit_is_under_out(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    r = runner.run(act(["sh", "-c", "mkdir -p \"$OUT\" && echo '<testsuite/>' > \"$OUT/r.xml\""],
                       env=(("OUT", "{out}"),), junit="r.xml"), env)
    assert r.junit == (tmp_path / "out" / "r.xml").resolve()


def test_adapter_placeholder_needs_a_package_adapter(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path)
    try:
        env.resolve("{adapter}/x", "t")
    except ValueError as e:
        assert "not a package" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_ambient_qq_settings_do_not_reach_the_command(tmp_path, monkeypatch):
    monkeypatch.setenv("QQ_PROPERTY_EXAMPLES", "7")
    show = [sys.executable, "-c", "import os, sys; sys.exit(os.environ.get('QQ_PROPERTY_EXAMPLES', 'unset') != 'unset')"]
    assert runner.run(act(show), runner.Env(repo=tmp_path, out=tmp_path / "out")).ok
    keyed = act(show, env=(("QQ_PROPERTY_EXAMPLES", "7"),))
    assert not runner.run(keyed, runner.Env(repo=tmp_path, out=tmp_path / "out")).ok


def test_a_run_on_the_tool_from_path_is_not_cacheable(tmp_path):
    a = act([sys.executable, "-c", "pass"], toolchains=(("py", "{pin}"),))
    assert not runner.run(a, runner.Env(repo=tmp_path, out=tmp_path / "out")).cacheable
    pinned = runner.Env(repo=tmp_path, out=tmp_path / "out", toolchains={"py": tmp_path})
    assert runner.run(a, pinned).cacheable
