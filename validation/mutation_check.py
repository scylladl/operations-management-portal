"""
Checks that the tests catch broken rules: breaks one rule at a time in the database scripts, runs the suite, and
restores the file. Every mutant must make at least one test fail.

    python validation/mutation_check.py
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

# (file, text to break, replacement, rule it breaks)
MUTANTS = [
    ("database/03_functions.sql", "AND (t.MustNotBeOwner = 0 OR a.RequesterId IS NULL OR a.RequesterId <> @ActorUserId)",
     "", "R3: nobody decides on their own request"),
    ("database/03_functions.sql", "AND (u.RoleCode = 'ADM' OR u.RegionCode = a.RegionCode)", "", "R3/R6: region"),
    ("database/04_action_procedures.sql",
     "IF @CurrentRowVer <> @RowVer\n            THROW 50003, 'This action changed since you opened it. Reload it to see its current state.', 1;",
     "", "R12: concurrent edits"),
    ("database/01_schemas_reference.sql",
     "('CANCEL',   'Approved',   'APR', 'Cancelled',  N'Cancel',            1, 0, 0),",
     "('CANCEL',   'Approved',   'APR', 'Cancelled',  N'Cancel',            1, 0, 0),\n"
     "    ('CANCEL',   'Submitted',  'APR', 'Cancelled',  N'Cancel',            1, 0, 0),", "workflow: extra transition"),
    ("database/04_action_procedures.sql", "IF @RequiresReason = 1 AND @Reason IS NULL", "IF 1 = 0", "R4: reasons"),
    ("database/02_tables.sql", "OR (Status = 'Completed' AND IsHistorical = 0) THEN 0 ELSE ActionId END PERSISTED",
     "THEN 0 ELSE ActionId END PERSISTED", "R1: completed actions are open"),
    ("database/03_functions.sql", "OR (u.RoleCode = 'REQ' AND a.RegionCode = u.RegionCode AND s.IsOpen = 1)",
     "OR (u.RoleCode = 'REQ' AND a.RegionCode = u.RegionCode)", "R10: visibility"),
    ("database/04_action_procedures.sql", "IF @TransitionCode = 'COMPLETE' AND @EventDate < @StartDate", "IF 1 = 0",
     "R6: completion date"),
]

missed = 0
for path, old, new, rule in MUTANTS:
    target = ROOT / path
    original = target.read_text(encoding="utf-8")
    if original.count(old) != 1:
        sys.exit(f"{rule}: the text to break is not in {path} exactly once; update this script")
    target.write_text(original.replace(old, new), encoding="utf-8")
    try:
        run = subprocess.run([str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                             capture_output=True, text=True)
    finally:
        target.write_text(original, encoding="utf-8")
    caught = run.returncode != 0
    missed += not caught
    print(f"{rule:42} {'caught' if caught else 'MISSED'}: {run.stdout.strip().splitlines()[-1]}")
sys.exit(1 if missed else 0)
