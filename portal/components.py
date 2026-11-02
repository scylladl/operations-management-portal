"""
HTML pieces of the "Service desk" design, styled by assets/portal.css and rendered with st.html.
Every value from the database is escaped here; st.html also sanitizes the markup and runs no JavaScript.
"""
import base64
import pathlib
from html import escape

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
STEPS = [("Draft", "Draft"), ("Submitted", "Submitted"), ("Approved", "Approved"), ("InProgress", "In progress"),
         ("Completed", "Completed"), ("Verified", "Verified")]


def header(kicker, title, subtitle=None):
    return (f'<div class="ng-header"><div class="ng-kicker">{escape(kicker)}</div>'
            f'<div class="ng-title">{escape(title)}</div>'
            + (f'<div class="ng-sub">{escape(subtitle)}</div>' if subtitle else "") + "</div>")


def section(label):
    return f'<div class="ng-section">{escape(label)}</div>'


def pill(status, name):
    return f'<span class="ng-pill s-{escape(status)}">{escape(name)}</span>'


def initials(name):
    parts = (name or "?").split()
    return escape((parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper())


def avatar(name):
    return f'<span class="ng-avatar">{initials(name)}</span>'


def user_chip(name, role_line):
    return (f'<div class="ng-user">{avatar(name)}<div><div class="ng-user-name">{escape(name)}</div>'
            f'<div class="ng-user-role">{escape(role_line)}</div></div></div>')


def action_card(row, waiting=False):
    """The text of a queue card: number, type and circuit, then who, where and how long."""
    chip = ""
    if waiting and row.get("WaitingWorkingDays") is not None:
        days = row["WaitingWorkingDays"]
        chip = (f'<span class="ng-chip{" late" if days > 5 else ""}">'
                f'{"Over target · " if days > 5 else ""}{days} working day{"s" if days != 1 else ""}</span>')
    meta = " · ".join(escape(str(part)) for part in
                      (row.get("RequesterName") or "requester not recorded", row.get("RegionCode"),
                       row.get("Started")) if part)
    return (f'<div class="ng-card"><div class="ng-card-top"><span class="ng-id">#{row["ActionId"]}</span>'
            f'<span class="ng-card-title">{escape(row["ActionTypeName"])} · {escape(row["CircuitId"])}</span>'
            f'{pill(row["Status"], row["StatusName"])}{chip}</div>'
            f'<div class="ng-card-meta">{meta}</div></div>')


def stepper(status, started):
    """Where the action is in the workflow. Returned, rejected and cancelled show where it stopped."""
    order = [code for code, _ in STEPS]
    stop = {"Returned": ("Submitted", "Returned", "stopped"), "Rejected": ("Submitted", "Rejected", "stopped"),
            "Cancelled": ("InProgress" if started else "Approved", "Cancelled", "stopped grey")}
    at, label, style = stop.get(status, (status, None, "current"))
    position = order.index(at)
    if status == "Verified":
        position, style = len(order), "done"
    items = []
    for i, (code, name) in enumerate(STEPS):
        if i < position:
            css, mark = "done", "&#10003;"
        elif i == position:
            css, mark, name = style, str(i + 1), label or name
        else:
            css, mark = "", str(i + 1)
        items.append(f'<div class="ng-step {css}"><span class="dot">{mark}</span>'
                     f'<span class="label">{escape(name)}</span></div>')
    return f'<div class="ng-stepper">{"".join(items)}</div>'


def facts(pairs):
    rows = "".join(f'<span class="label">{escape(label)}</span><span class="value">{escape(str(value))}</span>'
                   for label, value in pairs if value)
    return f'<div class="ng-facts">{rows}</div>'


def timeline(entries):
    """entries: (actor, title, when, lines, reason) per event, oldest first."""
    items = []
    for actor, title, when, lines, reason in entries:
        items.append(
            f'<li class="ng-event">{avatar(actor)}'
            f'<div class="ng-event-head"><b>{escape(title)}</b> · {escape(actor)} '
            f'<span class="ng-event-time">· {escape(when)}</span></div>'
            + (f'<div class="ng-event-body">{escape("; ".join(lines))}</div>' if lines else "")
            + (f'<div class="ng-reason">{escape(reason)}</div>' if reason else "") + "</li>")
    return f'<ul class="ng-timeline">{"".join(items)}</ul>'


def sign_in_hero():
    logo = base64.b64encode((ASSETS / "logo.svg").read_bytes()).decode()
    return (f'<div class="ng-hero"><div><img src="data:image/svg+xml;base64,{logo}" alt="NorthGrid">'
            "<h1>Improvement actions, from evidence to verified work.</h1>"
            "<p>Request an action with the incidents behind it, get a regional decision, record the field work "
            "and confirm it, with every step on record.</p>"
            "<ul><li>Evidence from the latest incident extraction</li>"
            "<li>Decisions by the regional approver, with reasons</li>"
            "<li>An audit trail written with every change</li></ul></div>"
            "<small>Simulated scenario. NorthGrid Telecom, its people and data are fictional.</small></div>")
