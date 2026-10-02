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


class CompareResults(unittest.TestCase):
    """Uses the sealed results (and a COPY of its evidence configuration relabelled as an LLM one) purely to test the comparison tool's logic - not a result."""

    def test_blocked_configurations_stay_blocked(self):
        import phase12_compare_results as CR
        r = json.loads(RES.read_text(encoding="utf-8"))
        c = CR.build(r, r)
        self.assertTrue(c["provenance"]["equals_frozen_hash"])
        self.assertEqual((c["configs"]["ollama"]["status"], c["configs"]["ollama_raw"]["status"]), ("BLOCKED", "BLOCKED"))
        self.assertEqual(c["review"], {})
        self.assertEqual(c["parity_with_sealed_extractive_run"]["baseline"]["differences"], 0)
        self.assertIn("BLOCKED", CR.markdown(c))

    def test_parity_reports_a_difference_and_review_flags_unsupported_answers(self):
        import copy
        import phase12_compare_results as CR
        sealed = json.loads(RES.read_text(encoding="utf-8"))
        r = copy.deepcopy(sealed)
        qid = next(k for k, v in r["configs"]["baseline"]["per_query"].items() if v["real"]["status"] != "answered")
        r["configs"]["baseline"]["per_query"][qid]["real"]["status"] = "answered"
        self.assertEqual(CR.parity(r, sealed)["baseline"]["differences"], 1)
        r["configs"]["ollama"] = copy.deepcopy(r["configs"]["baseline"])
        rv = CR.build(r, sealed)["review"]["ollama"]
        self.assertTrue(any("unsupported_question_answered" in f["flags"] for f in rv["flagged"]))
        self.assertTrue(all(a["status"] == "answered" for a in rv["all_answered"]))


STORES = (ROOT / "data" / "vector_store" / "page_collection").exists()


class CountingClient:
    """Stand-in for an LLM client in PLUMBING tests only (never used for any recorded result)."""

    def __init__(self, text="The answer is 42. [S1]", exc=None):
        self.calls, self.text, self.exc = 0, text, exc

    def generate(self, prompt):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.text


class RequireOllama(unittest.TestCase):
    def test_require_ollama_stops_before_any_work_when_not_ready(self):
        import tempfile
        import phase12_ollama_check as OC
        if OC.check()["ready"]:
            self.skipTest("a real Ollama is available on this machine")
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "r.json"
            self.assertEqual(EV.main(["--configs", "ollama_raw,ollama", "--require-ollama", "--out", str(out)]), 3)
            self.assertFalse(out.exists())
            self.assertFalse(Path(t, "r_performance.json").exists())

    def test_default_perf_path_never_targets_the_sealed_file_for_a_custom_out(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            Path(t, "x_performance.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(SystemExit) as c:
                EV.main(["--configs", "baseline", "--out", str(Path(t) / "x.json")])
            self.assertIn("x_performance.json", str(c.exception))

    def test_checkpoint_header_mismatch_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "c.jsonl"
            EV.Checkpoint(p, {"queries_sha256": "a", "model": "m", "configs": ["ollama"]}).put("ollama", "Q", "real", {"x": 1})
            self.assertEqual(EV.Checkpoint(p, {"queries_sha256": "a", "model": "m", "configs": ["ollama"]}).get("ollama", "Q", "real"), {"x": 1})
            with self.assertRaises(SystemExit):
                EV.Checkpoint(p, {"queries_sha256": "b", "model": "m", "configs": ["ollama"]})

    def test_error_record_is_neither_correct_nor_a_correct_abstention(self):
        q = {"type": "absent_detail", "category": "absent_detail", "id": "x"}
        r = EV.error_record(q, "oracle", "M2C-07", RuntimeError("boom"))
        self.assertEqual((r["status"], r["correct"], r["outcome"]), ("generator_error", False, "absent_detail_generator_error"))
        per = {"x": {"oracle": r}}
        m = EV.answer_metrics([dict(q, type="absent_detail")], per, "oracle")
        self.assertEqual((m["unsupported"]["correctly_abstained"], m["unsupported"]["incorrectly_answered"], m["unsupported"]["generator_errors"], m["absent_detail"]["abstained"]), (0, 0, 1, 0))


@unittest.skipUnless(STORES, "stores not built in this checkout (see Phase 11 recreate order)")
class LlmPlumbing(unittest.TestCase):
    """The evaluator's LLM path with a FAKE client: error handling, resume, no fallback. These are plumbing tests, not LLM results."""

    @classmethod
    def setUpClass(cls):
        import rag_pipeline as RP
        cls.RP = RP
        qs = EV.load_queries()
        cls.q = [x for x in qs if x["type"] == "answerable"][:3] + [x for x in qs if x["type"] == "absent_detail"][:2]
        units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))
        cls.card_url = {u["source_id"]: u["source_url"] for u in (units["units"] if isinstance(units, dict) else units)}

    def run_cfg(self, client, **kw):
        pipe = self.RP.build_pipeline(generator="ollama", llm_client=client)
        return pipe, EV.evaluate_config(pipe, self.q, {}, self.card_url, name="ollama_raw", llm=True, **kw)["per_query"]

    def test_fabricated_llm_answer_is_not_counted_correct(self):
        client = CountingClient("The answer is 42. [S1]")
        _, per = self.run_cfg(client)
        self.assertGreater(client.calls, 0)
        for r in per.values():
            for rec in (r.get("real"), r.get("oracle")):
                if rec:
                    self.assertFalse(rec["correct"])
                    self.assertEqual(rec["phantom"], 0)

    def test_raising_client_is_recorded_per_question_not_substituted(self):
        client = CountingClient(exc=ConnectionError("ollama stopped"))
        with self.assertRaises(SystemExit) as c:
            self.run_cfg(client)
        self.assertIn("consecutive generator errors", str(c.exception))
        self.assertEqual(client.calls, EV.MAX_CONSECUTIVE_ERRORS)

    def test_questions_that_never_reach_the_generator_do_not_reset_the_error_counter(self):
        pipe = self.RP.build_pipeline(generator="ollama", llm_client=CountingClient(exc=ConnectionError("down")))
        qs = EV.load_queries()
        mixed = []
        for a in [x for x in qs if x["type"] == "answerable"][:8]:
            mixed += [a, next(x for x in qs if x["type"] == "out_of_domain")]
        with self.assertRaises(SystemExit):
            EV.evaluate_config(pipe, mixed, {}, self.card_url, name="ollama", llm=True)

    def test_extractive_exceptions_are_not_swallowed(self):
        pipe = self.RP.build_pipeline(generator="extractive")
        pipe.answer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug"))
        with self.assertRaises(RuntimeError):
            EV.evaluate_config(pipe, self.q[:1], {}, self.card_url, name="baseline", llm=False)

    def test_resume_makes_no_new_llm_calls(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            hdr = {"queries_sha256": "s", "model": "fake", "configs": ["ollama_raw"]}
            c1 = CountingClient("The answer is 42. [S1]")
            _, first = self.run_cfg(c1, ckpt=EV.Checkpoint(Path(t) / "p.jsonl", hdr))
            c2 = CountingClient(exc=AssertionError("must not be called"))
            _, second = self.run_cfg(c2, ckpt=EV.Checkpoint(Path(t) / "p.jsonl", hdr))
            self.assertEqual(c2.calls, 0)
            self.assertEqual({k: v.get("real", {}).get("outcome") for k, v in first.items()}, {k: v.get("real", {}).get("outcome") for k, v in second.items()})


if __name__ == "__main__":
    unittest.main()
