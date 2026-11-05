# PA_Engine

**An LLM prior-authorization reviewer that can't invent policy.** It decides a PA request (Meets / Does Not Meet / Missing Info)
only from verbatim payer policy and FDA-label text, proves every citation exists, and is scored run by run against an
expert-graded test set.

Built by **Mohan Nadarajah**: 25+ years in pharma market access, payer analytics and specialty sales (Amgen, Merck, Cytokinetics,
IQVIA, Mayo Clinic), now building evaluated AI systems for healthcare.

> All 30 test cases are **synthetic**. No real patients, no PHI.

## How it works

```
            ┌───────────────── domain pack (swap per product) ─────────────────┐
            │ domain.json   criteria.json (52 verbatim rules)   golden_set/ (30) │
            └───────┬──────────────────────────────────────────────────┬─────┘
request ──► RETRIEVE ──► PRE-COMPUTE ──► DECIDE ──► CHECK ──► verdict + cited evidence
            plain code    plain code      1 LLM call  plain code
            rules by      date windows,   tool-less,  every cited rule id must
            payer, drug,  decision-tree   JSON out    have been supplied; quotes
            diagnosis     routing                     attached
                                          golden set + expert grades ──► SCORE ──► scorecard per run
```

| Layer | File | What it does |
|---|---|---|
| Corpus | `pa_engine/corpus.py`, `corpus/` | Domain pack, 52 rules (each a verbatim quote with source and version), `verify` proves quotes against source text |
| Retrieve | `pa_engine/retrieve.py` | Picks the payer's rules for this drug, plus FDA-label rules, payer definition tables and reviewer rulings |
| Route | `pa_engine/route.py` | Parses the payer's "Go to #n" steps into a tree and keeps only the patient's diagnosis branch |
| Pre-compute | `pa_engine/dates.py` | Look-back windows and days-supply arithmetic, annotated into the facts |
| Decide | `pa_engine/decide.py` | One model call; never sees expected answers. `call_model()` is the single swap point for another model or API |
| Check | `pa_engine/decide.py: check()` | Rejects any rule id the model wasn't given; attaches verbatim quotes as evidence |
| Vote | `pa_engine/decide.py: vote()` | Self-consistency: N samples, majority verdict, **a tie goes to a human**, SAFETY kept if any sample raises it |
| Score | `pa_engine/score.py` | Verdict accuracy, citation accuracy, flag recall/precision, stability |

Design rules: plain code wherever possible, one model call only where judgement is needed; an honest "I don't know"
(MISSING_INFO + SOURCE_GAP) instead of a guess; every change measured as a scored run.

## Results (Claude Sonnet, 30 synthetic cases, answer key graded by a market-access expert)

| Run | What changed | Verdicts | Citations | Flags recall / precision |
|---|---|---|---|---|
| 1 | Model does the date math | 30/30 | 30/30 | 100% / 86% |
| 2 | Dates moved to plain code | 30/30 | 30/30 | 100% / 100% |
| 3 | + Policy definition tables and a reviewer ruling | 29/30 | 28/30 | 100% / 86% |
| 4 | + Decision-tree routing in code | 28/30 | 29/30 | 83% / 100% |
| 5 | + 3-vote self-consistency | 30/30 | 30/30 | 83% / 100% |
| 6 | + SAFETY flag kept if any vote raises it | **30/30** | **30/30** | **100% / 100%** |

- **Single calls: 95.6% correct (86/90).** All 4 wrong calls were outvoted, and all sat on the Missing Info boundary.
- **4 of 30 cases split the vote**: exactly the ones a human reviewer should see.
- Runs 3 and 4 dipped on prompts identical to earlier runs that got them right: run-to-run variance, which is why voting was added.
- Claude Haiku on the same setups: 23–24/30 verdicts, flag precision 33–40%.

Details per run: [results/RESULTS.md](results/RESULTS.md).

**Limits, stated plainly.** 30 cases is a small set, and the cases and draft answers were written with Claude before expert grading.
The next step is a harder set written by someone else. Payer policies change; each rule records its source version.

## The test set

`golden_set/cases.json`: 20 clean cases and 10 messy ones built to trap shortcuts: a stale "CHF" on a copy-forward problem list,
a 30-day fill with only 19 days inside the window, a quantity of 60 tablets per 30 days hidden in a form, pain scored in mm vs 0–10,
"failed biologic therapy" when the rule asks for a TNF inhibitor. `golden_set/grades.json` holds the expert's grades; they override
the drafted answers wherever they disagree.

Payers covered: Texas Medicaid (S43), Cigna (S44, S45), Aetna (S46). Drugs: adalimumab, upadacitinib, risankizumab, ustekinumab, tofacitinib.

## Run it

Python 3.12+, standard library only.

```
python -m unittest discover -s tests -t . -v     # 24 offline tests, no model calls
python -m pa_engine cases                        # list the 30 cases
python -m pa_engine verify                       # check rule quotes against downloaded sources
python -m pa_engine run --votes 3                # needs the Claude Code CLI (`claude`) on PATH
python -m pa_engine score runs/<run>.json
```

**Source documents.** The 52 rule quotes are in `corpus/criteria.json`. The payer policies and FDA labels themselves are not
redistributed: each source lists its public `url`. Download one into `corpus/sources/` under the name in its `file` field, and
`verify` checks its quotes (otherwise those rules show as SKIP).

**Reuse.** Everything prior-auth-specific is in `corpus/domain.json`, `corpus/criteria.json` and `golden_set/`. Point
`PA_ENGINE_HOME` at a folder with your own three files (for example clinical-trial eligibility criteria) and the same code runs.

## License

Copyright © 2026 Mohan Nadarajah. All rights reserved. This code is published for reading and evaluation only; see [LICENSE](LICENSE).
