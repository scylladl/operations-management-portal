"""
AC-02: every role can do exactly what the rules allow, and the database refuses the rest.

EXPECTED is written from docs/01-business-requirements.md (sections 4-6), not read from ref.Transition, so a wrong
row in the transition table fails these tests.
"""
import datetime as dt
import json

import pytest

from conftest import OTHER_REGION, PATHS, REGION, TODAY, row_ver, status
from portal import actions, db, users

ACTORS = ["owner", "req_x", "req_y", "apr_x", "apr_y", "fld_x", "fld_y", "adm"]
DECIDERS = {"apr_x", "adm"}   # approvers of the action's region and administrators (R3)

# transition -> (from statuses, actors allowed, status after)
EXPECTED = {
    "SUBMIT":   ({"Draft"}, {"owner"}, "Submitted"),
    "RESUBMIT": ({"Returned"}, {"owner"}, "Submitted"),
    "APPROVE":  ({"Submitted"}, DECIDERS, "Approved"),
    "RETURN":   ({"Submitted"}, DECIDERS, "Returned"),
    "REJECT":   ({"Submitted"}, DECIDERS, "Rejected"),
    "START":    ({"Approved"}, {"fld_x"}, "InProgress"),
    "COMPLETE": ({"InProgress"}, {"fld_x"}, "Completed"),
    "VERIFY":   ({"Completed"}, DECIDERS, "Verified"),
    "REOPEN":   ({"Completed"}, DECIDERS, "InProgress"),
    "CANCEL":   ({"Approved", "InProgress"}, DECIDERS, "Cancelled"),
}

CASES = [(start, code, actor) for start in PATHS for code in EXPECTED for actor in ACTORS]


def allowed(start, code, actor):
    from_statuses, actors_allowed, _ = EXPECTED[code]
    return start in from_statuses and actor in actors_allowed


@pytest.fixture(scope="module")
def one_per_status(build):
    """One action per status, shared by the refusal cases (a refusal changes nothing)."""
    return {start: build.action_in(start) for start in PATHS}


@pytest.mark.parametrize("start, code, actor", [c for c in CASES if not allowed(*c)])
def test_refused(conn, people, build, one_per_status, start, code, actor):
    action_id = one_per_status[start]
    before = row_ver(conn, action_id)
    with pytest.raises(db.Forbidden):
        build.step(action_id, code, actor)
    assert row_ver(conn, action_id) == before


@pytest.mark.parametrize("start, code, actor", [c for c in CASES if allowed(*c)])
def test_allowed(conn, build, start, code, actor):
    action_id = build.action_in(start)
    build.step(action_id, code, actor)
    assert status(conn, action_id) == EXPECTED[code][2]


OPEN = {"Submitted", "Returned", "Approved", "InProgress", "Completed"}


def visible(start, actor):
    """R10. Drafts are private to their requester; other requesters of the region see its open actions."""
    if actor == "owner":
        return True
    if start == "Draft" or actor.endswith("_y"):
        return False
    return actor != "req_x" or start in OPEN


@pytest.mark.parametrize("start", list(PATHS))
@pytest.mark.parametrize("actor", ACTORS)
def test_visibility(conn, people, one_per_status, start, actor):
    action_id = one_per_status[start]
    if visible(start, actor):
        assert actions.get_action(conn, people[actor], action_id)["action"]["ActionId"] == action_id
    else:
        with pytest.raises(db.NotFound):
            actions.get_action(conn, people[actor], action_id)


@pytest.mark.parametrize("start, actor", [(s, a) for s in PATHS for a in ACTORS if visible(s, a)])
def test_buttons_match_rules(conn, people, one_per_status, start, actor):
    detail = actions.get_action(conn, people[actor], one_per_status[start])
    shown = {t["TransitionCode"] for t in detail["transitions"]}
    assert shown == {code for code in EXPECTED if allowed(start, code, actor)}


def test_approver_cannot_decide_own_request_but_another_approver_can(conn, people, build):
    action_id = build.action_in("Submitted", actor="apr_x2")
    with pytest.raises(db.Forbidden):
        build.step(action_id, "APPROVE", "apr_x2")
    build.step(action_id, "APPROVE", "apr_x")
    assert status(conn, action_id) == "Approved"


@pytest.mark.parametrize("code, start", [("RETURN", "Submitted"), ("REJECT", "Submitted"),
                                         ("CANCEL", "Approved"), ("CANCEL", "InProgress"),
                                         ("REOPEN", "Completed")])
def test_reason_required(conn, build, code, start):
    action_id = build.action_in(start)
    with pytest.raises(db.Invalid):
        build.step(action_id, code, "apr_x", reason="  ")
    assert status(conn, action_id) == start


def test_reason_is_recorded(conn, people, build):
    action_id = build.action_in("Submitted")
    build.step(action_id, "REJECT", "apr_x", reason="Circuit is already scheduled for migration.")
    reason = conn.execute("SELECT Reason FROM audit.ActionEvent WHERE ActionId = ? AND EventType = 'REJECT' "
                          "AND FieldName = 'Status'", action_id).fetchval()
    assert reason == "Circuit is already scheduled for migration."


def test_returned_request_is_edited_and_resubmitted_as_a_new_version(conn, people, build):
    action_id = build.action_in("Returned")
    actions.save_request(conn, people["owner"], None, None, "Outages every week since October.",
                         "No outage for 60 days.", None, action_id=action_id, row_ver=row_ver(conn, action_id))
    build.step(action_id, "RESUBMIT", "owner")
    versions = actions.get_action(conn, people["apr_x"], action_id)["versions"]
    assert [v["VersionNo"] for v in versions] == [2, 1]
    assert versions[0]["Justification"] == "Outages every week since October."
    assert versions[1]["Justification"] == "Repeated outages on this circuit."


def test_only_the_requester_edits_and_only_before_a_decision(conn, people, build):
    draft = build.draft()
    with pytest.raises(db.Forbidden):
        actions.save_request(conn, people["req_x"], None, None, "Changed", "Changed", None,
                             action_id=draft, row_ver=row_ver(conn, draft))
    submitted = build.action_in("Submitted")
    with pytest.raises(db.Forbidden):
        actions.save_request(conn, people["owner"], None, None, "Changed", "Changed", None,
                             action_id=submitted, row_ver=row_ver(conn, submitted))


def test_submission_needs_evidence(conn, people, circuits):
    circuit, tickets = next(circuits[REGION])
    action_id, rv = actions.save_request(conn, people["owner"], circuit, "REROUTE", "", "", [])
    with pytest.raises(db.Invalid):
        actions.transition(conn, people["owner"], action_id, rv, "SUBMIT")
    assert status(conn, action_id) == "Draft"


def test_incident_must_belong_to_the_circuit_and_the_window(conn, people, circuits):
    circuit, _ = next(circuits[REGION])
    _, other_tickets = next(circuits[REGION])
    with pytest.raises(db.Invalid):
        actions.save_request(conn, people["owner"], circuit, "REROUTE", "x", "y", other_tickets[:1])
    old_ticket = conn.execute("""
        SELECT TOP (1) TicketId FROM ng.Incident
        WHERE CircuitId = ? AND OpenedAt < '2025-09-01' ORDER BY OpenedAt""", circuit).fetchval()
    if old_ticket:
        with pytest.raises(db.Invalid):
            actions.save_request(conn, people["owner"], circuit, "REROUTE", "x", "y", [old_ticket])


def test_requester_works_only_in_own_region(conn, people, circuits):
    circuit, tickets = next(circuits[OTHER_REGION])
    with pytest.raises(db.Forbidden):
        actions.save_request(conn, people["owner"], circuit, "REROUTE", "x", "y", tickets[:1])


def test_field_coordinator_cannot_request(conn, people, circuits):
    circuit, tickets = next(circuits[REGION])
    with pytest.raises(db.Forbidden):
        actions.save_request(conn, people["fld_x"], circuit, "REROUTE", "x", "y", tickets[:1])


@pytest.mark.parametrize("condition", ["RegionCode IS NULL", "DecommissionDate IS NOT NULL"])
def test_circuits_without_region_or_decommissioned_cannot_be_requested(conn, people, condition):
    circuit = conn.execute(f"SELECT TOP (1) CircuitId FROM ng.Circuit WHERE {condition} ORDER BY CircuitId").fetchval()
    with pytest.raises(db.Invalid):
        actions.save_request(conn, people["adm"], circuit, "REROUTE", "x", "y", [])


def test_no_second_open_action_of_the_same_type(conn, people, build):
    first = build.action_in("Approved")
    circuit = conn.execute("SELECT CircuitId FROM app.Action WHERE ActionId = ?", first).fetchval()
    tickets = [r.TicketId for r in conn.execute("SELECT TicketId FROM app.ActionIncident WHERE ActionId = ?", first)]
    with pytest.raises(db.Duplicate):
        actions.save_request(conn, people["req_x"], circuit, "SITE_SURVEY", "x", "y", tickets)
    other_type, _ = actions.save_request(conn, people["req_x"], circuit, "REROUTE", "x", "y", tickets)
    assert status(conn, other_type) == "Draft"


def test_completed_but_not_verified_still_blocks(conn, people, build):
    completed = build.action_in("Completed")
    circuit = conn.execute("SELECT CircuitId FROM app.Action WHERE ActionId = ?", completed).fetchval()
    tickets = [r.TicketId for r in conn.execute("SELECT TicketId FROM app.ActionIncident WHERE ActionId = ?", completed)]
    with pytest.raises(db.Duplicate):
        actions.save_request(conn, people["owner"], circuit, "SITE_SURVEY", "x", "y", tickets)


def test_historical_completed_action_does_not_block(conn, people):
    circuit, action_type = conn.execute("""
        SELECT TOP (1) a.CircuitId, a.ActionTypeCode FROM app.Action AS a
        JOIN ng.Circuit AS c ON c.CircuitId = a.CircuitId
        WHERE a.IsHistorical = 1 AND a.Status = 'Completed' AND c.RegionCode = ? AND c.DecommissionDate IS NULL
          AND NOT EXISTS (SELECT 1 FROM app.Action AS o WHERE o.CircuitId = a.CircuitId AND o.OpenSlot = 0)
        ORDER BY a.ActionId""", REGION).fetchone()
    action_id, _ = actions.save_request(conn, people["owner"], circuit, action_type, "x", "y", [])
    assert status(conn, action_id) == "Draft"


def test_a_closed_action_does_not_block_a_new_one(conn, people, build):
    rejected = build.action_in("Rejected")
    circuit = conn.execute("SELECT CircuitId FROM app.Action WHERE ActionId = ?", rejected).fetchval()
    tickets = [r.TicketId for r in conn.execute("SELECT TicketId FROM app.ActionIncident WHERE ActionId = ?", rejected)]
    new_id, _ = actions.save_request(conn, people["owner"], circuit, "SITE_SURVEY", "x", "y", tickets)
    assert status(conn, new_id) == "Draft"


def test_start_and_completion_dates(conn, build):
    approved = build.action_in("Approved")
    with pytest.raises(db.Invalid):
        build.step(approved, "START", "fld_x", event_date=TODAY + dt.timedelta(days=1))
    build.step(approved, "START", "fld_x", event_date=TODAY - dt.timedelta(days=5))
    with pytest.raises(db.Invalid):
        build.step(approved, "COMPLETE", "fld_x", event_date=TODAY - dt.timedelta(days=6))
    with pytest.raises(db.Invalid):
        build.step(approved, "COMPLETE", "fld_x", event_date=TODAY + dt.timedelta(days=1))
    build.step(approved, "COMPLETE", "fld_x", event_date=TODAY - dt.timedelta(days=1))
    assert status(conn, approved) == "Completed"


def test_reopen_clears_the_completion_date(conn, build):
    action_id = build.action_in("Completed")
    build.step(action_id, "REOPEN", "apr_x", reason="Equipment still alarming.")
    assert conn.execute("SELECT CompletionDate FROM app.Action WHERE ActionId = ?", action_id).fetchval() is None


def test_draft_discarded_only_by_its_requester(conn, people, build):
    draft = build.draft()
    with pytest.raises(db.Forbidden):
        actions.discard_draft(conn, people["adm"], draft, row_ver(conn, draft))
    actions.discard_draft(conn, people["owner"], draft, row_ver(conn, draft))
    assert status(conn, draft) is None
    assert conn.execute("SELECT COUNT(*) FROM audit.ActionEvent WHERE ActionId = ? AND EventType = 'DISCARD'",
                        draft).fetchval() > 0


def test_submitted_request_cannot_be_discarded(conn, people, build):
    action_id = build.action_in("Submitted")
    with pytest.raises(db.Forbidden):
        actions.discard_draft(conn, people["owner"], action_id, row_ver(conn, action_id))


def test_administrator_changes_owner_with_reason(conn, people, build):
    action_id = build.action_in("Returned")
    with pytest.raises(db.Forbidden):
        actions.change_owner(conn, people["apr_x"], action_id, row_ver(conn, action_id), people["req_x"], "Leaving")
    with pytest.raises(db.Invalid):
        actions.change_owner(conn, people["adm"], action_id, row_ver(conn, action_id), people["req_x"], "")
    with pytest.raises(db.Invalid):
        actions.change_owner(conn, people["adm"], action_id, row_ver(conn, action_id), people["req_y"], "Leaving")
    actions.change_owner(conn, people["adm"], action_id, row_ver(conn, action_id), people["req_x"], "Leaving")
    assert conn.execute("SELECT RequesterId FROM app.Action WHERE ActionId = ?", action_id).fetchval() == people["req_x"]
    build.step(action_id, "RESUBMIT", "req_x")


def test_work_notes_only_by_field_coordinator_of_the_region(conn, people, build):
    action_id = build.action_in("InProgress")
    with pytest.raises(db.Forbidden):
        actions.add_work_note(conn, people["fld_y"], action_id, "Visited the site.")
    actions.add_work_note(conn, people["fld_x"], action_id, "Visited the site.")
    notes = actions.get_action(conn, people["apr_x"], action_id)["notes"]
    assert [n["NoteText"] for n in notes] == ["Visited the site."]


def test_disabled_account_can_do_nothing(conn, people, build, password):
    temp = users.create_account(conn, people["adm"], "temp_apr", "Temp approver", "APR", REGION, password)
    action_id = build.action_in("Submitted")
    account = users.get_account(conn, temp)
    users.update_account(conn, people["adm"], temp, "APR", REGION, False, account["RowVer"])
    with pytest.raises(db.Forbidden):
        actions.transition(conn, temp, action_id, row_ver(conn, action_id), "APPROVE")


def test_versions_keep_the_incidents(conn, people, build):
    action_id = build.action_in("Submitted")
    version = actions.get_action(conn, people["apr_x"], action_id)["versions"][0]
    assert len(json.loads(version["TicketIds"])) >= 1
