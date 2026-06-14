"""Tests for Signal receive WebSocket recovery."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nightwire.bot import SignalBot, WS_IDLE_RECONNECT_SECONDS


class _StaleWebSocket:
    def __init__(self, bot):
        self.bot = bot
        self.receive_timeout = None

    async def receive(self, timeout=None):
        self.receive_timeout = timeout
        self.bot.running = False
        raise asyncio.TimeoutError


class _WebSocketContext:
    def __init__(self, ws):
        self.ws = ws

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_poll_messages_reconnects_stale_websocket():
    bot = SignalBot.__new__(SignalBot)
    bot.config = SimpleNamespace(
        signal_api_url="http://127.0.0.1:8080",
        allowed_numbers=[],
    )
    bot.account = "+15551234567"
    bot.running = True
    bot._startup_notified = True
    bot._last_ws_activity = time.monotonic() - WS_IDLE_RECONNECT_SECONDS - 1
    bot._ws_connected_at = time.time()
    bot._ws_frames_received = 7
    bot._handle_signal_message = AsyncMock()

    ws = _StaleWebSocket(bot)
    bot.session = SimpleNamespace(
        ws_connect=MagicMock(return_value=_WebSocketContext(ws)),
    )

    with patch("nightwire.bot.logger") as mock_logger:
        await bot.poll_messages()

    bot.session.ws_connect.assert_called_once()
    assert ws.receive_timeout == WS_IDLE_RECONNECT_SECONDS
    warning_calls = [
        call for call in mock_logger.warning.call_args_list
        if call.args and call.args[0] == "websocket_stale_reconnect"
    ]
    assert len(warning_calls) == 1
