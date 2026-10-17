"""Agent plan schema, validation, and safe parsing of LLM output."""

import json
from dataclasses import dataclass
from typing import Any, Dict

ALLOWED_ACTIONS = ("work", "end_day")
DEFAULT_MAX_NOTE_CHARS = 200


class PlanError(ValueError):
    """Raised when an agent's plan is malformed or not allowed right now."""


@dataclass(frozen=True)
class Plan:
    """A validated one-day plan."""

    action: str
    note: str = ""


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return text


def parse_plan(
    raw: str, state: Dict[str, Any], max_note_chars: int = DEFAULT_MAX_NOTE_CHARS
) -> Plan:
    """Parse and validate raw model text; raise PlanError with a clear reason."""
    if not isinstance(raw, str) or not raw.strip():
        raise PlanError("empty reply")
    if max_note_chars < 0:
        raise ValueError("max_note_chars must be non-negative")
    try:
        data: Any = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise PlanError("reply is not valid JSON: {}".format(exc.msg)) from exc
    if not isinstance(data, dict):
        raise PlanError("reply must be a JSON object")

    action = data.get("action")
    if action not in ALLOWED_ACTIONS:
        raise PlanError("action must be one of {}".format(list(ALLOWED_ACTIONS)))
    try:
        open_jobs = int(state.get("open_jobs", 0))
    except (TypeError, ValueError) as exc:
        raise PlanError("open_jobs must be an integer") from exc
    if action == "work" and open_jobs <= 0:
        raise PlanError("no open jobs today")

    note = data.get("note", "")
    if note is None:
        note = ""
    if not isinstance(note, str):
        raise PlanError("note must be a string")
    return Plan(action=action, note=note.strip()[:max_note_chars])
