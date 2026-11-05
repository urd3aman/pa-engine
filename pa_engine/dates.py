"""Plain-code date arithmetic (done in code, not by the model).

Annotates request facts before the model sees them:
  - every full date (YYYY-MM-DD) gets "[N days before review]" (or "after")
  - every "<N> days supply, filled <date>" gets its coverage span and the days it covers inside the 30/90/180-day windows
  - a header lists the start date of each look-back window the payer rules use
The original text is kept; annotations are appended in [brackets] so a reviewer can audit them.
"""
import re
from datetime import date, timedelta

WINDOWS = (30, 90, 180, 365, 730)
DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
SUPPLY = re.compile(r"(\d+)\s*days? supply,? filled (\d{4}-\d{2}-\d{2})")


def _d(s):
    return date(*map(int, s.split("-")))


def windows(review):
    r = _d(review)
    return {n: (r - timedelta(days=n)).isoformat() for n in WINDOWS}


def _annotate(text, r):
    def supply(m):
        days, start = int(m.group(1)), _d(m.group(2))
        end = start + timedelta(days=days - 1)
        inside = {n: max(0, (min(end, r) - max(start, r - timedelta(days=n))).days + 1) for n in (30, 90, 180)}
        return (m.group(0) + f" [covers {start} to {end}; days inside window: "
                + ", ".join(f"{n}-day {inside[n]}" for n in inside) + "]")

    text = SUPPLY.sub(supply, text)

    def stamp(m):
        try:
            d = _d(m.group(0))
        except ValueError:
            return m.group(0)
        n = (r - d).days
        return m.group(0) + (f" [{n} days before review]" if n >= 0 else f" [{-n} days after review]")

    # stamp dates that are not already inside a [covers ...] annotation
    parts = re.split(r"(\[covers [^\]]*\])", text)
    return "".join(p if p.startswith("[covers") else DATE.sub(stamp, p) for p in parts)


def annotate(facts, review):
    """Returns a copy of facts with date annotations, plus a window header line."""
    r = _d(review)

    def walk(v):
        if isinstance(v, str):
            return _annotate(v, r)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v

    header = "Look-back window start dates (computed in code): " + ", ".join(f"{n} days = {s}" for n, s in windows(review).items())
    return walk(facts), header
