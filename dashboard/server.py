"""FastAPI dashboard API for the local World Engine database."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from engine.db import DB_PATH, connect, initialize_database

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="AI Survival Program Dashboard")


@app.on_event("startup")
def startup() -> None:
    """Ensure the database schema exists before serving dashboard requests."""
    initialize_database(DB_PATH)


def query(
    sql: str, args: Tuple[Any, ...] = (), *, write: bool = False
) -> Iterable[Dict[str, Any]]:
    """Execute a parameterized query and close its short-lived connection."""
    connection = connect(DB_PATH)
    try:
        cursor = connection.execute(sql, args)
        if write:
            connection.commit()
            return [{"rowcount": cursor.rowcount}]
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail="Dashboard database error") from exc
    finally:
        connection.close()


def meta(key: str, default: str = "0") -> str:
    rows = query("SELECT value FROM meta WHERE key = ?", (key,))
    return str(rows[0]["value"]) if rows else default


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/summary")
def summary() -> Dict[str, Any]:
    totals = query(
        """SELECT
             (SELECT COUNT(*) FROM agents WHERE status = 'alive') AS alive,
             (SELECT COUNT(*) FROM agents WHERE status = 'dead') AS dead,
             (SELECT COALESCE(SUM(w.balance), 0) FROM wallets w
                JOIN agents a ON a.wallet_id = w.id WHERE a.status = 'alive') AS money_minor,
             (SELECT COALESCE(SUM(amount), 0) FROM transactions
                WHERE reason LIKE 'royalty%') AS royalties_minor,
             (SELECT COUNT(*) FROM approvals WHERE status = 'pending') AS pending"""
    )[0]
    return {
        "generation": meta("generation", "1"),
        "day": meta("day", "1"),
        "paused": meta("paused") == "1",
        "alive": totals["alive"],
        "dead": totals["dead"],
        "money": round(totals["money_minor"] / 100, 2),
        "royalties": round(totals["royalties_minor"] / 100, 2),
        "pending": totals["pending"],
    }


@app.get("/api/agents")
def agents() -> Iterable[Dict[str, Any]]:
    rows = query(
        """SELECT a.id, a.parent_id, a.generation, a.status, a.genome_json, w.balance
           FROM agents a JOIN wallets w ON w.id = a.wallet_id
           ORDER BY w.balance DESC LIMIT 200"""
    )
    for row in rows:
        try:
            genome = json.loads(row.pop("genome_json") or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500, detail="Agent genome JSON is invalid"
            ) from exc
        row["balance"] = round(row["balance"] / 100, 2)
        row["role"] = genome.get("role", "?") if isinstance(genome, dict) else "?"
    return rows


@app.get("/api/generations")
def generations() -> Iterable[Dict[str, Any]]:
    rows = query(
        """SELECT a.generation AS gen, COUNT(*) AS total,
                  SUM(CASE WHEN a.status = 'alive' THEN 1 ELSE 0 END) AS alive,
                  ROUND(AVG(w.balance) / 100.0, 2) AS avg_balance
           FROM agents a JOIN wallets w ON w.id = a.wallet_id
           GROUP BY a.generation ORDER BY a.generation"""
    )
    return rows


@app.get("/api/events")
def events() -> Iterable[Dict[str, Any]]:
    return query(
        """SELECT ts, agent_id, tool, result_json FROM events
           ORDER BY id DESC LIMIT 50"""
    )


@app.get("/api/approvals")
def approvals() -> Iterable[Dict[str, Any]]:
    return query(
        """SELECT id, ts, agent_id, kind, payload_json FROM approvals
           WHERE status = 'pending' ORDER BY id"""
    )


@app.post("/api/approvals/{approval_id}/{decision}")
def decide(approval_id: int, decision: str) -> Dict[str, bool]:
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Decision must be approved or rejected")
    changed = query(
        """UPDATE approvals SET status = ?
           WHERE id = ? AND status = 'pending'""",
        (decision, approval_id),
        write=True,
    )
    if changed and changed[0]["rowcount"] == 1:
        return {"ok": True}
    rows = query(
        "SELECT status FROM approvals WHERE id = ?", (approval_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Approval not found")
    if rows[0]["status"] != decision:
        raise HTTPException(status_code=409, detail="Approval is no longer pending")
    return {"ok": True}


@app.post("/api/pause")
def pause() -> Dict[str, bool]:
    query(
        """INSERT INTO meta(key, value) VALUES ('paused', '1')
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        write=True,
    )
    return {"paused": True}


@app.post("/api/resume")
def resume() -> Dict[str, bool]:
    query(
        """INSERT INTO meta(key, value) VALUES ('paused', '0')
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        write=True,
    )
    return {"paused": False}
