"""Route layer (plain code): follow a payer's decision tree so the model only sees the steps on the patient's branch.

Payer criteria written as numbered steps ("[] Yes – Go to #6  [] No – Deny") are parsed from the verbatim rule text:
  tree = rule id without its step number (TX-HUM-11 -> tree TX-HUM, step 11); next steps = every "go to #n" in the quote.
When a tree has more than one diagnosis entry step, the patient's diagnoses are detected in code (ICD-10 prefixes and names
from the domain pack) and only the matching entry steps are kept; then every step reachable from them is kept.
Fail-safe: if no diagnosis matches, or every entry matches, nothing is pruned.
"""
import json
import re

STEP = re.compile(r"^(.*)-(\d+)$")
GOTO = re.compile(r"go to #\s*(\d+)", re.I)


def detect_diagnoses(facts, dom):
    """Diagnosis names found in the request facts (ICD-10 code prefixes or name/abbreviation patterns)."""
    text = json.dumps(facts, ensure_ascii=False)
    found = []
    for d in dom.get("diagnoses", []):
        codes = any(re.search(r"\b" + re.escape(p), text) for p in d.get("icd10", []))
        names = any(re.search(p, text) for p in d.get("patterns", []))
        if codes or names:
            found.append(d["name"])
    return found


def _mentions(quote, d):
    return any(re.search(p, quote) for p in d.get("patterns", []))


def route(rules, request, dom):
    """Returns (kept rules, route info). Only rules that are numbered steps of a tree can be pruned."""
    trees = {}
    for r in rules:
        m = STEP.match(r["id"])
        if m and r.get("kind") not in ("definition", "interpretation") and not r["source"].startswith(dom.get("always_include_source_prefix", "~")):
            trees.setdefault(m.group(1), {})[int(m.group(2))] = r
    if not dom.get("routing", True) or not trees:
        return rules, None
    found = detect_diagnoses(request["facts"], dom)
    diag = {d["name"]: d for d in dom.get("diagnoses", [])}
    dropped, info = set(), {"diagnoses": found, "trees": {}}
    for tree, steps in trees.items():
        entries = [n for n, r in steps.items() if r.get("kind") == "diagnosis"]
        keep_entries = [n for n in entries if any(_mentions(steps[n]["quote"], diag[f]) for f in found)]
        if len(entries) < 2 or not keep_entries or len(keep_entries) == len(entries):
            info["trees"][tree] = "not pruned (" + ("single entry" if len(entries) < 2 else "diagnosis unclear") + ")"
            continue
        reach, todo = set(), list(keep_entries)
        while todo:
            n = todo.pop()
            if n in reach or n not in steps:
                continue
            reach.add(n)
            todo += [int(x) for x in GOTO.findall(steps[n]["quote"])]
        cut = {steps[n]["id"] for n in steps if n not in reach}
        dropped |= cut
        info["trees"][tree] = {"path": [f"#{n}" for n in sorted(reach)], "omitted": sorted(cut, key=lambda i: int(STEP.match(i).group(2)))}
    return [r for r in rules if r["id"] not in dropped], info


def describe(info):
    """One line for the prompt, so the model knows the branch was chosen in code."""
    if not info:
        return ""
    parts = [f'{t}: steps {" → ".join(v["path"])} (other branches omitted: {", ".join(v["omitted"])})'
             for t, v in info["trees"].items() if isinstance(v, dict)]
    if not parts:
        return ""
    return ("Routing computed in code from the payer's 'Go to #' links and the diagnoses found in the facts ("
            + ", ".join(info["diagnoses"]) + "): " + "; ".join(parts) + ".")
