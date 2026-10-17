import csv
from pathlib import Path

from engine.scheduler import run_generation
from scripts.export_events import export_daily_survival, export_events


def test_export_events_writes_csv(tmp_path):
    config = Path(__file__).resolve().parents[1] / "config.yaml"
    db_path = tmp_path / "world.db"
    run_generation(config, db_path, seed=1)

    out = tmp_path / "nested" / "events.csv"
    count = export_events(db_path, out)
    assert count > 0

    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == count
    assert {"id", "ts", "agent_id", "tool", "args_json", "result_json"} <= set(
        rows[0]
    )
    assert [int(row["id"]) for row in rows] == sorted(
        int(row["id"]) for row in rows
    )


def test_export_daily_survival_writes_per_day_curve(tmp_path):
    config = Path(__file__).resolve().parents[1] / "config.yaml"
    db_path = tmp_path / "world.db"
    summary = run_generation(config, db_path, seed=1)

    out = tmp_path / "nested" / "survival.csv"
    row_count = export_daily_survival(db_path, out)

    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert row_count == len(rows) == 30
    assert {"generation", "day", "alive", "total", "survival_rate"} <= set(
        rows[0]
    )
    assert rows[0]["day"] == "1"
    assert int(rows[-1]["alive"]) == summary["alive_agents"]
    assert int(rows[-1]["total"]) == summary["total_agents"]
    assert float(rows[-1]["survival_rate"]) == summary["survival_rate"]
