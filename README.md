# sidechannel

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Claude](https://img.shields.io/badge/Claude-AI-purple.svg)](https://anthropic.com)
[![Signal](https://img.shields.io/badge/Signal-Messenger-blue.svg)](https://signal.org)

A Signal messaging bot that integrates Claude AI for intelligent conversations, code assistance, and autonomous development tasks with independent verification, parallel execution, and production-grade reliability.

## Why sidechannel?

Most AI coding tools require you to sit at your computer. sidechannel lets you manage your entire development workflow from your phone through Signal's end-to-end encrypted messaging. Whether you're commuting, in a meeting, or just away from your desk, you can:

- **Ship code from your phone** - Ask Claude to implement features, fix bugs, or refactor code on any of your projects, all from a Signal message
- **Delegate complex projects** - Describe what you want built, and sidechannel breaks it into a full PRD with stories and tasks, then executes them autonomously with parallel workers
- **Never lose context** - Episodic memory with vector embeddings means sidechannel remembers your conversations, project preferences, and past decisions across sessions
- **Trust the output** - Every autonomous task is independently verified by a separate Claude context using a fail-closed security model. Code that introduces security issues or logic errors is rejected automatically
- **Use your preferred AI provider** - Built-in support for both OpenAI and Grok as quick-response assistants, auto-detected from your API keys
- **Stay secure** - Phone number allowlist, end-to-end encryption via Signal, rate limiting, path validation hardening, and no message content logging

### Key Benefits

**Memory That Actually Works**
Unlike chat-based tools that forget everything when you close a tab, sidechannel's episodic memory system stores conversations with vector embeddings. When you ask Claude to work on something, it automatically retrieves relevant context from past conversations, stored memories, and project-specific knowledge. Your `/remember` facts persist forever. Session context groups related messages automatically.

**Autonomous Development at Scale**
Send `/complex Add user authentication with JWT tokens` and sidechannel will:
1. Use Claude to analyze the task and generate a full PRD
2. Break it into stories with focused, atomic tasks
3. Dispatch tasks to parallel workers (up to 10 concurrent)
4. Independently verify each task's output for security and correctness
5. Run quality gates (test baselines + regression detection)
6. Auto-fix verification failures (up to 2 attempts)
7. Send you progress updates via Signal as work completes

**Production-Grade Reliability**
- Transient errors (rate limits, timeouts) retried with exponential backoff
- Stale tasks automatically recovered on restart
- Circular dependency detection prevents deadlock
- Git checkpoints before every task, atomic commits after
- Baseline test snapshots distinguish new regressions from pre-existing failures

---

## Architecture

```
+-------------------+     +-------------------+     +---------------------+
|                   |     |                   |     |                     |
|  Signal Mobile    |<--->|  Signal CLI API   |<--->|    sidechannel      |
|                   |     |  (Docker)         |     |    (Python)         |
+-------------------+     +-------------------+     +---------------------+
                                                       |             |
                                              +--------+------+  +--+-------------+
                                              |               |  |                |
                                              | Autonomous    |  | Memory System  |
                                              | Loop          |  | (SQLite + Vec) |
                                              +-------+-------+  +----------------+
                                                      |
                              +-------------------------+-------------------------+
                              |                         |                         |
                    +---------+---------+   +-----------+---------+   +-----------+---------+
                    |  Worker 1         |   |  Worker 2           |   |  Worker N           |
                    |  (Claude CLI)     |   |  (Claude CLI)       |   |  (Claude CLI)       |
                    +---------+---------+   +-----------+---------+   +-----------+---------+
                              |                         |                         |
                    +---------+---------+   +-----------+---------+   +-----------+---------+
                    |  Verifier 1       |   |  Verifier 2         |   |  Verifier N         |
                    |  (Independent     |   |  (Independent       |   |  (Independent       |
                    |   Claude Context) |   |   Claude Context)   |   |   Claude Context)   |
                    +-------------------+   +---------------------+   +---------------------+
                              |                         |                         |
                    +---------+---------+   +-----------+---------+   +-----------+---------+
                    |  Quality Gate     |   |  Quality Gate       |   |  Quality Gate       |
                    |  (Test Baseline   |   |  (Test Baseline     |   |  (Test Baseline     |
                    |   + Regression)   |   |   + Regression)     |   |   + Regression)     |
                    +-------------------+   +---------------------+   +---------------------+
```

## Quick Start

```bash
# Clone the repository
git clone https://github.com/hackingdave/sidechannel.git
cd sidechannel

# Run the installer
./install.sh
```

The installer will:
1. Check prerequisites (Python 3.10+, Docker, Claude CLI)
2. Create a virtual environment and install dependencies
3. Set up Signal CLI REST API with QR code device linking
4. Configure your phone number and API keys
5. Optionally install as a systemd service

## Requirements

- **Python 3.10+**
- **Docker** - For Signal CLI REST API
- **Claude CLI** - [Installation guide](https://docs.anthropic.com/en/docs/claude-code)
- **Signal account** - Linked to the bot as a secondary device

---

## Commands Reference

### Project Management

These commands let you register, select, and navigate between multiple codebases.

| Command | Description |
|---------|-------------|
| `/projects` | List all registered projects |
| `/select <project>` | Set the active project for all code operations |
| `/add <name> [path] [description]` | Register an existing project directory |
| `/new <name> [description]` | Create a new project from scratch |
| `/status` | Show current project, running tasks, and autonomous loop state |
| `/help` | Show all available commands |

**Examples:**

```
/projects
  → Lists: myapp, backend-api, ml-pipeline

/select myapp
  → Active project: myapp (/home/user/projects/myapp)

/add backend-api /home/user/projects/api "REST API service"
  → Project 'backend-api' registered

/status
  → Project: myapp
    Running task (3 min elapsed): Add user authentication...
    [Autonomous Loop] Queued: 4 tasks | Completed today: 7
```

### Claude Integration

These are the core commands for interacting with Claude on your selected project. Claude has full access to the project's codebase and can read, analyze, and modify files.

| Command | Description |
|---------|-------------|
| `/ask <question>` | Ask Claude a read-only question about the project (architecture, how something works, debugging advice) |
| `/do <task>` | Have Claude make actual changes to the codebase (implement features, fix bugs, refactor) |
| `/complex <task>` | Break a large task into a PRD with stories and autonomous tasks, then execute them in parallel |
| `/summary` | Get a comprehensive summary of the project structure, technologies, and recent git changes |
| `/cancel` | Stop the currently running Claude task |

**Examples:**

```
/ask How does the authentication middleware work?
  → Claude analyzes the codebase and explains the auth flow,
    middleware chain, and token validation logic

/do Add input validation to the /users POST endpoint
  → Claude reads the endpoint, adds Pydantic models for
    request validation, and updates tests

/do Fix the race condition in the cache invalidation
  → Claude identifies the bug, adds proper locking, and
    verifies the fix doesn't break existing tests

/complex Build a REST API for task management with CRUD
         operations, authentication, pagination, and tests
  → Creates PRD #3: Task Management API
    Stories:
    - Database models and migrations (3 tasks)
    - CRUD endpoints (4 tasks)
    - Authentication middleware (2 tasks)
    - Pagination and filtering (2 tasks)
    - Test suite (3 tasks)
    Total: 14 tasks queued
    Autonomous loop: Started

/summary
  → Project: myapp (Python/FastAPI)
    Structure: 47 files, 3200 LOC
    Dependencies: FastAPI, SQLAlchemy, Pydantic
    Recent changes: Added user auth (3 commits today)
```

### Autonomous Development

The autonomous system handles complex, multi-step development tasks. It breaks work into atomic tasks, executes them in parallel, verifies each one independently, and runs quality gates.

| Command | Description |
|---------|-------------|
| `/prd <title>` | Create a new Product Requirements Document |
| `/prd list` | List all PRDs |
| `/prd <id>` | View PRD details with stories and task status |
| `/story <prd_id> <title> \| <description>` | Add a user story to a PRD |
| `/task <story_id> <title> \| <description>` | Add an individual task to a story |
| `/tasks [status]` | List tasks, optionally filtered by status (queued, running, completed, failed) |
| `/queue story\|prd <id>` | Queue all tasks from a story or entire PRD for execution |
| `/autonomous start` | Start the autonomous task execution loop |
| `/autonomous pause` | Pause execution (current task finishes, no new ones start) |
| `/autonomous stop` | Stop the loop and clear the queue |
| `/autonomous status` | Show detailed loop status: workers, queue depth, completion stats |
| `/learnings [search]` | View or search learnings captured from completed tasks |

**Examples:**

```
/prd Add OAuth2 social login
  → Created PRD #5: Add OAuth2 social login

/story 5 Google OAuth | Implement Google OAuth2 login flow
       with token exchange and profile creation
  → Created Story #12 under PRD #5

/task 12 Add Google callback endpoint | Create GET /auth/google/callback
      that exchanges the auth code for tokens and creates/links user
  → Created Task #34 under Story #12

/queue prd 5
  → Queued 8 tasks from PRD #5

/autonomous start
  → Starting autonomous loop (3 parallel workers)...
  → [2 min] Worker 1: Implementing Google callback endpoint
  → [3 min] Worker 2: Adding OAuth config model (parallel)
  → [5 min] Task #34 verified and passed quality gates

/tasks running
  → #35 [RUNNING] Add token refresh logic (2 min)
    #36 [RUNNING] Create OAuth settings page (1 min)

/autonomous status
  → Loop: RUNNING (3 workers)
    Current: 2 tasks executing
    Queued: 4 tasks remaining
    Completed today: 12 | Failed: 1

/learnings oauth
  → #7: Google OAuth requires PKCE flow for mobile clients
    #8: Token refresh should use sliding expiration window
```

### Memory & Context

The memory system gives sidechannel persistent context across sessions. Conversations are automatically stored and indexed with vector embeddings for semantic search. You can also store explicit facts that persist forever.

| Command | Description |
|---------|-------------|
| `/remember <text>` | Store a fact or preference for the current project |
| `/recall <query>` | Semantically search past conversations and memories |
| `/memories` | List all stored memories for the current project |
| `/history [count]` | View recent message history (default: 10 messages) |
| `/forget` | Clear your session memory |
| `/preferences` | View your stored preferences |
| `/global remember <text>` | Store a cross-project memory |
| `/global recall <query>` | Search across all projects |
| `/global memories` | List all cross-project memories |
| `/global history [count]` | View history across all projects |

**Examples:**

```
/remember We use Black for formatting and Ruff for linting
  → Stored memory for project 'myapp'

/remember Always run tests with --tb=short flag
  → Stored memory for project 'myapp'

/recall How did we set up the database migrations?
  → Found 3 relevant results:
    [2 days ago] Set up Alembic with async SQLAlchemy...
    [3 days ago] Created initial migration for users table...
    [Memory] We use PostgreSQL 15 with asyncpg driver

/memories
  → 1. We use Black for formatting and Ruff for linting
    2. Always run tests with --tb=short flag
    3. Deploy via GitHub Actions to AWS ECS

/history 5
  → Shows your last 5 messages and responses

/global remember Use conventional commits across all projects
  → Stored global memory

/global recall deployment process
  → Searches memories and conversations across all projects
```

### sidechannel AI Assistant (Optional)

When enabled with an OpenAI or Grok API key, you can ask quick questions directly without selecting a project. This is powered by GPT-4o or Grok and is ideal for general knowledge questions, quick advice, or anything that doesn't require project file access.

**How to use:**

```
sidechannel: what is the difference between REST and GraphQL?
  → Quick response comparing the two approaches

sidechannel, explain kubernetes pods
  → Concise explanation of K8s pod concepts

hey sidechannel what's the best way to handle JWT refresh tokens?
  → Practical advice on token refresh patterns

sidechannel
  → Hello! How can I help you?
```

The provider is auto-detected from your API keys. If only `OPENAI_API_KEY` is set, it uses OpenAI. If only `GROK_API_KEY` is set, it uses Grok. You can also set it explicitly in config.

---

## Configuration

### settings.yaml

```yaml
# Phone numbers authorized to use the bot (E.164 format)
allowed_numbers:
  - "+15551234567"

# Signal CLI REST API
signal_api_url: "http://127.0.0.1:8080"

# Claude CLI settings
claude:
  timeout: 600
  max_turns: 25

# Memory System
memory:
  session_timeout: 30        # Minutes before session expires
  max_context_tokens: 1500   # Max tokens for context window

# Autonomous Tasks
autonomous:
  enabled: true
  poll_interval: 30          # Seconds between task checks
  quality_gates: true        # Run tests after each task
  max_parallel: 3            # Concurrent task workers (1-10)
  verification: true         # Independent code review per task

# Optional: sidechannel AI assistant (supports OpenAI and Grok)
sidechannel_assistant:
  enabled: false
  # provider: "openai"       # or "grok" — auto-detected from API keys if omitted
  # model: "gpt-4o"          # Default: gpt-4o (OpenAI) or grok-3-latest (Grok)
  # max_tokens: 1024
```

### Environment Variables (.env)

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional (for sidechannel AI assistant) — set one or both
OPENAI_API_KEY=sk-...
GROK_API_KEY=xai-...
```

### Adding Projects

Edit `config/projects.yaml`:

```yaml
projects:
  myapp:
    path: /home/user/projects/myapp
    description: "My web application"

  backend:
    path: /home/user/projects/backend-api
    description: "REST API service"
```

## Running

### Manual Start

```bash
cd ~/sidechannel
./run.sh
```

### Systemd Service

```bash
# Start
systemctl --user start sidechannel

# Enable on boot
systemctl --user enable sidechannel
loginctl enable-linger $USER

# View logs
journalctl --user -u sidechannel -f
```

---

## Plugin Framework

sidechannel supports custom plugins so you can add your own functionality without touching the core codebase. Plugins are auto-discovered at startup, get their own config section, and integrate seamlessly with the bot's command system, message routing, and help output.

### How Plugins Work

```
plugins/
├── my_plugin/
│   ├── __init__.py        # Required (can be empty)
│   ├── plugin.py          # Required — contains your SidechannelPlugin subclass
│   └── README.md          # Optional — plugin documentation
├── daily_verse/           # Example: scheduled Bible verse delivery
│   ├── __init__.py
│   └── plugin.py
└── bluos_music/           # Example: multi-room speaker control
    ├── __init__.py
    ├── plugin.py
    ├── bluos_controller.py
    ├── nlp_parser.py
    └── models.py
```

At startup, the bot scans `plugins/` for directories containing `plugin.py`, finds your `SidechannelPlugin` subclass, and registers its commands, message matchers, and help sections. Broken or disabled plugins are logged and skipped — they never crash the bot.

### Quick Start: Your First Plugin

**1. Create the plugin directory and files:**

```bash
mkdir -p plugins/hello_world
touch plugins/hello_world/__init__.py
```

**2. Write `plugins/hello_world/plugin.py`:**

```python
from sidechannel.plugin_base import SidechannelPlugin, HelpSection


class HelloWorldPlugin(SidechannelPlugin):
    name = "hello_world"
    description = "A simple example plugin"
    version = "1.0.0"

    def commands(self):
        return {"hello": self._handle_hello}

    async def _handle_hello(self, sender: str, args: str) -> str:
        greeting = self.ctx.get_config("greeting", "Hello")
        return f"{greeting}, {args or 'world'}!"

    def help_sections(self):
        return [HelpSection(
            title="Hello World",
            commands={"hello": "Say hello (usage: /hello [name])"},
        )]
```

**3. Add config (optional) to `config/settings.yaml`:**

```yaml
plugins:
  hello_world:
    enabled: true
    greeting: "Hey there"
```

**4. Restart the bot.** Your plugin is live — send `/hello Dave` to test it.

### Plugin API Reference

Every plugin inherits from `SidechannelPlugin` and receives a `PluginContext` object (`self.ctx`) for interacting with the bot.

#### Class Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Plugin identifier (must be unique) |
| `description` | `str` | One-line description shown in logs |
| `version` | `str` | Semantic version string |

#### Methods to Override

| Method | Returns | Description |
|--------|---------|-------------|
| `commands()` | `dict[str, handler]` | Register `/slash` commands. Handler signature: `async (sender: str, args: str) -> str` |
| `message_matchers()` | `list[MessageMatcher]` | Register message interceptors checked before default routing |
| `on_start()` | `None` | Called after bot connects — start schedulers, open connections |
| `on_stop()` | `None` | Called during shutdown — cancel tasks, close sessions |
| `help_sections()` | `list[HelpSection]` | Add entries to the `/help` command output |

#### PluginContext (`self.ctx`)

| Method / Attribute | Description |
|--------------------|-------------|
| `await ctx.send_message(recipient, text)` | Send a Signal message to any phone number |
| `ctx.get_config(key, default=None)` | Read `plugins.<name>.<key>` from settings.yaml |
| `ctx.get_env(key)` | Read an environment variable |
| `ctx.logger` | Structured logger (structlog) tagged with your plugin name |
| `ctx.allowed_numbers` | List of authorized phone numbers |
| `ctx.data_dir` | Path to a persistent data directory for your plugin |
| `ctx.enabled` | Whether the plugin is enabled in config (default: `True`) |
| `ctx.plugin_name` | Your plugin's name string |

### Example: Command Plugin

A plugin that adds a `/weather` command:

```python
import aiohttp
from sidechannel.plugin_base import SidechannelPlugin, HelpSection


class WeatherPlugin(SidechannelPlugin):
    name = "weather"
    description = "Check the weather"
    version = "1.0.0"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._session = None

    def commands(self):
        return {"weather": self._handle_weather}

    async def _handle_weather(self, sender: str, args: str) -> str:
        city = args.strip() or self.ctx.get_config("default_city", "New York")
        api_key = self.ctx.get_env("WEATHER_API_KEY")
        if not api_key:
            return "Weather plugin requires WEATHER_API_KEY in .env"

        if not self._session:
            self._session = aiohttp.ClientSession()

        url = f"https://api.weatherapi.com/v1/current.json?key={api_key}&q={city}"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                return f"Could not fetch weather for {city}"
            data = await resp.json()

        current = data["current"]
        return f"Weather in {city}: {current['temp_f']}°F, {current['condition']['text']}"

    async def on_stop(self):
        if self._session:
            await self._session.close()

    def help_sections(self):
        return [HelpSection(
            title="Weather",
            commands={"weather": "Check weather (usage: /weather [city])"},
        )]
```

Config:
```yaml
plugins:
  weather:
    enabled: true
    default_city: "Columbus, OH"
```

### Example: Message Matcher Plugin

A plugin that intercepts messages matching a pattern (no `/command` needed):

```python
import re
from sidechannel.plugin_base import SidechannelPlugin, MessageMatcher


class ReminderPlugin(SidechannelPlugin):
    name = "reminder"
    description = "Set reminders with natural language"
    version = "1.0.0"

    _pattern = re.compile(r"remind me .+ in \d+ (minutes?|hours?)", re.IGNORECASE)

    def message_matchers(self):
        return [MessageMatcher(
            priority=20,          # Lower number = checked first
            match_fn=self._is_reminder,
            handle_fn=self._handle_reminder,
            description="Natural language reminders",
        )]

    def _is_reminder(self, message: str) -> bool:
        return bool(self._pattern.search(message))

    async def _handle_reminder(self, sender: str, message: str) -> str:
        # Parse and schedule the reminder...
        return f"Reminder set! I'll message you when it's time."
```

Message matchers are sorted by priority (lower = first). When a matcher's `match_fn` returns `True`, its `handle_fn` is called and no further matchers or default routing are checked.

### Example: Scheduled / Lifecycle Plugin

A plugin that runs a background task on a schedule:

```python
import asyncio
from sidechannel.plugin_base import SidechannelPlugin


class HealthCheckPlugin(SidechannelPlugin):
    name = "health_check"
    description = "Periodic health monitoring"
    version = "1.0.0"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._task = None
        self._interval = ctx.get_config("interval_seconds", 3600)

    async def on_start(self):
        """Start the health check loop when the bot connects."""
        self._task = asyncio.create_task(self._run_loop())
        self.ctx.logger.info("health_check_started", interval=self._interval)

    async def on_stop(self):
        """Cancel the loop on shutdown."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        while True:
            try:
                await asyncio.sleep(self._interval)
                # Perform health check...
                status = "all systems operational"
                admin = self.ctx.get_config("admin_number")
                if admin:
                    await self.ctx.send_message(admin, f"Health: {status}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.ctx.logger.error("health_check_error", error=str(e))
                await asyncio.sleep(60)  # Brief pause before retry
```

### Plugin Configuration

Every plugin gets its own section in `config/settings.yaml` under `plugins.<name>`:

```yaml
plugins:
  # Disable a plugin without removing it
  my_plugin:
    enabled: false

  # Plugin with custom config
  weather:
    enabled: true
    default_city: "Columbus, OH"
    units: "imperial"

  # Plugin that uses scheduled delivery
  daily_verse:
    enabled: true
    hour: 8
    minute: 30
    recipients: ["+15551234567"]
```

Access config values with `self.ctx.get_config("key", default)`. If no config section exists for your plugin, all `get_config` calls return the default value. Plugins default to `enabled: true` unless explicitly set to `false`.

### Environment Variables

For secrets (API keys, tokens), use environment variables via `self.ctx.get_env("KEY")` rather than storing them in settings.yaml. Add them to `config/.env`:

```bash
# Plugin-specific API keys
WEATHER_API_KEY=abc123
MY_PLUGIN_SECRET=xyz789
```

### Message Routing Order

When a message arrives, sidechannel processes it in this order:

1. **`/command`** — Core commands (help, projects, ask, do, etc.) checked first
2. **Plugin commands** — `/commands` registered by plugins, in load order
3. **Plugin message matchers** — Sorted by priority (lower number = checked first)
4. **sidechannel assistant** — Messages starting with "sidechannel:" prefix
5. **Default** — Treated as `/do` if a project is selected

Core commands always take precedence. If two plugins register the same `/command` name, the first-loaded plugin wins and a warning is logged.

### Included Example Plugins

#### Daily Verse (`plugins/daily_verse/`)

Delivers a Bible verse to configured recipients on a schedule. Uses OpenAI or Grok for verse generation.

```yaml
plugins:
  daily_verse:
    enabled: true
    hour: 8           # 24h format
    minute: 0
    recipients:       # Defaults to allowed_numbers if omitted
      - "+15551234567"
```

Requires `OPENAI_API_KEY` or `GROK_API_KEY` in your `.env`. Also registers `/verse` for on-demand requests.

#### BluOS Music (`plugins/bluos_music/`)

Controls BluOS-compatible speakers (Bluesound, NAD) with natural language. Supports multi-room grouping, volume control, and playback management.

```yaml
plugins:
  bluos_music:
    enabled: true
    players:
      main_floor: { name: "Main Floor", ip: "10.0.0.1" }
      bedroom: { name: "Bedroom", ip: "10.0.0.2" }
    groups:
      inside: [main_floor, bedroom]
```

Responds to natural language like "play jazz in the bedroom" and registers `/music` for direct control.

### Deployment: Syncing Updates

sidechannel is the authoritative codebase. Use `sync.sh` to push updates to your signal bot deployment:

```bash
# Sync to default target (~/signal)
./sync.sh

# Sync to a custom directory
./sync.sh /path/to/my/signal-bot
```

The sync copies core code and example plugins but **preserves your config**, secrets, databases, and logs. Your custom plugins in the target's `plugins/` directory are also preserved.

## How the Memory System Works

sidechannel uses a multi-layered memory architecture built on SQLite with sqlite-vec for vector similarity search:

1. **Automatic conversation storage** - Every message you send and every response is automatically stored with timestamps, project context, and command type
2. **Session grouping** - Messages within a configurable timeout window (default: 30 min) are grouped into sessions for coherent context retrieval
3. **Vector embeddings** - Stored messages are embedded using sentence-transformers (all-MiniLM-L6-v2) for semantic similarity search
4. **Context injection** - When you run `/ask` or `/do`, sidechannel automatically retrieves the most relevant past conversations and memories, injecting them into Claude's context window
5. **Explicit memories** - `/remember` facts are stored permanently and weighted higher in retrieval
6. **Project isolation** - Memories are scoped to projects by default, with `/global` for cross-project knowledge
7. **Token budgeting** - Retrieved context is capped at `max_context_tokens` (default: 1500) to leave room for Claude's actual work

This means Claude gets progressively smarter about your projects over time - it knows your conventions, past decisions, and what's been tried before.

## How Autonomous Development Works

The autonomous system is designed for tasks too large for a single Claude invocation:

1. **PRD Creation** (`/complex`) - Claude analyzes your request and generates a structured PRD with stories and atomic tasks
2. **Dependency Resolution** - Tasks are analyzed for dependencies; independent tasks can run in parallel
3. **Parallel Dispatch** - Up to `max_parallel` workers execute tasks concurrently, each with its own Claude CLI session
4. **Adaptive Effort** - Task type (feature, bugfix, refactor, test) is auto-detected and mapped to an effort level controlling Claude's thoroughness
5. **Independent Verification** - A *separate* Claude context reviews each task's git diff. Security concerns or logic errors cause the task to fail (fail-closed). Only infrastructure failures (timeout, crash) pass through (fail-open)
6. **Auto-Fix Loop** - If verification fails, a fresh Claude context gets the failure reason and attempts to fix the issue (up to 2 attempts)
7. **Quality Gates** - Test baselines are captured *before* each task. After completion, tests run again and only *new* failures (regressions) block the task. Pre-existing failures don't
8. **Git Safety** - Automatic git checkpoints before execution and atomic commits after, protected by asyncio locks for concurrent access
9. **Progress Updates** - Signal notifications as tasks complete, fail, or need attention

## Security Considerations

- Only phone numbers in `allowed_numbers` can interact with the bot
- **Rate limiting** - Per-user configurable request throttling prevents abuse
- **Path validation hardening** - Directory traversal protection with strict prefix matching
- **Phone number masking in logs** - Sensitive identifiers are redacted in all log output
- **Independent code verification** - Every autonomous task is reviewed by a separate Claude context with a fail-closed security model
- API keys are stored in `.env` (not committed to git)
- Signal messages are end-to-end encrypted
- No message content is logged by default
- Claude CLI runs with your local user permissions

## Troubleshooting

### Signal not receiving messages

1. Check Signal CLI is running: `docker ps | grep signal`
2. Verify device is linked: `curl http://127.0.0.1:8080/v1/accounts`
3. Check logs: `docker logs signal-api`

### Claude commands failing

1. Verify Claude CLI works: `claude --version`
2. Check API key: `echo $ANTHROPIC_API_KEY`
3. Test manually: `claude "hello"`

### Memory not persisting

1. Check data directory exists: `ls ~/sidechannel/data`
2. Verify SQLite database: `ls ~/sidechannel/data/*.db`

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Anthropic](https://anthropic.com) for Claude
- [Signal](https://signal.org) for secure messaging
- [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) for the Signal API wrapper
