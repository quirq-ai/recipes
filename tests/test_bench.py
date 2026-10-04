import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from qqrecipes import bench, runner
from qqrecipes.contract import Action, Bench, ContractError, Service, Target

DIGEST = "sha256:" + "0" * 64
HTTP = [sys.executable, "-m", "http.server", "{port}", "--bind", "127.0.0.1"]


def bench_action(argv, spec):
    return Action(target="web", capability="bench", name="serve", argv=tuple(argv), input_root_digest=DIGEST,
                  service=Service(ready_path="/", ready_timeout_s=30), bench=spec)


def test_startup_samples_every_start(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    res = bench.run(bench_action(HTTP, Bench(measure="startup", samples=3, warmup=1)), env)
    assert res.ok, res.detail
    assert len(res.samples) == 3 and res.unit == "s" and all(0 < s < 30 for s in res.samples)
    assert res.metrics["startup_samples"] == {"value": 3, "unit": "count"}
    assert res.metrics["startup_p50"]["unit"] == "s"
    assert res.metrics["startup_min"]["value"] <= res.metrics["startup_p50"]["value"] <= res.metrics["startup_max"]["value"]
    data = json.loads((tmp_path / "out/bench/web.bench.serve.json").read_text())
    assert data["measure"] == "startup" and data["samples"] == res.samples and data["ok"]
    assert len(set(res.logs)) == 4 and all(Path(log).exists() for log in res.logs)  # one per start, warmup too
    suite = ET.parse(tmp_path / "out/junit/web.bench.serve.xml").getroot()
    assert suite.get("failures") == "0" and suite.find("testcase").get("name") == "bench:startup"


def test_latency_times_each_path(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    res = bench.run(bench_action(HTTP, Bench(measure="latency", paths=("/", "/a.txt"), samples=4, warmup=2)), env)
    assert res.ok, res.detail
    assert len(res.samples) == 8 and res.unit == "ms"
    assert res.metrics["latency_samples"]["value"] == 8 and res.metrics["latency_p90"]["unit"] == "ms"


def test_a_bad_path_fails_the_bench(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    res = bench.run(bench_action(HTTP, Bench(measure="latency", paths=("/missing",))), env)
    assert not res.ok and "404" in res.detail and res.metrics == {}
    suite = ET.parse(tmp_path / "out/junit/web.bench.serve.xml").getroot()
    assert suite.get("failures") == "1"


def test_a_service_that_never_starts_fails(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path / "out")
    res = bench.run(bench_action(["sh", "-c", "exit 3"], Bench(measure="startup")), env)
    assert not res.ok and "exited with code 3" in res.detail


def test_needs_a_bench_action(tmp_path):
    env = runner.Env(repo=tmp_path, out=tmp_path)
    with pytest.raises(ValueError, match="not a bench action"):
        bench.run(Action(target="web", capability="bench", name="x", argv=("true",), input_root_digest=DIGEST), env)


def test_nearest_rank():
    assert bench.nearest_rank([5, 1, 3, 2, 4], 90) == 5
    assert bench.nearest_rank([1.0], 50) == 1.0
    assert bench.nearest_rank(list(range(1, 11)), 90) == 9


def target(params):
    return Target(name="app", kind="node-app", params=params)


def test_bench_params_defaults_and_values():
    assert Bench.from_params(target({}), measure="latency", path="/health") == Bench("latency", ("/health",), 5, 1)
    spec = Bench.from_params(target({"bench": {"measure": "latency", "paths": ["/a", "/b?q=x"], "samples": 9,
                                               "warmup": 0}}), measure="startup", path="/")
    assert spec == Bench("latency", ("/a", "/b?q=x"), 9, 0)
    assert Bench.from_params(target({"bench": {"measure": "startup"}}), measure="latency", path="/up").paths == ("/up",)
    with pytest.raises(ContractError, match="startup times the ready path"):
        Bench.from_params(target({"bench": {"measure": "startup", "paths": ["/a"]}}), measure="latency", path="/")


@pytest.mark.parametrize("raw, match", [
    ("fast", "must be a table"), ({"measure": "memory"}, "measure"), ({"paths": []}, "paths"),
    ({"paths": ["no-slash"]}, "paths"), ({"samples": 0}, "samples"), ({"warmup": True}, "warmup"),
    ({"rounds": 3}, "unknown keys")])
def test_bad_bench_params(raw, match):
    with pytest.raises(ContractError, match=match):
        Bench.from_params(target({"bench": raw}), measure="latency", path="/")


def test_timed_get_reads_the_whole_body(tmp_path):
    import http.server
    import threading

    class Slow(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"head")
            self.wfile.flush()
            import time
            time.sleep(0.3)
            self.wfile.write(b"tail")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    status, _, took = bench.timed_get(f"http://127.0.0.1:{srv.server_port}/")
    srv.server_close()
    assert status == 200 and took >= 0.3
