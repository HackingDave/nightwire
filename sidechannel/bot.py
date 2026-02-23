"""Signal bot implementation for sidechannel."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
import structlog

from .config import get_config
from .security import is_authorized, sanitize_input
from .claude_runner import get_runner
from .project_manager import get_project_manager
from .memory import MemoryManager, MemoryCommands
from .autonomous import AutonomousManager, AutonomousCommands
from .plugin_loader import PluginLoader
from .prd_builder import clean_json_string, extract_balanced_json, parse_prd_json

logger = structlog.get_logger()


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
        self._processed_messages: set = set()  # Dedup: (timestamp, message_hash)

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

        # Get the registered account
        await self._get_account()

        # Initialize memory system
        await self.memory.initialize()

        # Initialize autonomous system (uses same DB connection)
        async def autonomous_notify(phone: str, message: str):
            await self._send_message(phone, f"[Auto] {message}")

        self.autonomous_manager = AutonomousManager(
            db_connection=self.memory.db._conn,
            progress_callback=autonomous_notify,
            poll_interval=self.config.autonomous_poll_interval,
            run_quality_gates=self.config.autonomous_quality_gates,
        )
        self.autonomous_commands = AutonomousCommands(
            manager=self.autonomous_manager,
            get_current_project=lambda: (
                self.project_manager.current_project,
                self.project_manager.current_path,
            ),
        )

        # Start plugins
        await self.plugin_loader.start_all()

        logger.info("bot_started", account=self.account)

    async def stop(self):
        """Stop the bot."""
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
        """Get the registered Signal account."""
        try:
            url = f"{self.config.signal_api_url}/v1/accounts"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    accounts = await resp.json()
                    if accounts:
                        self.account = accounts[0]
                        logger.info("account_found", account=self.account)
                    else:
                        logger.error("no_accounts_registered")
                else:
                    logger.error("accounts_request_failed", status=resp.status)
        except Exception as e:
            logger.error("accounts_request_error", error=str(e))

    async def _send_message(self, recipient: str, message: str):
        """Send a message via Signal."""
        if not self.account:
            logger.error("no_account_for_sending")
            return

        # SECURITY: Double-check recipient is authorized before sending
        if not is_authorized(recipient):
            logger.warning("blocked_send_to_unauthorized", recipient=recipient[:6] + "...")
            return

        # Add sidechannel identifier to all messages
        message = f"sidechannel: {message}"

        try:
            url = f"{self.config.signal_api_url}/v2/send"
            payload = {
                "number": self.account,
                "recipients": [recipient],
                "message": message
            }

            async with self.session.post(url, json=payload) as resp:
                if resp.status == 201:
                    logger.info("message_sent", recipient=recipient[:6] + "...")
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
            return self.project_manager.list_projects()

        elif command == "select":
            if not args:
                return "Usage: /select <project_name>"
            success, msg = self.project_manager.select_project(args)
            if success:
                self.runner.set_project(self.project_manager.current_path)
            return msg

        elif command == "status":
            status = self.project_manager.get_status()
            # Add running task info (direct /do tasks)
            if self._current_task and not self._current_task.done():
                elapsed = ""
                if self._current_task_start:
                    mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
                    elapsed = f" ({mins} min elapsed)"
                task_info = f"\n\nRunning task{elapsed}:\n{self._current_task_description[:150] if self._current_task_description else 'unknown'}..."
                # Show current step if available
                if self._current_task_step:
                    task_info += f"\n\nCurrent step: {self._current_task_step}"
                status += task_info

            # Add autonomous loop status
            try:
                loop_status = await self.autonomous_manager.get_loop_status()
                if loop_status.is_running:
                    auto_info = "\n\n[Autonomous Loop]"
                    if loop_status.current_task_id:
                        # Get current task details
                        current_task = await self.autonomous_manager.db.get_task(loop_status.current_task_id)
                        if current_task:
                            auto_info += f"\nRunning: {current_task.title[:50]}"
                            if current_task.started_at:
                                mins = int((datetime.now() - current_task.started_at).total_seconds() / 60)
                                auto_info += f" ({mins} min)"
                    auto_info += f"\nQueued: {loop_status.tasks_queued} tasks"
                    auto_info += f"\nCompleted today: {loop_status.tasks_completed_today}"
                    if loop_status.tasks_failed_today > 0:
                        auto_info += f" | Failed: {loop_status.tasks_failed_today}"
                    status += auto_info
                elif loop_status.is_paused:
                    status += "\n\n[Autonomous Loop] PAUSED"
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

        elif command == "new":
            if not args:
                return "Usage: /new <project_name> [description]"
            parts = args.split(maxsplit=1)
            name = parts[0]
            desc = parts[1] if len(parts) > 1 else ""
            success, msg = self.project_manager.create_project(name, desc)
            if success:
                self.runner.set_project(self.project_manager.current_path)
            return msg

        elif command == "ask":
            if not args:
                return "Usage: /ask <question about the project>"
            if not self.project_manager.current_project:
                return "No project selected. Use /select <project> first."

            # Check if a task is already running
            if self._current_task and not self._current_task.done():
                elapsed = ""
                if self._current_task_start:
                    mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
                    elapsed = f" ({mins} min elapsed)"
                return (
                    f"A task is already running{elapsed}.\n"
                    f"Current: {self._current_task_description[:100] if self._current_task_description else 'unknown'}...\n"
                    f"Use /cancel to stop it first."
                )

            await self._send_message(sender, "Analyzing project...")
            self._start_background_task(
                sender,
                f"Answer this question about the codebase: {args}",
                self.project_manager.current_project
            )
            return None  # Response will be sent when task completes

        elif command == "do":
            if not args:
                return "Usage: /do <task to perform>"
            if not self.project_manager.current_project:
                return "No project selected. Use /select <project> first."

            # Check if a task is already running
            if self._current_task and not self._current_task.done():
                elapsed = ""
                if self._current_task_start:
                    mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
                    elapsed = f" ({mins} min elapsed)"
                return (
                    f"A task is already running{elapsed}.\n"
                    f"Current: {self._current_task_description[:100] if self._current_task_description else 'unknown'}...\n"
                    f"Use /cancel to stop it first."
                )

            # Simple task - start in background (non-blocking)
            await self._send_message(sender, "Working on it...")
            self._start_background_task(sender, args, self.project_manager.current_project)
            return None  # Response will be sent when task completes

        elif command == "complex":
            if not args:
                return "Usage: /complex <task to perform>\n\nBreaks task into PRD with stories and autonomous tasks."
            if not self.project_manager.current_project:
                return "No project selected. Use /select <project> first."

            # Check if a task is already running
            if self._current_task and not self._current_task.done():
                elapsed = ""
                if self._current_task_start:
                    mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
                    elapsed = f" ({mins} min elapsed)"
                return (
                    f"A task is already running{elapsed}.\n"
                    f"Current: {self._current_task_description[:100] if self._current_task_description else 'unknown'}...\n"
                    f"Use /cancel to stop it first."
                )

            await self._send_message(
                sender,
                "Creating PRD and breaking into autonomous tasks..."
            )
            # Run PRD creation in background (non-blocking)
            self._start_prd_creation_task(sender, args)
            return None  # Response sent when PRD creation completes

        elif command == "cancel":
            return await self._cancel_current_task()

        elif command == "summary":
            if not self.project_manager.current_project:
                return "No project selected. Use /select <project> first."

            # Check if a task is already running
            if self._current_task and not self._current_task.done():
                elapsed = ""
                if self._current_task_start:
                    mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
                    elapsed = f" ({mins} min elapsed)"
                return (
                    f"A task is already running{elapsed}.\n"
                    f"Current: {self._current_task_description[:100] if self._current_task_description else 'unknown'}...\n"
                    f"Use /cancel to stop it first."
                )

            await self._send_message(sender, "Generating summary...")
            self._start_background_task(
                sender,
                "Provide a comprehensive summary of this project including "
                "its structure, main technologies used, and any recent changes "
                "visible in git history.",
                self.project_manager.current_project
            )
            return None  # Response will be sent when task completes

        # Memory commands - use current project by default
        elif command == "remember":
            return await self.memory_commands.handle_remember(
                sender, args, project=self.project_manager.current_project
            )

        elif command == "recall":
            return await self.memory_commands.handle_recall(
                sender, args, project=self.project_manager.current_project
            )

        elif command == "history":
            return await self.memory_commands.handle_history(
                sender, args, project=self.project_manager.current_project
            )

        elif command == "forget":
            return await self.memory_commands.handle_forget(sender, args)

        elif command == "memories":
            return await self.memory_commands.handle_memories(
                sender, args, project=self.project_manager.current_project
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

        else:
            # Check plugin commands
            plugin_handler = self.plugin_loader.get_all_commands().get(command)
            if plugin_handler:
                return await plugin_handler(sender, args)
            return f"Unknown command: /{command}\nUse /help to see available commands."

    def _get_help(self) -> str:
        """Get help text."""
        help_text = """sidechannel Commands:

Project Commands (Claude):
  /projects - List available projects
  /select <project> - Select existing project
  /ask <question> - Ask Claude about the project
  /do <task> - Have Claude make changes
  /complex <task> - Break into PRD with autonomous tasks
  /cancel - Stop the currently running task

Autonomous Tasks:
  /prd <title> - Create PRD (Product Requirements Doc)
  /story <prd_id> <title> | <desc> - Add user story
  /task <story_id> <title> | <desc> - Add task
  /tasks [status] - List tasks
  /queue story|prd <id> - Queue tasks
  /autonomous status|start|pause|stop - Control loop
  /learnings [search] - View/search learnings

Memory Commands (uses current project):
  /remember <text> - Store a memory
  /recall <query> - Search conversations
  /memories - List stored memories
  /history [count] - View recent messages
  /global <cmd> - Cross-project (remember/recall/etc)

/help - Show this help"""

        if self.sidechannel_runner:
            help_text = """sidechannel Commands:

sidechannel (AI Assistant):
  sidechannel: <question> - Ask anything

""" + help_text[len("sidechannel Commands:\n\n"):]

        # Append plugin help sections
        for section in self.plugin_loader.get_all_help():
            help_text += f"\n\n{section.title}:"
            for cmd, desc in section.commands.items():
                help_text += f"\n  /{cmd} - {desc}"

        return help_text

    async def _get_memory_context(self, sender: str, query: str) -> Optional[str]:
        """Get memory context for a Claude prompt.

        Args:
            sender: User's phone number
            query: The current task/question

        Returns:
            Memory context string to inject, or None
        """
        try:
            context = await self.memory.get_relevant_context(
                phone_number=sender,
                query=query,
                project_name=self.project_manager.current_project,
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

                # Get memory context for this task
                self._current_task_step = "Loading memory context..."
                memory_context = await self._get_memory_context(sender, task_description)

                self._current_task_step = "Claude executing task..."
                success, response = await self.runner.run_claude(
                    task_description,
                    progress_callback=progress_cb,
                    memory_context=memory_context
                )

                # Store response to memory
                asyncio.create_task(
                    self.memory.store_message(
                        phone_number=sender,
                        role="assistant",
                        content=response,
                        project_name=project_name,
                        command_type="do"
                    )
                )

                # Send the response
                await self._send_message(sender, response)

            except asyncio.CancelledError:
                await self._send_message(sender, "Task cancelled.")
                logger.info("background_task_cancelled", task=task_description[:50])
            except Exception as e:
                logger.error("background_task_error", error=str(e))
                await self._send_message(sender, f"Task failed: {str(e)}")
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
                "Commands:\n"
                "  /global remember <text> - Store a global memory\n"
                "  /global recall <query> - Search all projects\n"
                "  /global memories - List all memories\n"
                "  /global history [count] - History across all projects"
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

    async def _cancel_current_task(self) -> str:
        """Cancel the currently running task."""
        if not self._current_task or self._current_task.done():
            return "No task is currently running."

        task_desc = self._current_task_description or "unknown"
        elapsed = ""
        if self._current_task_start:
            mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
            elapsed = f" after {mins} min"

        self._current_task.cancel()

        # Also cancel any running Claude process
        await self.runner.cancel()

        logger.info("task_cancelled_by_user", task=task_desc[:50])
        return f"Cancelled: {task_desc[:100]}...{elapsed}"

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
                logger.error("prd_creation_error", error=str(e))
                await self._send_message(sender, f"PRD creation failed: {str(e)}")
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
        project_name = self.project_manager.current_project
        project_path = self.project_manager.current_path

        # Helper to update step and notify user
        async def update_step(step: str, notify: bool = True):
            self._current_task_step = step
            if notify:
                await self._send_message(sender, f"[Step] {step}")

        await update_step("Step 1/5: Analyzing task complexity...")

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
            await update_step("Step 2/5: Claude analyzing and breaking down task...")
            success, response = await self.runner.run_claude(
                breakdown_prompt,
                timeout=self.config.claude_timeout  # Use configurable timeout
            )

            if not success:
                return f"Failed to analyze task: {response[:200]}"

            await update_step("Step 3/5: Parsing task breakdown...")

            # Parse the JSON response with robust error handling
            breakdown = await parse_prd_json(response, self.runner, update_step)

            await update_step("Step 4/5: Creating PRD structure...")

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
                await update_step(f"Step 4/5: Creating story {story_idx}/{total_stories}: {story_data.get('title', 'Untitled')[:30]}...", notify=False)
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

            await update_step("Step 5/5: Queuing tasks for execution...")

            # Queue all tasks
            queued = await self.autonomous_manager.queue_prd(prd.id)

            # Start the autonomous loop if not running
            status = await self.autonomous_manager.get_loop_status()
            if not status.is_running:
                await self.autonomous_manager.start_loop()

            # Return summary
            return (
                f"Created PRD #{prd.id}: {prd.title}\n\n"
                f"Stories:\n" + "\n".join(story_summaries) + "\n\n"
                f"Total: {total_tasks} tasks queued\n"
                f"Autonomous loop: {'Started' if not status.is_running else 'Already running'}\n\n"
                f"Monitor with /tasks or /autonomous status"
            )

        except (json.JSONDecodeError, ValueError) as e:
            logger.error("prd_json_parse_error", error=str(e))
            return f"Failed to parse task breakdown: {str(e)[:300]}"
        except KeyError as e:
            logger.error("prd_missing_field", error=str(e))
            return f"PRD response missing required field: {str(e)}"
        except Exception as e:
            logger.error("prd_creation_error", error=str(e))
            return f"Failed to create PRD: {str(e)[:300]}"

    async def _process_message(self, sender: str, message: str):
        """Process an incoming message."""
        # Check authorization
        if not is_authorized(sender):
            logger.warning("unauthorized_message", sender=sender)
            return  # Silently ignore unauthorized messages

        # Sanitize input
        message = sanitize_input(message.strip())

        if not message:
            return

        logger.info(
            "message_received",
            sender=sender[:6] + "...",
            length=len(message)
        )

        # Determine command type for memory logging
        command_type = None
        if message.startswith("/"):
            parts = message[1:].split(maxsplit=1)
            command_type = parts[0].lower()

        # Store incoming message (fire and forget, don't block)
        project_name = self.project_manager.current_project
        asyncio.create_task(
            self.memory.store_message(
                phone_number=sender,
                role="user",
                content=message,
                project_name=project_name,
                command_type=command_type
            )
        )

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
                if self.project_manager.current_project:
                    # Check if a task is already running
                    if self._current_task and not self._current_task.done():
                        elapsed = ""
                        if self._current_task_start:
                            mins = int((datetime.now() - self._current_task_start).total_seconds() / 60)
                            elapsed = f" ({mins} min elapsed)"
                        response = (
                            f"A task is already running{elapsed}.\n"
                            f"Current: {self._current_task_description[:100] if self._current_task_description else 'unknown'}...\n"
                            f"Use /cancel to stop it first."
                        )
                    else:
                        await self._send_message(sender, "Working on it...")
                        self._start_background_task(sender, message, self.project_manager.current_project)
                        return  # Response will be sent when task completes
                else:
                    response = (
                        "No project selected. Use /select <project> first, "
                        "or send a command like /help"
                    )


        # If response is None, the task is running in background
        if response is None:
            return

        # Store outgoing response (fire and forget)
        asyncio.create_task(
            self.memory.store_message(
                phone_number=sender,
                role="assistant",
                content=response,
                project_name=project_name,
                command_type=command_type
            )
        )

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
        success, response = await self.sidechannel_runner.ask_jarvis(message)
        return response

    async def poll_messages(self):
        """Connect via WebSocket to receive messages (json-rpc mode)."""
        if not self.account:
            logger.error("no_account_for_polling")
            return

        # Convert http:// to ws:// for websocket connection
        ws_base = self.config.signal_api_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base}/v1/receive/{self.account}"

        while self.running:
            try:
                logger.info("websocket_connecting", url=ws_url)
                async with self.session.ws_connect(ws_url, heartbeat=30) as ws:
                    logger.info("websocket_connected")
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
                await asyncio.sleep(5)

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
            msg_hash = hash((timestamp, message_text.strip()))
            if msg_hash in self._processed_messages:
                logger.debug("duplicate_message_skipped", timestamp=timestamp)
                return
            self._processed_messages.add(msg_hash)

            # Keep dedup set small (only recent messages)
            if len(self._processed_messages) > 100:
                self._processed_messages.clear()

            logger.info("processing_message", source=source[:6] + "...", length=len(message_text))
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
