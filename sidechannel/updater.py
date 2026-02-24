"""Auto-update module for sidechannel."""

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Callable, Awaitable, Optional

import structlog

logger = structlog.get_logger()

# Exit code to signal intentional restart for update
EXIT_CODE_UPDATE = 75


class AutoUpdater:
    """Checks for updates and applies them on admin approval."""

    def __init__(self, config, send_message: Callable[[str, str], Awaitable[None]],
                 repo_dir: Optional[Path] = None):
        self.config = config
        self.send_message = send_message
        self.repo_dir = repo_dir or Path(__file__).parent.parent
        self.branch = config.auto_update_branch
        self.check_interval = config.auto_update_check_interval
        self.admin_phone = config.allowed_numbers[0] if config.allowed_numbers else None

        # Update state
        self.pending_update = False
        self.pending_sha: Optional[str] = None
        self._check_task: Optional[asyncio.Task] = None

    async def _run_git(self, *args: str) -> str:
        """Run a git command and return stripped stdout."""
        cmd = ["git", "-C", str(self.repo_dir)] + list(args)
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result.stdout.strip()

    async def check_for_updates(self) -> bool:
        """Check if remote has new commits. Returns True if update available."""
        try:
            await self._run_git("fetch", "origin", self.branch)
            local_head = await self._run_git("rev-parse", "HEAD")
            remote_head = await self._run_git("rev-parse", f"origin/{self.branch}")

            if local_head == remote_head:
                self.pending_update = False
                self.pending_sha = None
                return False

            # Update available
            if self.pending_update and self.pending_sha == remote_head:
                return True

            # New update - get details and notify
            commit_count = await self._run_git(
                "rev-list", "--count", f"HEAD..origin/{self.branch}"
            )
            latest_msg = await self._run_git(
                "log", "--format=%s", "-1", f"origin/{self.branch}"
            )

            self.pending_update = True
            self.pending_sha = remote_head

            if self.admin_phone:
                msg = (
                    f"Update available: {commit_count} new commit(s) on {self.branch} "
                    f"({local_head[:7]} \u2192 {remote_head[:7]}). "
                    f"Latest: '{latest_msg}'. Reply /update to apply."
                )
                await self.send_message(self.admin_phone, msg)

            logger.info("update_available", commits=commit_count,
                        local=local_head[:7], remote=remote_head[:7])
            return True

        except Exception as e:
            logger.error("update_check_failed", error=str(e))
            return False

    async def apply_update(self) -> str:
        """Pull updates, install deps, and trigger restart. Returns status message."""
        if not self.pending_update:
            return "No updates available."

        previous_head = None
        try:
            previous_head = await self._run_git("rev-parse", "HEAD")

            # Pull with fast-forward only
            await self._run_git("pull", "--ff-only", "origin", self.branch)

            # Install dependencies
            pip_cmd = [sys.executable, "-m", "pip", "install", "-e",
                       str(self.repo_dir), "--quiet"]
            pip_result = await asyncio.to_thread(
                subprocess.run, pip_cmd, capture_output=True, text=True, timeout=120
            )
            if pip_result.returncode != 0:
                raise RuntimeError(f"pip install failed: {pip_result.stderr}")

            self.pending_update = False
            self.pending_sha = None

            logger.info("update_applied", previous=previous_head[:7])

            if self.admin_phone:
                await self.send_message(self.admin_phone,
                                        "Update applied successfully. Restarting...")

            # Schedule exit after giving the message time to send
            asyncio.get_event_loop().call_later(2, sys.exit, EXIT_CODE_UPDATE)
            return "Update applied. Restarting..."

        except subprocess.CalledProcessError as e:
            error_msg = f"Update failed (git): {e.stderr or e.stdout or str(e)}"
            logger.error("update_pull_failed", error=error_msg)
            if self.admin_phone:
                await self.send_message(self.admin_phone,
                                        f"Update failed: {error_msg}")
            return error_msg

        except RuntimeError as e:
            # pip install failed - rollback
            logger.error("update_install_failed", error=str(e))
            if previous_head:
                await self._rollback(previous_head)
            error_msg = str(e)
            if self.admin_phone:
                await self.send_message(self.admin_phone,
                                        f"Update failed and rolled back: {error_msg}")
            return f"Update failed and rolled back: {error_msg}"

    async def _rollback(self, previous_head: str):
        """Rollback to a previous commit."""
        try:
            await self._run_git("reset", "--hard", previous_head)
            logger.info("update_rollback_success", head=previous_head[:7])
        except Exception as e:
            logger.error("update_rollback_failed", error=str(e))

    async def _check_loop(self):
        """Background loop that periodically checks for updates."""
        logger.info("auto_update_loop_started",
                    interval=self.check_interval, branch=self.branch)
        while True:
            try:
                await asyncio.sleep(self.check_interval)
                await self.check_for_updates()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("auto_update_loop_error", error=str(e))

    async def start(self):
        """Start the background update check loop."""
        if not self.admin_phone:
            logger.warning("auto_update_no_admin",
                           msg="No allowed_numbers configured, cannot notify")
            return
        self._check_task = asyncio.create_task(self._check_loop())

    async def stop(self):
        """Stop the background update check loop."""
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("auto_update_loop_stopped")
