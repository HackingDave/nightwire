"""Plugin discovery, loading, and lifecycle management.

Scans the plugins directory for ``plugin.py`` files, instantiates
NightwirePlugin subclasses, and collects their commands, message
matchers, help sections, and agent specifications. Manages
start/stop lifecycle hooks and generates agent catalog prompts.

Key classes:
    PluginLoader: Discovers, loads, validates, and manages plugins.
"""

import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

import structlog

from .plugin_base import (
    AgentSpec,
    CommandHandler,
    HelpSection,
    MessageMatcher,
    NightwirePlugin,
    PluginContext,
)

logger = structlog.get_logger("nightwire.plugins")

# Register 'nightwire' as the canonical module name and alias 'sidechannel'
# for backwards compatibility, so plugins can use either
# `from nightwire.plugin_base import ...` or `from sidechannel.plugin_base import ...`
_parent_pkg = __name__.rsplit(".", 1)[0]
if _parent_pkg != "nightwire":
    sys.modules["nightwire"] = sys.modules[_parent_pkg]
    _prefix = _parent_pkg + "."
    for _key, _mod in list(sys.modules.items()):
        if _key.startswith(_prefix):
            sys.modules["nightwire" + _key[len(_parent_pkg):]] = _mod
# Always alias 'sidechannel' -> current package for backwards compat
sys.modules.setdefault("sidechannel", sys.modules[_parent_pkg])
_prefix = _parent_pkg + "."
for _key, _mod in list(sys.modules.items()):
    if _key.startswith(_prefix):
        sys.modules.setdefault("sidechannel" + _key[len(_parent_pkg):], _mod)


class PluginLoader:
    """Discovers, loads, and manages the lifecycle of nightwire plugins."""

    def __init__(
        self,
        plugins_dir: Path,
        settings: dict,
        send_message: Callable[[str, str], Awaitable[None]],
        allowed_numbers: List[str],
        data_dir: Path,
    ):
        """Initialize the plugin loader.

        Args:
            plugins_dir: Directory to scan for plugin subdirs.
            settings: Full settings.yaml dict (passed to contexts).
            send_message: Async callback for sending Signal messages.
            allowed_numbers: Authorized phone numbers/UUIDs.
            data_dir: Base data directory for plugin storage.
        """
        self.plugins_dir = plugins_dir
        self._settings = settings
        self._send_message = send_message
        self._allowed_numbers = allowed_numbers
        self._data_dir = data_dir
        self.plugins: List[NightwirePlugin] = []
        self._commands: Dict[str, CommandHandler] = {}
        self._matchers: List[MessageMatcher] = []
        self._help: List[HelpSection] = []
        self._agents: Dict[str, AgentSpec] = {}

    def discover_and_load(self) -> None:
        """Scan plugins_dir for plugin.py files and load them.

        Respects the ``plugin_allowlist`` setting and per-plugin
        ``enabled`` flags. Validates command names against
        BUILTIN_COMMANDS to prevent override conflicts.
        """
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
            agents=len(self._agents),
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
        if spec is None or spec.loader is None:
            logger.warning(
                "plugin_spec_failed",
                plugin=plugin_name, path=str(plugin_file),
            )
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find the NightwirePlugin subclass
        plugin_cls = None
        for attr_name, attr in module.__dict__.items():
            if (
                isinstance(attr, type)
                and issubclass(attr, NightwirePlugin)
                and attr is not NightwirePlugin
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
        from .commands.base import BUILTIN_COMMANDS

        for cmd_name, handler in plugin.commands().items():
            if not re.match(r'^[a-z][a-z0-9_-]*$', cmd_name):
                logger.warning("plugin_invalid_command_name", command=cmd_name, plugin=plugin_name)
                continue
            if cmd_name in BUILTIN_COMMANDS:
                logger.warning(
                    "plugin_builtin_override_blocked",
                    command=cmd_name,
                    plugin=plugin_name,
                )
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

        # Collect agents (M11)
        for agent_name, spec in plugin.agents().items():
            if not re.match(r'^[a-z][a-z0-9-]*$', agent_name):
                logger.warning(
                    "plugin_invalid_agent_name",
                    agent=agent_name,
                    plugin=plugin_name,
                )
                continue
            if agent_name in self._agents:
                logger.warning(
                    "plugin_agent_conflict",
                    agent=agent_name,
                    plugin=plugin_name,
                )
                continue
            self._agents[agent_name] = spec

        logger.info(
            "plugin_loaded",
            plugin=plugin_name,
            version=plugin.version,
            commands=list(plugin.commands().keys()),
            agents=list(plugin.agents().keys()),
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

    def get_all_agents(self) -> Dict[str, AgentSpec]:
        """Return merged agent dict from all plugins."""
        return dict(self._agents)

    def get_agent_catalog_prompt(self) -> str:
        """Generate a prompt section describing all registered agents.

        Returns an empty string when no agents are registered (zero
        token cost). When agents exist, returns a markdown section
        listing each agent's name and description.
        """
        if not self._agents:
            return ""
        lines = [
            "## Available Plugin Agents",
            "The following agents are provided by plugins and may be"
            " available during task execution:",
        ]
        for name, spec in self._agents.items():
            lines.append(f"- **{name}**: {spec.description}")
        lines.append(
            "\nNote: Agent dispatch is controlled by the system."
            " Mention an agent by name if you believe it would be"
            " useful for the current task."
        )
        return "\n".join(lines)

    def get_agent_definitions_json(self) -> "Optional[str]":
        """Convert registered agents to ``--agents`` JSON format.

        Returns None when no agents are registered. When agents exist,
        returns a JSON string suitable for the CLI ``--agents`` flag.
        """
        if not self._agents:
            return None
        definitions = {}
        for name, spec in self._agents.items():
            agent_def: dict = {"description": spec.description}
            if spec.prompt:
                agent_def["prompt"] = spec.prompt
            definitions[name] = agent_def
        return json.dumps(definitions)

    def get_all_help(self) -> List[HelpSection]:
        """Return merged help sections from all plugins."""
        return list(self._help)
