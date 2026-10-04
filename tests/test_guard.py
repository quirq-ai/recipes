import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("agnostic_guard", ROOT / "tools" / "agnostic_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_core_names_no_language_or_tool():
    assert guard.check(ROOT) == []


def test_guard_catches_a_named_tool_and_an_adapter_import(tmp_path):
    core = tmp_path / "src" / "qqrecipes"
    (core / "adapters" / "some_kind").mkdir(parents=True)
    (core / "adapters" / "__init__.py").write_text("")
    (core / "adapters" / "some_kind" / "__init__.py").write_text("RUN = 'pnpm install'\n")
    (core / "bad.py").write_text("# runs pytest\nfrom qqrecipes.adapters import some_kind\n")
    (core / "fine.py").write_text("# a pipeline; next step\n")
    hits = guard.check(tmp_path)
    assert len(hits) == 2
    assert "bad.py:1: names 'pytest'" in hits[0] and "imports qqrecipes.adapters.some_kind" in hits[1]
