"""Attachment handling for Signal bot - download, validate, and save image attachments."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import structlog

logger = structlog.get_logger()

# Supported image MIME types for Claude vision
SUPPORTED_IMAGE_TYPES: Dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


async def download_attachment(
    session: aiohttp.ClientSession,
    signal_api_url: str,
    attachment_id: str,
) -> Optional[bytes]:
    """Download an attachment from Signal API.

    Args:
        session: aiohttp session for HTTP requests
        signal_api_url: Base URL of the Signal API
        attachment_id: The Signal attachment ID

    Returns:
        Attachment bytes or None if download fails
    """
    try:
        url = f"{signal_api_url}/v1/attachments/{attachment_id}"
        async with session.get(url) as resp:
            if resp.status == 200:
                # Check content length before downloading
                content_length = resp.content_length
                if isinstance(content_length, int) and content_length > 50_000_000:  # 50MB limit
                    logger.warning("attachment_too_large", size=content_length, attachment_id=attachment_id)
                    return None
                data = await resp.read()
                logger.info("attachment_downloaded", id=attachment_id, size=len(data))
                return data
            else:
                logger.error("attachment_download_failed", id=attachment_id, status=resp.status)
                return None
    except aiohttp.ClientError as e:
        logger.error("attachment_download_error", id=attachment_id, error=str(e), error_type=type(e).__name__)
        return None


def save_attachment(
    attachment_data: bytes,
    content_type: str,
    sender: str,
    attachments_dir: Path,
) -> Optional[Path]:
    """Save attachment data to disk.

    Args:
        attachment_data: Raw attachment bytes
        content_type: MIME type of the attachment
        sender: Phone number of sender (for organizing files)
        attachments_dir: Base directory for attachments

    Returns:
        Path to saved file or None if unsupported type
    """
    if content_type not in SUPPORTED_IMAGE_TYPES:
        logger.warning("unsupported_attachment_type", content_type=content_type)
        return None

    ext = SUPPORTED_IMAGE_TYPES[content_type]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{timestamp}_{unique_id}{ext}"

    user_dir = attachments_dir / sender.replace("+", "")
    user_dir.mkdir(parents=True, exist_ok=True)

    file_path = user_dir / filename
    try:
        file_path.write_bytes(attachment_data)
        logger.info("attachment_saved", path=str(file_path), size=len(attachment_data))
        return file_path
    except OSError as e:
        logger.error("attachment_save_error", path=str(file_path), error=str(e), error_type=type(e).__name__)
        return None


async def process_attachments(
    attachments: List[dict],
    sender: str,
    session: aiohttp.ClientSession,
    signal_api_url: str,
    attachments_dir: Path,
) -> List[Path]:
    """Process and save image attachments from a message.

    Args:
        attachments: List of attachment dicts from Signal API
        sender: Phone number of sender
        session: aiohttp session for HTTP requests
        signal_api_url: Base URL of the Signal API
        attachments_dir: Base directory for attachments

    Returns:
        List of paths to saved image files
    """
    saved_images = []

    for attachment in attachments:
        content_type = attachment.get("contentType", "")
        attachment_id = attachment.get("id")

        if content_type not in SUPPORTED_IMAGE_TYPES:
            logger.debug("skipping_non_image_attachment", content_type=content_type)
            continue

        if not attachment_id:
            logger.warning("attachment_missing_id", attachment=attachment)
            continue

        data = await download_attachment(session, signal_api_url, attachment_id)
        if not data:
            continue

        file_path = save_attachment(data, content_type, sender, attachments_dir)
        if file_path:
            saved_images.append(file_path)

    return saved_images
