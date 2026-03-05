"""Logging configuration for nightwire.

Provides subsystem-level log file routing, secret sanitization,
and structlog + stdlib integration.

Subsystem hierarchy (stdlib dotted names, structlog wraps them):
    root              → ConsoleHandler (terminal, colored)
      └─ nightwire    → RotatingFileHandler → nightwire.log (combined, plain text)
           ├─ nightwire.bot        → RFH → bot.log
           ├─ nightwire.claude     → RFH → claude.log
           ├─ nightwire.autonomous → RFH → autonomous.log
           ├─ nightwire.memory     → RFH → memory.log
           ├─ nightwire.plugins    → RFH → plugins.log
           └─ nightwire.security   → RFH → security.log

Architecture: structlog processors handle filtering, timestamping,
and secret sanitization. ProcessorFormatter.wrap_for_formatter passes
the event dict to stdlib handlers. Each handler's ProcessorFormatter
does the final rendering — ConsoleRenderer(colors=True) for console,
ConsoleRenderer(colors=False) for files.
"""

import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import Any, Dict

import structlog

# Subsystem names — each gets its own RotatingFileHandler
SUBSYSTEMS = ("bot", "claude", "autonomous", "memory", "plugins", "security")

# stdlib logger name prefix for hierarchy-based propagation
LOGGER_PREFIX = "nightwire"

# ---------------------------------------------------------------------------
# Secret sanitization
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    # Anthropic API keys (sk-ant-...)
    re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"),
    # Generic sk- prefixed keys (OpenAI, etc.)
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    # xAI/Grok keys
    re.compile(r"xai-[a-zA-Z0-9_-]{20,}"),
    # Bearer token values in headers
    re.compile(r"Bearer\s+[a-zA-Z0-9_./-]{20,}"),
]

# Phone number pattern: E.164 format (+1234567890, 7-15 digits)
_PHONE_PATTERN = re.compile(r"\+\d{7,15}")

_REDACTED = "***REDACTED***"


def _scrub_value(value: str) -> str:
    """Scrub secrets and phone numbers from a single string value."""
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(_REDACTED, value)
    value = _PHONE_PATTERN.sub(lambda m: "..." + m.group(0)[-4:], value)
    return value


def sanitize_secrets(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """structlog processor that scrubs API keys and full phone numbers.

    Walks all string values in the event dict and replaces matches
    with redacted placeholders. Phone numbers are masked to last 4
    digits ("...1234"), matching the existing manual convention.

    This processor provides defense-in-depth — manual masking at
    call sites is preserved and this catches any leaks.
    """
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = _scrub_value(value)
        elif isinstance(value, (list, tuple)):
            event_dict[key] = type(value)(
                _scrub_value(v) if isinstance(v, str) else v
                for v in value
            )
        elif isinstance(value, dict):
            event_dict[key] = {
                k: _scrub_value(v) if isinstance(v, str) else v
                for k, v in value.items()
            }
    return event_dict


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(config=None) -> None:
    """Configure structured logging with subsystem file handlers.

    Sets up:
    1. Root logger: ConsoleHandler (colorized via ProcessorFormatter)
    2. "nightwire" logger: RotatingFileHandler → logs/nightwire.log (plain text)
    3. "nightwire.<subsystem>" loggers: individual RotatingFileHandlers (plain text)

    structlog processors handle filtering, timestamping, and secret
    sanitization. ProcessorFormatter.wrap_for_formatter passes the event
    dict to stdlib handlers. Each handler's ProcessorFormatter does the
    final rendering — colors for console, plain text for files.

    Args:
        config: Optional Config instance. First call (before config loads)
                uses sensible defaults with cache_logger_on_first_use=False.
                Second call (after config loads) uses real config and sets
                cache_logger_on_first_use=True.
    """
    if config is not None:
        log_dir = config.log_dir
        root_level_name = config.logging_level.upper()
        subsystem_levels = config.logging_subsystem_levels
        max_bytes = config.logging_max_file_size_mb * 1024 * 1024
        backup_count = config.logging_backup_count
        cache_loggers = True
    else:
        log_dir = Path(__file__).parent.parent / "logs"
        root_level_name = "INFO"
        subsystem_levels = {}
        max_bytes = 10 * 1024 * 1024  # 10 MB
        backup_count = 5
        cache_loggers = False

    root_level = getattr(logging, root_level_name, logging.INFO)

    # --- File handler setup (may fail on permissions/disk) ---
    file_handlers_ok = False
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handlers_ok = True
    except OSError as exc:
        # Fall back to console-only — bot must not crash on logging failure
        print(
            f"WARNING: Cannot create log directory {log_dir}: {exc}. "
            "Falling back to console-only logging.",
            file=sys.stderr,
        )

    # --- Formatters ---
    # File: plain text, no ANSI escape codes
    file_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
    )

    # Console: colored output
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
    )

    # --- stdlib logger setup ---

    # 1. Root logger: console only (colored via ProcessorFormatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Handlers filter by level
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(root_level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 2. "nightwire" parent logger: combined log file
    nw_logger = logging.getLogger(LOGGER_PREFIX)
    nw_logger.setLevel(logging.DEBUG)
    nw_logger.handlers.clear()
    nw_logger.propagate = True  # → root → console

    if file_handlers_ok:
        combined_handler = logging.handlers.RotatingFileHandler(
            log_dir / "nightwire.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        combined_handler.setLevel(root_level)
        combined_handler.setFormatter(file_formatter)
        nw_logger.addHandler(combined_handler)

    # 3. Per-subsystem loggers: individual log files
    for subsystem in SUBSYSTEMS:
        sub_logger = logging.getLogger(f"{LOGGER_PREFIX}.{subsystem}")
        sub_level_name = subsystem_levels.get(subsystem, "").upper()
        sub_level = getattr(logging, sub_level_name, root_level) if sub_level_name else root_level
        sub_logger.setLevel(sub_level)
        sub_logger.handlers.clear()
        sub_logger.propagate = True  # → "nightwire" → root

        if file_handlers_ok:
            sub_handler = logging.handlers.RotatingFileHandler(
                log_dir / f"{subsystem}.log",
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            sub_handler.setLevel(sub_level)
            sub_handler.setFormatter(file_formatter)
            sub_logger.addHandler(sub_handler)

    # --- structlog configuration ---
    # Processors handle filtering, timestamping, and sanitization.
    # wrap_for_formatter passes the event dict to stdlib handlers
    # for final rendering by each handler's ProcessorFormatter.
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            sanitize_secrets,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=cache_loggers,
    )
