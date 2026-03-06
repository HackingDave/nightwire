## Nightwire v3.0.4 — Architectural Refactor & Production Hardening

**Author**: [@offsecginger](https://github.com/offsecginger)
**Base**: HackingDave/Nightwire `main`
**Branch**: `pr/v3.0.4-refactor-showcase`

> **Note**: This PR is submitted to showcase the work done on the fork. It is not a request for merge — the changes are extensive and architectural in nature. Dave, thank you for creating Nightwire. This project has been an incredible foundation to build on, and every change here was made with deep respect for your original vision and design. The goal was to strengthen what you built, not replace it.

---

## Summary

This fork implements a **15-milestone architectural refactor** of Nightwire, driven by iterative production testing across 4 deployment cycles (v3.0.0 through v3.0.4). The codebase grew from ~12,200 LOC to ~20,000 LOC across 44 Python files, with a comprehensive 664-test suite covering every subsystem. All changes preserve the original feature set — nothing was removed.

### High-Level Changes

- **Claude Code CLI integration** (`claude -p` subprocess) replacing direct Anthropic SDK calls — supports Pro/Max OAuth login natively
- **OOP command architecture** — `bot.py` reduced from 1,195 to ~882 lines via `HandlerRegistry` + `CoreCommandHandler` extraction
- **Structured JSON output** — Pydantic models for all Claude-parsed output with regex fallback (zero single-point-of-failure parsing)
- **Subsystem logging** — Rotating log files per subsystem (bot, claude, autonomous, memory, plugins, security) with automated secret sanitization
- **Production hardening** — 4 rounds of deploy-test-fix cycles addressing 29 real-world issues
- **Signal ACI patches** — Patched Docker image for binary ACI/PNI protocol fix (signal-cli <= 0.13.24 device linking)
- **664 tests** across 24 test files, 0 failures, 0 ruff violations

---

## Milestone Breakdown

### M1-M2: SDK Migration & Assistant Structured Output
- Replaced `claude --print` subprocess with Anthropic Python SDK (`client.messages.create()`, `client.messages.stream()`)
- Added `run_claude_structured(response_model)` for Pydantic-validated JSON output
- NightwireRunner: `ask_structured()`, `AssistantResponse` model, metadata tracking
- *Note: M7 later migrated back to CLI subprocess due to Anthropic's Feb 2026 OAuth ban on third-party SDK usage*

### M3: Logging Overhaul
- Created `nightwire/logging_config.py` with `setup_logging(config)` and two-phase initialization
- 6 subsystem log files with `RotatingFileHandler` (10MB, 5 backups each) + combined `nightwire.log`
- `sanitize_secrets` processor scrubs API keys (`sk-ant-*`, `sk-*`, `xai-*`), Bearer tokens, and E.164 phone numbers
- ~30 debug log calls added across all subsystems
- All 28+ source files migrated to named loggers (`structlog.get_logger("nightwire.<subsystem>")`)

### M4: OOP Refactor — Command Extraction
- Created `nightwire/commands/` package: `base.py` (BotContext, HandlerRegistry, BUILTIN_COMMANDS), `core.py` (CoreCommandHandler)
- Created `nightwire/task_manager.py` — background task lifecycle extraction
- `bot.py` `_handle_command()` became a 12-line registry lookup (53% file reduction)
- Two-phase command registration: core + memory in `__init__`, autonomous in `start()`

### M5: Structured Data Flow (Replace Regex)
- 9 Pydantic schemas in `autonomous/models.py` (PRDBreakdown, VerificationOutput, LearningExtraction, etc.)
- PRD creation via `run_claude_structured()` with text+`parse_prd_json()` fallback
- Verification via `_try_structured_verify()` with fail-closed override preserved
- `_get_files_changed()` uses `git diff --name-only` (replaced 4 fragile regex patterns)
- Learning extraction via `extract_with_claude()` with LearningExtraction model
- Quality gates: JSON report parsing for pytest (`pytest-json-report`) and Jest

### M6: Documentation
- Multi-line module docstrings on all 30+ source files
- Google-style Args/Returns/Raises docstrings on ~140 public methods and ~25 constructors
- Signal usage examples (RST `::` blocks) on all 29 command handlers
- All ruff violations resolved codebase-wide

### M7: CLI Runner Migration (SDK -> Claude CLI)
- Complete `claude_runner.py` rewrite (~600 lines) for `claude -p` subprocess
- `_build_command()` assembles CLI flags: `--output-format json`, `--max-turns`, `--max-budget-usd`, `--resume`, `--json-schema`
- `_execute_once_streaming()` parses NDJSON events with concurrent stderr drain (Windows pipe deadlock prevention)
- `_InvocationState` dataclass for per-invocation mutable state isolation
- HaikuSummarizer migrated to `claude -p --model haiku`
- `anthropic` moved to optional dependency

### M8: Upstream Feature Port (14 commits)
- Image attachment processing pipeline (Signal -> `process_attachments()` -> Claude Read tool)
- Docker sandbox hardening (`Dockerfile.sandbox`, `--user 1000:1000`, `--cap-drop ALL`, `--pids-limit 256`)
- Installer sandbox setup with interactive prompts
- Shutdown reorder fix (cancel tasks BEFORE session.close())
- Attachment ID regex fix for dots in Signal IDs

### M9: Configuration & Diagnostics
- `claude_max_budget_usd` property -> `--max-budget-usd` CLI flag
- Session ID tracking (`last_session_id`, `--resume` flag)
- `nightwire/diagnostics.py`: 5 health checks (claude_cli, signal_api, sqlite_vec, embeddings, docker)
- `/diagnose` command, enhanced `/help <command>`, setup status display

### M10: Signal UX Improvements
- `nightwire/message_queue.py`: Per-recipient FIFO queues with rate limiting (1 msg/sec), retry (3 attempts, exponential backoff)
- Typing indicators via `PUT/DELETE /v1/typing-indicator/`
- Autonomous notification debounce (5s window, 6 debounced + 11 critical call sites)

### M11: Plugin Agent System
- `AgentSpec` dataclass with declarative agent registration
- `PluginLoader.get_agent_catalog_prompt()` for Claude prompt injection
- Agent catalog threaded through TaskManager into Claude context

### M12: Usage & Cost Tracking
- Schema v5: `usage_records` table with per-user/project tracking
- Recording hooks across ClaudeRunner, NightwireRunner, HaikuSummarizer, autonomous executor/verifier
- `/usage` command (default summary, `/usage project`, `/usage all` admin-only)
- Budget alerts with 80%/100% thresholds and spam prevention

### M13: Bot Monitoring & Loop Resilience
- `/monitor` and `/worker` commands (list/stop/restart)
- Per-task-type circuit breakers (configurable threshold/reset)
- Stuck task detection every 5 min (configurable timeout, default 60 min)
- Worker tracking via `_WorkerInfo` dataclass

### M14: Upstream Port 2 (35 commits)
- Concurrent `/do` per project (`_sender_tasks` keyed by `(sender, project)` tuple)
- Message splitting at paragraph boundaries (3000 char max, `[1/N]` indicators)
- Per-project git locks (`_git_locks: dict[str, asyncio.Lock]`)
- Graceful shutdown (90s grace period, interrupted task persistence)
- Multi-instance feedback loop prevention (`[instance_name]` prefix filtering)
- 120s message handling timeout (DoS prevention)
- Signal ACI patches: `Dockerfile.signal`, `scripts/apply-signal-patches.sh`, 3 compose variants
- Enhanced `/diagnose` (WebSocket status, Docker status, json-rpc mode)

### M15: SubAgent Integration
- `--agent` and `--agents <json>` CLI flag support in ClaudeRunner
- AgentSpec migrated to prompt-based model (dropped `handler_fn`)
- Agent definitions JSON threaded through TaskManager, autonomous pipeline, and `run_claude_structured()`

### Production Fix Cycles (v3.0.0 through v3.0.4)

**v3.0.1** (8 fixes): Message split `rfind` bug, `/tasks` PRD detection, `/cancel` autonomous support, `claude_max_turns` 15->30, systemd journal output, `--debug` CLI flag

**v3.0.2** (9 fixes): `files_changed` detection (untracked + staged files), zero-files short-circuit, verifier cache invalidation, `/cancel all` workers, port 9090 reuse, message limit 3000 chars, `max_turns_planning`/`execution` split

**v3.0.3** (6 fixes): WebSocket debug log noise filter, "Starting task" notification dedup, `TaskType.PLANNING` for 0-file tasks, `settings.yaml.example` completeness, debounce default alignment

**v3.0.4** (6 fixes): Task stats project filter, `/autonomous start` resume, verification detail in notifications, verifier base_ref for accurate diffs, `/help <command>` for all commands, task dependency indices in PRD creation

---

## New Files Added

### Core Application
| File | Purpose |
|------|---------|
| `nightwire/commands/__init__.py` | Commands package |
| `nightwire/commands/base.py` | BotContext, HandlerRegistry, HelpMetadata, BUILTIN_COMMANDS |
| `nightwire/commands/core.py` | CoreCommandHandler (20 commands + helpers) |
| `nightwire/task_manager.py` | Background task lifecycle, per-(sender,project) isolation |
| `nightwire/diagnostics.py` | Health checks (5+) with actionable hints |
| `nightwire/logging_config.py` | Subsystem log files, rotation, secret sanitization |
| `nightwire/message_queue.py` | Per-recipient FIFO with rate limiting and retry |

### Infrastructure
| File | Purpose |
|------|---------|
| `Dockerfile.signal` | Patched Signal bridge (ACI binary protocol fix) |
| `Dockerfile.sandbox` | Claude CLI sandbox container |
| `docker-compose.prepackaged.yml` | Default: patched nightwire-signal image |
| `docker-compose.unpatched.yml` | Vanilla signal-cli (no patches) |
| `scripts/apply-signal-patches.sh` | Idempotent signal-cli patch script |
| `patches/signal-cli/` | Compiled class files + Turasa JARs |

### Test Suite (24 files, 664 tests)
| File | Tests | Coverage |
|------|-------|----------|
| `test_benchmark_sdk.py` | 9 | CLI runner behavioral timing |
| `test_claude_runner.py` | 4 | Concurrent invocation isolation |
| `test_commands_base.py` | 27 | Handler registry |
| `test_commands_core.py` | 30 | Core command handlers |
| `test_integration_routing.py` | 12 | Message routing |
| `test_logging_config.py` | 29 | Logging + secret sanitization |
| `test_task_manager.py` | 11 | Background task management |
| `test_m5_structured.py` | 19 | Structured data flow |
| `test_m8_upstream.py` | 30 | Upstream feature port |
| `test_m9_config_diagnostics.py` | 34 | Config + diagnostics |
| `test_m10_signal_ux.py` | 32 | Message queue + typing |
| `test_m11_plugin_agents.py` | 26 | Plugin agent system |
| `test_m12_usage_tracking.py` | 35 | Usage/cost tracking |
| `test_m13_monitoring.py` | 54 | Monitoring + circuit breakers |
| `test_m14_bug_fixes.py` | 34 | Bug fixes |
| `test_m14_signal_infra.py` | 28 | Signal ACI infrastructure |
| `test_m14b_deferred.py` | 25 | Deferred M14 items |
| `test_m15_subagent_spike.py` | 9 | SubAgent spike prototype |
| `test_m15_full_impl.py` | 22 | SubAgent full implementation |
| `test_v303_fixes.py` | 24 | v3.0.3 production fixes |
| `test_v304_fixes.py` | 26 | v3.0.4 production fixes |
| `memory/test_haiku_summarizer.py` | 11 | Haiku summarizer |
| + 3 more | 18 | Various |

---

## Statistics

| Metric | Value |
|--------|-------|
| Application LOC | ~20,000 |
| Python files | 44 |
| Test files | 24 |
| Total tests | 664 |
| Test failures | 0 |
| Ruff violations | 0 |
| Files changed vs upstream | 98 |
| Insertions | 21,164 |
| Deletions | 2,892 |
| Commits ahead | 20 |
| Production deploy cycles | 4 (v3.0.0 - v3.0.4) |
| Production issues fixed | 29 |

---

## Breaking Changes

None. All original features and commands are preserved. The `sidechannel` backward-compatibility aliases remain functional.

## Security Considerations

- Automated secret sanitization in all log output (API keys, Bearer tokens, phone numbers)
- Fail-closed verification model preserved through all migrations
- Input sanitization unchanged — control characters, bidi overrides, and length limits enforced
- Phone number masking in all log paths
- Docker sandbox hardening (non-root, cap-drop, pids-limit)
- Signal ACI patches include checksums for JAR supply chain integrity

## Test Plan

- [x] Full test suite: 662 passed, 2 skipped, 0 failures
- [x] ruff check: 0 violations
- [x] 4 production deployment cycles with real Signal messaging
- [x] Autonomous task pipeline tested with `/complex` end-to-end
- [x] Memory system tested with `/remember`, `/recall`, `/forget`
- [x] Plugin system tested with agent registration and catalog injection
- [x] Signal ACI patches tested with fresh device linking on signal-cli 0.13.24

---

*Built with [Claude Code](https://claude.ai/code) by [@offsecginger](https://github.com/offsecginger). All credit for the original Nightwire project goes to [Dave Kennedy (@HackingDave)](https://github.com/HackingDave).*
