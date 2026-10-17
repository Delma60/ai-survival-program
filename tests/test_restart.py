import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import HTTPException

import dashboard.server as dashboard
from agents.runner import main as runner_main
from engine.db import connect, initialize_database
from engine.restart import RestartRefused, reset_world
from engine.scheduler import run_generation

WIPED = (
    "agents",
    "wallets",
    "transactions",
    "listings",
    "orders",
    "jobs",
    "assets",
    "lessons",
    "approvals",
)


def make_config(tmp_path):
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "config.yaml").read_text(
            encoding="utf-8"
        )
    )
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def set_meta(db_path, **values):
    connection = connect(db_path)
    try:
        with connection:
            for key, value in values.items():
                connection.execute(
                    "UPDATE meta SET value = ? WHERE key = ?", (value, key)
                )
    finally:
        connection.close()


def test_reset_archives_wipes_and_allows_identical_fresh_run(tmp_path):
    config_path = make_config(tmp_path)
    db_path = tmp_path / "world.db"
    first = run_generation(config_path, db_path, seed=3)

    result = reset_world(db_path)

    archive = Path(result["archive"])
    assert archive.exists()
    archived = sqlite3.connect(archive)
    try:
        assert archived.execute("SELECT COUNT(*) FROM agents").fetchone()[0] > 0
    finally:
        archived.close()

    connection = connect(db_path)
    try:
        for table in WIPED:
            assert connection.execute(
                "SELECT COUNT(*) AS n FROM {}".format(table)
            ).fetchone()["n"] == 0
        events = connection.execute("SELECT tool FROM events").fetchall()
        assert [row["tool"] for row in events] == ["world_restart"]
        meta = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT * FROM meta")
        }
        assert meta == {
            "paused": "0",
            "generation": "1",
            "day": "1",
            "run_status": "idle",
            "run_seed": "0",
        }
    finally:
        connection.close()

    assert run_generation(config_path, db_path, seed=3) == first


def test_restart_refused_while_running_but_allowed_when_paused(tmp_path):
    db_path = tmp_path / "world.db"
    initialize_database(db_path)
    set_meta(db_path, run_status="running", paused="0")
    with pytest.raises(RestartRefused):
        reset_world(db_path)

    set_meta(db_path, paused="1")
    assert reset_world(db_path, archive=False)["ok"] is True


def test_runner_restart_starts_a_fresh_generation(tmp_path, capsys):
    db_path = tmp_path / "world.db"
    config_path = make_config(tmp_path)

    assert runner_main(
        [
            "--config",
            str(config_path),
            "--db",
            str(db_path),
            "--restart",
            "--mock-llm",
            "--seed",
            "5",
        ]
    ) == 0

    assert "World restarted. Archive:" in capsys.readouterr().out
    connection = connect(db_path)
    try:
        assert connection.execute(
            "SELECT value FROM meta WHERE key = 'generation'"
        ).fetchone()["value"] == "1"
        assert connection.execute(
            "SELECT value FROM meta WHERE key = 'run_status'"
        ).fetchone()["value"] == "complete"
    finally:
        connection.close()


def test_dashboard_restart_requires_header_and_maps_refusal(tmp_path, monkeypatch):
    db_path = tmp_path / "world.db"
    initialize_database(db_path)
    monkeypatch.setattr(dashboard, "DB_PATH", db_path)

    with pytest.raises(HTTPException) as missing:
        dashboard.restart(SimpleNamespace(headers={}))
    assert missing.value.status_code == 400

    set_meta(db_path, run_status="running", paused="0")
    with pytest.raises(HTTPException) as refused:
        dashboard.restart(SimpleNamespace(headers={"x-confirm": "restart"}))
    assert refused.value.status_code == 409

    set_meta(db_path, paused="1")
    assert dashboard.restart(
        SimpleNamespace(headers={"x-confirm": "restart"})
    )["ok"] is True
