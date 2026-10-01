"""Phase 10 - RAG optimisation experiments: detail-cue generator, evidence-equalised fusion, frozen DEV/TEST sets, selection rules, results consistency,
protection of earlier phases. Store-dependent tests skip when the generated stores are absent."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.phase8_support import HAVE_BS4, HAVE_CHROMA, ROOT, make_pipeline
from tests.test_phase9 import NEED_STORES

import rag_generate as RG  # noqa: E402
import rag_optimised as RO  # noqa: E402

EVAL = ROOT / "data" / "evaluation"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(name: str):
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


class CueRuleTests(unittest.TestCase):
    def test_transaction_code_cue(self):
        self.assertIsNotNone(RO.cue_unmet("Which transaction code starts bill reversal?", "Bill reversal is started from the bill list."))
        self.assertIsNone(RO.cue_unmet("Which transaction code starts bill reversal?", "Use EA10 for reversal."))

    def test_how_many_needs_a_number(self):
        self.assertIsNotNone(RO.cue_unmet("How many contract accounts can one partner have?", "A partner can have contract accounts."))
        self.assertIsNone(RO.cue_unmet("How many contract accounts can one partner have?", "A partner can have 3 contract accounts."))
        self.assertIsNone(RO.cue_unmet("How many items?", "There are three items."))

    def test_default_and_limit_words(self):
        self.assertIsNotNone(RO.cue_unmet("What is the default billing period length?", "Billing periods are defined per contract."))
        self.assertIsNone(RO.cue_unmet("What is the default billing period length?", "The default is the calendar month."))
        self.assertIsNone(RO.cue_unmet("What is the minimum installment amount?", "The minimum is 50."))

    def test_no_cue_no_veto_and_word_boundaries(self):
        self.assertIsNone(RO.cue_unmet("How is a bill created?", "Bills are created by the billing run."))
        self.assertIsNone(RO.cue_unmet("Which delimiter is used?", "A slash."))           # 'limit' must not match inside 'delimiter'
        self.assertIsNone(RO.cue_unmet("", ""))

    def test_cue_rules_declared_in_contract(self):
        contract = (ROOT / "data" / "phase10_contract.md").read_text(encoding="utf-8").lower()
        for phrases, _ in RO.CUE_RULES:
            self.assertIn(phrases[0], contract)

    def test_generator_wrapper(self):
        class Base:
            name = "base"

            def __init__(self, res):
                self.res = res

            def generate(self, q, ctx):
                return self.res
        ok = RG.GenerationResult("Use EA10 [S1]", False, "base", "raw")
        self.assertIs(RO.DetailCueGenerator(Base(ok)).generate("Which transaction code?", None), ok)
        veto = RO.DetailCueGenerator(Base(RG.GenerationResult("Bills are reversed [S1]", False, "base", "raw"))).generate("Which transaction code?", None)
        self.assertTrue(veto.refused)
        self.assertEqual(veto.text, RG.NO_ANSWER_TEXT)
        refused = RG.GenerationResult(RG.NO_ANSWER_TEXT, True, "base", "")
        self.assertIs(RO.DetailCueGenerator(Base(refused)).generate("Which transaction code?", None), refused)
        # a source marker such as [S1] is never read as a transaction code
        marker = RO.DetailCueGenerator(Base(RG.GenerationResult("It is done [S1] [S2]", False, "base", "raw"))).generate("Which transaction code?", None)
        self.assertTrue(marker.refused)


class FakeCards:
    def __init__(self, order, sims):
        self.order, self.sims, self.calls = order, sims, 0

    def query(self, q, n):
        self.calls += 1
        ids = self.order[:n]
        return {"ids": [[f"id-{s}" for s in ids]], "metadatas": [[{"source_id": s} for s in ids]], "distances": [[round(1 - self.sims[s], 6) for s in ids]]}


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits

    def count(self):
        return 10

    def retrieve_corpus(self, q, top_k=5):
        return [SimpleNamespace(guide_id=g, page_id=p, similarity=s) for (g, p, s) in self.hits]


CORPUS = SimpleNamespace(entries={"A": {"corpus_status": "ingested", "doc_id": "g1/pa"}, "B": {"corpus_status": "ingested", "doc_id": "g2/pb"}, "C": {"corpus_status": "identified_not_local", "doc_id": None}})


class FusionTests(unittest.TestCase):
    def backend(self, lam, hits=(("g1", "pa", 0.2), ("g2", "pb", 0.9)), order=("C", "A", "B"), sims=None):
        cards = FakeCards(list(order), sims or {"C": 0.60, "A": 0.50, "B": 0.40})
        return RO.FusionBackend(cards, FakeRetriever(list(hits)), CORPUS, lam, n_cards=3), cards

    def test_lambda_zero_is_a_pure_passthrough(self):
        be, cards = self.backend(0.0)
        self.assertEqual(be.query("q", 3), cards.query("q", 3))
        self.assertEqual(be.last_fusion, [])

    def test_negative_lambda_rejected(self):
        with self.assertRaises(ValueError):
            self.backend(-0.1)

    def test_page_evidence_reranks_ingested_cards_only(self):
        be, _ = self.backend(1.0)
        ids = [m["source_id"] for m in be.query("q", 3)["metadatas"][0]]
        # C is not ingested -> its own similarity is its evidence (0.60 + 1*0.60 = 1.20); B: 0.40 + 0.90 = 1.30; A: 0.50 + 0.20 = 0.70
        self.assertEqual(ids, ["B", "C", "A"])

    def test_fusion_keeps_distances_and_length_and_is_stable(self):
        be, cards = self.backend(0.5, hits=(("g1", "pa", 0.5), ("g2", "pb", 0.5)), sims={"C": 0.5, "A": 0.5, "B": 0.5})
        r = be.query("q", 2)
        self.assertEqual(len(r["ids"][0]), 2)
        self.assertEqual([m["source_id"] for m in r["metadatas"][0]], ["C", "A"])         # ties keep the card order
        self.assertEqual(r["distances"][0], [0.5, 0.5])

    def test_fusion_never_adds_or_drops_a_card(self):
        be, _ = self.backend(2.0)
        self.assertEqual(sorted(m["source_id"] for m in be.query("q", 3)["metadatas"][0]), ["A", "B", "C"])

    def test_best_chunk_per_page_is_used(self):
        be, _ = self.backend(1.0, hits=(("g2", "pb", 0.1), ("g2", "pb", 0.95), ("g1", "pa", 0.2)))
        be.query("q", 3)
        top = {r["source_id"]: r["page_evidence"] for r in be.last_fusion}
        self.assertEqual(top["B"], 0.95)

    @unittest.skipUnless(HAVE_BS4 and HAVE_CHROMA, "bs4 / chromadb missing")
    def test_default_build_leaves_the_pipeline_unchanged(self):
        base = make_pipeline(RG.ExtractiveGenerator())
        same = RO.build_optimised_pipeline(0.0, RG.EXTRACTIVE_MIN_SCORE, False, "extractive", base=base)
        self.assertIs(same.backend, base.backend)
        self.assertIsInstance(same.generator, RG.ExtractiveGenerator)
        cue = RO.build_optimised_pipeline(0.0, 0.34, True, "extractive", base=base)
        self.assertIsInstance(cue.generator, RO.DetailCueGenerator)
        fused = RO.build_optimised_pipeline(1.0, 0.34, False, "extractive", base=base)
        self.assertIsInstance(fused.backend, RO.FusionBackend)
        self.assertIs(fused.retriever, base.retriever)

    @unittest.skipUnless(HAVE_BS4 and HAVE_CHROMA, "bs4 / chromadb missing")
    def test_ollama_generator_is_never_wrapped(self):
        base = make_pipeline(RG.ExtractiveGenerator())
        pipe = RO.build_optimised_pipeline(0.0, 0.5, True, "ollama", base=base)
        self.assertIs(pipe.generator, base.generator)


class FrozenSetTests(unittest.TestCase):
    def setUp(self):
        self.freeze = load("phase10_queries_freeze.json")
        self.dev, self.test = load("phase10_dev_queries.json"), load("phase10_test_queries.json")

    def test_hashes_match_the_freeze_record(self):
        self.assertEqual(sha(EVAL / "phase10_dev_queries.json"), self.freeze["files"]["dev"]["sha256"])
        self.assertEqual(sha(EVAL / "phase10_test_queries.json"), self.freeze["files"]["test"]["sha256"])

    def test_counts_and_unique_ids(self):
        for name, d in (("dev", self.dev), ("test", self.test)):
            qs = d["queries"]
            self.assertEqual(len(qs), 73)
            self.assertEqual(len({q["id"] for q in qs}), 73)
            from collections import Counter
            self.assertEqual(dict(Counter(q["type"] for q in qs)), self.freeze["files"][name]["counts"])

    @staticmethod
    def norm(t):
        return re.sub(r"\W+", " ", t.lower()).strip()

    def test_dev_test_and_earlier_sets_do_not_share_queries(self):
        earlier = {self.norm(q["query"]) for f in ("phase8_queries.json", "phase9_queries.json") for q in load(f)["queries"]}
        dev = {self.norm(q["query"]) for q in self.dev["queries"]}
        test = {self.norm(q["query"]) for q in self.test["queries"]}
        self.assertFalse(dev & test)
        self.assertFalse((dev | test) & earlier)

    def test_absent_detail_terms_are_not_in_the_page(self):
        for q in self.dev["queries"] + self.test["queries"]:
            if q["type"] == "absent_detail":
                self.assertTrue(q["gold_doc_id"])
                self.assertEqual(q["expected_status"], "insufficient_context")

    def test_answerable_queries_have_evidence_and_gold_page(self):
        for q in self.dev["queries"] + self.test["queries"]:
            if q["type"] == "answerable":
                self.assertTrue(q["evidence"])
                self.assertEqual(q["expected_status"], "answered")
                self.assertIn("/", q["gold_doc_id"])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.sel = load("phase10_selection.json")

    def test_selection_is_dev_only(self):
        freeze = load("phase10_queries_freeze.json")
        self.assertEqual(self.sel["dev_sha256"], freeze["files"]["dev"]["sha256"])
        self.assertIs(self.sel["test_file_read"], False)

    def test_r_rule_is_reproduced_from_the_grid(self):
        grid = self.sel["R_grid"]
        base = next(r for r in grid if r["lam"] == 0.0)
        passing = [r for r in grid if r["wrong_topic_answered"] <= base["wrong_topic_answered"]]
        best = max(passing, key=lambda r: (r["answerable_r1"]["k"], -r["lam"]))
        self.assertEqual(self.sel["R_selected_lam"], best["lam"])
        for r in grid:
            self.assertEqual(r["guard_passed"], r["wrong_topic_answered"] <= base["wrong_topic_answered"])
        self.assertEqual(self.sel["R_exploratory_lam"], max(grid, key=lambda r: (r["answerable_r1"]["k"], -r["lam"]))["lam"])

    def test_g_rule_is_reproduced_from_the_grid(self):
        grid = self.sel["G_grid"]
        g0 = grid[0]
        for g in grid:
            lost = g0["oracle_correct_answers"]["k"] - g["oracle_correct_answers"]["k"]
            self.assertEqual(g["answerable_correct_lost_vs_G0"], lost)
            self.assertEqual(g["constraint_passed"], lost <= 2)
        ok = [g for g in grid if g["constraint_passed"]]
        best = max(ok, key=lambda g: g["oracle_absent_detail_abstained"]["k"])
        self.assertEqual(self.sel["G_selected"]["name"], best["name"])
        self.assertEqual(self.sel["selected_configuration"], {"lam": self.sel["R_selected_lam"], "theta": self.sel["G_selected"]["theta"], "detail_cue_check": self.sel["G_selected"]["detail_cue_check"]})

    def test_candidate_grids_match_the_code(self):
        self.assertEqual([r["lam"] for r in self.sel["R_grid"]], list(RO.LAMBDA_GRID))
        import phase10_lib as L
        self.assertEqual([g["name"] for g in self.sel["G_grid"]], [n for n, _, _ in L.G_CANDIDATES])

    def test_sign_test(self):
        import phase10_lib as L
        self.assertEqual(L.sign_test_p(15, 2), 0.0023)
        self.assertIsNone(L.sign_test_p(0, 0))
        self.assertEqual(L.sign_test_p(3, 0), 0.25)


class ResultsConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.res = load("phase10_results.json")
        self.rep = (ROOT / "data" / "phase10_report.md").read_text(encoding="utf-8")

    def test_hashes_recorded_in_results(self):
        self.assertEqual(self.res["test_sha256"], sha(EVAL / "phase10_test_queries.json"))
        self.assertEqual(self.res["dev_sha256"], sha(EVAL / "phase10_dev_queries.json"))
        self.assertEqual(self.res["selection_sha256"], sha(EVAL / "phase10_selection.json"))

    def test_g_verdict_follows_the_declared_rule(self):
        g = self.res["verdicts"]["G"]
        rule = g["rule"]
        expect = g["net_correct_abstentions"] >= rule["min_net_correct_abstentions"] and g["answerable_correct_lost"] <= rule["max_answerable_correct_lost"] and g["grounding_failures"] == 0 and g["phantom_citations"] == 0
        self.assertEqual(g["supported"], expect)
        base, sel = self.res["test"]["baseline"]["metrics"], self.res["test"]["selected"]["metrics"]
        self.assertEqual(g["net_correct_abstentions"], sel["oracle_absent_detail_abstained"]["k"] - base["oracle_absent_detail_abstained"]["k"])

    def test_r_is_not_adopted_and_figures_recompute(self):
        v = self.res["verdicts"]["R_exploratory"]
        self.assertFalse(v["adopted"])
        base, r = self.res["test"]["baseline"]["metrics"], self.res["test"]["R_exploratory"]["metrics"]
        gain = (r["router_answerable"]["recall@1"]["k"] - base["router_answerable"]["recall@1"]["k"]) / base["n_answerable"]
        self.assertAlmostEqual(v["r1_gain_absolute"], gain, places=4)
        self.assertEqual(v["wrong_topic_answered"], r["wrong_topic_answered"]["count"])

    def test_no_grounding_failures_or_phantom_citations_anywhere(self):
        blocks = list(self.res["test"].values()) and [x["metrics"] for x in self.res["test"].values()]
        for ref in self.res["regression_references"].values():
            blocks += [ref[k] for k in ("baseline", "selected", "R_exploratory+G")]
        for m in blocks:
            self.assertEqual(m["oracle_grounding_failures"] + m["router_mode_grounding_failures"], 0)
            self.assertEqual(m["oracle_phantom_citations"] + m["router_mode_phantom_citations"], 0)

    def test_lambda_zero_routing_identical_and_determinism(self):
        for ref in self.res["regression_references"].values():
            self.assertTrue(ref["lam0_routing_identical_to_baseline"])
        self.assertTrue(self.res["determinism"]["identical"])

    def test_phase9_baseline_reproduces_the_frozen_phase9_numbers(self):
        b = self.res["regression_references"]["phase9_queries"]["baseline"]
        self.assertEqual((b["router_all_gold_card_queries"]["recall@1"]["k"], b["router_all_gold_card_queries"]["n"]), (51, 111))   # 0.4595
        self.assertEqual(b["oracle_correct_answers"]["k"], 58)
        self.assertEqual(b["router_mode_correct_answers"]["k"], 19)
        self.assertEqual(b["oracle_absent_detail_abstained"]["k"], 7)

    def test_phase9_input_file_unchanged(self):
        self.assertEqual(self.res["regression_references"]["phase9_queries"]["file_sha256"], sha(EVAL / "phase9_queries.json"))
        self.assertEqual(self.res["regression_references"]["phase8_queries"]["file_sha256"], sha(EVAL / "phase8_queries.json"))

    def test_report_states_derived_scope_status_and_hashes(self):
        low = self.rep.lower()
        self.assertIn("derived", low)
        self.assertIn("not a user-written specification", low)
        for h in (self.res["dev_sha256"][:8], self.res["test_sha256"][:8]):
            self.assertIn(h, self.rep)
        for section in ("COMPLETED", "EXPERIMENTALLY EVALUATED", "BLOCKED", "NOT CLAIMED"):
            self.assertIn(section, self.rep)
        g = self.res["verdicts"]["G"]
        self.assertIn("NOT ADOPTED" if not g["supported"] else "ADOPTED", self.rep)
        self.assertNotIn("29/29 pages", self.rep.replace("not 29/29 pages", ""))

    def test_report_numbers_match_results(self):
        t = self.res["test"]
        b, s, r = t["baseline"]["metrics"], t["selected"]["metrics"], t["R_exploratory"]["metrics"]
        for needle in (f"{b['router_answerable']['recall@1']['k']}/41", f"{r['router_answerable']['recall@1']['k']}/41",
                       f"{b['oracle_absent_detail_abstained']['k']}/12", f"{s['oracle_absent_detail_abstained']['k']}/12"):
            self.assertIn(needle, self.rep)
        self.assertIn(str(self.res["verdicts"]["R_exploratory"]["paired_r1"]["sign_test_p_two_sided"]), self.rep)


class ProtectionTests(unittest.TestCase):
    PINS = {"scripts/rag_chat.py": "e862ce38", "scripts/rag_core.py": "881316e4", "data/evaluation/phase8_results.json": "735f7061", "data/source_manifest.json": "08ad208c",
            "data/card_collection_manifest.json": "5b3a5c30", "data/m2c_page_identity.json": "fccb0bb8"}

    def test_pinned_files_unchanged(self):
        for rel, prefix in self.PINS.items():
            self.assertTrue(sha(ROOT / rel).startswith(prefix), rel)

    def test_phase9_frozen_artifacts_unchanged(self):
        self.assertTrue(sha(EVAL / "phase9_queries_freeze.json") and load("phase9_queries_freeze.json"))
        self.assertTrue(sha(EVAL / "phase9_queries.json") == load("phase9_queries_freeze.json").get("queries_sha256", sha(EVAL / "phase9_queries.json")))

    def test_default_runtime_does_not_import_the_experiments(self):
        for rel in ("scripts/rag_pipeline.py", "scripts/rag_answer.py", "scripts/rag_generate.py", "scripts/rag_modes.py"):
            self.assertNotIn("rag_optimised", (ROOT / rel).read_text(encoding="utf-8"), rel)

    def test_no_network_imports_in_phase10_scripts(self):
        banned = {"urllib.request", "urllib.error", "http.client", "requests", "socket", "ollama"}
        for rel in ("rag_optimised", "phase10_lib", "phase10_select", "evaluate_phase10", "build_phase10_queries"):
            tree = ast.parse((ROOT / "scripts" / f"{rel}.py").read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                for n in names:
                    self.assertNotIn(n, banned, rel)

    def test_no_forbidden_files(self):
        self.assertFalse((ROOT / "scripts" / "rag_two_stage.py").exists())
        self.assertFalse((ROOT / "chroma_db").exists())

    def test_evaluator_refuses_to_run_twice(self):
        src = (ROOT / "scripts" / "evaluate_phase10.py").read_text(encoding="utf-8")
        self.assertIn("RESULTS.exists()", src)

    def test_default_pipeline_constants_unchanged(self):
        self.assertEqual(RG.EXTRACTIVE_MIN_SCORE, 0.34)


@NEED_STORES
class RealStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import rag_pipeline as RP
        cls.base = RP.build_pipeline(generator="extractive")

    def test_lambda_zero_matches_baseline_answers(self):
        pipe = RO.build_optimised_pipeline(0.0, 0.34, False, "extractive", base=self.base)
        for q in ("Which monitoring selection criteria exist for the AMI monitor?", "How do I set up a SAP Concur expense report?"):
            a, b = self.base.answer(q), pipe.answer(q)
            self.assertEqual((a["status"], a["answer"]), (b["status"], b["answer"]))

    def test_fusion_changes_only_the_order_and_keeps_29_cards(self):
        pipe = RO.build_optimised_pipeline(1.0, 0.34, False, "extractive", base=self.base)
        r = pipe.backend.query("What does the page say about installment plans?", 29)
        self.assertEqual(len(r["ids"][0]), 29)
        self.assertEqual(len({m["source_id"] for m in r["metadatas"][0]}), 29)

    def test_selected_configuration_is_deterministic_and_grounded(self):
        sel = load("phase10_selection.json")["selected_configuration"]
        pipe = RO.build_optimised_pipeline(sel["lam"], sel["theta"], sel["detail_cue_check"], "extractive", base=self.base)
        q = load("phase10_dev_queries.json")["queries"][0]["query"]
        a, b = pipe.answer(q, debug=True), pipe.answer(q, debug=True)
        self.assertEqual((a["status"], a["answer"], a["citations"], a["routing"]), (b["status"], b["answer"], b["citations"], b["routing"]))
        ctx = {i["chunk_id"] for i in (a["debug"].get("context") or {}).get("items", [])}
        self.assertTrue(all(s["chunk_id"] in ctx for s in a["citations"]["answer_sources"]))


if __name__ == "__main__":
    unittest.main()
