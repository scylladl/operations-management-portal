"""
Loads the demo: accounts, the NorthGrid history (Q6) and about sixty requests in every status.

    set PORTAL_DEMO_PASSWORD=<a password of your choice>
    python scripts/seed_demo.py [--seed 11]

Every request goes through the same procedures the app calls, so the audit trail and the versions are real.
The demo clock (app.Setting DemoClock) is switched on while the script runs, so each event can be dated in the past
relative to today, and switched off at the end. People, names and texts are fictional.
The script refuses to run on a database that already has accounts.
"""
import argparse
import datetime as dt
import os
import pathlib
import random
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portal import actions, config, db, users  # noqa: E402

REGIONS = ["NOR", "NEA", "EST", "CEN", "SUR", "NWE"]
SECOND_APPROVER = {"NOR", "CEN"}   # so an approver's own request can go to a colleague (Q5)

PEOPLE = {
    "NOR": [("REQ", "Ane Etxeberria"), ("REQ", "Iker Zubiri"), ("APR", "Mikel Arrieta"), ("APR", "Leire Goñi"),
            ("FLD", "Unai Otaegui")],
    "NEA": [("REQ", "Marta Puigdomenech"), ("REQ", "Jordi Ferrer"), ("APR", "Núria Casals"), ("FLD", "Pau Rovira")],
    "EST": [("REQ", "Lucía Ballester"), ("REQ", "Vicent Soler"), ("APR", "Amparo Climent"), ("FLD", "Raúl Ibarra")],
    "CEN": [("REQ", "Elena Robledo"), ("REQ", "Daniel Arroyo"), ("APR", "Carmen Valdés"), ("APR", "Óscar Mena"),
            ("FLD", "Sergio Lozano")],
    "SUR": [("REQ", "Rocío Aguilar"), ("REQ", "Manuel Cabello"), ("APR", "Inmaculada Ruiz"), ("FLD", "Antonio Vega")],
    "NWE": [("REQ", "Xoán Varela"), ("REQ", "Iria Castro"), ("APR", "Brais Lema"), ("FLD", "Noelia Pazos")],
}

JUSTIFICATION = {
    "SITE_SURVEY": "{n} incidents since {first} ({causes}). No single cause stands out; a survey should show whether "
                   "the building access or the customer room is the problem before anything is replaced.",
    "EQUIP_REPLACE": "{n} incidents since {first} ({causes}). The customer premises equipment has restarted on its "
                     "own several times and is out of support.",
    "REROUTE": "{n} incidents since {first} ({causes}), all on the same access path. A second path through the "
               "other street cabinet is available.",
    "TECH_MIGRATION": "{n} incidents since {first} on a copper access ({causes}). Fibre reaches the street, and the "
                      "customer asked about it at the last review.",
}
CAUSES = {"BB": "backbone", "CPE": "customer premises", "LM": "last mile", "PWR": "power", "TPY": "third party",
          "UNK": "not identified", None: "not identified yet"}
OUTCOME = {
    "SITE_SURVEY": "A survey report with the cause and the recommended action.",
    "EQUIP_REPLACE": "No equipment-related incident in the 90 days after the replacement.",
    "REROUTE": "Last-mile incidents at most one per quarter.",
    "TECH_MIGRATION": "The circuit on fibre, with incidents at the level of other fibre circuits of the region.",
}
RETURN_REASONS = ["Link the incidents of December too; the request only shows the oldest ones.",
                  "Explain why a survey and not a replacement: the last two incidents point at the equipment.",
                  "The expected outcome needs a measurable target."]
REJECT_REASONS = ["The incidents were caused by a third-party works in the street, now finished.",
                  "This circuit is in the regional migration plan for next quarter; a separate action would duplicate it."]
CANCEL_REASONS = ["The customer is moving to a new site; the circuit will be decommissioned.",
                  "The building owner refused access for the works."]
NOTES = ["Site visited with the customer's facility manager; access confirmed.",
         "Equipment ordered; delivery expected next week.",
         "Works scheduled outside business hours at the customer's request."]

# Steps after the request is saved, as (transition, who, working days before today)
SCENARIOS = {
    "Draft":      [],
    "Submitted":  [("SUBMIT", "owner", None)],      # submitted at the age given per request
    "Returned":   [("SUBMIT", "owner", 7), ("RETURN", "approver", 5)],
    "Rejected":   [("SUBMIT", "owner", 16), ("REJECT", "approver", 13)],
    "Approved":   [("SUBMIT", "owner", 12), ("APPROVE", "approver", 9)],
    "InProgress": [("SUBMIT", "owner", 22), ("RETURN", "approver", 20), ("RESUBMIT", "owner", 19),
                   ("APPROVE", "approver", 17), ("START", "field", 14), ("NOTE", "field", 12)],
    "Completed":  [("SUBMIT", "owner", 32), ("APPROVE", "approver", 28), ("START", "field", 25),
                   ("COMPLETE", "field", 8)],
    "Verified":   [("SUBMIT", "owner", 48), ("APPROVE", "approver", 43), ("START", "field", 40),
                   ("COMPLETE", "field", 26), ("VERIFY", "approver", 22)],
    "Cancelled":  [("SUBMIT", "owner", 30), ("APPROVE", "approver", 27), ("START", "field", 24),
                   ("CANCEL", "approver", 18)],
}
REQUESTS_PER_REGION = ["Draft", "Submitted", "Submitted", "Submitted", "Returned", "Rejected", "Approved",
                       "InProgress", "Completed", "Verified", "Verified", "Cancelled"]
SUBMITTED_AGES = [1, 4, 8]   # working days, so the queue shows each age band (Q4)


def working_days_before(day, count):
    while count > 0:
        day -= dt.timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


def login_for(name):
    first, last = name.split(" ", 1)
    plain = str.maketrans("áéíóúñÁÉÍÓÚÑ", "aeiounAEIOUN")
    return f"{first[0]}.{last.split()[0]}".lower().translate(plain)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()
    password = os.environ.get("PORTAL_DEMO_PASSWORD")
    if not password or len(password) < 10:
        sys.exit("Set PORTAL_DEMO_PASSWORD (10 characters or more) before seeding.")
    rng = random.Random(args.seed)

    conn = db.connect(config.database_settings())
    if conn.execute("SELECT COUNT(*) FROM app.UserAccount").fetchval():
        sys.exit("The portal database already has accounts; the demo is loaded only into an empty database.")

    today = dt.date.today()
    conn.execute("UPDATE app.Setting SET SettingValue = 1 WHERE SettingCode = 'DemoClock'")
    try:
        def clock(day, hour):
            db.set_clock(conn, dt.datetime.combine(day, dt.time(hour, rng.randint(0, 59))))

        clock(working_days_before(today, 60), 9)
        admin = users.bootstrap_admin(conn, "admin", "Service Assurance Office", password)
        team = {}
        for region in REGIONS:
            for role, name in PEOPLE[region]:
                user_id = users.create_account(conn, admin, login_for(name), name, role, region, password)
                team.setdefault((region, role), []).append(user_id)
        disabled = users.create_account(conn, admin, "j.moreno", "Javier Moreno", "REQ", "CEN", password)
        users.update_account(conn, admin, disabled, "REQ", "CEN", False, users.get_account(conn, disabled)["RowVer"])
        users.request_account(conn, "s.prieto", "Sara Prieto", password)
        print(f"accounts: {conn.execute('SELECT COUNT(*) FROM app.UserAccount').fetchval()}")

        print(f"history: {actions.import_history(conn, admin)} actions imported")

        created = 0
        for region in REGIONS:
            busy = {r.CircuitId for r in conn.execute("SELECT CircuitId FROM app.Action WHERE OpenSlot = 0")}
            circuits = [c for c in actions.list_circuits(conn, region)
                        if c["RecentIncidents"] >= 3 and c["CircuitId"] not in busy][:40]
            rng.shuffle(circuits)
            ages = iter(SUBMITTED_AGES)
            requesters = team[(region, "REQ")]
            for number, target in enumerate(REQUESTS_PER_REGION):
                circuit = circuits.pop()
                owner = requesters[number % 2]
                age = next(ages) if target == "Submitted" else None
                seed_request(conn, rng, clock, today, circuit, target, owner, team, region, age)
                created += 1
            if region in SECOND_APPROVER:
                # Q5: an approver's own request, decided by the other approver of the region
                own, colleague = team[(region, "APR")]
                circuit = circuits.pop()
                seed_request(conn, rng, clock, today, circuit, "Approved", own, team, region, None, approver=colleague)
                created += 1
        print(f"requests: {created}")

        # R14: a field coordinator records the completion of a historical action still in progress
        historical = conn.execute("""
            SELECT TOP (1) ActionId, RegionCode, StartDate FROM app.Action
            WHERE IsHistorical = 1 AND Status = 'InProgress' AND RegionCode IS NOT NULL
            ORDER BY StartDate""").fetchone()
        clock(working_days_before(today, 3), 11)
        actions.transition(conn, team[(historical.RegionCode, "FLD")][0], historical.ActionId,
                           conn.execute("SELECT RowVer FROM app.Action WHERE ActionId = ?", historical.ActionId).fetchval(),
                           "COMPLETE", event_date=working_days_before(today, 4))
    finally:
        conn.execute("EXEC sp_set_session_context N'portal.clock', NULL")
        conn.execute("UPDATE app.Setting SET SettingValue = 0 WHERE SettingCode = 'DemoClock'")
    conn.close()


def seed_request(conn, rng, clock, today, circuit, target, owner, team, region, age, approver=None):
    evidence = actions.circuit_evidence(conn, owner, circuit["CircuitId"])
    incidents = evidence["incidents"]
    causes = Counter(i["RootCauseCode"] for i in incidents)
    if circuit["TechnologyCode"] == "COP":
        action_type = "TECH_MIGRATION"
    elif causes["CPE"]:
        action_type = "EQUIP_REPLACE"
    elif causes["LM"] and circuit["TechnologyCode"] == "FIB":
        action_type = "REROUTE"
    else:
        action_type = "SITE_SURVEY"
    cited = incidents[: rng.randint(2, min(4, len(incidents)))]
    text = JUSTIFICATION[action_type].format(
        n=len(incidents), first=min(i["OpenedAt"] for i in incidents).strftime("%d %B").lstrip("0"),
        causes=", ".join(f"{count} {CAUSES[code]}" for code, count in causes.most_common()))

    steps = SCENARIOS[target]
    first_day = working_days_before(today, (age if target == "Submitted" else steps[0][2] if steps else 2) + 1)
    clock(first_day, 9)
    action_id, row_ver = actions.save_request(conn, owner, circuit["CircuitId"], action_type, text,
                                              OUTCOME[action_type], [i["TicketId"] for i in cited])
    who = {"owner": owner, "approver": approver or team[(region, "APR")][0], "field": team[(region, "FLD")][0]}
    for code, actor, days_before in steps:
        day = working_days_before(today, age if days_before is None else days_before)
        clock(day, rng.randint(9, 17))
        if code == "NOTE":
            actions.add_work_note(conn, who[actor], action_id, rng.choice(NOTES))
            continue
        if code == "RESUBMIT":
            actions.save_request(conn, owner, None, None, text + " The December incidents are now linked.", None,
                                 [i["TicketId"] for i in incidents[:5]], action_id=action_id, row_ver=row_ver)
            row_ver = conn.execute("SELECT RowVer FROM app.Action WHERE ActionId = ?", action_id).fetchval()
        reason = {"RETURN": RETURN_REASONS, "REJECT": REJECT_REASONS, "CANCEL": CANCEL_REASONS}.get(code)
        row_ver = actions.transition(conn, who[actor], action_id, row_ver, code,
                                     reason=rng.choice(reason) if reason else None,
                                     event_date=day if code in ("START", "COMPLETE") else None)


if __name__ == "__main__":
    main()
