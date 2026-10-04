"""A kind with only build: everything else is declared missing."""
from qqrecipes.contract import Adapter


class DocsOnly(Adapter):
    kind = "docs-only"

    def build(self, target, ctx):
        return [self.action(target, ctx, "build", "noop", ["true"])]


ADAPTER = DocsOnly()
