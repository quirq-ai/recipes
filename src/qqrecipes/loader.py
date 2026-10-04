"""The one loader: a kind name resolves to its adapter. Core file: names no language or tool.

Adapters are discovered, not registered: adding a kind means adding `qqrecipes/adapters/<kind>`
with an `ADAPTER`, and no core edit. A kind with no module is AdapterNotFound. An adapter module
that exists but fails to import raises, so a broken install is never mistaken for a missing kind.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

from qqrecipes.contract import Adapter, ContractError

PACKAGE = "qqrecipes.adapters"
KIND_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # the manifest's kind pattern (quirq-repo/1)


class AdapterNotFound(LookupError):
    def __init__(self, kind: str, package: str):
        self.kind = kind
        super().__init__(
            f"no adapter for kind {kind!r}: add {package}.{module_name(kind)} with an ADAPTER, or fix"
            f" the target's kind (known: {', '.join(available(package)) or 'none'})")


def module_name(kind: str) -> str:
    return kind.replace("-", "_")


def kind_name(module: str) -> str:
    return module.replace("_", "-")


def load(kind: str, package: str | None = None) -> Adapter:
    package = package or PACKAGE
    if not KIND_RE.match(kind):
        raise ContractError(f"{kind!r} is not a kind name (lowercase letters, digits and '-')")
    modname = f"{package}.{module_name(kind)}"
    try:
        module = importlib.import_module(modname)
    except ModuleNotFoundError as e:
        if e.name == modname:
            raise AdapterNotFound(kind, package) from None
        raise  # the adapter exists but something it imports is missing: fail loudly
    adapter = getattr(module, "ADAPTER", None)
    if not isinstance(adapter, Adapter):
        raise ContractError(f"{modname} must define ADAPTER, an instance of qqrecipes.contract.Adapter")
    if adapter.kind != kind:
        raise ContractError(f"{modname}.ADAPTER.kind is {adapter.kind!r}; it must be {kind!r}")
    return adapter


def available(package: str | None = None) -> list[str]:
    """Every kind with an adapter module in `package`, sorted."""
    package = package or PACKAGE
    pkg = importlib.import_module(package)
    paths = [str(Path(p)) for p in getattr(pkg, "__path__", [])]
    return sorted(kind_name(m.name) for m in pkgutil.iter_modules(paths) if not m.name.startswith("_"))


def adapter_dir(adapter: Adapter) -> Path:
    """The directory holding the adapter's own files: what `{adapter}` resolves to."""
    module = importlib.import_module(type(adapter).__module__)
    path = Path(module.__file__).resolve()
    if path.name != "__init__.py":
        raise ContractError(f"{module.__name__} uses {{adapter}} but is a single module; make it a"
                            f" package ({module.__name__.replace('.', '/')}/__init__.py) to hold files")
    return path.parent
