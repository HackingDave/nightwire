"""PRD (Product Requirements Document) builder - JSON parsing and PRD creation from Claude output."""

import json
import re
from typing import Optional

import structlog

logger = structlog.get_logger()


def clean_json_string(json_str: str) -> str:
    """Clean common JSON issues from LLM output."""
    # Remove markdown code blocks if present
    json_str = re.sub(r'^```(?:json)?\s*', '', json_str.strip())
    json_str = re.sub(r'\s*```$', '', json_str)

    # Replace smart quotes with regular quotes
    json_str = json_str.replace('\u201c', '"').replace('\u201d', '"')
    json_str = json_str.replace('\u2018', "'").replace('\u2019', "'")

    # Remove single-line comments (// ...) that LLMs sometimes add
    # Process line by line, only remove comments outside of strings
    cleaned_lines = []
    for line in json_str.split('\n'):
        in_str = False
        result_chars = []
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '\\' and in_str and i + 1 < len(line):
                result_chars.append(ch)
                result_chars.append(line[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = not in_str
            if ch == '/' and not in_str and i + 1 < len(line) and line[i + 1] == '/':
                break  # Rest of line is comment
            result_chars.append(ch)
            i += 1
        cleaned_lines.append(''.join(result_chars))
    json_str = '\n'.join(cleaned_lines)

    # Remove trailing commas before } or ]
    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)

    # Remove control characters first (before string processing)
    json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', ' ', json_str)

    # Fix unescaped backslashes BEFORE escaping newlines to avoid double-escaping
    json_str = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', json_str)

    # Fix unescaped newlines inside strings
    def escape_newlines_in_strings(match):
        return match.group(0).replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

    json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', escape_newlines_in_strings, json_str)

    return json_str


def extract_balanced_json(text: str) -> Optional[str]:
    """Extract the first balanced top-level JSON object from text using brace matching."""
    start = text.find('{')
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == '\\' and in_string:
            escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    # If unbalanced, fall back to returning from first { to last }
    end = text.rfind('}')
    if end > start:
        return text[start:end + 1]

    return None


def is_complex_task(task_description: str) -> bool:
    """Detect if a task is complex and should use the autonomous system.

    Criteria for complex tasks:
    - Multiple sentences (3+)
    - Contains keywords suggesting breakdown needed
    - Very long description (500+ chars)
    - Mentions testing/deployment
    """
    desc_lower = task_description.lower()

    complexity_keywords = [
        "break into tasks", "break these into", "systematically",
        "multiple", "several", "also", "additionally", "as well",
        "once completed", "after that", "then deploy", "run tests",
        "push to production", "deploy to", "refactor", "overhaul",
        "redesign", "enhance the overall", "make it look",
    ]

    keyword_matches = sum(1 for kw in complexity_keywords if kw in desc_lower)
    sentence_count = task_description.count('.') + task_description.count('!') + task_description.count('?')
    has_multiple_also = desc_lower.count(' also ') >= 2

    if keyword_matches >= 3:
        return True
    if sentence_count >= 5 and len(task_description) > 300:
        return True
    if len(task_description) > 800:
        return True
    if has_multiple_also:
        return True
    if "break" in desc_lower and "task" in desc_lower:
        return True

    return False


async def parse_prd_json(response: str, runner, update_step) -> dict:
    """Parse PRD JSON from Claude's response with robust error handling and retry.

    Args:
        response: Raw Claude response text
        runner: ClaudeRunner instance for retry requests
        update_step: Async callback to update progress step

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If JSON cannot be parsed after all attempts
    """
    from .exceptions import ClaudeRunnerError

    json_str = extract_balanced_json(response)
    if not json_str:
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            raise ValueError("Response does not contain valid JSON structure")
        json_str = json_match.group()

    # Try parsing with increasingly aggressive cleanup
    parse_attempts = [
        ("basic", lambda s: s),
        ("cleaned", clean_json_string),
        ("re-extracted", lambda s: extract_balanced_json(clean_json_string(s)) or clean_json_string(s)),
    ]

    last_error = None
    for attempt_name, cleaner in parse_attempts:
        try:
            cleaned = cleaner(json_str)
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning("json_parse_attempt_failed", attempt=attempt_name, error=str(e)[:100])
            continue

    # All local attempts failed - try asking Claude to fix the JSON
    await update_step("Step 3/5: Fixing malformed JSON (retry)...")

    max_preview = 12000
    json_preview = json_str
    truncated_note = ""
    if len(json_str) > max_preview:
        truncate_at = max_preview
        for candidate in range(max_preview, max(max_preview - 500, 0), -1):
            if json_str[candidate] in ('}', ']', ','):
                truncate_at = candidate + 1
                break
        json_preview = json_str[:truncate_at]
        truncated_note = f"\n\n[TRUNCATED at {truncate_at} of {len(json_str)} chars. Complete the JSON structure with proper closing braces/brackets.]"

    fix_prompt = f"""The following JSON has a syntax error. Fix ONLY the JSON syntax and return valid JSON.
Do not add any explanation, just return the corrected JSON.

Error: {str(last_error)[:200]}

JSON to fix:
{json_preview}{truncated_note}"""

    try:
        success, fix_response = await runner.run_claude(fix_prompt, timeout=60)
        if success:
            fixed_str = extract_balanced_json(fix_response)
            if not fixed_str:
                fixed_match = re.search(r'\{[\s\S]*\}', fix_response)
                if fixed_match:
                    fixed_str = fixed_match.group()
            if fixed_str:
                fixed_json = clean_json_string(fixed_str)
                return json.loads(fixed_json)
    except (json.JSONDecodeError, ClaudeRunnerError) as e:
        logger.warning("json_fix_retry_failed", error=str(e), error_type=type(e).__name__)
    except Exception as e:
        logger.warning("json_fix_retry_unexpected_error", error=str(e), error_type=type(e).__name__)

    # If we still can't parse, raise with helpful context
    error_pos = last_error.pos if last_error else 0
    context_start = max(0, error_pos - 50)
    context_end = min(len(json_str), error_pos + 50)
    context = json_str[context_start:context_end]

    raise ValueError(
        f"Failed to parse JSON after multiple attempts. "
        f"Error near: ...{context}..."
    )
