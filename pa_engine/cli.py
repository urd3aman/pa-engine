"""Command line:  python -m pa_engine <command>

  run     [--model sonnet] [--set clean|messy] [--cases GS-01,GS-07] [--no-dates] [--votes 3] [--out runs/x.json] [--workers 5]
  retry   runs/x.json          re-run only the ENGINE_ERROR cases of a run (e.g. after a usage limit resets)
  revote  runs/x.json [--out]  re-apply the current voting flag rule to a voted run's saved samples (no model calls)
  score   runs/x.json [...]    score runs against the golden set (expert grades override drafts) -> *_SCORECARD.md
  verify                       prove every rule quote is verbatim in its (downloaded) source document
  cases   [--set messy]        list golden-set cases
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__, corpus, decide, score
from .config import RUNS


def _run(ids, model, use_dates, workers, out, prior=None, votes=1):
    crit, dom, data = corpus.criteria(), corpus.domain(), corpus.cases()
    blind = [{k: c[k] for k in dom["request_fields"]}  # expected answers never reach the model
             for c in data["cases"] if c["id"] in ids]
    t0 = time.time()
    tasks = [c for c in blind for _ in range(votes)]  # each case `votes` times, spread across the workers
    with ThreadPoolExecutor(workers) as ex:
        flat = list(ex.map(lambda c: decide.decide(c, crit, dom, data["review_date"], model, use_dates), tasks))
    results = [flat[i * votes] if votes == 1 else decide.vote(flat[i * votes:(i + 1) * votes], any_flags=dom.get("any_vote_flags", [])) for i in range(len(blind))]
    if prior:
        new = {x["id"]: x for x in results}
        results = [new.get(x["id"], x) for x in prior["results"]]
    for x in results:
        v = f' votes={x["votes"]}' if x.get("votes") else ""
        print(f'{x["id"]}  {x["verdict"]:<14} fail={",".join(x.get("failed_rules", [])) or "-":<22} '
              f'flags={",".join(x.get("flags", [])) or "-":<24} {x["seconds"]}s{v}')
    engine = f'{__version__}{"+dates" if use_dates else ""}{f"+vote{votes}" if votes > 1 else ""}'
    out.write_text(json.dumps({"model": model, "engine": engine, "domain_version": dom.get("version"), "use_dates": use_dates, "votes": votes,
                               "wall_seconds": round(time.time() - t0, 1), "results": results}, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\nsaved {out}")
    if decide.LIMIT.is_set():
        print(f"STOPPED: usage limit hit. After it resets, run:  python -m pa_engine retry {out}")
    return out


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="pa_engine", description="PA_Engine v" + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--model", default="sonnet")
    r.add_argument("--set", default="", help="clean or messy (default: all)")
    r.add_argument("--cases", default="")
    r.add_argument("--no-dates", action="store_true", help="let the model do date arithmetic itself")
    r.add_argument("--out", default="")
    r.add_argument("--workers", type=int, default=5)
    r.add_argument("--votes", type=int, default=1, help="self-consistency: decide each case N times, majority wins (3 recommended)")
    t = sub.add_parser("retry")
    t.add_argument("run_file")
    t.add_argument("--workers", type=int, default=5)
    v = sub.add_parser("revote")
    v.add_argument("run_file")
    v.add_argument("--out", default="")
    s = sub.add_parser("score")
    s.add_argument("run_files", nargs="+")
    sub.add_parser("verify")
    c = sub.add_parser("cases")
    c.add_argument("--set", default="")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        want = set(filter(None, a.cases.split(",")))
        ids = [x["id"] for x in corpus.cases()["cases"]
               if (not want or x["id"] in want) and (not a.set or x.get("set", "clean") == a.set)]
        RUNS.mkdir(exist_ok=True)
        out = Path(a.out) if a.out else RUNS / f"run_{a.model}_{time.strftime('%Y%m%d_%H%M%S')}.json"
        out = _run(ids, a.model, not a.no_dates, a.workers, out, votes=a.votes)
        print(score.write(out)[1])
    elif a.cmd == "retry":
        prior = json.loads(Path(a.run_file).read_text(encoding="utf-8"))
        ids = [x["id"] for x in prior["results"] if x["verdict"] == "ENGINE_ERROR"]
        print(f"retrying {len(ids)} errored case(s) with {prior['model']}")
        if ids:
            out = _run(ids, prior["model"], prior.get("use_dates", "dates" in str(prior.get("engine"))), a.workers, Path(a.run_file), prior,
                       votes=prior.get("votes", 1))
            print(score.write(out)[1])
    elif a.cmd == "revote":
        run = json.loads(Path(a.run_file).read_text(encoding="utf-8"))
        anyf = corpus.domain().get("any_vote_flags", [])
        changed = []
        for r in run["results"]:
            ok = [x for x in r.get("samples", []) if x.get("verdict") != "ENGINE_ERROR"]
            if ok and r["verdict"] != "ENGINE_ERROR":
                new = decide.vote_flags(ok, anyf)
                if new != r.get("flags"):
                    changed.append(f'{r["id"]}: {r.get("flags")} -> {new}')
                r["flags"] = new
        run["flags_rule"] = {"majority": True, "any_vote_flags": anyf, "revoted_from": Path(a.run_file).name}
        out = Path(a.out) if a.out else Path(a.run_file).with_name(Path(a.run_file).stem + "_revote.json")
        out.write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")
        print("\n".join(changed) or "no flag changes", f"\nsaved {out}")
        print(score.write(out)[1])
    elif a.cmd == "score":
        for p in a.run_files:
            print(score.write(p)[1])
    elif a.cmd == "verify":
        res = corpus.verify()
        for rid, status, detail in res:
            print(f"{status:<4} {rid}" + (f"  → {detail[:90]}" if detail else ""))
        n = {k: sum(1 for _, s, _ in res if s == k) for k in ("OK", "MISS", "SKIP")}
        print(f"\n{n['OK']} verified verbatim, {n['MISS']} missing, {n['SKIP']} skipped (source not downloaded; see its url)")
        return 1 if n["MISS"] else 0
    elif a.cmd == "cases":
        for x in corpus.cases()["cases"]:
            if not a.set or x.get("set", "clean") == a.set:
                print(f'{x["id"]}  {x.get("set", "clean"):<5}  {x["payer"]:<32} {x["drug"]:<42} expected {x["expected"]["verdict"]}')
    return 0
