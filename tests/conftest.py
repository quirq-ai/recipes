import subprocess
import textwrap
from pathlib import Path

import pytest

FAKE = "fake_adapters"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small git repo with two inputs and a manifest using the fake kinds."""
    (tmp_path / "a.txt").write_text("a\n")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "b.txt").write_text("b\n")
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "repo.toml").write_text(textwrap.dedent("""\
        schema = "quirq-repo/1"
        [qq]
        version = "0.1.0"
        [toolchains.sh]
        version = "1"
        source = "https://example.invalid/sh.tar"
        digest = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        [[targets]]
        name = "lib"
        kind = "shell-tool"
        srcs = ["lib/**"]
        [[targets]]
        name = "app"
        kind = "shell-tool"
        srcs = ["a.txt"]
        deps = ["lib"]
        [[targets]]
        name = "docs"
        kind = "docs-only"
        """))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path
