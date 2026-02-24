"""Tests for auto-update feature."""

import asyncio
import subprocess

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path


class TestAutoUpdateConfig:
    """Tests for auto_update configuration properties."""

    def test_auto_update_disabled_by_default(self):
        from sidechannel.config import Config
        with patch.object(Config, '__init__', lambda self, **kw: None):
            config = Config.__new__(Config)
            config.settings = {}
            assert config.auto_update_enabled is False

    def test_auto_update_enabled_from_settings(self):
        from sidechannel.config import Config
        with patch.object(Config, '__init__', lambda self, **kw: None):
            config = Config.__new__(Config)
            config.settings = {"auto_update": {"enabled": True}}
            assert config.auto_update_enabled is True

    def test_auto_update_check_interval_default(self):
        from sidechannel.config import Config
        with patch.object(Config, '__init__', lambda self, **kw: None):
            config = Config.__new__(Config)
            config.settings = {}
            assert config.auto_update_check_interval == 21600

    def test_auto_update_check_interval_from_settings(self):
        from sidechannel.config import Config
        with patch.object(Config, '__init__', lambda self, **kw: None):
            config = Config.__new__(Config)
            config.settings = {"auto_update": {"check_interval": 3600}}
            assert config.auto_update_check_interval == 3600

    def test_auto_update_branch_default(self):
        from sidechannel.config import Config
        with patch.object(Config, '__init__', lambda self, **kw: None):
            config = Config.__new__(Config)
            config.settings = {}
            assert config.auto_update_branch == "main"

    def test_auto_update_branch_from_settings(self):
        from sidechannel.config import Config
        with patch.object(Config, '__init__', lambda self, **kw: None):
            config = Config.__new__(Config)
            config.settings = {"auto_update": {"branch": "develop"}}
            assert config.auto_update_branch == "develop"


class TestAutoUpdater:
    """Tests for AutoUpdater class."""

    def _make_updater(self, send_message=None):
        """Create an AutoUpdater with mocked dependencies."""
        from sidechannel.updater import AutoUpdater
        config = MagicMock()
        config.auto_update_enabled = True
        config.auto_update_check_interval = 21600
        config.auto_update_branch = "main"
        config.allowed_numbers = ["+15551234567"]
        if send_message is None:
            send_message = AsyncMock()
        return AutoUpdater(
            config=config,
            send_message=send_message,
            repo_dir=Path("/fake/repo"),
        )

    @pytest.mark.asyncio
    async def test_check_for_updates_no_update(self):
        """check_for_updates returns False when local matches remote."""
        updater = self._make_updater()
        async def fake_run_git(*args, **kwargs):
            return "abc1234"
        updater._run_git = fake_run_git
        result = await updater.check_for_updates()
        assert result is False
        assert updater.pending_update is False

    @pytest.mark.asyncio
    async def test_check_for_updates_has_update(self):
        """check_for_updates returns True and sets pending state when remote is ahead."""
        send = AsyncMock()
        updater = self._make_updater(send_message=send)
        call_count = 0
        async def fake_run_git(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ""  # git fetch
            elif call_count == 2:
                return "abc1234"  # local HEAD
            elif call_count == 3:
                return "def5678"  # remote HEAD
            elif call_count == 4:
                return "3"  # commit count
            elif call_count == 5:
                return "feat: add cool thing"  # latest commit message
            return ""
        updater._run_git = fake_run_git
        result = await updater.check_for_updates()
        assert result is True
        assert updater.pending_update is True
        assert updater.pending_sha == "def5678"
        send.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_for_updates_no_renotify_same_sha(self):
        """check_for_updates should not re-notify if pending_sha unchanged."""
        send = AsyncMock()
        updater = self._make_updater(send_message=send)
        updater.pending_update = True
        updater.pending_sha = "def5678"
        call_count = 0
        async def fake_run_git(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ""  # git fetch
            elif call_count == 2:
                return "abc1234"  # local HEAD
            elif call_count == 3:
                return "def5678"  # remote HEAD (same as pending)
            return ""
        updater._run_git = fake_run_git
        result = await updater.check_for_updates()
        assert result is True
        send.assert_not_called()
