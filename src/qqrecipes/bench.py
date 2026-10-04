"""Run a `bench` action: start its service, measure, tear it down (V0-PRF-01). Core file: names no
language or tool.

A bench action is a service action with a `Bench` spec. `startup` starts the service again for
each sample and times how long its ready path takes to answer; `latency` starts it once and times
GETs of the listed paths. Every sample is kept raw, next to a few summary metrics, each with its
unit. The result is `{out}/bench/<action>.json` and one JUnit test case, so a broken benchmark is
a failed step like any other. quirq-ai/perf turns the JSON into stored Results.
TODO(expert): CPU pinning and repeated runs to tame shared-runner noise; v0 records the runner type.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from qqrecipes import service
from qqrecipes.contract import Action
from qqrecipes.runner import Env, slug

POLL_S = 0.02  # readiness polling while timing a start; the default 0.5s would swamp the number


@dataclass
class BenchResult:
    action: Action
    ok: bool = False
    detail: str = ""
    samples: list[float] = field(default_factory=list)
    unit: str = ""
    metrics: dict[str, dict] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        b = self.action.bench
        return {
            "target": self.action.target, "name": self.action.name, "measure": b.measure,
            "paths": list(b.paths), "ok": self.ok, "detail": self.detail, "unit": self.unit,
            "samples": self.samples, "metrics": self.metrics, "logs": self.logs,
            "action_digest": self.action.digest(),
        }


def nearest_rank(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[max(math.ceil(pct / 100 * len(ordered)) - 1, 0)]


def summarize(name: str, samples: list[float], unit: str) -> dict[str, dict]:
    return {
        f"{name}_p50": {"value": round(statistics.median(samples), 4), "unit": unit},
        f"{name}_p90": {"value": round(nearest_rank(samples, 90), 4), "unit": unit},
        f"{name}_min": {"value": round(min(samples), 4), "unit": unit},
        f"{name}_max": {"value": round(max(samples), 4), "unit": unit},
        f"{name}_samples": {"value": len(samples), "unit": "count"},
    }


def _startup(res: BenchResult, env: Env, backend: str) -> None:
    b = res.action.bench
    for i in range(b.warmup + b.samples):
        started = time.monotonic()
        dep = service.start(res.action, env, backend, poll_s=POLL_S)
        took = time.monotonic() - started
        try:
            res.logs.append(str(dep.log))
            if not dep.ready:
                res.detail = f"start {i + 1}: {dep.ready_detail}"
                return
        finally:
            service.stop(dep)
        if i >= b.warmup:
            res.samples.append(took)
    res.unit = "s"
    res.metrics = summarize("startup", res.samples, "s")
    res.ok, res.detail = True, f"{b.samples} start(s), p50 {res.metrics['startup_p50']['value']}s"


def _latency(res: BenchResult, env: Env, backend: str) -> None:
    b = res.action.bench
    dep = service.start(res.action, env, backend)
    res.logs.append(str(dep.log))
    try:
        if not dep.ready:
            res.detail = dep.ready_detail
            return
        for i in range(b.warmup + b.samples):
            for path in b.paths:
                started = time.monotonic()
                status, detail = service.get(dep.url + path)
                took_ms = (time.monotonic() - started) * 1000
                if status is None or status >= 400:
                    res.detail = f"GET {path} answered {status if status is not None else detail}"
                    return
                if i >= b.warmup:
                    res.samples.append(took_ms)
    finally:
        service.stop(dep)
    res.unit = "ms"
    res.metrics = summarize("latency", res.samples, "ms")
    res.ok = True
    res.detail = (f"{len(res.samples)} request(s) over {len(b.paths)} path(s),"
                  f" p50 {res.metrics['latency_p50']['value']}ms")


def run(action: Action, env: Env, backend: str = "local") -> BenchResult:
    if action.service is None or action.bench is None:
        raise ValueError(f"{action.target} {action.capability}:{action.name} is not a bench action")
    res = BenchResult(action)
    (_startup if action.bench.measure == "startup" else _latency)(res, env, backend)
    out = env.out.resolve()
    (out / "bench").mkdir(parents=True, exist_ok=True)
    (out / "bench" / f"{slug(action)}.json").write_text(json.dumps(res.to_json(), indent=2) + "\n")
    write_junit(res, out / "junit" / f"{slug(action)}.xml")
    return res


def write_junit(res: BenchResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    a = res.action
    suite = ET.Element("testsuite", name=a.target, tests="1", failures="0" if res.ok else "1")
    case = ET.SubElement(suite, "testcase", classname=a.target, name=f"bench:{a.bench.measure}")
    if not res.ok:
        failure = ET.SubElement(case, "failure", message=res.detail)
        log = Path(res.logs[-1]) if res.logs else None
        failure.text = log.read_text(errors="replace")[-8000:] if log and log.exists() else ""
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
    return path
