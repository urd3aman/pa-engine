"""Offline tests (no model calls). Run:  python -m unittest discover -s tests -t . -v"""
import json
import unittest

from pa_engine import corpus, dates, decide, score
from pa_engine.retrieve import retrieve

CRIT, DOM, DATA = corpus.criteria(), corpus.domain(), corpus.cases()
CASE = {c["id"]: c for c in DATA["cases"]}
REVIEW = DATA["review_date"]


def blind(cid):
    return {k: CASE[cid][k] for k in DOM["request_fields"]}


class Corpus(unittest.TestCase):
    def test_no_quote_is_missing_from_a_downloaded_source(self):
        self.assertEqual([r for r, status, _ in corpus.verify() if status == "MISS"], [])

    def test_reviewer_ruling_is_verified_from_the_bundled_source(self):
        self.assertIn(("INT-TX-TNF", "OK", ""), corpus.verify())

    def test_every_source_is_bundled_or_linked(self):
        for sid, s in CRIT["sources"].items():
            self.assertTrue(s.get("url") or (corpus.CORPUS / s["file"]).exists(), sid)

    def test_every_case_cites_existing_rules(self):
        ids = {r["id"] for r in CRIT["rules"]}
        for c in DATA["cases"]:
            e = c["expected"]
            for rid in e.get("path", []) + e.get("label_rules", []) + [e.get("failed_rule")]:
                if rid:
                    self.assertIn(rid, ids, c["id"])


class Retrieve(unittest.TestCase):
    def test_texas_rinvoq_gets_its_definition_tables(self):
        ids = [r["id"] for r in retrieve(CRIT, DOM, blind("GS-06"))[0]]
        for rid in ("TX-RIN-9", "TX-DEF-POTENT", "TX-DEF-CYP3A4", "TX-DEF-TNF", "LBL-RIN-IND"):
            self.assertIn(rid, ids)
        self.assertFalse(any(i.startswith(("AET-", "CIG-")) for i in ids))

    def test_reviewer_interpretation_reaches_texas_tnf_steps_only(self):
        self.assertIn("INT-TX-TNF", [r["id"] for r in retrieve(CRIT, DOM, blind("GS-09"))[0]])
        for cid in ("GS-13", "GS-14", "GS-19"):  # Cigna / Aetna requests never get a Texas ruling
            self.assertNotIn("INT-TX-TNF", [r["id"] for r in retrieve(CRIT, DOM, blind(cid))[0]])

    def test_aetna_gets_no_texas_rules(self):
        ids = [r["id"] for r in retrieve(CRIT, DOM, blind("GS-14"))[0]]
        self.assertTrue(ids and not any(i.startswith("TX-") for i in ids))


class Route(unittest.TestCase):
    def test_routing_never_prunes_a_rule_the_answer_needs(self):
        for c in DATA["cases"]:
            kept = {r["id"] for r in retrieve(CRIT, DOM, blind(c["id"]))[0]}
            e = c["expected"]
            for rid in e.get("path", []) + e.get("label_rules", []) + [e.get("failed_rule")]:
                if rid:
                    self.assertIn(rid, kept, f'{c["id"]} lost {rid}')

    def test_ra_case_drops_the_uc_branch_and_its_table(self):  # GS-21: the run-8 routing slip
        rules, _, info = retrieve(CRIT, DOM, blind("GS-21"))
        ids = {r["id"] for r in rules}
        self.assertFalse(ids & {"TX-HUM-3", "TX-HUM-9", "TX-HUM-11", "TX-DEF-CONV-UC"})
        self.assertEqual(info["trees"]["TX-HUM"]["path"], ["#1", "#6", "#12", "#13", "#14", "#15", "#16"])

    def test_uc_case_keeps_the_uc_branch(self):
        ids = {r["id"] for r in retrieve(CRIT, DOM, blind("GS-22"))[0]}
        self.assertTrue({"TX-HUM-3", "TX-HUM-9", "TX-HUM-11", "TX-DEF-CONV-UC"} <= ids and not ids & {"TX-HUM-1", "TX-HUM-6"})

    def test_unpruned_cases_get_no_routing_line(self):
        from pa_engine.route import describe
        for cid in ("GS-06", "GS-14", "GS-25"):  # single-entry Texas trees, Aetna
            self.assertEqual(describe(retrieve(CRIT, DOM, blind(cid))[2]), "")


class Dates(unittest.TestCase):
    def test_window_starts(self):
        w = dates.windows(REVIEW)
        self.assertEqual((w[90], w[180]), ("2026-08-04", "2026-05-06"))

    def test_fill_inside_window(self):  # GS-22: 30-day fill from 2026-04-25 has 19 days inside the 180-day window
        facts, _ = dates.annotate(CASE["GS-22"]["facts"], REVIEW)
        self.assertIn("180-day 19", " ".join(facts["claims"]))


class DecideAndCheck(unittest.TestCase):
    def fake(self, reply):
        return lambda prompt, role, model: reply

    def test_valid_reply_passes_check_with_evidence(self):
        reply = json.dumps({"verdict": "DOES_NOT_MEET", "failed_rules": ["TX-HUM-11"], "rules_checked": ["TX-HUM-3", "TX-HUM-11"],
                            "label_rules": [], "flags": [], "rationale": "19 < 30 days", "next_step": "x"})
        out = decide.decide(blind("GS-22"), CRIT, DOM, REVIEW, "sonnet", call=self.fake(reply))
        self.assertEqual((out["verdict"], out["bad_citations"]), ("DOES_NOT_MEET", []))
        self.assertIn("30-day trial", out["evidence"]["TX-HUM-11"])

    def test_invented_rule_is_caught(self):
        reply = json.dumps({"verdict": "MEETS", "failed_rules": [], "rules_checked": ["TX-RIN-99"], "label_rules": [], "flags": ["MADE_UP"]})
        out = decide.decide(blind("GS-06"), CRIT, DOM, REVIEW, "sonnet", call=self.fake(reply))
        self.assertEqual((out["bad_citations"], out["flags"]), (["TX-RIN-99"], []))

    def test_usage_limit_stops_the_run(self):
        decide.LIMIT.clear()
        out = decide.decide(blind("GS-01"), CRIT, DOM, REVIEW, "sonnet", call=self.fake("You've hit your 5-hour limit · resets 6:40pm"))
        self.assertTrue(out["error"].startswith("USAGE_LIMIT") and decide.LIMIT.is_set())
        nxt = decide.decide(blind("GS-02"), CRIT, DOM, REVIEW, "sonnet", call=self.fake("{}"))
        self.assertIn("skipped", nxt["error"])
        decide.LIMIT.clear()

    def test_expected_answers_never_reach_the_model(self):
        seen = []
        decide.decide(blind("GS-10"), CRIT, DOM, REVIEW, "sonnet", call=lambda p, r, m: seen.append(p) or "{}")
        self.assertNotIn(CASE["GS-10"]["expected"]["rationale"][:60], seen[0])
        self.assertNotIn("LABEL_POLICY_CONFLICT\"]", seen[0])


class Vote(unittest.TestCase):
    S = lambda self, v, flags=(), fr=(), err=None: dict({"id": "GS-X", "verdict": v, "flags": list(flags), "failed_rules": list(fr), "seconds": 1},
                                                    **({"error": err} if err else {}))

    def test_majority_wins_and_records_stability(self):
        out = decide.vote([self.S("MEETS"), self.S("MISSING_INFO", fr=["A"]), self.S("MEETS")])
        self.assertEqual((out["verdict"], out["votes"], out["stability"], out["tie"]), ("MEETS", {"MEETS": 2, "MISSING_INFO": 1}, 0.67, False))
        self.assertEqual(len(out["samples"]), 3)

    def test_three_way_split_goes_to_a_human(self):
        out = decide.vote([self.S("MEETS"), self.S("DOES_NOT_MEET", fr=["A"]), self.S("MISSING_INFO", fr=["B"])])
        self.assertEqual((out["verdict"], out["tie"], out["failed_rules"]), ("MISSING_INFO", True, ["A", "B"]))

    def test_flags_need_a_majority(self):
        out = decide.vote([self.S("MEETS", ["SAFETY"]), self.S("MEETS", ["SAFETY", "SOURCE_GAP"]), self.S("MEETS")])
        self.assertEqual(out["flags"], ["SAFETY"])

    def test_safety_is_kept_if_any_sample_raises_it(self):  # GS-07 in run 10: SAFETY raised by 1 of 3
        samples = [self.S("DOES_NOT_MEET", fr=["A"]), self.S("DOES_NOT_MEET", fr=["A"]), self.S("DOES_NOT_MEET", ["SAFETY", "SOURCE_GAP"], ["A"])]
        self.assertEqual(decide.vote(samples)["flags"], [])
        self.assertEqual(decide.vote(samples, any_flags=DOM["any_vote_flags"])["flags"], ["SAFETY"])  # SOURCE_GAP still needs a majority

    def test_usage_limit_marks_case_for_retry_and_errors_are_skipped(self):
        out = decide.vote([self.S("MEETS"), self.S("ENGINE_ERROR", err="USAGE_LIMIT: x"), self.S("MEETS")])
        self.assertEqual(out["verdict"], "ENGINE_ERROR")
        out = decide.vote([self.S("MEETS"), self.S("ENGINE_ERROR", err="ValueError"), self.S("DOES_NOT_MEET", fr=["A"])])
        self.assertTrue(out["tie"])  # 1 vs 1 among usable samples -> human


class Score(unittest.TestCase):
    def perfect_run(self):
        """A run that answers every case exactly as the key does."""
        return {"model": "test", "results": [
            {"id": c["id"], "verdict": c["expected"]["verdict"], "flags": c["expected"].get("flags", []),
             "failed_rules": [c["expected"]["failed_rule"]] if c["expected"]["verdict"] != "MEETS" else [],
             "rules_checked": c["expected"].get("path", []), "bad_citations": []} for c in DATA["cases"]]}

    def test_perfect_run_scores_100(self):
        s, _ = score.score(self.perfect_run())
        self.assertEqual((s["verdict_acc"], s["citation_acc"], s["flag_recall"], s["flag_precision"]), (1.0, 1.0, 1.0, 1.0))

    def test_one_wrong_verdict_and_one_invented_citation(self):
        run = self.perfect_run()
        run["results"][0]["verdict"] = "MISSING_INFO"           # GS-01 wrong verdict
        run["results"][1]["bad_citations"] = ["TX-HUM-99"]      # GS-02 cites a rule that wasn't supplied
        s, _ = score.score(run)
        self.assertAlmostEqual(s["verdict_acc"], 29 / 30)
        self.assertAlmostEqual(s["citation_acc"], 29 / 30)


if __name__ == "__main__":
    unittest.main()
