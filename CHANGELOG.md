# Changelog

All notable changes to sidechannel will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] - 2026-02-24

### Added
- `/sidechannel <question>` slash command for the AI assistant (previously only natural language prefix detection)
- Per-phone-number project scoping — each user has their own active project selection
- Optional `allowed_numbers` field in `projects.yaml` to restrict project access to specific phone numbers
- `/help` now shows AI Assistant section with `/sidechannel` command when assistant is enabled

### Fixed
- Sidechannel assistant errors no longer silently swallowed — returns user-friendly error messages instead of silence
- Empty sidechannel assistant responses now return a clear message instead of blank reply
- `allowed_numbers: []` (empty list) now correctly blocks all access instead of granting public access
- Background tasks use project context captured at creation time, preventing stale lookups if user switches projects mid-task

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
