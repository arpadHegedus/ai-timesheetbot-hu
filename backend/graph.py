"""LangGraph pipeline: chat messages -> structured timesheet entries + assistant reply."""
import re
import time
from datetime import date as date_cls
from enum import Enum
from typing import Any, TypedDict

from google import genai
from google.genai import errors, types
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

import locations
import timesheet
from config import settings


class Category(str, Enum):
    regular = "regular"
    overtime = "overtime"
    sick = "sick"
    holiday = "holiday"


class Entry(BaseModel):
    date: str  # YYYY-MM-DD
    location: str = ""  # helyszín; nem kötelező sick/holiday esetén
    hours: float
    category: Category = Category.regular


class Extraction(BaseModel):
    reply: str  # short conversational reply / clarifying question
    entries: list[Entry]  # full, current set of entries implied by the conversation
    ready: bool  # true only when every entry is complete and no question is pending


class State(TypedDict):
    messages: list[dict[str, Any]]
    reply: str
    entries: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    totals: dict[str, float]
    ready: bool


SYSTEM = (
    "Te egy munkaidő-nyilvántartó asszisztens vagy. Mindig magyarul válaszolj. "
    "A beszélgetésből vezesd a munkaidő-bejegyzések TELJES aktuális listáját "
    "(dátum ÉÉÉÉ-HH-NN formában, helyszín, órák száma, kategória). "
    "A kategória négy érték egyike: 'regular' (rendes munkaidő), 'overtime' (túlóra), "
    "'sick' (betegszabadság), 'holiday' (szabadság). Ha a felhasználó nem mond mást, a kategória 'regular'. "
    "Ha egy napon belül rendes ÉS túlóra is elhangzik, HOZZ LÉTRE KÉT KÜLÖN BEJEGYZÉST ugyanazzal a "
    "dátummal: egyet 'regular', egyet 'overtime' kategóriával, a megfelelő óraszámmal. Ha a mondatban a "
    "helyszín csak EGYSZER szerepel a két óraszámhoz (pl. 'X órát rendesen és Y órát túlórában a Z-ben'), "
    "MINDKÉT bejegyzésbe ugyanazt a helyszínt írd — ne hagyd üresen egyiket sem emiatt. "
    "'sick' és 'holiday' kategóriánál a helyszín NEM kötelező: hagyd üresen ('' érték), és SOHA ne "
    "kérdezz rá és ne várj rá — ezekhez a bejegyzésekhez a hiányzó helyszín NEM hiányzó adat. "
    "'regular' és 'overtime' esetén viszont a helyszín kötelező. "
    "A helyszínt mindig alapesetben (ragok nélkül) írd: 'Győrben' -> 'Győr', 'Pécsen' -> 'Pécs'. "
    "A relatív dátumokat (tegnap, hétfő) a mai dátumhoz képest old fel. A `date` mezőben MINDIG "
    "szigorúan ÉÉÉÉ-HH-NN formátumot használj (pl. 2026-09-28), soha pontokkal vagy perjellel tagolt "
    "alakot, még akkor sem, ha bizonytalan vagy a pontos napban — válaszd a legvalószínűbbet, és a "
    "bizonytalanságot a `reply` szövegében jelezd. "
    "Ha valami hiányzik vagy nem egyértelmű (pl. rendes/túlóránál nincs helyszín vagy nincs óraszám), "
    "tegyél fel EGY rövid tisztázó kérdést a `reply` mezőben, és állítsd a `ready` értékét false-ra. "
    "A `ready` értéke PUSZTÁN attól függ, hogy teljesek-e az adatok: ha van legalább egy bejegyzés, és "
    "MINDEN bejegyzés megfelel a fenti szabályoknak, akkor `ready` = true (akkor is, ha a felhasználó "
    "nem kérte külön). Ilyenkor röviden erősítsd meg, mit rögzítettél, és kérd, hogy ellenőrizze az összesítőt. "
    "Minden más esetben `ready` = false."
)


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_date(raw: str) -> str | None:
    """Coerce common non-ISO shapes the model occasionally emits (dots/slashes/spaces) to ISO; None if unparseable."""
    s = raw.strip()
    if _ISO_DATE.match(s):
        return s
    m = re.match(r"^(\d{4})[.\-/\s]+(\d{1,2})[.\-/\s]+(\d{1,2})\.?$", s)
    if not m:
        return None
    try:
        return date_cls(*map(int, m.groups())).isoformat()
    except ValueError:
        return None


def extract(state: State) -> dict:
    from datetime import date

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    transcript = "\n".join(f"{m.get('role', 'user')}: {m.get('text', '')}" for m in state["messages"])
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM + locations.prompt_section(),
        response_mime_type="application/json",
        response_schema=Extraction,
        temperature=0,  # deterministic extraction; this is data entry, not creative writing
    )
    contents = f"Today is {date.today().isoformat()}.\n\n{transcript}"

    # Try each configured model in order. 429 (quota) / 404 (retired) -> next model at once;
    # 503 (overloaded) -> one short retry, then next model.
    last: Exception | None = None
    for model in settings.models:
        for attempt in range(2):
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=config)
                parsed: Extraction = resp.parsed
                entries = []
                complete = True
                for e in parsed.entries:
                    norm = _normalize_date(e.date)
                    if norm is None:
                        complete = False  # unparseable date -> force a re-ask instead of showing garbage
                    loc = locations.canonical(e.location) if e.location else ""
                    if e.category in (Category.regular, Category.overtime) and not loc.strip():
                        complete = False  # worked hours need a location; sick/holiday don't
                    entries.append({**e.model_dump(), "location": loc, "date": norm or e.date})
                rows = timesheet.build_rows(entries)
                return {
                    "reply": parsed.reply,
                    "entries": entries,
                    "rows": rows,
                    "totals": timesheet.column_totals(rows),
                    # Completeness is checked deterministically here rather than trusted from the model's
                    # self-reported `ready` field, which stayed inconsistent even at temperature=0.
                    "ready": bool(parsed.entries) and complete,
                }
            except errors.APIError as e:
                last = e
                if e.code == 503 and attempt == 0:
                    time.sleep(1.5)
                    continue
                break
    raise last


_g = StateGraph(State)
_g.add_node("extract", extract)
_g.add_edge(START, "extract")
_g.add_edge("extract", END)
graph = _g.compile()
