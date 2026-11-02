"""Password hashing (Argon2id) and sign-in."""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from portal import db

hasher = PasswordHasher()   # argon2-cffi defaults: Argon2id, RFC 9106 low-memory profile


class SignInFailed(Exception):
    pass


def hash_password(password):
    return hasher.hash(password)


def sign_in(conn, login, password):
    """Returns the account. The same message for every failure, so it does not reveal which logins exist."""
    rows = db.call(conn, "app.usp_GetSignIn", Login=login)[0]
    if not rows:
        hasher.hash(password)   # same work as a real check, so timing does not reveal unknown logins either
        raise SignInFailed("Wrong login or password, or the account is not active.")
    account = rows[0]
    try:
        hasher.verify(account["PasswordHash"], password)
    except (VerificationError, InvalidHashError):
        raise SignInFailed("Wrong login or password, or the account is not active.") from None
    if not account["IsActive"]:
        raise SignInFailed("Wrong login or password, or the account is not active.")
    if hasher.check_needs_rehash(account["PasswordHash"]):
        db.call(conn, "app.usp_SetPassword", ActorUserId=account["UserId"], UserId=account["UserId"],
                PasswordHash=hash_password(password))
    return {key: account[key] for key in ("UserId", "Login", "DisplayName", "RoleCode", "RegionCode")}


def change_password(conn, user_id, current_password, new_password):
    stored = db.call(conn, "app.usp_GetSignIn", UserId=user_id)[0][0]
    try:
        hasher.verify(stored["PasswordHash"], current_password)
    except (VerificationError, InvalidHashError):
        raise SignInFailed("The current password is wrong.") from None
    db.call(conn, "app.usp_SetPassword", ActorUserId=user_id, UserId=user_id, PasswordHash=hash_password(new_password))
