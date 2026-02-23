"""BluOS music control plugin for sidechannel."""

from typing import Dict, List, Optional

from sidechannel.plugin_base import (
    SidechannelPlugin,
    MessageMatcher,
    HelpSection,
)

from .models import MusicCommand, PlaybackAction, Zone
from .bluos_controller import BluOSController
from .nlp_parser import MusicNLPParser


class BluOSMusicPlugin(SidechannelPlugin):
    """Multi-room BluOS speaker control plugin."""

    name = "bluos_music"
    description = "Multi-room BluOS speaker control"
    version = "1.0.0"

    def __init__(self, ctx):
        super().__init__(ctx)
        # Read zone config from plugins.bluos_music.players
        players_config = self.ctx.get_config("players", {})
        groups_config = self.ctx.get_config("groups", {})

        # Build zones from config
        self._zones: Dict[str, Zone] = {}
        for zone_id, zone_info in players_config.items():
            self._zones[zone_id] = Zone(
                id=zone_id,
                name=zone_info.get("name", zone_id),
                ip=zone_info.get("ip", ""),
                port=zone_info.get("port", 11000),
            )

        # Initialize NLP parser with zone groups
        self._parser = MusicNLPParser(zone_groups=groups_config)

        # Initialize BluOS controller
        self._controller = BluOSController(zones=self._zones)

    def commands(self):
        return {"music": self._handle_music_command}

    def message_matchers(self):
        return [
            MessageMatcher(
                priority=10,
                match_fn=self._is_music_command,
                handle_fn=self._handle_music_message,
                description="BluOS music NLP",
            )
        ]

    def _is_music_command(self, message: str) -> bool:
        """Check if message looks like a music command."""
        return self._parser.is_music_command(message)

    async def _handle_music_message(self, sender: str, message: str) -> str:
        """Handle a music command from NLP parsing."""
        try:
            command = self._parser.parse(message)
            if command is None:
                return "I couldn't understand that music command."
            return await self._execute_command(command)
        except Exception as e:
            self.ctx.logger.error("music_command_error", error=str(e))
            return f"Music error: {e}"

    async def _handle_music_command(self, sender: str, args: str) -> str:
        """Handle /music command."""
        if not args:
            return self._get_music_help()
        return await self._handle_music_message(sender, args)

    async def _execute_command(self, command: MusicCommand) -> str:
        """Execute a parsed music command.

        Adapted from MusicManager.handle_command().
        """
        self.ctx.logger.info("music_command_received", command=str(command))

        try:
            if command.action == PlaybackAction.PAUSE:
                return await self._handle_pause(command)
            elif command.action == PlaybackAction.RESUME:
                return await self._handle_resume(command)
            elif command.action == PlaybackAction.STOP:
                return await self._handle_stop(command)
            elif command.action == PlaybackAction.SKIP:
                return await self._handle_skip(command)
            elif command.action == PlaybackAction.BACK:
                return await self._handle_back(command)
            elif command.action == PlaybackAction.PLAY:
                return await self._handle_play(command)
            else:
                return f"Unknown action: {command.action.value}"
        except Exception as e:
            self.ctx.logger.error(
                "music_command_error", error=str(e), command=str(command)
            )
            return f"Music command failed: {str(e)}"

    # -- Playback action handlers (ported from MusicManager) --

    def _get_leader_zone(self, command: MusicCommand) -> Optional[Zone]:
        """Resolve command to a single leader zone, with fallback to first available."""
        zones = self._resolve_zones(command.zone_target)
        if not zones:
            zones = list(self._zones.values())[:1]
        return zones[0] if zones else None

    async def _handle_pause(self, command: MusicCommand) -> str:
        """Handle pause command."""
        leader = self._get_leader_zone(command)
        if not leader:
            return "No zones available."
        success = await self._controller.pause(leader)
        if success:
            return "Paused."
        return "Failed to pause playback."

    async def _handle_resume(self, command: MusicCommand) -> str:
        """Handle resume command."""
        leader = self._get_leader_zone(command)
        if not leader:
            return "No zones available."
        success = await self._controller.play(leader)
        if success:
            return "Resumed."
        return "Failed to resume playback."

    async def _handle_stop(self, command: MusicCommand) -> str:
        """Handle stop command."""
        leader = self._get_leader_zone(command)
        if not leader:
            return "No zones available."
        success = await self._controller.stop(leader)
        if success:
            return "Stopped."
        return "Failed to stop playback."

    async def _handle_skip(self, command: MusicCommand) -> str:
        """Handle skip command."""
        leader = self._get_leader_zone(command)
        if not leader:
            return "No zones available."
        success = await self._controller.skip(leader)
        if success:
            return "Skipped to next track."
        return "Failed to skip track."

    async def _handle_back(self, command: MusicCommand) -> str:
        """Handle back/previous command."""
        leader = self._get_leader_zone(command)
        if not leader:
            return "No zones available."
        success = await self._controller.back(leader)
        if success:
            return "Went back to previous track."
        return "Failed to go back."

    async def _handle_play(self, command: MusicCommand) -> str:
        """Handle play command - sets up zones and volumes."""
        # 1. Resolve zones
        zones = self._resolve_zones(command.zone_target)
        if not zones:
            return "No valid zone specified."

        leader = zones[0]
        followers = zones[1:] if len(zones) > 1 else []

        # 2. Create BluOS group if multiple zones
        if followers:
            group_success = await self._controller.create_group(leader, followers)
            if not group_success:
                self.ctx.logger.warning(
                    "bluos_group_failed",
                    leader=leader.id,
                    followers=[f.id for f in followers],
                )

        # 3. Set volumes if specified
        volume_msg = ""
        if command.volume is not None:
            results = await self._controller.set_group_volumes(zones, command.volume)
            successful = sum(1 for v in results.values() if v)
            if successful == len(zones):
                volume_msg = f" at {command.volume}%"
            else:
                volume_msg = f" (volume set on {successful}/{len(zones)} zones)"

        # 4. Resume playback on leader
        await self._controller.play(leader)

        # Build response
        zone_desc = self._describe_zones(zones)
        if command.content_query:
            return (
                f"BluOS zones ready {zone_desc}{volume_msg}. "
                "Start playback from your streaming app."
            )
        return f"Resumed playback {zone_desc}{volume_msg}"

    # -- Zone resolution helpers (ported from MusicManager) --

    def _resolve_zones(self, zone_target: Optional[str]) -> List[Zone]:
        """Resolve a zone target to actual Zone objects."""
        if not zone_target:
            # Default to main_floor if available, else first zone
            if "main_floor" in self._zones:
                return [self._zones["main_floor"]]
            return [list(self._zones.values())[0]] if self._zones else []

        # Get zone IDs from NLP parser (handles groups)
        zone_ids = self._parser.get_zone_ids(zone_target)

        # Convert to Zone objects
        zones = []
        for zone_id in zone_ids:
            if zone_id in self._zones:
                zones.append(self._zones[zone_id])
        return zones

    def _describe_zones(self, zones: List[Zone]) -> str:
        """Create a human-readable description of zones."""
        if len(zones) == 1:
            return f"in the {zones[0].name}"
        elif len(zones) == 2:
            return f"in the {zones[0].name} and {zones[1].name}"
        else:
            zone_names = [z.name for z in zones]
            return f"in {', '.join(zone_names[:-1])}, and {zone_names[-1]}"

    def _get_music_help(self) -> str:
        zones = ", ".join(self._zones.keys()) if self._zones else "none configured"
        return (
            "Music Commands:\n"
            f"  Available zones: {zones}\n"
            "  play <song/artist> [in <zone>]\n"
            "  pause/stop [zone]\n"
            "  volume <0-100> [zone]\n"
            "  skip/next [zone]\n"
            "  what's playing [zone]"
        )

    async def on_stop(self):
        """Close the BluOS controller session."""
        await self._controller.close()

    def help_sections(self):
        return [HelpSection(
            title="Music Control (BluOS)",
            commands={
                "music": "Control BluOS speakers (play, pause, volume, etc.)",
            },
        )]
