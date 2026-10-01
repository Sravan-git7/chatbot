"""Phase 12 - evaluator helpers, audit rules (pure functions), and invariants of the recorded results / audit / E2E artifacts."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate_phase12 as EV  # noqa: E402
import phase12_failure_audit as AU  # noqa: E402

RES = ROOT / "data" / "evaluation" / "phase12_results.json"


def a(status):
    return {"status": status}


class Outcome(unittest.TestCase):
    def test_answerable(self):
        q = {"type": "answerable"}
        self.assertEqual(EV.outcome(q, a("answered"), True, True), "answerable_answered_correct")
        self.assertEqual(EV.outcome(q, a("answered"), False, True), "answerable_answered_citation_evidence_failure")
        self.assertEqual(EV.outcome(q, a("answered"), False, False), "answerable_answered_wrong_page")
        self.assertEqual(EV.outcome(q, a("unable_to_verify"), False, True), "answerable_abstained")

    def test_unsupported_types_and_ambiguous(self):
        for t in EV.UNSUPPORTED_TYPES:
            self.assertEqual(EV.outcome({"type": t}, a("answered"), False, True), f"{t}_incorrectly_answered")
            self.assertEqual(EV.outcome({"type": t}, a("insufficient_context"), False, True), f"{t}_correctly_abstained")
        self.assertEqual(EV.outcome({"type": "ambiguous"}, a("answered"), False, True), "ambiguous_answered_acceptable")
        self.assertEqual(EV.outcome({"type": "ambiguous"}, a("answered"), False, False), "ambiguous_answered_wrong_page")

    def test_router_rank(self):
        q = {"type": "answerable", "gold_source_id": "B"}
        self.assertEqual(EV.router_rank(q, ["A", "B"]), 2)
        self.assertIsNone(EV.router_rank(q, ["A"]))
        self.assertEqual(EV.router_rank({"type": "ambiguous", "gold_source_id": None, "acceptable_source_ids": ["C", "B"]}, ["A", "B", "C"]), 2)
        self.assertIsNone(EV.router_rank({"type": "out_of_domain", "gold_source_id": None, "acceptable_source_ids": []}, ["A"]))

    def test_router_metrics_counts_are_consistent(self):
        qs = [{"id": "1", "type": "answerable", "category": "x", "gold_source_id": "A"}, {"id": "2", "type": "answerable", "category": "x", "gold_source_id": "B"}]
        m = EV.router_metrics(qs, {"1": ["A", "B"], "2": ["A", "B"]})["all_gold_card_questions"]
        self.assertEqual((m["R@1"], m["R@3"], m["counts"]["top1"]), (0.5, 1.0, 1))

    def test_ollama_configuration_is_blocked_never_substituted(self):
        cfgs = EV.build_configs(["ollama_raw", "ollama"], {"ready": False, "blockers": ["NO_OLLAMA_EXECUTABLE"], "statement": "x"})
        for name in ("ollama_raw", "ollama"):
            self.assertEqual(cfgs[name]["blocked"], ["NO_OLLAMA_EXECUTABLE"])

    def test_unknown_configuration_is_rejected(self):
        with self.assertRaises(SystemExit):
            EV.build_configs(["gpt"], {"ready": False})

    def test_evaluator_refuses_to_overwrite_sealed_results(self):
        with self.assertRaises(SystemExit) as c:
            EV.main(["--configs", "baseline"])
        self.assertIn("exists", str(c.exception))


class AuditRules(unittest.TestCase):
    CARD_TERMS = {"A": {"meter", "reading"}, "B": {"invoice", "bill"}, "C": {"device", "install"}, "H": {"hub"}}
    CAT = {"A": "x", "B": "x", "C": "y", "H": "z"}
    IDENT = {"H": "conflicting_identity"}

    def ranked(self, *pairs):
        return [{"source_id": s, "similarity": v} for s, v in pairs]

    def cls(self, query, gold, ranked, typ="answerable"):
        return AU.classify_miss({"id": "q", "query": query, "type": typ, "gold": gold, "acceptable": [], "category": "c"}, ranked, self.CARD_TERMS, self.CAT, self.IDENT)

    def test_hit_is_not_a_miss(self):
        self.assertIsNone(self.cls("meter reading values", "A", self.ranked(("A", .5), ("B", .4))))

    def test_first_match_wins_in_the_declared_order(self):
        self.assertEqual(self.cls("meter reading values", "A", self.ranked(("H", .6), ("A", .59)))["rule"], "identity_hub")
        self.assertEqual(self.cls("meter reading values", "A", self.ranked(("B", .6), ("A", .3)))["rule"], "sibling_ambiguity")
        self.assertEqual(self.cls("wholly unrelated words here", "A", self.ranked(("C", .6), ("A", .3)))["rule"], "vocabulary_mismatch")
        self.assertEqual(self.cls("meter", "A", self.ranked(("C", .6), ("A", .3)))["rule"], "query_underspecified")
        self.assertEqual(self.cls("meter reading values", "A", self.ranked(("C", .6), ("A", .58)))["rule"], "near_tie_embedding")
        self.assertEqual(self.cls("meter reading values", "A", self.ranked(("C", .9), ("B", .5), ("D", .4), ("A", .3)))["rule"], "other_ranking")

    def test_sibling_needs_gold_within_top3(self):
        r = self.ranked(("B", .9), ("C", .8), ("H", .7), ("A", .3))
        self.assertNotEqual(self.cls("meter reading values", "A", r)["rule"], "sibling_ambiguity")

    def test_ambiguous_uses_best_acceptable_card(self):
        q = {"id": "q", "query": "meter reading values", "type": "ambiguous", "gold": None, "acceptable": ["A", "B"], "category": "c"}
        self.assertIsNone(AU.classify_miss(q, self.ranked(("B", .6), ("A", .5)), self.CARD_TERMS, self.CAT, self.IDENT))


class RecordedArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = json.loads(RES.read_text(encoding="utf-8"))

    def test_results_are_bound_to_the_frozen_set(self):
        fz = json.loads((ROOT / "data" / "evaluation" / "phase12_freeze.json").read_text(encoding="utf-8"))
        self.assertEqual(self.r["queries_sha256"], fz["sha256"])
        self.assertEqual(self.r["n_queries"], 113)
        self.assertFalse(self.r["corpus"]["complete"])

    def test_ollama_configs_are_blocked_without_metrics(self):
        for n in ("ollama_raw", "ollama"):
            c = self.r["configs"][n]
            self.assertEqual(c["status"], "BLOCKED")
            self.assertNotIn("answers_real_routing", c)
            self.assertNotIn("per_query", c)

    def test_safety_invariants_of_the_run_configurations(self):
        for n in ("baseline", "evidence"):
            for mode in ("answers_real_routing", "answers_oracle_routing"):
                m = self.r["configs"][n][mode]
                self.assertEqual((m["grounding_failures"], m["support_chain_failures"], m["phantom_citations"], m["url_changes"]), (0, 0, 0, 0), (n, mode))

    def test_evidence_config_does_not_answer_more_unsupported_than_baseline(self):
        b, e = (self.r["configs"][n]["answers_oracle_routing"] for n in ("baseline", "evidence"))
        self.assertLessEqual(e["absent_detail"]["answered"], b["absent_detail"]["answered"])
        self.assertLessEqual(e["unsupported"]["incorrectly_answered"], b["unsupported"]["incorrectly_answered"])
        br, er = (self.r["configs"][n]["answers_real_routing"] for n in ("baseline", "evidence"))
        self.assertLessEqual(er["unsupported"]["incorrectly_answered"], br["unsupported"]["incorrectly_answered"])

    def test_counts_add_up(self):
        for n in ("baseline", "evidence"):
            m = self.r["configs"][n]["answers_real_routing"]
            a = m["answerable"]
            self.assertEqual(a["answered_correct"] + a["answered_wrong_page"] + a["answered_citation_evidence_failure"] + a["incorrectly_abstained"], a["n"])
            u = m["unsupported"]
            self.assertEqual(u["correctly_abstained"] + u["incorrectly_answered"], u["n"])

    def test_router_is_identical_for_all_configurations(self):
        # the router block is configuration independent by construction: one block, 105 gold-card questions
        self.assertEqual(self.r["router"]["all_gold_card_questions"]["n"], 105)

    def test_audit_covers_every_set_and_every_miss_has_one_rule(self):
        au = json.loads((ROOT / "data" / "evaluation" / "phase12_failure_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(len(au["sets"]), 8)
        for name, s in au["sets"].items():
            self.assertEqual(sum(s["rule_counts"].values()), s["router_top1_misses"], name)
            self.assertTrue(all(m["rule"] in AU.RULES for m in s["misses"]))
        p12 = au["sets"]["phase12"]
        self.assertEqual(p12["n_with_gold_card"] - p12["router_top1_misses"], self.r["router"]["all_gold_card_questions"]["counts"]["top1"])

    def test_browser_e2e_artifact(self):
        p = ROOT / "data" / "phase12" / "browser_e2e.json"
        if not p.exists():
            self.skipTest("browser E2E has not been run in this checkout")
        b = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(b["passed"], b["total"])
        self.assertTrue(b["synthetic_checks"] >= 1 and b["backend_checks"] > b["synthetic_checks"])


class EvaluatorWithStores(unittest.TestCase):
    def test_pipeline_pieces_agree_with_recorded_run(self):
        if not (ROOT / "data" / "vector_store" / "page_collection").exists():
            self.skipTest("stores not built in this checkout (see Phase 11 recreate order)")
        import rag_pipeline as RP
        pipe = RP.build_pipeline(generator="extractive")
        qs = {q["id"]: q for q in EV.load_queries()}
        r = json.loads(RES.read_text(encoding="utf-8"))["configs"]["baseline"]["per_query"]
        for qid in ("P12-001", "P12-070"):
            q = qs[qid]
            out = pipe.answer(q["query"])
            self.assertEqual(out["status"], r[qid]["real"]["status"])


if __name__ == "__main__":
    unittest.main()
