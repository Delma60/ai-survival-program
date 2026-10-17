"""Archive and reset the world database."""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

from engine.db import DB_PATH, atomic, connect, initialize_database

PathLike = Union[str, Path]

WIPE_ORDER = (
    "transactions",
    "orders",
    "listings",
    "jobs",
    "assets",
    "lessons",
    "events",
    "approvals",
    "wallets",
    "agents",
)
META_DEFAULTS = {
    "paused": "0",
    "generation": "1",
    "day": "1",
    "run_status": "idle",
    "run_seed": "0",
}


class RestartRefused(RuntimeError):
    """Raised when a restart would interrupt a live simulation."""


def _meta(connection: sqlite3.Connection, key: str, default: str) -> str:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _assert_restartable(connection: sqlite3.Connection) -> None:
    paused = _meta(connection, "paused", "0") == "1"
    status = _meta(connection, "run_status", "idle")
    if status == "running" and not paused:
        raise RestartRefused(
            "simulation is running: pause it and wait for the runner to stop first"
        )


def archive_database(
    db_path: PathLike, archive_dir: Optional[PathLike] = None
) -> Path:
    """Copy a consistent database snapshot using SQLite's online backup API."""
    directory = (
        Path(archive_dir) if archive_dir else Path(db_path).parent / "logs" / "archive"
    )
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = directory / "world-{}.db".format(stamp)
    source = connect(db_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target


def reset_world(
    db_path: PathLike = DB_PATH,
    *,
    archive: bool = True,
    archive_dir: Optional[PathLike] = None,
) -> Dict[str, Any]:
    """Archive and wipe the simulation, returning it to generation 1, day 1."""
    initialize_database(db_path)

    connection = connect(db_path)
    try:
        _assert_restartable(connection)
    finally:
        connection.close()

    archived = archive_database(db_path, archive_dir) if archive else None

    connection = connect(db_path)
    try:
        with atomic(connection):
            _assert_restartable(connection)
            connection.execute("UPDATE agents SET wallet_id = NULL, parent_id = NULL")
            for table in WIPE_ORDER:
                connection.execute("DELETE FROM {}".format(table))
            connection.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ({})".format(
                    ",".join("?" for _ in WIPE_ORDER)
                ),
                WIPE_ORDER,
            )
            connection.execute("DELETE FROM meta")
            connection.executemany(
                "INSERT INTO meta(key, value) VALUES (?, ?)", META_DEFAULTS.items()
            )
            connection.execute(
                """INSERT INTO events(agent_id, tool, args_json, result_json)
                   VALUES (NULL, 'world_restart', '{}', ?)""",
                (json.dumps({"archive": str(archived) if archived else None}),),
            )
    finally:
        connection.close()
    return {"ok": True, "archive": str(archived) if archived else None}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Archive and reset the world.")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--no-archive", action="store_true", help="skip the backup")
    parser.add_argument("--yes", action="store_true", help="skip confirmation")
    args = parser.parse_args(argv)

    if not args.yes and input("Type RESTART to confirm: ").strip() != "RESTART":
        print("Cancelled.")
        return 1
    try:
        result = reset_world(args.db, archive=not args.no_archive)
    except RestartRefused as exc:
        print("Refused: {}".format(exc))
        return 1
    print("World restarted. Archive: {}".format(result["archive"] or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
