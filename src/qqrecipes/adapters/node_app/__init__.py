"""node-app: a Next.js app managed with pnpm, on the pinned Node toolchain (which bundles pnpm).

Steps come from package.json: `build` runs the `build` script; `test` runs the `typecheck` script
(or `tsc --noEmit` when there is a tsconfig.json but no such script), then the `test` script if
there is one. A test runner that writes JUnit gets it under {out}; vitest is wired automatically.

params (all optional):
    dir           the app directory, relative to the repo root (default ".")
    port_flag     how `next start` takes the port (default "-p")
    ready_path    the HTTP path that answers once the app is up (default "/")
    probes        paths a deploy probes (default: [ready_path])
    env           extra environment for build, test and run, a table of strings
"""
from __future__ import annotations

import json
from pathlib import Path

from qqrecipes.contract import Adapter, ContractError, Service

TOOLCHAIN = "node"
PNPM = "{toolchain:node}pnpm"
NODE = "{toolchain:node}node"
BASE_ENV = {"CI": "1", "NEXT_TELEMETRY_DISABLED": "1"}


class NodeApp(Adapter):
    kind = "node-app"
    toolchain = TOOLCHAIN

    def _app(self, target, ctx) -> tuple[str, dict]:
        app = str(target.params.get("dir", "."))
        path = Path(ctx.repo) / app / "package.json"
        try:
            package = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            raise ContractError(f"target {target.name!r} (node-app): no package.json in {app!r}") from None
        except json.JSONDecodeError as e:
            raise ContractError(f"target {target.name!r} (node-app): {path.name} is not JSON: {e}") from None
        return app, package

    def _env(self, target, **extra) -> dict:
        env = dict(BASE_ENV)
        user = target.params.get("env", {})
        if not isinstance(user, dict) or not all(isinstance(v, str) for v in user.values()):
            raise ContractError(f"target {target.name!r} (node-app): params.env must be a table of strings")
        env.update(user)
        env.update(extra)
        return env

    def fetch(self, target, ctx):
        app, _ = self._app(target, ctx)
        actions = []
        major = str(ctx.toolchains.get(TOOLCHAIN, {}).get("version", "")).split(".")[0]
        if major.isdigit():
            # TODO(expert): check the full version and digest once quirq-ai/toolchains publishes
            # Node (V0-TCH-02); until then CI provides it with actions/setup-node at this pin.
            check = (f"const m = process.versions.node.split('.')[0];"
                     f" if (m !== '{major}') {{ console.error('pinned Node {major}, found ' + m); process.exit(1); }}")
            actions.append(self.action(target, ctx, "fetch", "toolchain-check", [NODE, "-e", check], workdir=app))
        if not (Path(ctx.repo) / app / "pnpm-lock.yaml").is_file():
            raise ContractError(f"target {target.name!r} (node-app): no pnpm-lock.yaml in {app!r};"
                                " commit one so installs are pinned")
        # pnpm 11 refuses unapproved dependency build scripts; skip them with a warning, as pnpm 10
        # did, matching the toolchain's own smoke test. TODO(expert): repos list approved builds.
        actions.append(self.action(target, ctx, "fetch", "install",
                                   [PNPM, "install", "--frozen-lockfile", "--config.strict-dep-builds=false"],
                                   workdir=app, env={"CI": "1"}, cacheable=False))
        return actions

    def build(self, target, ctx):
        app, package = self._app(target, ctx)
        if "build" not in package.get("scripts", {}):
            raise ContractError(f"target {target.name!r} (node-app): package.json has no `build` script")
        return [self.action(target, ctx, "build", "build", [PNPM, "run", "build"], workdir=app,
                            env=self._env(target), outputs=tuple(target.outs) or (".next",))]

    def test(self, target, ctx):
        app, package = self._app(target, ctx)
        scripts = package.get("scripts", {})
        deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        actions = []
        if "typecheck" in scripts:
            actions.append(self.action(target, ctx, "test", "typecheck", [PNPM, "run", "typecheck"],
                                       workdir=app, env=self._env(target)))
        elif (Path(ctx.repo) / app / "tsconfig.json").is_file():
            actions.append(self.action(target, ctx, "test", "typecheck", [PNPM, "exec", "tsc", "--noEmit"],
                                       workdir=app, env=self._env(target)))
        if "vitest" in deps:
            junit = f"{{out}}/junit/{target.name}.vitest.xml"
            actions.append(self.action(
                target, ctx, "test", "vitest",
                [PNPM, "exec", "vitest", "run", "--reporter=default", "--reporter=junit",
                 f"--outputFile.junit={junit}"], workdir=app, env=self._env(target), junit=junit))
        elif "test" in scripts:
            actions.append(self.action(target, ctx, "test", "test", [PNPM, "run", "test"], workdir=app,
                                       env=self._env(target)))
        if not actions:
            raise ContractError(f"target {target.name!r} (node-app): nothing to test; add a `typecheck`"
                                " or `test` script, or a tsconfig.json")
        return actions

    def _service(self, target, ctx, capability):
        app, _ = self._app(target, ctx)
        ready = str(target.params.get("ready_path", "/"))
        probes = tuple(target.params.get("probes", [ready]))
        argv = [PNPM, "exec", "next", "start", str(target.params.get("port_flag", "-p")), "{port}",
                "-H", "127.0.0.1"]
        return [self.action(target, ctx, capability, "serve", argv, workdir=app,
                            env=self._env(target, PORT="{port}"), cacheable=False,
                            service=Service(ready_path=ready, probes=probes))]

    def run(self, target, ctx):
        return self._service(target, ctx, "run")

    def deploy(self, target, ctx):
        return self._service(target, ctx, "deploy")


ADAPTER = NodeApp()
