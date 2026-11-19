"""Shared test setup.

Every test runs from an empty temporary directory with no API key in the environment.
`load_env()` therefore never reads the real .env, and no test could reach the API even by mistake.
Tests that need repo files use absolute paths built from __file__.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_from_real_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "TRIAGE_MODEL"):
        monkeypatch.delenv(var, raising=False)
