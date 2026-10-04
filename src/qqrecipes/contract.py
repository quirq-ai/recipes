"""The adapter contract (plan §5.2): capabilities, actions, and what an adapter promises.

Core file: it names no language, build tool or test runner. Adapters live under
`qqrecipes.adapters` and are the only place that may.

An adapter implements some of the capabilities in CAPABILITIES. Each one it implements is a method
of the same name, `(target, ctx) -> list[Action]`. A capability it does not implement is the
declared state MISSING, never an error: a docs site simply has no `test`.

An Action is shaped like the REAPI `Action`: a command, an input root digest, platform properties
and an environment. Running it yields output digests, an exit code and test results (JUnit XML).
Commands and environment values may hold placeholders that the executor resolves, so the action
digest is the same on every machine:

    {toolchain:NAME}   the toolchain's executable prefix, `<root>/bin/`, or "" when the toolchain
                       is ambient (on PATH; the v0 stand-in until quirq-ai/toolchains publishes it)
    {out}              the absolute results directory for this run
    {repo}             the absolute repo root
    {adapter}          the absolute directory of the adapter's own files; only for an adapter that
                       is a package (`qqrecipes/adapters/<kind>/__init__.py`)
    {port}             the port a service action listens on
"""
from __future__ import annotations

import hashlib
import json
import platform as _platform
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from qqrecipes import digest as _digest

CAPABILITIES = ("fetch", "build", "test", "package", "run", "deploy", "bench", "fuzz")


class State(StrEnum):
    IMPLEMENTED = "implemented"
    MISSING = "missing"  # a declared state: the kind has no such step


# Caller settings named QQ_* (such as property-test bounds) reach an action only through its env, so
# they are part of its key; the executor drops any other QQ_* variable from the environment.
KEYED_ENV_PREFIX = "QQ_"


def is_placeholder_digest(digest) -> bool:
    """An all-zero digest stands in for a toolchain not published yet: it pins nothing."""
    hexpart = str(digest).split(":", 1)[-1]
    return not hexpart or set(hexpart) == {"0"}


def _digests(pin) -> list:
    if isinstance(pin, Mapping):
        return [v for k, v in pin.items() if k == "digest"] + [d for v in pin.values() for d in _digests(v)]
    return []


class ContractError(Exception):
    """An adapter broke the contract. The message names the adapter and what to fix."""


@dataclass(frozen=True)
class Target:
    """One `[[targets]]` entry of a manifest, as read by qqsync."""

    name: str
    kind: str
    srcs: tuple[str, ...] = ()
    outs: tuple[str, ...] = ()
    deps: tuple[str, ...] = ()
    cacheable: bool = True
    params: Mapping = field(default_factory=dict)

    @classmethod
    def from_manifest(cls, entry: Mapping) -> Target:
        return cls(
            name=entry["name"],
            kind=entry["kind"],
            srcs=tuple(entry.get("srcs", ())),
            outs=tuple(entry.get("outs", ())),
            deps=tuple(entry.get("deps", ())),
            cacheable=entry.get("cacheable", True),
            params=dict(entry.get("params", {})),
        )


@dataclass(frozen=True)
class Context:
    """What an adapter may know about the repo when it plans actions."""

    repo: Path
    targets: Mapping[str, Target]
    toolchains: Mapping[str, Mapping] = field(default_factory=dict)  # manifest `[toolchains]`
    env: Mapping[str, str] = field(default_factory=dict)  # the caller's QQ_* settings, keyed into every action

    def input_globs(self, target: Target) -> tuple[str, ...]:
        """The target's own srcs plus those of every target it depends on, transitively."""
        seen: list[str] = []
        stack, visited = [target.name], set()
        while stack:
            name = stack.pop()
            if name in visited:
                continue
            visited.add(name)
            t = self.targets[name]
            seen.extend(g for g in t.srcs if g not in seen)
            stack.extend(t.deps)
        return tuple(seen)

    def toolchain_pin(self, name: str) -> str:
        """A stable string for the toolchain pin, part of every action digest that uses it."""
        pin = self.toolchains.get(name)
        if pin is None:
            return "ambient"
        return json.dumps(pin, sort_keys=True, separators=(",", ":"))

    def toolchain_pinned(self, name: str) -> bool:
        """True only if the manifest pins the toolchain by real digests (none missing or all-zero)."""
        digests = _digests(self.toolchains.get(name))
        return bool(digests) and not any(is_placeholder_digest(d) for d in digests)


@dataclass(frozen=True)
class Service:
    """Marks an action as a long-running service (`run`, `deploy`) and says how to probe it."""

    ready_path: str = "/"
    ready_timeout_s: int = 180
    probes: tuple[str, ...] = ("/",)  # paths that must answer below HTTP 500 once ready


@dataclass(frozen=True)
class Action:
    target: str
    capability: str
    name: str  # a short label within the capability, such as "install" or "typecheck"
    argv: tuple[str, ...]
    input_root_digest: str
    env: tuple[tuple[str, str], ...] = ()
    workdir: str = "."
    outputs: tuple[str, ...] = ()
    junit: str | None = None  # path under {out} where the command writes JUnit XML, if it does
    toolchains: tuple[tuple[str, str], ...] = ()  # (name, pin) of each toolchain the command uses
    adapter: str = ""  # kind@fingerprint of the recipes code that planned it, so a recipe change re-keys
    platform: tuple[tuple[str, str], ...] = ()
    cacheable: bool = True
    timeout_s: int = 1800
    service: Service | None = None

    def key(self) -> dict:
        """What identifies the action: everything but labels. Hash it for the action digest."""
        return {
            "argv": list(self.argv),
            "env": [list(kv) for kv in self.env],
            "workdir": self.workdir,
            "input_root_digest": self.input_root_digest,
            "outputs": list(self.outputs),
            "toolchains": [list(kv) for kv in self.toolchains],
            "platform": [list(kv) for kv in self.platform],
            "adapter": self.adapter,
        }

    def digest(self) -> str:
        blob = json.dumps(self.key(), sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(blob).hexdigest()

    def to_json(self) -> dict:
        return {
            "target": self.target,
            "capability": self.capability,
            "name": self.name,
            "digest": self.digest(),
            **self.key(),
            "junit": self.junit,
            "cacheable": self.cacheable,
            "timeout_s": self.timeout_s,
            "service": None if self.service is None else {
                "ready_path": self.service.ready_path,
                "ready_timeout_s": self.service.ready_timeout_s,
                "probes": list(self.service.probes),
            },
        }


def host_platform() -> tuple[tuple[str, str], ...]:
    """REAPI-style platform properties for this machine."""
    return (("arch", _platform.machine().lower()), ("os", sys.platform))


def recipes_fingerprint() -> str:
    """Digest of every file in the installed qqrecipes package.

    v0 keys every action on all of recipes, so any adapter change re-runs everything.
    TODO(expert): version and pin adapters one by one (plan §5.2) and key on that.
    """
    global _FINGERPRINT
    if _FINGERPRINT is None:
        pkg = Path(__file__).resolve().parent
        rels = [p.relative_to(pkg).as_posix() for p in pkg.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts]
        _FINGERPRINT = _digest.files_digest(pkg, rels)
    return _FINGERPRINT


_FINGERPRINT: str | None = None


@dataclass(frozen=True)
class Plan:
    """One capability of one target: its declared state and, if implemented, its actions."""

    target: str
    kind: str
    capability: str
    state: State
    actions: tuple[Action, ...] = ()


class Adapter:
    """Base class for adapters. Subclasses set `kind` and define capability methods."""

    kind: str = ""
    toolchain: str | None = None  # the infra-config toolchain this kind runs on, if any

    def capabilities(self) -> dict[str, State]:
        return {
            cap: State.IMPLEMENTED if callable(getattr(type(self), cap, None)) else State.MISSING
            for cap in CAPABILITIES
        }

    def plan(self, capability: str, target: Target, ctx: Context) -> Plan:
        if capability not in CAPABILITIES:
            raise ContractError(f"unknown capability {capability!r}; known: {', '.join(CAPABILITIES)}")
        if self.capabilities()[capability] is State.MISSING:
            return Plan(target.name, self.kind, capability, State.MISSING)
        actions = tuple(getattr(self, capability)(target, ctx))
        for a in actions:
            if not isinstance(a, Action) or a.capability != capability or a.target != target.name:
                raise ContractError(
                    f"adapter {self.kind!r} capability {capability!r} returned {a!r}; it must return"
                    f" Actions for target {target.name!r} and capability {capability!r}")
        return Plan(target.name, self.kind, capability, State.IMPLEMENTED, actions)

    def action(self, target: Target, ctx: Context, capability: str, name: str, argv, *,
               env: Mapping[str, str] | None = None, toolchains=(), **kw) -> Action:
        """Build an Action with its input root digest computed from the target's inputs.

        An action on a toolchain the manifest does not pin by a real digest (absent, or a
        placeholder) is never cacheable: its digest cannot say which tool ran it. The executor
        also reports a run as not cacheable when it used the tool on PATH instead of the pinned one.
        """
        names = tuple(toolchains) or ((self.toolchain,) if self.toolchain else ())
        pins = tuple((n, ctx.toolchain_pin(n)) for n in names)
        try:
            input_root = _digest.input_root(ctx.repo, ctx.input_globs(target))
        except _digest.NoMatch as e:
            raise ContractError(f"target {target.name!r} (or a dep): {e}; fix srcs in the manifest") from None
        cacheable = kw.pop("cacheable", target.cacheable) and all(ctx.toolchain_pinned(n) for n in names)
        return Action(
            target=target.name,
            capability=capability,
            name=name,
            argv=tuple(argv),
            input_root_digest=input_root,
            env=tuple(sorted({**ctx.env, **(env or {})}.items())),
            toolchains=pins,
            platform=kw.pop("platform", host_platform()),
            adapter=f"{self.kind}@{recipes_fingerprint()}",
            cacheable=cacheable,
            **kw,
        )
