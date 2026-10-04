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

Plan and every v0 item: [quirq-ai/infra-config](https://github.com/quirq-ai/infra-config),
`docs/plan.md` and `docs/v0.md`.

## v0 status

| Item | What | PR | State |
|---|---|---|---|
| V0-REC-01 | Adapter contract and loader | | not started |
| V0-REC-02 | `python-service` and `pytest` adapters | | not started |
| V0-REC-03 | `node-app` adapter (Next.js) | | not started |
| V0-REC-04 | Property tests in `test` | | not started |
| V0-REC-05 | `deploy` to a canary test environment | | not started |

## Working here

See [AGENTS.md](AGENTS.md). Run the checks with `python -m pytest`.
