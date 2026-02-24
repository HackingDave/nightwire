"""Signal bot implementation for sidechannel."""

import asyncio
import hashlib
import json
import time as _time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import structlog

from .config import get_config
from .security import is_authorized, sanitize_input, check_rate_limit
from .claude_runner import get_runner
from .project_manager import get_project_manager
from .memory import MemoryManager, MemoryCommands
from .autonomous import AutonomousManager, AutonomousCommands
from .plugin_loader import PluginLoader
from .prd_builder import clean_json_string, extract_balanced_json, parse_prd_json

logger = structlog.get_logger()


def _log_task_exception(task: asyncio.Task):
    """Log exceptions from fire-and-forget tasks instead of silently swallowing them."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("background_task_failed", error=str(exc), exc_type=type(exc).__name__)


class SignalBot:
    """Signal bot that interfaces with Claude."""

    def __init__(self):
        self.config = get_config()
        self.runner = get_runner()
        self.project_manager = get_project_manager()

        # sidechannel assistant runner is optional (supports OpenAI and Grok providers)
        self.sidechannel_runner = None
        if self.config.sidechannel_assistant_enabled:
            try:
                from .sidechannel_runner import SidechannelRunner
                self.sidechannel_runner = SidechannelRunner(
                    api_url=self.config.sidechannel_assistant_api_url,
                    api_key=self.config.sidechannel_assistant_api_key,
                    model=self.config.sidechannel_assistant_model,
                    max_tokens=self.config.sidechannel_assistant_max_tokens,
                )
                logger.info(
                    "sidechannel_runner_initialized",
                    provider=self.config.sidechannel_assistant_provider,
                    model=self.config.sidechannel_assistant_model,
                )
            except Exception as e:
                logger.warning("sidechannel_runner_unavailable", error=str(e))

        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        self.account: Optional[str] = None
        self._processed_messages = OrderedDict()  # Dedup: msg_hash -> timestamp

        # Task state tracking - prevents blocking and allows cancellation
        self._current_task: Optional[asyncio.Task] = None
        self._current_task_description: Optional[str] = None
        self._current_task_sender: Optional[str] = None
        self._current_task_start: Optional[datetime] = None
        self._current_task_step: Optional[str] = None  # Current step in the task

        # Memory system
        memory_db_path = Path(self.config.config_dir).parent / "data" / "memory.db"
        self.memory = MemoryManager(
            db_path=memory_db_path,
            session_timeout_minutes=self.config.memory_session_timeout,
            max_context_tokens=self.config.memory_max_context_tokens
        )
        self.memory_commands = MemoryCommands(self.memory)

        # Autonomous system (initialized after memory in start())
        self.autonomous_manager: Optional[AutonomousManager] = None
        self.autonomous_commands: Optional[AutonomousCommands] = None

        # Plugin system
        plugins_data_dir = Path(self.config.config_dir).parent / "data" / "plugins"
        plugins_data_dir.mkdir(parents=True, exist_ok=True)
        self.plugin_loader = PluginLoader(
            plugins_dir=self.config.plugins_dir,
            settings=self.config.settings,
            send_message=self._send_message,
            allowed_numbers=self.config.allowed_numbers,
            data_dir=plugins_data_dir,
        )
        self.plugin_loader.discover_and_load()

    async def start(self):
        """Start the bot."""
        self.session = aiohttp.ClientSession()
        self.running = True

        # Warn if non-localhost Signal API is not using HTTPS
        parsed = urlparse(self.config.signal_api_url)
        if parsed.hostname not in ("127.0.0.1", "localhost", "::1") and parsed.scheme != "https":
            logger.warning("insecure_signal_api_url", url=self.config.signal_api_url,
                           msg="Non-localhost Signal API should use HTTPS")

        # Get the registered account
        await self._get_account()

        # Initialize memory system
        await self.memory.initialize()

        # Initialize autonomous system (uses same DB connection)
        async def autonomous_notify(phone: str, message: str):
            await self._send_message(phone, message)

        self.autonomous_manager = AutonomousManager(
            db_connection=self.memory.db._conn,
            progress_callback=autonomous_notify,
            poll_interval=self.config.autonomous_poll_interval,
            run_quality_gates=self.config.autonomous_quality_gates,
        )
        self.autonomous_commands = AutonomousCommands(
            manager=self.autonomous_manager,
            get_current_project=lambda phone: (
                self.project_manager.get_current_project(phone),
                self.project_manager.get_current_path(phone),
            ),
        )

        # Start plugins
        await self.plugin_loader.start_all()

        logger.info("bot_started", account=self.account)

    async def stop(self):
        """Stop the bot."""
        if not self.running:
            return
        self.running = False
        # Stop plugins
        await self.plugin_loader.stop_all()
        if self.autonomous_manager:
            await self.autonomous_manager.stop_loop()
        if self.sidechannel_runner:
            await self.sidechannel_runner.close()
        if self.session:
            await self.session.close()
        await self.runner.cancel()
        await self.memory.close()
        logger.info("bot_stopped")

    async def _get_account(self):
        """Get the registered Signal account with retry.

        Retries on connection errors and timeouts (signal-api may still be
        starting).  Does NOT retry when signal-api responds 200 with an
        empty account list (it's up but unconfigured).
        """
        url = f"{self.config.signal_api_url}/v1/accounts"
        max_attempts = 12
        base_delay = 5
        max_delay = 15

        for attempt in range(1, max_attempts + 1):
            try:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        accounts = await resp.json()
                        if accounts:
                            self.account = accounts[0]
                            logger.info("account_found", account=self.account)
                            return
                        else:
                            # Signal API is up but no accounts registered — don't retry
                            logger.error("no_accounts_registered")
                            return
                    else:
                        logger.warning(
                            "accounts_request_failed",
                            status=resp.status,
                            attempt=attempt,
                            max_attempts=max_attempts,
                        )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < max_attempts:
                    delay = min(base_delay * attempt, max_delay)
                    logger.warning(
                        "accounts_request_retry",
                        error=str(e),
                        attempt=attempt,
                        max_attempts=max_attempts,
                        retry_in=delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "accounts_request_error",
                        error=str(e),
                        attempts_exhausted=max_attempts,
                    )
                    return
            except Exception as e:
                logger.error("accounts_request_error", error=str(e))
                return

    async def _send_message(self, recipient: str, message: str):
        """Send a message via Signal."""
        if not self.account:
            logger.error("no_account_for_sending")
            return

        # SECURITY: Double-check recipient is authorized before sending
        if not is_authorized(recipient):
            logger.warning("blocked_send_to_unauthorized", recipient="..." + recipient[-4:])
            return

        # Add sidechannel identifier to all messages
        message = f"[sidechannel] {message}"

        try:
            url = f"{self.config.signal_api_url}/v2/send"
            payload = {
                "number": self.account,
                "recipients": [recipient],
                "message": message
            }

            async with self.session.post(url, json=payload) as resp:
                if resp.status == 201:
                    logger.info("message_sent", recipient="..." + recipient[-4:])
                else:
                    text = await resp.text()
                    logger.error("send_failed", status=resp.status, response=text)

        except Exception as e:
            logger.error("send_error", error=str(e))

    async def _handle_command(self, command: str, args: str, sender: str) -> str:
        """Handle a bot command."""
        command = command.lower()

        if command == "help":
            return self._get_help()

        elif command == "projects":
            return self.project_manager.list_projects(sender)

        elif command == "select":
            if not args:
                return "Usage: /select <project_name>"
            success, msg = self.project_manager.select_project(args, sender)
            if success:
                self.runner.set_project(self.project_manager.get_current_path(sender))
            return msg

        elif command == "status":
            status = self.project_manager.get_status(sender)
            # Add running task info (direct /do tasks)
            if self._current_task and not self._current_task.done():
                elapsed = ""
                if self._current_task_start:
                    mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
                    elapsed = f" ({mins}m)"
                desc = self._current_task_description[:120] if self._current_task_description else "unknown"
                status += f"\n\nActive Task{elapsed}: {desc}"
                if self._current_task_step:
                    status += f"\nStep: {self._current_task_step}"

            # Add autonomous loop status
            try:
                loop_status = await self.autonomous_manager.get_loop_status()
                if loop_status.is_running:
                    auto_info = "\n\nAutonomous Loop: Running"
                    if loop_status.current_task_id:
                        current_task = await self.autonomous_manager.db.get_task(loop_status.current_task_id)
                        if current_task:
                            elapsed_auto = ""
                            if current_task.started_at:
                                mins = int((datetime.now() - current_task.started_at).total_seconds() / 60)
                                elapsed_auto = f" ({mins}m)"
                            auto_info += f"\nCurrent: {current_task.title[:50]}{elapsed_auto}"
                    auto_info += f"\nQueued: {loop_status.tasks_queued}"
                    auto_info += f" | Done: {loop_status.tasks_completed_today}"
                    if loop_status.tasks_failed_today > 0:
                        auto_info += f" | Failed: {loop_status.tasks_failed_today}"
                    status += auto_info
                elif loop_status.is_paused:
                    status += "\n\nAutonomous Loop: Paused"
            except Exception as e:
                logger.warning("status_autonomous_error", error=str(e))

            return status

        elif command == "add":
            if not args:
                return "Usage: /add <project_name> [path] [description]"
            parts = args.split(maxsplit=2)
            name = parts[0]
            path = parts[1] if len(parts) > 1 else None
            desc = parts[2] if len(parts) > 2 else ""
            success, msg = self.project_manager.add_project(name, path, desc)
            return msg

        elif command == "remove":
            if not args:
                return "Usage: /remove <project_name>"
            success, msg = self.project_manager.remove_project(args)
            if success and self.project_manager.get_current_project(sender) is None:
                self.runner.set_project(None)
            return msg

        elif command == "new":
            if not args:
                return "Usage: /new <project_name> [description]"
            parts = args.split(maxsplit=1)
            name = parts[0]
            desc = parts[1] if len(parts) > 1 else ""
            success, msg = self.project_manager.create_project(name, sender, desc)
            if success:
                self.runner.set_project(self.project_manager.get_current_path(sender))
            return msg

        elif command == "ask":
            if not args:
                return "Usage: /ask <question about the project>"
            current_project = self.project_manager.get_current_project(sender)
            if not current_project:
                return "No project selected. Use /select <project> first."
            busy = self._check_task_busy()
            if busy:
                return busy

            await self._send_message(sender, "Analyzing project...")
            self._start_background_task(
                sender,
                f"Answer this question about the codebase: {args}",
                current_project
            )
            return None  # Response will be sent when task completes

        elif command == "do":
            if not args:
                return "Usage: /do <task to perform>"
            current_project = self.project_manager.get_current_project(sender)
            if not current_project:
                return "No project selected. Use /select <project> first."
            busy = self._check_task_busy()
            if busy:
                return busy

            await self._send_message(sender, "Working on it...")
            self._start_background_task(sender, args, current_project)
            return None  # Response will be sent when task completes

        elif command == "complex":
            if not args:
                return "Usage: /complex <task>\nBreaks task into PRD with stories and autonomous tasks."
            if not self.project_manager.get_current_project(sender):
                return "No project selected. Use /select <project> first."
            busy = self._check_task_busy()
            if busy:
                return busy

            await self._send_message(sender, "Creating PRD and breaking into autonomous tasks...")
            # Run PRD creation in background (non-blocking)
            self._start_prd_creation_task(sender, args)
            return None  # Response sent when PRD creation completes

        elif command == "cancel":
            return await self._cancel_current_task()

        elif command == "summary":
            current_project = self.project_manager.get_current_project(sender)
            if not current_project:
                return "No project selected. Use /select <project> first."
            busy = self._check_task_busy()
            if busy:
                return busy

            await self._send_message(sender, "Generating summary...")
            self._start_background_task(
                sender,
                "Provide a comprehensive summary of this project including "
                "its structure, main technologies used, and any recent changes "
                "visible in git history.",
                current_project
            )
            return None  # Response will be sent when task completes

        # Memory commands - use current project by default
        elif command == "remember":
            return await self.memory_commands.handle_remember(
                sender, args, project=self.project_manager.get_current_project(sender)
            )

        elif command == "recall":
            return await self.memory_commands.handle_recall(
                sender, args, project=self.project_manager.get_current_project(sender)
            )

        elif command == "history":
            return await self.memory_commands.handle_history(
                sender, args, project=self.project_manager.get_current_project(sender)
            )

        elif command == "forget":
            return await self.memory_commands.handle_forget(sender, args)

        elif command == "memories":
            return await self.memory_commands.handle_memories(
                sender, args, project=self.project_manager.get_current_project(sender)
            )

        elif command == "preferences":
            return await self.memory_commands.handle_preferences(sender, args)

        # Global memory commands - explicitly cross-project
        elif command == "global":
            return await self._handle_global_command(sender, args)

        # Autonomous system commands
        elif command == "prd":
            return await self.autonomous_commands.handle_prd(sender, args)

        elif command == "story":
            return await self.autonomous_commands.handle_story(sender, args)

        elif command == "task":
            return await self.autonomous_commands.handle_task(sender, args)

        elif command == "tasks":
            return await self.autonomous_commands.handle_tasks(sender, args)

        elif command == "autonomous":
            return await self.autonomous_commands.handle_autonomous(sender, args)

        elif command == "queue":
            return await self.autonomous_commands.handle_queue(sender, args)

        elif command == "learnings":
            return await self.autonomous_commands.handle_learnings(sender, args)

        elif command == "sidechannel":
            if not self.sidechannel_runner:
                return "sidechannel assistant is not enabled. Set sidechannel_assistant.enabled: true in settings.yaml and provide OPENAI_API_KEY or GROK_API_KEY."
            if not args:
                return "Usage: /sidechannel <question>\nAsk the AI assistant anything."
            return await self._sidechannel_response(args)

        else:
            # Check plugin commands
            plugin_handler = self.plugin_loader.get_all_commands().get(command)
            if plugin_handler:
                return await plugin_handler(sender, args)
            return f"Unknown command: /{command}\nUse /help to see available commands."

    def _get_help(self) -> str:
        """Get help text."""
        help_text = """sidechannel Commands:

Project Management:
  /projects - List available projects
  /select <project> - Select a project
  /add <name> [path] [desc] - Add existing project
  /remove <project> - Remove a project from the list
  /new <name> [desc] - Create new project
  /status - Show current project and task status
  /summary - Generate project summary

Claude Tasks:
  /ask <question> - Ask about the current project
  /do <task> - Execute a task with Claude
  /complex <task> - Break into PRD with autonomous tasks
  /cancel - Stop the running task

Autonomous System:
  /prd <title> - Create a Product Requirements Doc
  /story <prd_id> <title> | <desc> - Add a user story
  /task <story_id> <title> | <desc> - Add a task
  /tasks [status] - List tasks
  /queue story|prd <id> - Queue tasks for execution
  /autonomous status|start|pause|stop - Control the loop
  /learnings [search] - View or search learnings

Memory:
  /remember <text> - Store a memory
  /recall <query> - Search past conversations
  /memories - List stored memories
  /history [count] - View recent messages
  /forget all|preferences|today - Delete data
  /preferences - View stored preferences
  /global <cmd> - Cross-project memory commands"""

        if self.sidechannel_runner:
            help_text = """sidechannel Commands:

AI Assistant:
  /sidechannel <question> - Ask the AI assistant anything
  Or just: sidechannel <question>

""" + help_text[len("sidechannel Commands:\n\n"):]

        # Append plugin help sections
        for section in self.plugin_loader.get_all_help():
            help_text += f"\n\n{section.title}:"
            for cmd, desc in section.commands.items():
                help_text += f"\n  /{cmd} - {desc}"

        return help_text

    async def _get_memory_context(self, sender: str, query: str,
                                   project_name: Optional[str] = None) -> Optional[str]:
        """Get memory context for a Claude prompt.

        Args:
            sender: User's phone number
            query: The current task/question
            project_name: Project to scope memory to (uses sender's current if None)

        Returns:
            Memory context string to inject, or None
        """
        if project_name is None:
            project_name = self.project_manager.get_current_project(sender)
        try:
            context = await self.memory.get_relevant_context(
                phone_number=sender,
                query=query,
                project_name=project_name,
                max_results=5,
                max_tokens=self.config.memory_max_context_tokens
            )
            return context if context else None
        except Exception as e:
            logger.warning("memory_context_error", error=str(e))
            return None

    def _start_background_task(self, sender: str, task_description: str, project_name: Optional[str]):
        """Start a Claude task in the background (non-blocking).

        This allows other commands to be processed while the task runs.
        """
        self._current_task_description = task_description
        self._current_task_sender = sender
        self._current_task_start = datetime.now()
        self._current_task_step = "Preparing context..."

        async def run_task():
            try:
                async def progress_cb(msg: str):
                    self._current_task_step = msg
                    await self._send_message(sender, msg)

                # Get memory context for this task (use project_name captured at creation)
                self._current_task_step = "Loading memory context..."
                memory_context = await self._get_memory_context(sender, task_description, project_name)

                self._current_task_step = "Claude executing task..."
                success, response = await self.runner.run_claude(
                    task_description,
                    progress_callback=progress_cb,
                    memory_context=memory_context
                )

                # Store response to memory
                t = asyncio.create_task(
                    self.memory.store_message(
                        phone_number=sender,
                        role="assistant",
                        content=response,
                        project_name=project_name,
                        command_type="do"
                    )
                )
                t.add_done_callback(_log_task_exception)

                # Send the response
                await self._send_message(sender, response)

            except asyncio.CancelledError:
                await self._send_message(sender, "Task cancelled.")
                logger.info("background_task_cancelled", task=task_description[:50])
            except Exception as e:
                logger.error("background_task_error", error=str(e), exc_type=type(e).__name__)
                await self._send_message(sender, "Task failed due to an internal error.")
            finally:
                # Clear task state
                self._current_task = None
                self._current_task_description = None
                self._current_task_sender = None
                self._current_task_start = None
                self._current_task_step = None

        self._current_task = asyncio.create_task(run_task())
        logger.info("background_task_started", task=task_description[:50])

    async def _handle_global_command(self, sender: str, args: str) -> str:
        """Handle /global <subcommand> for cross-project memory operations."""
        if not args.strip():
            return (
                "Usage: /global <command> <args>\n\n"
                "  remember <text> - Store a global memory\n"
                "  recall <query> - Search all projects\n"
                "  memories - List all memories\n"
                "  history [count] - History across projects"
            )

        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower()
        subargs = parts[1] if len(parts) > 1 else ""

        if subcommand == "remember":
            return await self.memory_commands.handle_remember(sender, subargs, project=None)
        elif subcommand == "recall":
            return await self.memory_commands.handle_recall(sender, subargs, project=None)
        elif subcommand == "memories":
            return await self.memory_commands.handle_memories(sender, subargs, project=None)
        elif subcommand == "history":
            return await self.memory_commands.handle_history(sender, subargs, project=None)
        else:
            return f"Unknown global command: {subcommand}\n\nUse /global for help."

    def _check_task_busy(self) -> Optional[str]:
        """Return a busy message if a task is running, else None."""
        if not self._current_task or self._current_task.done():
            return None
        elapsed = ""
        if self._current_task_start:
            mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
            elapsed = f" ({mins}m)"
        desc = self._current_task_description[:100] if self._current_task_description else "unknown"
        return f"Task in progress{elapsed}: {desc}\nUse /cancel to stop it."

    async def _cancel_current_task(self) -> str:
        """Cancel the currently running task."""
        if not self._current_task or self._current_task.done():
            return "No task is currently running."

        task_desc = self._current_task_description or "unknown"
        elapsed = ""
        if self._current_task_start:
            mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
            elapsed = f" after {mins}m"

        self._current_task.cancel()

        # Also cancel any running Claude process
        await self.runner.cancel()

        logger.info("task_cancelled_by_user", task=task_desc[:50])
        return f"Cancelled{elapsed}: {task_desc[:100]}"

    def _start_prd_creation_task(self, sender: str, task_description: str):
        """Start PRD creation in the background (non-blocking)."""
        self._current_task_description = f"Creating PRD: {task_description[:50]}..."
        self._current_task_sender = sender
        self._current_task_start = datetime.now()
        self._current_task_step = "Initializing..."

        async def run_prd_creation():
            try:
                result = await self._create_autonomous_prd(sender, task_description)
                await self._send_message(sender, result)
            except asyncio.CancelledError:
                await self._send_message(sender, "PRD creation cancelled.")
                logger.info("prd_creation_cancelled")
            except Exception as e:
                logger.error("prd_creation_error", error=str(e), exc_type=type(e).__name__)
                await self._send_message(sender, "PRD creation failed. Check logs for details.")
            finally:
                self._current_task = None
                self._current_task_description = None
                self._current_task_sender = None
                self._current_task_start = None
                self._current_task_step = None

        self._current_task = asyncio.create_task(run_prd_creation())
        logger.info("prd_creation_started", task=task_description[:50])

    async def _create_autonomous_prd(self, sender: str, task_description: str) -> str:
        """Create a PRD with stories and tasks from a complex task description.

        Uses Claude to intelligently break down the task into manageable pieces.
        """
        project_name = self.project_manager.get_current_project(sender)
        project_path = self.project_manager.get_current_path(sender)

        # Helper to update step and notify user
        async def update_step(step: str, notify: bool = True):
            self._current_task_step = step
            if notify:
                await self._send_message(sender, step)

        await update_step("Analyzing task complexity...")

        # First, use Claude to analyze and break down the task
        breakdown_prompt = f"""Analyze this task request and break it into a structured PRD (Product Requirements Document).

TASK REQUEST:
{task_description}

PROJECT: {project_name}

Return a JSON structure with this EXACT format (no markdown, just JSON):
{{
    "prd_title": "Brief title for the PRD (max 50 chars)",
    "prd_description": "One paragraph summary of what we're building",
    "stories": [
        {{
            "title": "Story title (max 50 chars)",
            "description": "What this story accomplishes",
            "tasks": [
                {{
                    "title": "Task title (max 50 chars)",
                    "description": "Detailed description of what to do. Include specific files, functions, or components to modify. Be specific enough that Claude can execute this independently.",
                    "priority": 10
                }}
            ]
        }}
    ]
}}

RULES:
1. Break into logical stories (features/components)
2. Each story should have 2-5 focused tasks
3. Tasks should be atomic - completable in one Claude session
4. Higher priority number = executed first
5. Order tasks by dependency (foundations first)
6. Include a final "Testing & Deployment" story if mentioned
7. Be specific in task descriptions - mention exact files/components
8. Keep tasks focused - if a task is too big, split it

CRITICAL JSON FORMATTING:
- Use double quotes for all strings
- NO trailing commas
- NO comments
- Escape special characters in strings (use \\n for newlines)
- Keep descriptions on single lines (no literal newlines in strings)

Return ONLY valid JSON, no markdown code blocks, no explanation."""

        try:
            # Run Claude to get the breakdown
            self.runner.set_project(project_path)
            await update_step("Breaking down task...")
            success, response = await self.runner.run_claude(
                breakdown_prompt,
                timeout=self.config.claude_timeout  # Use configurable timeout
            )

            if not success:
                logger.error("prd_analyze_failed", response=response[:200])
                return "Failed to analyze task."

            await update_step("Parsing task breakdown...", notify=False)

            # Parse the JSON response with robust error handling
            breakdown = await parse_prd_json(response, self.runner, update_step)

            await update_step("Creating PRD structure...", notify=False)

            # Create the PRD
            prd = await self.autonomous_manager.create_prd(
                phone_number=sender,
                project_name=project_name,
                title=breakdown["prd_title"],
                description=breakdown["prd_description"]
            )

            total_tasks = 0
            story_summaries = []
            total_stories = len(breakdown.get("stories", []))

            # Create stories and tasks
            for story_idx, story_data in enumerate(breakdown.get("stories", []), 1):
                await update_step(f"Creating story {story_idx}/{total_stories}...", notify=False)
                story = await self.autonomous_manager.create_story(
                    prd_id=prd.id,
                    phone_number=sender,
                    title=story_data["title"],
                    description=story_data["description"]
                )

                task_count = 0
                for task_data in story_data.get("tasks", []):
                    await self.autonomous_manager.create_task(
                        story_id=story.id,
                        phone_number=sender,
                        project_name=project_name,
                        title=task_data["title"],
                        description=task_data["description"],
                        priority=task_data.get("priority", 5)
                    )
                    task_count += 1
                    total_tasks += 1

                story_summaries.append(f"  - {story.title} ({task_count} tasks)")

            await update_step("Queuing tasks for execution...")

            # Queue all tasks
            queued = await self.autonomous_manager.queue_prd(prd.id)

            # Start the autonomous loop if not running
            status = await self.autonomous_manager.get_loop_status()
            if not status.is_running:
                await self.autonomous_manager.start_loop()

            # Return summary
            loop_state = "Started" if not status.is_running else "Running"
            return (
                f"PRD #{prd.id}: {prd.title}\n\n"
                f"Stories:\n" + "\n".join(story_summaries) + "\n\n"
                f"{total_tasks} tasks queued | Loop: {loop_state}\n"
                f"Use /tasks or /autonomous status to monitor."
            )

        except (json.JSONDecodeError, ValueError) as e:
            logger.error("prd_json_parse_error", error=str(e), exc_type=type(e).__name__)
            return "Failed to parse the task breakdown. Please try again."
        except KeyError as e:
            logger.error("prd_missing_field", error=str(e))
            return "Task breakdown was incomplete. Please try again."
        except Exception as e:
            logger.error("prd_creation_error", error=str(e), exc_type=type(e).__name__)
            return "PRD creation failed. Please try again or check logs."

    async def _process_message(self, sender: str, message: str):
        """Process an incoming message."""
        # Check authorization
        if not is_authorized(sender):
            logger.warning("unauthorized_message", sender=sender)
            return  # Silently ignore unauthorized messages

        # Check rate limit
        if not check_rate_limit(sender):
            logger.warning("rate_limited", sender="..." + sender[-4:])
            await self._send_message(sender, "Rate limited. Please wait before sending more messages.")
            return

        # Sanitize input
        message = sanitize_input(message.strip())

        if not message:
            return

        logger.info(
            "message_received",
            sender="..." + sender[-4:],
            length=len(message)
        )

        # Determine command type for memory logging
        command_type = None
        if message.startswith("/"):
            parts = message[1:].split(maxsplit=1)
            command_type = parts[0].lower()

        # Store incoming message (fire and forget, don't block)
        project_name = self.project_manager.get_current_project(sender)
        t = asyncio.create_task(
            self.memory.store_message(
                phone_number=sender,
                role="user",
                content=message,
                project_name=project_name,
                command_type=command_type
            )
        )
        t.add_done_callback(_log_task_exception)

        # Check if it's a command
        if message.startswith("/"):
            parts = message[1:].split(maxsplit=1)
            command = parts[0]
            args = parts[1] if len(parts) > 1 else ""

            response = await self._handle_command(command, args, sender)
        else:
            # Check plugin message matchers
            response = None
            for matcher in self.plugin_loader.get_sorted_matchers():
                if matcher.match_fn(message):
                    response = await matcher.handle_fn(sender, message)
                    break

            if response is None and self._is_sidechannel_query(message):
                # Addressed to sidechannel - general AI assistant mode
                response = await self._sidechannel_response(message)
            elif response is None:
                # Treat non-command messages as /do commands if a project is selected
                if project_name:
                    busy = self._check_task_busy()
                    if busy:
                        response = busy
                    else:
                        await self._send_message(sender, "Working on it...")
                        self._start_background_task(sender, message, project_name)
                        return  # Response will be sent when task completes
                else:
                    response = "No project selected. Use /projects to list or /select <project> to choose one."


        # If response is None, the task is running in background
        if response is None:
            return

        # Store outgoing response (fire and forget)
        t = asyncio.create_task(
            self.memory.store_message(
                phone_number=sender,
                role="assistant",
                content=response,
                project_name=project_name,
                command_type=command_type
            )
        )
        t.add_done_callback(_log_task_exception)

        await self._send_message(sender, response)

    def _is_sidechannel_query(self, message: str) -> bool:
        """Detect if a message is addressed to sidechannel assistant."""
        if not self.sidechannel_runner:
            return False
        msg_lower = message.lower().strip()
        # Match: "sidechannel:", "sidechannel,", "sidechannel " followed by text, or just "sidechannel"
        if msg_lower.startswith("sidechannel:") or msg_lower.startswith("sidechannel,"):
            return True
        if msg_lower.startswith("sidechannel ") and len(msg_lower) > 12:
            return True
        if msg_lower == "sidechannel":
            return True
        return False

    async def _sidechannel_response(self, message: str) -> str:
        """Generate a sidechannel response using the configured provider."""
        if not self.sidechannel_runner:
            return "sidechannel assistant is not enabled. Set sidechannel_assistant.enabled: true in settings.yaml and provide OPENAI_API_KEY or GROK_API_KEY."
        try:
            logger.info("sidechannel_query", length=len(message))
            success, response = await self.sidechannel_runner.ask_jarvis(message)
            if not response or not response.strip():
                logger.warning("sidechannel_empty_response")
                return "The assistant returned an empty response. Please try again."
            return response
        except Exception as e:
            logger.error("sidechannel_response_error", error=str(e), exc_type=type(e).__name__)
            return "The assistant encountered an error. Please try again later."

    async def poll_messages(self):
        """Connect via WebSocket to receive messages (json-rpc mode)."""
        if not self.account:
            logger.error("no_account_for_polling")
            return

        # Convert http:// to ws:// for websocket connection
        ws_base = self.config.signal_api_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base}/v1/receive/{self.account}"

        reconnect_delay = 5
        MAX_RECONNECT_DELAY = 300

        while self.running:
            try:
                logger.info("websocket_connecting", url=ws_url)
                async with self.session.ws_connect(ws_url, heartbeat=30) as ws:
                    logger.info("websocket_connected")
                    reconnect_delay = 5  # Reset on successful connection
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                await self._handle_signal_message(data)
                            except json.JSONDecodeError:
                                logger.warning("invalid_json", data=msg.data[:100])
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error("websocket_error", error=str(ws.exception()))
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            logger.info("websocket_closed")
                            break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("websocket_exception", error=str(e))
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)

    async def _handle_signal_message(self, msg: dict):
        """Handle a message from Signal API."""
        try:
            envelope = msg.get("envelope", {})
            source = envelope.get("source") or envelope.get("sourceNumber")
            message_text = None

            # Check for regular data message (from others TO us)
            data_message = envelope.get("dataMessage")
            if data_message:
                message_text = data_message.get("message", "")

            # Check for sync message (our own messages sent from another device)
            sync_message = envelope.get("syncMessage")
            if sync_message and not message_text:
                sent_message = sync_message.get("sentMessage")
                if sent_message:
                    # Check destination - only process messages sent to our own number
                    destination = sent_message.get("destination") or sent_message.get("destinationNumber")

                    # Ignore group messages
                    if sent_message.get("groupInfo"):
                        return

                    # Only process if sent to ourselves (the bot's number)
                    if destination and destination == self.account:
                        message_text = sent_message.get("message", "")
                        source = self.account

            # Ignore receipts, typing indicators, and other message types
            if not message_text or not message_text.strip():
                return

            # SECURITY: Only process messages from authorized sources
            if not source:
                return

            # Deduplication: Signal sends both dataMessage and syncMessage for self-messages
            timestamp = envelope.get("timestamp", 0)
            msg_hash = hashlib.sha256(f"{timestamp}:{message_text.strip()}".encode()).hexdigest()
            if msg_hash in self._processed_messages:
                logger.debug("duplicate_message_skipped", timestamp=timestamp)
                return
            self._processed_messages[msg_hash] = _time.time()

            # Evict entries older than 60 seconds
            cutoff = _time.time() - 60
            while self._processed_messages:
                oldest_key, oldest_time = next(iter(self._processed_messages.items()))
                if oldest_time < cutoff:
                    self._processed_messages.pop(oldest_key)
                else:
                    break

            logger.info("processing_message", source="..." + source[-4:], length=len(message_text))
            await self._process_message(source, message_text)

        except Exception as e:
            logger.error("message_handling_error", error=str(e), msg=str(msg)[:200])

    async def run(self):
        """Main run loop."""
        await self.start()

        try:
            await self.poll_messages()
        finally:
            await self.stop()
