"""The example service's one piece of logic: build a greeting from a name taken from a request."""


def greeting(name: str) -> str:
    name = " ".join(name.split())[:64] or "there"
    return f"hello, {name}"
