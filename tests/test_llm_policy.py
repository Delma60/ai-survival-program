import random
from pathlib import Path

import yaml

from agents.llm_client import LLMError
from agents.policy import make_llm_policy
from engine.db import connect
from engine.scheduler import run_generation

STATE = {
    "day": 1,
    "days_total": 30,
    "balance_minor": 5000,
    "daily_upkeep": 5,
    "open_jobs": 1,
}


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, system, user):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_retry_then_success():
    policy = make_llm_policy(FakeClient(["garbage", '{"action": "work", "note": "ok"}']))
    assert policy(STATE, random.Random(0)) == {"action": "work", "note": "ok"}


def test_fallback_to_end_day_after_failures():
    client = FakeClient([LLMError("down"), "still bad"])
    result = make_llm_policy(client, retries=1)(STATE, random.Random(0))
    assert result["action"] == "end_day"
    assert result["error"]


def test_scheduler_logs_rejections_and_stores_notes(tmp_path):
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8")
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    db_path = tmp_path / "llm.db"

    def policy(state, rng):
        if state["agent_id"] % 2:
            return {"action": "work", "note": "keep working"}
        return {"action": "end_day", "note": "", "error": "bad reply"}

    summary = run_generation(config_path, db_path, 1, policy)
    assert summary["status"] == "complete"
    connection = connect(db_path)
    try:
        rejected = connection.execute(
            "SELECT COUNT(*) AS n FROM events WHERE tool = 'action_rejected'"
        ).fetchone()["n"]
        actions = connection.execute(
            """SELECT COUNT(*) AS n FROM events
               WHERE tool IN ('scripted_work', 'agent_decision')"""
        ).fetchone()["n"]
        lessons = connection.execute("SELECT COUNT(*) AS n FROM lessons").fetchone()["n"]
        assert rejected > 0
        assert actions > 0
        assert lessons > 0
    finally:
        connection.close()
