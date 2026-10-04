"""Property tests for the one input handler: whatever name a request carries, the greeting stays
a single short line. Hypothesis runs these as ordinary tests (V0-REC-04)."""
from hypothesis import given, strategies as st

from greet import greeting


@given(st.text())
def test_greeting_is_one_bounded_line(name):
    out = greeting(name)
    assert out.startswith("hello, ")
    assert "\n" not in out and "\r" not in out
    assert len(out) <= len("hello, ") + 64


@given(st.text(alphabet=st.characters(categories=["L", "N"]), min_size=1, max_size=20))
def test_plain_names_are_kept(name):
    assert greeting(name) == f"hello, {name}"
