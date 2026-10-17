import pytest

from engine.tools import PlanError, parse_plan

STATE = {"open_jobs": 2}


def test_valid_plan_and_fenced_json():
    assert parse_plan('{"action": "work", "note": "go"}', STATE).action == "work"
    fenced = '```json\n{"action": "end_day"}\n```'
    assert parse_plan(fenced, STATE).action == "end_day"


def test_note_is_truncated():
    plan = parse_plan('{"action": "end_day", "note": "%s"}' % ("x" * 500), STATE, 50)
    assert len(plan.note) == 50


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "[1, 2]", '{"action": "steal"}', '{"action": "work", "note": 5}'],
)
def test_invalid_plans_raise(raw):
    with pytest.raises(PlanError):
        parse_plan(raw, STATE)


def test_work_rejected_when_no_open_jobs():
    with pytest.raises(PlanError, match="no open jobs"):
        parse_plan('{"action": "work"}', {"open_jobs": 0})
