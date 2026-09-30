"""Canonical location names + aliases (locations.json, re-read on every call so edits apply live)."""
import difflib
import json
import unicodedata
from pathlib import Path

_FILE = Path(__file__).parent / "locations.json"
CUTOFF = 0.82  # fuzzy-match strictness for typos / speech-to-text errors


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


def load() -> dict[str, list[str]]:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def prompt_section() -> str:
    locs = load()
    if not locs:
        return ""
    lines = "\n".join(f'- "{canon}" (ezek mind ide tartoznak: {", ".join(aliases)})' for canon, aliases in locs.items())
    return (
        "\n\nISMERT HELYSZÍNEK. Ha a felhasználó által említett helyszín hasonlít (elírás, becenév, "
        "ékezet nélküli vagy angol/magyar változat, félrehallás) valamelyik alábbihoz, a `location` mezőbe "
        "MINDIG a pontos, idézőjeles hivatalos nevet írd:\n" + lines +
        "\nHa a helyszín egyikhez sem hasonlít, hagyd úgy, ahogy a felhasználó mondta (ne találj ki egyezést)."
    )


def canonical(name: str) -> str:
    """Safety net after the LLM: map a returned location to its canonical name if it's close enough."""
    locs = load()
    n = _norm(name)
    index = {}
    for canon, aliases in locs.items():
        for a in [canon, *aliases]:
            index[_norm(a)] = canon
    if n in index:
        return index[n]
    close = difflib.get_close_matches(n, index.keys(), n=1, cutoff=CUTOFF)
    return index[close[0]] if close else name
