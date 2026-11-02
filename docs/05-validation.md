# Validation

> **SIMULATED SCENARIO.** NorthGrid Telecom and all its data are fictional.

What was checked, how, and the result on 2026-11-02. Commands run from the repository root.

## Acceptance criteria

| # | Criterion | How it is checked | Result |
|---|---|---|---|
| AC-01 | One command creates the database objects and loads the demo | `build.ps1 -Reset` | Database, 29 accounts, 558 historical actions and 74 requests in 19 s, then the tests |
| AC-02 | Each role can do exactly what the rules allow; the backend refuses the rest | `tests/test_workflow.py` | 857 tests pass, among them every role × transition × status (see below) |
| AC-03 | The audit record is written in the same transaction; a failed change leaves neither | `tests/test_integrity.py::test_failed_audit_write_leaves_no_change` | Passes |
| AC-04 | Two simultaneous decisions cannot both succeed | `tests/test_integrity.py::test_two_simultaneous_decisions_one_wins` | Passes |
| AC-05 | No secret or personal data committed; an example configuration exists | `.gitignore`, `.streamlit/secrets.example.toml`, review of the history | No password, connection string with credentials or hash in the repository; the demo password comes from `PORTAL_DEMO_PASSWORD` |
| AC-06 | Walkthrough with screenshots from the running app | `scripts/capture_walkthrough.py`, `docs/04-walkthrough.md` | 16 screenshots, draft to verified with a return, and a rejection |
| AC-07 | Indicators match independent SQL | `tests/test_indicators.py` against `validation/indicators_check.sql` | Passes, all four result sets |

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

903 tests, all passing, in about 10 seconds. They run against `NorthGridPortal_Test`, which the run creates from
`database/` and drops at the end; NorthGridOps is only read.

| File | Tests | What they prove |
|---|---|---|
| `test_workflow.py` | 857 | For every status, every transition and eight kinds of actor (the requester, another requester of the region, a requester of another region, approvers and field coordinators of the region and of another region, an administrator): allowed transitions succeed and land in the right status, the rest are refused by the database and change nothing. Visibility (R10) per status and actor. The buttons offered match the rules. Plus reasons, dates, versions, duplicates, ownership, drafts, notes and disabled accounts. |
| `test_integrity.py` | 7 | Audit content (who, when, before, after), atomicity, refusal of direct table changes, an insert-only trail, stale versions, and simultaneous decisions |
| `test_accounts.py` | 8 | Argon2id hashes, sign-in, disabled and pending accounts, administrator-only management, password change, no hash in the trail |
| `test_security.py` | 8 | The app's database role cannot read or write tables or run setup procedures, can run the app procedures, and needs a NorthGridOps grant for the synonyms |
| `test_history_export.py` | 6 | The 558 actions imported as they are; the export reproduces NorthGridOps row for row; R14; status mapping of the export |
| `test_indicators.py` | 3 | A known request (returned once, decided after five working days), the independent check, region scope |
| `test_ui.py` | 14 | User text cannot become Markdown links, images, HTML or Streamlit directives; the HTML components escape database values; the workflow stepper marks returned, rejected and cancelled actions where they stopped |

The expected permissions in `test_workflow.py` are written from the requirements, not read from
`ref.Transition`, so a wrong row in the transition table fails the tests.

## Do the tests catch broken rules?

Most tests passed on their first run, which by itself does not prove they can fail. `validation/mutation_check.py`
breaks one rule at a time in the database scripts and runs the suite:

| Rule broken | Result |
|---|---|
| R3: an approver may decide on their own request | caught (1 test fails) |
| R3/R6: region ignored | caught (28) |
| R12: no row version check | caught (2) |
| An extra transition (cancel a submitted request) | caught (5) |
| R4: reasons not required | caught (5) |
| R1: a completed, unverified action no longer blocks a duplicate | caught (1) |
| R10: requesters see closed actions of their region | caught (3) |
| R6: completion before the start accepted | caught (1) |

The R1 case was missed by the first version of the suite; the test
`test_completed_but_not_verified_still_blocks` was added for it.

## Visual review

The screens were checked in the browser and in the walkthrough screenshots. Problems found and fixed:

- The sign-in form did nothing: the app cleared the whole session state, including the submitted form, before
  the sign-in page read it.
- The reason of a return kept showing after the request moved on (even on verified actions); it now shows only
  while it explains the current status.
- The comparison between versions was below the fold; it is now at the top while the request waits for a decision.
- Indicator values were truncated, empty dates showed "None", the history showed "nan" and action type codes.

## Limitations

- Local only: Windows authentication, so the app connects as the developer, not through the `portal_app` role.
  A production login also needs a read-only user in NorthGridOps (`database/07_security.sql`).
- No login throttling or session timeout: not in the approved requirements.
- Working days without a holiday calendar.
- The demo data is synthetic; the indicator values describe the seeded scenario, not a real operation.
- The screenshots show one browser size; mobile layout was out of scope.
