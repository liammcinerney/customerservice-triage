"""The packages import, so `python -m triage.cli` and `python -m eval.run` can find them."""

import importlib


def test_packages_import():
    for name in ("triage", "triage.config", "eval"):
        assert importlib.import_module(name) is not None
