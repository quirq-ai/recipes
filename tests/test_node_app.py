import json
import textwrap

import pytest
from qqsync.manifest import loads

from qqrecipes import loader, runner
from qqrecipes.contract import Action, ContractError, State
from qqrecipes.plan import plan


def manifest(params=""):
    return loads(textwrap.dedent(f"""\
        schema = "quirq-repo/1"
        [qq]
        version = "0.1.0"
        [toolchains.node]
        version = "24"
        source = "https://example.invalid/node.tar"
        digest = "sha256:{'0' * 64}"
        [[targets]]
        name = "app"
        kind = "node-app"
        srcs = ["package.json", "pnpm-lock.yaml", "app/**"]
        {params}
        """))


@pytest.fixture
def app(tmp_path):
    def make(scripts=None, deps=None, tsconfig=True, lock=True):
        (tmp_path / "app").mkdir(exist_ok=True)
        (tmp_path / "app" / "page.tsx").write_text("export default function P() { return null }\n")
        (tmp_path / "package.json").write_text(json.dumps(
            {"scripts": scripts if scripts is not None else {"build": "next build", "typecheck": "tsc --noEmit"},
             "devDependencies": deps or {}}))
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n" if lock else "")
        if not lock:
            (tmp_path / "pnpm-lock.yaml").unlink()
        if tsconfig:
            (tmp_path / "tsconfig.json").write_text("{}")
        return tmp_path
    return make


def step(plans, capability):
    return next(p for p in plans if p.capability == capability)


def test_capabilities_match_kinds_toml():
    caps = loader.load("node-app").capabilities()
    assert {c for c, s in caps.items() if s is State.IMPLEMENTED} == {"fetch", "build", "test", "run", "deploy"}


def test_innernet_shape(app):
    repo = app()
    plans = plan(manifest(), "test", repo)
    fetch = step(plans, "fetch").actions
    assert [a.name for a in fetch] == ["toolchain-check", "install"]
    assert "'24'" in fetch[0].argv[2]
    assert fetch[1].argv[:3] == ("{toolchain:node}pnpm", "install", "--frozen-lockfile")
    build = step(plans, "build").actions[0]
    assert build.argv[1:] == ("run", "build") and build.outputs == (".next",)
    assert dict(build.env)["NEXT_TELEMETRY_DISABLED"] == "1"
    assert [a.name for a in step(plans, "test").actions] == ["typecheck"]


def test_typecheck_falls_back_to_tsc_and_vitest_writes_junit(app):
    repo = app(scripts={"build": "next build"}, deps={"vitest": "^5"})
    tests = step(plan(manifest(), "test", repo), "test").actions
    assert tests[0].argv[1:] == ("exec", "tsc", "--noEmit")
    assert tests[1].name == "vitest" and tests[1].junit == "{out}/junit/app.vitest.xml"
    assert f"--outputFile.junit={tests[1].junit}" in tests[1].argv


def test_test_script_without_vitest(app):
    repo = app(scripts={"build": "x", "test": "node --test"}, tsconfig=False)
    assert [a.name for a in step(plan(manifest(), "test", repo), "test").actions] == ["test"]


@pytest.mark.parametrize("kw,match", [
    ({"lock": False}, "no pnpm-lock.yaml"),
    ({"scripts": {}, "tsconfig": False}, "no `build` script"),
])
def test_clear_errors(app, kw, match):
    repo = app(**kw)
    files = ["package.json", "app/**"] + (["pnpm-lock.yaml"] if kw.get("lock", True) else [])
    m = manifest()
    m["targets"][0]["srcs"] = files
    with pytest.raises(ContractError, match=match):
        plan(m, "test", repo)


def test_nothing_to_test(app):
    repo = app(scripts={"build": "x"}, tsconfig=False)
    with pytest.raises(ContractError, match="nothing to test"):
        plan(manifest(), "test", repo)


def test_service_and_env_params(app):
    repo = app()
    m = manifest('params = { ready_path = "/api/health", env = { INNERNET_DEMO = "1" } }')
    a = step(plan(m, "deploy", repo), "deploy").actions[0]
    assert a.argv[1:] == ("exec", "next", "start", "-p", "{port}", "-H", "127.0.0.1")
    assert dict(a.env)["INNERNET_DEMO"] == "1" and a.service.ready_path == "/api/health"
    bad = manifest('params = { env = { X = 1 } }')
    with pytest.raises(ContractError, match="params.env"):
        plan(bad, "build", repo)


def test_pinned_toolchain_bin_goes_first_on_path(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path, toolchains={"node": tmp_path / "tc"})
    a = Action(target="t", capability="fetch", name="n", argv=("x",), input_root_digest="sha256:" + "0" * 64,
               toolchains=(("node", "pin"),))
    _, environ, _ = env.command(a)
    assert environ["PATH"].split(":")[0] == str((tmp_path / "tc" / "bin").resolve())
