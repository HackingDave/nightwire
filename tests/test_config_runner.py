"""Tests for runner configuration compatibility."""

from nightwire.config import Config


def _make_config(monkeypatch, settings):
    def _fake_init(self, config_dir=None):
        self.settings = settings
        self.projects = {"projects": []}

    monkeypatch.setattr(Config, "__init__", _fake_init)
    return Config()


def test_runner_type_defaults_to_claude(monkeypatch):
    config = _make_config(monkeypatch, {})
    assert config.runner_type == "claude"


def test_runner_path_defaults_to_claude_path(monkeypatch):
    config = _make_config(monkeypatch, {"claude_path": "/custom/claude"})
    assert config.runner_path == "/custom/claude"


def test_runner_type_opencode(monkeypatch):
    config = _make_config(monkeypatch, {"runner": {"type": "opencode"}})
    assert config.runner_type == "opencode"


def test_runner_path_override(monkeypatch):
    config = _make_config(monkeypatch, {"runner": {"path": "/custom/opencode"}})
    assert config.runner_path == "/custom/opencode"


def test_legacy_claude_path_still_works_without_runner(monkeypatch):
    config = _make_config(monkeypatch, {"claude_path": "/legacy/claude"})
    assert config.claude_path == "/legacy/claude"
