"""Plugin discovery, loading, and lifecycle management."""

import importlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

import structlog

from .plugin_base import (
    CommandHandler,
    HelpSection,
    MessageMatcher,
    PluginContext,
    SidechannelPlugin,
)

logger = structlog.get_logger()

# Register 'sidechannel' as a module alias so plugins can always
# `from sidechannel.plugin_base import ...` even when the package
# is deployed as 'signal_claude_bot' (via sync.sh).
_parent_pkg = __name__.rsplit(".", 1)[0]
if _parent_pkg != "sidechannel":
    # Alias the top-level package
    sys.modules["sidechannel"] = sys.modules[_parent_pkg]
    # Also alias all already-imported submodules (e.g. plugin_base)
    # so `from sidechannel.plugin_base import X` returns the same
    # class objects as `from signal_claude_bot.plugin_base import X`.
    _prefix = _parent_pkg + "."
    for _key, _mod in list(sys.modules.items()):
        if _key.startswith(_prefix):
            _alias = "sidechannel" + _key[len(_parent_pkg):]
            sys.modules[_alias] = _mod


class PluginLoader:
    """Discovers, loads, and manages the lifecycle of sidechannel plugins."""

    def __init__(
        self,
        plugins_dir: Path,
        settings: dict,
        send_message: Callable[[str, str], Awaitable[None]],
        allowed_numbers: List[str],
        data_dir: Path,
    ):
        self.plugins_dir = plugins_dir
        self._settings = settings
        self._send_message = send_message
        self._allowed_numbers = allowed_numbers
        self._data_dir = data_dir
        self.plugins: List[SidechannelPlugin] = []
        self._commands: Dict[str, CommandHandler] = {}
        self._matchers: List[MessageMatcher] = []
        self._help: List[HelpSection] = []

    def discover_and_load(self) -> None:
        """Scan plugins_dir for plugin.py files and load them."""
        if not self.plugins_dir.is_dir():
            logger.info("plugin_loader_no_dir", path=str(self.plugins_dir))
            return

        # Add plugins_dir to sys.path so plugins can import each other
        plugins_str = str(self.plugins_dir)
        if plugins_str not in sys.path:
            sys.path.append(plugins_str)

        # Plugin allowlist: if configured, only load listed plugins
        allowlist = self._settings.get("plugin_allowlist")
        if allowlist is not None and not isinstance(allowlist, list):
            logger.error("plugin_allowlist_invalid_type", type=type(allowlist).__name__)
            allowlist = None

        for plugin_dir in sorted(self.plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            plugin_file = plugin_dir / "plugin.py"
            if not plugin_file.is_file():
                continue

            plugin_name = plugin_dir.name

            # Enforce allowlist if configured
            if allowlist is not None and plugin_name not in allowlist:
                logger.warning(
                    "plugin_blocked_not_in_allowlist",
                    plugin=plugin_name,
                    allowlist=allowlist,
                )
                continue

            try:
                self._load_plugin(plugin_name, plugin_file)
            except Exception as e:
                logger.error(
                    "plugin_load_failed",
                    plugin=plugin_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )

        logger.info(
            "plugin_loader_complete",
            plugins_loaded=len(self.plugins),
            commands=len(self._commands),
            matchers=len(self._matchers),
        )

    def _load_plugin(self, plugin_name: str, plugin_file: Path) -> None:
        """Load a single plugin from its plugin.py file."""
        # Check if plugin is disabled in config
        plugin_config = self._settings.get("plugins", {}).get(plugin_name, {})
        if isinstance(plugin_config, dict) and plugin_config.get("enabled") is False:
            logger.info("plugin_skipped_disabled", plugin=plugin_name)
            return

        # Import the module
        module_name = f"{plugin_name}.plugin"
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find the SidechannelPlugin subclass
        plugin_cls = None
        for attr_name, attr in module.__dict__.items():
            if (
                isinstance(attr, type)
                and issubclass(attr, SidechannelPlugin)
                and attr is not SidechannelPlugin
            ):
                plugin_cls = attr
                break

        if plugin_cls is None:
            logger.warning("plugin_no_class_found", plugin=plugin_name)
            return

        # Create context and instantiate
        ctx = PluginContext(
            plugin_name=plugin_name,
            send_message=self._send_message,
            settings=self._settings,
            allowed_numbers=self._allowed_numbers,
            data_dir=self._data_dir,
        )

        plugin = plugin_cls(ctx)
        self.plugins.append(plugin)

        # Collect commands (with validation)
        BUILTIN_COMMANDS = frozenset({
            "help", "projects", "select", "add", "new", "ask", "do",
            "complex", "cancel", "summary", "remember", "recall",
            "history", "forget", "memories", "preferences", "global",
            "prd", "story", "task", "tasks", "autonomous", "queue",
            "learnings", "status",
        })

        for cmd_name, handler in plugin.commands().items():
            if not re.match(r'^[a-z][a-z0-9_-]*$', cmd_name):
                logger.warning("plugin_invalid_command_name", command=cmd_name, plugin=plugin_name)
                continue
            if cmd_name in BUILTIN_COMMANDS:
                logger.warning("plugin_builtin_override_blocked", command=cmd_name, plugin=plugin_name)
                continue
            if cmd_name in self._commands:
                logger.warning(
                    "plugin_command_conflict",
                    command=cmd_name,
                    plugin=plugin_name,
                )
            else:
                self._commands[cmd_name] = handler

        # Collect matchers
        self._matchers.extend(plugin.message_matchers())

        # Collect help
        self._help.extend(plugin.help_sections())

        logger.info(
            "plugin_loaded",
            plugin=plugin_name,
            version=plugin.version,
            commands=list(plugin.commands().keys()),
        )

    async def start_all(self) -> None:
        """Call on_start() on all loaded plugins."""
        for plugin in self.plugins:
            try:
                await plugin.on_start()
                logger.info("plugin_started", plugin=plugin.name or type(plugin).__name__)
            except Exception as e:
                logger.error(
                    "plugin_start_failed",
                    plugin=plugin.name or type(plugin).__name__,
                    error=str(e),
                )

    async def stop_all(self) -> None:
        """Call on_stop() on all loaded plugins (reverse order)."""
        for plugin in reversed(self.plugins):
            try:
                await plugin.on_stop()
                logger.info("plugin_stopped", plugin=plugin.name or type(plugin).__name__)
            except Exception as e:
                logger.error(
                    "plugin_stop_failed",
                    plugin=plugin.name or type(plugin).__name__,
                    error=str(e),
                )

    def get_all_commands(self) -> Dict[str, CommandHandler]:
        """Return merged command dict from all plugins."""
        return dict(self._commands)

    def get_sorted_matchers(self) -> List[MessageMatcher]:
        """Return all matchers sorted by priority (lower first)."""
        return sorted(self._matchers, key=lambda m: m.priority)

    def get_all_help(self) -> List[HelpSection]:
        """Return merged help sections from all plugins."""
        return list(self._help)
