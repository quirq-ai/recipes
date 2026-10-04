"""qqrecipes: list adapters, check them against infra-config, plan and run a goal. Core file.

    qqrecipes kinds [--json]                         every kind with an adapter, and its capabilities
    qqrecipes check-kinds --infra-config DIR         adapters agree with infra-config's kinds.toml
    qqrecipes plan GOAL [--target T]... [--json]     the actions a goal needs, without running them
    qqrecipes execute GOAL [--target T]... [--out DIR] [--toolchain NAME=ROOT]... [--backend local]

GOAL is a capability. The manifest is read through qqsync (default `infra/repo.toml` in --repo).
`execute` is the local stand-in for remote-build's executor (V0-RBE-01) and for `qq build` and
`qq test` (V0-DEP-03); it writes JUnit XML, logs and `results.json` under --out. With GOAL
`deploy`, each service is started in the canary test environment (--backend), probed and torn
down (V0-REC-05); with GOAL `run`, it is started and kept up until interrupted.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from qqsync.errors import ManifestError
from qqsync.manifest import load as load_manifest

from qqrecipes import loader, runner, service
from qqrecipes.contract import CAPABILITIES, ContractError, State
from qqrecipes.plan import plan


def cmd_kinds(args) -> int:
    rows = {k: {c: s.value for c, s in loader.load(k).capabilities().items()} for k in loader.available()}
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for kind, caps in rows.items():
            print(f"{kind}: {' '.join(c for c, s in caps.items() if s == State.IMPLEMENTED)}")
    return 0


def check_kinds(kinds_cfg: dict) -> tuple[list[str], list[str]]:
    """Problems and notes from comparing adapters with infra-config's `kinds` area."""
    problems, notes = [], []
    declared = {k["name"]: k for k in kinds_cfg.get("kind", [])}
    have = set(loader.available())
    for kind in sorted(have - set(declared)):
        problems.append(f"adapter {kind!r} has no kind in infra-config kinds.toml; add it there first")
    for name, k in declared.items():
        if name not in have:
            notes.append(f"{name} ({k['phase']}): no adapter yet")
            continue
        caps = loader.load(name).capabilities()
        implemented = {c for c, s in caps.items() if s is State.IMPLEMENTED}
        listed = set(k["capabilities"])
        if implemented != listed:
            problems.append(
                f"{name}: kinds.toml lists {sorted(listed)} but the adapter implements"
                f" {sorted(implemented)}; change whichever is wrong")
        if k.get("toolchain") != loader.load(name).toolchain:
            problems.append(f"{name}: kinds.toml toolchain {k.get('toolchain')!r} but the adapter"
                            f" runs on {loader.load(name).toolchain!r}")
    return problems, notes


def cmd_check_kinds(args) -> int:
    root = Path(args.infra_config).resolve()
    sys.path.insert(0, str(root / "tools"))
    try:
        import qqcfg  # infra-config's own reader, at the commit the caller checked out
    except ImportError as e:
        print(f"cannot import qqcfg from {root / 'tools'}: {e}", file=sys.stderr)
        return 2
    problems, notes = check_kinds(qqcfg.load(root)["kinds"])
    for n in notes:
        print(f"note: {n}")
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    print("FAIL" if problems else "PASS")
    return 1 if problems else 0


def _plans(args):
    repo = Path(args.repo)
    manifest = load_manifest(Path(args.manifest) if args.manifest else repo / "infra/repo.toml")
    return plan(manifest, args.goal, repo, args.target or None)


def cmd_plan(args) -> int:
    plans = _plans(args)
    if args.json:
        print(json.dumps([{"target": p.target, "kind": p.kind, "capability": p.capability,
                           "state": p.state.value, "actions": [a.to_json() for a in p.actions]}
                          for p in plans], indent=2))
        return 0
    for p in plans:
        print(f"{p.target} [{p.kind}] {p.capability}: {p.state.value}")
        for a in p.actions:
            print(f"  {a.name}: {' '.join(a.argv)}  ({a.digest()[:19]})")
    return 0


def parse_toolchains(values: list[str]) -> dict[str, Path]:
    out = {}
    for v in values:
        name, sep, root = v.partition("=")
        if not sep or not name or not root:
            raise ContractError(f"--toolchain wants NAME=ROOT, got {v!r}")
        out[name] = Path(root)
    return out


def _cancelled(signum, frame):
    raise SystemExit(128 + signum)  # unwinds through deploy teardown, as Ctrl-C does


def cmd_execute(args) -> int:
    signal.signal(signal.SIGTERM, _cancelled)  # a cancelled CI job still tears services down
    plans = _plans(args)
    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve() if args.out else repo / ".qq" / "out"
    adapter_dirs = {}
    for p in plans:
        try:
            adapter_dirs[p.target] = loader.adapter_dir(loader.load(p.kind))
        except ContractError:
            pass  # a single-module adapter; it cannot use {adapter}, and the runner says so if it does
    env = runner.Env(repo=repo, out=out, toolchains=parse_toolchains(args.toolchain),
                     adapter_dirs=adapter_dirs)
    records, failed, skipped = [], False, 0
    try:
        for p in plans:
            if p.state is State.MISSING:
                print(f"-    {p.target} {p.capability}: missing (declared)")
                records.append({"target": p.target, "capability": p.capability, "state": "missing"})
                continue
            for a in p.actions:
                if failed and not args.keep_going:
                    break
                if a.service is not None and a.capability == "deploy" == args.goal:
                    dep = service.deploy_and_probe(a, env, args.backend)
                    failed |= not dep.ok
                    print(f"{'PASS' if dep.ok else 'FAIL'} {a.target} deploy:{a.name} on {args.backend}"
                          f" ({dep.ready_detail}; {sum(p.ok for p in dep.probes)}/{len(dep.probes)} probes;"
                          f" {dep.stopped}){'' if dep.ok else f'  log: {dep.log}'}")
                    records.append({**a.to_json(), "deployment": dep.to_json()})
                    continue
                if a.service is not None and a.capability == "run" == args.goal:
                    failed |= not serve_foreground(a, env, args.backend)
                    continue
                if a.service is not None:
                    print(f"skip {a.target} {a.capability}:{a.name}: a service; start it with deploy or run")
                    skipped += 1
                    continue
                r = runner.run(a, env)
                failed |= not r.ok
                print(f"{'PASS' if r.ok else 'FAIL'} {a.target} {a.capability}:{a.name}"
                      f" ({r.duration_s:.1f}s){'' if r.ok else f'  log: {r.log}'}")
                records.append({**a.to_json(), "exit_code": r.exit_code, "duration_s": round(r.duration_s, 3),
                                "output_digests": r.output_digests, "junit": str(r.junit), "log": str(r.log)})
    finally:  # also on cancel, so a cancelled job still leaves a record
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps(records, indent=2) + "\n")
    if skipped and args.goal in ("run", "deploy"):
        print(f"qqrecipes: {skipped} service action(s) not started", file=sys.stderr)
        return 1
    return 1 if failed else 0


def serve_foreground(action, env, backend: str) -> bool:
    dep = service.start(action, env, backend)
    if not dep.ready:
        print(f"FAIL {action.target} run:{action.name}: {dep.ready_detail}  log: {dep.log}")
        service.stop(dep)
        return False
    print(f"{action.target} is up at {dep.url} (log: {dep.log}); Ctrl-C stops it", flush=True)
    try:
        dep.process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop(dep)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qqrecipes", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kinds")
    k.add_argument("--json", action="store_true")
    k.set_defaults(func=cmd_kinds)
    c = sub.add_parser("check-kinds")
    c.add_argument("--infra-config", required=True, help="a checkout of quirq-ai/infra-config")
    c.set_defaults(func=cmd_check_kinds)
    for name, func in (("plan", cmd_plan), ("execute", cmd_execute)):
        s = sub.add_parser(name)
        s.add_argument("goal", choices=CAPABILITIES)
        s.add_argument("--repo", default=".")
        s.add_argument("--manifest", help="default: REPO/infra/repo.toml")
        s.add_argument("--target", action="append", help="limit to this target (repeatable)")
        s.set_defaults(func=func)
    sub.choices["plan"].add_argument("--json", action="store_true")
    e = sub.choices["execute"]
    e.add_argument("--out", help="results directory (default: REPO/.qq/out)")
    e.add_argument("--toolchain", action="append", default=[], metavar="NAME=ROOT",
                   help="use the toolchain unpacked at ROOT (executables in ROOT/bin); default: PATH")
    e.add_argument("--keep-going", action="store_true", help="run every action even after a failure")
    e.add_argument("--backend", choices=service.BACKENDS, default="local",
                   help="where deploy starts services (v0: this machine, e.g. the CI runner)")
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ManifestError, ContractError, loader.AdapterNotFound, ValueError) as e:
        print(f"qqrecipes: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
