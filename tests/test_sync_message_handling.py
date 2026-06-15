"""Tests for Signal syncMessage command handling."""

from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nightwire.bot import SignalBot


TEST_ACCOUNT = "+15551234567"


def _make_bot(tmp_path):
    bot = SignalBot.__new__(SignalBot)
    bot.account = TEST_ACCOUNT
    bot.session = None
    bot.config = SimpleNamespace(
        instance_name="nightwire",
        signal_api_url="http://127.0.0.1:8080",
        attachments_dir=tmp_path,
        allowed_numbers=[TEST_ACCOUNT],
    )
    bot._processed_messages = OrderedDict()
    bot._ws_connected_at = 0
    bot._last_signal_receive_error_notified = 0
    bot._send_message = AsyncMock()
    bot._process_message = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_sync_message_without_phone_destination_is_processed(tmp_path):
    bot = _make_bot(tmp_path)
    msg = {
        "envelope": {
            "timestamp": 1234567890000,
            "syncMessage": {
                "sentMessage": {
                    "message": "/select swish365",
                    "attachments": [],
                },
            },
        },
    }

    await bot._handle_signal_message(msg)

    bot._process_message.assert_awaited_once_with(
        TEST_ACCOUNT,
        "/select swish365",
        image_paths=[],
    )


@pytest.mark.asyncio
async def test_sync_message_with_uuid_only_destination_is_processed(tmp_path):
    bot = _make_bot(tmp_path)
    msg = {
        "envelope": {
            "timestamp": 1234567890001,
            "syncMessage": {
                "sentMessage": {
                    "destinationUuid": "00000000-0000-0000-0000-000000000001",
                    "message": "/select swish365",
                    "attachments": [],
                },
            },
        },
    }

    await bot._handle_signal_message(msg)

    bot._process_message.assert_awaited_once_with(
        TEST_ACCOUNT,
        "/select swish365",
        image_paths=[],
    )


@pytest.mark.asyncio
async def test_sync_message_to_other_phone_number_is_ignored(tmp_path):
    bot = _make_bot(tmp_path)
    msg = {
        "envelope": {
            "timestamp": 1234567890002,
            "syncMessage": {
                "sentMessage": {
                    "destinationNumber": "+15557654321",
                    "message": "/select swish365",
                    "attachments": [],
                },
            },
        },
    }

    await bot._handle_signal_message(msg)

    bot._process_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_signal_receive_exception_notifies_allowed_number(tmp_path):
    bot = _make_bot(tmp_path)
    msg = {
        "account": TEST_ACCOUNT,
        "exception": {
            "message": "getServerGuid(...) must not be null",
            "type": "NullPointerException",
        },
        "envelope": {
            "timestamp": 1234567890003,
        },
    }

    await bot._handle_signal_message(msg)

    bot._process_message.assert_not_awaited()
    bot._send_message.assert_awaited_once()
    assert bot._send_message.await_args.args[0] == TEST_ACCOUNT
    assert "Signal receive error" in bot._send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_signal_sender_key_retry_exception_is_not_notified(tmp_path):
    bot = _make_bot(tmp_path)
    msg = {
        "account": TEST_ACCOUNT,
        "exception": {
            "message": (
                "org.signal.libsignal.protocol.NoSessionException: "
                "missing sender key state for distribution ID "
                "48a080c1-c735-45ab-972f-91d641663f9c"
            ),
            "type": "ProtocolNoSessionException",
        },
        "envelope": {
            "sourceUuid": "11111111-2222-3333-4444-555555555555",
            "sourceDevice": 1,
            "timestamp": 1234567890004,
        },
    }

    with patch("nightwire.bot.logger") as mock_logger:
        await bot._handle_signal_message(msg)

    bot._process_message.assert_not_awaited()
    bot._send_message.assert_not_awaited()

    retry_logs = [
        call for call in mock_logger.warning.call_args_list
        if call.args and call.args[0] == "signal_receive_sender_key_retry"
    ]
    assert len(retry_logs) == 1
    assert retry_logs[0].kwargs["source_tail"] == "55555555"
