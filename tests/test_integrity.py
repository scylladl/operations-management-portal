"""AC-03 (audit in the same transaction), AC-04 (concurrent decisions) and the audit trail itself (R9)."""
import threading

import pyodbc
import pytest

from conftest import NOW, open_connection, row_ver, status
from portal import actions, db


def audit_count(conn, action_id):
    return conn.execute("SELECT COUNT(*) FROM audit.ActionEvent WHERE ActionId = ?", action_id).fetchval()


def test_audit_records_who_when_before_and_after(conn, people, build):
    action_id = build.action_in("Submitted")
    build.step(action_id, "APPROVE", "apr_x")
    row = conn.execute("""
        SELECT ActorUserId, EventAt, OldValue, NewValue FROM audit.ActionEvent
        WHERE ActionId = ? AND EventType = 'APPROVE' AND FieldName = 'Status'""", action_id).fetchone()
    assert (row.ActorUserId, row.EventAt, row.OldValue, row.NewValue) == (people["apr_x"], NOW, "Submitted", "Approved")


def test_failed_audit_write_leaves_no_change(conn, build):
    action_id = build.action_in("Submitted")
    before = (row_ver(conn, action_id), audit_count(conn, action_id))
    conn.execute("""
        CREATE TRIGGER audit.trg_TestFailure ON audit.ActionEvent AFTER INSERT
        AS THROW 50999, 'Simulated audit failure.', 1;""")
    try:
        with pytest.raises(pyodbc.Error, match="Simulated audit failure"):
            build.step(action_id, "APPROVE", "apr_x")
    finally:
        conn.execute("DROP TRIGGER audit.trg_TestFailure")
    assert status(conn, action_id) == "Submitted"
    assert (row_ver(conn, action_id), audit_count(conn, action_id)) == before


def test_changes_outside_the_procedures_are_refused(conn, build):
    action_id = build.action_in("Submitted")
    with pytest.raises(pyodbc.Error, match="only through the portal procedures"):
        conn.execute("UPDATE app.Action SET Status = 'Approved' WHERE ActionId = ?", action_id)
    assert status(conn, action_id) == "Submitted"


@pytest.mark.parametrize("statement", ["UPDATE audit.ActionEvent SET Reason = 'edited' WHERE ActionId = ?",
                                       "DELETE FROM audit.ActionEvent WHERE ActionId = ?"])
def test_audit_trail_cannot_be_edited(conn, build, statement):
    action_id = build.action_in("Submitted")
    with pytest.raises(pyodbc.Error, match="audit trail cannot be changed"):
        conn.execute(statement, action_id)


def test_stale_version_is_refused(conn, people, build):
    action_id = build.action_in("Submitted")
    seen = row_ver(conn, action_id)
    build.step(action_id, "RETURN", "apr_x")
    with pytest.raises(db.Changed):
        actions.transition(conn, people["adm"], action_id, seen, "REJECT", reason="Too late")
    assert status(conn, action_id) == "Returned"


def test_two_simultaneous_decisions_one_wins(people, build, conn):
    action_id = build.action_in("Submitted")
    seen = row_ver(conn, action_id)
    barrier = threading.Barrier(2)
    outcomes = {}

    def decide(actor, code):
        own = open_connection()
        try:
            barrier.wait()
            actions.transition(own, people[actor], action_id, seen, code, reason="Simultaneous")
            outcomes[actor] = "ok"
        except db.Changed:
            outcomes[actor] = "changed"
        finally:
            own.close()

    threads = [threading.Thread(target=decide, args=("apr_x", "APPROVE")),
               threading.Thread(target=decide, args=("adm", "REJECT"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes.values()) == ["changed", "ok"]
    winner = next(a for a, o in outcomes.items() if o == "ok")
    assert status(conn, action_id) == {"apr_x": "Approved", "adm": "Rejected"}[winner]
    assert conn.execute("SELECT COUNT(*) FROM audit.ActionEvent WHERE ActionId = ? AND FieldName = 'Status' "
                        "AND EventType IN ('APPROVE', 'REJECT')", action_id).fetchval() == 1
