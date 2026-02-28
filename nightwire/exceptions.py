"""Custom exception hierarchy for Nightwire.

Provides precise error classification across all subsystems, enabling
targeted error handling, retry decisions, and better debugging context.

The ErrorCategory enum (originally from claude_runner.py) is re-exported
here as the canonical project-wide location.
"""

from enum import Enum
from typing import Any, Optional


class ErrorCategory(str, Enum):
    """Classification of errors for retry decisions."""
    TRANSIENT = "transient"          # Worth retrying (timeout, rate limit, process crash)
    PERMANENT = "permanent"          # Not worth retrying (bad input, token limit)
    INFRASTRUCTURE = "infrastructure"  # CLI not found, env issues
    RATE_LIMITED = "rate_limited"     # Subscription/capacity rate limits


class SignalBotError(Exception):
    """Base exception for all Nightwire errors.

    All custom exceptions inherit from this, enabling broad catches
    when needed while still allowing precise handling per subsystem.

    Attributes:
        message: Human-readable error description.
        category: Error classification for retry/escalation decisions.
        module: Originating module name (e.g. "autonomous.executor").
        context: Arbitrary key-value pairs for structured logging.
    """

    def __init__(
        self,
        message: str = "",
        *,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        self.message = message
        self.category = category
        self.module = module
        self.context = context
        super().__init__(message)

    @property
    def is_retryable(self) -> bool:
        """Whether this error is worth retrying."""
        return self.category == ErrorCategory.TRANSIENT

    def __str__(self) -> str:
        parts = [self.message or self.__class__.__name__]
        if self.module:
            parts.append(f"[module={self.module}]")
        if self.context:
            ctx = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"({ctx})")
        return " ".join(parts)

    def __repr__(self) -> str:
        cls = self.__class__.__name__
        return (
            f"{cls}({self.message!r}, category={self.category.value!r}, "
            f"module={self.module!r})"
        )


# Backward-compatible aliases
NightwireError = SignalBotError
SidechannelError = SignalBotError


# ---------------------------------------------------------------------------
# Autonomous subsystem exceptions
# ---------------------------------------------------------------------------

class AutonomousTaskError(SignalBotError):
    """Error during autonomous task execution.

    Attributes:
        task_id: ID of the task that failed (if known).
    """

    def __init__(
        self,
        message: str = "",
        *,
        task_id: Optional[int] = None,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        self.task_id = task_id
        super().__init__(
            message, category=category, module=module or "autonomous", **context
        )


class VerificationError(AutonomousTaskError):
    """Error during independent task verification.

    Inherits from AutonomousTaskError because verification is part of
    the autonomous task lifecycle.
    """

    def __init__(
        self,
        message: str = "",
        *,
        task_id: Optional[int] = None,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        super().__init__(
            message,
            task_id=task_id,
            category=category,
            module=module or "autonomous.verifier",
            **context,
        )


class QualityGateError(AutonomousTaskError):
    """Error during quality gate checks (tests, lint, typecheck).

    Attributes:
        gate_name: Which gate failed (e.g. "tests", "lint", "typecheck").
    """

    def __init__(
        self,
        message: str = "",
        *,
        task_id: Optional[int] = None,
        gate_name: Optional[str] = None,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        self.gate_name = gate_name
        super().__init__(
            message,
            task_id=task_id,
            category=category,
            module=module or "autonomous.quality_gates",
            **context,
        )


class TaskDependencyError(AutonomousTaskError):
    """A task's dependencies could not be resolved."""

    def __init__(
        self,
        message: str = "",
        *,
        task_id: Optional[int] = None,
        depends_on: Optional[list[int]] = None,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        self.depends_on = depends_on
        super().__init__(
            message,
            task_id=task_id,
            category=category,
            module=module or "autonomous.loop",
            **context,
        )


# ---------------------------------------------------------------------------
# Claude / Nightwire runner exceptions
# ---------------------------------------------------------------------------

class ClaudeRunnerError(SignalBotError):
    """Error from the Claude CLI subprocess runner.

    Attributes:
        return_code: Process exit code (if available).
    """

    def __init__(
        self,
        message: str = "",
        *,
        return_code: Optional[int] = None,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        self.return_code = return_code
        super().__init__(
            message, category=category, module=module or "claude_runner", **context
        )


class NightwireRunnerError(SignalBotError):
    """Error from the Nightwire runner."""

    def __init__(
        self,
        message: str = "",
        *,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        super().__init__(
            message, category=category, module=module or "nightwire_runner", **context
        )


# Backward-compatible alias
SidechannelRunnerError = NightwireRunnerError


# ---------------------------------------------------------------------------
# Memory subsystem exceptions
# ---------------------------------------------------------------------------

class MemorySystemError(SignalBotError):
    """Error in the memory/conversation storage system."""

    def __init__(
        self,
        message: str = "",
        *,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        super().__init__(
            message, category=category, module=module or "memory", **context
        )


# ---------------------------------------------------------------------------
# Configuration exceptions
# ---------------------------------------------------------------------------

class ConfigurationError(SignalBotError):
    """Invalid or missing configuration.

    Defaults to INFRASTRUCTURE because config issues are environmental
    and won't resolve by retrying.
    """

    def __init__(
        self,
        message: str = "",
        *,
        setting_name: Optional[str] = None,
        category: ErrorCategory = ErrorCategory.INFRASTRUCTURE,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        self.setting_name = setting_name
        super().__init__(
            message, category=category, module=module or "config", **context
        )


# ---------------------------------------------------------------------------
# Database exceptions
# ---------------------------------------------------------------------------

class DatabaseError(SignalBotError):
    """Error during database operations.

    Attributes:
        operation: The DB operation that failed (e.g. "insert", "query").
        table: The table involved (if known).
    """

    def __init__(
        self,
        message: str = "",
        *,
        operation: Optional[str] = None,
        table: Optional[str] = None,
        category: ErrorCategory = ErrorCategory.TRANSIENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        self.operation = operation
        self.table = table
        super().__init__(
            message, category=category, module=module or "database", **context
        )


# ---------------------------------------------------------------------------
# Security exceptions
# ---------------------------------------------------------------------------

class SecurityError(SignalBotError):
    """Security violation or suspicious activity detected.

    Defaults to PERMANENT -- security violations should not normally be retried.
    """

    def __init__(
        self,
        message: str = "",
        *,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        super().__init__(
            message, category=category, module=module or "security", **context
        )


# ---------------------------------------------------------------------------
# Additional exceptions
# ---------------------------------------------------------------------------

class GrokRunnerError(SignalBotError):
    """Error from the Grok/nightwire AI assistant runner."""

    def __init__(
        self,
        message: str = "",
        *,
        category: ErrorCategory = ErrorCategory.PERMANENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        super().__init__(
            message, category=category, module=module or "grok_runner", **context
        )


class MusicControlError(SignalBotError):
    """Error from a music control plugin."""

    def __init__(
        self,
        message: str = "",
        *,
        category: ErrorCategory = ErrorCategory.TRANSIENT,
        module: Optional[str] = None,
        **context: Any,
    ) -> None:
        super().__init__(
            message, category=category, module=module or "music", **context
        )
