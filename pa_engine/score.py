"""Score engine runs against the golden set. The answer key is the drafted expected answers (cases.json) with the
expert's grades (golden_set/grades.json) laid over them wherever the expert disagreed, so re-running this after grading
re-scores instantly.

Metrics (targets: verdict >= 90%, citations 100%):
  verdict     engine verdict == key verdict
  citation    no cited id outside the supplied corpus, AND for non-MEETS cases the key's deciding rule is among the
              engine's failed_rules, AND for MEETS cases the engine names no failed rule
  flags       recall and precision over SAFETY / LABEL_POLICY_CONFLICT / SOURCE_GAP
  path recall share of the key's rule path the engine says it checked (informational)
Usage: python -m pa_engine score runs/<run>.json [more runs...]   -> prints and writes runs/<run>_SCORECARD.md
"""
import json
from pathlib import Path

from . import corpus


def key():
    cases, grades = corpus.cases()["cases"], corpus.grades()
    k = {}
    for c in cases:
        e, g = c["expected"], grades.get(c["id"])
        k[c["id"]] = {"verdict": g["verdict"] if g and g.get("agree") is False else e["verdict"],
                      "graded": bool(g), "changed": bool(g and g.get("agree") is False),
                      "failed_rule": e.get("failed_rule"), "path": e.get("path", []), "flags": set(e.get("flags", []))}
    return k, sum(1 for g in grades.values() if g)  # graded count


def score(run):
    """`run` is a run-file path or an already-loaded run dict."""
    if not isinstance(run, dict):
        run = json.loads(Path(run).read_text(encoding="utf-8"))
    k, n_graded = key()
    rows, tp, fp, fn = [], 0, 0, 0
    for r in run["results"]:
        e = k[r["id"]]
        fr = set(r.get("failed_rules", []))
        v_ok = r["verdict"] == e["verdict"]
        if e["verdict"] == "MEETS":
            decisive = not fr
        else:  # a changed key verdict keeps the drafted deciding rule only if it still fails; judge citations on that rule
            decisive = bool(e["failed_rule"]) and e["failed_rule"] in fr
        c_ok = decisive and not r.get("bad_citations") and r["verdict"] != "ENGINE_ERROR"  # an error is never a correct citation
        flags = set(r.get("flags", []))
        tp, fp, fn = tp + len(flags & e["flags"]), fp + len(flags - e["flags"]), fn + len(e["flags"] - flags)
        path = set(e["path"])
        recall = len(path & set(r.get("rules_checked", []))) / len(path) if path else None
        rows.append((r["id"], e["verdict"], r["verdict"], v_ok, e["failed_rule"] or "-", ",".join(sorted(fr)) or "-",
                     c_ok, ",".join(sorted(e["flags"])) or "-", ",".join(sorted(flags)) or "-", recall, r.get("seconds")))
    n = len(rows)
    v = sum(x[3] for x in rows)
    c = sum(x[6] for x in rows)
    recalls = [x[9] for x in rows if x[9] is not None]
    secs = [x[10] for x in rows if x[10]]
    summary = {"model": run.get("model"), "cases": n, "verdict_acc": v / n, "citation_acc": c / n,
               "flag_recall": tp / (tp + fn) if tp + fn else 1.0, "flag_precision": tp / (tp + fp) if tp + fp else 1.0,
               "path_recall": sum(recalls) / len(recalls) if recalls else 0, "median_s": sorted(secs)[len(secs) // 2] if secs else 0,
               "wall_s": run.get("wall_seconds"), "engine": run.get("engine", "?"), "graded": n_graded, "total": len(k),
               "errors": sum(1 for r in run["results"] if r["verdict"] == "ENGINE_ERROR"),
               "votes": run.get("votes", 1),
               "unanimous": sum(1 for r in run["results"] if r.get("stability") == 1),
               "split": [(r["id"], r["votes"], r.get("tie", False)) for r in run["results"] if r.get("votes") and r.get("stability", 1) < 1]}
    return summary, rows


def markdown(run_path, s, rows):
    key_note = (f"Expert graded {s['graded']}/{s['total']} cases; expert verdicts override the drafted answers." if s["graded"]
                else "**Key = drafted answers (not yet graded by the expert).** Re-run score after grading.")
    if s["errors"]:
        key_note += (f"\n\n**⚠ {s['errors']} engine error(s): this run is incomplete, and errors count as wrong.** "
                     f"Re-run them with `python -m pa_engine retry {Path(run_path).as_posix()}`.")
    out = [f"# PA_Engine scorecard: {Path(run_path).name} (engine {s['engine']})", "", key_note, "",
           "| Metric | Result | Target |", "|---|---|---|",
           f"| Verdict accuracy | **{s['verdict_acc']:.0%}** ({round(s['verdict_acc'] * s['cases'])}/{s['cases']}) | ≥ 90% |",
           f"| Citation accuracy | **{s['citation_acc']:.0%}** ({round(s['citation_acc'] * s['cases'])}/{s['cases']}) | 100% |",
           f"| Flag recall / precision | {s['flag_recall']:.0%} / {s['flag_precision']:.0%} | 100% / – |",
           f"| Rule-path recall | {s['path_recall']:.0%} | informational |",
           f"| Speed | median {s['median_s']} s per case; {s['wall_s']} s wall time for {s['cases']} cases | – |", "",
           "| Case | Key | Engine | ✓ | Key's deciding rule | Engine's failed rules | Cite ✓ | Key flags | Engine flags |",
           "|---|---|---|---|---|---|---|---|---|"]
    for x in rows:
        out.append(f"| {x[0]} | {x[1]} | {x[2]} | {'✓' if x[3] else '✗'} | {x[4]} | {x[5]} | {'✓' if x[6] else '✗'} | {x[7]} | {x[8]} |")
    if s["votes"] > 1:
        out += ["", f"## Stability ({s['votes']} votes per case)",
                f"**{s['unanimous']}/{s['cases']} cases unanimous.** Split cases (majority shown above; a tie is routed to a human as MISSING_INFO):", ""]
        out += [f"- {cid}: " + ", ".join(f"{v} ×{n}" for v, n in votes.items()) + (" **(tie)**" if tie else "")
                for cid, votes, tie in s["split"]] or ["- none"]
    return "\n".join(out) + "\n"


def write(run_path):
    s, rows = score(run_path)
    md = markdown(run_path, s, rows)
    Path(run_path).with_name(Path(run_path).stem + "_SCORECARD.md").write_text(md, encoding="utf-8")
    return s, md
