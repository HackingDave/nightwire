# Changelog

All notable changes to nightwire (formerly sidechannel) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.4.0] - 2026-02-27

### Fixed
- Image attachment detection — attachments sent via Signal are now downloaded, saved, and passed to Claude for vision analysis
- Attachment-only messages (no text) are now processed instead of silently dropped

### Added
- `attachments_dir` config option to customize where image attachments are saved (default: `data/attachments/`)
- 18 new tests covering attachment download, save, and message pipeline integration

## [2.3.1] - 2026-02-27

### Added
- `CONTRIBUTORS.md` with credits for all community contributors from closed PRs and issues
- Contributors section in README linking to CONTRIBUTORS.md

## [2.3.0] - 2026-02-26

### Added
- Docker sandbox image (`Dockerfile.sandbox`) with Python 3.11 + Node.js 20 + Claude CLI for containerized execution
- Docker availability validation — fail-closed with clear error when Docker is unavailable
- Installer option to build sandbox image and enable sandbox config automatically
- `tmpfs_size` sandbox configuration option (was hardcoded, now user-configurable)

### Changed
- Default sandbox image from `python:3.11-slim` to `nightwire-sandbox:latest`
- Sandbox no longer passes host `PATH` to container (container uses its own)

### Security
- Container hardening: `--cap-drop ALL`, `--security-opt no-new-privileges`, `--pids-limit 256`, `--user 1000:1000`
- Docker socket permission errors now detected with actionable guidance

## [2.2.0] - 2026-02-25

### Changed
- Nightwire assistant now supports any OpenAI-compatible API provider via `api_url`, `api_key_env`, and `model` settings
- Removed hardcoded API host allowlist — any HTTPS endpoint is accepted
- OpenAI and Grok remain as built-in convenience presets

## [2.1.1] - 2026-02-25

### Fixed
- Signal UUID sender authorization — modern Signal accounts that use UUIDs instead of phone numbers are now correctly authorized (#7)
- `allowed_numbers` config now accepts both E.164 phone numbers and Signal UUIDs
- Config validation no longer warns on UUID entries in `allowed_numbers`
- Systemd service now writes stdout/stderr to `$LOGS_DIR/nightwire.log` on Linux (#6)

## [2.1.0] - 2026-02-25

### Added
- Rate limit cooldown system — detects Claude subscription rate limits, pauses all operations, notifies users via Signal, and auto-resumes after configurable cooldown period
- `/cooldown` command with `status`, `clear`, and `test` subcommands
- `RATE_LIMITED` error category in Claude runner for subscription-level rate limit detection
- `rate_limit_cooldown` configuration section in settings.yaml (enabled, cooldown_minutes, consecutive_threshold, failure_window_seconds)
- Cooldown status displayed in `/status` output when active
- Interactive `/ask`, `/do`, `/complex` commands and plain-text messages blocked with helpful message during cooldown

## [2.0.0] - 2026-02-25

### Changed
- **Project renamed from sidechannel to nightwire** — package, commands, config keys, service names, and all documentation updated
- Console entry point: `sidechannel` → `nightwire`
- Bot command: `/sidechannel` → `/nightwire`
- Config key: `sidechannel_assistant` → `nightwire_assistant` (old key still works as fallback)
- Systemd service: `sidechannel.service` → `nightwire.service`
- macOS LaunchAgent: `com.sidechannel.bot` → `com.nightwire.bot`
- Plugin base class: `SidechannelPlugin` → `NightwirePlugin` (old name still works as alias)
- Bot still accepts both "nightwire:" and "sidechannel:" message triggers during transition

## [1.6.0] - 2026-02-24

### Added
- Auto-update feature: opt-in periodic update checking with admin approval via Signal
- `/update` command for admin to apply pending updates
- `auto_update` configuration section in settings.yaml (enabled, check_interval, branch)
- Automatic rollback on failed updates (git reset to previous HEAD)
- Exit code 75 restart mechanism for systemd/launchd service restart after update

### Security
- Branch name validation prevents git flag injection via config
- asyncio.Lock serializes update check and apply to prevent race conditions
- Rollback on all failure paths (git pull, pip install, timeout)

### Fixed
- Replace deprecated asyncio.get_event_loop() with asyncio.create_task for Python 3.12+ compatibility
- Catch subprocess.TimeoutExpired in apply_update to prevent silent failures
- Reset pending state on update failure so next check cycle re-notifies admin

## [1.5.3] - 2026-02-24

### Fixed
- Task state is now per-sender instead of global — users can work on multiple projects concurrently without blocking each other

## [1.5.2] - 2026-02-24

### Added
- `@require_valid_project_path` decorator for consistent path validation on functions that accept a path argument
- `tests/test_security.py` with tests for the new decorator
- Plugin loader allowlist (`plugin_allowlist` config option)
- Security scan in quality gates (detects os.system, shell=True, eval, hardcoded keys, IP exfil)
- Comprehensive test suite skeleton for security functions (path validation, sanitization, rate limiting)
- Static analysis regression test (no shell=True or os.system in codebase)
- Resource guard: checks memory/CPU before spawning parallel workers
- `make security` target (bandit + safety), `make typecheck` target (mypy), `make check` target (lint + typecheck + test + security)
- Optional Docker sandbox for Claude task execution (`sandbox` config)
- Operational security guide in SECURITY.md, hardening checklist in README.md

### Changed
- psutil added as dependency for resource monitoring
- Dev dependencies expanded: mypy, bandit, safety

### Security
- Path validation enforced in `ClaudeRunner.set_project()`
- Verification agent explicitly checks for backdoors, cryptocurrency miners, and data exfiltration
- Rate limiter dict operations protected by asyncio.Lock

## [1.5.1] - 2026-02-24

### Changed
- Capitalized "Sidechannel" in README documentation sections for consistent branding (commands and code references unchanged)

## [1.5.0] - 2026-02-24

### Added
- `/sidechannel <question>` slash command for the AI assistant (previously only natural language prefix detection)
- Per-phone-number project scoping — each user has their own active project selection
- Optional `allowed_numbers` field in `projects.yaml` to restrict project access to specific phone numbers
- `/help` now shows AI Assistant section with `/sidechannel` command when assistant is enabled
- Runtime dependencies declared in `pyproject.toml` for proper `pip install` support
- Installer flags documented in README (`--skip-signal`, `--skip-systemd`, `--restart`, `--uninstall`)
- `SIGNAL_API_URL` environment variable documented in README

### Fixed
- **Race condition**: `ClaudeRunner` shared project state could cause tasks to run in wrong project directory when multiple users active — now passes `project_path` directly to `run_claude()`
- **PRD completion broken**: `failed_stories` count was never populated from database, preventing PRDs from completing when stories failed
- **`failed_tasks` missing from `list_stories`**: PRD completion summary always reported 0 failed tasks
- **Memory timezone mismatch**: `datetime.now()` (local time) was compared against SQLite `CURRENT_TIMESTAMP` (UTC), breaking `/forget today` and session detection in non-UTC timezones
- **Process leak after timeout**: `_running_process` not cleared to `None` after Claude CLI timeout, causing stale reference on subsequent cancel
- **Verifier blind after commit**: `_get_git_diff` returned empty when executor had already committed changes — now falls back to `HEAD~1..HEAD`
- **Division by zero**: `_get_relevant_learnings_sync` crashed on empty query strings
- **Config crash on invalid types**: `int()` conversion for `max_parallel` and `max_tokens` settings now handles non-numeric values gracefully
- **Inconsistent case sensitivity**: `get_project_path` now uses case-insensitive matching like `remove_project` and `select_project`
- Unauthorized message logging now masks phone numbers (was logging full number)
- `pyproject.toml` build-backend fixed from internal API to standard `setuptools.build_meta`
- Python version requirement aligned across installer (3.9+), pyproject.toml, and tooling
- Version numbers aligned to 1.5.0 across `__init__.py`, `main.py`, `install.sh`, and `pyproject.toml`
- Plugin error messages no longer expose internal exception details to users (BluOS music, daily verse)
- BluOS volume XML parsing handles non-numeric values instead of crashing
- `initialize_database` now closes previous connection before replacing global instance
- `similarity_score` model constraint relaxed from `[0, 1]` to `[-1, 1]` to match cosine similarity range
- Hardcoded `/home/hackingdave/.local/bin/claude` path removed from `haiku_summarizer` — uses auto-detection
- Deprecated `asyncio.get_event_loop()` replaced with `asyncio.get_running_loop()`
- Sidechannel assistant errors no longer silently swallowed — returns user-friendly error messages instead of silence
- Empty sidechannel assistant responses now return a clear message instead of blank reply
- `allowed_numbers: []` (empty list) now correctly blocks all access instead of granting public access
- Background tasks use project context captured at creation time, preventing stale lookups if user switches projects mid-task

### Changed
- Rate limit config example clarified — currently hardcoded, configurable rate limiting planned for future release
- SECURITY.md version table updated
- CONTRIBUTING.md fork URL uses `YOUR_USERNAME` placeholder instead of upstream URL
- README config section expanded with undocumented options (project paths, effort levels, embedding model)
- `/forget` command description corrected in README to show actual scopes (`all|preferences|today`)

## [1.4.0] - 2026-02-24

### Removed
- **Docker install mode** — the bot no longer runs in a container; removed `Dockerfile`, `--docker`/`--local` flags, and interactive mode selection menu
- `sidechannel` service from `docker-compose.yml` — compose now only manages the Signal bridge

### Added
- `./install.sh --restart` flag to restart the sidechannel service (systemd or launchd)
- Projects directory prompt during install — auto-registers all subdirectories as projects
- `/remove <project>` command to unregister a project from the bot

### Changed
- Python requirement lowered from 3.10+ to 3.9+ (compatible with macOS default Python)
- Installer is now a single code path (Python venv + Signal bridge in Docker)
- Installer runs from the repo directory instead of copying to `~/sidechannel` — `git pull` updates code immediately
- Clearer AI assistant prompt explains it's optional and not needed for core functionality
- `docker-compose.yml` is a signal-bridge-only compose file

### Fixed
- Signal bridge restarted in `json-rpc` mode after pairing (was left in `native` mode, breaking WebSocket message receiving)
- Bot startup now retries Signal API connection (12 attempts over ~90s) instead of failing immediately when signal-api is still starting
- Fire-and-forget memory tasks now log exceptions instead of silently swallowing them
- API key sed injection in installer — keys with special characters no longer break setup
- Incorrect `projects.yaml` format in README (was dict-based, now matches actual list-based format)
- Stale references to `~/sidechannel` paths and Python 3.10+ in documentation
- Claude CLI prompt passed via stdin instead of `-p` flag — fixes crash when memory context starts with dashes
- Systemd service file: `EnvironmentFile` missing `=` operator (service would fail to load on Linux)
- Systemd/run.sh: use `python3` instead of `python` (avoids Python 2 on older Linux systems)
- IP detection fallback: replaced macOS-only `ipconfig getifaddr` with Linux-compatible `ip route`
- Generated `run.sh` now has `set -e`, guards `.env` source, uses `exec`
- Added `curl` prerequisite check to installer
- Docker container restart race: use `docker rm -f` instead of stop+rm to prevent port conflicts from restart policy
- Claude config format: README and `settings.yaml.example` showed nested `claude:` block but code reads flat keys (`claude_timeout`, `claude_max_turns`)
- `.env.example` wrongly labeled `ANTHROPIC_API_KEY` as "Required" (Claude CLI handles its own auth)

### Security
- Autonomous task failure notifications no longer leak exception types and internal error details to users

## [1.3.0] - 2026-02-24

### Changed
- **Installer rewrite** — local mode Signal setup is now fully automatic (no confusing "protocol bridge" choices)
- **Installer auto-detects Docker** and installs qrencode automatically for terminal QR codes
- **Installer starts service automatically** — asks once, installs + starts, no "next steps" homework
- **Installer summary simplified** — shows "sidechannel is ready!" with one test command instead of multi-step instructions
- **Docker mode Signal pairing** — cleaner QR code flow with proper verification and retry

### Added
- **Docker mode projects mount** — host projects directory mounted into container so Claude can access your code
- **Claude CLI in Docker image** — Dockerfile now installs Claude CLI so /ask, /do, /complex actually work
- **Projects directory prompt** — Docker installer asks for your projects path and configures the mount
- **Claude auth mount** — `~/.claude` mounted into container so Claude CLI auth persists
- **macOS launchd support** — installer creates `com.sidechannel.bot.plist` for auto-start on login
- **Signal pairing retry** — installer offers a second verification attempt if first scan isn't detected
- **Auto Docker install** — on Linux (apt/dnf), installer offers to install Docker if missing
- **Remote QR code access** — both Docker and local modes ask if you need to scan from another device

### Fixed
- Docker mode can now access host project files (previously only saw files inside the container)
- Raw ANSI escape codes (`\033[0;36m`) no longer appear in installer output
- Installer no longer offers broken "Native signal-cli" option that can't provide the required REST API
- Uninstaller now removes macOS launchd plist in addition to Linux systemd service
- Buffered keystrokes during long installs no longer skip interactive prompts
- Signal bridge QR code endpoint polled until actually ready (fixes "no data to encode" error)
- Updated signal-cli-rest-api from pinned v0.80 to `latest` tag (v0.80 incompatible with current Signal protocol)
- QR code readiness detection uses GET content-type instead of HEAD (API returns 404 for HEAD)
- macOS-specific Docker start instructions (`open -a Docker` instead of `systemctl`)

## [1.2.0] - 2026-02-24

### Added
- **Docker install mode** — `./install.sh --docker` runs everything in containers via Docker Compose
- **Dockerfile** — containerized sidechannel bot with Python 3.12-slim base
- **Install mode menu** — interactive Docker/Local selection when no flag is passed
- **Dependency auto-check** — local install skips `pip install` if packages already present
- **Plugin framework** — extend sidechannel with custom plugins in `plugins/` directory
- **Plugin base class** (`SidechannelPlugin`) with commands, message matchers, lifecycle hooks, and help sections
- **Plugin auto-discovery** — plugins loaded automatically from `plugins/<name>/plugin.py`
- **PluginContext API** — safe interface for plugins (send_message, config, env, logger)
- **Priority message routing** — plugins can intercept messages before default routing
- **Exception hierarchy** (`exceptions.py`) — structured error classification with retry support
- **Attachment handling** (`attachments.py`) — image download and processing with size limits
- **PRD builder** (`prd_builder.py`) — robust JSON parsing for autonomous PRDs
- **Skill registry** (`skill_registry.py`) — Claude plugin discovery and matching

### Security
- **SecurityError hardened** — category is always PERMANENT and cannot be overridden
- **Attachment size limit** — downloads capped at 50MB to prevent memory exhaustion

### Changed
- Help text now shows all commands including /add, /new, /status, /summary, /forget, /preferences
- Message prefix changed from "sidechannel:" to "[sidechannel]" for cleaner formatting
- Cleaner status output with compact elapsed time and autonomous loop info
- Reduced verbose step notifications during PRD creation
- Consolidated duplicate task-busy checks into `_check_task_busy()` helper
- Bot refactored to use `prd_builder` module instead of inline JSON parsing methods
- Plugin loader uses insertion-order class discovery (Python 3.7+ dict ordering)

### Fixed
- **macOS sed compatibility** — `sed -i` calls now use `sed_inplace()` helper that detects GNU vs BSD sed

## [1.1.0] - 2026-02-23

### Added
- **OpenAI provider support** for sidechannel AI assistant — users can now choose between OpenAI and Grok as the backend provider
- **Provider auto-detection** — if only `OPENAI_API_KEY` is set, sidechannel uses OpenAI automatically; if only `GROK_API_KEY`, it uses Grok
- **Shared HTTP session** for sidechannel runner — reuses connections instead of creating per-request

### Fixed
- `aiohttp.ClientTimeout` exception bug — now correctly catches `asyncio.TimeoutError`

### Changed
- Renamed "nova" assistant to "sidechannel" throughout the codebase
- `sidechannel_assistant:` config section replaces legacy `nova:` / `grok:` sections (backward compatible)
- `sidechannel_runner.py` replaces `grok_runner.py` / `nova_runner.py` with configurable provider settings

## [1.0.0] - 2026-02-23

### Added
- Claude CLI integration for code analysis, generation, and project work
- Signal messaging integration via signal-cli-rest-api (Docker)
- Episodic memory system with vector embeddings and semantic search
- Autonomous task execution with PRD/Story/Task breakdown
- **Parallel task execution** with configurable worker count (1-10 concurrent)
- **Independent verification system** - separate Claude context reviews each task's output
- **Error classification and retry** - transient errors retried with exponential backoff
- **Baseline test snapshots** - pre-task test state captured for regression detection
- **Stale task recovery** - stuck tasks automatically re-queued on loop restart
- **Circular dependency detection** - DFS-based cycle detection prevents deadlocks
- **Git safety** - checkpoint/commit locking prevents concurrent git corruption
- **Auto-fix loop** - verification failures trigger up to 2 fix attempts
- **Task type detection** - automatic classification (feature, bugfix, refactor, test, docs, config)
- **Adaptive effort levels** - task complexity mapped to execution effort
- Project management with multi-project support
- sidechannel AI assistant (optional OpenAI/Grok integration, disabled by default)
- Interactive installer with Signal QR code device linking
- Systemd service support
- Comprehensive test suite

### Security
- Phone number allowlist for access control
- **Rate limiting** - per-user request throttling with configurable window
- **Path validation hardening** - prefix attack prevention on project paths
- **Phone number masking** - numbers partially redacted in all log output
- **Fail-closed verification** - security concerns and logic errors block task completion
- Environment-based secret management (.env not committed)
- No message content logging by default
- End-to-end encrypted Signal transport

### Fixed
- Path validation bypass via directory prefix attack
- Zombie subprocess on timeout (now properly killed)
- Init race condition in memory manager (double-checked locking)
- Session ID collision risk (full UUID instead of truncated prefix)
