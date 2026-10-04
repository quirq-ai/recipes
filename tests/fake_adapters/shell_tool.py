"""A kind that runs shell commands: fetch, build and test, nothing else."""
from qqrecipes.contract import Adapter, Service


class ShellTool(Adapter):
    kind = "shell-tool"
    toolchain = "sh"

    def fetch(self, target, ctx):
        return [self.action(target, ctx, "fetch", "noop", ["{toolchain:sh}sh", "-c", "true"])]

    def build(self, target, ctx):
        script = target.params.get("build", "mkdir -p out && cat " + " ".join(target.srcs) + " > out/all")
        return [self.action(target, ctx, "build", "concat", ["sh", "-c", script], outputs=("out",))]

    def test(self, target, ctx):
        script = target.params.get("test", "true")
        return [self.action(target, ctx, "test", "check", ["sh", "-c", script], env={"OUT": "{out}"})]

    def run(self, target, ctx):
        return [self.action(target, ctx, "run", "serve", ["sh", "-c", "sleep 60"], service=Service())]


ADAPTER = ShellTool()
