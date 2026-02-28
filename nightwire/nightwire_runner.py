"""nightwire AI assistant runner for any OpenAI-compatible provider."""

import asyncio
from typing import Optional, Tuple
from urllib.parse import urlparse

import aiohttp
import structlog

logger = structlog.get_logger()

class NightwireRunner:
    """Manages API execution for nightwire AI assistant.

    Supports any OpenAI-compatible provider via /v1/chat/completions.
    OpenAI and Grok are available as built-in convenience presets.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self._session: Optional[aiohttp.ClientSession] = None

        # Validate API URL scheme and hostname
        parsed = urlparse(self.api_url)
        if parsed.scheme != "https":
            logger.warning("insecure_api_url", url=self.api_url)
            raise ValueError("API URL must use HTTPS")
        if not parsed.hostname:
            logger.warning("invalid_api_url", url=self.api_url)
            raise ValueError("API URL must have a valid hostname")
        logger.info("nightwire_api_configured", host=parsed.hostname)

        if not self.api_key:
            logger.warning("nightwire_api_key_not_found")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create a shared aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the shared HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def ask_nightwire(
        self,
        message: str,
        timeout: int = 60,
    ) -> Tuple[bool, str]:
        """
        Send a query to the configured provider as nightwire AI assistant.

        Args:
            message: The user's message
            timeout: Request timeout in seconds

        Returns:
            Tuple of (success, response)
        """
        if not self.api_key:
            return False, "nightwire assistant is not configured. Set the API key for your provider in .env (see api_key_env in settings.yaml)."

        # Clean the message - remove nightwire/sidechannel prefix variations
        clean_message = message.strip()
        msg_lower = clean_message.lower()
        for variant in ["nightwire:", "nightwire,", "nightwire ", "hey nightwire ", "hi nightwire ", "ok nightwire ",
                         "sidechannel:", "sidechannel,", "sidechannel ", "hey sidechannel ", "hi sidechannel ", "ok sidechannel "]:
            if msg_lower.startswith(variant):
                clean_message = clean_message[len(variant):].strip()
                break

        if clean_message.lower() in ("nightwire", "sidechannel") or not clean_message:
            clean_message = "Hello, how can you help me?"

        system_prompt = """You are nightwire, an intelligent AI development assistant integrated into a Signal messaging bot.

Personality:
- Professional yet friendly
- Concise and helpful
- Technical but approachable
- Direct and efficient

Capabilities:
- Answer questions on any topic
- Provide technical guidance and recommendations
- Help with research and analysis
- Give coding advice and best practices

When responding:
- Be concise (responses go through Signal messages)
- Lead with the answer, then provide context if needed
- For coding/development tasks, remind the user that /select, /ask, and /do commands are available for hands-on Claude integration
- Be helpful and informative without being verbose

Response Style:
- Clear and organized
- Use bullet points for lists
- Keep responses under 4000 characters
- No emojis unless specifically requested"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": clean_message}
            ],
            "temperature": 0.7,
            "max_tokens": self.max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            session = await self._get_session()
            async with session.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    choices = data.get("choices")
                    if not choices or not isinstance(choices, list):
                        logger.error("nightwire_malformed_response", data_keys=list(data.keys()))
                        return False, "Received an unexpected response from the AI provider. Please try again."
                    response = choices[0].get("message", {}).get("content", "")
                    if not response:
                        logger.warning("nightwire_empty_response")
                        return False, "The AI provider returned an empty response. Please try again."
                    logger.info("nightwire_response_success", length=len(response))

                    # Truncate if too long for Signal
                    if len(response) > 4000:
                        response = response[:4000] + "\n\n[Response truncated...]"

                    return True, response
                else:
                    error_text = await resp.text()
                    logger.error("nightwire_api_error", status=resp.status, error=error_text[:500])
                    return False, f"nightwire encountered an error (status {resp.status}). Please try again."

        except asyncio.TimeoutError:
            logger.warning("nightwire_timeout", timeout=timeout)
            return False, "That query required more processing time than anticipated. Perhaps try a more specific question?"

        except Exception as e:
            logger.error("nightwire_exception", error=str(e))
            return False, "I'm experiencing a temporary issue. Please try again."


# Backwards compat alias
SidechannelRunner = NightwireRunner


# Global instance
_nightwire_runner: Optional[NightwireRunner] = None


def get_nightwire_runner(
    api_url: str = "",
    api_key: str = "",
    model: str = "",
    max_tokens: int = 1024,
) -> NightwireRunner:
    """Get or create the global nightwire runner instance."""
    global _nightwire_runner
    if _nightwire_runner is None:
        _nightwire_runner = NightwireRunner(
            api_url=api_url,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
        )
    return _nightwire_runner


# Backwards compat alias
get_sidechannel_runner = get_nightwire_runner
