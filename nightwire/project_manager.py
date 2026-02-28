"""Project management for Signal Claude Bot."""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from .config import get_config
from .security import validate_project_path

logger = structlog.get_logger()


class ProjectManager:
    """Manages project selection and registration with per-phone scoping."""

    def __init__(self):
        self.config = get_config()
        # Per-phone state: phone_number -> (project_name, project_path)
        self._current_projects: Dict[str, Tuple[str, Path]] = {}

    def _can_access(self, project: dict, phone_number: Optional[str] = None) -> bool:
        """Check if a phone number can access a project.

        Projects without allowed_numbers (None) are accessible to everyone.
        Projects with an empty allowed_numbers list ([]) are accessible to nobody.
        """
        allowed = project.get("allowed_numbers")
        if allowed is None:
            return True
        if phone_number is None:
            return False
        return phone_number in allowed

    def get_current_project(self, phone_number: str) -> Optional[str]:
        """Get the current project name for a phone number."""
        entry = self._current_projects.get(phone_number)
        return entry[0] if entry else None

    def get_current_path(self, phone_number: str) -> Optional[Path]:
        """Get the current project path for a phone number."""
        entry = self._current_projects.get(phone_number)
        return entry[1] if entry else None

    def get_project_path(self, project_name: str) -> Optional[Path]:
        """Get the path for a project by name (case-insensitive)."""
        return self.config.get_project_path(project_name)

    def list_projects(self, phone_number: Optional[str] = None) -> str:
        """List registered projects visible to this phone number."""
        all_projects = self.config.get_project_list()
        projects = [p for p in all_projects if self._can_access(p, phone_number)]

        if not projects:
            # Also list directories in projects base path
            base = self.config.projects_base_path
            if base.exists():
                dirs = [d.name for d in base.iterdir() if d.is_dir()]
                if dirs:
                    return (
                        "No registered projects. Available directories:\n"
                        + "\n".join(f"  - {d}" for d in sorted(dirs))
                        + "\n\nUse /add <name> to register a project."
                    )
            return "No projects registered. Use /add <name> to register a project."

        current = self.get_current_project(phone_number) if phone_number else None
        lines = ["Registered projects:"]
        for p in projects:
            marker = " *" if p["name"] == current else ""
            desc = f" - {p.get('description', '')}" if p.get('description') else ""
            lines.append(f"  {p['name']}{marker}{desc}")

        if current:
            lines.append(f"\n* = currently selected")

        return "\n".join(lines)

    def select_project(self, name: str, phone_number: str) -> Tuple[bool, str]:
        """Select a project to work on."""
        name = name.strip().lower()

        # First check registered projects (case-insensitive)
        path = None
        matched_name = None
        matched_project = None
        for p in self.config.get_project_list():
            if p["name"].lower() == name:
                path = Path(p["path"])
                matched_name = p["name"]
                matched_project = p
                break

        if path is None:
            # Try as a direct path under projects base
            potential_path = self.config.projects_base_path / name
            if potential_path.exists() and potential_path.is_dir():
                # Auto-register it
                self.config.add_project(name, str(potential_path))
                path = potential_path
                matched_name = name
                matched_project = {"name": name, "path": str(potential_path)}
                logger.info("project_auto_registered", name=name, path=str(path))

        if path is None:
            return False, f"Project '{name}' not found. Use /projects to see available projects."

        # Check access control
        if matched_project and not self._can_access(matched_project, phone_number):
            logger.warning("project_access_denied", project=matched_name,
                           phone="..." + phone_number[-4:])
            return False, f"You don't have access to project '{matched_name}'."

        # Validate the path is allowed
        validated_path = validate_project_path(str(path))
        if validated_path is None:
            return False, f"Project path is not within the allowed directory."

        if not validated_path.exists():
            return False, f"Project directory does not exist: {validated_path}"

        self._current_projects[phone_number] = (matched_name, validated_path)

        logger.info("project_selected", name=matched_name, path=str(validated_path),
                     phone="..." + phone_number[-4:])

        return True, f"Selected: {matched_name}\nPath: {validated_path}"

    def add_project(self, name: str, path: str = None, description: str = "") -> Tuple[bool, str]:
        """Add a new project to the registry."""
        if path is None:
            # Assume it's a directory under the projects base path
            path = str(self.config.projects_base_path / name)

        # Validate the path
        validated_path = validate_project_path(path)
        if validated_path is None:
            return False, f"Path must be within {self.config.projects_base_path}"

        if not validated_path.exists():
            return False, f"Directory does not exist: {validated_path}"

        if not validated_path.is_dir():
            return False, f"Path is not a directory: {validated_path}"

        # Add to config
        if self.config.add_project(name, str(validated_path), description):
            logger.info("project_added", name=name, path=str(validated_path))
            return True, f"Added project: {name} ({validated_path})"
        else:
            return False, f"Project '{name}' already exists."

    def remove_project(self, name: str) -> Tuple[bool, str]:
        """Remove a project from the registry."""
        name_lower = name.strip().lower()

        # Find the actual registered name
        matched_name = None
        for p in self.config.get_project_list():
            if p["name"].lower() == name_lower:
                matched_name = p["name"]
                break

        if matched_name is None:
            return False, f"Project '{name}' not found. Use /projects to see registered projects."

        self.config.remove_project(matched_name)
        logger.info("project_removed", name=matched_name)

        # Clear selection for any user who had this project selected
        to_remove = [
            phone for phone, (proj, _) in self._current_projects.items()
            if proj and proj.lower() == name_lower
        ]
        for phone in to_remove:
            del self._current_projects[phone]

        return True, f"Removed project: {matched_name}"

    def create_project(self, name: str, phone_number: str, description: str = "") -> Tuple[bool, str]:
        """Create a new project directory and select it."""
        # Validate name with positive allowlist
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', name) or len(name) > 64:
            return False, "Invalid project name. Use alphanumeric characters, dots, hyphens, or underscores (max 64 chars)."

        # Create path under projects base
        project_path = self.config.projects_base_path / name

        if project_path.exists():
            return False, f"Directory already exists: {project_path}\nUse /select {name} to select it."

        try:
            # Create the directory
            project_path.mkdir(parents=True, exist_ok=False)
            logger.info("project_created", name=name, path=str(project_path))

            # Register it
            self.config.add_project(name, str(project_path), description)

            # Select it for this user
            self._current_projects[phone_number] = (name, project_path)

            return True, f"Created and selected new project: {name}\nPath: {project_path}\n\nReady for Claude! Send a message describing what to build."

        except Exception as e:
            logger.error("project_create_error", name=name, error=str(e))
            return False, f"Failed to create project: {str(e)}"

    def get_status(self, phone_number: str) -> str:
        """Get current project status for a phone number."""
        current_project = self.get_current_project(phone_number)
        current_path = self.get_current_path(phone_number)

        if current_project is None:
            return "No project selected. Use /select <project> to select one."

        status = [
            f"Current project: {current_project}",
            f"Path: {current_path}"
        ]

        # Add some project info
        if current_path and current_path.exists():
            # Check for common files
            markers = []
            if (current_path / ".git").exists():
                markers.append("git repo")
            if (current_path / "package.json").exists():
                markers.append("Node.js")
            if (current_path / "requirements.txt").exists():
                markers.append("Python")
            if (current_path / "Cargo.toml").exists():
                markers.append("Rust")
            if (current_path / "go.mod").exists():
                markers.append("Go")

            if markers:
                status.append(f"Type: {', '.join(markers)}")

            # Count files
            try:
                file_count = sum(1 for _ in current_path.rglob("*") if _.is_file())
                status.append(f"Files: ~{file_count}")
            except Exception:
                pass

        return "\n".join(status)


# Global instance
_manager: Optional[ProjectManager] = None


def get_project_manager() -> ProjectManager:
    """Get or create the global project manager instance."""
    global _manager
    if _manager is None:
        _manager = ProjectManager()
    return _manager
