"""Rolling agent memory and lesson summaries."""

import sqlite3
from typing import List

DEFAULT_MAX_CHARS = 200


def add_lesson(
    connection: sqlite3.Connection,
    agent_id: int,
    day: int,
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> None:
    """Store a short note for an agent; empty notes are ignored."""
    cleaned = " ".join(str(text).split())[:max_chars]
    if not cleaned:
        return
    connection.execute(
        "INSERT INTO lessons(agent_id, day, text) VALUES (?, ?, ?)",
        (agent_id, day, cleaned),
    )


def recent_lessons(
    connection: sqlite3.Connection, agent_id: int, limit: int = 3
) -> List[str]:
    """Return the agent's latest notes, oldest first."""
    if limit <= 0:
        return []
    rows = connection.execute(
        """SELECT text FROM lessons WHERE agent_id = ?
           ORDER BY id DESC LIMIT ?""",
        (agent_id, limit),
    ).fetchall()
    return [row["text"] for row in reversed(rows)]
