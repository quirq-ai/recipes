# Agent guide

How an agent changes this repo safely. Read `README.md` first.

- Every change is a pull request against `main`, titled with its work item id (for example
  `V0-REC-02: ...`). It lands only with the `presubmit` check green.
- Only adapters (`src/qqrecipes/adapters/<kind>`) may name a language, build tool, test runner or
  deploy target. Every other module under `src/qqrecipes` is core and stays agnostic;
  `tools/agnostic_guard.py` enforces it in CI. Tests and docs may name tools.
- Manifests are read only through `quirq-ai/sync` (`qqsync`). Never parse `infra/repo.toml` here.
- `.github/CODEOWNERS` names suraj (`@sharmasuraj0123`) as owner of the policy and trust paths;
  owner names are his call, so never change them. Leave any other `owners` list empty.
- Mark a decision you cannot make with a one-line `TODO(suraj):` or `TODO(expert):`.
- This repo is public: no secrets, tokens or internal hostnames.
- GitHub-specific code stays behind a `backend` field (`github` now, `launchpad` later).
- Use other qq repos by pinned commit, never by copying their code.
