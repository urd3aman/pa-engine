# Run-by-run results

Claude Sonnet via the Claude Code CLI, 30 synthetic cases, answer key graded by the author (30/30 cases graded; one ruling, GS-09,
recorded as the reviewer interpretation INT-TX-TNF). Run numbers below are renumbered 1–6 for readability; the build-log run is in brackets.

| Run | Engine change | Verdicts | Citations | Flags R / P | What happened |
|---|---|---|---|---|---|
| 1 [run5] | Model does dates | 30/30 | 30/30 | 100% / 86% | Extra SAFETY flags from date slips |
| 2 [run6] | Plain-code dates (default since) | 30/30 | 30/30 | 100% / 100% | Date errors gone |
| 3 [run8] | + definition tables + reviewer interpretation | 29/30 | 28/30 | 100% / 86% | GS-09 fixed by the ruling. GS-21: applied a UC-branch step to an RA patient. GS-04: cited `LBL-HUMIRA-HF` (doesn't exist); **the check layer caught it** |
| 4 [run9] | + decision-tree routing in code | 28/30 | 29/30 | 83% / 100% | GS-21 fixed; all 7 routed cases right. GS-15 and GS-30 missed on prompts byte-identical to run 3, where both were right: variance |
| 5 [run10] | + 3-vote self-consistency (90 calls) | 30/30 | 30/30 | 83% / 100% | 26/30 unanimous. 4 wrong single calls, all outvoted, all on the Missing Info boundary. GS-07 SAFETY raised by 1 of 3 votes, dropped by majority |
| 6 [run10 revote] | + SAFETY kept if any vote raises it (no new calls) | 30/30 | 30/30 | 100% / 100% | Only GS-07 changed; no false SAFETY flags added |

Haiku on the same setups (runs 5–7): 23–24/30 verdicts, 24–26/30 citations, flags 100% recall / 33–40% precision.

## Split votes in run 5 (the cases a human should review)

- GS-06: MEETS ×2 / MISSING_INFO ×1
- GS-15: MISSING_INFO ×2 / DOES_NOT_MEET ×1
- GS-16: MEETS ×2 / MISSING_INFO ×1
- GS-30: MISSING_INFO ×2 / MEETS ×1

## What the runs taught

1. Move what code can do into code: dates and routing left the prompt, and those errors stopped.
2. One run is one draw: on unchanged prompts, results swung by ±2 cases. Report a distribution.
3. Vote, and send ties to a human: the split votes marked exactly the hard cases.
4. Safety is asymmetric: a missed safety warning costs more than an extra one.
