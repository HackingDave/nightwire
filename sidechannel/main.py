"""Main entry point for sidechannel."""

import asyncio
import logging
import signal
import sys
from pathlib import Path

import structlog


def setup_logging():
    """Configure structured logging."""
    # Configure standard logging first
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
        stream=sys.stdout
    )

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
            structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def main():
    """Main async entry point."""
    setup_logging()
    logger = structlog.get_logger()

    logger.info("sidechannel_starting", version="1.5.0")

    # Import here to ensure logging is configured first
    from .config import get_config
    from .bot import SignalBot

    config = get_config()
    config.validate()

    bot = SignalBot()

    # Setup graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def handle_shutdown(sig):
        logger.info("shutdown_signal_received", signal=sig.name)
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_shutdown, sig)

    # Run the bot
    try:
        bot_task = asyncio.create_task(bot.run())

        # Wait for shutdown signal
        await shutdown_event.wait()

        # Cancel the bot task
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass

    except Exception as e:
        logger.error("bot_error", error=str(e))
        raise
    finally:
        await bot.stop()
        logger.info("sidechannel_stopped")


def run():
    """Synchronous entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
