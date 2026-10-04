"""python-service: a Python server or app run from source on the pinned CPython.

params (all optional):
    requirements  runtime requirements file (default "requirements.txt")
    entry         the script that starts the service (default: the first plain `.py` in srcs)
    port_env      the variable the service reads its port from (default "PORT")
    ready_path    the HTTP path that answers once the service is up (default "/")
    probes        paths a deploy probes (default: [ready_path])
    bench         what `bench` measures: a table with measure ("startup", the default, or
                  "latency"), paths (default: [ready_path]), samples (default 5) and warmup
                  (default 1); see qqrecipes.contract.Bench
"""
from __future__ import annotations

from pathlib import Path

from qqrecipes.adapters import _python
from qqrecipes.contract import Adapter, Bench, ContractError, Service

WILDCARDS = set("*?[")


def compile_roots(repo: Path, srcs) -> list[str]:
    """The `.py` files and top directories named by srcs, for compileall. "." if a glob starts wild."""
    roots: list[str] = []
    for glob in srcs:
        head = glob.removeprefix("./").strip("/").split("/", 1)[0]
        if WILDCARDS & set(head):
            return ["."]
        if (repo / head).is_file() and not head.endswith(".py"):
            continue  # requirements.txt and the like: inputs, but nothing to compile
        if head not in roots:
            roots.append(head)
    return roots or ["."]


class PythonService(Adapter):
    kind = "python-service"
    toolchain = _python.TOOLCHAIN

    def fetch(self, target, ctx):
        return [*_python.venv_actions(self, target, ctx), _python.install(self, target, ctx, "requirements.txt")]

    def build(self, target, ctx):
        # Byte-compile every source: a syntax error anywhere fails the build.
        argv = [_python.VENV_PYTHON, "-m", "compileall", "-q", "-x", r"(^|/)(\.qq|\.git|venv|\.venv)/",
                *compile_roots(Path(ctx.repo), target.srcs)]
        return [self.action(target, ctx, "build", "compileall", argv)]

    def _service(self, target, ctx, capability, bench=None):
        entry = target.params.get("entry") or next(
            (s for s in target.srcs if s.endswith(".py") and not WILDCARDS & set(s)), None)
        if not entry:
            raise ContractError(f"target {target.name!r} (python-service): no entry script; set params.entry")
        ready = str(target.params.get("ready_path", "/"))
        probes = target.params.get("probes", [ready])
        if not isinstance(probes, list) or not all(isinstance(p, str) for p in probes):
            raise ContractError(f"target {target.name!r} (python-service): params.probes must be a list of paths")
        probes = tuple(probes)
        env = {str(target.params.get("port_env", "PORT")): "{port}", "PYTHONUNBUFFERED": "1"}
        return [self.action(target, ctx, capability, "serve", [_python.VENV_PYTHON, entry], env=env,
                            cacheable=False, service=Service(ready_path=ready, probes=probes), bench=bench)]

    def run(self, target, ctx):
        return self._service(target, ctx, "run")

    def deploy(self, target, ctx):
        return self._service(target, ctx, "deploy")

    def bench(self, target, ctx):
        spec = Bench.from_params(target, measure="startup", path=str(target.params.get("ready_path", "/")))
        return self._service(target, ctx, "bench", bench=spec)


ADAPTER = PythonService()
