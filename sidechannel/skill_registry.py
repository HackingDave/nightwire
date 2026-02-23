"""Skill auto-selection registry for Claude CLI prompts.

Discovers installed plugins/skills, matches them against prompts via
keyword scoring, and generates a compact catalog + recommendation
section to inject into every Claude CLI invocation.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class SkillInfo:
    """A discovered skill from a plugin."""

    name: str
    description: str
    plugin_name: str
    keywords: List[str] = field(default_factory=list)


@dataclass
class CommandInfo:
    """A discovered command from a plugin."""

    name: str
    description: str
    plugin_name: str
    keywords: List[str] = field(default_factory=list)


# Stop-words filtered out during keyword extraction
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "this", "that", "these",
    "those", "it", "its", "and", "but", "or", "nor", "not", "so", "yet",
    "both", "each", "all", "any", "few", "more", "most", "other", "some",
    "such", "no", "only", "same", "than", "too", "very", "just", "about",
    "use", "used", "using", "when", "which", "who", "how", "what", "where",
    "why", "if", "then", "also", "their", "them", "they", "your", "you",
})


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from a description string."""
    # Tokenize: split on non-alphanumeric (keeps hyphenated words)
    tokens = re.findall(r"[a-z][a-z0-9-]+", text.lower())
    # Filter stop words and very short tokens
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]


def _parse_frontmatter(content: str) -> Dict[str, str]:
    """Parse YAML-like frontmatter from a markdown file.

    Handles the simple key: value format used in SKILL.md / command .md files
    without requiring a full YAML parser.
    """
    result: Dict[str, str] = {}
    if not content.startswith("---"):
        return result

    end = content.find("---", 3)
    if end == -1:
        return result

    frontmatter = content[3:end].strip()
    for line in frontmatter.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                result[key] = value

    return result


class SkillRegistry:
    """Discovers plugin skills/commands and matches them to prompts."""

    def __init__(self, plugins_path: Optional[Path] = None, config: Optional[dict] = None):
        self._plugins_path = plugins_path
        self._config = config or {}
        self._skills: List[SkillInfo] = []
        self._commands: List[CommandInfo] = []

    @property
    def skills(self) -> List[SkillInfo]:
        return list(self._skills)

    @property
    def commands(self) -> List[CommandInfo]:
        return list(self._commands)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self) -> None:
        """Walk plugin directories and discover skills + commands."""
        if self._plugins_path is None or not self._plugins_path.is_dir():
            logger.warning("skill_registry_no_plugins_dir", path=str(self._plugins_path))
            return

        exclude_skills = set(self._config.get("exclude_skills", []))
        exclude_commands = set(self._config.get("exclude_commands", []))

        # Scan both plugins/ and external_plugins/ subdirectories
        for subdir_name in ("plugins", "external_plugins"):
            subdir = self._plugins_path / subdir_name
            if not subdir.is_dir():
                continue

            for plugin_dir in sorted(subdir.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                plugin_name = plugin_dir.name

                # Discover skills (skills/*/SKILL.md)
                skills_dir = plugin_dir / "skills"
                if skills_dir.is_dir():
                    for skill_dir in sorted(skills_dir.iterdir()):
                        skill_md = skill_dir / "SKILL.md"
                        if skill_md.is_file():
                            info = self._parse_skill(skill_md, plugin_name)
                            if info and info.name not in exclude_skills:
                                self._skills.append(info)

                # Discover commands (commands/*.md)
                commands_dir = plugin_dir / "commands"
                if commands_dir.is_dir():
                    for cmd_file in sorted(commands_dir.glob("*.md")):
                        info = self._parse_command(cmd_file, plugin_name)
                        if info and info.name not in exclude_commands:
                            self._commands.append(info)

        logger.info(
            "skill_registry_scan_complete",
            skills=len(self._skills),
            commands=len(self._commands),
        )

    def _parse_skill(self, path: Path, plugin_name: str) -> Optional[SkillInfo]:
        """Parse a SKILL.md file into a SkillInfo."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("skill_parse_error", path=str(path), error=str(exc))
            return None

        fm = _parse_frontmatter(content)
        name = fm.get("name", path.parent.name)
        description = fm.get("description", "")

        if not description:
            return None

        keywords = _extract_keywords(description)
        # Also add the skill name tokens as keywords
        keywords.extend(_extract_keywords(name.replace("-", " ")))
        # Deduplicate while preserving order
        seen = set()
        unique_kw = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_kw.append(kw)

        return SkillInfo(
            name=name,
            description=description,
            plugin_name=plugin_name,
            keywords=unique_kw,
        )

    def _parse_command(self, path: Path, plugin_name: str) -> Optional[CommandInfo]:
        """Parse a command .md file into a CommandInfo."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("command_parse_error", path=str(path), error=str(exc))
            return None

        fm = _parse_frontmatter(content)
        name = path.stem  # e.g. "commit.md" -> "commit"
        description = fm.get("description", "")

        if not description:
            return None

        keywords = _extract_keywords(description)
        keywords.extend(_extract_keywords(name.replace("-", " ")))
        seen = set()
        unique_kw = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_kw.append(kw)

        return CommandInfo(
            name=name,
            description=description,
            plugin_name=plugin_name,
            keywords=unique_kw,
        )

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match_skills(self, prompt: str) -> List[SkillInfo]:
        """Return skills matching the prompt, ordered by relevance score."""
        return self._match(prompt, self._skills)

    def match_commands(self, prompt: str) -> List[CommandInfo]:
        """Return commands matching the prompt, ordered by relevance score.

        Only returns commands from the suggest_commands whitelist.
        """
        suggest = set(self._config.get("suggest_commands", []))
        candidates = [c for c in self._commands if c.name in suggest]
        return self._match(prompt, candidates)

    def _match(self, prompt: str, items):
        """Score items against prompt tokens using keyword overlap."""
        prompt_lower = prompt.lower()
        prompt_tokens = set(re.findall(r"[a-z][a-z0-9-]+", prompt_lower))

        scored = []
        for item in items:
            score = 0
            for kw in item.keywords:
                # Exact token match
                if kw in prompt_tokens:
                    score += 1
                # Phrase / substring match (bonus for multi-word keywords)
                elif kw in prompt_lower:
                    score += 2
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    # ------------------------------------------------------------------
    # Prompt section generation
    # ------------------------------------------------------------------

    def build_prompt_section(self, prompt: str) -> Optional[str]:
        """Build the skill catalog + recommendation section for injection.

        Returns None if registry is empty or disabled.
        """
        if not self._skills and not self._commands:
            return None

        parts: List[str] = []

        # 1. Always include compact catalog
        catalog_lines = ["## Available Skills & Commands", ""]
        catalog_lines.append("**Skills** (invoke via the Skill tool):")
        for s in self._skills:
            # Truncate long descriptions to keep token count down
            short_desc = s.description[:120]
            if len(s.description) > 120:
                short_desc += "..."
            catalog_lines.append(f"- `{s.name}` ({s.plugin_name}): {short_desc}")

        suggest_commands = set(self._config.get("suggest_commands", []))
        suggested_cmds = [c for c in self._commands if c.name in suggest_commands]
        if suggested_cmds:
            catalog_lines.append("")
            catalog_lines.append("**Commands** (invoke via the Skill tool as `/<command>`):")
            for c in suggested_cmds:
                short_desc = c.description[:120]
                if len(c.description) > 120:
                    short_desc += "..."
                catalog_lines.append(f"- `/{c.name}`: {short_desc}")

        parts.append("\n".join(catalog_lines))

        # 2. If strong skill match (threshold: 2+ keyword hits), add recommendation
        matched_skills = self.match_skills(prompt)
        if matched_skills:
            top = matched_skills[0]
            # Re-score to check threshold
            prompt_lower = prompt.lower()
            prompt_tokens = set(re.findall(r"[a-z][a-z0-9-]+", prompt_lower))
            score = sum(1 for kw in top.keywords if kw in prompt_tokens) + \
                    sum(2 for kw in top.keywords if kw not in prompt_tokens and kw in prompt_lower)
            if score >= 2:
                parts.append(
                    f"\n**Skill Recommendation:** You SHOULD invoke the Skill tool with "
                    f"skill name `{top.name}` — it is designed for this kind of task."
                )

        # 3. If command match, suggest post-task commands
        matched_cmds = self.match_commands(prompt)
        if matched_cmds:
            cmd_names = ", ".join(f"`/{c.name}`" for c in matched_cmds[:3])
            parts.append(
                f"\n**Post-task commands to consider:** {cmd_names}"
            )

        return "\n\n".join(parts)
