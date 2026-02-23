"""Configuration management for sidechannel."""

import os
import shutil
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv


class Config:
    """Configuration manager for the bot."""

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self.config_dir = config_dir

        # Load environment variables
        env_file = config_dir / ".env"
        if env_file.exists():
            load_dotenv(env_file)

        # Load settings
        self.settings = self._load_yaml("settings.yaml")
        self.projects = self._load_yaml("projects.yaml") or {"projects": []}

    def _load_yaml(self, filename: str) -> dict:
        """Load a YAML configuration file."""
        filepath = self.config_dir / filename
        if filepath.exists():
            with open(filepath, "r") as f:
                return yaml.safe_load(f) or {}
        return {}

    def save_projects(self):
        """Save the projects configuration."""
        filepath = self.config_dir / "projects.yaml"
        with open(filepath, "w") as f:
            yaml.dump(self.projects, f, default_flow_style=False)

    @property
    def allowed_numbers(self) -> List[str]:
        """Get list of allowed phone numbers."""
        return self.settings.get("allowed_numbers", [])

    @property
    def signal_api_url(self) -> str:
        """Get Signal API URL."""
        return self.settings.get("signal_api_url", "http://127.0.0.1:8080")

    @property
    def projects_base_path(self) -> Path:
        """Get base path for projects."""
        configured = self.settings.get("projects_base_path")
        if configured:
            return Path(configured).expanduser()
        return Path.home() / "projects"

    @property
    def log_dir(self) -> Path:
        """Get log directory path."""
        configured = self.settings.get("log_dir")
        if configured:
            return Path(configured).expanduser()
        return Path(__file__).parent.parent / "logs"

    @property
    def claude_timeout(self) -> int:
        """Get Claude command timeout in seconds (default 30 minutes)."""
        return self.settings.get("claude_timeout", 1800)

    @property
    def claude_max_turns(self) -> int:
        """Get max turns per Claude invocation to prevent token overflow (default 15)."""
        return self.settings.get("claude_max_turns", 15)

    @property
    def claude_path(self) -> str:
        """Get absolute path to Claude CLI binary."""
        configured = self.settings.get("claude_path")
        if configured:
            return configured
        # Try to find claude in PATH
        found = shutil.which("claude")
        if found:
            return found
        # Fallback to common locations
        home_local = Path.home() / ".local" / "bin" / "claude"
        if home_local.exists():
            return str(home_local)
        return "claude"  # Hope it's in PATH

    # sidechannel AI assistant configuration (supports OpenAI and Grok providers)
    @property
    def sidechannel_assistant_enabled(self) -> bool:
        """Whether sidechannel AI assistant is enabled."""
        sc_config = self.settings.get("sidechannel_assistant", {})
        if sc_config.get("enabled") is not None:
            return sc_config.get("enabled", False)
        # Fallback to legacy nova / grok config
        nova_config = self.settings.get("nova", {})
        if nova_config.get("enabled") is not None:
            return nova_config.get("enabled", False)
        grok_config = self.settings.get("grok", {})
        return grok_config.get("enabled", False)

    @property
    def grok_enabled(self) -> bool:
        """Backward-compatible alias for sidechannel_assistant_enabled."""
        return self.sidechannel_assistant_enabled

    @property
    def sidechannel_assistant_provider(self) -> str:
        """Detect which provider to use: 'openai' or 'grok'.

        Priority:
        1. Explicit sidechannel_assistant.provider setting
        2. Auto-detect from env: only OPENAI_API_KEY -> 'openai'
        3. Auto-detect from env: only GROK_API_KEY -> 'grok'
        4. Both keys present -> 'grok' (backward compat)
        5. Neither key -> 'grok' (will fail gracefully at call time)
        """
        sc_config = self.settings.get("sidechannel_assistant", {})
        explicit = sc_config.get("provider")
        if explicit:
            return explicit
        # Fallback to legacy nova config
        nova_config = self.settings.get("nova", {})
        explicit = nova_config.get("provider")
        if explicit:
            return explicit

        has_openai = bool(os.environ.get("OPENAI_API_KEY"))
        has_grok = bool(os.environ.get("GROK_API_KEY"))

        if has_openai and not has_grok:
            return "openai"
        # grok for: only grok, both, or neither
        return "grok"

    @property
    def sidechannel_assistant_api_key(self) -> str:
        """Return the API key for the active provider."""
        if self.sidechannel_assistant_provider == "openai":
            return os.environ.get("OPENAI_API_KEY", "")
        return os.environ.get("GROK_API_KEY", "")

    @property
    def sidechannel_assistant_api_url(self) -> str:
        """Return the API URL for the active provider."""
        sc_config = self.settings.get("sidechannel_assistant", {})
        custom_url = sc_config.get("api_url")
        if custom_url:
            return custom_url
        # Fallback to legacy nova config
        nova_config = self.settings.get("nova", {})
        custom_url = nova_config.get("api_url")
        if custom_url:
            return custom_url
        if self.sidechannel_assistant_provider == "openai":
            return "https://api.openai.com/v1/chat/completions"
        return "https://api.x.ai/v1/chat/completions"

    @property
    def sidechannel_assistant_model(self) -> str:
        """Return the model name for the active provider."""
        sc_config = self.settings.get("sidechannel_assistant", {})
        model = sc_config.get("model")
        if model:
            return model
        # Fallback to legacy nova / grok config
        nova_config = self.settings.get("nova", {})
        model = nova_config.get("model")
        if model:
            return model
        grok_config = self.settings.get("grok", {})
        model = grok_config.get("model")
        if model:
            return model
        # Provider default
        if self.sidechannel_assistant_provider == "openai":
            return "gpt-4o"
        return "grok-3-latest"

    @property
    def sidechannel_assistant_max_tokens(self) -> int:
        """Return max tokens for sidechannel assistant responses."""
        sc_config = self.settings.get("sidechannel_assistant", {})
        val = sc_config.get("max_tokens")
        if val is not None:
            return int(val)
        # Fallback to legacy nova / grok config
        nova_config = self.settings.get("nova", {})
        val = nova_config.get("max_tokens")
        if val is not None:
            return int(val)
        grok_config = self.settings.get("grok", {})
        val = grok_config.get("max_tokens")
        if val is not None:
            return int(val)
        return 1024

    # Memory configuration
    @property
    def memory_session_timeout(self) -> int:
        """Get session timeout in minutes for memory grouping."""
        memory_config = self.settings.get("memory", {})
        return memory_config.get("session_timeout", 30)

    @property
    def memory_max_context_tokens(self) -> int:
        """Get max tokens for memory context injection."""
        memory_config = self.settings.get("memory", {})
        return memory_config.get("max_context_tokens", 1500)

    @property
    def memory_embedding_model(self) -> str:
        """Get embedding model name for semantic search."""
        memory_config = self.settings.get("memory", {})
        return memory_config.get("embedding_model", "all-MiniLM-L6-v2")

    # Autonomous system configuration
    @property
    def autonomous_enabled(self) -> bool:
        """Whether autonomous system is enabled."""
        auto_config = self.settings.get("autonomous", {})
        return auto_config.get("enabled", True)

    @property
    def autonomous_poll_interval(self) -> int:
        """Seconds between queue polls."""
        auto_config = self.settings.get("autonomous", {})
        return auto_config.get("poll_interval", 30)

    @property
    def autonomous_max_retries(self) -> int:
        """Max retries for failed tasks."""
        auto_config = self.settings.get("autonomous", {})
        return auto_config.get("max_retries", 2)

    @property
    def autonomous_quality_gates(self) -> bool:
        """Whether to run tests/typecheck after tasks."""
        auto_config = self.settings.get("autonomous", {})
        return auto_config.get("quality_gates", True)

    @property
    def autonomous_max_parallel(self) -> int:
        """Max parallel task workers (default 3, max 10)."""
        auto_config = self.settings.get("autonomous", {})
        val = auto_config.get("max_parallel", 3)
        return min(int(val), 10)

    @property
    def autonomous_verification(self) -> bool:
        """Whether to run independent verification on task output."""
        auto_config = self.settings.get("autonomous", {})
        return auto_config.get("verification", True)

    @property
    def autonomous_effort_levels(self) -> dict:
        """Effort level mapping for task types."""
        defaults = {
            "prd_breakdown": "max",
            "implementation": "high",
            "bug_fix": "high",
            "refactor": "medium",
            "testing": "medium",
            "verification": "max",
        }
        auto_config = self.settings.get("autonomous", {})
        user_levels = auto_config.get("effort_levels", {})
        return {**defaults, **user_levels}

    @property
    def allowed_paths(self) -> List[Path]:
        """Get list of additional allowed paths (outside projects_base_path)."""
        paths = self.settings.get("allowed_paths", [])
        return [Path(p).expanduser() for p in paths]

    @property
    def plugins_dir(self) -> Path:
        """Get plugins directory path."""
        configured = self.settings.get("plugins_dir")
        if configured:
            return Path(configured).expanduser()
        return Path(self.config_dir).parent / "plugins"

    def get_project_list(self) -> List[dict]:
        """Get list of registered projects."""
        return self.projects.get("projects", [])

    def add_project(self, name: str, path: str, description: str = "") -> bool:
        """Add a new project to the registry."""
        # Check if project already exists
        for p in self.projects.get("projects", []):
            if p["name"] == name:
                return False

        if "projects" not in self.projects:
            self.projects["projects"] = []

        self.projects["projects"].append({
            "name": name,
            "path": path,
            "description": description
        })
        self.save_projects()
        return True

    def get_project_path(self, name: str) -> Optional[Path]:
        """Get the path for a project by name."""
        for p in self.projects.get("projects", []):
            if p["name"] == name:
                return Path(p["path"])
        return None


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
