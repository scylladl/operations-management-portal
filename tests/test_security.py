"""The app's database role (07_security.sql): procedures and report views only, no direct table access."""
import pyodbc
import pytest


@pytest.fixture
def as_app_role(conn):
    conn.execute("""
        IF DATABASE_PRINCIPAL_ID(N'test_app') IS NULL CREATE USER test_app WITHOUT LOGIN;
        ALTER ROLE portal_app ADD MEMBER test_app;""")
    conn.execute("EXECUTE AS USER = N'test_app'")
    yield conn
    conn.execute("REVERT")


@pytest.mark.parametrize("statement", [
    "SELECT TOP (1) PasswordHash FROM app.UserAccount",
    "SELECT TOP (1) * FROM audit.ActionEvent",
    "UPDATE app.Action SET Status = 'Approved' WHERE ActionId = 1",
    "INSERT audit.ActionEvent (ActionId, EventAt, ActorUserId, EventType, FieldName) VALUES (1, SYSDATETIME(), 1, 'X', 'X')",
    "EXEC app.usp_ImportHistory @ActorUserId = 1",
    "EXEC app.usp_BootstrapAdmin @Login = 'x', @DisplayName = 'x', @PasswordHash = 'x'",
])
def test_app_role_cannot_touch_tables_or_setup(as_app_role, statement):
    with pytest.raises(pyodbc.Error, match=r"\(229\)"):
        as_app_role.execute(statement).fetchall()


def test_app_role_runs_procedures_and_reads_views(as_app_role, people):
    logins = {r.Login for r in as_app_role.execute("EXEC app.usp_ListAccounts @ActorUserId = ?", people["adm"])}
    assert "adm" in logins
    as_app_role.execute("SELECT TOP (1) * FROM rpt.vw_ActionCycle").fetchall()


def test_northgrid_reads_need_a_grant_in_northgridops(as_app_role):
    """Documents the deployment step in 07_security.sql: without a NorthGridOps user the synonyms are refused."""
    with pytest.raises(pyodbc.Error, match=r"\(916\)"):
        as_app_role.execute("EXEC app.usp_ListCircuits @RegionCode = 'NOR'").fetchall()
