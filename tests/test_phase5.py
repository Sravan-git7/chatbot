"""Phase 5: independent query set, BM25/hybrid retrievers, robustness evaluation, decision rule and report (offline)."""
import ast
import copy
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
UNITS = ROOT / "data" / "retrieval_units.json"
QUERIES = ROOT / "data" / "evaluation" / "independent_queries.json"
P4_QUESTIONS = ROOT / "data" / "evaluation" / "card_retrieval_questions.json"
P4_RESULTS = ROOT / "data" / "evaluation" / "card_retrieval_results.json"
P5_RESULTS = ROOT / "data" / "evaluation" / "phase5_results.json"
CORPUS = ROOT / "data" / "source_corpus.json"
VECTOR = ROOT / "data" / "vector_store"
PHASE5_SCRIPTS = ["build_independent_queries", "phase5_retrievers", "evaluate_phase5", "build_phase5_report"]


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _have(pkg):
    return importlib.util.find_spec(pkg) is not None


def _model_available():
    try:
        _mod("m2c_common").resolve_model()
        return True
    except FileNotFoundError:
        return False


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class IndependentQuerySetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.units = {u["source_id"]: u for u in json.loads(UNITS.read_text(encoding="utf-8"))["units"]}
        cls.payload = json.loads(QUERIES.read_text(encoding="utf-8"))
        cls.qs = cls.payload["queries"]
        cls.p4 = {q["question"].strip().lower() for q in json.loads(P4_QUESTIONS.read_text(encoding="utf-8"))["questions"]}
        cls.mod = _mod("build_independent_queries")

    def test_size_and_ids(self):
        self.assertEqual(self.payload["query_count"], len(self.qs))
        self.assertGreaterEqual(len(self.qs), 50)
        ids = [q["query_id"] for q in self.qs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len({q["query"].lower() for q in self.qs}), len(self.qs))

    def test_required_fields_and_labels(self):
        for q in self.qs:
            for k in ("query", "query_type", "difficulty", "expected_source_ids", "rationale", "evidence", "ambiguous"):
                self.assertTrue(q[k] not in ("", None, []) or k == "ambiguous", (q["query_id"], k))
            self.assertIn(q["difficulty"], ("easy", "medium", "hard"))
            self.assertIn(q["query_type"], self.mod.TYPES)
            for sid in q["expected_source_ids"] + q["also_relevant_source_ids"]:
                self.assertIn(sid, self.units)
            if len(q["expected_source_ids"]) > 1:
                self.assertTrue(q["ambiguous"], q["query_id"])

    def test_evidence_is_verbatim_and_covers_expected(self):
        for q in self.qs:
            self.assertEqual({e["source_id"] for e in q["evidence"]}, set(q["expected_source_ids"]), q["query_id"])
            for e in q["evidence"]:
                self.assertIn(e["quote"], self.units[e["source_id"]]["full_text"], q["query_id"])

    def test_queries_are_not_phase4_questions_nor_copied_from_cards(self):
        for q in self.qs:
            self.assertNotIn(q["query"].strip().lower(), self.p4, q["query_id"])
            self.assertLessEqual(q["max_verbatim_overlap_words"], self.payload["independence_rules"]["max_verbatim_overlap_words"])
            words = self.mod.words(q["query"])
            recomputed = max(self.mod.longest_common_run(words, self.mod.words(self.units[s]["full_text"])) for s in q["expected_source_ids"])
            self.assertEqual(recomputed, q["max_verbatim_overlap_words"], q["query_id"])

    def test_coverage_of_required_kinds(self):
        types = {q["query_type"] for q in self.qs}
        self.assertEqual(types, set(self.mod.TYPES))
        buckets = {q["length_bucket"] for q in self.qs}
        self.assertIn("very_short", buckets)
        self.assertIn("long", buckets)
        for q in self.qs:
            self.assertEqual(q["word_count"], len(self.mod.words(q["query"])))
            self.assertEqual(q["length_bucket"], self.mod.length_bucket(q["word_count"]))
        self.assertTrue(any(1 <= q["word_count"] <= 4 for q in self.qs))
        self.assertTrue(any(8 <= q["word_count"] <= 20 for q in self.qs))
        self.assertEqual({q["difficulty"] for q in self.qs}, {"easy", "medium", "hard"})
        covered = {s for q in self.qs for s in q["expected_source_ids"]}
        self.assertGreaterEqual(len(covered), 25, "the set should exercise most of the 29 cards")

    def test_builder_reproduces_committed_file_and_is_deterministic(self):
        units = list(self.units.values())
        p4 = [q["question"] for q in json.loads(P4_QUESTIONS.read_text(encoding="utf-8"))["questions"]]
        a = self.mod.build(units, p4)
        b = self.mod.build(units, p4)
        self.assertEqual(a, b)
        self.assertEqual(a, self.payload)

    def test_builder_refuses_bad_entries(self):
        units = list(self.units.values())
        p4 = [q["question"] for q in json.loads(P4_QUESTIONS.read_text(encoding="utf-8"))["questions"]]
        original = list(self.mod.Q)
        first = list(original[0])
        try:
            bad_quote = list(first); bad_quote[8] = [(first[8][0][0], "this sentence is not in the card")]
            self.mod.Q[:] = [tuple(bad_quote)]
            with self.assertRaisesRegex(ValueError, "not found"):
                self.mod.build(units, p4)
            same_as_p4 = list(first); same_as_p4[3] = p4[0]
            self.mod.Q[:] = [tuple(same_as_p4)]
            with self.assertRaisesRegex(ValueError, "Phase-4"):
                self.mod.build(units, p4)
            unknown = list(first); unknown[4] = ["M2C-99"]
            self.mod.Q[:] = [tuple(unknown)]
            with self.assertRaisesRegex(ValueError, "unknown source"):
                self.mod.build(units, p4)
            quote = first[8][0][1]
            copied = list(first); copied[3] = " ".join(quote.split()[:6])
            self.mod.Q[:] = [tuple(copied)]
            with self.assertRaisesRegex(ValueError, "consecutive words"):
                self.mod.build(units, p4)
            multi = list(first); multi[4] = ["M2C-01", "M2C-02"]; multi[6] = False
            multi[8] = [(first[8][0][0], first[8][0][1]), ("M2C-02", self.units["M2C-02"]["full_text"][:30])]
            self.mod.Q[:] = [tuple(multi)]
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                self.mod.build(units, p4)
            self.mod.Q[:] = [tuple(first), tuple(first)]
            with self.assertRaisesRegex(ValueError, "duplicate"):
                self.mod.build(units, p4)
        finally:
            self.mod.Q[:] = original


class RetrieverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _mod("phase5_retrievers")
        cls.ids = ["a", "b", "c"]
        cls.docs = ["meter reading estimation for billing", "payment clearing for incoming payments", "subledger processing of contract accounts payment"]

    def test_tokenize(self):
        self.assertEqual(self.m.tokenize("The Move-Out, of a customer!"), ["move", "out", "customer"])
        self.assertEqual(self.m.tokenize("The of", drop_stopwords=False), ["the", "of"])
        self.assertEqual(self.m.tokenize("FI-CA 2024"), ["fi", "ca", "2024"])

    def test_bm25_ranks_rare_term_and_is_deterministic(self):
        bm = self.m.BM25(self.ids, self.docs)
        s = bm.scores("subledger")
        self.assertEqual(max(s, key=s.get), "c")
        self.assertEqual(s["a"], 0.0)
        self.assertEqual(s, self.m.BM25(self.ids, self.docs).scores("subledger"))
        self.assertGreater(bm.idf("subledger"), bm.idf("payment"))
        self.assertEqual(bm.matched_terms("subledger and payment and reading", "c"), ["payment", "subledger"])
        self.assertEqual(set(bm.scores("zzz").values()), {0.0})

    def test_bm25_longer_documents_are_normalised(self):
        bm = self.m.BM25(["short", "long"], ["alpha beta", "alpha beta " + "filler " * 40])
        s = bm.scores("alpha")
        self.assertGreater(s["short"], s["long"])

    def test_minmax_and_hybrid(self):
        self.assertEqual(self.m.minmax({"a": 1.0, "b": 3.0}), {"a": 0.0, "b": 1.0})
        self.assertEqual(self.m.minmax({"a": 2.0, "b": 2.0}), {"a": 0.0, "b": 0.0})
        dense = {"a": 0.9, "b": 0.5, "c": 0.1}
        lex = {"a": 0.0, "b": 1.0, "c": 4.0}
        r = lambda w: [k for k, _ in self.m.rank(self.m.hybrid(dense, lex, w))]
        self.assertEqual(r(1.0), ["a", "b", "c"])
        self.assertEqual(r(0.0), ["c", "b", "a"])
        self.assertEqual(self.m.hybrid(dense, lex, 0.5), self.m.hybrid(dense, lex, 0.5))
        with self.assertRaises(ValueError):
            self.m.hybrid(dense, lex, 1.5)

    def test_rank_ties_break_by_id(self):
        self.assertEqual([k for k, _ in self.m.rank({"b": 1.0, "a": 1.0, "c": 2.0})], ["c", "a", "b"])

    def test_declared_weights_are_fixed(self):
        self.assertEqual(self.m.HYBRID_WEIGHTS, (0.75, 0.5, 0.25))
        self.assertIn(self.m.PRIMARY_HYBRID_WEIGHT, self.m.HYBRID_WEIGHTS)
        self.assertEqual(self.m.PRIMARY_HYBRID_WEIGHT, 0.5)


@unittest.skipUnless(_have("sentence_transformers") and _have("chromadb"), "needs sentence-transformers and chromadb to import the evaluator")
class EvaluatorUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev = _mod("evaluate_phase5")

    def test_sign_test(self):
        self.assertEqual(self.ev.sign_test_p(7, 7), 1.0)
        self.assertEqual(self.ev.sign_test_p(0, 5), 0.0625)
        self.assertEqual(self.ev.sign_test_p(0, 0), 1.0)
        self.assertEqual(self.ev.sign_test_p(5, 0), self.ev.sign_test_p(0, 5))

    def test_length_bucket(self):
        self.assertEqual([self.ev.length_bucket(n) for n in (1, 4, 5, 7, 8, 20, 21)], ["very_short", "very_short", "short", "short", "long", "long", "very_long"])

    def test_paired(self):
        base = [{"id": "x", "first_expected_rank": 3, "pass": False}, {"id": "y", "first_expected_rank": 1, "pass": True}, {"id": "z", "first_expected_rank": 2, "pass": False}]
        other = [{"id": "x", "first_expected_rank": 1, "pass": True}, {"id": "y", "first_expected_rank": 4, "pass": False}, {"id": "z", "first_expected_rank": 2, "pass": False}]
        p = self.ev.paired(base, other)
        self.assertEqual((p["improved"], p["worsened"], p["unchanged"]), (1, 1, 1))
        self.assertEqual((p["gained_rank1"], p["lost_rank1"]), (["x"], ["y"]))

    def test_tree_sha_detects_change(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "a.bin").write_bytes(b"1")
            before = self.ev.tree_sha(d)
            self.assertEqual(before, self.ev.tree_sha(d))
            (d / "a.bin").write_bytes(b"2")
            self.assertNotEqual(before, self.ev.tree_sha(d))

    def _synthetic(self, hybrid_mrr, deltas, p4_mrr=(0.9, 0.9), p4_r1=(0.9, 0.9), slices_ok=True, r3=(0.8, 0.8), r5=(0.9, 0.9), imp=10, wor=2, p=0.02):
        def sysd(mrr, r1=0.5, a3=0.8, a5=0.9, sl=0.8):
            return {"summary": {"overall": {"mrr": mrr, "recall@1": r1, "recall@3": a3, "recall@5": a5},
                                "slices": {"very_short": {"questions": 5, "mrr": sl}, "rare_term": {"questions": 5, "mrr": sl}}}}
        p5 = {"systems": {"dense": sysd(0.7, a3=r3[0], a5=r5[0])}, "paired_vs_dense": {}}
        p5["systems"]["hybrid_0.5"] = sysd(hybrid_mrr, a3=r3[1], a5=r5[1], sl=0.9 if slices_ok else 0.5)
        for w, dlt in deltas.items():
            if w != "0.5":
                p5["systems"][f"hybrid_{w}"] = sysd(0.7 + dlt)
        p5["systems"]["hybrid_0.5"]["summary"]["overall"]["mrr"] = hybrid_mrr
        p5["paired_vs_dense"]["hybrid_0.5"] = {"improved": imp, "worsened": wor, "sign_test_p_two_sided": p}
        p4 = {"systems": {"dense": sysd(p4_mrr[0], r1=p4_r1[0]), "hybrid_0.5": sysd(p4_mrr[1], r1=p4_r1[1])}}
        return {"datasets": {"phase5": p5, "phase4": p4}}

    def test_decision_rule_accepts_only_when_every_criterion_holds(self):
        good = self._synthetic(0.76, {"0.75": 0.05, "0.5": 0.06, "0.25": -0.01})
        d = self.ev.decide(good)
        self.assertTrue(d["all_pass"], d["failed_criteria"])
        self.assertIn("measurable benefit", d["verdict"])

    def test_decision_rule_rejections(self):
        base_w = {"0.75": 0.05, "0.5": 0.06, "0.25": -0.01}
        cases = {
            "C1": self._synthetic(0.72, base_w),
            "C2": self._synthetic(0.76, base_w, r3=(0.8, 0.7)),
            "C3": self._synthetic(0.76, base_w, imp=5, wor=6, p=0.5),
            "C4": self._synthetic(0.76, base_w, slices_ok=False),
            "C5": self._synthetic(0.76, base_w, p4_mrr=(0.95, 0.90)),
            "C6": self._synthetic(0.76, {"0.75": -0.05, "0.5": 0.06, "0.25": -0.01}),
        }
        for crit, res in cases.items():
            d = self.ev.decide(res)
            self.assertFalse(d["all_pass"], crit)
            self.assertIn(crit, d["failed_criteria"])
            self.assertIn("retain dense-only", d["verdict"])

    def test_r1_gain_alone_does_not_pass(self):
        res = self._synthetic(0.70, {"0.75": 0.0, "0.5": 0.0, "0.25": 0.0})
        res["datasets"]["phase5"]["systems"]["hybrid_0.5"]["summary"]["overall"]["recall@1"] = 0.9
        self.assertFalse(self.ev.decide(res)["all_pass"])


@unittest.skipUnless(P5_RESULTS.is_file(), "needs data/evaluation/phase5_results.json")
class RecordedResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = json.loads(P5_RESULTS.read_text(encoding="utf-8"))
        cls.qs = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]

    def test_inputs_are_not_stale(self):
        i = self.res["inputs"]
        self.assertEqual(i["independent_queries_sha256"], _sha(QUERIES))
        self.assertEqual(i["retrieval_units_sha256"], _sha(UNITS))
        self.assertEqual(i["phase4_questions_sha256"], _sha(P4_QUESTIONS))
        self.assertEqual(i["phase4_results_sha256"], _sha(P4_RESULTS))
        self.assertEqual(i["source_corpus_sha256"], _sha(CORPUS))

    def test_baseline_reproduced_and_store_untouched(self):
        b = self.res["protected_baseline"]
        self.assertTrue(b["top5_identical_to_recorded_phase4_results"])
        self.assertEqual(b["mismatching_questions"], [])
        self.assertEqual(b["max_abs_similarity_difference_vs_recorded"], 0.0)
        self.assertTrue(b["vector_store_unchanged_by_this_evaluation"])
        self.assertTrue(b["stored_embeddings_consistent_with_embedding_text"])
        self.assertLess(b["stored_vs_recomputed_embedding_max_abs_diff"], 1e-6)
        manifest = json.loads((ROOT / "data" / "card_collection_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(b["phase4_manifest_embeddings_float32_sha256"], manifest["embeddings_float32_sha256"])
        self.assertNotIn("vector_store_tree_sha256_before", b, "raw store hashes are environment-dependent and must not be recorded")
        rec = json.loads(P4_RESULTS.read_text(encoding="utf-8"))["metrics"]["overall"]
        for k in ("recall@1", "recall@3", "recall@5", "mrr"):
            self.assertEqual(b["phase4_recorded_metrics"][k], rec[k])
            self.assertEqual(self.res["datasets"]["phase4"]["systems"]["dense"]["summary"]["overall"][k], rec[k])

    def test_metrics_match_rows(self):
        for name, ds in self.res["datasets"].items():
            for s, blk in ds["systems"].items():
                rows = blk["rows"]
                n = len(rows)
                self.assertEqual(n, ds["query_count"], (name, s))
                m = blk["summary"]["overall"]
                self.assertAlmostEqual(m["recall@1"], round(sum(r["first_expected_rank"] == 1 for r in rows) / n, 4), places=4)
                self.assertAlmostEqual(m["recall@5"], round(sum(r["first_expected_rank"] <= 5 for r in rows) / n, 4), places=4)
                self.assertAlmostEqual(m["mrr"], round(sum(1.0 / r["first_expected_rank"] for r in rows) / n, 4), places=4)
                for r in rows:
                    self.assertEqual(r["pass"], r["first_expected_rank"] == 1)
                    self.assertEqual(len(r["top5"]), 5)
                    self.assertEqual([t["rank"] for t in r["top5"]], [1, 2, 3, 4, 5])

    def test_all_systems_answer_the_same_queries(self):
        ids = [q["query_id"] for q in self.qs]
        for s, blk in self.res["datasets"]["phase5"]["systems"].items():
            self.assertEqual([r["id"] for r in blk["rows"]], ids, s)
        self.assertEqual(list(self.res["datasets"]["phase5"]["systems"]), ["dense", "bm25", "hybrid_0.75", "hybrid_0.5", "hybrid_0.25"])

    def test_dense_rows_are_sorted_by_similarity(self):
        for r in self.res["datasets"]["phase5"]["systems"]["dense"]["rows"]:
            scores = [t["score"] for t in r["top5"]]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_breakdowns_cover_all_queries(self):
        p5 = self.res["datasets"]["phase5"]
        for key in ("by_query_type", "by_length", "by_difficulty"):
            total = sum(v["questions"] for v in p5["systems"]["dense"]["summary"][key].values())
            self.assertEqual(total, p5["query_count"], key)
        self.assertEqual(sum(p5["composition"]["by_query_type"].values()), p5["query_count"])
        for name, ids in p5["slices"].items():
            self.assertEqual(p5["systems"]["dense"]["summary"]["slices"][name].get("questions", 0), len(ids), name)

    def test_decision_is_reproducible_from_recorded_numbers(self):
        ev = _mod_or_skip(self)
        self.assertEqual(json.loads(json.dumps(ev.decide(self.res))), self.res["datasets"]["phase5"]["decision"])

    def test_hybrid_is_not_declared_better_on_r1_alone(self):
        d = self.res["datasets"]["phase5"]["decision"]
        if not d["all_pass"]:
            self.assertIn("retain dense-only", d["verdict"])
        else:
            self.assertEqual(d["failed_criteria"], [])

    def test_failure_diagnostics_cover_known_and_new_failures(self):
        known = [d["id"] for d in self.res["failure_diagnostics"]["phase4_known_failures"]]
        self.assertEqual(known, ["Q07", "Q39", "Q42", "Q49"])
        dense = self.res["datasets"]["phase5"]["systems"]["dense"]["rows"]
        failing = [r["id"] for r in dense if not r["pass"]]
        self.assertEqual([d["id"] for d in self.res["failure_diagnostics"]["phase5_dense_not_rank1"]], failing)
        self.assertEqual(self.res["failure_pattern_counts_phase5"]["dense_not_rank1"], len(failing))

    def test_tokenizer_study_records_actual_splits(self):
        tk = self.res["tokenization"]
        self.assertEqual(tk["tokenizer"], "BertTokenizer")
        self.assertEqual(tk["card_terms_fragmented"]["subledger"], ["sub", "##led", "##ger"])
        self.assertEqual(tk["card_terms_fragmented"]["clarification"], ["cl", "##ari", "##fication"])
        for term, pieces in tk["card_terms_fragmented"].items():
            self.assertGreaterEqual(len(pieces), tk["fragment_threshold_pieces"], term)
            self.assertEqual("".join(p.replace("##", "") for p in pieces), term)
        self.assertTrue(all(t.isalpha() for t in tk["card_terms_fragmented"]))

    def test_protected_phase4_results_are_unmodified(self):
        self.assertEqual(self.res["inputs"]["phase4_results_sha256"], _sha(P4_RESULTS))


def _mod_or_skip(case):
    if not (_have("sentence_transformers") and _have("chromadb")):
        case.skipTest("evaluator imports need sentence-transformers and chromadb")
    return _mod("evaluate_phase5")


@unittest.skipUnless(VECTOR.is_dir() and _have("chromadb") and _have("sentence_transformers") and _model_available(), "needs the store and model")
class LiveReproductionTests(unittest.TestCase):
    def test_rerun_reproduces_recorded_results_and_leaves_store_untouched(self):
        ev = _mod("evaluate_phase5")
        before = ev.tree_sha(VECTOR)
        recorded = json.loads(P5_RESULTS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "r.json"
            res = ev.run(UNITS, CORPUS, QUERIES, P4_QUESTIONS, P4_RESULTS, VECTOR, out)
            self.assertTrue(res["protected_baseline"]["top5_identical_to_recorded_phase4_results"])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), recorded, "evaluation is not deterministic")
        self.assertEqual(ev.tree_sha(VECTOR), before)

    def test_missing_store_fails_with_instructions(self):
        ev = _mod("evaluate_phase5")
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(SystemExit) as cm:
                ev.run(UNITS, CORPUS, QUERIES, P4_QUESTIONS, P4_RESULTS, Path(t) / "absent", Path(t) / "o.json")
            self.assertIn("rebuild", str(cm.exception))


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _mod("build_phase5_report")

    @unittest.skipUnless(P5_RESULTS.is_file(), "needs phase5 results")
    def test_report_has_the_twelve_sections_in_order(self):
        text = self.m.build("x passed")
        heads = re.findall(r"^## (\d+)\. (.+)$", text, flags=re.M)
        self.assertEqual([int(n) for n, _ in heads], list(range(1, 13)))
        expected = ["Phase 4 baseline", "Independent dataset description", "Dense-only results", "BM25-only results", "Hybrid results", "Breakdown by query type",
                    "Breakdown by query length", "Failure analysis", "Tokenization findings", "Comparison against Phase 4", "Whether hybrid gives a measurable benefit",
                    "Recommendation for the next phase"]
        for (_, title), want in zip(heads, expected):
            self.assertTrue(title.startswith(want), (title, want))
        self.assertIn("x passed", text)
        self.assertIn("Retain dense-only", text)

    @unittest.skipUnless(P5_RESULTS.is_file(), "needs phase5 results")
    def test_report_is_deterministic_and_placeholder_without_summary(self):
        self.assertEqual(self.m.build("a"), self.m.build("a"))
        self.assertIn("Not recorded in this run", self.m.build(None))

    @unittest.skipUnless(P5_RESULTS.is_file(), "needs phase5 results")
    def test_report_numbers_come_from_the_results_file(self):
        res = json.loads(P5_RESULTS.read_text(encoding="utf-8"))
        d = res["datasets"]["phase5"]["systems"]["dense"]["summary"]["overall"]
        text = self.m.build(None)
        self.assertIn(f"{d['recall@1']:.4f}", text)
        self.assertIn(f"{d['mrr']:.4f}", text)
        for q in res["datasets"]["phase5"]["systems"]["dense"]["rows"]:
            self.assertIn(q["id"], text)

    def test_report_table_helpers(self):
        self.assertEqual(self.m.table(["a", "b"], [[1, 2]]), "| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertEqual(self.m.mrow("x", {"questions": 0}), ["x", 0, "-", "-", "-", "-"])


class SafetyTests(unittest.TestCase):
    def _tree(self, name):
        return ast.parse((ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8"))

    def test_no_network_modules(self):
        banned = {"requests", "urllib.request", "urllib.error", "http.client", "socket", "httpx", "aiohttp", "ftplib"}
        for name in PHASE5_SCRIPTS:
            for node in ast.walk(self._tree(name)):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                for m in mods:
                    self.assertNotIn(m, banned, f"{name} imports {m}")

    def test_protected_rag_code_is_not_imported(self):
        protected = {"rag_chat", "retrieve", "evaluate_retrieval", "create_embeddings", "rag_core"}
        for name in PHASE5_SCRIPTS:
            for node in ast.walk(self._tree(name)):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    for m in mods:
                        self.assertNotIn(m.split(".")[0], protected, f"{name} imports {m}")

    def test_protected_store_is_queried_through_a_copy(self):
        ev_src = (ROOT / "scripts" / "evaluate_phase5.py").read_text(encoding="utf-8")
        self.assertIn("shutil.copytree", ev_src)
        self.assertIn("tree_sha", ev_src)

    def test_experimental_retrievers_are_not_used_elsewhere(self):
        self.assertFalse((ROOT / "chroma_db").exists())
        for p in (ROOT / "scripts").glob("*.py"):
            if p.stem in PHASE5_SCRIPTS:
                continue
            self.assertNotIn("phase5_retrievers", p.read_text(encoding="utf-8"), f"{p.name} must not use the experimental retrievers")


if __name__ == "__main__":
    unittest.main()
