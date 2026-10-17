from pathlib import Path

import yaml

from engine.db import connect, initialize_database
from engine.scheduler import run_generation


def make_config(tmp_path):
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "config.yaml").read_text(
            encoding="utf-8"
        )
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def test_generation_is_reproducible_and_within_survival_target(tmp_path):
    config_path = make_config(tmp_path)
    results = []
    for seed in range(20):
        summary = run_generation(
            config_path=config_path,
            db_path=tmp_path / "run-{}.db".format(seed),
            seed=seed,
        )
        assert summary["status"] == "complete"
        results.append(summary["alive_agents"] / summary["total_agents"])

    survival_rate = sum(results) / len(results)
    assert 0.35 <= survival_rate <= 0.65

    repeated = run_generation(
        config_path=config_path,
        db_path=tmp_path / "repeat.db",
        seed=8,
    )
    assert repeated["survival_rate"] == results[8]


def test_pause_flag_stops_before_agent_actions_and_resumes(tmp_path):
    config_path = make_config(tmp_path)
    db_path = tmp_path / "paused.db"
    initialize_database(db_path)
    connection = connect(db_path)
    try:
        with connection:
            connection.execute("UPDATE meta SET value = '1' WHERE key = 'paused'")

        paused = run_generation(config_path, db_path, seed=7)
        assert paused["status"] == "paused"
        assert connection.execute(
            "SELECT COUNT(*) AS n FROM events WHERE tool = 'scripted_work'"
        ).fetchone()["n"] == 0
        assert connection.execute(
            "SELECT value FROM meta WHERE key = 'day'"
        ).fetchone()["value"] == "1"

        with connection:
            connection.execute("UPDATE meta SET value = '0' WHERE key = 'paused'")
        resumed = run_generation(config_path, db_path, seed=7)
        assert resumed["status"] == "complete"
    finally:
        connection.close()
