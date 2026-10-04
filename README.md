# recipes

Part of **quirq infra** ("qq"), quirq-ai's CI/CD system for repos in any language. This repo holds
one **adapter** per target kind, found by one loader. An adapter is the only place in quirq infra
that may name a language, a build tool or a test runner.

**Chromium counterpart:** the recipes in `chromium/tools/build` and the `recipes-py` engine that runs
them. As there, the core says *what* to do with a target and the recipe says *how* for its kind.

## How it works (v0)

- A repo's manifest (`infra/repo.toml`, owned and parsed by `quirq-ai/sync`) lists typed targets.
  Each target has a `kind`, such as `python-service`, `pytest` or `node-app`. The list of kinds lives
  in `quirq-ai/infra-config` (`config/kinds.toml`).
- One loader resolves a kind to its adapter. An adapter implements some of the capabilities `fetch`,
  `build`, `test`, `package`, `run`, `deploy`, `bench` and `fuzz`. A capability it does not implement
  is a declared state, not an error: a docs site simply has no `test`.
- A capability turns a target into **actions**, shaped like the REAPI `Action`: a command, an input
  root digest, platform properties and an environment, producing output digests, an exit code and
  test results (JUnit XML). The same action runs locally, on a GitHub Actions runner, or later on a
  remote executor (`quirq-ai/remote-build`).
- The adapters replace the `interim` commands in infra-config's `kinds.toml`.

## The contract

```python
from qqrecipes import loader
from qqrecipes.contract import Adapter, Service

class MyKind(Adapter):                       # qqrecipes/adapters/my_kind.py, for kind "my-kind"
    kind = "my-kind"
    toolchain = "some-toolchain"             # a toolchain name from infra-config kinds.toml
    def build(self, target, ctx):            # one method per capability it implements
        return [self.action(target, ctx, "build", "compile", ["{toolchain:some-toolchain}tool", "build"])]

ADAPTER = MyKind()

loader.load("my-kind").capabilities()     # {"fetch": "missing", "build": "implemented", ...}
```

- **Loader.** `loader.load(kind)` imports `qqrecipes.adapters.<kind with - as _>` and returns its
  `ADAPTER`. Nothing registers adapters: adding a kind adds a module and edits no core file. A kind
  with no module is `AdapterNotFound`; an adapter that fails to import raises, so a broken install
  never looks like a missing kind.
- **Actions.** `Action` carries the command, the input root digest (every file matched by the
  target's `srcs` and its deps' `srcs`), environment, declared outputs, the pins of the toolchains
  it uses, and where it writes JUnit XML. `Action.digest()` is the cache key. Commands hold
  placeholders such as `{toolchain:NAME}` and `{out}` that the executor resolves, so the digest is
  the same on every machine of the same platform. The key also holds the platform and a
  fingerprint of the recipes code. An action on a toolchain the manifest doesn't pin by a real
  digest (absent, or an all-zero placeholder) is never cacheable, and `results.json` marks a run
  not cacheable when it used the tool on PATH because no `--toolchain` root was given. Today every
  pin is a placeholder, so nothing is cacheable yet. Caller settings named `QQ_*` reach a command
  only through the action's env, so they are part of the key.
  A `srcs` glob that matches no file is an error, not an empty input.
- **Results.** Every action leaves JUnit XML. A step that writes none (a typecheck, a build) gets a
  one-case report from its exit code, so the result sink (V0-TST-01) sees every step.
- **Core stays agnostic.** Only `src/qqrecipes/adapters/<kind>` may name a language or tool.
  `tools/agnostic_guard.py` fails CI otherwise, and CI checks that every adapter implements exactly
  the capabilities infra-config's `kinds.toml` lists for its kind.

```sh
qqrecipes kinds                                     # adapters and their capabilities
qqrecipes plan test --repo PATH [--json]            # the actions, without running them
qqrecipes execute test --repo PATH [--toolchain python=ROOT]   # run them here; results in .qq/out
qqrecipes check-kinds --infra-config PATH           # adapters agree with kinds.toml
```

`execute` is a local stand-in until `quirq-ai/remote-build` provides the executor interface
(V0-RBE-01) and `depot` provides `qq build` and `qq test` (V0-DEP-03). Manifests are read only
through `qqsync`, pinned by commit in `pyproject.toml`.

Plan and every v0 item: [quirq-ai/infra-config](https://github.com/quirq-ai/infra-config),
`docs/plan.md` and `docs/v0.md`.

## v0 status

| Item | What | PR | State |
|---|---|---|---|
| V0-REC-01 | Adapter contract and loader | #2 | merged |
| V0-REC-02 | `python-service` and `pytest` adapters | #3 | merged |
| V0-REC-03 | `node-app` adapter (Next.js) | #4 | merged |
| V0-REC-04 | Property tests in `test` | #5 | merged |
| V0-REC-05 | `deploy` to a canary test environment | #6 | merged |

## Adapters

| Kind | Capabilities | Toolchain | Notes |
|---|---|---|---|
| `python-service` | fetch, build, run, deploy | python | venv in `.qq/venv` from the pinned CPython; build byte-compiles srcs; run/deploy emit a service action for `params.entry` listening on `$PORT` (`params.port_env`), which `deploy` starts and probes (V0-REC-05) |
| `pytest` | fetch, test | python | installs `requirements-dev.txt`; writes JUnit XML to `{out}/junit/<target>.pytest.xml` |
| `node-app` | fetch, build, test, run, deploy | node (bundles pnpm) | `pnpm install --frozen-lockfile`; build runs the `build` script; test runs `typecheck` (or `tsc --noEmit`), then vitest with JUnit or the `test` script; run/deploy use `next start` |

**Property tests (V0-REC-04).** Hypothesis (Python) and fast-check (TypeScript) tests run as
ordinary tests in `test`, deterministic and time-boxed: the pytest adapter loads its
`qq_hypothesis` plugin (derandomized, no example database, 100 examples, no per-example deadline,
unless the repo picked its own profile), and the node-app adapter runs vitest with fast-check
configured globally (seed 42, 100 runs, 5 s per property). A property cut short by its time limit
passes with fewer runs, so a slow runner explores less. `QQ_PROPERTY_*` variables override the
bounds (and so change the action key); the test action's timeout bounds the whole run. `tools/check_planted_bug.py` plants an
input-handling bug in an example and checks a property test catches it; CI runs it for both kinds.

**Deploy (V0-REC-05).** `qqrecipes execute deploy` builds each target, starts its service action
on a free port in the canary test environment, waits until its ready path answers (below HTTP 500), runs its HTTP probes
(status below 400 passes) and always tears it down, killing the whole process group. Start and
each probe are JUnit test cases; `results.json` records the deployment. v0's only backend is
`local`: on GitHub, the Actions runner. `qqrecipes execute run` starts a service and keeps it up.
CI deploys and probes both examples, xo-space and innernet.

Each adapter's docstring lists its `params`. `examples/` holds small repos that CI builds and tests
through the adapters, and CI also runs xo-space's pytest suite and innernet's build and typecheck through them.

## Working here

See [AGENTS.md](AGENTS.md). Run the checks with `python -m pytest`.
