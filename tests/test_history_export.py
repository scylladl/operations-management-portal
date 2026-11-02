"""Q6 and R14 (historical actions) and Q7 (the export the NorthGrid loader reads)."""
import datetime as dt

import pytest

from conftest import OTHER_REGION, TODAY, row_ver, status
from portal import actions, db

STATUS_TEXT = {"Completed": "Completed", "InProgress": "In progress", "Cancelled": "Cancelled"}


def northgrid_rows(conn):
    return {tuple(r) for r in conn.execute(
        "SELECT ActionId, CircuitId, ActionTypeCode, StartDate, CompletionDate, Status FROM ng.ImprovementAction")}


def test_history_imported_as_is(conn, people):
    portal = {(r.ActionId, r.CircuitId, r.ActionTypeCode, r.StartDate, r.CompletionDate, STATUS_TEXT[r.Status])
              for r in conn.execute("SELECT * FROM app.Action WHERE IsHistorical = 1")}
    assert portal == northgrid_rows(conn)
    assert conn.execute("SELECT COUNT(*) FROM app.Action WHERE IsHistorical = 1 AND RequesterId IS NOT NULL").fetchval() == 0


def test_export_of_history_matches_northgrid_row_for_row(conn, people):
    changed = {r.ActionId for r in conn.execute(
        "SELECT DISTINCT ActionId FROM audit.ActionEvent WHERE ActionId < 10001 AND EventType <> 'IMPORT'")}
    exported = {tuple(r) for r in conn.execute("""
        SELECT ActionId, CircuitId, ActionTypeCode, StartDate, CompletionDate, Status
        FROM pub.vw_ImprovementActionExport WHERE ActionId < 10001""")}
    expected = {r for r in northgrid_rows(conn) if r[0] not in changed}
    assert {r for r in exported if r[0] not in changed} == expected
    assert len(expected) >= 557


@pytest.fixture
def historical_in_progress(conn, people):
    return conn.execute("""
        SELECT TOP (1) a.ActionId FROM app.Action AS a
        WHERE a.IsHistorical = 1 AND a.Status = 'InProgress' AND a.RegionCode = ?
          AND NOT EXISTS (SELECT 1 FROM audit.ActionEvent AS e WHERE e.ActionId = a.ActionId AND e.EventType <> 'IMPORT')
        ORDER BY a.ActionId""", OTHER_REGION).fetchval()


def test_field_coordinator_records_completion_of_historical_action(conn, people, historical_in_progress):
    action_id = historical_in_progress
    buttons = {t["TransitionCode"] for t in actions.get_action(conn, people["fld_y"], action_id)["transitions"]}
    assert buttons == {"COMPLETE"}
    assert actions.get_action(conn, people["apr_y"], action_id)["transitions"] == []
    with pytest.raises(db.Forbidden):
        actions.transition(conn, people["apr_y"], action_id, row_ver(conn, action_id), "CANCEL", reason="x")
    actions.transition(conn, people["fld_y"], action_id, row_ver(conn, action_id), "COMPLETE", event_date=TODAY)
    assert status(conn, action_id) == "Completed"
    assert actions.get_action(conn, people["apr_y"], action_id)["transitions"] == []


def test_historical_completed_cannot_be_reopened_or_verified(conn, people):
    action_id = conn.execute("""
        SELECT TOP (1) ActionId FROM app.Action WHERE IsHistorical = 1 AND Status = 'Completed' AND RegionCode = ?""",
                             OTHER_REGION).fetchval()
    for code in ("VERIFY", "REOPEN"):
        with pytest.raises(db.Forbidden):
            actions.transition(conn, people["adm"], action_id, row_ver(conn, action_id), code, reason="x")


def test_export_maps_portal_statuses(conn, build):
    cases = {
        "Draft": None, "Submitted": None, "Returned": None, "Rejected": None,
        "Approved": None,                  # no start date yet
        "InProgress": "In progress", "Completed": "Completed", "Verified": "Completed",
    }
    ids = {start: build.action_in(start) for start in cases}
    before_start = build.action_in("Approved")
    build.step(before_start, "CANCEL", "apr_x")
    after_start = build.action_in("InProgress")
    build.step(after_start, "CANCEL", "apr_x")
    exported = dict(conn.execute("SELECT ActionId, Status FROM pub.vw_ImprovementActionExport WHERE ActionId >= 10001"))
    for start, expected in cases.items():
        assert exported.get(ids[start]) == expected, start
    assert before_start not in exported
    assert exported[after_start] == "Cancelled"


def test_export_file_has_the_northgrid_layout(conn, tmp_path):
    from scripts import export_actions
    target = tmp_path / "improvement_actions.csv"
    export_actions.export(conn, target)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ActionId,CircuitId,ActionTypeCode,StartDate,CompletionDate,Status"
    first = lines[1].split(",")
    assert first[0] == "1" and dt.date.fromisoformat(first[3])
