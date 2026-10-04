"""The adapters: one module or package per target kind, named after the kind with `-` as `_`.

Kind `my-kind` lives in `qqrecipes.adapters.my_kind`. Each exposes `ADAPTER`, an instance
of `qqrecipes.contract.Adapter` whose `kind` is that kind. Modules whose name starts with `_` are
shared helpers, not kinds. Only this tree may name a language, a build tool or a test runner.
"""
