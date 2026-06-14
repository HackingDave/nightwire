"""Tests for Signal syncMessage command handling."""

from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
    )
    bot._processed_messages = OrderedDict()
    bot._ws_connected_at = 0
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
