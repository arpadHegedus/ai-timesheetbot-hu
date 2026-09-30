"""Firestore persistence: users/{email}/reports/{id}. Only the raw entries are stored (a few
hundred bytes); the PDF is regenerated on demand from them rather than stored as a binary blob.
"""
from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore


@lru_cache
def _db() -> firestore.Client:
    return firestore.Client()  # credentials from GOOGLE_APPLICATION_CREDENTIALS


def _col(owner: str):
    return _db().collection("users").document(owner).collection("reports")


def save_report(owner: str, period: str, entries: list[dict], total: float) -> str:
    _, ref = _col(owner).add({
        "period": period,
        "entries": entries,
        "entries_count": len(entries),
        "total": total,
        "created_at": datetime.now(timezone.utc),
    })
    return ref.id


def list_reports(owner: str, limit: int = 50) -> list[dict]:
    q = (_col(owner).order_by("created_at", direction=firestore.Query.DESCENDING)
         .limit(limit).select(["period", "total", "entries_count", "created_at"]))
    return [{"id": d.id, **{k: (v.isoformat() if k == "created_at" else v) for k, v in d.to_dict().items()}}
            for d in q.stream()]


def get_report(owner: str, report_id: str) -> dict | None:
    doc = _col(owner).document(report_id).get()
    if not doc.exists:
        return None
    return doc.to_dict()


def delete_report(owner: str, report_id: str) -> bool:
    ref = _col(owner).document(report_id)
    if not ref.get().exists:
        return False
    ref.delete()
    return True
