"""Docker sandbox for task execution."""

from dataclasses import dataclass
from pathlib import Path
from typing import List

import structlog

logger = structlog.get_logger()


@dataclass
class SandboxConfig:
    """Configuration for Docker sandbox."""
    enabled: bool = False
    image: str = "python:3.11-slim"
    network: bool = False
    memory_limit: str = "2g"
    cpu_limit: float = 2.0
    tmpfs_size: str = "256m"


def build_sandbox_command(
    cmd: List[str],
    project_path: Path,
    config: SandboxConfig,
) -> List[str]:
    """Wrap a command in a Docker sandbox if enabled.

    Mounts only project_path read-write, /tmp as tmpfs, no network by default.
    Returns original command unchanged if sandbox is disabled.
    """
    if not config.enabled:
        return cmd

    docker_cmd = [
        "docker", "run",
        "--rm",
        "--interactive",
        f"--memory={config.memory_limit}",
        f"--cpus={config.cpu_limit}",
        "--tmpfs", f"/tmp:size={config.tmpfs_size}",
        "-v", f"{project_path}:{project_path}:rw",
        "-w", str(project_path),
    ]

    if not config.network:
        docker_cmd.append("--network=none")

    # Pass through essential env vars
    docker_cmd.extend([
        "-e", "HOME",
        "-e", "PATH",
        "-e", "ANTHROPIC_API_KEY",
    ])

    docker_cmd.append(config.image)
    docker_cmd.extend(cmd)

    logger.info("sandbox_command_built", project=str(project_path), network=config.network)

    return docker_cmd
