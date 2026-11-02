"""Account administration (R11). Only administrators may call these, apart from request_account."""
from portal import db
from portal.auth import hash_password


def bootstrap_admin(conn, login, display_name, password):
    """Creates the first administrator; refused once any administrator exists."""
    return db.call(conn, "app.usp_BootstrapAdmin", Login=login, DisplayName=display_name,
                   PasswordHash=hash_password(password))[0][0]["UserId"]


def request_account(conn, login, display_name, password):
    """Sign-up: an inactive account without a role, until an administrator activates it."""
    return db.call(conn, "app.usp_RequestAccount", Login=login, DisplayName=display_name,
                   PasswordHash=hash_password(password))[0][0]["UserId"]


def create_account(conn, actor_id, login, display_name, role, region, password):
    return db.call(conn, "app.usp_CreateAccount", ActorUserId=actor_id, Login=login, DisplayName=display_name,
                   RoleCode=role, RegionCode=region, PasswordHash=hash_password(password))[0][0]["UserId"]


def update_account(conn, actor_id, user_id, role, region, is_active, row_ver):
    db.call(conn, "app.usp_UpdateAccount", ActorUserId=actor_id, UserId=user_id, RoleCode=role, RegionCode=region,
            IsActive=is_active, RowVer=row_ver)


def reset_password(conn, actor_id, user_id, password):
    db.call(conn, "app.usp_SetPassword", ActorUserId=actor_id, UserId=user_id, PasswordHash=hash_password(password))


def get_account(conn, user_id):
    """The current state of an account, read on every page run so a change applies on the next click."""
    rows = db.call(conn, "app.usp_GetAccount", UserId=user_id)[0]
    return rows[0] if rows else None


def list_accounts(conn, actor_id):
    return db.call(conn, "app.usp_ListAccounts", ActorUserId=actor_id)[0]
