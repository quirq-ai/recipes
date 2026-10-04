import pytest

from qqrecipes import loader
from qqrecipes.contract import CAPABILITIES, ContractError, State

FAKE = "fake_adapters"


def test_resolves_a_kind_to_its_adapter():
    adapter = loader.load("shell-tool", FAKE)
    assert adapter.kind == "shell-tool"


def test_lists_kinds_but_not_helpers():
    assert loader.available(FAKE) == ["broken", "docs-only", "shell-tool", "wrong-kind"]


def test_missing_kind_is_adapter_not_found_with_known_kinds():
    with pytest.raises(loader.AdapterNotFound) as e:
        loader.load("no-such-kind", FAKE)
    assert "no_such_kind" in str(e.value) and "shell-tool" in str(e.value)


def test_broken_adapter_fails_loudly():
    with pytest.raises(ModuleNotFoundError) as e:
        loader.load("broken", FAKE)
    assert e.value.name == "qq_module_that_does_not_exist"


def test_adapter_must_match_its_kind():
    with pytest.raises(ContractError, match="must be 'wrong-kind'"):
        loader.load("wrong-kind", FAKE)


def test_rejects_names_that_are_not_kinds():
    with pytest.raises(ContractError):
        loader.load("../etc", FAKE)


def test_missing_capability_is_a_declared_state():
    caps = loader.load("docs-only", FAKE).capabilities()
    assert list(caps) == list(CAPABILITIES)
    assert caps["build"] is State.IMPLEMENTED
    assert {c for c, s in caps.items() if s is State.MISSING} == set(CAPABILITIES) - {"build"}


def test_real_adapters_tree_loads():
    for kind in loader.available():
        assert loader.load(kind).kind == kind


def test_adapter_dir_only_for_package_adapters():
    with pytest.raises(ContractError, match="single module"):
        loader.adapter_dir(loader.load("shell-tool", FAKE))
