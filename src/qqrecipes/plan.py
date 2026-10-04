"""From a manifest and a goal to an ordered list of Plans. Core file: names no language or tool.

A goal is a capability. Reaching it runs `fetch` and `build` for every target the selected ones
depend on, then the goal capability on the selected targets, stage by stage in dependency order.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from qqrecipes import loader
from qqrecipes.contract import CAPABILITIES, Context, ContractError, Plan, Target

PREPARE = ("fetch", "build")


def stages(goal: str) -> tuple[str, ...]:
    if goal not in CAPABILITIES:
        raise ContractError(f"unknown goal {goal!r}; a goal is one of: {', '.join(CAPABILITIES)}")
    if goal in PREPARE:
        return PREPARE[: PREPARE.index(goal) + 1]
    return PREPARE + (goal,)


def context(manifest: Mapping, repo: Path) -> Context:
    targets = {t["name"]: Target.from_manifest(t) for t in manifest.get("targets", [])}
    return Context(repo=Path(repo).resolve(), targets=targets, toolchains=manifest.get("toolchains", {}))


def order(ctx: Context, selected: Iterable[str] | None = None) -> list[str]:
    """Selected targets and their transitive deps, dependencies first. qqsync rejects cycles."""
    names = list(selected) if selected is not None else list(ctx.targets)
    unknown = [n for n in names if n not in ctx.targets]
    if unknown:
        raise ContractError(f"no target named {', '.join(map(repr, unknown))}; the manifest has"
                            f" {', '.join(ctx.targets) or 'no targets'}")
    out: list[str] = []

    def visit(name: str) -> None:
        if name in out:
            return
        for dep in ctx.targets[name].deps:
            visit(dep)
        out.append(name)

    for n in names:
        visit(n)
    return out


def plan(manifest: Mapping, goal: str, repo: Path, selected: Iterable[str] | None = None,
         package: str | None = None) -> list[Plan]:
    ctx = context(manifest, repo)
    chosen = list(dict.fromkeys(selected)) if selected is not None else list(ctx.targets)
    closure = order(ctx, chosen)  # manifest order where deps allow, so plans are deterministic
    plans: list[Plan] = []
    for stage in stages(goal):
        for name in closure:
            if stage not in PREPARE and name not in chosen:
                continue
            target = ctx.targets[name]
            plans.append(loader.load(target.kind, package).plan(stage, target, ctx))
    return plans
