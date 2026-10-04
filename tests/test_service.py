import sys
import time
from xml.etree import ElementTree as ET

import pytest

from qqrecipes import runner, service
from qqrecipes.contract import Action, Service

DIGEST = "sha256:" + "0" * 64


def svc(argv, probes=("/",), ready_timeout_s=30):
    return Action(target="web", capability="deploy", name="serve", argv=tuple(argv), input_root_digest=DIGEST,
                  service=Service(ready_path="/", ready_timeout_s=ready_timeout_s, probes=tuple(probes)))


HTTP = [sys.executable, "-m", "http.server", "{port}", "--bind", "127.0.0.1"]


def test_deploy_probe_teardown(tmp_path):
    (tmp_path / "index.html").write_text("hi")
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    dep = service.deploy_and_probe(svc(HTTP, probes=("/", "/index.html")), env)
    assert dep.ready and dep.ok and [p.status for p in dep.probes] == [200, 200]
    assert dep.stopped == "terminated" and dep.process.poll() is not None
    suite = ET.parse(tmp_path / "out/junit/web.deploy.serve.xml").getroot()
    assert [c.get("name") for c in suite] == ["deploy:start", "probe:/", "probe:/index.html"]
    assert suite.get("failures") == "0"


def test_failing_probe_fails_the_deploy(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    dep = service.deploy_and_probe(svc(HTTP, probes=("/", "/missing")), env)
    assert dep.ready and not dep.ok and dep.probes[1].status == 404
    suite = ET.parse(tmp_path / "out/junit/web.deploy.serve.xml").getroot()
    assert suite.get("failures") == "1"


def test_service_that_exits_is_not_ready(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    dep = service.deploy_and_probe(svc(["sh", "-c", "echo crashing; exit 3"]), env)
    assert not dep.ready and "exited with code 3" in dep.ready_detail and not dep.ok
    assert "crashing" in ET.parse(tmp_path / "out/junit/web.deploy.serve.xml").getroot().find(
        "testcase/failure").text


def test_never_ready_times_out_and_is_killed(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    dep = service.deploy_and_probe(svc(["sh", "-c", "trap '' TERM; sleep 60"], ready_timeout_s=1), env)
    assert not dep.ready and "did not answer within 1s" in dep.ready_detail
    assert dep.stopped in ("terminated", "killed after grace period")


def test_teardown_kills_the_process_group(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    pidfile = tmp_path / "child.pid"
    dep = service.start(svc(["sh", "-c", f"sleep 60 & echo $! > {pidfile}; exec {' '.join(HTTP[:3])} {{port}} --bind 127.0.0.1"]), env)
    assert dep.ready
    child = int(pidfile.read_text())
    service.stop(dep)
    for _ in range(50):
        if not alive(child):
            break
        time.sleep(0.1)
    assert not alive(child)


def alive(pid: int) -> bool:
    try:
        state = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"  # a zombie is dead, just not yet reaped by its new parent


def test_rejects_unknown_backend_and_non_service(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path)
    with pytest.raises(ValueError, match="backend"):
        service.start(svc(HTTP), env, backend="launchpad")
    plain = Action(target="t", capability="build", name="n", argv=("true",), input_root_digest=DIGEST)
    with pytest.raises(ValueError, match="not a service"):
        service.start(plain, env)


def test_interrupt_while_waiting_tears_down(tmp_path, monkeypatch):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    started = {}

    def boom(dep):
        started["dep"] = dep
        raise KeyboardInterrupt

    monkeypatch.setattr(service, "wait_ready", boom)
    with pytest.raises(KeyboardInterrupt):
        service.start(svc(["sh", "-c", "sleep 60"]), env)
    dep = started["dep"]
    assert dep.stopped == "terminated" and not service.group_alive(dep.process.pid)


def test_children_of_an_exited_leader_are_stopped(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    dep = service.deploy_and_probe(svc(["sh", "-c", "sleep 60 & exit 3"]), env)
    assert "exited with code 3" in dep.ready_detail
    assert not service.group_alive(dep.process.pid) and dep.stopped == "terminated"


def test_child_ignoring_term_is_killed(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    script = f"sh -c \"trap '' TERM; sleep 60\" & exec {' '.join(HTTP[:3])} {{port}} --bind 127.0.0.1"
    dep = service.start(svc(["sh", "-c", script]), env)
    assert dep.ready
    service.stop(dep, grace_s=1)
    assert dep.stopped == "killed after grace period" and not service.group_alive(dep.process.pid)


@pytest.mark.parametrize("path", ["@example.com/", "example.com/", "//example.com/", "/a b", "/a\\b", ""])
def test_service_paths_must_stay_on_the_service(path):
    from qqrecipes.contract import ContractError
    with pytest.raises(ContractError, match="must be a path on the service"):
        Service(probes=("/", path))
    with pytest.raises(ContractError):
        Service(ready_path=path)


REDIRECTOR = [sys.executable, "-c", """
import http.server, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        where = {"/off": "http://example.invalid/", "/on": "/ok"}.get(self.path)
        self.send_response(302 if where else 200)
        if where:
            self.send_header("Location", where)
        self.end_headers()
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
""", "{port}"]


def test_probes_follow_redirects_only_on_the_deployment(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    dep = service.deploy_and_probe(svc(REDIRECTOR, probes=("/on", "/off")), env)
    on, off = dep.probes
    assert on.ok and on.status == 200
    assert not off.ok and off.status is None and "redirect off the deployment" in off.detail
    assert not dep.ok
