# Agent guide

How an agent changes this repo safely. Read `README.md` first.

- Every change is a pull request against `main`, titled with its work item id (for example
  `V0-REC-02: ...`). It lands only with the `presubmit` check green.
- Only files under the adapters tree may name a language, build tool, test runner or deploy target.
  Everything else is core and stays agnostic; a CI guard (V0-REC-01) enforces it.
- Manifests are read only through `quirq-ai/sync` (`qqsync`). Never parse `infra/repo.toml` here.
- Leave `.github/CODEOWNERS` and any `owners` list empty; suraj assigns people.
- Mark a decision you cannot make with a one-line `TODO(suraj):` or `TODO(expert):`.
- This repo is public: no secrets, tokens or internal hostnames.
- GitHub-specific code stays behind a `backend` field (`github` now, `launchpad` later).
- Use other qq repos by pinned commit, never by copying their code.
