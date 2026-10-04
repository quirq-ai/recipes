"""pytest plugin the pytest adapter loads (`-p qq_hypothesis`): Hypothesis property tests run as
ordinary tests in every gate run, deterministic and bounded (plan §5.9).

When Hypothesis is installed and neither the command line nor the repo (for example a conftest
calling `settings.load_profile`) picked a profile, it loads the "qq-gate" profile: derandomized
(the same examples on every run, so the gate is deterministic), no example database (no state
carried between runs) and a bounded number of examples (QQ_PROPERTY_EXAMPLES, default 100).
There is no per-example deadline, as in Hypothesis's own `ci` profile: a deadline makes results
depend on machine speed. Total time is bounded by the test action's timeout.
"""
from __future__ import annotations

import os

PROFILE = "qq-gate"
UNCHOSEN = {"default", "ci"}  # Hypothesis's built-ins: what is loaded when nobody chose


def pytest_configure(config):
    try:
        from hypothesis import settings
    except ImportError:
        return  # no property tests in this repo
    if config.getoption("hypothesis_profile", default=None):
        return  # chosen on the command line; respect it
    if settings.get_current_profile_name() not in UNCHOSEN:
        return  # the repo loaded its own profile; respect it
    settings.register_profile(
        PROFILE,
        derandomize=True,
        database=None,
        max_examples=int(os.environ.get("QQ_PROPERTY_EXAMPLES", "100")),
        deadline=None,
        print_blob=True,
    )
    settings.load_profile(PROFILE)
