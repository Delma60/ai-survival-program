import json

import pytest
from fastapi import HTTPException

import dashboard.server as dashboard
from engine.db import connect, initialize_database


def test_dashboard_summary_controls_and_approval_queue(tmp_path, monkeypatch):
    db_path = tmp_path / "world.db"
    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    initialize_database(db_path)
    dashboard.startup()

    assert dashboard.summary()["paused"] is False
    assert dashboard.agents() == []
    assert dashboard.generations() == []
    assert dashboard.events() == []
    assert dashboard.approvals() == []

    connection = connect(db_path)
    try:
        with connection:
            cursor = connection.execute(
                "INSERT INTO agents(generation, genome_json) VALUES (1, ?)",
                (json.dumps({"role": "<worker>"}),),
            )
            agent_id = cursor.lastrowid
            wallet = connection.execute(
                "INSERT INTO wallets(owner_agent_id, balance) VALUES (?, 1250)",
                (agent_id,),
            )
            connection.execute(
                "UPDATE agents SET wallet_id = ? WHERE id = ?",
                (wallet.lastrowid, agent_id),
            )
            approval = connection.execute(
                """INSERT INTO approvals(agent_id, kind, payload_json)
                   VALUES (?, 'post_content', ?)""",
                (agent_id, '{"text":"draft"}'),
            )
    finally:
        connection.close()

    assert dashboard.summary()["alive"] == 1
    assert dashboard.summary()["money"] == 12.5
    assert dashboard.agents()[0]["role"] == "<worker>"
    assert dashboard.approvals()[0]["id"] == approval.lastrowid
    assert dashboard.decide(approval.lastrowid, "approved") == {"ok": True}
    with pytest.raises(HTTPException) as conflict:
        dashboard.decide(approval.lastrowid, "rejected")
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as invalid:
        dashboard.decide(approval.lastrowid, "maybe")
    assert invalid.value.status_code == 400

    assert dashboard.pause() == {"paused": True}
    assert dashboard.summary()["paused"] is True
    assert dashboard.resume() == {"paused": False}
