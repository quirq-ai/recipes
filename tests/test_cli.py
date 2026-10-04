import json

from qqrecipes import cli, loader


def use_fake(monkeypatch):
    monkeypatch.setattr(loader, "PACKAGE", "fake_adapters")


def test_execute_runs_the_goal_and_writes_results(repo, monkeypatch, capsys):
    use_fake(monkeypatch)
    assert cli.main(["execute", "build", "--repo", str(repo), "--target", "app"]) == 0
    records = json.loads((repo / ".qq/out/results.json").read_text())
    builds = [r for r in records if r.get("capability") == "build"]
    assert [r["target"] for r in builds] == ["lib", "app"]
    assert builds[0]["output_digests"]["out"].startswith("sha256:")


def test_execute_fails_on_a_failing_test(repo, monkeypatch, capsys):
    use_fake(monkeypatch)
    text = (repo / "infra/repo.toml").read_text().replace(
        'srcs = ["a.txt"]', 'srcs = ["a.txt"]\nparams = { test = "exit 1" }')
    (repo / "infra/repo.toml").write_text(text)
    assert cli.main(["execute", "test", "--repo", str(repo)]) == 1
    assert "FAIL app test:check" in capsys.readouterr().out


def test_plan_json_shows_declared_missing(repo, monkeypatch, capsys):
    use_fake(monkeypatch)
    assert cli.main(["plan", "test", "--repo", str(repo), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {"target": "docs", "capability": "test", "state": "missing"}.items() <= next(
        r for r in rows if r["target"] == "docs" and r["capability"] == "test").items()


def test_bad_manifest_is_a_clear_error(tmp_path, capsys):
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra/repo.toml").write_text('schema = "nope"\n')
    assert cli.main(["plan", "build", "--repo", str(tmp_path)]) == 1
    assert "qqrecipes:" in capsys.readouterr().err


def test_check_kinds(monkeypatch):
    use_fake(monkeypatch)
    cfg = {"kind": [
        {"name": "shell-tool", "phase": "year-one", "capabilities": ["fetch", "build", "test", "run"],
         "toolchain": "sh"},
        {"name": "docs-only", "phase": "year-one", "capabilities": ["build", "deploy"]},
        {"name": "later-kind", "phase": "later", "capabilities": ["build"]},
    ]}
    monkeypatch.setattr(loader, "available", lambda package=None: ["docs-only", "shell-tool"])
    problems, notes = cli.check_kinds(cfg)
    assert notes == ["later-kind (later): no adapter yet"]
    assert len(problems) == 1 and problems[0].startswith("docs-only:")
