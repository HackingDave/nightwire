"""Docker sandbox for task execution."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import structlog

logger = structlog.get_logger()


@dataclass
class SandboxConfig:
    """Configuration for Docker sandbox."""
    enabled: bool = False
    image: str = "nightwire-sandbox:latest"
    network: bool = False
    memory_limit: str = "2g"
    cpu_limit: float = 2.0
    tmpfs_size: str = "256m"


def validate_docker_available() -> Tuple[bool, str]:
    """Check if Docker daemon is accessible.

    Returns:
        Tuple of (available, error_message). error_message is empty if available.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, (
                "Docker daemon is not running. "
                "Start Docker or disable sandbox in config/settings.yaml."
            )
        return True, ""
    except FileNotFoundError:
        return False, (
            "Docker is not installed. "
            "Install Docker or disable sandbox in config/settings.yaml."
        )
    except PermissionError:
        return False, (
            "Permission denied accessing Docker. "
            "Add your user to the docker group or disable sandbox in config/settings.yaml."
        )
    except subprocess.TimeoutExpired:
        return False, (
            "Docker daemon did not respond. "
            "Check Docker status or disable sandbox in config/settings.yaml."
        )


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
        "--user", "1000:1000",
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "--pids-limit", "256",
        f"--memory={config.memory_limit}",
        f"--cpus={config.cpu_limit}",
        "--tmpfs", f"/tmp:size={config.tmpfs_size}",
        "-v", f"{project_path}:{project_path}:rw",
        "-w", str(project_path),
    ]

    if not config.network:
        docker_cmd.append("--network=none")

    # Pass through essential env vars (not PATH — container has its own)
    docker_cmd.extend([
        "-e", "ANTHROPIC_API_KEY",
    ])

    docker_cmd.append(config.image)
    docker_cmd.extend(cmd)

    logger.info("sandbox_command_built", project=str(project_path), network=config.network)

    return docker_cmd
