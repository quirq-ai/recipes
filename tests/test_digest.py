import pytest

from qqrecipes import digest


@pytest.mark.parametrize("pattern,path,hit", [
    ("a.txt", "a.txt", True),
    ("a.txt", "b/a.txt", False),
    ("*.ts", "x.ts", True),
    ("*.ts", "app/x.ts", False),
    ("app/**", "app/x/y.ts", True),
    ("app/**", "apps/x", False),
    ("**/*.md", "README.md", True),
    ("**/*.md", "docs/a/b.md", True),
    (".next/", ".next/static/x.js", True),
    ("lib", "lib/b.txt", True),
    ("l?b/*", "lib/b.txt", True),
])
def test_matches(pattern, path, hit):
    assert digest.matches(pattern, path) is hit


def test_list_files_skips_git_and_qq_and_ignored(repo):
    (repo / ".gitignore").write_text("ignored/\n")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "x").write_text("x")
    (repo / ".qq").mkdir()
    (repo / ".qq" / "y").write_text("y")
    files = digest.list_files(repo)
    assert "a.txt" in files and "lib/b.txt" in files
    assert not any(f.startswith((".git/", ".qq/", "ignored/")) for f in files)


def test_list_files_without_git(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f").write_text("f")
    (tmp_path / ".qq").mkdir()
    (tmp_path / ".qq" / "g").write_text("g")
    assert digest.list_files(tmp_path) == ["d/f"]


def test_input_root_is_stable_and_content_addressed(repo):
    a = digest.input_root(repo, ["lib/**"])
    assert a == digest.input_root(repo, ["lib/**"])
    assert a.startswith("sha256:") and len(a) == 71
    (repo / "lib" / "b.txt").write_text("other\n")
    assert digest.input_root(repo, ["lib/**"]) != a


def test_path_digest(tmp_path):
    assert digest.path_digest(tmp_path / "missing") is None
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f").write_text("f")
    assert digest.path_digest(tmp_path / "d").startswith("sha256:")
    assert digest.path_digest(tmp_path / "d" / "f").startswith("sha256:")


def test_dot_slash_and_brackets():
    assert digest.matches("./src/**", "src/a.py")
    assert digest.matches("src/[ab].py", "src/b.py") and not digest.matches("src/[ab].py", "src/c.py")
    assert digest.matches("src/[!a].py", "src/c.py") and not digest.matches("src/[!a].py", "src/a.py")


def test_glob_matching_nothing_is_an_error(repo):
    with pytest.raises(digest.NoMatch, match="'nope/\\*\\*'"):
        digest.input_root(repo, ["lib/**", "nope/**"])


def test_list_files_from_a_subdirectory_of_a_checkout(repo):
    (repo / ".gitignore").write_text("lib/ignored\n")
    (repo / "lib" / "ignored").write_text("x")
    assert digest.list_files(repo / "lib") == ["b.txt"]
