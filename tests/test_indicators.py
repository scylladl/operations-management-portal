"""AC-07: the follow-up indicators match an independent query (validation/indicators_check.sql)."""
import datetime as dt
import pathlib

import pytest

from conftest import REGION, SETTINGS, row_ver
from portal import actions, db

CHECK_SQL = (pathlib.Path(__file__).resolve().parents[1] / "validation" / "indicators_check.sql").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def timeline(conn, people, circuits):
    """One request returned once and approved after five working days, and one waiting since before Christmas."""
    clocked = db.connect(SETTINGS)

    def at(when, fn, *args, **kwargs):
        db.set_clock(clocked, when)
        return fn(clocked, *args, **kwargs)

    circuit, tickets = next(circuits[REGION])
    a, rv = at(dt.datetime(2026, 1, 5, 9), actions.save_request, people["owner"], circuit, "EQUIP_REPLACE",
               "Port flapping.", "Stable port.", tickets[:1])
    at(dt.datetime(2026, 1, 5, 9), actions.transition, people["owner"], a, rv, "SUBMIT")
    at(dt.datetime(2026, 1, 7, 15), actions.transition, people["apr_x"], a, row_ver(conn, a), "RETURN", reason="Add tickets")
    at(dt.datetime(2026, 1, 8, 10), actions.transition, people["owner"], a, row_ver(conn, a), "RESUBMIT")
    at(dt.datetime(2026, 1, 12, 8), actions.transition, people["apr_x"], a, row_ver(conn, a), "APPROVE")

    circuit, tickets = next(circuits[REGION])
    b, rv = at(dt.datetime(2025, 12, 24, 12), actions.save_request, people["owner"], circuit, "REROUTE",
               "Fibre cut twice.", "No cuts.", tickets[:1])
    at(dt.datetime(2025, 12, 24, 12), actions.transition, people["owner"], b, rv, "SUBMIT")
    clocked.close()
    return a, b


def test_cycle_of_a_known_request(conn, timeline):
    returned_then_approved, waiting = timeline
    row = conn.execute("SELECT * FROM rpt.vw_ActionCycle WHERE ActionId = ?", returned_then_approved).fetchone()
    assert (row.Decision, row.TimesReturned, row.WorkingDaysToDecision) == ("Approved", 1, 5)
    row = conn.execute("SELECT * FROM rpt.vw_ActionCycle WHERE ActionId = ?", waiting).fetchone()
    # Wednesday 24 December to Monday 12 January: 13 working days (no holiday calendar)
    assert (row.Decision, row.WaitingWorkingDays, row.WaitingBucket) == (None, 13, "Over 5")


def test_indicators_match_the_independent_query(conn, people, timeline):
    result = actions.indicators(conn, people["adm"])
    check = db.result_sets(conn.execute(CHECK_SQL))
    for name, expected in zip(["waiting", "decisions", "completion", "by_status"], check):
        assert result[name] == expected, name


def test_indicators_are_limited_to_the_approvers_region(conn, people, timeline):
    regions = {r["RegionCode"] for r in actions.indicators(conn, people["apr_x"])["by_status"]}
    assert regions == {REGION}
    with pytest.raises(db.Forbidden):
        actions.indicators(conn, people["owner"])
