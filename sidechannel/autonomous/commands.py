"""Command handlers for autonomous system."""

from typing import Optional

import structlog

from .models import LearningCategory, TaskStatus
from .manager import AutonomousManager

logger = structlog.get_logger()


class AutonomousCommands:
    """Handlers for autonomous-related slash commands."""

    def __init__(self, manager: AutonomousManager, get_current_project: callable):
        """
        Initialize command handlers.

        Args:
            manager: AutonomousManager instance
            get_current_project: Callable(phone_number) -> (project_name, project_path)
        """
        self.manager = manager
        self.get_current_project = get_current_project

    # ========== /prd Command ==========

    async def handle_prd(self, phone: str, args: str) -> str:
        """/prd command handler."""
        if not args.strip():
            return self._prd_help()

        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower()
        subargs = parts[1] if len(parts) > 1 else ""

        if subcommand == "list":
            return await self._list_prds(phone)
        elif subcommand == "activate":
            return await self._activate_prd(phone, subargs)
        elif subcommand == "archive":
            return await self._archive_prd(phone, subargs)
        elif subcommand.isdigit():
            return await self._show_prd(phone, int(subcommand))
        else:
            # Create new PRD
            return await self._create_prd(phone, args)

    async def _create_prd(self, phone: str, title: str) -> str:
        """Create a new PRD."""
        project_name, _ = self.get_current_project(phone)
        if not project_name:
            return "No project selected. Use /select <project> first."

        prd = await self.manager.create_prd(
            phone_number=phone,
            project_name=project_name,
            title=title,
            description=f"PRD for: {title}",
        )

        return (
            f"Created PRD #{prd.id}: {title}\n\n"
            f"Add stories with:\n"
            f"/story {prd.id} <story title> | <description>\n\n"
            f"Example:\n"
            f"/story {prd.id} User registration | Users can register with email"
        )

    async def _list_prds(self, phone: str) -> str:
        """List PRDs for user."""
        project_name, _ = self.get_current_project(phone)
        prds = await self.manager.list_prds(phone, project_name)

        if not prds:
            return "No PRDs found. Create one with /prd <title>"

        lines = ["Your PRDs:"]
        for prd in prds:
            status_emoji = {
                "draft": "[ ]",
                "active": "[>]",
                "completed": "[x]",
                "archived": "[-]",
            }.get(prd.status.value, "[ ]")

            lines.append(
                f"{status_emoji} #{prd.id} {prd.title} "
                f"({prd.completed_stories}/{prd.total_stories} stories)"
            )

        return "\n".join(lines)

    async def _show_prd(self, phone: str, prd_id: int) -> str:
        """Show PRD details."""
        prd = await self.manager.get_prd(prd_id)
        if not prd:
            return f"PRD #{prd_id} not found."

        stories = await self.manager.list_stories(prd_id=prd_id)

        lines = [
            f"PRD #{prd.id}: {prd.title}",
            f"Status: {prd.status.value}",
            f"Project: {prd.project_name}",
            f"Stories: {prd.completed_stories}/{prd.total_stories}",
            "",
            "Stories:",
        ]

        if stories:
            for story in stories:
                status_emoji = {
                    "pending": "[ ]",
                    "in_progress": "[>]",
                    "completed": "[x]",
                    "blocked": "[!]",
                    "failed": "[X]",
                }.get(story.status.value, "[ ]")
                lines.append(
                    f"  {status_emoji} #{story.id} {story.title} "
                    f"({story.completed_tasks}/{story.total_tasks} tasks)"
                )
        else:
            lines.append("  No stories yet. Add with /story")

        return "\n".join(lines)

    async def _activate_prd(self, phone: str, args: str) -> str:
        """Activate a PRD."""
        if not args.strip().isdigit():
            return "Usage: /prd activate <prd_id>"

        prd_id = int(args.strip())
        prd = await self.manager.get_prd(prd_id)
        if not prd:
            return f"PRD #{prd_id} not found."

        await self.manager.activate_prd(prd_id)
        return f"PRD #{prd_id} activated: {prd.title}"

    async def _archive_prd(self, phone: str, args: str) -> str:
        """Archive a PRD."""
        if not args.strip().isdigit():
            return "Usage: /prd archive <prd_id>"

        prd_id = int(args.strip())
        prd = await self.manager.get_prd(prd_id)
        if not prd:
            return f"PRD #{prd_id} not found."

        await self.manager.archive_prd(prd_id)
        return f"PRD #{prd_id} archived: {prd.title}"

    def _prd_help(self) -> str:
        return """PRD Commands:
/prd <title> - Create new PRD
/prd list - List all PRDs
/prd <id> - Show PRD details
/prd activate <id> - Activate for processing
/prd archive <id> - Archive a PRD

Example:
/prd User Authentication System"""

    # ========== /story Command ==========

    async def handle_story(self, phone: str, args: str) -> str:
        """/story command handler."""
        if not args.strip():
            return self._story_help()

        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower()
        subargs = parts[1] if len(parts) > 1 else ""

        if subcommand == "list":
            return await self._list_stories(phone, subargs)
        elif subcommand.isdigit():
            # Could be showing a story or creating one
            if "|" in subargs or not subargs:
                # Creating a story: /story <prd_id> <title> | <description>
                return await self._create_story(phone, int(subcommand), subargs)
            else:
                # Showing a story: /story <story_id>
                return await self._show_story(phone, int(subcommand))
        else:
            return self._story_help()

    async def _create_story(self, phone: str, prd_id: int, args: str) -> str:
        """Create a story in a PRD."""
        prd = await self.manager.get_prd(prd_id)
        if not prd:
            return f"PRD #{prd_id} not found."

        if "|" in args:
            title, description = args.split("|", 1)
            title = title.strip()
            description = description.strip()
        else:
            title = args.strip() if args.strip() else "Untitled Story"
            description = title

        if not title:
            return "Usage: /story <prd_id> <title> | <description>"

        story = await self.manager.create_story(
            prd_id=prd_id,
            phone_number=phone,
            title=title,
            description=description,
        )

        return (
            f"Created Story #{story.id}: {title}\n"
            f"In PRD #{prd_id}: {prd.title}\n\n"
            f"Add tasks with:\n"
            f"/task {story.id} <task title> | <description>"
        )

    async def _list_stories(self, phone: str, args: str) -> str:
        """List stories."""
        prd_id = int(args.strip()) if args.strip().isdigit() else None
        stories = await self.manager.list_stories(prd_id=prd_id, phone_number=phone)

        if not stories:
            return "No stories found."

        lines = ["Stories:"]
        for story in stories:
            status_emoji = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
                "blocked": "[!]",
                "failed": "[X]",
            }.get(story.status.value, "[ ]")
            lines.append(
                f"{status_emoji} #{story.id} (PRD {story.prd_id}) {story.title} "
                f"({story.completed_tasks}/{story.total_tasks} tasks)"
            )

        return "\n".join(lines)

    async def _show_story(self, phone: str, story_id: int) -> str:
        """Show story details."""
        story = await self.manager.get_story(story_id)
        if not story:
            return f"Story #{story_id} not found."

        tasks = await self.manager.list_tasks(story_id=story_id)

        lines = [
            f"Story #{story.id}: {story.title}",
            f"Status: {story.status.value}",
            f"PRD: #{story.prd_id}",
            f"Tasks: {story.completed_tasks}/{story.total_tasks}",
            "",
            f"Description: {story.description[:200]}",
        ]

        if story.acceptance_criteria:
            lines.append("\nAcceptance Criteria:")
            for ac in story.acceptance_criteria:
                lines.append(f"  - {ac}")

        lines.append("\nTasks:")
        if tasks:
            for task in tasks:
                status_emoji = {
                    "pending": "[ ]",
                    "queued": "[Q]",
                    "in_progress": "[>]",
                    "running_tests": "[T]",
                    "completed": "[x]",
                    "failed": "[X]",
                    "blocked": "[!]",
                    "cancelled": "[-]",
                }.get(task.status.value, "[ ]")
                lines.append(f"  {status_emoji} #{task.id} {task.title}")
        else:
            lines.append("  No tasks yet. Add with /task")

        return "\n".join(lines)

    def _story_help(self) -> str:
        return """Story Commands:
/story <prd_id> <title> | <description> - Create story
/story list [prd_id] - List stories
/story <id> - Show story details

Example:
/story 1 User login | Users can log in with email and password"""

    # ========== /task Command ==========

    async def handle_task(self, phone: str, args: str) -> str:
        """/task command handler."""
        if not args.strip():
            return self._task_help()

        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower()
        subargs = parts[1] if len(parts) > 1 else ""

        if subcommand.isdigit():
            story_id = int(subcommand)
            if "|" in subargs or subargs:
                return await self._create_task(phone, story_id, subargs)
            else:
                return await self._show_task(phone, story_id)
        else:
            return self._task_help()

    async def _create_task(self, phone: str, story_id: int, args: str) -> str:
        """Create a task in a story."""
        story = await self.manager.get_story(story_id)
        if not story:
            return f"Story #{story_id} not found."

        prd = await self.manager.get_prd(story.prd_id)
        project_name = prd.project_name if prd else None

        if not project_name:
            project_name, _ = self.get_current_project(phone)
        if not project_name:
            return "No project found. Select a project first."

        if "|" in args:
            title, description = args.split("|", 1)
            title = title.strip()
            description = description.strip()
        else:
            title = args.strip()
            description = title

        if not title:
            return "Usage: /task <story_id> <title> | <description>"

        task = await self.manager.create_task(
            story_id=story_id,
            phone_number=phone,
            project_name=project_name,
            title=title,
            description=description,
        )

        return (
            f"Created Task #{task.id}: {title}\n"
            f"In Story #{story_id}: {story.title}\n\n"
            f"Queue with: /queue story {story_id}"
        )

    async def _show_task(self, phone: str, task_id: int) -> str:
        """Show task details."""
        task = await self.manager.get_task(task_id)
        if not task:
            return f"Task #{task_id} not found."

        lines = [
            f"Task #{task.id}: {task.title}",
            f"Status: {task.status.value}",
            f"Story: #{task.story_id}",
            f"Project: {task.project_name}",
            f"Retries: {task.retry_count}/{task.max_retries}",
            "",
            f"Description:\n{task.description[:500]}",
        ]

        if task.error_message:
            lines.append(f"\nError: {task.error_message[:300]}")

        if task.files_changed:
            lines.append(f"\nFiles changed: {', '.join(task.files_changed[:5])}")

        return "\n".join(lines)

    def _task_help(self) -> str:
        return """Task Commands:
/task <story_id> <title> | <description> - Create task
/task <id> - Show task details

Example:
/task 1 Create login form | Build HTML form with email/password fields"""

    # ========== /tasks Command ==========

    async def handle_tasks(self, phone: str, args: str) -> str:
        """/tasks command handler - list tasks."""
        project_name, _ = self.get_current_project(phone)

        status_filter = None
        if args.strip():
            try:
                status_filter = TaskStatus(args.strip().lower())
            except ValueError:
                return f"Invalid status. Use: {', '.join(s.value for s in TaskStatus)}"

        tasks = await self.manager.list_tasks(
            phone_number=phone,
            project_name=project_name,
            status=status_filter,
        )

        if not tasks:
            return "No tasks found."

        # Group by status
        by_status = {}
        for task in tasks:
            status = task.status.value
            if status not in by_status:
                by_status[status] = []
            by_status[status].append(task)

        lines = ["Tasks:"]
        for status in ["queued", "in_progress", "pending", "completed", "failed"]:
            if status in by_status:
                lines.append(f"\n{status.upper()}:")
                for task in by_status[status][:10]:
                    lines.append(f"  #{task.id} {task.title[:40]}")
                if len(by_status[status]) > 10:
                    lines.append(f"  ... and {len(by_status[status]) - 10} more")

        stats = await self.manager.get_task_stats(phone, project_name)
        lines.append(f"\nTotal: {stats['total']} | Today: {stats['completed_today']} done, {stats['failed_today']} failed")

        return "\n".join(lines)

    # ========== /autonomous Command ==========

    async def handle_autonomous(self, phone: str, args: str) -> str:
        """/autonomous command handler."""
        if not args.strip():
            return await self._autonomous_status(phone)

        subcommand = args.strip().lower().split()[0]

        if subcommand == "start":
            await self.manager.start_loop()
            return "Autonomous loop started. Tasks will be processed automatically."
        elif subcommand == "stop":
            await self.manager.stop_loop()
            return "Autonomous loop stopped."
        elif subcommand == "pause":
            await self.manager.pause_loop()
            return "Autonomous loop paused. Current task will finish first."
        elif subcommand == "resume":
            await self.manager.resume_loop()
            return "Autonomous loop resumed."
        elif subcommand == "status":
            return await self._autonomous_status(phone)
        else:
            return """Autonomous Commands:
/autonomous - Show status
/autonomous start - Start processing
/autonomous pause - Pause (finishes current task)
/autonomous resume - Resume processing
/autonomous stop - Stop processing"""

    async def _autonomous_status(self, phone: str) -> str:
        """Show autonomous loop status."""
        status = await self.manager.get_loop_status()

        state = "RUNNING" if status.is_running else "STOPPED"
        if status.is_paused:
            state = "PAUSED"

        lines = [
            f"Autonomous Loop: {state}",
            f"Tasks in queue: {status.tasks_queued}",
            f"Today: {status.tasks_completed_today} completed, {status.tasks_failed_today} failed",
        ]

        if status.current_task_id:
            lines.append(f"Currently executing: Task #{status.current_task_id}")

        if status.is_running:
            uptime_min = int(status.uptime_seconds / 60)
            lines.append(f"Uptime: {uptime_min} minutes")

        return "\n".join(lines)

    # ========== /queue Command ==========

    async def handle_queue(self, phone: str, args: str) -> str:
        """/queue command handler."""
        if not args.strip():
            return """Queue Commands:
/queue story <id> - Queue all tasks for a story
/queue prd <id> - Queue all tasks for a PRD"""

        parts = args.strip().split()
        if len(parts) < 2:
            return "Usage: /queue story <id> or /queue prd <id>"

        target_type = parts[0].lower()
        target_id = parts[1]

        if not target_id.isdigit():
            return "ID must be a number."

        target_id = int(target_id)

        if target_type == "story":
            count = await self.manager.queue_story(target_id)
            return f"Queued {count} tasks for Story #{target_id}"
        elif target_type == "prd":
            count = await self.manager.queue_prd(target_id)
            return f"Queued {count} tasks for PRD #{target_id}"
        else:
            return "Use: /queue story <id> or /queue prd <id>"

    # ========== /learnings Command ==========

    async def handle_learnings(self, phone: str, args: str) -> str:
        """/learnings command handler."""
        if not args.strip():
            return await self._list_learnings(phone)

        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower()
        subargs = parts[1] if len(parts) > 1 else ""

        if subcommand == "search":
            return await self._search_learnings(phone, subargs)
        elif subcommand == "add":
            return await self._add_learning(phone, subargs)
        else:
            # Treat as search query
            return await self._search_learnings(phone, args)

    async def _list_learnings(self, phone: str) -> str:
        """List recent learnings."""
        project_name, _ = self.get_current_project(phone)
        learnings = await self.manager.get_learnings(
            phone_number=phone,
            project_name=project_name,
            limit=20,
        )

        if not learnings:
            return "No learnings yet. They'll be extracted as tasks complete."

        lines = ["Recent Learnings:"]
        for l in learnings[:15]:
            lines.append(f"  [{l.category.value}] {l.title[:50]}")

        return "\n".join(lines)

    async def _search_learnings(self, phone: str, query: str) -> str:
        """Search learnings."""
        if not query:
            return "Usage: /learnings search <query>"

        project_name, _ = self.get_current_project(phone)
        learnings = await self.manager.search_learnings(
            phone_number=phone,
            query=query,
            project_name=project_name,
        )

        if not learnings:
            return f"No learnings found for: {query}"

        lines = [f"Learnings for '{query}':"]
        for l in learnings[:10]:
            lines.append(f"\n[{l.category.value}] {l.title}")
            lines.append(f"  {l.content[:150]}...")

        return "\n".join(lines)

    async def _add_learning(self, phone: str, args: str) -> str:
        """Manually add a learning."""
        if "|" not in args:
            return "Usage: /learnings add <category> | <title> | <content>\n\nCategories: pattern, pitfall, best_practice, debugging, testing"

        parts = args.split("|")
        if len(parts) < 3:
            return "Usage: /learnings add <category> | <title> | <content>"

        category_str = parts[0].strip().lower()
        title = parts[1].strip()
        content = "|".join(parts[2:]).strip()

        try:
            category = LearningCategory(category_str)
        except ValueError:
            valid = ", ".join(c.value for c in LearningCategory)
            return f"Invalid category. Use: {valid}"

        project_name, _ = self.get_current_project(phone)

        learning_id = await self.manager.add_learning(
            phone_number=phone,
            category=category,
            title=title,
            content=content,
            project_name=project_name,
        )

        return f"Learning #{learning_id} added: {title}"
