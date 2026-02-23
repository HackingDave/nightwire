"""sidechannel AI assistant runner with configurable provider (OpenAI or Grok)."""

import asyncio
from typing import Optional, Tuple

import aiohttp
import structlog

logger = structlog.get_logger()

GROK_API_URL = "https://api.x.ai/v1/chat/completions"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

class SidechannelRunner:
    """Manages API execution for sidechannel AI assistant.

    Supports both OpenAI and Grok (X.AI) as backend providers.
    Both use the identical /v1/chat/completions schema.
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

        if not self.api_key:
            logger.warning("sidechannel_api_key_not_found")

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

    async def ask_jarvis(
        self,
        message: str,
        timeout: int = 60,
    ) -> Tuple[bool, str]:
        """
        Send a query to the configured provider as sidechannel AI assistant.

        Args:
            message: The user's message
            timeout: Request timeout in seconds

        Returns:
            Tuple of (success, response)
        """
        if not self.api_key:
            return False, "sidechannel assistant is not configured. Set OPENAI_API_KEY or GROK_API_KEY in your .env file."

        # Clean the message - remove sidechannel prefix variations
        clean_message = message.strip()
        msg_lower = clean_message.lower()
        for variant in ["sidechannel:", "sidechannel,", "sidechannel ", "hey sidechannel ", "hi sidechannel ", "ok sidechannel "]:
            if msg_lower.startswith(variant):
                clean_message = clean_message[len(variant):].strip()
                break

        if clean_message.lower() == "sidechannel" or not clean_message:
            clean_message = "Hello, how can you help me?"

        system_prompt = """You are sidechannel, an intelligent AI development assistant integrated into a Signal messaging bot.

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
                    response = data["choices"][0]["message"]["content"]
                    logger.info("sidechannel_response_success", length=len(response))

                    # Truncate if too long for Signal
                    if len(response) > 4000:
                        response = response[:4000] + "\n\n[Response truncated...]"

                    return True, response
                else:
                    error_text = await resp.text()
                    logger.error("sidechannel_api_error", status=resp.status, error=error_text[:500])
                    return False, f"sidechannel encountered an error (status {resp.status}). Please try again."

        except asyncio.TimeoutError:
            logger.warning("sidechannel_timeout", timeout=timeout)
            return False, "That query required more processing time than anticipated. Perhaps try a more specific question?"

        except Exception as e:
            logger.error("sidechannel_exception", error=str(e))
            return False, "I'm experiencing a temporary issue. Please try again."


# Global instance
_sidechannel_runner: Optional[SidechannelRunner] = None


def get_sidechannel_runner(
    api_url: str = "",
    api_key: str = "",
    model: str = "",
    max_tokens: int = 1024,
) -> SidechannelRunner:
    """Get or create the global sidechannel runner instance."""
    global _sidechannel_runner
    if _sidechannel_runner is None:
        _sidechannel_runner = SidechannelRunner(
            api_url=api_url,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
        )
    return _sidechannel_runner
