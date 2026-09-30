"""Group flat AI-extracted entries (one per date+category) into per-day timesheet rows,
matching the paper timesheet template's layout: one line per day, hours split into
Regular/Overtime/Sick/Holiday columns, locations collected into Notes.
"""
from collections import OrderedDict
from datetime import datetime

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CATEGORIES = ("regular", "overtime", "sick", "holiday")


def _as_dict(e) -> dict:
    return e if isinstance(e, dict) else e.model_dump()


def build_rows(entries) -> list[dict]:
    by_date: "OrderedDict[str, dict]" = OrderedDict()
    for raw in entries:
        e = _as_dict(raw)
        row = by_date.setdefault(e["date"], {c: 0.0 for c in CATEGORIES} | {"locations": []})
        cat = e.get("category") or "regular"
        row[cat] += float(e["hours"])
        loc = (e.get("location") or "").strip()
        if loc and loc not in row["locations"]:
            row["locations"].append(loc)

    rows = []
    for d in sorted(by_date):
        r = by_date[d]
        rows.append({
            "date": d,
            "weekday": WEEKDAYS[datetime.strptime(d, "%Y-%m-%d").weekday()],
            "notes": ", ".join(r["locations"]),
            "total": round(sum(r[c] for c in CATEGORIES), 2),
            **{c: round(r[c], 2) for c in CATEGORIES},
        })
    return rows


def column_totals(rows: list[dict]) -> dict:
    return {k: round(sum(r[k] for r in rows), 2) for k in (*CATEGORIES, "total")}
