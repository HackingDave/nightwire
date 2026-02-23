"""Daily Bible verse plugin for sidechannel."""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import aiohttp

from sidechannel.plugin_base import (
    CommandHandler,
    HelpSection,
    PluginContext,
    SidechannelPlugin,
)

ET = ZoneInfo("America/New_York")

VERSE_PROMPT = (
    "Give me a random motivational Bible verse. Include the full verse text "
    "with the book, chapter, and verse reference. Then provide a brief, "
    "uplifting explanation of what this verse means and how it can be applied "
    "to daily life. Keep the total response under 2000 characters. "
    "Pick a different verse each time - draw from both Old and New Testament. "
    "Format it nicely for a text message."
)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
GROK_API_URL = "https://api.x.ai/v1/chat/completions"


class DailyVersePlugin(SidechannelPlugin):
    """Scheduled daily Bible verse delivery plugin."""

    name = "daily_verse"
    description = "Scheduled daily Bible verse delivery"
    version = "1.0.0"

    def __init__(self, ctx: PluginContext):
        super().__init__(ctx)
        self._schedule_hour: int = ctx.get_config("hour", 8)
        self._schedule_minute: int = ctx.get_config("minute", 0)
        self._recipients: List[str] = ctx.get_config(
            "recipients", ctx.allowed_numbers
        )
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None

    # -- Plugin interface ---------------------------------------------------

    def commands(self) -> Dict[str, CommandHandler]:
        """Register /verse command."""
        return {"verse": self._handle_verse}

    def help_sections(self) -> List[HelpSection]:
        """Return help text for the daily verse plugin."""
        return [
            HelpSection(
                title="Daily Verse",
                commands={"verse": "Get a Bible verse on demand"},
            )
        ]

    async def on_start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        self.ctx.logger.info(
            "daily_verse_scheduler_started",
            hour=self._schedule_hour,
            minute=self._schedule_minute,
            recipients=len(self._recipients),
        )

    async def on_stop(self) -> None:
        """Cancel the scheduler task and clean up."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self.ctx.logger.info("daily_verse_scheduler_stopped")

    # -- Internal -----------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create a shared aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _handle_verse(self, sender: str, args: str) -> str:
        """Handle the /verse command: fetch and return a Bible verse."""
        result = await self._fetch_verse()
        if result is None:
            return (
                "Daily verse is not available. "
                "No API key is configured (OPENAI_API_KEY or GROK_API_KEY)."
            )
        return result

    async def _fetch_verse(self) -> Optional[str]:
        """Fetch a Bible verse from OpenAI or Grok API.

        Returns the verse text, or None if no API key is configured.
        """
        openai_key = self.ctx.get_env("OPENAI_API_KEY")
        grok_key = self.ctx.get_env("GROK_API_KEY")

        if openai_key:
            return await self._query_openai(openai_key)
        elif grok_key:
            return await self._query_grok(grok_key)
        else:
            return None

    async def _query_openai(self, api_key: str) -> str:
        """Query OpenAI chat completions API."""
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": VERSE_PROMPT}],
            "max_tokens": 1024,
        }
        try:
            async with session.post(
                OPENAI_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=90)
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    self.ctx.logger.error("daily_verse_api_error", status=resp.status, error=error_text[:200])
                    return f"Verse unavailable (API error {resp.status})"
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            self.ctx.logger.error("daily_verse_openai_error", error=str(e))
            return f"Error fetching verse: {e}"

    async def _query_grok(self, api_key: str) -> str:
        """Query Grok (xAI) chat completions API."""
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "grok-3-mini",
            "messages": [{"role": "user", "content": VERSE_PROMPT}],
            "max_tokens": 1024,
        }
        try:
            async with session.post(
                GROK_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=90)
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    self.ctx.logger.error("daily_verse_api_error", status=resp.status, error=error_text[:200])
                    return f"Verse unavailable (API error {resp.status})"
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            self.ctx.logger.error("daily_verse_grok_error", error=str(e))
            return f"Error fetching verse: {e}"

    def _seconds_until_next(self) -> float:
        """Calculate seconds until the next scheduled send time in ET."""
        now = datetime.now(ET)
        target = now.replace(
            hour=self._schedule_hour,
            minute=self._schedule_minute,
            second=0,
            microsecond=0,
        )
        if now >= target:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def _run_loop(self) -> None:
        """Main scheduler loop: sleep until send time, send verse, repeat."""
        while self._running:
            try:
                delay = self._seconds_until_next()
                self.ctx.logger.info(
                    "daily_verse_next_send",
                    delay_seconds=int(delay),
                    delay_hours=round(delay / 3600, 1),
                )
                await asyncio.sleep(delay)

                if not self._running:
                    break

                await self._send_daily_verse()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.ctx.logger.error(
                    "daily_verse_loop_error",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Wait a minute before retrying to avoid tight error loops
                await asyncio.sleep(60)

    async def _send_daily_verse(self) -> None:
        """Fetch a Bible verse and send it to all recipients."""
        self.ctx.logger.info("daily_verse_fetching")

        verse = await self._fetch_verse()
        if verse is None:
            self.ctx.logger.error("daily_verse_no_api_key")
            return

        for recipient in self._recipients:
            try:
                await self.ctx.send_message(recipient, verse)
                self.ctx.logger.info(
                    "daily_verse_sent", recipient=recipient[:6] + "..."
                )
            except Exception as e:
                self.ctx.logger.error(
                    "daily_verse_send_error",
                    recipient=recipient[:6] + "...",
                    error=str(e),
                    error_type=type(e).__name__,
                )
