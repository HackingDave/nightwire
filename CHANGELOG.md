# Changelog

All notable changes to nightwire (formerly sidechannel) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.4] - 2026-03-06

### Fixed — Production Deployment Issues (v3.0.3 Observations)

- `autonomous/database.py`: Fixed `_get_task_stats_sync()` second SQL query (completed_today/failed_today counts) not filtering by `project_name` — `/tasks` showed 0 completed for the active project when tasks existed across multiple projects.
- `autonomous/commands.py`: `/autonomous start` now resumes a paused loop instead of silently doing nothing — checks `get_loop_status()` and calls `resume_loop()` when paused, returns "already running" when active.
- `autonomous/loop.py`: Verification failure notifications now include issue details (security concerns, logic errors, top issues) instead of just a count — module-level `_format_verification_summary()` function formats top 3 items, used in both retry and max-retries notification paths.
- `autonomous/verifier.py`: Fixed `_get_git_diff()` returning empty diffs for all verified tasks — executor now captures pre-task HEAD hash via `_get_head_hash()` and passes it as `base_ref` to the verifier, replacing the fragile `HEAD~1` fallback. Added `process.returncode` checks on both subprocess calls.
- `commands/base.py`: Added `register_external_help()` method to `HandlerRegistry` — enables HelpMetadata registration for externally registered commands.
- `autonomous/commands.py`, `memory/commands.py`: Added `get_help_metadata()` functions providing detailed `/help <command>` output for all 13 external commands (7 autonomous + 6 memory) — previously returned generic "Use /help for the full command list" fallback.

### Added

- `autonomous/models.py`: `depends_on_indices` field on `TaskBreakdown` schema — Claude now declares task dependencies during PRD creation (0-based indices within the same story).
- `task_manager.py`: Dependency index-to-ID mapping in both `_create_prd_from_breakdown()` and `_create_prd_from_dict()` — validates indices (skips self-references, clamps range, logs warnings), creates `depends_on` entries via new `update_task_depends_on()` DB method.
- `autonomous/database.py`: `update_task_depends_on()` async method with thread-safe `_lock` for setting task dependency lists.
- Structured prompt rule 9: Instructs Claude to populate `depends_on_indices` for tasks with dependencies during PRD generation.

## [3.0.3] - 2026-03-06

### Fixed — Production Deployment Issues (v3.0.2 Observations)

- `bot.py`: WebSocket debug logging now filters to actionable envelope types (`dataMessage`, `syncMessage`) — receipt, typing, and other high-frequency frames no longer flood debug logs.
- `autonomous/loop.py`: Removed duplicate "Starting task" notification from `_process_task()` — was being merged with executor's first progress callback within the debounce window, causing redundant text in Signal messages.
- `autonomous/loop.py`: Fixed debounce constructor default from 2.0s to 5.0s to match `config.py` runtime default. Also fixed in `autonomous/manager.py`.
- `autonomous/executor.py`: Planning tasks (choose, evaluate, research, etc.) no longer fail with "files_changed=0" — these tasks legitimately produce no files. Claude output is preserved and learning extraction still runs.
- `bot.py`: Fixed stale docstring referencing 5000-char message split limit (actual limit is 3000 since v3.0.2).
- `settings.yaml.example`: Added all missing configurable options: `instance_name`, `claude_max_budget_usd`, Signal UX settings, usage budget alerts, autonomous monitoring settings (`stuck_task_timeout_minutes`, `circuit_breaker_threshold`, `circuit_breaker_reset_minutes`).

### Added

- `autonomous/models.py`: `TaskType.PLANNING` enum value — auto-detected from task titles containing "choose", "plan", "evaluate", "research", "analyze", "strategy".
- `config.py`: `"planning": "medium"` default effort level for planning tasks.
- `settings.yaml.example`: `planning: "medium"` in effort_levels example.

## [3.0.2] - 2026-03-06

### Fixed — Production Deployment Issues (v3.0.1 Observations)

- `autonomous/executor.py`: Fixed `_get_files_changed()` not detecting newly created (untracked) files — `git diff --name-only HEAD` only sees tracked file changes. Added `git ls-files --others --exclude-standard` for new files and `git diff --name-only --cached` for staged changes. This was the root cause of `files_changed=0` on all task executions.
- `autonomous/executor.py`: Short-circuit tasks that produce zero file changes — immediately fail with clear error message instead of running expensive verification/auto-fix loops on empty workspaces.
- `autonomous/verifier.py`: Added `invalidate_cache(task_id)` method and task-to-hash tracking — auto-fix loop now clears stale verification cache before re-verification, preventing infinite `verification_cache_hit passed=False` loops.
- `commands/core.py`: `/cancel all` now cancels active autonomous workers in addition to pausing the loop — previously only paused dispatch (existing workers continued running indefinitely).
- `autonomous/loop.py`: Added `cancel_all_workers()` method that cancels all active worker tasks and marks them CANCELLED in the database.
- `install.sh`: Fixed port 9090 "Address already in use" error — set `allow_reuse_address = True` before bind (was setting `SO_REUSEADDR` after bind), added signal handler cleanup for SIGALRM/SIGTERM, and proper `server_close()` in finally block.
- `bot.py`: Reduced message split limit from 5000 to 3000 characters — Signal clients may truncate at various thresholds below 5000.
- `autonomous/commands.py`: Increased `/tasks` title display from 40 to 60 characters — task names were being cut off in Signal output.
- `config.py`: Increased notification debounce default from 2.0s to 5.0s — reduces notification spam during parallel autonomous execution.

### Added

- `config.py`: `claude_max_turns_planning` and `claude_max_turns_execution` config properties — allows separate turn limits for planning phase (PRD creation, verification) vs execution phase (task implementation, auto-fix). Both default to `claude_max_turns` if not set separately.
- `claude_runner.py`: `max_turns_override` parameter threaded through `run_claude()`, `_run_claude_inner()`, `_execute_once()`, `_execute_once_streaming()`, and `_build_command()` — enables per-invocation turn limit overrides.
- `autonomous/manager.py`: `cancel_all_workers()` pass-through to loop.
- `settings.yaml.example`: Documented `claude_max_turns_planning` and `claude_max_turns_execution` options.

### Known Limitations

- Signal "Note to Self" conversations do not display typing indicators — this is a Signal client limitation, not a Nightwire bug. Typing indicators work correctly in conversations with other users.

## [3.0.1] - 2026-03-05

### Fixed — Production Deployment Issues

- `bot.py`: Fixed `_split_message()` rfind bug — `rfind()` returning -1 was treated as a valid split position, causing messages to be cut off at the last character instead of falling through to the next boundary type. Added word-boundary fallback between newline and hard split.
- `message_queue.py`: Added debug logging for typing indicator errors — previously `except Exception: pass` silently swallowed all failures, making typing indicator issues invisible in production logs.
- `autonomous/commands.py`: `/tasks` now detects active PRD creation and shows "A PRD is currently being generated" instead of a bare "No tasks found" during the ~95s gap between `/complex` and task creation.
- `commands/core.py`: Extended `/cancel` to support autonomous task IDs (`/cancel 5`) and `/cancel all` (cancels interactive task + pauses autonomous loop). Previously `/cancel` only cancelled interactive TaskManager tasks and ignored the `args` parameter entirely.
- `config.py`: Increased `claude_max_turns` default from 15 to 30 — production logs showed Claude exhausting turns on planning before writing files (`files_changed=0` on all tasks, circuit breaker tripped after 3 consecutive failures).
- `install.sh`: Changed systemd `StandardOutput=append:$LOGS_DIR/nightwire.log` to `StandardOutput=journal` — the RotatingFileHandler already writes clean plain-text to nightwire.log, so stdout redirect was causing duplicate lines with ANSI color codes.

### Added

- `main.py`: `--debug` CLI flag via argparse — sets `NIGHTWIRE_LOG_LEVEL=DEBUG` env var before logging initialization.
- `logging_config.py`: `NIGHTWIRE_LOG_LEVEL` environment variable override — takes precedence over `logging.level` in settings.yaml. Enables debug logging without config file changes.
- `settings.yaml.example`: Added logging configuration section with env var and CLI flag documentation. Added clarifying comment that API keys belong in `.env` not `settings.yaml`.

## [3.0.0] - 2026-03-05

### Fixed — Production Testing

- `scripts/apply-signal-patches.sh`: Fixed git file mode from 100644 to 100755 — `install.sh` checks `[ -x ]` which requires execute permission, blocking Signal device pairing entirely on fresh installs
- `logging_config.py`: Replaced structlog double-rendering architecture with proper `ProcessorFormatter.wrap_for_formatter` pattern — file handlers now produce clean plain-text logs without ANSI escape codes or junk metadata
- Aligned version to 3.0.0 across `install.sh`, `pyproject.toml`, `__init__.py`, and `CLAUDE.md`
- `install.sh`: Fixed repository URLs to point to offsecginger/nightwire fork (author attribution preserved)
- `pyproject.toml`: Fixed Repository and Bug Tracker URLs to point to offsecginger/nightwire fork
- `SECURITY.md`: Fixed security advisory URL to point to offsecginger/nightwire fork
- `bot.py`: Enhanced `no_accounts_registered` warning with actionable hint for users

## [2.9.2] - 2026-03-05

### Fixed — Production Readiness Audit
- `autonomous/loop.py`: Replaced deprecated `asyncio.ensure_future` with `asyncio.get_running_loop().create_task()` — eliminates DeprecationWarning, gracefully handles sync test contexts
- `autonomous/loop.py`: Added `asyncio.CancelledError` handler in `_process_task` — tasks cancelled during shutdown/stuck detection now correctly transition to CANCELLED status in database (with guard against double-update from `_check_stuck_tasks`)
- `autonomous/database.py`: Story completion SQL now counts CANCELLED and BLOCKED tasks as terminal — prevents stories from being stuck IN_PROGRESS forever
- `autonomous/database.py`: Added `threading.Lock` to all 14 write methods — prevents concurrent `OperationalError` when parallel workers write to the shared SQLite connection via `asyncio.to_thread`
- `README.md`: Fixed clone URL from `hackingdave/nightwire` to `offsecginger/nightwire` (consistent with pyproject.toml)
- `README.md`: Added missing `/diagnose`, `/usage`, `/monitor`, `/worker` commands to System section
- `memory/haiku_summarizer.py`: Kill orphaned subprocess on timeout — prevents zombie process accumulation
- `autonomous/quality_gates.py`: Kill orphaned subprocess on timeout in `_run_tests`, `_run_typecheck`, and `_run_lint` — prevents zombie process accumulation during autonomous pipeline
- `memory/database.py`: Fixed stale docstring "Schema version: 4" → "5"
- `SECURITY.md`: Fixed security advisory URL from `hackingdave/nightwire` to `offsecginger/nightwire`
- `config.py`: Clamp `signal_send_rate_per_second` to minimum 0.01 — prevents `ZeroDivisionError` in message queue consumer
- `task_manager.py`: Clean up orphaned temp file on `save_interrupted_tasks` failure
- `bot.py`: Initialize `source = None` before try block in message handler — prevents `UnboundLocalError` on malformed messages
- `autonomous/executor.py`: Kill orphaned git subprocesses on timeout using `active_proc` tracking pattern — covers `_git_save_checkpoint`, `_git_commit_task_changes`, `_get_files_changed`
- `claude_runner.py`: Added `ProcessLookupError` guards to all 4 `process.kill()` sites (timeout and cancel handlers in both `_execute_once` and `_execute_once_streaming`)
- `claude_runner.py`: Type-safe `claude_max_turns` parsing with `int()` conversion and `ValueError`/`TypeError` handling
- `message_queue.py`: Consumer loop uses `try/finally` to ensure cleanup runs even on `CancelledError` during shutdown
- `bot.py`: Dedup window increased from 60s to 120s to match handler timeout — prevents duplicate processing on Signal retries
- `config.py`: Added `isinstance` non-dict protection to all 4 logging config properties — prevents `AttributeError` on misconfigured `logging:` section
- `security.py`: Moved `_BIDI_CHARS` to module-level `frozenset` — eliminates per-call `set()` allocation on hot path
- `plugin_loader.py`: Added null check for `spec.loader` before `exec_module()` — prevents confusing `AttributeError` on broken plugin files

## [2.9.1] - 2026-03-05

### Added — Milestones 10-11, 15
- **Signal UX (M10)**: Per-recipient message queue with FIFO ordering, rate limiting, retry. Typing indicators. Autonomous notification debounce (critical vs non-critical split).
- **Plugin Agent System (M11)**: `AgentSpec` declarative registration, `PluginLoader` agent collection and catalog prompt generation, `TaskManager` catalog injection.
- **SubAgent Spike (M15.1)**: `--agent` and `--agents <json>` CLI flag support in `ClaudeRunner`. Evaluation findings document recommending `--agents <json>` for runtime plugin agent dispatch.
- **SubAgent Full Impl (M15.2)**: `AgentSpec` migrated to prompt-based model (dropped `handler_fn`). Agent definitions JSON threaded through TaskManager, autonomous pipeline, and `run_claude_structured()`. Plugins define agents that Claude dispatches natively via `--agents <json>`.

### Changed
- `claude_runner.py`: `agent_name` and `agent_definitions` params threaded through all call chains including `run_claude_structured()`
- `config.py`: 4 new Signal UX config properties
- `bot.py`: MessageQueue routing, typing indicator callbacks
- `autonomous/loop.py`: Notification debounce with 6 debounced + 11 critical call sites
- `plugin_base.py`, `plugin_loader.py`: AgentSpec, agent collection, catalog generation
- `task_manager.py`: Agent catalog callback, catalog concatenation

## [2.9.0] - 2026-02-27

### Added — Milestone 8: Upstream Feature Port
- **Image attachment processing** — Signal image attachments (JPEG, PNG, GIF, WebP) are downloaded, saved per-sender, and passed to Claude's agentic Read tool for multimodal analysis. Image-only messages default to "Describe this image."
- **Docker sandbox hardening** — `Dockerfile.sandbox` for Claude CLI container with non-root user, no-new-privileges, cap-drop ALL, PID limits, memory/CPU limits, and network isolation
- **Sandbox integration in Claude runner** — `_maybe_sandbox()` wraps CLI commands in Docker when `sandbox.enabled: true`, with `asyncio.to_thread()` for blocking Docker validation
- **Installer sandbox setup** — `install.sh` offers optional sandbox image build with idempotent settings.yaml config and build failure logging
- **`CONTRIBUTORS.md`** — Acknowledgment of community contributions from upstream

### Fixed — Milestone 8: Upstream Bug Fixes
- **Shutdown crash fix** — Reordered `bot.stop()` to cancel runner + background tasks BEFORE closing HTTP session (prevents use-after-close crashes on SIGTERM)
- **`cancel_all_tasks()`** — New TaskManager method drains all background tasks during shutdown
- **Attachment ID regex** — Allow dots in Signal attachment IDs (e.g., `09GIqaSf01wyBX0zokr7.jpg`) with path traversal prevention
- **Sandbox PermissionError** — `validate_docker_available()` handles PermissionError, FileNotFoundError, and TimeoutExpired gracefully
- **Sandbox hardening flags** — `--user 1000:1000`, `--security-opt no-new-privileges`, `--cap-drop ALL`, `--pids-limit 256`

### Changed
- `config.py`: Added `attachments_dir` property (default: `data/attachments/`)
- `sandbox.py`: Default image changed from `python:3.11-slim` to `nightwire-sandbox:latest`
- `SECURITY.md`: Added Docker sandbox hardening section

## [2.8.0] - 2026-02-27

### Changed — Milestone 7: CLI Runner Migration
- **Replaced Anthropic Python SDK with Claude Code CLI** — `claude -p` subprocess replaces `anthropic.AsyncAnthropic` for all Claude operations. Supports both Pro/Max OAuth login and API key authentication transparently.
- Non-streaming: `claude -p --output-format json` → JSON response with `result`, `usage`, `modelUsage`
- Streaming: `claude -p --output-format stream-json --verbose` → NDJSON events with text chunks
- Structured output: `claude -p --json-schema '{...}'` → `structured_output` field with Pydantic validation
- System prompt: `--append-system-prompt-file` with config/CLAUDE.md (replaces SDK `system` parameter)
- Error classification: text-based `classify_error()` promoted from legacy to primary classifier
- Cancel: `process.kill()` replaces `stream.close()` + `task.cancel()`
- `_InvocationState`: `process` field replaces `task`/`stream` fields
- HaikuSummarizer: migrated from SDK `client.messages.create()` to `claude -p --model haiku` subprocess
- `claude_max_turns` config: wired into `--max-turns` CLI flag (no longer deprecated)
- `anthropic` package moved from required to optional dependency (`pip install nightwire[sdk]`)

### Removed
- `classify_error_from_exception()` — SDK-era error classifier (deleted, not just deprecated)
- `import anthropic` at module level in `claude_runner.py` and `haiku_summarizer.py`

## [2.7.0] - 2026-02-27

### Changed — Milestone 1: Claude SDK Migration
- **Replaced Claude CLI subprocess with Anthropic Python SDK** — `claude --print` subprocess calls replaced by `anthropic.AsyncAnthropic` with `client.messages.create()` and `client.messages.stream()`
- `run_claude()` now calls the Anthropic API directly with native error handling, retry, and progress updates
- Added `run_claude_structured(response_model)` for Pydantic-validated JSON output via SDK `output_config` json_schema
- Error classification rewritten for SDK exceptions (`APIStatusError`, `AuthenticationError`, `RateLimitError`) instead of text pattern matching
- Streaming via `client.messages.stream()` with time-based batching (2-second interval, 50-char minimum) to avoid Signal API flooding
- Per-invocation state isolation via `_InvocationState` dataclass — concurrent `run_claude()` calls no longer share mutable state
- Cancel support broadcasts to all active invocations with belt-and-suspenders approach (`stream.close()` + `task.cancel()`)
- Added `RATE_LIMITED` error category for subscription-level rate limit detection via SDK
- Timing instrumentation: `response_time_ms`, `input_tokens`, `output_tokens`, `model` logged from SDK response metadata
- System prompt token budget check warns once when estimated tokens exceed 4,000
- `sandbox.py` marked as deprecated — SDK runs server-side, Docker sandbox no longer needed
- Added `anthropic>=0.77.0` to both `pyproject.toml` and `requirements.txt`
- Config properties added: `claude_model`, `claude_api_key`, `claude_system_prompt`, `anthropic_client_config`
- Legacy `classify_error()` text-based function (restored as primary in 3.1.0 M7 CLI migration)

### Changed — Milestone 2: Nightwire Assistant Structured Output
- `NightwireRunner.ask_structured(response_model)` added for JSON mode on any OpenAI-compatible provider via `response_format: {"type": "json_object"}`
- `AssistantResponse` Pydantic model added with `content`, `tokens_used`, `model` fields
- `ask_with_metadata()` returns full response metadata including token usage
- Cleaned up backward-compat aliases: `ask_jarvis` → `ask` (deprecated alias retained)
- Removed dead `SidechannelRunner` and `get_sidechannel_runner` references

### Changed — Milestone 3: Logging Overhaul
- **New `nightwire/logging_config.py` module** with `setup_logging(config)` and `sanitize_secrets` processor
- Subsystem log files with rotation: `bot.log`, `claude.log`, `autonomous.log`, `memory.log`, `plugins.log`, `security.log` (10MB max, 5 backups each)
- Combined `nightwire.log` for all subsystem output
- Two-phase logging initialization in `main.py` — defaults before config is loaded, full subsystem setup after
- All 28+ source files migrated from bare `structlog.get_logger()` to named `structlog.get_logger("nightwire.<subsystem>")`
- ~30 debug log calls added across all subsystems: SDK params, retry decisions, error classification, command routing, message routing, plugin matchers, task state transitions, git operations, verification I/O, quality gate details, worker dispatch, dependency checks, embedding generation, vector search results, session resolution, context budget
- **Secret sanitization processor** scrubs API keys (`sk-ant-*`, `sk-*`, `xai-*`), Bearer tokens, and E.164 phone numbers from all log output, including nested dicts
- Config properties added: `logging_level`, `logging_subsystem_levels`, `logging_max_file_size_mb`, `logging_backup_count`

### Changed — Milestone 4: OOP Refactor — Command Extraction
- **`nightwire/commands/` package created** with `base.py` and `core.py`
- `BotContext` dataclass provides shared state (config, runner, project manager, etc.) to all handlers
- `BaseCommandHandler` ABC defines the handler contract with `get_commands()` and `get_help_lines()`
- `HandlerRegistry` supports both ABC handler registration and direct `register_external()` for non-ABC handlers
- `CoreCommandHandler` encapsulates 16 core commands (`/help`, `/projects`, `/select`, `/status`, `/add`, `/remove`, `/new`, `/ask`, `/do`, `/complex`, `/cancel`, `/summary`, `/cooldown`, `/update`, `/nightwire`, `/global`)
- `BUILTIN_COMMANDS` frozenset in `commands/base.py` is single source of truth (replaces hardcoded set in plugin_loader)
- **`nightwire/task_manager.py` created** — extracts background task lifecycle management (`start_background_task`, `cancel_current_task`, `create_autonomous_prd`, `get_task_state`)
- `bot.py` reduced from 1,195 to ~563 lines (53% reduction) — `_handle_command()` is now a 12-line registry lookup
- Two-phase command registration: core + memory in `__init__`, autonomous in `start()`
- Autonomous commands registered via direct `register_external()` passthrough (no wrapper class)
- Memory commands registered via `_make_memory_commands()` factory with project-injecting closures
- `get_memory_context` extracted as standalone function to eliminate circular dependency

### Changed — Milestone 5: Structured Data Flow (Replace Regex)
- **9 Pydantic schemas added to `autonomous/models.py`**: `PRDBreakdown`, `StoryBreakdown`, `TaskBreakdown`, `VerificationOutput`, `LearningExtraction`, `ExtractedLearning`, `PytestJsonReport`, `PytestTestResult`, `JestJsonReport`
- PRD creation uses `run_claude_structured(PRDBreakdown)` with text + `parse_prd_json()` fallback
- Verification agent uses `_try_structured_verify()` with `VerificationOutput` model — fail-closed override preserved (errors = blocked)
- `_parse_files_changed()` (4 regex patterns) replaced with `_get_files_changed()` using `git diff --name-only` — git as source of truth
- Learning extraction uses `extract_with_claude()` with `LearningExtraction` model — regex `LEARNING_MARKERS` kept as fallback
- Quality gates: JSON report detection for pytest (`pytest-json-report` plugin, cached availability check) and Jest (`--json --outputFile`)
- `HaikuSummarizer` migrated from Claude CLI subprocess to Anthropic SDK with lazy `_get_client()` and proper `close()` method
- `close_summarizer()` added to shutdown path via `MemoryManager.close()`
- Added `pytest-json-report>=1.0` as optional dependency (`[project.optional-dependencies] autonomous`)
- Every structured SDK call has a real regex/text fallback — zero production risk from SDK failures

### Changed — Milestone 6: Documentation
- **Module docstrings expanded to multi-line** on all 30+ source files — purpose, key classes, key functions, constants
- **Args/Returns/Raises docstrings** added to ~140 public methods and ~25 class constructors across all subsystems
- **Signal usage examples** (RST `::` code blocks) added to all 29 command handlers: 16 in `commands/core.py`, 7 in `autonomous/commands.py`, 6 in `memory/commands.py`
- Google-style docstring format used consistently throughout
- Inline comments added for non-obvious logic (e.g., fail-closed verification, session timeout grouping, token budget estimation)

### Fixed
- All ruff lint violations resolved codebase-wide: 16 I001 (import sort), 19 F401/F541 (unused imports, empty f-strings), 2 E741 (ambiguous variable names), 50+ E501 (line length >100 chars)
- HTTP connection leak in autonomous executor/verifier — all `ClaudeRunner()` instances now closed via `try/finally` blocks
- `set_project(None)` crash — fixed with `Optional[Path]` and early return
- Windows signal handler compatibility in `main.py` — `try/except NotImplementedError` with `SIGINT` fallback
- Removed dead `SidechannelError = SignalBotError` alias from `exceptions.py`
- `claude_max_turns` config property now logs deprecation warning (SDK does not support turn limits)

### Security
- Secret sanitization processor automatically scrubs API keys, Bearer tokens, and phone numbers from all log output
- Fail-closed verification preserved through structured output migration — SDK parse errors default to "blocked"
- No secrets logged anywhere — audit confirmed across all `logger.*()` calls
- Input sanitization unchanged — control characters, bidi overrides, and length limits enforced at boundary
- Phone number masking maintained in all log paths

### Added
- `nightwire/commands/` package (M4)
- `nightwire/task_manager.py` (M4)
- `nightwire/logging_config.py` (M3)
- `tests/test_claude_runner.py` — 4 `_InvocationState` concurrency isolation tests
- `tests/test_benchmark_sdk.py` — 9 SDK performance validation tests (2 real-API behind `NIGHTWIRE_BENCHMARK=1` gate)
- `tests/test_logging_config.py` — 29 logging configuration and secret sanitization tests
- `tests/test_commands_base.py` — 27 handler registry and base class tests
- `tests/test_commands_core.py` — 30 core command handler tests
- `tests/test_task_manager.py` — 11 background task management tests
- `tests/test_integration_routing.py` — 12 message routing integration tests
- `tests/memory/test_haiku_summarizer.py` — 11 Haiku summarizer unit tests
- `tests/test_structured_output.py` — 19 structured data flow tests

### Deprecated
- `nightwire/sandbox.py` — Docker sandbox no longer needed (SDK runs server-side). Import triggers `DeprecationWarning`.
- ~~`classify_error()` in `claude_runner.py`~~ — **Undeprecated in 3.1.0** (M7 CLI migration promoted it back to primary; `classify_error_from_exception()` was deleted).
- `ask_jarvis()` in `nightwire_runner.py` — use `ask()` instead.
- `GrokRunnerError` and `MusicControlError` in `exceptions.py` — no production callers remain.

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
