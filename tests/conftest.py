"""
The tests run against NorthGridPortal_Test, deployed from database/ at the start of the run and dropped at the end,
so they never touch the demo database. NorthGridOps is only read.

Region NOR plays "the action's region" and SUR "another region". The demo clock is fixed at a Monday in January
2026; the NorthGrid incident data ends on 2025-12-31, which is where the evidence window ends.
"""
import datetime as dt
import os
import pathlib
import secrets
import subprocess

import pytest

from portal import actions, db, users

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = os.environ.get("PORTAL_TEST_SERVER", "localhost")
SETTINGS = {"server": SERVER, "database": "NorthGridPortal_Test"}
NOW = dt.datetime(2026, 1, 12, 10, 0)
TODAY = NOW.date()
REGION, OTHER_REGION = "NOR", "SUR"

# name -> (role, region)
ACCOUNTS = {
    "owner":  ("REQ", REGION),
    "req_x":  ("REQ", REGION),
    "req_y":  ("REQ", OTHER_REGION),
    "apr_x":  ("APR", REGION),
    "apr_x2": ("APR", REGION),
    "apr_y":  ("APR", OTHER_REGION),
    "fld_x":  ("FLD", REGION),
    "fld_y":  ("FLD", OTHER_REGION),
    "adm2":   ("ADM", None),
}


def drop_test_database():
    master = db.connect({**SETTINGS, "database": "master"})
    master.execute("""
        IF DB_ID(N'NorthGridPortal_Test') IS NOT NULL
        BEGIN
            ALTER DATABASE NorthGridPortal_Test SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
            DROP DATABASE NorthGridPortal_Test;
        END""")
    master.close()


def open_connection():
    conn = db.connect(SETTINGS)
    db.set_clock(conn, NOW)
    return conn


@pytest.fixture(scope="session")
def conn():
    drop_test_database()
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(ROOT / "database" / "deploy.ps1"), "-Server", SERVER,
                    "-Database", SETTINGS["database"]], check=True, capture_output=True)
    setup = db.connect(SETTINGS)
    setup.execute("UPDATE app.Setting SET SettingValue = 1 WHERE SettingCode = 'DemoClock'")
    setup.close()
    connection = open_connection()
    yield connection
    connection.close()
    drop_test_database()


@pytest.fixture(scope="session")
def password():
    return secrets.token_urlsafe(16)


@pytest.fixture(scope="session")
def people(conn, password):
    """Account ids by name; 'adm' is the first administrator."""
    ids = {"adm": users.bootstrap_admin(conn, "adm", "Test Administrator", password)}
    for name, (role, region) in ACCOUNTS.items():
        ids[name] = users.create_account(conn, ids["adm"], name, f"Test {name}", role, region, password)
    actions.import_history(conn, ids["adm"])
    return ids


@pytest.fixture(scope="session")
def circuits(conn):
    """Iterators of (circuit, tickets in the evidence window), one circuit per request so R1 never interferes."""
    rows = conn.execute("""
        WITH w AS (SELECT CAST(MAX(OpenedAt) AS date) AS WindowEnd FROM ng.Incident)
        SELECT c.RegionCode, i.CircuitId, i.TicketId
        FROM ng.Incident AS i
        JOIN ng.Circuit AS c ON c.CircuitId = i.CircuitId
        CROSS JOIN w
        WHERE c.RegionCode IN (?, ?) AND c.DecommissionDate IS NULL
          AND i.IsCancelled = 0 AND i.DuplicateOfTicketId IS NULL
          AND CAST(i.OpenedAt AS date) > DATEADD(day, -90, w.WindowEnd)
          AND NOT EXISTS (SELECT 1 FROM ng.ImprovementAction AS a
                          WHERE a.CircuitId = c.CircuitId AND a.Status = 'In progress')
        ORDER BY i.CircuitId, i.TicketId""", REGION, OTHER_REGION).fetchall()
    by_region = {REGION: {}, OTHER_REGION: {}}
    for region, circuit, ticket in rows:
        by_region[region].setdefault(circuit, []).append(ticket)
    return {region: iter(found.items()) for region, found in by_region.items()}


def row_ver(conn, action_id):
    return conn.execute("SELECT RowVer FROM app.Action WHERE ActionId = ?", action_id).fetchval()


def status(conn, action_id):
    return conn.execute("SELECT Status FROM app.Action WHERE ActionId = ?", action_id).fetchval()


# How to reach each status from a fresh draft, as (transition, actor) steps
PATHS = {
    "Draft":      [],
    "Submitted":  [("SUBMIT", "owner")],
    "Returned":   [("SUBMIT", "owner"), ("RETURN", "apr_x")],
    "Rejected":   [("SUBMIT", "owner"), ("REJECT", "apr_x")],
    "Approved":   [("SUBMIT", "owner"), ("APPROVE", "apr_x")],
    "InProgress": [("SUBMIT", "owner"), ("APPROVE", "apr_x"), ("START", "fld_x")],
    "Completed":  [("SUBMIT", "owner"), ("APPROVE", "apr_x"), ("START", "fld_x"), ("COMPLETE", "fld_x")],
    "Verified":   [("SUBMIT", "owner"), ("APPROVE", "apr_x"), ("START", "fld_x"), ("COMPLETE", "fld_x"),
                   ("VERIFY", "apr_x")],
    "Cancelled":  [("SUBMIT", "owner"), ("APPROVE", "apr_x"), ("CANCEL", "apr_x")],
}


class Builder:
    def __init__(self, conn, people, circuits):
        self.conn, self.people, self.circuits = conn, people, circuits

    def draft(self, actor="owner", region=REGION, action_type="SITE_SURVEY"):
        circuit, tickets = next(self.circuits[region])
        action_id, _ = actions.save_request(
            self.conn, self.people[actor], circuit, action_type,
            "Repeated outages on this circuit.", "Fewer incidents in the next quarter.", tickets[:2])
        return action_id

    def step(self, action_id, code, actor, reason="Test reason", event_date=TODAY):
        return actions.transition(self.conn, self.people[actor], action_id, row_ver(self.conn, action_id), code,
                                  reason=reason, event_date=event_date)

    def action_in(self, target, actor="owner"):
        action_id = self.draft(actor)
        for code, step_actor in PATHS[target]:
            self.step(action_id, code, actor if step_actor == "owner" else step_actor)
        assert status(self.conn, action_id) == target
        return action_id


@pytest.fixture(scope="session")
def build(conn, people, circuits):
    return Builder(conn, people, circuits)
