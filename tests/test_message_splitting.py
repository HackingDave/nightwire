"""Tests for message splitting and text truncation in bot."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from nightwire.bot import SignalBot


@pytest.fixture
def bot():
    """Create a minimal bot instance for testing _split_message."""
    with patch.object(SignalBot, "__init__", lambda self: None):
        b = SignalBot.__new__(SignalBot)
        return b


class TestSplitMessage:
    def test_short_message_no_split(self, bot):
        result = bot._split_message("Hello, world!")
        assert result == ["Hello, world!"]

    def test_exactly_at_limit(self, bot):
        msg = "x" * 5000
        result = bot._split_message(msg)
        assert result == [msg]

    def test_splits_at_paragraph_boundary(self, bot):
        paragraph1 = "A" * 3000
        paragraph2 = "B" * 3000
        msg = paragraph1 + "\n\n" + paragraph2
        result = bot._split_message(msg)
        assert len(result) == 2
        assert result[0] == paragraph1
        assert result[1] == paragraph2

    def test_splits_at_line_boundary(self, bot):
        line1 = "A" * 3000
        line2 = "B" * 3000
        msg = line1 + "\n" + line2
        result = bot._split_message(msg)
        assert len(result) == 2
        assert result[0] == line1
        assert result[1] == line2

    def test_hard_split_when_no_boundaries(self, bot):
        msg = "A" * 10000
        result = bot._split_message(msg, max_length=5000)
        assert len(result) == 2
        assert result[0] == "A" * 5000
        assert result[1] == "A" * 5000

    def test_multiple_parts(self, bot):
        msg = "A" * 15000
        result = bot._split_message(msg, max_length=5000)
        assert len(result) == 3
        assert all(len(p) == 5000 for p in result)

    def test_prefers_paragraph_over_line_split(self, bot):
        # Build a message with paragraph break well past halfway
        part1 = "A" * 3500
        part2 = "B" * 3500
        # paragraph break at 3500, well past halfway (2500)
        msg = part1 + "\n\n" + part2
        result = bot._split_message(msg)
        assert len(result) == 2
        assert result[0] == part1
        assert result[1] == part2

    def test_empty_message(self, bot):
        result = bot._split_message("")
        assert result == [""]

    def test_custom_max_length(self, bot):
        msg = "A" * 200
        result = bot._split_message(msg, max_length=100)
        assert len(result) == 2
        assert result[0] == "A" * 100
        assert result[1] == "A" * 100


class TestTruncateDescription:
    def test_short_description_unchanged(self):
        assert SignalBot._truncate_description("hello world") == "hello world"

    def test_exactly_at_limit(self):
        desc = "x" * 100
        assert SignalBot._truncate_description(desc) == desc

    def test_truncates_at_word_boundary(self):
        desc = "we don't seem to be doing well early on - anything you can learn to improve chances? Right now we are doing poorly"
        result = SignalBot._truncate_description(desc)
        assert result.endswith("...")
        assert len(result) <= 103  # 100 + "..."
        assert "Right now we" in result
        # Should NOT cut mid-word like "we ar"
        assert not result.endswith("ar...")

    def test_adds_ellipsis_when_truncated(self):
        desc = "a " * 100  # 200 chars
        result = SignalBot._truncate_description(desc)
        assert result.endswith("...")

    def test_custom_max_len(self):
        desc = "hello world this is a longer string"
        result = SignalBot._truncate_description(desc, max_len=20)
        assert len(result) <= 23  # 20 + "..."
        assert result.endswith("...")

    def test_no_space_falls_back_to_hard_truncate(self):
        desc = "a" * 200  # No spaces at all
        result = SignalBot._truncate_description(desc)
        assert result == "a" * 100 + "..."
