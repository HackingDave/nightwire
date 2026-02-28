"""Tests for the context builder, including command history formatting."""

from datetime import datetime

import pytest

from nightwire.memory.context_builder import ContextBuilder
from nightwire.memory.models import (
    Conversation,
    ExplicitMemory,
    Preference,
    SearchResult,
)


@pytest.fixture
def builder():
    return ContextBuilder(max_tokens=1500)


# --- Command history formatting ---


def _make_conv(role, content, minutes_ago=0, project="testproject"):
    """Helper to create Conversation objects with decreasing timestamps."""
    ts = datetime(2026, 2, 28, 12, minutes_ago, 0)
    return Conversation(
        id=minutes_ago,
        phone_number="+1234567890",
        session_id="sess1",
        timestamp=ts,
        role=role,
        content=content,
        project_name=project,
        command_type="do" if role == "user" else "do",
    )


class TestFormatCommandHistory:
    def test_empty_history_returns_empty(self, builder):
        assert builder._format_command_history([], 5000) == ""

    def test_none_history_returns_empty(self, builder):
        assert builder._format_command_history(None, 5000) == ""

    def test_basic_command_pair(self, builder):
        history = [
            _make_conv("user", "/do add a login page", minutes_ago=0),
            _make_conv("assistant", "I've added a login page with form fields.", minutes_ago=1),
        ]
        result = builder._format_command_history(history, 5000)
        assert "## Recent Command History" in result
        assert "User: add a login page" in result  # /do prefix stripped
        assert "Claude: I've added a login page" in result

    def test_strips_do_prefix(self, builder):
        history = [
            _make_conv("user", "/do implement the feature", minutes_ago=0),
        ]
        result = builder._format_command_history(history, 5000)
        assert "/do" not in result
        assert "implement the feature" in result

    def test_preserves_non_do_messages(self, builder):
        history = [
            _make_conv("user", "just a plain message", minutes_ago=0),
        ]
        result = builder._format_command_history(history, 5000)
        assert "just a plain message" in result

    def test_truncates_long_assistant_responses(self, builder):
        long_response = "x" * 600
        history = [
            _make_conv("assistant", long_response, minutes_ago=0),
        ]
        result = builder._format_command_history(history, 5000)
        assert "..." in result
        # Should be truncated to ~500 chars for assistant
        assert len(result) < 700

    def test_truncates_long_user_messages(self, builder):
        long_msg = "y" * 400
        history = [
            _make_conv("user", long_msg, minutes_ago=0),
        ]
        result = builder._format_command_history(history, 5000)
        assert "..." in result

    def test_respects_max_chars_limit(self, builder):
        history = [
            _make_conv("user", "/do task one", minutes_ago=0),
            _make_conv("assistant", "Done with task one.", minutes_ago=1),
            _make_conv("user", "/do task two", minutes_ago=2),
            _make_conv("assistant", "Done with task two.", minutes_ago=3),
        ]
        # Very small budget
        result = builder._format_command_history(history, 100)
        # Should include at least the header and maybe one entry
        assert "## Recent Command History" in result
        # Should not include all entries
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) < 5

    def test_multiple_command_pairs(self, builder):
        history = [
            _make_conv("user", "/do add login page", minutes_ago=0),
            _make_conv("assistant", "Added login page.", minutes_ago=1),
            _make_conv("user", "/do add validation", minutes_ago=2),
            _make_conv("assistant", "Added validation.", minutes_ago=3),
        ]
        result = builder._format_command_history(history, 5000)
        assert "add login page" in result
        assert "Added login page" in result
        assert "add validation" in result
        assert "Added validation" in result


class TestBuildContextSectionWithCommandHistory:
    def test_command_history_included_in_context(self, builder):
        history = [
            _make_conv("user", "/do create API endpoint", minutes_ago=0),
            _make_conv("assistant", "Created the endpoint.", minutes_ago=1),
        ]
        result = builder.build_context_section(command_history=history)
        assert "# Memory Context" in result
        assert "## Recent Command History" in result
        assert "create API endpoint" in result

    def test_command_history_appears_before_semantic_search(self, builder):
        history = [
            _make_conv("user", "/do task A", minutes_ago=0),
        ]
        search = [
            SearchResult(
                id=1,
                content="some old conversation",
                role="user",
                timestamp=datetime(2026, 1, 1),
                similarity_score=0.8,
            )
        ]
        result = builder.build_context_section(
            command_history=history,
            relevant_history=search,
        )
        cmd_pos = result.find("## Recent Command History")
        search_pos = result.find("## Relevant Past Context")
        assert cmd_pos < search_pos

    def test_command_history_with_preferences_and_memories(self, builder):
        history = [_make_conv("user", "/do something", minutes_ago=0)]
        prefs = [Preference(phone_number="+1", category="style", key="indent", value="4 spaces")]
        mems = [ExplicitMemory(phone_number="+1", memory_text="Remember this")]

        result = builder.build_context_section(
            preferences=prefs,
            explicit_memories=mems,
            command_history=history,
        )
        assert "## User Preferences" in result
        assert "## Remembered Facts" in result
        assert "## Recent Command History" in result

    def test_no_context_returns_empty(self, builder):
        result = builder.build_context_section()
        assert result == ""

    def test_only_command_history_produces_valid_context(self, builder):
        history = [_make_conv("user", "/do hello", minutes_ago=0)]
        result = builder.build_context_section(command_history=history)
        assert result.startswith("---")
        assert result.endswith("---\n\n")


class TestExistingContextBuilderBehavior:
    """Ensure existing functionality still works after adding command_history."""

    def test_preferences_only(self, builder):
        prefs = [Preference(phone_number="+1", category="tech", key="lang", value="Python")]
        result = builder.build_context_section(preferences=prefs)
        assert "tech/lang: Python" in result

    def test_memories_only(self, builder):
        mems = [ExplicitMemory(phone_number="+1", memory_text="Use pytest")]
        result = builder.build_context_section(explicit_memories=mems)
        assert "Use pytest" in result

    def test_history_only(self, builder):
        search = [
            SearchResult(
                id=1,
                content="past conversation",
                role="user",
                timestamp=datetime(2026, 1, 15),
                similarity_score=0.9,
            )
        ]
        result = builder.build_context_section(relevant_history=search)
        assert "past conversation" in result

    def test_summarized_context_preferred_over_history(self, builder):
        search = [
            SearchResult(
                id=1,
                content="raw history",
                role="user",
                timestamp=datetime(2026, 1, 15),
                similarity_score=0.9,
            )
        ]
        result = builder.build_context_section(
            relevant_history=search,
            summarized_context="This is a summary of past work.",
        )
        assert "This is a summary" in result
        assert "raw history" not in result
