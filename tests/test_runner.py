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
