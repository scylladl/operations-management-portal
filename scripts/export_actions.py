"""
Writes improvement_actions.csv in the layout the NorthGrid loader reads (Q7), from pub.vw_ImprovementActionExport.

    python scripts/export_actions.py [--out data/export/improvement_actions.csv]

The file replaces the spreadsheet export in telecom-operations-intelligence/data/generated; copying it there is an
operations step this script does not do.
"""
import argparse
import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portal import config, db  # noqa: E402

COLUMNS = ["ActionId", "CircuitId", "ActionTypeCode", "StartDate", "CompletionDate", "Status"]


def export(conn, target):
    rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM pub.vw_ImprovementActionExport ORDER BY ActionId").fetchall()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(["" if value is None else value for value in row])
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "data" / "export" / "improvement_actions.csv")
    args = parser.parse_args()
    conn = db.connect(config.database_settings())
    print(f"{export(conn, args.out)} actions written to {args.out}")
