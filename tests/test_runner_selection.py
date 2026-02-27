"""Tests for runner command selection and OpenCode output parsing."""

import json
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from nightwire.bot import SignalBot
from nightwire.claude_runner import ClaudeRunner


def _make_runner(monkeypatch, runner_type="claude", runner_path="opencode"):
    cfg = SimpleNamespace(
        config_dir=Path("/tmp"),
        runner_type=runner_type,
        runner_path=runner_path,
        claude_path="claude",
        claude_max_turns=8,
        claude_timeout=60,
    )
    monkeypatch.setattr("nightwire.claude_runner.get_config", lambda: cfg)
    return ClaudeRunner()


def test_default_runner_keeps_claude_command(monkeypatch):
    runner = _make_runner(monkeypatch, runner_type="claude")

    cmd = runner._build_runner_command(Path("/tmp/project"))

    assert cmd == [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--verbose",
        "--max-turns",
        "8",
    ]


def test_opencode_runner_uses_json_command(monkeypatch):
    runner = _make_runner(
        monkeypatch,
        runner_type="opencode",
        runner_path="/usr/local/bin/opencode",
    )

    cmd = runner._build_runner_command(Path("/tmp/project"))

    assert cmd == [
        "/usr/local/bin/opencode",
        "run",
        "--format",
        "json",
        "--dir",
        "/tmp/project",
    ]


def test_opencode_json_events_extract_text(monkeypatch):
    runner = _make_runner(monkeypatch, runner_type="opencode")

    output = "\n".join(
        [
            json.dumps({"type": "text", "text": "first line"}),
            json.dumps(
                {
                    "type": "content",
                    "content": [
                        {"type": "text", "text": "second line"},
                        {"type": "image", "url": "https://example.invalid/img"},
                    ],
                }
            ),
            json.dumps(
                {
                    "type": "assistant_message",
                    "message": {
                        "content": [
                            {"type": "text", "text": "third line"},
                            {"type": "tool_use", "name": "noop"},
                        ]
                    },
                }
            ),
            "not-json",
        ]
    )

    extracted = runner._extract_opencode_text(output)

    assert extracted == "first line\nsecond line\nthird line"


@pytest.mark.asyncio
@pytest.mark.parametrize("sandbox_enabled", [False, True])
async def test_signal_message_exec_path_uses_direct_or_sandbox_runner(monkeypatch, tmp_path, sandbox_enabled):
    cfg = SimpleNamespace(
        config_dir=tmp_path,
        runner_type="opencode",
        runner_path="/usr/local/bin/opencode",
        claude_path="claude",
        claude_max_turns=8,
        claude_timeout=60,
        sandbox_config={
            "enabled": sandbox_enabled,
            "image": "nightwire-sandbox:latest",
            "network": False,
            "memory_limit": "2g",
            "cpu_limit": 2.0,
            "tmpfs_size": "256m",
        },
        memory_max_context_tokens=1000,
    )
    monkeypatch.setattr("nightwire.claude_runner.get_config", lambda: cfg)

    captured_commands = []

    class _FakeProcess:
        returncode = 0

        async def communicate(self, input=None):
            return b'{"type":"text","text":"ok"}\n', b""

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    async def _fake_create_subprocess_exec(*cmd, **kwargs):
        captured_commands.append(list(cmd))
        return _FakeProcess()

    monkeypatch.setattr(
        "nightwire.claude_runner.asyncio.create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    monkeypatch.setattr("nightwire.sandbox.validate_docker_available", lambda: (True, ""))

    runner = ClaudeRunner()

    bot = cast(Any, SignalBot.__new__(SignalBot))
    bot.config = SimpleNamespace(memory_max_context_tokens=1000)
    bot.runner = runner
    bot.project_manager = SimpleNamespace(
        get_current_project=lambda _sender: "demo-project",
        get_current_path=lambda _sender: tmp_path,
    )
    bot.memory = SimpleNamespace(
        store_message=AsyncMock(return_value=None),
        get_relevant_context=AsyncMock(return_value=None),
    )
    bot.plugin_loader = SimpleNamespace(get_sorted_matchers=lambda: [])
    bot.cooldown_manager = None
    bot._sender_tasks = {}
    bot.nightwire_runner = None
    bot._send_message = AsyncMock(return_value=None)

    started_task = {}
    original_start_background_task = SignalBot._start_background_task

    def _capture_background_task(self, sender, task_description, project_name, image_paths=None):
        original_start_background_task(self, sender, task_description, project_name, image_paths=image_paths)
        started_task["task"] = self._sender_tasks[sender]["task"]

    bot._start_background_task = MethodType(_capture_background_task, bot)

    monkeypatch.setattr("nightwire.bot.is_authorized", lambda _sender: True)
    monkeypatch.setattr("nightwire.bot.check_rate_limit", lambda _sender: True)

    await SignalBot._process_message(bot, "+15555550123", "run this")
    await started_task["task"]

    assert captured_commands
    cmd = captured_commands[0]

    if not sandbox_enabled:
        assert cmd[0] == "/usr/local/bin/opencode"
        assert cmd[1:5] == ["run", "--format", "json", "--dir"]
        assert cmd[5] == str(tmp_path)
    else:
        assert cmd[:2] == ["docker", "run"]
        opencode_idx = cmd.index("/usr/local/bin/opencode")
        assert cmd[opencode_idx:opencode_idx + 5] == [
            "/usr/local/bin/opencode",
            "run",
            "--format",
            "json",
            "--dir",
        ]
        assert cmd[opencode_idx + 5] == str(tmp_path)
