"""Haiku-based summarization for memory context.

Uses Claude Haiku (via CLI) to summarize retrieved memories into
concise context that can be injected into prompts without bloating
the token count.
"""

import asyncio
from typing import List, Optional

import structlog

from .models import SearchResult

logger = structlog.get_logger()


class HaikuSummarizer:
    """Uses Claude Haiku to summarize context for injection.

    This is a lightweight subagent that summarizes retrieved memories
    into a concise format suitable for prompt injection.
    """

    def __init__(
        self,
        claude_path: str = None,
        model: str = "claude-3-haiku-20240307",
        timeout: int = 30
    ):
        """Initialize the summarizer.

        Args:
            claude_path: Path to Claude CLI binary (auto-detected if None)
            model: Model to use for summarization
            timeout: Timeout in seconds for summarization
        """
        if claude_path is None:
            # Auto-detect claude path
            import shutil
            from pathlib import Path
            claude_path = shutil.which("claude")
            if not claude_path:
                home_local = Path.home() / ".local" / "bin" / "claude"
                if home_local.exists():
                    claude_path = str(home_local)
                else:
                    claude_path = "claude"
        self.claude_path = claude_path
        self.model = model
        self.timeout = timeout

    async def summarize_for_context(
        self,
        retrieved_memories: List[SearchResult],
        current_query: str,
        max_output_tokens: int = 500
    ) -> Optional[str]:
        """Summarize retrieved memories relevant to current query.

        Args:
            retrieved_memories: List of relevant search results
            current_query: The current user query/task
            max_output_tokens: Maximum tokens in output

        Returns:
            Summarized context string, or None if summarization fails
        """
        if not retrieved_memories:
            return None

        # Build input for Haiku
        memory_sections = []
        for mem in retrieved_memories[:10]:  # Limit input
            date = mem.timestamp.strftime("%Y-%m-%d")
            role = "User" if mem.role == "user" else "Assistant"
            content = mem.content[:500]  # Truncate individual memories
            memory_sections.append(f"[{date}] {role}: {content}")

        memory_text = "\n---\n".join(memory_sections)

        prompt = f"""You are a context summarization assistant. Your job is to extract and summarize the most relevant information from past conversations.

Given these past conversation snippets:

{memory_text}

The user is now asking about or working on: "{current_query}"

Summarize ONLY the information from the past conversations that is directly relevant to the current query. Focus on:
- Previous decisions or choices made
- Technical preferences or patterns established
- Key facts or context that would help with the current task
- Any warnings or lessons learned

Output a concise summary (max {max_output_tokens} tokens) using bullet points.
If nothing is relevant, say "No relevant past context found."
"""

        try:
            result = await self._run_claude(prompt, max_output_tokens)
            return result
        except Exception as e:
            logger.warning("haiku_summarization_failed", error=str(e))
            return None

    async def _run_claude(self, prompt: str, max_tokens: int) -> Optional[str]:
        """Run Claude CLI with Haiku model.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum output tokens

        Returns:
            Claude's response, or None on failure
        """
        cmd = [
            self.claude_path,
            "--model", self.model,
            "--print",
            "--max-tokens", str(max_tokens),
        ]

        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=prompt.encode("utf-8")),
                timeout=self.timeout
            )

            output = stdout.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                logger.warning(
                    "haiku_cli_error",
                    returncode=process.returncode,
                    stderr=stderr.decode("utf-8", errors="replace")[:200]
                )
                return None

            return output

        except asyncio.TimeoutError:
            if process is not None:
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
            logger.warning("haiku_timeout", timeout=self.timeout)
            return None
        except FileNotFoundError:
            logger.error("claude_cli_not_found", path=self.claude_path)
            return None
        except Exception as e:
            logger.error("haiku_error", error=str(e))
            return None


# Global summarizer instance
_summarizer: Optional[HaikuSummarizer] = None


def get_haiku_summarizer(claude_path: Optional[str] = None) -> HaikuSummarizer:
    """Get or create the global Haiku summarizer instance.

    Args:
        claude_path: Path to Claude CLI (only used on first call)

    Returns:
        HaikuSummarizer instance
    """
    global _summarizer
    if _summarizer is None:
        _summarizer = HaikuSummarizer(
            claude_path=claude_path or "/home/hackingdave/.local/bin/claude"
        )
    return _summarizer
