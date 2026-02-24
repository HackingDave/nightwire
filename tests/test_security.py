"""Tests for security module."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from sidechannel.security import require_valid_project_path, validate_project_path


def test_require_valid_project_path_passes_valid_path():
    """Decorator should call the wrapped function when path is valid."""
    @require_valid_project_path
    def my_func(path: str, extra: str = "hello"):
        return f"ok:{path}:{extra}"

    with patch("sidechannel.security.validate_project_path") as mock_validate:
        mock_validate.return_value = Path("/home/user/projects/valid")
        result = my_func("/home/user/projects/valid", extra="world")
        assert result == "ok:/home/user/projects/valid:world"
        mock_validate.assert_called_once_with("/home/user/projects/valid")


def test_require_valid_project_path_rejects_invalid_path():
    """Decorator should raise ValueError when path validation fails."""
    @require_valid_project_path
    def my_func(path: str):
        return "should not reach"

    with patch("sidechannel.security.validate_project_path") as mock_validate:
        mock_validate.return_value = None
        with pytest.raises(ValueError, match="Path validation failed"):
            my_func("/etc/passwd")


def test_require_valid_project_path_works_with_path_kwarg():
    """Decorator should find 'path' in kwargs too."""
    @require_valid_project_path
    def my_func(path: str):
        return "ok"

    with patch("sidechannel.security.validate_project_path") as mock_validate:
        mock_validate.return_value = Path("/valid")
        result = my_func(path="/valid")
        assert result == "ok"


def test_claude_runner_set_project_validates_path():
    """ClaudeRunner.set_project should reject invalid paths."""
    with patch("sidechannel.security.validate_project_path") as mock_validate:
        mock_validate.return_value = None
        with patch("sidechannel.claude_runner.get_config"):
            from sidechannel.claude_runner import ClaudeRunner
            runner = ClaudeRunner.__new__(ClaudeRunner)
            runner.current_project = None
            with pytest.raises(ValueError, match="validation failed"):
                runner.set_project(Path("/etc/shadow"))


@pytest.mark.asyncio
async def test_rate_limiter_thread_safety():
    """Rate limiter should be safe under concurrent access."""
    from sidechannel.security import check_rate_limit_async, _reset_rate_limits

    _reset_rate_limits()

    # Run many concurrent checks — should not raise
    async def check_many():
        tasks = [
            asyncio.create_task(check_rate_limit_async(f"+1555000{i:04d}"))
            for i in range(50)
        ]
        results = await asyncio.gather(*tasks)
        assert all(r is True for r in results)

    await check_many()
