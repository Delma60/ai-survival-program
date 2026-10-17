"""Export the audit log and daily survival curve to CSV.

Run from the project root:
    python scripts/export_events.py --db world-llm.db --out logs/events.csv
    python scripts/export_events.py --db world-llm.db --survival-out logs/survival.csv
"""
import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from engine.db import DB_PATH, connect


def export_events(db_path: Path, out_path: Path) -> int:
    """Write every event, oldest first, to a CSV file and return the row count."""
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """SELECT id, ts, agent_id, tool, args_json, result_json
               FROM events ORDER BY id"""
        ).fetchall()
    except sqlite3.Error as exc:
        print("FAIL: could not read events: {}".format(exc))
        return -1
    finally:
        connection.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "ts", "agent_id", "tool", "args_json", "result_json"])
        for row in rows:
            writer.writerow([row[key] for key in row.keys()])
    return len(rows)


def export_daily_survival(db_path: Path, out_path: Path) -> int:
    """Write generation/day survivor counts reconstructed from settlement events."""
    connection = connect(db_path)
    try:
        agents = connection.execute(
            "SELECT id, generation FROM agents ORDER BY generation, id"
        ).fetchall()
        settlements = connection.execute(
            """SELECT a.generation, e.args_json, e.result_json
               FROM events e JOIN agents a ON a.id = e.agent_id
               WHERE e.tool = 'settle_day'
               ORDER BY e.id"""
        ).fetchall()
    except sqlite3.Error as exc:
        print("FAIL: could not read daily survival data: {}".format(exc))
        return -1
    finally:
        connection.close()

    totals: Dict[int, int] = {}
    for agent in agents:
        generation = int(agent["generation"])
        totals[generation] = totals.get(generation, 0) + 1

    alive_by_day: Dict[Tuple[int, int], int] = {}
    for row in settlements:
        args = json.loads(row["args_json"])
        result = json.loads(row["result_json"])
        generation = int(row["generation"])
        day = int(args["day"])
        key = (generation, day)
        alive_by_day[key] = alive_by_day.get(key, 0) + (
            result.get("status") == "alive"
        )

    survival_rows: List[Tuple[int, int, int, int, float]] = []
    for generation, day in sorted(alive_by_day):
        alive = alive_by_day[(generation, day)]
        total = totals[generation]
        survival_rows.append(
            (generation, day, alive, total, alive / total if total else 0.0)
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["generation", "day", "alive", "total", "survival_rate"])
        writer.writerows(survival_rows)
    return len(survival_rows)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export the events log to CSV.")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--out", type=Path, default=Path("logs") / "events.csv")
    parser.add_argument(
        "--survival-out",
        type=Path,
        default=Path("logs") / "survival.csv",
        help="CSV path for per-generation, per-day survival counts",
    )
    args = parser.parse_args(argv)
    count = export_events(args.db, args.out)
    if count < 0:
        return 1
    survival_count = export_daily_survival(args.db, args.survival_out)
    if survival_count < 0:
        return 1
    print("Exported {} events to {}".format(count, args.out))
    print(
        "Exported {} daily survival rows to {}".format(
            survival_count, args.survival_out
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
