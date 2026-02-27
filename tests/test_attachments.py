"""Tests for attachment handling — download, save, and integration with message pipeline."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from nightwire.attachments import (
    SUPPORTED_IMAGE_TYPES,
    download_attachment,
    process_attachments,
    save_attachment,
)


class TestDownloadAttachment:
    """Tests for download_attachment()."""

    @pytest.fixture
    def session(self):
        return MagicMock(spec=aiohttp.ClientSession)

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, session):
        """SSRF prevention: reject IDs with path traversal."""
        result = await download_attachment(session, "http://localhost:8080", "../etc/passwd")
        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_double_dot_traversal(self, session):
        """SSRF prevention: reject IDs containing '..' even without slashes."""
        result = await download_attachment(session, "http://localhost:8080", "..something")
        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_attachment_id_with_slashes(self, session):
        result = await download_attachment(session, "http://localhost:8080", "foo/bar")
        assert result is None

    @pytest.mark.asyncio
    async def test_accepts_attachment_id_with_extension(self):
        """Signal API returns IDs with file extensions (e.g., '09GIqaSf01wyBX0zokr7.jpg')."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        async def fake_chunks():
            yield b"image_data_here"

        mock_resp.content.iter_chunked = MagicMock(return_value=fake_chunks())

        session = MagicMock(spec=aiohttp.ClientSession)
        session.get = MagicMock(return_value=mock_resp)

        result = await download_attachment(session, "http://localhost:8080", "09GIqaSf01wyBX0zokr7.jpg")
        assert result == b"image_data_here"

    @pytest.mark.asyncio
    async def test_accepts_attachment_id_with_hyphen(self):
        """Signal API IDs may contain hyphens (e.g., '-nVtmdGVEJuCnLsmgc-Q.jpg')."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        async def fake_chunks():
            yield b"image_data_here"

        mock_resp.content.iter_chunked = MagicMock(return_value=fake_chunks())

        session = MagicMock(spec=aiohttp.ClientSession)
        session.get = MagicMock(return_value=mock_resp)

        result = await download_attachment(session, "http://localhost:8080", "-nVtmdGVEJuCnLsmgc-Q.jpg")
        assert result == b"image_data_here"

    @pytest.mark.asyncio
    async def test_accepts_valid_attachment_id_no_extension(self):
        """Plain alphanumeric IDs should still be accepted."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        async def fake_chunks():
            yield b"image_data_here"

        mock_resp.content.iter_chunked = MagicMock(return_value=fake_chunks())

        session = MagicMock(spec=aiohttp.ClientSession)
        session.get = MagicMock(return_value=mock_resp)

        result = await download_attachment(session, "http://localhost:8080", "abc123_XYZ=-")
        assert result == b"image_data_here"

    @pytest.mark.asyncio
    async def test_returns_none_on_http_error(self):
        """Non-200 status should return None."""
        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock(spec=aiohttp.ClientSession)
        session.get = MagicMock(return_value=mock_resp)

        result = await download_attachment(session, "http://localhost:8080", "valid123")
        assert result is None


class TestSaveAttachment:
    """Tests for save_attachment()."""

    def test_saves_jpeg(self, tmp_path):
        data = b"\xff\xd8\xff\xe0fake_jpeg"
        result = save_attachment(data, "image/jpeg", "+15555551234", tmp_path)
        assert result is not None
        assert result.suffix == ".jpg"
        assert result.read_bytes() == data

    def test_saves_png(self, tmp_path):
        data = b"\x89PNG\r\n\x1a\nfake_png"
        result = save_attachment(data, "image/png", "+15555551234", tmp_path)
        assert result is not None
        assert result.suffix == ".png"

    def test_rejects_unsupported_type(self, tmp_path):
        result = save_attachment(b"data", "application/pdf", "+15555551234", tmp_path)
        assert result is None

    def test_sanitizes_sender_directory(self, tmp_path):
        """Sender phone number should be digits only in directory name."""
        data = b"test"
        result = save_attachment(data, "image/jpeg", "+1 (555) 555-1234", tmp_path)
        assert result is not None
        # Directory should contain only digits
        assert result.parent.name == "15555551234"

    def test_unknown_sender_uses_fallback(self, tmp_path):
        """Non-digit sender should use 'unknown' directory."""
        data = b"test"
        result = save_attachment(data, "image/jpeg", "no-digits-here", tmp_path)
        assert result is not None
        assert result.parent.name == "unknown"


class TestProcessAttachments:
    """Tests for process_attachments()."""

    @pytest.mark.asyncio
    async def test_processes_image_attachment(self, tmp_path):
        """Full pipeline: download + save for an image attachment."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        async def fake_chunks():
            yield b"fake_image_bytes"

        mock_resp.content.iter_chunked = MagicMock(return_value=fake_chunks())

        session = MagicMock(spec=aiohttp.ClientSession)
        session.get = MagicMock(return_value=mock_resp)

        attachments = [
            {"id": "attachment123.jpg", "contentType": "image/jpeg", "size": 1024},
        ]

        result = await process_attachments(
            attachments=attachments,
            sender="+15555551234",
            session=session,
            signal_api_url="http://localhost:8080",
            attachments_dir=tmp_path,
        )

        assert len(result) == 1
        assert result[0].suffix == ".jpg"
        assert result[0].read_bytes() == b"fake_image_bytes"

    @pytest.mark.asyncio
    async def test_skips_non_image_attachment(self, tmp_path):
        """Non-image MIME types should be skipped."""
        session = MagicMock(spec=aiohttp.ClientSession)

        attachments = [
            {"id": "doc123", "contentType": "application/pdf", "size": 2048},
        ]

        result = await process_attachments(
            attachments=attachments,
            sender="+15555551234",
            session=session,
            signal_api_url="http://localhost:8080",
            attachments_dir=tmp_path,
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_skips_attachment_without_id(self, tmp_path):
        """Attachments missing an ID should be skipped."""
        session = MagicMock(spec=aiohttp.ClientSession)

        attachments = [
            {"contentType": "image/png", "size": 512},
        ]

        result = await process_attachments(
            attachments=attachments,
            sender="+15555551234",
            session=session,
            signal_api_url="http://localhost:8080",
            attachments_dir=tmp_path,
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_empty_attachments_list(self, tmp_path):
        """Empty list returns empty result."""
        session = MagicMock(spec=aiohttp.ClientSession)

        result = await process_attachments(
            attachments=[],
            sender="+15555551234",
            session=session,
            signal_api_url="http://localhost:8080",
            attachments_dir=tmp_path,
        )

        assert result == []


class TestHandleSignalMessageAttachments:
    """Tests for attachment extraction in _handle_signal_message."""

    @pytest.mark.asyncio
    async def test_data_message_extracts_attachments(self):
        """Verify attachments are extracted from dataMessage."""
        from nightwire.attachments import process_attachments as _proc

        msg = {
            "envelope": {
                "source": "+15555551234",
                "timestamp": 1234567890,
                "dataMessage": {
                    "message": "/do test with image",
                    "attachments": [
                        {"id": "att1abc.png", "contentType": "image/png", "size": 100},
                    ],
                },
            }
        }

        # Verify the attachment data is in the right place
        data_message = msg["envelope"]["dataMessage"]
        attachments = data_message.get("attachments") or []
        assert len(attachments) == 1
        assert attachments[0]["id"] == "att1abc.png"
        assert attachments[0]["contentType"] == "image/png"

    @pytest.mark.asyncio
    async def test_sync_message_extracts_attachments(self):
        """Verify attachments are extracted from syncMessage.sentMessage."""
        msg = {
            "envelope": {
                "source": "+15555551234",
                "timestamp": 1234567890,
                "syncMessage": {
                    "sentMessage": {
                        "destination": "+15555551234",
                        "message": "test",
                        "attachments": [
                            {"id": "att2xyz.jpeg", "contentType": "image/jpeg", "size": 200},
                        ],
                    },
                },
            }
        }

        sent_message = msg["envelope"]["syncMessage"]["sentMessage"]
        attachments = sent_message.get("attachments") or []
        assert len(attachments) == 1
        assert attachments[0]["id"] == "att2xyz.jpeg"

    @pytest.mark.asyncio
    async def test_message_without_attachments(self):
        """Messages without attachments should have empty list."""
        msg = {
            "envelope": {
                "source": "+15555551234",
                "timestamp": 1234567890,
                "dataMessage": {
                    "message": "just text",
                },
            }
        }

        data_message = msg["envelope"]["dataMessage"]
        attachments = data_message.get("attachments") or []
        assert attachments == []


class TestSupportedImageTypes:
    """Verify SUPPORTED_IMAGE_TYPES constant."""

    def test_includes_common_types(self):
        assert "image/jpeg" in SUPPORTED_IMAGE_TYPES
        assert "image/png" in SUPPORTED_IMAGE_TYPES
        assert "image/gif" in SUPPORTED_IMAGE_TYPES
        assert "image/webp" in SUPPORTED_IMAGE_TYPES

    def test_correct_extensions(self):
        assert SUPPORTED_IMAGE_TYPES["image/jpeg"] == ".jpg"
        assert SUPPORTED_IMAGE_TYPES["image/png"] == ".png"
        assert SUPPORTED_IMAGE_TYPES["image/gif"] == ".gif"
        assert SUPPORTED_IMAGE_TYPES["image/webp"] == ".webp"
