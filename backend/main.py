import logging
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from typing import Any

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from google.genai import errors as genai_errors
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token
from pydantic import BaseModel

import store
import timesheet
from config import settings
from graph import Entry, graph
from pdf import build_pdf, email_period, period_label

log = logging.getLogger("timesheetbot")
app = FastAPI(title="Timesheetbot")


SESSION_TTL = 12 * 3600


def require_auth(authorization: str = Header(default="")) -> str:
    token = authorization.removeprefix("Bearer ")
    try:
        claims = jwt.decode(token, settings.SESSION_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Nincs jogosultság")
    if claims["sub"] not in settings.allowed_emails:  # whitelist changes apply immediately
        raise HTTPException(status_code=401, detail="Nincs jogosultság")
    return claims["sub"]


class GoogleLogin(BaseModel):
    credential: str  # Google ID token from Sign-In


class Chat(BaseModel):
    messages: list[dict[str, Any]]


class Submit(BaseModel):
    entries: list[Entry]


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/google")
def auth_google(body: GoogleLogin):
    try:
        info = id_token.verify_oauth2_token(body.credential, g_requests.Request(), settings.GOOGLE_CLIENT_ID)
    except ValueError:
        raise HTTPException(status_code=401, detail="Érvénytelen Google-token")
    email = info.get("email", "").lower()
    if not info.get("email_verified") or email not in settings.allowed_emails:
        raise HTTPException(status_code=403, detail=f"{email or 'Ez a fiók'} nem jogosult az alkalmazás használatára")
    token = jwt.encode({"sub": email, "exp": int(time.time()) + SESSION_TTL}, settings.SESSION_SECRET, algorithm="HS256")
    return {"token": token, "email": email}


@app.post("/chat", dependencies=[Depends(require_auth)])
def chat(body: Chat):
    try:
        out = graph.invoke({"messages": body.messages, "reply": "", "entries": [], "rows": [], "totals": {}, "ready": False})
    except genai_errors.APIError as e:
        if e.code == 429:
            raise HTTPException(status_code=429, detail="A Gemini kvótája elfogyott. Próbáld később, vagy ellenőrizd a csomagot.")
        raise HTTPException(status_code=502, detail=f"Gemini-hiba ({e.code}). Kérlek, próbáld újra.")
    return {"reply": out["reply"], "entries": out["entries"], "rows": out["rows"], "totals": out["totals"], "ready": out["ready"]}


def _send_email(to: str, month_name: str, year: int, total_hours: float, pdf: bytes) -> None:
    msg = EmailMessage()
    msg["From"] = settings.GMAIL_USER
    msg["To"] = to
    msg["Subject"] = f"Timesheets {month_name} {year} ({settings.EMPLOYEE_NAME})"
    msg.set_content(f"Hi {settings.RECIPIENT_NAME},\n\nPlease see attached my latest timesheets. I've worked {total_hours:g}hrs.\n")
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=f"timesheet-{month_name.lower()}-{year}.pdf")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as srv:
        srv.login(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD)
        srv.send_message(msg)


@app.post("/submit-report")
def submit_report(body: Submit, user: str = Depends(require_auth)):
    if not body.entries:
        raise HTTPException(status_code=422, detail="Nincs elküldhető bejegyzés")
    rows = timesheet.build_rows(body.entries)
    totals = timesheet.column_totals(rows)
    period = period_label(body.entries)  # Hungarian, used for the history list
    month_name, year = email_period(body.entries)  # English, used for the email
    pdf = build_pdf(rows, totals, period)
    try:
        _send_email(settings.REPORT_RECIPIENT or settings.GMAIL_USER, month_name, year, totals["total"], pdf)
    except Exception as e:
        log.exception("email failed")
        raise HTTPException(status_code=502, detail=f"E-mail küldési hiba: {e}")
    saved = True
    try:
        store.save_report(user, period, [e.model_dump() for e in body.entries], totals["total"])
    except Exception:
        log.exception("firestore save failed")
        saved = False  # the email went out; tell the UI the archive copy is missing
    return {"status": "success", "reportPeriod": period, "saved": saved}


@app.get("/history")
def history(user: str = Depends(require_auth)):
    try:
        return store.list_reports(user)
    except Exception:
        log.exception("firestore list failed")
        raise HTTPException(status_code=503, detail="Az előzmények jelenleg nem érhetők el")


@app.get("/reports/{report_id}/pdf")
def report_pdf(report_id: str, user: str = Depends(require_auth)):
    try:
        found = store.get_report(user, report_id)
    except Exception:
        log.exception("firestore get failed")
        raise HTTPException(status_code=503, detail="A jelentés jelenleg nem érhető el")
    if not found:
        raise HTTPException(status_code=404, detail="Nem található")
    entries = [Entry(**e) for e in found["entries"]]
    rows = timesheet.build_rows(entries)
    totals = timesheet.column_totals(rows)
    pdf = build_pdf(rows, totals, found["period"])  # regenerated on the fly from the stored entries
    filename = found["period"].replace(". ", "-").replace(" ", "-")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="munkaido-{filename}.pdf"'})


@app.delete("/reports/{report_id}")
def delete_report(report_id: str, user: str = Depends(require_auth)):
    try:
        found = store.delete_report(user, report_id)
    except Exception:
        log.exception("firestore delete failed")
        raise HTTPException(status_code=503, detail="A törlés jelenleg nem lehetséges")
    if not found:
        raise HTTPException(status_code=404, detail="Nem található")
    return {"status": "success"}
