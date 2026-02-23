"""BluOS REST API controller for multi-room speaker control."""

import asyncio
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import aiohttp
import structlog

from .models import Zone

logger = structlog.get_logger()


class BluOSController:
    """Controls BluOS speakers via REST API on port 11000."""

    def __init__(self, zones: Dict[str, Zone], timeout: int = 10):
        """
        Initialize BluOS controller.

        Args:
            zones: Dictionary of zone_id -> Zone objects
            timeout: HTTP request timeout in seconds
        """
        self.zones = zones
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _request(
        self,
        zone: Zone,
        endpoint: str,
        params: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Make a request to a BluOS zone.

        Args:
            zone: The zone to send request to
            endpoint: API endpoint (e.g., "/Status")
            params: Optional query parameters

        Returns:
            Response text or None on error
        """
        url = f"{zone.base_url}{endpoint}"
        try:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(timeout=self.timeout)
            async with self._session.get(url, params=params) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    else:
                        logger.warning(
                            "bluos_request_failed",
                            zone=zone.id,
                            endpoint=endpoint,
                            status=resp.status
                        )
                        return None
        except asyncio.TimeoutError:
            logger.error("bluos_timeout", zone=zone.id, endpoint=endpoint)
            return None
        except aiohttp.ClientError as e:
            logger.error("bluos_client_error", zone=zone.id, error=str(e))
            return None
        except Exception as e:
            logger.error("bluos_error", zone=zone.id, error=str(e))
            return None

    def _parse_xml(self, xml_str: str) -> Optional[ET.Element]:
        """Parse XML response, rejecting DTD/entity declarations."""
        if "<!DOCTYPE" in xml_str or "<!ENTITY" in xml_str:
            logger.error("bluos_xml_rejected_dtd", reason="DTD or ENTITY declaration found")
            return None
        try:
            return ET.fromstring(xml_str)
        except ET.ParseError as e:
            logger.error("bluos_xml_parse_error", error=str(e))
            return None

    async def get_status(self, zone: Zone) -> Optional[Dict]:
        """
        Get current status of a zone.

        Returns:
            Dictionary with status info or None on error
        """
        response = await self._request(zone, "/Status")
        if not response:
            return None

        root = self._parse_xml(response)
        if root is None:
            return None

        # Extract key status fields
        status = {
            "state": root.findtext("state", ""),
            "volume": int(root.findtext("volume", "0")),
            "mute": root.findtext("mute", "0") == "1",
            "title1": root.findtext("title1", ""),
            "title2": root.findtext("title2", ""),
            "title3": root.findtext("title3", ""),
            "artist": root.findtext("artist", ""),
            "album": root.findtext("album", ""),
            "service": root.findtext("service", ""),
            "shuffle": root.findtext("shuffle", "0") == "1",
            "repeat": root.findtext("repeat", "0"),
        }

        # Check if this zone is a group leader
        slaves = root.findall("slave")
        if slaves:
            status["group_followers"] = [s.text for s in slaves if s.text]

        return status

    async def set_volume(self, zone: Zone, level: int) -> bool:
        """
        Set volume for a zone.

        Args:
            zone: The zone to set volume on
            level: Volume level 0-100

        Returns:
            True if successful
        """
        level = max(0, min(100, level))
        response = await self._request(zone, "/Volume", {"level": str(level)})
        if response is not None:
            logger.info("bluos_volume_set", zone=zone.id, level=level)
            return True
        return False

    async def play(self, zone: Zone) -> bool:
        """Resume playback on a zone."""
        response = await self._request(zone, "/Play")
        if response is not None:
            logger.info("bluos_play", zone=zone.id)
            return True
        return False

    async def pause(self, zone: Zone) -> bool:
        """Pause playback on a zone."""
        response = await self._request(zone, "/Pause")
        if response is not None:
            logger.info("bluos_pause", zone=zone.id)
            return True
        return False

    async def stop(self, zone: Zone) -> bool:
        """Stop playback on a zone."""
        response = await self._request(zone, "/Stop")
        if response is not None:
            logger.info("bluos_stop", zone=zone.id)
            return True
        return False

    async def skip(self, zone: Zone) -> bool:
        """Skip to next track."""
        response = await self._request(zone, "/Skip")
        if response is not None:
            logger.info("bluos_skip", zone=zone.id)
            return True
        return False

    async def back(self, zone: Zone) -> bool:
        """Go to previous track."""
        response = await self._request(zone, "/Back")
        if response is not None:
            logger.info("bluos_back", zone=zone.id)
            return True
        return False

    async def create_group(self, leader: Zone, followers: List[Zone]) -> bool:
        """
        Create a speaker group with leader and followers.

        BluOS groups work by adding "slaves" to a "master" speaker.
        The master receives the audio stream and distributes it.

        Args:
            leader: The zone that will be the group leader
            followers: List of zones to add to the group

        Returns:
            True if all followers were added successfully
        """
        # First dissolve any existing group
        await self.dissolve_group(leader)

        success = True
        for follower in followers:
            # AddSlave takes IP and port of the follower
            response = await self._request(
                leader,
                "/AddSlave",
                {"slave": follower.ip, "port": str(follower.port)}
            )
            if response is None:
                logger.error(
                    "bluos_add_slave_failed",
                    leader=leader.id,
                    follower=follower.id
                )
                success = False
            else:
                logger.info(
                    "bluos_slave_added",
                    leader=leader.id,
                    follower=follower.id
                )

        return success

    async def dissolve_group(self, leader: Zone) -> bool:
        """
        Dissolve a speaker group.

        Removes all slaves from the leader.

        Args:
            leader: The group leader zone

        Returns:
            True if successful
        """
        # Get current status to find slaves
        status = await self.get_status(leader)
        if not status:
            return False

        followers = status.get("group_followers", [])
        if not followers:
            return True  # No group to dissolve

        # Remove each slave
        for follower_ip in followers:
            response = await self._request(
                leader,
                "/RemoveSlave",
                {"slave": follower_ip}
            )
            if response is None:
                logger.warning(
                    "bluos_remove_slave_failed",
                    leader=leader.id,
                    follower_ip=follower_ip
                )

        logger.info("bluos_group_dissolved", leader=leader.id)
        return True

    async def set_group_volumes(
        self,
        zones: List[Zone],
        volume: int
    ) -> Dict[str, bool]:
        """
        Set volume on multiple zones concurrently.

        Args:
            zones: List of zones to set volume on
            volume: Volume level 0-100

        Returns:
            Dictionary of zone_id -> success status
        """
        tasks = [self.set_volume(zone, volume) for zone in zones]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            zones[i].id: (
                result is True if not isinstance(result, Exception) else False
            )
            for i, result in enumerate(results)
        }

    async def close(self) -> None:
        """Close the shared HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def get_zone(self, zone_id: str) -> Optional[Zone]:
        """Get a zone by ID."""
        return self.zones.get(zone_id)

    def get_zones(self, zone_ids: List[str]) -> List[Zone]:
        """Get multiple zones by ID."""
        return [
            self.zones[zid]
            for zid in zone_ids
            if zid in self.zones
        ]
