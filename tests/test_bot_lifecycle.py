"""Lifecycle regression tests for the Signal bot."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nightwire.bot import SignalBot


@pytest.mark.asyncio
async def test_start_fails_when_signal_api_has_no_account():
    bot = SignalBot.__new__(SignalBot)
    bot.session = None
    bot.running = False
    bot.config = MagicMock(signal_api_url="http://127.0.0.1:8080")
    bot._get_account = AsyncMock()
    bot._check_signal_api_health = AsyncMock()
    bot.account = None

    with pytest.raises(RuntimeError, match="no registered account"):
        await bot.start()

    await bot.session.close()
    bot._check_signal_api_health.assert_not_awaited()
