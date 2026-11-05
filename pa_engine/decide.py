"""Decide layer (the only AI step) + Check layer (plain code).

DECIDE: a fresh, tool-less `claude -p` call (Claude Code CLI) reads only the request and the retrieved rules and
        returns one JSON object in the domain's output contract. It never sees expected answers.
        Swap `call_model()` to use the Anthropic API or another model.
CHECK:  every cited rule id must be one we supplied (so every citation carries a verified verbatim quote); anything else
        is recorded as a bad citation, never silently fixed. Unknown verdicts/flags are rejected.
"""
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import dates
from .config import RUNS
from .retrieve import retrieve
from .route import describe

CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
LIMIT = threading.Event()  # set when the model reports a usage limit; remaining cases are skipped

TASK = """Review date: {review_date}. All look-back windows count back from this date.

{request}

RULES IN THE CORPUS (verbatim quotes; cite them by id)
{rules}

{instructions}

Return exactly this JSON:
{contract}"""


def build_prompt(request, rules, sources, dom, review_date, use_dates=True, route_info=None):
    facts, header = request["facts"], ""
    if use_dates:
        facts, header = dates.annotate(facts, review_date)
    fields = {k: v for k, v in request.items() if k != "facts"}
    req = dom["request_header"].format(facts=json.dumps(facts, indent=1, ensure_ascii=False) + ("\n" + header if header else ""), **fields)
    return TASK.format(review_date=review_date, request=req,
                       rules="\n".join(f'[{r["id"]}] ({r["source"]}, {r["kind"]}) "{r["quote"]}"' for r in rules)
                       + ("\n\n" + describe(route_info) if describe(route_info) else ""),
                       instructions=dom["instructions"].format(sources="; ".join(sources) or "none"),
                       contract=dom["output_contract"].format())


def call_model(prompt, role, model):
    """Returns the model's text, or raises. Swap this function to use the Anthropic API or another model."""
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json", "--max-turns", "2", "--tools", "",
           "--no-session-persistence", "--append-system-prompt", role]
    if model:
        cmd += ["--model", model]
    RUNS.mkdir(exist_ok=True)
    r = subprocess.run(cmd, cwd=RUNS, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    try:
        return json.loads(r.stdout)["result"]
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {e} | raw: {(r.stdout or r.stderr)[-1500:]}")


def decide(request, crit, dom, review_date, model, use_dates=True, call=call_model):
    rules, sources, info = retrieve(crit, dom, request)
    out = {"id": request["id"], "seconds": 0, "supplied_rules": [x["id"] for x in rules], "route": info}
    if LIMIT.is_set():  # usage limit already hit in this run: don't burn more calls
        out.update({"verdict": "ENGINE_ERROR", "error": "USAGE_LIMIT: skipped after an earlier case hit the usage limit"})
        return out
    t0 = time.time()
    try:
        text = call(build_prompt(request, rules, sources, dom, review_date, use_dates, info), dom["role"], model)
        out["seconds"] = round(time.time() - t0, 1)
        if re.search(r"hit your .*limit", text, re.I):
            LIMIT.set()
            out.update({"verdict": "ENGINE_ERROR", "error": "USAGE_LIMIT: " + text})
            return out
        out.update(json.loads(re.search(r"\{.*\}", text, re.S).group(0)))
    except Exception as e:  # keep the error visible, never hidden
        out.update({"verdict": "ENGINE_ERROR", "error": f"{type(e).__name__}: {e}"[:2000], "seconds": round(time.time() - t0, 1)})
        return out
    return check(out, rules, dom)


def check(out, rules, dom):
    """Plain-code citation check: only supplied rule ids count; attach the verbatim quote for each."""
    quotes = {r["id"]: r["quote"] for r in rules}
    cited = set(out.get("failed_rules", [])) | set(out.get("rules_checked", [])) | set(out.get("label_rules", []))
    out["bad_citations"] = sorted(c for c in cited if c not in quotes)
    out["evidence"] = {c: quotes[c] for c in out.get("failed_rules", []) + out.get("label_rules", []) if c in quotes}
    if out.get("verdict") not in dom["verdicts"]:
        out["bad_verdict"] = out.get("verdict")
    out["flags"] = [f for f in out.get("flags", []) if f in dom["flags"]]
    return out


def vote(samples, tie_verdict="MISSING_INFO", any_flags=()):
    """Self-consistency: combine N independent decisions on one case (plain code).
    - Any sample cut off by a usage limit -> the whole case is ENGINE_ERROR, so `retry` redoes it with all N samples.
    - Other errored samples are left out of the vote; if none is usable -> ENGINE_ERROR.
    - Majority verdict wins; a tie (e.g. 1-1-1) -> tie_verdict (route to a human), never a guess.
    - The representative answer is the first sample with the winning verdict.
    - Flags: kept if most usable samples raised them, except `any_flags` (safety-first, e.g. SAFETY), kept if any sample raised them.
    - Records votes, stability (winning share) and a compact copy of every sample for audit.
    """
    compact = [{k: s.get(k) for k in ("verdict", "failed_rules", "flags", "bad_citations", "seconds", "error") if s.get(k) is not None}
               for s in samples]
    if any(str(s.get("error", "")).startswith("USAGE_LIMIT") for s in samples):
        return {"id": samples[0]["id"], "verdict": "ENGINE_ERROR", "error": "USAGE_LIMIT: case not finished (re-run with retry)",
                "seconds": round(sum(s.get("seconds", 0) for s in samples), 1), "samples": compact}
    ok = [s for s in samples if s.get("verdict") != "ENGINE_ERROR"]
    if not ok:
        return dict(samples[0], samples=compact)
    counts = {}
    for s in ok:
        counts[s["verdict"]] = counts.get(s["verdict"], 0) + 1
    top = max(counts.values())
    winners = [v for v, n in counts.items() if n == top]
    tie = len(winners) > 1
    verdict = tie_verdict if tie else winners[0]
    rep = next((s for s in ok if s["verdict"] == verdict), ok[0])
    out = dict(rep)
    out.update({"verdict": verdict, "flags": vote_flags(ok, any_flags),
                "votes": counts, "stability": round(top / len(ok), 2), "tie": tie,
                "seconds": round(sum(s.get("seconds", 0) for s in samples), 1), "samples": compact})
    if tie:
        out["failed_rules"] = sorted({r for s in ok for r in s.get("failed_rules", [])})
        out["rationale"] = "Samples disagreed (" + ", ".join(f"{v} x{n}" for v, n in counts.items()) + "); routed to a human reviewer."
    return out


def vote_flags(samples, any_flags=()):
    """Majority for each flag; flags in `any_flags` (safety-first) need only one sample."""
    counts = {}
    for s in samples:
        for f in set(s.get("flags") or []):
            counts[f] = counts.get(f, 0) + 1
    return sorted(f for f, n in counts.items() if n * 2 > len(samples) or (f in any_flags and n >= 1))
