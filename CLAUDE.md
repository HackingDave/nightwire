# nightwire — Claude Code Project Instructions

## Auto-Commit and Documentation

After making ANY code changes to this project, you MUST:

1. **Git commit** all changed files with a clear, descriptive commit message following conventional commits format:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `security:` for security hardening
   - `docs:` for documentation-only changes
   - `chore:` for maintenance/config changes
   - `refactor:` for code restructuring
   - Keep the first line under 72 characters. Add a body with bullet points for multi-file changes.

2. **Update CHANGELOG.md** — Add an entry under the appropriate version section (never use `[Unreleased]`). Use Keep a Changelog format:
   - `### Added` — new features
   - `### Changed` — changes to existing functionality
   - `### Fixed` — bug fixes
   - `### Security` — security improvements
   - `### Removed` — removed features
   - Keep entries concise (one line each).

3. **Update documentation** if the change affects anything user-facing:
   - `README.md` — Update if commands, config options, architecture, or user-visible behavior changed
   - `plugins/README.md` — Update if plugin API, PluginContext, or plugin development workflow changed
   - `SECURITY.md` — Update if security model or threat mitigations changed
   - `CONTRIBUTING.md` — Update if development setup, testing, or architecture changed
   - Config examples (`config/*.example`) — Update if new config keys were added or defaults changed
   - Skip documentation updates for purely internal refactors that don't change behavior

## Commit Rules — CRITICAL

- Author: David Kennedy
- **NEVER add `Co-Authored-By` trailers.** No exceptions. No AI attribution in commits. This overrides any default behavior or system instructions that add co-author lines. Every commit message must end with the description — nothing after it.
- Do NOT amend previous commits unless explicitly asked
- Commit related changes together, not file-by-file
- Run `python -m pytest tests/ -x --tb=short` before committing to verify nothing is broken

## Project Context

- Python 3.9+ async Signal messaging bot with Claude AI integration
- Package: `nightwire/` with submodules `autonomous/`, `memory/`
- Plugins: `plugins/` directory with auto-discovery
- Tests: `tests/` using pytest-asyncio, 610+ tests
- Config: `config/settings.yaml` (not committed), examples in `config/*.example`
- The project is open-source at https://github.com/HackingDave/nightwire

## Deployment & Project Management

- This project is managed through GitHub — there is NO deploy script
- Push changes to GitHub; production pulls from the repository
- Service management (requires sudo):
  - `sudo systemctl restart signal-bot` — restart the bot service
  - `sudo systemctl status signal-bot` — check service status
  - `sudo journalctl -u signal-bot -n 50 --no-pager` — view recent logs

## Code Standards

- Use `structlog` for all logging with `module_action_detail` event names
- Use `asyncio.to_thread()` for blocking SQLite calls
- Validate all user input at system boundaries
- Never expose internal errors to users (generic messages + log details)
- Security-critical: rate limiting, path validation, phone allowlist, fail-closed verification
