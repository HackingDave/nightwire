"""Per-recipient FIFO message queue with rate limiting and retry.

Provides ordered, rate-limited message delivery to the Signal CLI REST API.
Replaces direct HTTP POST calls with a queued consumer model that handles
retries, timeouts, and per-recipient isolation.

Key classes:
    MessageQueue: Central queue manager with per-recipient consumers.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import aiohttp
import structlog

if TYPE_CHECKING:
    from .config import Config

logger = structlog.get_logger("nightwire.bot")


class MessageQueue:
    """Per-recipient FIFO message queue with rate limiting and retry.

    Each recipient gets an independent asyncio.Queue and consumer task.
    Consumers are auto-created on first enqueue and auto-cleaned after
    30 seconds of idle. Rate limiting enforces a configurable minimum
    interval between sends per recipient.

    Args:
        session: aiohttp session for HTTP requests.
        config: Nightwire Config instance.
        signal_api_url: Signal CLI REST API base URL.
        account: Signal account phone number.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        config: "Config",
        signal_api_url: str,
        account: str,
    ):
        self._session = session
        self._config = config
        self._signal_api_url = signal_api_url
        self._account = account
        self._queues: dict[str, asyncio.Queue] = {}
        self._consumers: dict[str, asyncio.Task] = {}
        self._rate_limiters: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._running = True

    async def enqueue(self, recipient: str, message: str) -> None:
        """Add message to per-recipient queue. Creates consumer if needed.

        Args:
            recipient: Phone number or UUID.
            message: Already-prefixed, already-split message text.
        """
        async with self._lock:
            if recipient not in self._queues or (
                recipient in self._consumers
                and self._consumers[recipient].done()
            ):
                self._queues[recipient] = asyncio.Queue()
                self._consumers[recipient] = asyncio.create_task(
                    self._consume(recipient)
                )

        await self._queues[recipient].put(message)

    async def _consume(self, recipient: str) -> None:
        """Consumer loop: rate-limited HTTP sends with retry.

        Processes messages from the recipient's queue until the queue
        is idle for 30 seconds. Rate limiting enforces minimum interval
        between sends. Uses try/finally to ensure cleanup runs even
        when cancelled during shutdown.
        """
        queue = self._queues[recipient]
        try:
            while self._running or not queue.empty():
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    if queue.empty():
                        break
                    continue

                now = asyncio.get_running_loop().time()
                last = self._rate_limiters.get(recipient, 0.0)
                min_interval = 1.0 / self._config.signal_send_rate_per_second
                wait = max(0.0, min_interval - (now - last))
                if wait > 0:
                    await asyncio.sleep(wait)

                await self._send_with_retry(recipient, message)
                self._rate_limiters[recipient] = asyncio.get_running_loop().time()
        finally:
            # Identity-based cleanup: runs even on CancelledError
            async with self._lock:
                if self._queues.get(recipient) is queue:
                    del self._queues[recipient]
                if self._consumers.get(recipient) is asyncio.current_task():
                    del self._consumers[recipient]
                self._rate_limiters.pop(recipient, None)

    async def _send_with_retry(self, recipient: str, message: str) -> bool:
        """Send HTTP POST with exponential backoff retry.

        If all retries are exhausted, the message is dropped and logged
        at error level. This is fire-and-forget semantics -- the caller
        does not receive the dropped message back.

        Args:
            recipient: Phone number or UUID.
            message: Message text to send.

        Returns:
            True if delivered, False if all retries exhausted (message dropped).
        """
        max_retries = self._config.signal_send_max_retries
        timeout = aiohttp.ClientTimeout(
            total=self._config.signal_send_timeout_seconds
        )

        for attempt in range(max_retries):
            try:
                url = f"{self._signal_api_url}/v2/send"
                payload = {
                    "message": message,
                    "number": self._account,
                    "recipients": [recipient],
                }
                async with self._session.post(
                    url, json=payload, timeout=timeout
                ) as resp:
                    if resp.status == 201:
                        return True
                    body = await resp.text()
                    logger.warning(
                        "send_retry",
                        attempt=attempt + 1,
                        status=resp.status,
                        body=body[:200],
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "send_timeout",
                    attempt=attempt + 1,
                    recipient="..." + recipient[-4:],
                )
            except Exception as e:
                logger.error(
                    "send_error", attempt=attempt + 1, error=str(e)
                )

            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)

        logger.error("send_exhausted", recipient="..." + recipient[-4:])
        return False

    async def send_typing_indicator(
        self, recipient: str, typing: bool = True
    ) -> None:
        """Send or clear typing indicator. Best-effort, never blocks.

        Args:
            recipient: Phone number or UUID.
            typing: True to start typing, False to clear.
        """
        url = f"{self._signal_api_url}/v1/typing-indicator/{self._account}"
        payload = {"recipient": recipient}
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            method = self._session.put if typing else self._session.delete
            async with method(url, json=payload, timeout=timeout) as resp:
                if resp.status not in (200, 204):
                    logger.debug(
                        "typing_indicator_failed", status=resp.status
                    )
        except Exception:
            pass  # Best-effort, never block

    async def close(self) -> None:
        """Drain queues and shut down consumers gracefully."""
        self._running = False
        async with self._lock:
            tasks = list(self._consumers.values())
        if tasks:
            await asyncio.wait(tasks, timeout=5.0)
            for task in tasks:
                if not task.done():
                    task.cancel()
