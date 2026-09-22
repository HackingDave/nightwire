"""Regression tests for subprocess cleanup in ClaudeRunner._execute_claude_once.

Previously, if proc.communicate() raised anything other than a timeout,
most importantly asyncio.CancelledError from a user /cancel, the CLI
subprocess was never killed and stayed in _active_processes, leaking a
running process whose piped stdout/stderr nobody drained.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nightwire.claude_runner import ClaudeRunner, ErrorCategory


def _make_runner() -> ClaudeRunner:
    runner = ClaudeRunner()
    runner.config = SimpleNamespace(
        runner_type="claude",
        runner_path="/usr/bin/claude",
        runner_model=None,
        runner_reasoning_effort=None,
        sandbox_config={},
        claude_path="/usr/bin/claude",
        claude_max_turns=25,
        config_dir=Path("/tmp"),
        runner_name="Claude",
    )
    return runner


class _HangingProcess:
    """Dummy subprocess whose communicate() blocks until cancelled."""

    def __init__(self):
        self.returncode = None
        self.pid = 999999  # Nonexistent pid: kill falls back to proc.kill()
        self.killed = False

    def kill(self):
        self.killed = True

    async def wait(self):
        self.returncode = -9
        return self.returncode

    async def communicate(self, input=None):
        await asyncio.sleep(3600)
        return b"", b""


class _FailingProcess(_HangingProcess):
    """Dummy subprocess whose communicate() raises a transport error."""

    async def communicate(self, input=None):
        raise ConnectionResetError("pipe closed unexpectedly")


@pytest.mark.asyncio
async def test_cancel_kills_subprocess_and_propagates():
    runner = _make_runner()
    proc = _HangingProcess()
    kill_spy = MagicMock(wraps=ClaudeRunner._kill_process_group)

    with (
        patch("nightwire.claude_runner.asyncio.create_subprocess_exec", return_value=proc),
        patch.object(ClaudeRunner, "_kill_process_group", kill_spy),
    ):
        task = asyncio.create_task(
            runner._execute_claude_once(
                cmd=["claude", "-p"],
                prompt="do work",
                timeout=3600,
                project_path=Path("/tmp/project"),
            )
        )
        await asyncio.sleep(0)  # Let the subprocess start and reach communicate()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    kill_spy.assert_called_once_with(proc)
    assert proc.killed is True
    assert proc not in runner._active_processes


@pytest.mark.asyncio
async def test_communicate_failure_kills_subprocess_and_returns_error():
    runner = _make_runner()
    proc = _FailingProcess()
    kill_spy = MagicMock(wraps=ClaudeRunner._kill_process_group)

    with (
        patch("nightwire.claude_runner.asyncio.create_subprocess_exec", return_value=proc),
        patch.object(ClaudeRunner, "_kill_process_group", kill_spy),
    ):
        success, output, category = await runner._execute_claude_once(
            cmd=["claude", "-p"],
            prompt="do work",
            timeout=5,
            project_path=Path("/tmp/project"),
        )

    assert success is False
    assert category == ErrorCategory.INFRASTRUCTURE
    assert "pipe closed unexpectedly" in output
    kill_spy.assert_called_once_with(proc)
    assert proc.killed is True
    assert proc not in runner._active_processes
