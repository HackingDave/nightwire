# Auto-Update Feature Design

## Overview

Add an opt-in auto-update feature that periodically checks for new commits on the configured branch, notifies the admin via Signal, and applies updates on admin approval. Off by default.

## Configuration

New `auto_update` section in `settings.yaml`:

```yaml
auto_update:
  enabled: false          # Off by default
  check_interval: 21600   # 6 hours in seconds
  branch: "main"          # Branch to track for updates
```

Three new properties on `Config`: `auto_update_enabled`, `auto_update_check_interval`, `auto_update_branch`.

## Architecture

### New Module: `sidechannel/updater.py`

`AutoUpdater` class with an asyncio background task.

**Key methods:**
- `start()` — spawn background check loop
- `stop()` — cancel background task
- `check_for_updates()` — `git fetch`, compare local vs remote HEAD
- `apply_update()` — `git pull --ff-only`, `pip install -e .`, exit with code 75
- `rollback(previous_head)` — `git reset --hard <saved-HEAD>`, notify admin

### Integration Points

- `bot.start()` creates and starts `AutoUpdater` (if enabled)
- `bot.stop()` calls `updater.stop()` during shutdown
- `/update` command handled in `bot.py` message routing

## Message Flow

1. AutoUpdater detects new commits via `git fetch` + HEAD comparison
2. Sends Signal message to admin (first phone in allowlist):
   `"Update available: N new commits on main (abc1234 → def5678). Latest: 'commit message'. Reply /update to apply."`
3. Stores `pending_update = True` and remote HEAD sha in memory
4. Admin replies `/update` → bot validates sender is admin, applies update
5. Subsequent check cycles don't re-notify unless additional new commits appear
6. `/update` without a pending update responds: "No updates available"

## Update Process

1. Record current HEAD sha
2. Run `git pull --ff-only` (fails cleanly if branch has diverged)
3. Run `pip install -e .` to pick up dependency changes
4. Notify admin: "Update applied. Restarting..."
5. Exit with code 75 (systemd/launchd restarts the bot)

## Failure & Rollback

- If `git pull --ff-only` fails (diverged branch, conflict): notify admin, no restart
- If `pip install -e .` fails: `git reset --hard <previous-HEAD>`, notify admin, continue running
- All errors logged via structlog

## Safety

- Only admin (first phone in allowlist) can trigger `/update`
- `--ff-only` prevents merge conflicts
- All git/pip operations run via `asyncio.to_thread()` (non-blocking)
- Update state is in-memory only (lost on restart, which is fine)

## Restart Mechanism

- Bot exits with code 75 to signal intentional restart
- systemd: add `RestartForceExitStatus=75` to unit template in `install.sh`
- launchd: already restarts on non-zero exit (`KeepAlive.SuccessfulExit=false`)

## Exit Code

Exit code 75 chosen because:
- Non-zero triggers service manager restart
- Not commonly used by other tools
- Maps to EX_TEMPFAIL in sysexits.h (temporary failure, retry later — semantically close)

## Files Changed

1. `sidechannel/updater.py` — new module
2. `sidechannel/config.py` — add auto_update properties
3. `sidechannel/bot.py` — integrate AutoUpdater, add `/update` command
4. `sidechannel/main.py` — handle exit code 75
5. `config/settings.yaml.example` — add auto_update section
6. `install.sh` — add `RestartForceExitStatus=75` to systemd template
7. `tests/test_updater.py` — new test file
