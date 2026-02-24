# Changelog

All notable changes to sidechannel will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-02-24

### Added
- **Plugin framework** — extend sidechannel with custom plugins in `plugins/` directory
- **Plugin base class** (`SidechannelPlugin`) with commands, message matchers, lifecycle hooks, and help sections
- **Plugin auto-discovery** — plugins loaded automatically from `plugins/<name>/plugin.py`
- **PluginContext API** — safe interface for plugins (send_message, config, env, logger)
- **Priority message routing** — plugins can intercept messages before default routing
- **Daily verse plugin** — scheduled Bible verse delivery (extracted from signal bot)
- **BluOS music plugin** — multi-room speaker control (extracted from signal bot)
- **Exception hierarchy** (`exceptions.py`) — structured error classification with retry support
- **Attachment handling** (`attachments.py`) — image download and processing with size limits
- **PRD builder** (`prd_builder.py`) — robust JSON parsing for autonomous PRDs
- **Skill registry** (`skill_registry.py`) — Claude plugin discovery and matching

### Security
- **XML entity attack prevention** — BluOS controller rejects DTD/ENTITY declarations in XML responses
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
