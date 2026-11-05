"""Retrieve layer (plain code): which rules apply to one request.

1. Source: the domain's source_pattern finds the payer source id in the request (e.g. "(S43)").
2. Subject: the first domain subject named in the request (e.g. molecule "upadacitinib").
3. Rules for that source and subject, plus every rule from sources that always apply (FDA labels, prefix "L-").
   Then route.py keeps only the decision-tree branch for the patient's diagnosis.
4. Definition rules (the payer's supporting tables) and reviewer interpretation rules whenever a supplied rule uses a term they cover.
"""
import re

from .route import route


def retrieve(crit, dom, request):
    m = re.search(dom["source_pattern"], request[dom["source_field"]])
    src = m.group(1) if m else None
    subject = next((s for s in dom["subjects"] if s in request[dom["subject_field"]].lower()), None)
    always = dom.get("always_include_source_prefix")
    rules = [r for r in crit["rules"] if r.get("kind") not in ("definition", "interpretation") and r["drug"] == subject
             and (r["source"] == src or (always and r["source"].startswith(always)))]
    rules, info = route(rules, request, dom)  # keep only the decision-tree branch for the patient's diagnosis
    text = " ".join(r["quote"].lower() for r in rules)
    # definitions (payer tables) and reviewer interpretations attach when a supplied rule uses a term they cover
    rules += [r for r in crit["rules"] if r.get("kind") in ("definition", "interpretation")
              and (r["source"] if r["kind"] == "definition" else r.get("applies_to_source")) == src
              and any(t.lower() in text for t in r.get("defines", []))]
    used = sorted({r["source"] for r in rules})
    return rules, [f'{s} = {crit["sources"][s]["title"]} ({crit["sources"][s].get("version", "")})' for s in used], info
