"""Queries and commands on improvement actions. Every call names the acting user; the procedures decide."""
import json

from portal import db


def save_request(conn, actor_id, circuit_id, action_type, justification, expected_outcome, ticket_ids,
                 action_id=None, row_ver=None):
    """Creates a draft, or edits a draft or returned request. None keeps a field of an existing request as it is."""
    row = db.call(conn, "app.usp_SaveRequest", ActorUserId=actor_id, ActionId=action_id, RowVer=row_ver,
                  CircuitId=circuit_id, ActionTypeCode=action_type, Justification=justification,
                  ExpectedOutcome=expected_outcome,
                  TicketIds=None if ticket_ids is None else json.dumps(list(ticket_ids)))[0][0]
    return row["ActionId"], row["RowVer"]


def transition(conn, actor_id, action_id, row_ver, code, reason=None, event_date=None):
    return db.call(conn, "app.usp_Transition", ActorUserId=actor_id, ActionId=action_id, RowVer=row_ver,
                   TransitionCode=code, Reason=reason, EventDate=event_date)[0][0]["RowVer"]


def discard_draft(conn, actor_id, action_id, row_ver):
    db.call(conn, "app.usp_DiscardDraft", ActorUserId=actor_id, ActionId=action_id, RowVer=row_ver)


def change_owner(conn, actor_id, action_id, row_ver, new_owner_id, reason):
    return db.call(conn, "app.usp_ChangeOwner", ActorUserId=actor_id, ActionId=action_id, RowVer=row_ver,
                   NewOwnerId=new_owner_id, Reason=reason)[0][0]["RowVer"]


def add_work_note(conn, actor_id, action_id, text):
    db.call(conn, "app.usp_AddWorkNote", ActorUserId=actor_id, ActionId=action_id, NoteText=text)


def get_action(conn, actor_id, action_id):
    action, incidents, versions, events, notes, transitions = db.call(
        conn, "app.usp_GetAction", ActorUserId=actor_id, ActionId=action_id)
    return {"action": action[0], "incidents": incidents, "versions": versions, "events": events,
            "notes": notes, "transitions": transitions}


def list_actions(conn, actor_id, view):
    """view: mine, decide, verify, work, region or all."""
    return db.call(conn, "app.usp_ListActions", ActorUserId=actor_id, ListName=view)[0]


def list_circuits(conn, region_code=None):
    """Circuits that can be requested, with their incidents in the evidence window; all regions when None."""
    return db.call(conn, "app.usp_ListCircuits", RegionCode=region_code)[0]


def circuit_evidence(conn, actor_id, circuit_id):
    circuit, incidents, history = db.call(conn, "app.usp_GetCircuitEvidence", ActorUserId=actor_id,
                                          CircuitId=circuit_id)
    return {"circuit": circuit[0], "incidents": incidents, "history": history}


def indicators(conn, actor_id):
    waiting, decisions, completion, by_status = db.call(conn, "app.usp_GetIndicators", ActorUserId=actor_id)
    return {"waiting": waiting, "decisions": decisions, "completion": completion, "by_status": by_status}


def import_history(conn, actor_id):
    """Setup step (Q6): copies the NorthGrid actions once. Not granted to the app's database role."""
    return db.call(conn, "app.usp_ImportHistory", ActorUserId=actor_id)[0][0]["Imported"]
