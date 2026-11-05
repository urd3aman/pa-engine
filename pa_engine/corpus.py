"""Corpus layer: the domain pack, the rules (each a verbatim quote from a source document), the golden-set cases and
the expert's grades. `verify()` proves every quote appears in its source text (whitespace-normalised).

Source documents are not all redistributed in this repository. Each source in criteria.json carries its public `url`;
download it into corpus/sources/ under the name in its `file` field and `verify` checks those quotes too.
"""
import json
import re

from .config import CORPUS, GOLDEN

norm = lambda s: re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


def _json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() or default is None else default


def domain():
    return _json(CORPUS / "domain.json")


def criteria():
    return _json(CORPUS / "criteria.json")


def cases():
    return _json(GOLDEN / "cases.json")


def grades():
    return _json(GOLDEN / "grades.json", {})


def source_text(src):
    """Normalised text of one source document, or None if it is not available locally.
    Markdown extracts get PDF page headers and markdown escapes removed."""
    path = CORPUS / src["file"] if src.get("file") else None
    if not path or not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    if src["file"].endswith(".md"):
        raw = raw.replace("\\[", "[").replace("\\]", "]").replace("\\*", "*")
        # PDF page headers land mid-sentence in extracted text; remove them before matching
        raw = re.sub(r"###\s*Page\s+\d+\s+Page\s+\d+\s+of\s+\d+\s+Coverage\s+Policy\s+Number:\s*PSM\d+", " ", raw)
    return norm(raw)


def verify():
    """Returns [(rule id, status, detail)] with status OK, MISS (fragment not found) or SKIP (source not downloaded).
    Quotes with ' ... ' are checked part by part."""
    data, cache, out = criteria(), {}, []
    for r in data["rules"]:
        if r["source"] not in cache:
            cache[r["source"]] = source_text(data["sources"][r["source"]])
        text = cache[r["source"]]
        if text is None:
            out.append((r["id"], "SKIP", data["sources"][r["source"]].get("url", "")))
            continue
        missing = [p for p in (norm(x) for x in r["quote"].split("...")) if p and p not in text]
        out.append((r["id"], "MISS" if missing else "OK", missing[0] if missing else ""))
    return out
