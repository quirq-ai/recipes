import pytest
from qqsync.manifest import load as load_manifest

from qqrecipes import plan as qplan
from qqrecipes.contract import ContractError, State

FAKE = "fake_adapters"


def plans(repo, goal, selected=None):
    return qplan.plan(load_manifest(repo / "infra/repo.toml"), goal, repo, selected, package=FAKE)


def test_stages():
    assert qplan.stages("fetch") == ("fetch",)
    assert qplan.stages("build") == ("fetch", "build")
    assert qplan.stages("test") == ("fetch", "build", "test")
    with pytest.raises(ContractError):
        qplan.stages("ship")


def test_test_goal_orders_stages_then_deps(repo):
    got = [(p.target, p.capability, p.state) for p in plans(repo, "test")]
    assert got == [
        ("lib", "fetch", State.IMPLEMENTED), ("app", "fetch", State.IMPLEMENTED),
        ("docs", "fetch", State.MISSING),
        ("lib", "build", State.IMPLEMENTED), ("app", "build", State.IMPLEMENTED),
        ("docs", "build", State.IMPLEMENTED),
        ("lib", "test", State.IMPLEMENTED), ("app", "test", State.IMPLEMENTED),
        ("docs", "test", State.MISSING),
    ]


def test_selected_target_prepares_its_deps_but_tests_only_itself(repo):
    got = [(p.target, p.capability) for p in plans(repo, "test", ["app"])]
    assert got == [("lib", "fetch"), ("app", "fetch"), ("lib", "build"), ("app", "build"), ("app", "test")]


def test_unknown_target(repo):
    with pytest.raises(ContractError, match="no target named 'nope'"):
        plans(repo, "build", ["nope"])


def test_input_root_covers_deps_and_tracks_content(repo):
    def app_build():
        return next(p for p in plans(repo, "build") if p.target == "app" and p.capability == "build")
    before = app_build().actions[0]
    (repo / "lib" / "b.txt").write_text("changed\n")
    after = app_build().actions[0]
    assert before.input_root_digest != after.input_root_digest
    assert before.digest() != after.digest()


def test_action_digest_includes_toolchain_pin(repo):
    a = next(p for p in plans(repo, "fetch") if p.target == "lib").actions[0]
    assert a.toolchains[0][0] == "sh" and "sha256:5ca1ab1e" in a.toolchains[0][1]


def test_ambient_toolchain_is_not_cacheable_and_platform_and_adapter_are_keyed(repo):
    ps = plans(repo, "build")
    pinned = next(p for p in ps if p.target == "lib" and p.capability == "fetch").actions[0]
    assert pinned.cacheable
    key = pinned.key()
    assert dict(key["platform"])["os"] and key["adapter"].startswith("shell-tool@sha256:")
    text = (repo / "infra/repo.toml").read_text()
    start = text.index("[toolchains.sh]")
    (repo / "infra/repo.toml").write_text(text[:start] + text[text.index("[[targets]]"):])
    ambient = next(p for p in plans(repo, "fetch") if p.target == "lib").actions[0]
    assert ambient.toolchains == (("sh", "ambient"),) and not ambient.cacheable


def test_srcs_matching_nothing_is_a_contract_error(repo):
    text = (repo / "infra/repo.toml").read_text().replace('srcs = ["a.txt"]', 'srcs = ["a.txt", "missing/**"]')
    (repo / "infra/repo.toml").write_text(text)
    with pytest.raises(ContractError, match="'missing/\\*\\*' match no file"):
        plans(repo, "build")


def test_placeholder_digest_is_not_cacheable(repo):
    text = (repo / "infra/repo.toml").read_text().replace("5ca1ab1e" + "0" * 55 + "1", "0" * 64)
    (repo / "infra/repo.toml").write_text(text)
    a = next(p for p in plans(repo, "fetch") if p.target == "lib").actions[0]
    assert a.toolchains[0][0] == "sh" and not a.cacheable


def test_qq_settings_are_keyed_into_actions(repo, monkeypatch):
    before = next(p for p in plans(repo, "fetch") if p.target == "lib").actions[0]
    monkeypatch.setenv("QQ_PROPERTY_EXAMPLES", "7")
    monkeypatch.setenv("QQ_TOKEN", "secret")
    after = next(p for p in plans(repo, "fetch") if p.target == "lib").actions[0]
    assert dict(after.env)["QQ_PROPERTY_EXAMPLES"] == "7" and "QQ_TOKEN" not in dict(after.env)
    assert before.digest() != after.digest()
