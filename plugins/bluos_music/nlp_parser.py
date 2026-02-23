"""Natural language parser for music commands."""

import re
from typing import Dict, List, Optional, Pattern

import structlog

from .models import ContentType, MusicCommand, PlaybackAction

logger = structlog.get_logger()


class MusicNLPParser:
    """Parse natural language music commands."""

    # Zone aliases - maps user phrases to zone IDs
    ZONE_ALIASES: Dict[str, List[str]] = {
        "main_floor": ["main", "main floor", "living room", "living", "great room"],
        "master_bedbath": ["master", "bedroom", "master bedroom", "master bath", "bed bath"],
        "craft_room": ["craft", "craft room", "crafts"],
        "basement": ["basement", "downstairs", "lower level"],
        "pool": ["pool", "pool area"],
        "deck": ["deck", "back deck", "patio"],
        "court": ["court", "basketball", "sport court"],
        "gym": ["gym", "workout room", "exercise room", "fitness"],
        "bunker_garage": ["garage", "bunker", "bunker garage"],
        # Groups
        "inside": ["inside", "indoors", "in the house", "all inside", "whole house"],
        "outside": ["outside", "outdoors", "exterior", "all outside"],
    }

    # Action patterns
    ACTION_PATTERNS: Dict[PlaybackAction, List[str]] = {
        PlaybackAction.PLAY: ["play", "put on", "start", "queue", "listen to"],
        PlaybackAction.PAUSE: ["pause", "hold"],
        PlaybackAction.RESUME: ["resume", "continue", "unpause"],
        PlaybackAction.STOP: ["stop", "turn off", "end", "silence"],
        PlaybackAction.SKIP: ["skip", "next", "skip track", "next track", "next song"],
        PlaybackAction.BACK: ["back", "previous", "go back", "last track", "previous track"],
    }

    # Content type detection patterns
    CONTENT_TYPE_PATTERNS: Dict[ContentType, List[Pattern]] = {
        ContentType.PLAYLIST: [
            re.compile(r'\bplaylist\b', re.IGNORECASE),
            re.compile(r'\bmy\s+\w+\s+mix\b', re.IGNORECASE),  # "my daily mix"
            re.compile(r'\bdiscover\s*weekly\b', re.IGNORECASE),
            re.compile(r'\brelease\s*radar\b', re.IGNORECASE),
        ],
        ContentType.PODCAST: [
            re.compile(r'\bpodcast\b', re.IGNORECASE),
            re.compile(r'\bepisode\b', re.IGNORECASE),
            re.compile(r'\bshow\b(?!\s+me)', re.IGNORECASE),  # "show" but not "show me"
            # Known podcast hosts
            re.compile(r'\b(joe\s*rogan|tim\s*ferriss|lex\s*fridman|huberman|jre)\b', re.IGNORECASE),
        ],
        ContentType.ALBUM: [
            re.compile(r'\balbum\b', re.IGNORECASE),
            re.compile(r'\bthe\s+\w+\s+album\b', re.IGNORECASE),
        ],
        ContentType.TRACK: [
            re.compile(r'\bsong\b', re.IGNORECASE),
            re.compile(r'\btrack\b', re.IGNORECASE),
        ],
    }

    # Common playlist name keywords (without explicit "playlist" word)
    PLAYLIST_KEYWORDS = [
        "workout", "chill", "focus", "party", "sleep", "morning",
        "evening", "dinner", "cooking", "running", "cardio", "yoga",
        "meditation", "study", "work", "driving", "road trip",
        "summer", "winter", "christmas", "holiday", "throwback",
    ]

    # Volume patterns
    VOLUME_PATTERNS = [
        re.compile(r'at\s+(\d+)\s*%', re.IGNORECASE),
        re.compile(r'at\s+(\d+)\s*percent', re.IGNORECASE),
        re.compile(r'volume\s+(\d+)', re.IGNORECASE),
        re.compile(r'(\d+)\s*%\s*volume', re.IGNORECASE),
        re.compile(r'set\s+(?:to\s+)?(\d+)\s*%?', re.IGNORECASE),
    ]

    def __init__(self, zone_groups: Optional[Dict[str, List[str]]] = None):
        """
        Initialize the parser.

        Args:
            zone_groups: Dictionary mapping group names to zone IDs
        """
        self.zone_groups = zone_groups or {}

        # Build reverse lookup for zone aliases
        self._alias_to_zone: Dict[str, str] = {}
        for zone_id, aliases in self.ZONE_ALIASES.items():
            for alias in aliases:
                self._alias_to_zone[alias.lower()] = zone_id

    def is_music_command(self, message: str) -> bool:
        """
        Check if a message contains a music intent.

        Unlike the original signal bot version, this does not require a
        "jarvis" prefix since the plugin framework handles routing before
        the message reaches the plugin.

        Args:
            message: The message to check

        Returns:
            True if the message appears to be a music command
        """
        msg_lower = message.lower().strip()

        # Check for any action keyword
        for action, keywords in self.ACTION_PATTERNS.items():
            for keyword in keywords:
                if msg_lower.startswith(keyword):
                    # Additional check: for "play", require some content or zone
                    if action == PlaybackAction.PLAY:
                        # Must have more than just "play"
                        return len(msg_lower.split()) > 1
                    return True

        return False

    def parse(self, message: str) -> Optional[MusicCommand]:
        """
        Parse a natural language message into a MusicCommand.

        Args:
            message: The message to parse

        Returns:
            MusicCommand if parsing succeeds, None otherwise
        """
        msg = message.strip()
        msg_lower = msg.lower()

        # Detect action
        action = self._detect_action(msg_lower)
        if not action:
            logger.debug("music_parser_no_action", message=msg[:50])
            return None

        # Extract volume
        volume = self._extract_volume(msg)

        # Extract zone target
        zone_target = self._extract_zone(msg_lower)

        # Extract content query (for play action)
        content_query = None
        content_type = None

        if action == PlaybackAction.PLAY:
            content_query = self._extract_content_query(msg_lower, zone_target, volume)
            if content_query:
                content_type = self._detect_content_type(content_query)

        command = MusicCommand(
            action=action,
            content_query=content_query,
            content_type=content_type,
            zone_target=zone_target,
            volume=volume
        )

        logger.info("music_command_parsed", command=str(command))
        return command

    def _detect_action(self, msg_lower: str) -> Optional[PlaybackAction]:
        """Detect the playback action from the message."""
        for action, keywords in self.ACTION_PATTERNS.items():
            for keyword in keywords:
                # Check for keyword at start or after space
                if msg_lower.startswith(keyword + " ") or msg_lower.startswith(keyword + ","):
                    return action
                if f" {keyword} " in msg_lower or msg_lower.endswith(f" {keyword}"):
                    return action
                # Exact match (for single-word commands)
                if msg_lower == keyword:
                    return action
        return None

    def _extract_volume(self, message: str) -> Optional[int]:
        """Extract volume level from message."""
        for pattern in self.VOLUME_PATTERNS:
            match = pattern.search(message)
            if match:
                vol = int(match.group(1))
                return max(0, min(100, vol))
        return None

    def _extract_zone(self, msg_lower: str) -> Optional[str]:
        """Extract zone target from message."""
        # Check for "in the <zone>" or "on the <zone>" patterns
        in_patterns = [
            r'\bin\s+(?:the\s+)?(\w+(?:\s+\w+)?)',
            r'\bon\s+(?:the\s+)?(\w+(?:\s+\w+)?)',
            r'\bto\s+(?:the\s+)?(\w+(?:\s+\w+)?)',
        ]

        for pattern in in_patterns:
            match = re.search(pattern, msg_lower)
            if match:
                potential_zone = match.group(1).strip()
                # Check if it's a known zone
                if potential_zone in self._alias_to_zone:
                    return self._alias_to_zone[potential_zone]

        # Direct zone name anywhere in message
        # Sort by length (longest first) to match "main floor" before "main"
        for alias in sorted(self._alias_to_zone.keys(), key=len, reverse=True):
            if alias in msg_lower:
                return self._alias_to_zone[alias]

        return None

    def _extract_content_query(
        self,
        msg_lower: str,
        zone_target: Optional[str],
        volume: Optional[int]
    ) -> Optional[str]:
        """Extract the content to play from the message."""
        # Start with the message
        query = msg_lower

        # Remove action words at the start
        for keywords in self.ACTION_PATTERNS.values():
            for keyword in keywords:
                if query.startswith(keyword + " "):
                    query = query[len(keyword):].strip()
                    break

        # Remove zone references - use specific zone patterns
        zone_patterns = [
            r'\bin\s+(?:the\s+)?\w+(?:\s+\w+)?(?:\s+zone)?',
            r'\bon\s+(?:the\s+)?\w+(?:\s+\w+)?',
            r'\bto\s+(?:the\s+)?\w+(?:\s+\w+)?',
        ]
        for pattern in zone_patterns:
            query = re.sub(pattern, '', query)

        # Remove known zone aliases directly (for cases without prepositions)
        # Sort by length to match longer aliases first
        for alias in sorted(self._alias_to_zone.keys(), key=len, reverse=True):
            # Use word boundaries to avoid partial matches
            query = re.sub(r'\b' + re.escape(alias) + r'\b', '', query, flags=re.IGNORECASE)

        # Remove volume references
        for pattern in self.VOLUME_PATTERNS:
            query = pattern.sub('', query)

        # Also remove standalone percentage patterns
        query = re.sub(r'\b\d+\s*%', '', query)
        query = re.sub(r'\b\d+\s*percent\b', '', query, flags=re.IGNORECASE)

        # Remove common filler words
        query = re.sub(r'\b(some|something|music|by)\b', ' ', query)

        # Clean up whitespace
        query = ' '.join(query.split()).strip()

        # If nothing left, return None
        if not query or query in ['the', 'a', 'an', 'my']:
            return None

        return query

    def _detect_content_type(self, query: str) -> ContentType:
        """
        Detect the content type from the query.

        Returns ARTIST as default if no specific type is detected.
        """
        query_lower = query.lower()

        # Check explicit patterns first
        for content_type, patterns in self.CONTENT_TYPE_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(query_lower):
                    logger.debug(
                        "content_type_detected",
                        type=content_type.value,
                        query=query[:30]
                    )
                    return content_type

        # Check playlist keywords (without explicit "playlist" word)
        for keyword in self.PLAYLIST_KEYWORDS:
            if keyword in query_lower:
                # Only if it looks like a playlist context
                if "playlist" not in query_lower and "by" not in query_lower:
                    logger.debug(
                        "playlist_keyword_detected",
                        keyword=keyword,
                        query=query[:30]
                    )
                    return ContentType.PLAYLIST

        # Default to ARTIST
        return ContentType.ARTIST

    def get_zone_ids(self, zone_target: str) -> List[str]:
        """
        Resolve a zone target to a list of zone IDs.

        Handles both individual zones and groups.

        Args:
            zone_target: Zone ID or group name

        Returns:
            List of zone IDs
        """
        # Check if it's a group
        if zone_target in self.zone_groups:
            return self.zone_groups[zone_target]

        # Single zone
        return [zone_target]
