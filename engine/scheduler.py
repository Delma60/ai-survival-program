"""Seeded generation runner, daily upkeep, and survival settlement."""

import json
import random
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

import yaml

from engine.db import DB_PATH, atomic, connect, initialize_database
from engine.jobs import generate_daily_jobs, log_event, work_one_job
from engine.ledger import BASIS_POINTS, credit, credits_to_minor, debit

PathLike = Union[str, Path]
DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(config_path: PathLike = DEFAULT_CONFIG) -> Dict[str, Any]:
    """Read and validate the project's YAML configuration."""
    with Path(config_path).open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a mapping")
    required = ("days_per_generation", "starting_balance", "daily_upkeep", "low_spec")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError("missing config keys: {}".format(", ".join(missing)))
    low_spec = config["low_spec"]
    if not isinstance(low_spec, dict) or "cohort_size" not in low_spec:
        raise ValueError("low_spec.cohort_size must be configured")
    if "jobs" not in config:
        raise ValueError("jobs settings are required in config.yaml")
    return config


def _meta(connection: sqlite3.Connection, key: str, default: Optional[str] = None) -> str:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        if default is None:
            raise KeyError("missing meta key: {}".format(key))
        return default
    return row["value"]


def _set_meta(connection: sqlite3.Connection, key: str, value: Union[str, int]) -> None:
    connection.execute(
        """INSERT INTO meta(key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, str(value)),
    )


def _record_event(
    connection: sqlite3.Connection,
    agent_id: Optional[int],
    tool: str,
    args: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    connection.execute(
        """INSERT INTO events(agent_id, tool, args_json, result_json)
           VALUES (?, ?, ?, ?)""",
        (
            agent_id,
            tool,
            json.dumps(args, sort_keys=True),
            json.dumps(result, sort_keys=True),
        ),
    )


def _create_cohort(
    connection: sqlite3.Connection,
    generation: int,
    cohort_size: int,
    starting_balance: int,
) -> None:
    for index in range(cohort_size):
        cursor = connection.execute(
            """INSERT INTO agents(generation, genome_json, born_day)
               VALUES (?, ?, 1)""",
            (
                generation,
                json.dumps({"role": "worker", "strategy": "accept available work"}),
            ),
        )
        agent_id = int(cursor.lastrowid)
        wallet_cursor = connection.execute(
            "INSERT INTO wallets(owner_agent_id, balance) VALUES (?, 0)", (agent_id,)
        )
        wallet_id = int(wallet_cursor.lastrowid)
        connection.execute(
            "UPDATE agents SET wallet_id = ? WHERE id = ?", (wallet_id, agent_id)
        )
        credit(
            connection,
            wallet_id,
            credits_to_minor(starting_balance),
            "starting_balance",
            ref_id="gen{}-agent{}".format(generation, index + 1),
        )
        _record_event(
            connection,
            agent_id,
            "agent_born",
            {"generation": generation},
            {"status": "alive", "starting_balance": starting_balance},
        )


def is_paused(connection: sqlite3.Connection) -> bool:
    """Return whether the dashboard kill switch is active."""
    return _meta(connection, "paused", "0") == "1"


def run_generation(
    config_path: PathLike = DEFAULT_CONFIG,
    db_path: PathLike = DB_PATH,
    seed: int = 0,
    decision_policy: Optional[Callable[[Dict[str, Any], random.Random], str]] = None,
) -> Dict[str, Any]:
    """Run or resume one scripted cohort and return its survival summary."""
    config = load_config(config_path)
    jobs_config = config["jobs"]
    royalty_config = config.get("royalty", {})
    royalty_rate_bp = int(round(float(royalty_config.get("rate", 0.10)) * BASIS_POINTS))
    grandparent_rate_bp = int(
        round(float(royalty_config.get("grandparent_rate", 0.01)) * BASIS_POINTS)
    )
    cohort_size = int(config["low_spec"]["cohort_size"])
    days = int(config["days_per_generation"])
    if cohort_size <= 0 or days <= 0:
        raise ValueError("cohort size and generation length must be positive")
    if int(config["starting_balance"]) < 0 or int(config["daily_upkeep"]) <= 0:
        raise ValueError("starting balance must be non-negative and upkeep positive")

    initialize_database(db_path)
    connection = connect(db_path)
    try:
        status = _meta(connection, "run_status", "idle")
        if status == "complete":
            generation = int(
                connection.execute(
                    "SELECT COALESCE(MAX(generation), 0) + 1 AS n FROM agents"
                ).fetchone()["n"]
            )
            with atomic(connection):
                _set_meta(connection, "generation", generation)
                _set_meta(connection, "day", 1)
                _set_meta(connection, "run_status", "idle")
                _set_meta(connection, "run_seed", seed)
                _create_cohort(
                    connection, generation, cohort_size, int(config["starting_balance"])
                )
        elif status == "idle":
            generation = int(_meta(connection, "generation", "1"))
            with atomic(connection):
                existing = connection.execute(
                    "SELECT COUNT(*) AS n FROM agents WHERE generation = ?",
                    (generation,),
                ).fetchone()["n"]
                if not existing:
                    _create_cohort(
                        connection,
                        generation,
                        cohort_size,
                        int(config["starting_balance"]),
                    )
                _set_meta(connection, "run_seed", seed)
        else:
            generation = int(_meta(connection, "generation", "1"))
            seed = int(_meta(connection, "run_seed", str(seed)))

        if is_paused(connection):
            return _generation_summary(connection, generation, "paused")

        for day in range(int(_meta(connection, "day", "1")), days + 1):
            with atomic(connection):
                _set_meta(connection, "run_status", "running")
                _set_meta(connection, "day", day)
                alive = connection.execute(
                    """SELECT id FROM agents
                       WHERE generation = ? AND status = 'alive'
                       ORDER BY id""",
                    (generation,),
                ).fetchall()
                generate_daily_jobs(
                    connection,
                    generation,
                    day,
                    int(jobs_config["jobs_per_day"]),
                    int(jobs_config["minimum_reward"]),
                    int(jobs_config["maximum_reward"]),
                    random.Random(seed + generation * 1_000_000 + day),
                )

            order = [int(agent["id"]) for agent in alive]
            random.Random(seed + generation * 2_000_000 + day).shuffle(order)
            for agent_id in order:
                if is_paused(connection):
                    return _generation_summary(connection, generation, "paused")
                with atomic(connection):
                    agent = connection.execute(
                        """SELECT status, last_action_day FROM agents WHERE id = ?""",
                        (agent_id,),
                    ).fetchone()
                    if agent is None or agent["status"] != "alive":
                        continue
                    if agent["last_action_day"] == day:
                        continue
                    agent_rng = random.Random(
                        seed + generation * 3_000_000 + day * 10_000 + agent_id
                    )
                    open_jobs = connection.execute(
                        """SELECT COUNT(*) AS n FROM jobs
                           WHERE generation = ? AND day = ? AND status = 'open'""",
                        (generation, day),
                    ).fetchone()["n"]
                    balance = connection.execute(
                        """SELECT w.balance FROM wallets w
                           JOIN agents a ON a.wallet_id = w.id WHERE a.id = ?""",
                        (agent_id,),
                    ).fetchone()["balance"]
                    state = {
                        "agent_id": agent_id,
                        "generation": generation,
                        "day": day,
                        "balance_minor": balance,
                        "open_jobs": int(open_jobs),
                    }
                    action = (
                        decision_policy(state, agent_rng)
                        if decision_policy is not None
                        else ("work" if open_jobs else "end_day")
                    )
                    if action not in ("work", "end_day"):
                        _record_event(
                            connection,
                            agent_id,
                            "action_rejected",
                            {"day": day, "action": str(action)},
                            {"error": "unsupported scripted action", "fallback": "end_day"},
                        )
                        action = "end_day"
                    if action == "work":
                        work_one_job(
                            connection,
                            agent_id,
                            generation,
                            day,
                            float(jobs_config["success_probability"]),
                            agent_rng,
                            royalty_rate_bp=royalty_rate_bp,
                            grandparent_rate_bp=grandparent_rate_bp,
                        )
                    else:
                        _record_event(
                            connection,
                            agent_id,
                            "agent_decision",
                            {"day": day},
                            {"action": "end_day"},
                        )
                    connection.execute(
                        "UPDATE agents SET last_action_day = ? WHERE id = ?",
                        (day, agent_id),
                    )

            if is_paused(connection):
                return _generation_summary(connection, generation, "paused")

            with atomic(connection):
                agents = connection.execute(
                    """SELECT id, wallet_id, status FROM agents
                       WHERE generation = ? AND status = 'alive'""",
                    (generation,),
                ).fetchall()
                for agent in agents:
                    debit(
                        connection,
                        agent["wallet_id"],
                        credits_to_minor(int(config["daily_upkeep"])),
                        "daily_upkeep",
                        allow_overdraft=True,
                        ref_id="gen{}-day{}-agent{}".format(
                            generation, day, agent["id"]
                        ),
                    )
                    balance = connection.execute(
                        "SELECT balance FROM wallets WHERE id = ?",
                        (agent["wallet_id"],),
                    ).fetchone()["balance"]
                    if balance < 0:
                        connection.execute(
                            "UPDATE agents SET status = 'dead', died_day = ? WHERE id = ?",
                            (day, agent["id"]),
                        )
                        _record_event(
                            connection,
                            agent["id"],
                            "settle_day",
                            {"day": day},
                            {"status": "dead", "balance_minor": balance},
                        )
                if day == days:
                    _set_meta(connection, "run_status", "complete")
                    _set_meta(connection, "day", days)
                else:
                    _set_meta(connection, "day", day + 1)

        return _generation_summary(connection, generation, _meta(connection, "run_status"))
    finally:
        connection.close()


def _generation_summary(
    connection: sqlite3.Connection, generation: int, status: str
) -> Dict[str, Any]:
    row = connection.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status = 'alive' THEN 1 ELSE 0 END) AS alive
           FROM agents WHERE generation = ?""",
        (generation,),
    ).fetchone()
    total = int(row["total"])
    alive = int(row["alive"] or 0)
    return {
        "generation": generation,
        "status": status,
        "total_agents": total,
        "alive_agents": alive,
        "survival_rate": alive / total if total else 0.0,
    }
