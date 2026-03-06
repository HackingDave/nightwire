"""Memory command handlers for Signal bot.

Provides slash-command handlers for storing explicit memories, searching
past conversations via semantic search, viewing history, managing
preferences, and deleting stored data. Each handler is registered via
``_make_memory_commands()`` in bot.py with project-scoping closures.
"""

from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from .manager import MemoryManager

logger = structlog.get_logger("nightwire.memory")


class MemoryCommands:
    """Handlers for memory-related slash commands."""

    def __init__(self, memory_manager: "MemoryManager"):
        """Initialize with a MemoryManager instance.

        Args:
            memory_manager: Provides store, search, and delete operations.
        """
        self.memory = memory_manager

    async def handle_remember(
        self, phone: str, args: str, project: Optional[str] = None,
    ) -> str:
        """Store an explicit memory, scoped to the current project.

        Signal usage::

            /remember Always use UTC timestamps in this project
            /global remember Use snake_case for all Python files

        Args:
            phone: Phone number or UUID of the sender.
            args: Text to remember.
            project: Project scope (None = global).

        Returns:
            Confirmation with preview and memory ID, or usage help.
        """
        if not args.strip():
            if project:
                return (
                    f"Usage: /remember <something to remember>"
                    f"\n\nThis will be saved for project: {project}"
                    f"\nUse /global remember for cross-project memories."
                )
            return (
                "Usage: /remember <something to remember>"
                "\n\nNo project selected - this will be a global memory."
            )

        content = args.strip()
        memory_id = await self.memory.remember(phone, content, project_name=project)
        preview = content[:50] + "..." if len(content) > 50 else content
        project_info = f" [{project}]" if project else " [global]"
        return f"Remembered{project_info}: \"{preview}\" (ID: {memory_id})"

    async def handle_recall(
        self, phone: str, args: str, project: Optional[str] = None,
    ) -> str:
        """Semantic search over past conversations and stored memories.

        Uses vector embeddings for relevance-based matching.

        Signal usage::

            /recall database migration strategy
            /global recall deployment process

        Args:
            phone: Phone number or UUID of the sender.
            args: Search query text.
            project: Project scope (None = search all projects).

        Returns:
            Formatted list of matching memories with previews, or usage help.
        """
        if not args.strip():
            if project:
                return (
                    f"Usage: /recall <search query>"
                    f"\n\nSearching in project: {project}"
                    f"\nUse /global recall to search all projects."
                )
            return "Usage: /recall <search query>\n\nNo project selected - searching all projects."

        query = args.strip()
        results = await self.memory.semantic_search(phone, query, limit=5, project_name=project)

        if not results:
            scope = f" in {project}" if project else ""
            return f"No relevant memories found{scope} for: \"{query}\""

        scope = f" [{project}]" if project else " [all projects]"
        lines = [f"Found {len(results)} relevant memories{scope}:\n"]
        for i, r in enumerate(results, 1):
            date = r.timestamp.strftime("%Y-%m-%d")
            role = "You" if r.role == "user" else "Claude"
            preview = r.content[:100].replace("\n", " ")
            if len(r.content) > 100:
                preview += "..."
            # Show project tag if searching globally
            proj_tag = f" [{r.project_name}]" if r.project_name and not project else ""
            lines.append(f"{i}. [{date}]{proj_tag} {role}: {preview}")

        return "\n".join(lines)

    async def handle_history(
        self, phone: str, args: str, project: Optional[str] = None,
    ) -> str:
        """Show recent conversation history for the current project.

        Signal usage::

            /history                        — Last 10 messages (default)
            /history 20                     — Last 20 messages
            /global history 30              — Last 30 across all projects

        Args:
            phone: Phone number or UUID of the sender.
            args: Optional message count (1-50, default 10).
            project: Project scope (None = all projects).

        Returns:
            Chronological list of recent messages with timestamps.
        """
        limit = 10
        if args.strip():
            try:
                limit = int(args.strip())
                limit = max(1, min(limit, 50))  # Clamp between 1 and 50
            except ValueError:
                return "Usage: /history [count]\n\nExample: /history 20"

        history = await self.memory.get_history(phone, limit=limit, project_name=project)

        if not history:
            scope = f" for {project}" if project else ""
            return f"No conversation history found{scope}."

        scope = f" [{project}]" if project else " [all projects]"
        lines = [f"Last {len(history)} messages{scope}:\n"]
        for msg in history:
            date = msg.timestamp.strftime("%m/%d %H:%M")
            role = "You" if msg.role == "user" else "Claude"
            preview = msg.content[:80].replace("\n", " ")
            if len(msg.content) > 80:
                preview += "..."
            lines.append(f"[{date}] {role}: {preview}")

        return "\n".join(lines)

    async def handle_forget(self, phone: str, args: str) -> str:
        """Delete stored data by scope.

        Signal usage::

            /forget all                     — Delete all your data
            /forget preferences             — Clear learned preferences only
            /forget today                   — Delete today's conversations only

        Args:
            phone: Phone number or UUID of the sender.
            args: Scope — ``all``, ``preferences``, or ``today``.

        Returns:
            Confirmation of deletion or usage help.
        """
        target = args.strip().lower() if args else ""

        if not target or target == "help":
            return (
                "Usage: /forget <scope>\n\n"
                "Scopes:\n"
                "  all - Delete all your data\n"
                "  preferences - Clear learned preferences\n"
                "  today - Delete today's conversations"
            )

        if target not in ["all", "preferences", "today"]:
            return f"Unknown scope: \"{target}\"\n\nValid scopes: all, preferences, today"

        success = await self.memory.forget(phone, target)

        if success:
            if target == "all":
                return "All your data has been deleted."
            elif target == "preferences":
                return "Your preferences have been cleared."
            elif target == "today":
                return "Today's conversations have been deleted."

        return "Nothing to delete."

    async def handle_memories(
        self, phone: str, args: str, project: Optional[str] = None,
    ) -> str:
        """List all explicitly stored memories for the current project.

        Signal usage::

            /memories                       — List project memories
            /global memories                — List all memories

        Args:
            phone: Phone number or UUID of the sender.
            args: Unused.
            project: Project scope (None = all projects).

        Returns:
            Numbered list of stored memories with dates and previews.
        """
        memories = await self.memory.get_memories(phone, limit=20, project_name=project)

        if not memories:
            scope = f" for {project}" if project else ""
            return f"No memories stored{scope}. Use /remember <text> to store memories."

        scope = f" [{project}]" if project else " [all projects]"
        lines = [f"Stored memories{scope} ({len(memories)}):\n"]
        for i, m in enumerate(memories, 1):
            date = m.created_at.strftime("%Y-%m-%d")
            preview = m.memory_text[:60]
            if len(m.memory_text) > 60:
                preview += "..."
            # Show project tag if viewing globally
            proj_tag = f" [{m.project_name}]" if m.project_name and not project else ""
            lines.append(f"{i}. [{date}]{proj_tag} {preview}")

        return "\n".join(lines)

    async def handle_preferences(self, phone: str, args: str) -> str:
        """List automatically learned user preferences grouped by category.

        Signal usage::

            /preferences

        Args:
            phone: Phone number or UUID of the sender.
            args: Unused.

        Returns:
            Preferences grouped by category, or a message if none stored.
        """
        prefs = await self.memory.get_preferences(phone)

        if not prefs:
            return "No preferences stored yet."

        lines = ["Your preferences:\n"]
        by_category: dict[str, list] = {}

        for p in prefs:
            if p.category not in by_category:
                by_category[p.category] = []
            by_category[p.category].append(p)

        for category, items in sorted(by_category.items()):
            lines.append(f"\n{category.upper()}:")
            for p in items:
                lines.append(f"  - {p.key}: {p.value}")

        return "\n".join(lines)


def get_memory_help_metadata():
    """Return HelpMetadata for all memory commands."""
    from ..commands.base import HelpMetadata

    return {
        "remember": HelpMetadata(
            description="Store a fact or preference for the current project",
            usage="/remember <text>",
            examples=[
                "/remember We use Black for formatting",
                "/remember Always run tests with --tb=short",
            ],
        ),
        "recall": HelpMetadata(
            description="Semantically search past conversations and memories",
            usage="/recall <query>",
            examples=["/recall How did we set up migrations?"],
        ),
        "memories": HelpMetadata(
            description="List all stored memories for the current project",
            usage="/memories",
            examples=["/memories"],
        ),
        "history": HelpMetadata(
            description="View recent message history",
            usage="/history [count]",
            examples=["/history", "/history 20"],
        ),
        "forget": HelpMetadata(
            description="Delete your data by scope",
            usage="/forget <all|preferences|today>",
            examples=["/forget today", "/forget preferences", "/forget all"],
        ),
        "preferences": HelpMetadata(
            description="View your stored preferences",
            usage="/preferences",
            examples=["/preferences"],
        ),
    }
