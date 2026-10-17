"""Daily faucet jobs and deterministic scripted-work execution."""

import json
import random
import sqlite3
from typing import Any, Dict, List, Optional

from engine.db import atomic
from engine.ledger import credit, credits_to_minor


def generate_daily_jobs(
    connection: sqlite3.Connection,
    generation: int,
    day: int,
    count: int,
    minimum_reward: int,
    maximum_reward: int,
    rng: random.Random,
) -> List[sqlite3.Row]:
    """Create a reproducible set of daily jobs, or return an existing set."""
    existing = connection.execute(
        """SELECT * FROM jobs WHERE generation = ? AND day = ?
           ORDER BY sequence""",
        (generation, day),
    ).fetchall()
    if existing:
        return list(existing)
    if count < 0 or minimum_reward <= 0 or maximum_reward < minimum_reward:
        raise ValueError("invalid daily job settings")

    with atomic(connection):
        for sequence in range(count):
            reward = rng.randint(minimum_reward, maximum_reward)
            connection.execute(
                """INSERT INTO jobs(
                       generation, day, sequence, source, description, reward,
                       verifier, deadline
                   ) VALUES (?, ?, ?, 'daily_faucet', ?, ?, 'scripted', ?)""",
                (
                    generation,
                    day,
                    sequence,
                    "Complete a small simulated task (day {}, task {}).".format(
                        day, sequence + 1
                    ),
                    reward,
                    day,
                ),
            )
            log_event(
                connection,
                None,
                "job_created",
                {"generation": generation, "day": day, "sequence": sequence},
                {"reward": reward, "source": "daily_faucet"},
            )
    return list(
        connection.execute(
            """SELECT * FROM jobs WHERE generation = ? AND day = ?
               ORDER BY sequence""",
            (generation, day),
        ).fetchall()
    )


def work_one_job(
    connection: sqlite3.Connection,
    agent_id: Optional[int],
    generation: int,
    day: int,
    success_probability: float,
    rng: random.Random,
    *,
    royalty_rate_bp: int = 1_000,
    grandparent_rate_bp: int = 100,
) -> Dict[str, Any]:
    """Claim the first open job and resolve its scripted verifier result."""
    if not 0 <= success_probability <= 1:
        raise ValueError("job success probability must be between 0 and 1")
    with atomic(connection):
        agent = connection.execute(
            """SELECT a.status, a.wallet_id FROM agents a
               WHERE a.id = ? AND a.generation = ?""",
            (agent_id, generation),
        ).fetchone()
        if agent is None or agent["status"] != "alive":
            raise ValueError("only a living agent can take a job")
        job = connection.execute(
            """SELECT id, reward FROM jobs
               WHERE generation = ? AND day = ? AND status = 'open'
               ORDER BY sequence LIMIT 1""",
            (generation, day),
        ).fetchone()
        if job is None:
            result = {"status": "no_job"}
            log_event(connection, agent_id, "scripted_work", {}, result)
            return result

        connection.execute(
            """UPDATE jobs SET status = 'assigned', assigned_agent_id = ?
               WHERE id = ? AND status = 'open'""",
            (agent_id, job["id"]),
        )
        succeeded = rng.random() < success_probability
        if succeeded:
            connection.execute(
                "UPDATE jobs SET status = 'completed' WHERE id = ?", (job["id"],)
            )
            credit(
                connection,
                agent["wallet_id"],
                credits_to_minor(job["reward"]),
                "job_reward",
                income=True,
                ref_id=str(job["id"]),
                royalty_rate_bp=royalty_rate_bp,
                grandparent_rate_bp=grandparent_rate_bp,
            )
            result = {"status": "completed", "reward": job["reward"]}
        else:
            connection.execute(
                "UPDATE jobs SET status = 'failed' WHERE id = ?", (job["id"],)
            )
            result = {"status": "failed", "reward": 0}

        log_event(
            connection,
            agent_id,
            "scripted_work",
            {"job_id": job["id"], "day": day},
            result,
        )
        return result


def log_event(
    connection: sqlite3.Connection,
    agent_id: int,
    tool: str,
    args: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    """Persist an agent action or engine decision as JSON."""
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
