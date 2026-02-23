"""Data models for music control system."""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class PlaybackAction(Enum):
    """Playback control actions."""
    PLAY = "play"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    SKIP = "skip"
    BACK = "back"


class ContentType(Enum):
    """Types of music content."""
    ARTIST = "artist"
    TRACK = "track"
    ALBUM = "album"
    PLAYLIST = "playlist"
    PODCAST = "podcast"


@dataclass
class Zone:
    """Represents a BluOS speaker zone."""
    id: str
    name: str
    ip: str
    port: int = 11000

    @property
    def base_url(self) -> str:
        """Get the base URL for this zone's BluOS API."""
        return f"http://{self.ip}:{self.port}"


@dataclass
class MusicCommand:
    """Parsed music command from natural language."""
    action: PlaybackAction
    content_query: Optional[str] = None
    content_type: Optional[ContentType] = None
    zone_target: Optional[str] = None  # Zone ID or group name
    volume: Optional[int] = None  # 0-100

    def __str__(self) -> str:
        parts = [f"action={self.action.value}"]
        if self.content_query:
            parts.append(f"query='{self.content_query}'")
        if self.content_type:
            parts.append(f"type={self.content_type.value}")
        if self.zone_target:
            parts.append(f"zone={self.zone_target}")
        if self.volume is not None:
            parts.append(f"volume={self.volume}%")
        return f"MusicCommand({', '.join(parts)})"
