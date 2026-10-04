"""Run actions on this machine. Core file: names no language or tool.

The v0 stand-in for the executor interface, which quirq-ai/remote-build owns (V0-RBE-01): it runs
one Action as a subprocess and returns an ActionResult. Every action leaves JUnit XML behind. One
whose command writes its own (`Action.junit`) keeps it; any other gets one test case per action,
so a typecheck or a build step is a result like any test.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from qqrecipes import digest
from qqrecipes.contract import Action

PLACEHOLDER = re.compile(r"\{(toolchain:[a-z0-9][a-z0-9._-]*|out|repo|adapter|port)\}")


@dataclass(frozen=True)
class Env:
    """Where this run happens: resolves the placeholders an Action may hold."""

    repo: Path
    out: Path
    toolchains: Mapping[str, Path | None] = field(default_factory=dict)  # None or absent: ambient
    adapter_dirs: Mapping[str, Path] = field(default_factory=dict)  # target name -> adapter dir
    port: int | None = None

    def resolve(self, text: str, target: str) -> str:
        def sub(m: re.Match) -> str:
            key = m.group(1)
            if key.startswith("toolchain:"):
                root = self.toolchains.get(key.split(":", 1)[1])
                return f"{Path(root).resolve()}/bin/" if root else ""
            if key == "out":
                return str(self.out.resolve())
            if key == "repo":
                return str(self.repo.resolve())
            if key == "adapter":
                if target not in self.adapter_dirs:
                    raise ValueError(f"{{adapter}} used by target {target!r}, whose adapter is not a package")
                return str(self.adapter_dirs[target])
            if self.port is None:
                raise ValueError("{port} used by an action that is not a service")
            return str(self.port)
        return PLACEHOLDER.sub(sub, text)

    def command(self, action: Action) -> tuple[list[str], dict[str, str], Path]:
        argv = [self.resolve(a, action.target) for a in action.argv]
        env = dict(os.environ)  # TODO(expert): pass an allowlist, as REAPI does, for hermeticity
        env.update({k: self.resolve(v, action.target) for k, v in action.env})
        cwd = (self.repo / action.workdir).resolve()
        return argv, env, cwd


@dataclass(frozen=True)
class ActionResult:
    action_digest: str
    exit_code: int
    duration_s: float
    output_digests: dict[str, str | None]
    junit: Path
    log: Path

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def slug(action: Action) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{action.target}.{action.capability}.{action.name}")


def run(action: Action, env: Env) -> ActionResult:
    out = env.out.resolve()
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "junit").mkdir(parents=True, exist_ok=True)
    log = out / "logs" / f"{slug(action)}.log"
    argv, environ, cwd = env.command(action)
    stale = junit_path(action, env)
    if stale is not None:
        stale.unlink(missing_ok=True)  # never report an earlier run's results as this one's
    started = time.monotonic()
    with open(log, "wb") as f:
        try:
            code = subprocess.run(argv, cwd=cwd, env=environ, stdout=f, stderr=subprocess.STDOUT,
                                  timeout=action.timeout_s, check=False).returncode
        except subprocess.TimeoutExpired:
            f.write(f"\nqq: timed out after {action.timeout_s}s\n".encode())
            code = 124
        except OSError as e:
            f.write(f"\nqq: could not start {argv[0]!r}: {e.strerror or e}\n".encode())
            code = 127
    duration = time.monotonic() - started
    outputs = {o: digest.path_digest(cwd / o) for o in action.outputs}
    junit = native_junit(action, env)
    if junit is None or (code != 0 and not junit_has_failures(junit)):
        junit = write_junit(action, code, duration, log, out / "junit" / f"{slug(action)}.xml")
    return ActionResult(action.digest(), code, duration, outputs, junit, log)


def junit_path(action: Action, env: Env) -> Path | None:
    """Where the action writes JUnit; a relative path is under {out}."""
    if not action.junit:
        return None
    path = Path(env.resolve(action.junit, action.target))
    return path if path.is_absolute() else env.out.resolve() / path


def native_junit(action: Action, env: Env) -> Path | None:
    path = junit_path(action, env)
    return path if path is not None and path.is_file() else None


def junit_has_failures(path: Path) -> bool:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return False
    return any(el.tag in ("failure", "error") for el in root.iter())


def write_junit(action: Action, code: int, duration: float, log: Path, path: Path) -> Path:
    suite = ET.Element("testsuite", name=action.target, tests="1",
                       failures="0" if code == 0 else "1", time=f"{duration:.3f}")
    case = ET.SubElement(suite, "testcase", classname=action.target,
                         name=f"{action.capability}:{action.name}", time=f"{duration:.3f}")
    if code != 0:
        tail = log.read_text(errors="replace")[-8000:]
        failure = ET.SubElement(case, "failure", message=f"exit code {code}")
        failure.text = tail
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
    return path
