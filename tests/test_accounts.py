"""R11: accounts, sign-in and password storage."""
import pytest

from conftest import REGION
from portal import auth, db, users


def test_passwords_are_stored_as_argon2id(conn, people):
    stored = conn.execute("SELECT PasswordHash FROM app.UserAccount WHERE UserId = ?", people["req_x"]).fetchval()
    assert stored.startswith("$argon2id$")


def test_sign_in(conn, password):
    account = auth.sign_in(conn, "req_x", password)
    assert account["RoleCode"] == "REQ"
    with pytest.raises(auth.SignInFailed):
        auth.sign_in(conn, "req_x", password + "x")
    with pytest.raises(auth.SignInFailed):
        auth.sign_in(conn, "nobody", password)


def test_disabled_account_cannot_sign_in(conn, people, password):
    user_id = users.create_account(conn, people["adm"], "leaver", "Leaver", "REQ", REGION, password)
    users.update_account(conn, people["adm"], user_id, "REQ", REGION, False, users.get_account(conn, user_id)["RowVer"])
    with pytest.raises(auth.SignInFailed):
        auth.sign_in(conn, "leaver", password)


def test_sign_up_waits_for_activation(conn, people, password):
    user_id = users.request_account(conn, "newcomer", "New Engineer", password)
    with pytest.raises(auth.SignInFailed):
        auth.sign_in(conn, "newcomer", password)
    users.update_account(conn, people["adm"], user_id, "REQ", REGION, True, users.get_account(conn, user_id)["RowVer"])
    assert auth.sign_in(conn, "newcomer", password)["UserId"] == user_id


def test_only_administrators_manage_accounts(conn, people, password):
    with pytest.raises(db.Forbidden):
        users.create_account(conn, people["apr_x"], "intruder", "Intruder", "ADM", None, password)
    target = users.get_account(conn, people["req_x"])
    with pytest.raises(db.Forbidden):
        users.update_account(conn, people["apr_x"], people["req_x"], "ADM", None, True, target["RowVer"])


def test_second_bootstrap_is_refused(conn, password):
    with pytest.raises(db.Forbidden):
        users.bootstrap_admin(conn, "another_admin", "Another", password)


def test_password_change(conn, people, password):
    user_id = users.create_account(conn, people["adm"], "changer", "Changer", "FLD", REGION, password)
    with pytest.raises(auth.SignInFailed):
        auth.change_password(conn, user_id, "wrong", "new-password-123")
    auth.change_password(conn, user_id, password, "new-password-123")
    assert auth.sign_in(conn, "changer", "new-password-123")["UserId"] == user_id


def test_account_audit_never_holds_the_hash(conn, people):
    values = [r[0] for r in conn.execute(
        "SELECT CONCAT(OldValue, '|', NewValue) FROM audit.UserEvent WHERE FieldName = 'Password'")]
    assert values and all("argon2" not in v for v in values)
    actor = conn.execute("SELECT ActorUserId FROM audit.UserEvent WHERE UserId = ? AND FieldName = 'RoleCode'",
                         people["req_x"]).fetchval()
    assert actor == people["adm"]
