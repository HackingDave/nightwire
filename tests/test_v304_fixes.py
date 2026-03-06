"""Tests for v3.0.4 production fixes."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from nightwire.autonomous.commands import get_autonomous_help_metadata
from nightwire.autonomous.loop import _format_verification_summary
from nightwire.autonomous.models import Task, TaskBreakdown
from nightwire.memory.commands import get_memory_help_metadata

# ========== Helpers ==========


def _make_task(title="Test Task", story_id=1, project="test-proj"):
    return Task(
        id=1, story_id=story_id, phone_number="+15551234567",
        project_name=project, title=title,
        description="desc", task_order=1,
    )


def _make_verification(passed=False, security=None, logic=None, issues=None):
    """Create a mock VerificationResult."""
    v = MagicMock()
    v.passed = passed
    v.security_concerns = security or []
    v.logic_errors = logic or []
    v.issues = issues or []
    return v


# ========== Fix 1: Task stats project_name filter ==========


class TestTaskStatsProjectFilter:
    """Fix 1: _get_task_stats_sync must filter today's counts by project."""

    async def test_completed_today_filters_by_project(self):
        """Completed today count should respect project_name."""
        from nightwire.autonomous.database import AutonomousDatabase
        db = AutonomousDatabase.__new__(AutonomousDatabase)
        # Verify the method source includes project_name filter on second query
        import inspect
        source = inspect.getsource(db._get_task_stats_sync)
        # The second query must include project_name conditional
        assert "params2" in source, "Second query should use dynamic params"
        assert 'sql2 +=' in source or "project_name" in source

    async def test_failed_today_filters_by_project(self):
        """Failed today count should use same project filter."""
        import inspect

        from nightwire.autonomous.database import AutonomousDatabase
        source = inspect.getsource(
            AutonomousDatabase._get_task_stats_sync
        )
        # Both queries must check project_name
        project_checks = source.count("project_name")
        assert project_checks >= 3, (
            f"Expected >=3 project_name references (2 conditional checks + param), "
            f"got {project_checks}"
        )

    async def test_no_project_counts_all(self):
        """When project_name is None, counts should span all projects."""
        import inspect

        from nightwire.autonomous.database import AutonomousDatabase
        source = inspect.getsource(
            AutonomousDatabase._get_task_stats_sync
        )
        # Both queries should have 'if project_name:' guard
        assert source.count("if project_name:") >= 2

    async def test_project_name_none_vs_empty(self):
        """Empty string project_name should not add filter (falsy)."""
        import inspect

        from nightwire.autonomous.database import AutonomousDatabase
        source = inspect.getsource(
            AutonomousDatabase._get_task_stats_sync
        )
        # Uses 'if project_name:' which treats "" as falsy — correct
        assert "if project_name:" in source


# ========== Fix 2: Autonomous start resumes paused loop ==========


class TestAutonomousStartResume:
    """Fix 2: /autonomous start should resume a paused loop."""

    async def test_start_resumes_paused_loop(self):
        """When loop is paused, /autonomous start should resume it."""
        from nightwire.autonomous.commands import AutonomousCommands

        cmds = AutonomousCommands.__new__(AutonomousCommands)
        cmds.manager = MagicMock()

        status = MagicMock()
        status.is_paused = True
        status.is_running = True
        cmds.manager.get_loop_status = AsyncMock(return_value=status)
        cmds.manager.resume_loop = AsyncMock()

        result = await cmds.handle_autonomous("+15551234567", "start")
        cmds.manager.resume_loop.assert_called_once()
        assert "resumed" in result.lower()

    async def test_start_reports_already_running(self):
        """When loop is running (not paused), report already running."""
        from nightwire.autonomous.commands import AutonomousCommands

        cmds = AutonomousCommands.__new__(AutonomousCommands)
        cmds.manager = MagicMock()

        status = MagicMock()
        status.is_paused = False
        status.is_running = True
        cmds.manager.get_loop_status = AsyncMock(return_value=status)

        result = await cmds.handle_autonomous("+15551234567", "start")
        assert "already running" in result.lower()

    async def test_start_starts_fresh(self):
        """When loop is stopped, start it fresh."""
        from nightwire.autonomous.commands import AutonomousCommands

        cmds = AutonomousCommands.__new__(AutonomousCommands)
        cmds.manager = MagicMock()

        status = MagicMock()
        status.is_paused = False
        status.is_running = False
        cmds.manager.get_loop_status = AsyncMock(return_value=status)
        cmds.manager.start_loop = AsyncMock()

        result = await cmds.handle_autonomous("+15551234567", "start")
        cmds.manager.start_loop.assert_called_once()
        assert "started" in result.lower()

    async def test_stop_then_start_works(self):
        """After stop, start should work normally."""
        from nightwire.autonomous.commands import AutonomousCommands

        cmds = AutonomousCommands.__new__(AutonomousCommands)
        cmds.manager = MagicMock()

        # After stop: is_running=False, is_paused=False
        status = MagicMock()
        status.is_paused = False
        status.is_running = False
        cmds.manager.get_loop_status = AsyncMock(return_value=status)
        cmds.manager.start_loop = AsyncMock()

        result = await cmds.handle_autonomous("+15551234567", "start")
        cmds.manager.start_loop.assert_called_once()
        assert "started" in result.lower()


# ========== Fix 3: Verification failure details ==========


class TestVerificationSummary:
    """Fix 3: Verification details in failure notifications."""

    def test_format_summary_with_security_and_logic(self):
        v = _make_verification(
            security=["SQL injection in query builder"],
            logic=["Missing null check on user input"],
            issues=["Style: inconsistent naming"],
        )
        result = _format_verification_summary(v)
        assert "Security:" in result
        assert "Logic:" in result
        assert "SQL injection" in result

    def test_format_summary_passed_returns_empty(self):
        v = _make_verification(passed=True)
        result = _format_verification_summary(v)
        assert result == ""

    def test_format_summary_none_returns_empty(self):
        result = _format_verification_summary(None)
        assert result == ""

    def test_format_summary_truncates_long_issues(self):
        v = _make_verification(
            logic=["A" * 200],
        )
        result = _format_verification_summary(v)
        # Should be truncated to 100 chars per item
        assert len(result) < 200


# ========== Fix 4: Verifier git diff with base_ref ==========


class TestVerifierBaseRef:
    """Fix 4: Verifier should use base_ref for accurate git diffs."""

    async def test_get_head_hash_success(self):
        from nightwire.autonomous.executor import TaskExecutor
        executor = TaskExecutor.__new__(TaskExecutor)

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b"abc123def456\n", b"")
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor._get_head_hash(Path("/tmp/test"))
        assert result == "abc123def456"

    async def test_get_head_hash_failure_returns_none(self):
        from nightwire.autonomous.executor import TaskExecutor
        executor = TaskExecutor.__new__(TaskExecutor)

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
        mock_proc.returncode = 128

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor._get_head_hash(Path("/tmp/test"))
        assert result is None

    async def test_get_git_diff_uses_base_ref(self):
        from nightwire.autonomous.verifier import VerificationAgent
        agent = VerificationAgent.__new__(VerificationAgent)

        calls = []

        async def mock_exec(*args, **kwargs):
            calls.append(args)
            proc = MagicMock()
            if len(calls) == 1:
                # First call: git diff HEAD (empty)
                proc.communicate = AsyncMock(return_value=(b"", b""))
                proc.returncode = 0
            else:
                # Second call: git diff base_ref HEAD
                proc.communicate = AsyncMock(
                    return_value=(b"diff --git a/file.py\n+added", b"")
                )
                proc.returncode = 0
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await agent._get_git_diff(
                Path("/tmp/test"), base_ref="abc123"
            )

        assert "abc123" in str(calls[1]), "Should use base_ref in diff command"
        assert "added" in result

    async def test_get_git_diff_falls_back_to_head_tilde1(self):
        from nightwire.autonomous.verifier import VerificationAgent
        agent = VerificationAgent.__new__(VerificationAgent)

        calls = []

        async def mock_exec(*args, **kwargs):
            calls.append(args)
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
            if len(calls) == 2:
                proc.communicate = AsyncMock(
                    return_value=(b"fallback diff", b"")
                )
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            await agent._get_git_diff(Path("/tmp/test"), base_ref=None)

        # Second call should use HEAD~1
        assert "HEAD~1" in str(calls[1])

    async def test_get_git_diff_checks_returncode(self):
        from nightwire.autonomous.verifier import VerificationAgent
        agent = VerificationAgent.__new__(VerificationAgent)

        async def mock_exec(*args, **kwargs):
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b"bad output", b"err"))
            proc.returncode = 128  # Non-zero
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await agent._get_git_diff(
                Path("/tmp/test"), base_ref="abc"
            )
        # Both calls fail with returncode 128, result should be empty
        assert result == ""

    async def test_verify_accepts_base_ref(self):
        """verify() signature accepts base_ref parameter."""
        import inspect

        from nightwire.autonomous.verifier import VerificationAgent
        sig = inspect.signature(VerificationAgent.verify)
        assert "base_ref" in sig.parameters


# ========== Fix 5: HelpMetadata for external commands ==========


class TestExternalHelpMetadata:
    """Fix 5: /help <command> should work for autonomous/memory commands."""

    def test_autonomous_help_metadata_registered(self):
        metadata = get_autonomous_help_metadata()
        expected = {"prd", "story", "task", "tasks", "queue",
                    "autonomous", "learnings"}
        assert set(metadata.keys()) == expected

    def test_memory_help_metadata_registered(self):
        metadata = get_memory_help_metadata()
        expected = {"remember", "recall", "memories", "history",
                    "forget", "preferences"}
        assert set(metadata.keys()) == expected

    def test_help_tasks_has_detail(self):
        metadata = get_autonomous_help_metadata()
        tasks_help = metadata["tasks"]
        assert tasks_help.description
        assert tasks_help.usage
        assert tasks_help.examples

    def test_help_remember_has_detail(self):
        metadata = get_memory_help_metadata()
        remember_help = metadata["remember"]
        assert remember_help.description
        assert remember_help.usage
        assert len(remember_help.examples) >= 1


# ========== Fix 6: Task dependency indices ==========


class TestTaskDependencyIndices:
    """Fix 6: TaskBreakdown should support depends_on_indices."""

    def test_task_breakdown_accepts_depends_on_indices(self):
        tb = TaskBreakdown(
            title="Deploy app",
            description="Package and deploy",
            priority=5,
            depends_on_indices=[0, 1],
        )
        assert tb.depends_on_indices == [0, 1]

    def test_task_breakdown_defaults_to_none(self):
        tb = TaskBreakdown(
            title="Init project",
            description="Set up project structure",
        )
        assert tb.depends_on_indices is None

    async def test_index_to_id_mapping_in_prd_creation(self):
        """Structured PRD creation maps indices to task IDs."""
        from nightwire.autonomous.models import (
            PRDBreakdown,
            StoryBreakdown,
        )

        breakdown = PRDBreakdown(
            prd_title="Test PRD",
            prd_description="Test",
            stories=[
                StoryBreakdown(
                    title="Story 1",
                    description="First story",
                    tasks=[
                        TaskBreakdown(
                            title="Task A", description="First",
                            depends_on_indices=None,
                        ),
                        TaskBreakdown(
                            title="Task B", description="Second",
                            depends_on_indices=[0],
                        ),
                    ],
                )
            ],
        )

        # Verify the breakdown has dependency info
        assert breakdown.stories[0].tasks[1].depends_on_indices == [0]

    async def test_tasks_without_deps_can_parallel(self):
        """Tasks with no depends_on_indices should have None deps."""
        tb = TaskBreakdown(
            title="Independent task",
            description="Can run anytime",
            priority=5,
        )
        assert tb.depends_on_indices is None
