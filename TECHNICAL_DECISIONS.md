# Technical Decisions

> **SIMULATED SCENARIO.** NorthGrid Telecom and all its data are fictional.

The decisions that shaped the portal, with the reason and what was given up. The client-facing version is
`docs/03-architecture.md`.

## D-01 A separate database, reading NorthGridOps through synonyms

NorthGridOps reloads `ops.ImprovementAction` from the client's export with `DELETE` and bulk insert, and its
warehouse rebuild is triggered by a fingerprint of that table. A portal writing there would lose its data on the
next load and trigger rebuilds on every decision. `NorthGridPortal` has its own lifecycle and permissions and reads
six NorthGridOps tables through synonyms, so nothing is copied. Cost: no foreign keys to circuits and incidents
(the procedures check them), and both databases must stay on one instance or the synonyms need a linked server.

## D-02 The rules live in stored procedures, the transition table drives both screen and database

Every change is one procedure call that checks the actor, the transition, the region, ownership, the reason, the
dates and the row version, in one transaction. `app.fn_AllowedTransitions` reads `ref.Transition` and is used both
by `app.usp_Transition` to refuse and by the action page to show buttons, so they cannot disagree. Hiding a button
is a convenience; the 857 workflow tests call the procedures directly. Cost: the business rules are in T-SQL, which
fewer Python developers read; there is no Python service layer repeating them.

## D-03 Audit by triggers, with the actor in SESSION_CONTEXT

Procedures set the actor, event, reason and time in `SESSION_CONTEXT`; triggers write one row per changed field in
the same transaction and refuse any change made without that context. The audit tables refuse `UPDATE` and
`DELETE` from anyone. Cost: anyone with `ALTER` on the database can still disable a trigger; the trail is
tamper-evident for the app and its users, not for a database administrator.

## D-04 The database trusts the app for identity, and nothing else

The app authenticates (Argon2id via argon2-cffi, defaults) and passes the user id; the database decides what that
user may do and reloads the account on every call, so a disabled account stops working on the next click. The
app's database role can only run procedures and read report views. Cost: if the app's login were stolen, it could
act as any user; per-user database logins were not worth it for an internal portal of this size.

## D-05 Optimistic concurrency with rowversion

Each command receives the row version the user saw and locks the row (`UPDLOCK, HOLDLOCK`) before comparing. Two
simultaneous decisions: one wins, the other gets "this action changed" and the current state. Cost: a user who
waits long on a page may have to reload before acting.

## D-06 The evidence window follows the extraction, not the calendar

The NorthGrid incident data ends on 2025-12-31. "The last 90 days" (R2) is counted back from the latest incident
loaded, because the portal can only show what the last extraction contains; the page states the dates.
Submission re-checks the linked incidents, in case a newer extraction moved the window.

## D-07 The history becomes the export the NorthGrid report already reads

`pub.vw_ImprovementActionExport` writes the six columns of `improvement_actions.csv`, mapping portal statuses to the
NorthGrid ones and leaving out requests that never became work. Replacing the spreadsheet with this file needs no
change to the NorthGrid report or its KPIs (Q7). A test proves the historical rows round-trip exactly. Cost: the
NorthGrid report still learns about portal actions only when its load runs.

## D-08 A demo clock instead of fake timestamps

Seeded requests go through the same procedures as real ones, so their audit trail and versions are genuine. To
give them past dates, the procedures accept a time from `SESSION_CONTEXT` only while `app.Setting DemoClock` is 1;
deploy sets it to 0. Cost: one setting that must stay off in production (deploy enforces it).

## D-09 Tests on their own database, and a check that they can fail

The suite deploys `NorthGridPortal_Test` from the scripts, runs, and drops it, so the demo data is never touched.
Because most tests passed on their first run, `validation/mutation_check.py` breaks eight rules one at a time and
confirms each one fails the suite; it found one gap, now covered.

## D-10 Design through the native theme first, CSS only on the portal's own pieces

The "Service desk" design (chosen by the client among three directions) comes mostly from Streamlit's theme:
colours, the navy sidebar, Inter, radii, table headers. What the theme cannot do (queue cards, the workflow stepper,
the history timeline, the sign-in panel) is HTML built in `portal/components.py`, with every database value
escaped, and styled by `assets/portal.css`, which targets only those classes and keyed containers, never
Streamlit's internal class names. Cost: the Inter font loads from Google Fonts, so a browser without internet
access falls back to its own sans-serif; a stricter deployment would host the font files with the app.
