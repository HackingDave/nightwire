# Contributing to nightwire

Thank you for your interest in contributing to nightwire!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/nightwire.git`
3. Create a branch: `git checkout -b feature/your-feature`
4. Make your changes
5. Run tests: `python -m pytest tests/ -v --tb=short`
6. Commit: `git commit -m "Add your feature"`
7. Push: `git push origin feature/your-feature`
8. Open a Pull Request

## Architecture Overview

```
nightwire/
├── bot.py              # Main bot: message routing, command dispatch
├── claude_runner.py    # Claude CLI subprocess with retry and error classification
├── config.py           # YAML/env configuration loader
├── nightwire_runner.py    # nightwire AI assistant (OpenAI / Grok provider)
├── security.py         # Auth, rate limiting, path validation, input sanitization
├── project_manager.py  # Multi-project management
├── plugin_base.py      # Plugin base class and PluginContext API
├── plugin_loader.py    # Plugin auto-discovery and lifecycle management
├── exceptions.py       # Structured exception hierarchy
├── attachments.py      # Image download and processing
├── prd_builder.py      # Robust JSON parsing for autonomous PRDs
├── skill_registry.py   # Claude plugin discovery and matching
├── autonomous/
│   ├── loop.py         # Parallel task dispatch with dependency resolution
│   ├── executor.py     # Task execution with git safety and verification
│   ├── verifier.py     # Independent code review (fail-closed for security)
│   ├── quality_gates.py # Test runner with baseline snapshots
│   ├── database.py     # SQLite operations for PRDs, stories, tasks
│   ├── models.py       # Pydantic models for all autonomous data
│   ├── commands.py     # Signal command handlers for autonomous system
│   └── exceptions.py   # Exception hierarchy
└── memory/
    ├── manager.py      # Memory API: store, recall, semantic search
    ├── database.py     # SQLite + sqlite-vec for vector storage
    └── haiku_summarizer.py  # Conversation summarization
```

### Key Design Decisions
- **Fail-closed verification**: Security concerns or logic errors in code review block task completion
- **Parallel execution**: Tasks dispatched to concurrent workers with dependency-aware batching
- **Regression detection**: Pre-task test baselines compared to post-task results
- **Error retry**: Transient failures (rate limits, timeouts) retried with exponential backoff

## Development Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in editable mode with dev dependencies (pyproject.toml)
pip install -e ".[dev]"

# Fallback: if using requirements.txt
# pip install -r requirements.txt
# pip install pytest pytest-asyncio black ruff

# Run linting
ruff check nightwire/
black --check nightwire/

# Run tests
python -m pytest tests/ -v --tb=short
```

## Writing Plugins

nightwire supports custom plugins in the `plugins/` directory. See `plugins/README.md` for the full guide.

Quick start:
1. Create `plugins/my_plugin/plugin.py`
2. Subclass `NightwirePlugin` from `nightwire.plugin_base`
3. Override `commands()`, `message_matchers()`, `on_start()`, `on_stop()`, `help_sections()` as needed
4. Add config to `config/settings.yaml` under `plugins.my_plugin`
5. Restart the bot — your plugin loads automatically

## Code Style

- Use [Black](https://github.com/psf/black) for formatting
- Use [Ruff](https://github.com/astral-sh/ruff) for linting
- Follow PEP 8 conventions
- Add type hints to function signatures
- Write docstrings for public functions

## Pull Request Guidelines

- Keep PRs focused on a single feature or fix
- Update documentation if needed
- Add tests for new functionality
- Ensure all tests pass
- Write clear commit messages

## Reporting Issues

When reporting bugs, please include:

- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs

## Feature Requests

Feature requests are welcome! Please describe:

- The problem you're trying to solve
- Your proposed solution
- Any alternatives you've considered

## Code of Conduct

Be respectful and constructive in all interactions.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
