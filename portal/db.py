"""
Connection to the portal database and calls to its procedures.

Every rule is enforced by the procedures; this module only turns their errors (THROW 5000x) into exceptions
the pages can show.
"""
import re

import pyodbc


class PortalError(Exception):
    """A rule refused the change; the message is meant for the user."""


class Forbidden(PortalError):
    pass


class Invalid(PortalError):
    pass


class Changed(PortalError):
    pass


class NotFound(PortalError):
    pass


class Duplicate(PortalError):
    pass


ERRORS = {50001: Forbidden, 50002: Invalid, 50003: Changed, 50004: NotFound, 50005: Duplicate}
SQL_MESSAGE = re.compile(r"\[SQL Server\](?P<text>.*?) \((?P<number>\d+)\)")


def connection_string(settings):
    parts = {
        "Driver": "{%s}" % settings.get("driver", "ODBC Driver 18 for SQL Server"),
        "Server": settings["server"],
        "Database": settings["database"],
        "Encrypt": "yes",
        "TrustServerCertificate": settings.get("trust_server_certificate", "yes"),
    }
    if settings.get("username"):
        parts.update(UID=settings["username"], PWD=settings["password"])
    else:
        parts["Trusted_Connection"] = "yes"
    return ";".join(f"{key}={value}" for key, value in parts.items())


def connect(settings):
    # Each procedure manages its own transaction
    return pyodbc.connect(connection_string(settings), autocommit=True)


def set_clock(conn, when):
    """Demo and tests only: the time procedures record. Ignored unless app.Setting DemoClock is 1."""
    conn.execute("EXEC sp_set_session_context N'portal.clock', ?", when)


def result_sets(cursor):
    sets = []
    while True:
        if cursor.description:
            columns = [c[0] for c in cursor.description]
            sets.append([dict(zip(columns, row)) for row in cursor.fetchall()])
        if not cursor.nextset():
            return sets


def call(conn, procedure, **params):
    """Runs a procedure with named parameters and returns its result sets as lists of dicts."""
    arguments = ", ".join(f"@{name} = ?" for name in params)
    try:
        return result_sets(conn.execute(f"EXEC {procedure} {arguments}", *params.values()))
    except pyodbc.Error as error:
        match = SQL_MESSAGE.search(str(error))
        if match and int(match["number"]) in ERRORS:
            raise ERRORS[int(match["number"])](match["text"]) from None
        raise
