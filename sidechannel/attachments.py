"""Attachment handling for Signal bot - download, validate, and save attachments."""

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import structlog

logger = structlog.get_logger()

MAX_ATTACHMENT_SIZE = 50_000_000  # 50MB

# Supported image MIME types for Claude vision
SUPPORTED_IMAGE_TYPES: Dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

# Common MIME type to extension mappings for non-image files
MIME_TYPE_EXTENSIONS: Dict[str, str] = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "application/zip": ".zip",
    "application/x-yaml": ".yaml",
    "text/yaml": ".yaml",
    "text/markdown": ".md",
}

# Allowed file extensions for generic file attachments
ALLOWED_FILE_EXTENSIONS = {
    ".evtx", ".log", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".md", ".pdf", ".zip", ".gz", ".tar", ".pcap", ".cap",
    ".html", ".htm", ".rtf", ".doc", ".docx", ".xls", ".xlsx",
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs",
    ".conf", ".cfg", ".ini", ".toml",
}


async def download_attachment(
    session: aiohttp.ClientSession,
    signal_api_url: str,
    attachment_id: str,
    original_filename: Optional[str] = None,
) -> Optional[bytes]:
    """Download an attachment from Signal API.

    Args:
        session: aiohttp session for HTTP requests
        signal_api_url: Base URL of the Signal API
        attachment_id: The Signal attachment ID
        original_filename: Original filename; used to construct a fallback
            download URL if the bare ID returns 404 (signal-cli-rest-api
            stores some attachments as ``{id}.{ext}``).

    Returns:
        Attachment bytes or None if download fails
    """
    # Validate attachment_id to prevent SSRF — allow dots for IDs that
    # include a file extension (e.g. "K5xMevmK416G8_FSbt1s.evtx").
    if not re.match(r'^[a-zA-Z0-9_.\-=]+$', str(attachment_id)):
        logger.warning("invalid_attachment_id", attachment_id=str(attachment_id)[:50])
        return None

    # Build candidate URLs: the bare ID first, then ID+extension as fallback.
    urls_to_try = [f"{signal_api_url}/v1/attachments/{attachment_id}"]
    if original_filename and "." not in attachment_id:
        ext = Path(original_filename).suffix
        if ext:
            urls_to_try.append(f"{signal_api_url}/v1/attachments/{attachment_id}{ext}")

    for url in urls_to_try:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    chunks = []
                    total = 0
                    async for chunk in resp.content.iter_chunked(8192):
                        total += len(chunk)
                        if total > MAX_ATTACHMENT_SIZE:
                            logger.warning("attachment_too_large_streaming", attachment_id=attachment_id)
                            return None
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    logger.info("attachment_downloaded", id=attachment_id, size=len(data), url=url)
                    return data
                elif resp.status == 404 and url != urls_to_try[-1]:
                    logger.debug("attachment_not_found_trying_fallback", id=attachment_id)
                    continue
                else:
                    logger.error("attachment_download_failed", id=attachment_id, status=resp.status)
                    return None
        except aiohttp.ClientError as e:
            logger.error("attachment_download_error", id=attachment_id, error=str(e), error_type=type(e).__name__)
            return None

    return None


def _resolve_extension(content_type: str, original_filename: Optional[str] = None) -> Optional[str]:
    """Resolve file extension from content type and/or original filename.

    Args:
        content_type: MIME type of the attachment
        original_filename: Original filename from the attachment metadata

    Returns:
        File extension (e.g. '.evtx') or None if type is not allowed
    """
    # Check image types first
    if content_type in SUPPORTED_IMAGE_TYPES:
        return SUPPORTED_IMAGE_TYPES[content_type]

    # Try to get extension from original filename (use basename to prevent traversal)
    if original_filename:
        safe_name = Path(original_filename).name
        ext = Path(safe_name).suffix.lower()
        if ext and ext in ALLOWED_FILE_EXTENSIONS:
            return ext

    # Fall back to MIME type mapping
    if content_type in MIME_TYPE_EXTENSIONS:
        return MIME_TYPE_EXTENSIONS[content_type]

    return None


def save_attachment(
    attachment_data: bytes,
    content_type: str,
    sender: str,
    attachments_dir: Path,
    original_filename: Optional[str] = None,
) -> Optional[Path]:
    """Save attachment data to disk.

    Args:
        attachment_data: Raw attachment bytes
        content_type: MIME type of the attachment
        sender: Phone number of sender (for organizing files)
        attachments_dir: Base directory for attachments
        original_filename: Original filename from Signal attachment metadata

    Returns:
        Path to saved file or None if unsupported type
    """
    ext = _resolve_extension(content_type, original_filename)
    if ext is None:
        logger.warning("unsupported_attachment_type", content_type=content_type,
                       filename=original_filename)
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{timestamp}_{unique_id}{ext}"

    safe_sender = re.sub(r'[^\d]', '', sender)
    if not safe_sender:
        safe_sender = "unknown"
    user_dir = attachments_dir / safe_sender
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
    """Process and save attachments from a message.

    Supports both image attachments (for Claude vision) and generic file
    attachments (e.g. .evtx, .log, .csv) that are saved to disk so Claude
    can read them from the project context.

    Args:
        attachments: List of attachment dicts from Signal API
        sender: Phone number of sender
        session: aiohttp session for HTTP requests
        signal_api_url: Base URL of the Signal API
        attachments_dir: Base directory for attachments

    Returns:
        List of paths to saved files
    """
    saved_files = []

    for attachment in attachments:
        content_type = attachment.get("contentType", "")
        attachment_id = attachment.get("id")
        original_filename = attachment.get("filename")

        # Check if this file type is supported (image or allowed file extension)
        ext = _resolve_extension(content_type, original_filename)
        if ext is None:
            logger.debug("skipping_unsupported_attachment", content_type=content_type,
                         filename=original_filename)
            continue

        if not attachment_id:
            logger.warning("attachment_missing_id", attachment=attachment)
            continue

        data = await download_attachment(session, signal_api_url, attachment_id,
                                         original_filename=original_filename)
        if not data:
            continue

        file_path = save_attachment(data, content_type, sender, attachments_dir,
                                    original_filename=original_filename)
        if file_path:
            saved_files.append(file_path)

    return saved_files
