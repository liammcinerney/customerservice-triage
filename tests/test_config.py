"""The small .env reader in triage.config."""

import os

from triage.config import DEFAULT_MODEL, load_env, model_name, parse_env_file


def test_parse_basic_lines_comments_and_quotes():
    text = """
# a comment
ANTHROPIC_API_KEY=abc123
export TRIAGE_MODEL="claude-haiku-5-5"
SINGLE='quoted value'
  SPACED  =  padded
NO_EQUALS_SIGN
=no_key
"""
    assert parse_env_file(text) == {
        "ANTHROPIC_API_KEY": "abc123",
        "TRIAGE_MODEL": "claude-haiku-5-5",
        "SINGLE": "quoted value",
        "SPACED": "padded",
    }


def test_value_may_contain_equals_sign():
    assert parse_env_file("KEY=a=b=c") == {"KEY": "a=b=c"}


def test_load_env_does_not_override_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TRIAGE_TEST_A=from_file\nTRIAGE_TEST_B=from_file\n")
    monkeypatch.setenv("TRIAGE_TEST_A", "from_shell")
    monkeypatch.delenv("TRIAGE_TEST_B", raising=False)

    load_env(env_file)

    assert os.environ["TRIAGE_TEST_A"] == "from_shell"
    assert os.environ["TRIAGE_TEST_B"] == "from_file"
    # monkeypatch recorded B as unset, so teardown removes the value load_env added.


def test_load_env_skips_empty_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TRIAGE_TEST_EMPTY=\n")
    monkeypatch.delenv("TRIAGE_TEST_EMPTY", raising=False)

    load_env(env_file)

    assert "TRIAGE_TEST_EMPTY" not in os.environ


def test_load_env_missing_file_is_fine(tmp_path):
    load_env(tmp_path / "does-not-exist.env")


def test_model_name_default_and_override(monkeypatch):
    monkeypatch.delenv("TRIAGE_MODEL", raising=False)
    assert model_name() == DEFAULT_MODEL == "claude-opus-5-5"
    monkeypatch.setenv("TRIAGE_MODEL", "claude-haiku-5-5")
    assert model_name() == "claude-haiku-5-5"
