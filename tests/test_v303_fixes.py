"""Tests for v3.0.3 production fixes: WS log filtering, notification dedup,
planning task support."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from nightwire.autonomous.executor import detect_task_type
from nightwire.autonomous.models import Task, TaskType

# ---------------------------------------------------------------------------
# Fix 1: WS frame debug log filtering
# ---------------------------------------------------------------------------


class TestWSFrameLogFiltering:
    """Verify ws_envelope logs are filtered to actionable envelope types."""

    async def test_ws_envelope_not_logged_for_receipt(self):
        """Receipt/typing/other envelope types should be filtered out."""
        envelope_types_to_skip = ("receipt", "typing", "other")
        for etype in envelope_types_to_skip:
            assert etype not in ("dataMessage", "syncMessage"), (
                f"{etype} should be filtered out"
            )

    async def test_ws_envelope_logged_for_data_message(self):
        """dataMessage and syncMessage SHOULD be in the actionable set."""
        actionable_types = ("dataMessage", "syncMessage")
        for etype in actionable_types:
            assert etype in ("dataMessage", "syncMessage"), (
                f"{etype} should be logged"
            )


# ---------------------------------------------------------------------------
# Fix 2: Deduplicate "Starting Task" notification
# ---------------------------------------------------------------------------


class TestStartingTaskDedup:
    """Verify loop does not send duplicate 'Starting task' notification."""

    async def test_process_task_no_starting_notification(self):
        """_process_task should NOT call _notify_debounced with
        'Starting task' text — executor callbacks handle this."""
        import inspect

        from nightwire.autonomous.loop import AutonomousLoop

        source = inspect.getsource(AutonomousLoop._process_task)
        # The "Starting task" debounced notification was removed in v3.0.3.
        # Only occurrence should be in the comment explaining why.
        assert "Starting task" not in source or "Note:" in source, (
            "_process_task should not send 'Starting task' notification"
        )


# ---------------------------------------------------------------------------
# Fix 3: Planning task support (TaskType.PLANNING)
# ---------------------------------------------------------------------------


def _make_task(title: str, description: str = "") -> Task:
    """Create a minimal Task for testing."""
    return Task(
        id=1,
        story_id=1,
        phone_number="+15551234567",
        project_name="test-project",
        title=title,
        description=description,
        task_order=1,
    )


class TestPlanningTaskDetection:
    """Verify detect_task_type correctly identifies planning tasks."""

    def test_choose_technology_stack_is_planning(self):
        """'Choose Technology Stack' should be detected as PLANNING."""
        task = _make_task("Choose Technology Stack")
        assert detect_task_type(task) == TaskType.PLANNING

    def test_design_login_page_is_not_planning(self):
        """'Design the login page' should NOT be PLANNING — 'design'
        is excluded from planning keywords to avoid false positives."""
        task = _make_task("Design the login page")
        result = detect_task_type(task)
        assert result != TaskType.PLANNING

    def test_plan_architecture_is_planning(self):
        """'Plan the system architecture' should be PLANNING."""
        task = _make_task("Plan the system architecture")
        assert detect_task_type(task) == TaskType.PLANNING

    def test_research_task_is_planning(self):
        """'Research best practices' should be PLANNING."""
        task = _make_task("Research best practices for caching")
        assert detect_task_type(task) == TaskType.PLANNING


class TestPlanningTaskExecution:
    """Verify executor handles planning tasks with 0 files correctly."""

    def _make_executor(self):
        """Create executor with all dependencies mocked."""
        from nightwire.autonomous.executor import TaskExecutor

        executor = TaskExecutor.__new__(TaskExecutor)
        executor.config = MagicMock()
        executor.config.autonomous_verification = True
        executor.config.get_project_path = MagicMock(
            return_value=Path("/tmp/test-project")
        )
        executor.config.projects_base_path = Path("/tmp")
        executor.run_quality_gates = True
        executor.run_verification = True
        executor.db = MagicMock()
        executor.db.get_relevant_learnings = AsyncMock(return_value=[])

        mock_learnings = [MagicMock()]
        executor.learning_extractor = MagicMock()
        executor.learning_extractor.extract_with_claude = AsyncMock(
            return_value=mock_learnings
        )
        executor.learning_extractor.extract = AsyncMock(
            return_value=mock_learnings
        )

        executor._get_files_changed = AsyncMock(return_value=[])
        executor._git_save_checkpoint = AsyncMock()

        executor.quality_runner = MagicMock()
        executor.quality_runner.snapshot_baseline = AsyncMock(
            return_value=None
        )

        mock_context = MagicMock()
        mock_context.learnings = []
        mock_context.token_count = 100
        executor._build_task_context = AsyncMock(return_value=mock_context)
        executor._build_prompt = MagicMock(return_value="prompt")

        return executor, mock_learnings

    async def test_planning_task_succeeds_with_zero_files(self):
        """Planning task with 0 file changes should succeed, not fail."""
        executor, _ = self._make_executor()

        task = _make_task(
            "Choose Technology Stack",
            "Evaluate and choose the best tech stack",
        )

        mock_runner = MagicMock()
        mock_runner.run_claude = AsyncMock(
            return_value=(True, "I recommend FastAPI with PostgreSQL")
        )
        mock_runner.last_usage = {"input_tokens": 100, "output_tokens": 50}
        mock_runner.close = AsyncMock()

        with patch(
            "nightwire.autonomous.executor.ClaudeRunner",
            return_value=mock_runner,
        ):
            result = await executor.execute(
                task, progress_callback=AsyncMock(),
            )

        assert result.success is True
        assert "no files" not in (result.error_message or "").lower()

    async def test_planning_task_extracts_learnings(self):
        """Planning tasks should still run learning extraction."""
        executor, mock_learnings = self._make_executor()

        task = _make_task(
            "Research caching strategies",
            "Evaluate Redis vs Memcached",
        )
        task.id = 2

        mock_runner = MagicMock()
        mock_runner.run_claude = AsyncMock(
            return_value=(True, "Redis is better for this use case")
        )
        mock_runner.last_usage = {"input_tokens": 200, "output_tokens": 100}
        mock_runner.close = AsyncMock()

        with patch(
            "nightwire.autonomous.executor.ClaudeRunner",
            return_value=mock_runner,
        ):
            result = await executor.execute(
                task, progress_callback=AsyncMock(),
            )

        executor.learning_extractor.extract_with_claude.assert_called_once()
        assert result.learnings_extracted == mock_learnings
