"""Deploy a service action to a canary test environment, probe it, tear it down (V0-REC-05).
Core file: names no language or tool.

v0's environment is the machine running the canary: on GitHub that is the Actions runner, so the
`local` backend serves both. A deployment starts the built artifact with the adapter's service
action on a free port, waits until its ready path answers, runs HTTP probes against it, and always
tears it down (the whole process group). Every step is a JUnit test case.
TODO(expert): a `launchpad` backend for persistent canary environments (v1).
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from qqrecipes.contract import Action
from qqrecipes.runner import Env, slug

BACKENDS = ("local",)
HOST = "127.0.0.1"


@dataclass
class Probe:
    path: str
    status: int | None
    ok: bool
    detail: str
    duration_s: float


@dataclass
class Deployment:
    action: Action
    backend: str
    url: str
    log: Path
    ready: bool = False
    ready_detail: str = ""
    probes: list[Probe] = field(default_factory=list)
    stopped: str = ""
    process: subprocess.Popen | None = None
    poll_s: float = 0.5  # how often readiness is checked; a bench timing a start polls faster

    @property
    def ok(self) -> bool:
        return self.ready and all(p.ok for p in self.probes) and bool(self.probes)

    def to_json(self) -> dict:
        return {
            "target": self.action.target, "capability": self.action.capability, "backend": self.backend,
            "url": self.url, "ready": self.ready, "ready_detail": self.ready_detail,
            "probes": [p.__dict__ for p in self.probes], "stopped": self.stopped, "log": str(self.log),
            "action_digest": self.action.digest(),
        }


def free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to the deployment itself: a probe must never pass on another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (new.scheme, new.netloc) != (old.scheme, old.netloc):
            raise urllib.error.URLError(f"HTTP {code} redirect off the deployment to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Talk to the deployment directly: no proxy from the environment, no redirects off it.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SameHostRedirects)


def get(url: str, timeout: float = 10.0) -> tuple[int | None, str]:
    try:
        with _OPENER.open(urllib.request.Request(url, method="GET"), timeout=timeout) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, str(e.reason)
    except (urllib.error.URLError, OSError) as e:
        return None, str(getattr(e, "reason", e))


def start(action: Action, env: Env, backend: str = "local", poll_s: float = 0.5) -> Deployment:
    if backend not in BACKENDS:
        raise ValueError(f"unknown deploy backend {backend!r}; v0 has {', '.join(BACKENDS)}")
    if action.service is None:
        raise ValueError(f"{action.target} {action.capability}:{action.name} is not a service action")
    port = free_port()
    penv = Env(repo=env.repo, out=env.out, toolchains=env.toolchains, adapter_dirs=env.adapter_dirs, port=port)
    argv, environ, cwd = penv.command(action)
    (env.out / "logs").mkdir(parents=True, exist_ok=True)
    log = env.out.resolve() / "logs" / f"{slug(action)}.log"
    dep = Deployment(action, backend, f"http://{HOST}:{port}", log, poll_s=poll_s)
    with open(log, "wb") as f:
        try:
            dep.process = subprocess.Popen(argv, cwd=cwd, env=environ, stdout=f, stderr=subprocess.STDOUT,
                                           start_new_session=True)
        except OSError as e:
            dep.ready_detail = f"could not start {argv[0]!r}: {e.strerror or e}"
            return dep
    try:
        wait_ready(dep)
    except BaseException:
        stop(dep)  # interrupted or cancelled while waiting: never leave the service running
        raise
    return dep


def wait_ready(dep: Deployment) -> None:
    """Ready means the ready path answers at all (below HTTP 500); probes then judge the answers.
    TODO(expert): fail if the service ignores {port} and binds elsewhere (a free-port race)."""
    svc = dep.action.service
    deadline = time.monotonic() + svc.ready_timeout_s
    while time.monotonic() < deadline:
        if dep.process.poll() is not None:
            dep.ready_detail = f"exited with code {dep.process.returncode} before it was ready"
            return
        status, _ = get(dep.url + svc.ready_path, timeout=5)
        if status is not None and status < 500:
            dep.ready, dep.ready_detail = True, f"{svc.ready_path} answered {status}"
            return
        time.sleep(dep.poll_s)
    dep.ready_detail = f"{svc.ready_path} did not answer within {svc.ready_timeout_s}s"


def probe(dep: Deployment, paths=None) -> list[Probe]:
    """GET each path; a probe passes on a status below 400 (stricter than readiness)."""
    for path in paths if paths is not None else dep.action.service.probes:
        started = time.monotonic()
        status, detail = get(dep.url + path)
        ok = status is not None and status < 400
        dep.probes.append(Probe(path, status, ok, detail or f"HTTP {status}", round(time.monotonic() - started, 3)))
    return dep.probes


def group_alive(pgid: int) -> bool:
    """True while any live (non-zombie) process remains in the process group."""
    proc = Path("/proc")
    if proc.is_dir():
        for stat in proc.glob("[0-9]*/stat"):
            try:
                fields = stat.read_text().rsplit(")", 1)[1].split()
            except (OSError, IndexError):
                continue
            if int(fields[2]) == pgid and fields[0] != "Z":  # fields: state, ppid, pgrp, ...
                return True
        return False
    try:  # no /proc (macOS): zombies count as alive here, so the grace period may run out
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def stop(dep: Deployment, grace_s: float = 10.0) -> None:
    """Tear down the whole process group: SIGTERM, then SIGKILL whatever outlives the grace period.
    Runs even when the leader has already exited, since its children may not have."""
    proc = dep.process
    if proc is None:
        dep.stopped = "not running"
        return
    pgid = proc.pid  # start_new_session: the leader's pid is the group id
    leader_gone = proc.poll() is not None
    if not group_alive(pgid):
        dep.stopped = f"already exited ({proc.returncode})" if leader_gone else "already gone"
        proc.poll()
        return
    _signal_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while group_alive(pgid) and time.monotonic() < deadline:
        proc.poll()
        time.sleep(0.1)
    if group_alive(pgid):
        _signal_group(pgid, signal.SIGKILL)
        end = time.monotonic() + 5
        while group_alive(pgid) and time.monotonic() < end:
            proc.poll()
            time.sleep(0.1)
        dep.stopped = "killed after grace period"
    else:
        dep.stopped = "terminated"
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        dep.stopped += "; leader still running"


def deploy_and_probe(action: Action, env: Env, backend: str = "local") -> Deployment:
    """Start, probe if ready, and always tear down."""
    dep = start(action, env, backend)
    try:
        if dep.ready:
            probe(dep)
    finally:
        stop(dep)
    write_junit(dep, env.out.resolve() / "junit" / f"{slug(action)}.xml")
    return dep


def write_junit(dep: Deployment, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cases = [(f"{dep.action.capability}:start", dep.ready, dep.ready_detail)]
    cases += [(f"probe:{p.path}", p.ok, p.detail) for p in dep.probes]
    if dep.ready and not dep.probes:
        cases.append(("probe:none", False, "no probes ran"))
    suite = ET.Element("testsuite", name=dep.action.target, tests=str(len(cases)),
                       failures=str(sum(not ok for _, ok, _ in cases)))
    for name, ok, detail in cases:
        case = ET.SubElement(suite, "testcase", classname=dep.action.target, name=name)
        if not ok:
            failure = ET.SubElement(case, "failure", message=detail)
            failure.text = dep.log.read_text(errors="replace")[-8000:] if dep.log.exists() else ""
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
    return path
