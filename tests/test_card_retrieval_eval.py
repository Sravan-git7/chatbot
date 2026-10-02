"""Phase-4 tokenizer check, evaluation set, collection `sap_m2c_card_v1` and retrieval results (offline)."""
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
UNITS = ROOT / "data" / "retrieval_units.json"
STATS = ROOT / "data" / "retrieval_token_stats.json"
QUESTIONS = ROOT / "data" / "evaluation" / "card_retrieval_questions.json"
RESULTS = ROOT / "data" / "evaluation" / "card_retrieval_results.json"
MANIFEST = ROOT / "data" / "card_collection_manifest.json"
VECTOR = ROOT / "data" / "vector_store"


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
    return m


def _have(pkg):
    return importlib.util.find_spec(pkg) is not None


def _model_available():
    try:
        _mod("m2c_common").resolve_model()
        return True
    except FileNotFoundError:
        return False


class EvalSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.units = {u["source_id"]: u for u in json.loads(UNITS.read_text(encoding="utf-8"))["units"]}
        cls.payload = json.loads(QUESTIONS.read_text(encoding="utf-8"))
        cls.qs = cls.payload["questions"]

    def test_set_is_well_formed(self):
        self.assertEqual(self.payload["question_count"], len(self.qs))
        self.assertGreaterEqual(len(self.qs), 40)
        ids = [q["question_id"] for q in self.qs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len({q["question"] for q in self.qs}), len(self.qs))
        for q in self.qs:
            for k in ("question_id", "question", "question_type", "expected_source_ids", "also_relevant_source_ids", "ambiguous", "evidence", "notes"):
                self.assertIn(k, q)
            self.assertTrue(q["question"].strip() and q["expected_source_ids"])
            self.assertTrue(set(q["expected_source_ids"]) | set(q["also_relevant_source_ids"]) <= set(self.units))
            self.assertFalse(set(q["expected_source_ids"]) & set(q["also_relevant_source_ids"]))
        types = {q["question_type"] for q in self.qs}
        self.assertTrue({"exact_title", "semantic", "m2c_relevance", "category", "distinctive_term", "ambiguous"} <= types)

    def test_every_expected_source_is_backed_by_a_verbatim_card_quote(self):
        for q in self.qs:
            self.assertEqual({e["source_id"] for e in q["evidence"]}, set(q["expected_source_ids"]), q["question_id"])
            for e in q["evidence"]:
                self.assertIn(e["quote"], self.units[e["source_id"]]["full_text"], (q["question_id"], e["quote"]))

    def test_builder_output_matches_committed_file_and_rejects_bad_quotes(self):
        m = _mod("build_card_eval_questions")
        units = list(self.units.values())
        self.assertEqual(m.build(units), self.payload)
        bad = json.loads(json.dumps(units))
        victim = next(u for u in bad if u["source_id"] == "M2C-08")
        victim["full_text"] = victim["full_text"].replace("estimated-bill", "x")
        with self.assertRaises(ValueError):
            m.build(bad)

    def test_ambiguity_flags_cover_multi_expected_questions(self):
        for q in self.qs:
            if len(q["expected_source_ids"]) > 1:
                self.assertTrue(q["ambiguous"], q["question_id"])


class MetricUnitTests(unittest.TestCase):
    def test_metrics_and_ranking_on_synthetic_data(self):
        ev = _mod("evaluate_card_retrieval")
        qs = [{"question_id": "a", "question": "x", "question_type": "t", "ambiguous": False, "expected_source_ids": ["S1"], "also_relevant_source_ids": []},
              {"question_id": "b", "question": "y", "question_type": "t", "ambiguous": True, "expected_source_ids": ["S2", "S3"], "also_relevant_source_ids": ["S1"]},
              {"question_id": "c", "question": "z", "question_type": "u", "ambiguous": False, "expected_source_ids": ["S3"], "also_relevant_source_ids": []}]
        order = lambda ids: [{"source_id": i, "title": i, "cosine_similarity": 0.5} for i in ids]
        ranked = {"a": order(["S1", "S2", "S3", "S4", "S5", "S6"]), "b": order(["S1", "S4", "S3", "S2", "S5", "S6"]),
                  "c": order(["S1", "S2", "S4", "S5", "S6", "S3"])}
        rows = ev.rank_questions(qs, ranked)
        self.assertEqual([r["first_expected_rank"] for r in rows], [1, 3, 6])
        self.assertTrue(rows[1]["hit@3"] and not rows[1]["hit@1"] and rows[1]["top1_is_also_relevant"])
        m = ev.metrics(rows)
        self.assertEqual((m["recall@1"], m["recall@3"], m["recall@5"]), (round(1 / 3, 4), round(2 / 3, 4), round(2 / 3, 4)))
        self.assertEqual(m["mrr"], round((1 + 1 / 3 + 1 / 6) / 3, 4))
        self.assertEqual(m["mean_expected_coverage@3"], round((1 + 0.5 + 0) / 3, 4))
        self.assertEqual(ev.summarise(rows)["by_question_type"]["u"]["questions"], 1)


@unittest.skipUnless(STATS.is_file() and _have("transformers") and _model_available(), "needs transformers + local all-MiniLM-L6-v2 files")
class TokenizerTests(unittest.TestCase):
    def test_recorded_statistics_match_a_fresh_measurement_and_fit_the_model(self):
        tv = _mod("validate_token_lengths")
        payload = json.loads(UNITS.read_text(encoding="utf-8"))
        model_dir, _ = _mod("m2c_common").resolve_model()
        fresh = tv.measure(payload["units"], model_dir)
        rec = json.loads(STATS.read_text(encoding="utf-8"))
        self.assertEqual(rec["units_file_sha256"], hashlib.sha256(UNITS.read_bytes()).hexdigest(), "token stats are stale")
        for k in ("full_text", "embedding_text", "sources", "max_seq_length", "embedding_text_over_limit", "full_text_over_limit"):
            self.assertEqual(rec[k], fresh[k], k)
        self.assertEqual(len(rec["sources"]), 29)
        self.assertEqual(fresh["tokenizer"]["model_max_seq_length_sentence_transformers"], 256)
        self.assertEqual(fresh["embedding_text_over_limit"], [])                       # no truncation anywhere
        self.assertLessEqual(fresh["embedding_text"]["max"], 256)
        self.assertLess(fresh["embedding_text"]["max"], fresh["full_text"]["max"])

    def test_overlong_text_is_reported_and_stops_the_pipeline(self):
        tv, bc = _mod("validate_token_lengths"), _mod("build_card_collection")
        model_dir, _ = _mod("m2c_common").resolve_model()
        u = json.loads(UNITS.read_text(encoding="utf-8"))["units"][:1]
        u[0] = dict(u[0], embedding_text="word " * 400)
        res = tv.measure(u, model_dir)
        self.assertEqual(res["embedding_text_over_limit"], [u[0]["source_id"]])
        self.assertTrue(res["verdict"].startswith("STOP"))
        with tempfile.TemporaryDirectory() as t:
            sp = Path(t) / "s.json"
            sp.write_text(json.dumps(dict(res, units_file_sha256=hashlib.sha256(UNITS.read_bytes()).hexdigest())), encoding="utf-8")
            with self.assertRaises(SystemExit):
                bc.check_token_stats(UNITS, sp)                                        # embedding refused
            sp.write_text(json.dumps(dict(res, embedding_text_over_limit=[], units_file_sha256="0" * 64)), encoding="utf-8")
            with self.assertRaises(SystemExit):
                bc.check_token_stats(UNITS, sp)                                        # stale statistics refused


@unittest.skipUnless(VECTOR.is_dir() and MANIFEST.is_file() and _have("chromadb"), "needs the built sap_m2c_card_v1 store")
class CollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import chromadb
        from chromadb.config import Settings
        cls.units = {u["source_id"]: u for u in json.loads(UNITS.read_text(encoding="utf-8"))["units"]}
        cls.client = chromadb.PersistentClient(path=str(VECTOR), settings=Settings(anonymized_telemetry=False))
        cls.col = cls.client.get_collection("sap_m2c_card_v1")
        cls.man = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_collection_is_new_separate_and_complete(self):
        names = [c.name if hasattr(c, "name") else c for c in self.client.list_collections()]
        self.assertEqual(names, ["sap_m2c_card_v1"])                                     # legacy sap_docs is not here
        self.assertFalse((ROOT / "chroma_db").exists() and "sap_m2c_card_v1" in str(ROOT / "chroma_db"))
        self.assertEqual(self.col.count(), 29)
        self.assertEqual(self.man["vector_count"], 29)
        got = self.col.get(include=["embeddings"])
        self.assertEqual(len(got["embeddings"][0]), 384)
        self.assertEqual(self.man["embedding_dimensions"], 384)

    def test_hashes_recorded_in_collection_and_manifest_are_current(self):
        meta = self.col.metadata
        units_sha = hashlib.sha256(UNITS.read_bytes()).hexdigest()
        corpus = json.loads(UNITS.read_text(encoding="utf-8"))["source_corpus"]["file_sha256"]
        self.assertEqual(meta["retrieval_units_file_sha256"], units_sha)
        self.assertEqual(self.man["retrieval_units_file_sha256"], units_sha)
        self.assertEqual(meta["source_corpus_file_sha256"], corpus)
        self.assertEqual(corpus, hashlib.sha256((ROOT / "data" / "source_corpus.json").read_bytes()).hexdigest())
        self.assertEqual(meta["embedding_model"], "all-MiniLM-L6-v2")
        self.assertEqual(meta["hnsw:space"], "cosine")
        for k in ("created_utc", "config_json", "embedding_dimensions"):
            self.assertIn(k, meta)
        self.assertEqual(self.man["token_stats_file_sha256"], hashlib.sha256(STATS.read_bytes()).hexdigest())

    def test_every_vector_keeps_readable_provenance_and_the_embedded_text(self):
        got = self.col.get(include=["documents", "metadatas"])
        self.assertEqual(sorted(got["ids"]), sorted(self.units))
        for i, doc, md in zip(got["ids"], got["documents"], got["metadatas"]):
            u = self.units[i]
            self.assertEqual(doc, u["embedding_text"])
            for k, uk in (("retrieval_unit_id", "retrieval_unit_id"), ("source_id", "source_id"), ("source_number", "source_number"), ("title", "title"),
                          ("category", "category"), ("source_url", "source_url"), ("source_status", "source_status"), ("source_url_status", "source_url_status"),
                          ("has_source_correction", "has_source_correction"), ("citation", "citation"), ("sha256", "sha256"), ("filename", "filename")):
                self.assertEqual(md[k], u[uk], (i, k))
            self.assertEqual(md["corpus_document"], u["provenance"]["corpus_document"])
            self.assertEqual((md["page_start"], md["page_end"]), (1, 1))
        self.assertEqual([md["source_id"] for md in got["metadatas"] if md["has_source_correction"]], ["M2C-05"])

    def test_builder_refuses_existing_collection_and_rebuilds_only_its_own(self):
        if not _model_available():
            self.skipTest("model files unavailable")
        bc = _mod("build_card_collection")
        t = Path(tempfile.mkdtemp())
        try:
            args = dict(units_path=UNITS, vector_dir=t / "vs", collection_name="sap_m2c_card_v1", rebuild=False, model_path=None,
                        manifest_path=t / "m.json", stats_path=STATS)
            m1 = bc.build(**args)
            self.assertEqual((m1["vector_count"], m1["embedding_dimensions"]), (29, 384))
            with self.assertRaises(SystemExit):
                bc.build(**args)                                                         # existing collection is never silently overwritten
            m2 = bc.build(**dict(args, rebuild=True))
            self.assertEqual(m2["embeddings_float32_sha256"], m1["embeddings_float32_sha256"])   # reproducible on this machine
            self.assertEqual(m2["embeddings_float32_sha256"], self.man["embeddings_float32_sha256"])
            self.assertTrue((ROOT / "data" / "vector_store").is_dir() and self.col.count() == 29)   # repo store untouched
        finally:
            shutil.rmtree(t, ignore_errors=True)


@unittest.skipUnless(RESULTS.is_file(), "needs data/evaluation/card_retrieval_results.json")
class ResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = json.loads(RESULTS.read_text(encoding="utf-8"))
        cls.qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]

    def test_results_cover_every_question_and_are_current(self):
        self.assertEqual(self.res["question_count"], len(self.qs))
        self.assertEqual([r["question_id"] for r in self.res["per_question"]], [q["question_id"] for q in self.qs])
        self.assertEqual(self.res["questions_file_sha256"], hashlib.sha256(QUESTIONS.read_bytes()).hexdigest(), "results are stale (questions changed)")
        self.assertEqual(self.res["retrieval_units_file_sha256"], hashlib.sha256(UNITS.read_bytes()).hexdigest(), "results are stale (units changed)")
        self.assertEqual((self.res["collection"], self.res["vector_count"], self.res["embedding_dimensions"]), ("sap_m2c_card_v1", 29, 384))

    def test_reported_metrics_are_recomputed_from_per_question_rows(self):
        ev = _mod("evaluate_card_retrieval")
        rows = self.res["per_question"]
        self.assertEqual(ev.summarise(rows), self.res["metrics"])
        for r in rows:
            self.assertEqual(len(r["retrieved_top5"]), 5)
            self.assertTrue(all(t["source_id"] and t["title"] for t in r["retrieved_top5"]))
            self.assertEqual(r["first_expected_rank"], min(r["expected_ranks"].values()))
        self.assertEqual(self.res["failed_at_1"], [r["question_id"] for r in rows if r["first_expected_rank"] > 1])
        self.assertEqual(self.res["failed_at_3"], [r["question_id"] for r in rows if r["first_expected_rank"] > 3])
        m = self.res["metrics"]["overall"]
        self.assertTrue(0 <= m["recall@1"] <= m["recall@3"] <= m["recall@5"] <= 1)
        self.assertTrue(m["recall@1"] <= m["mrr"] <= 1)

    def test_control_is_labelled_and_not_the_evaluated_collection(self):
        c = self.res.get("control_full_text_in_memory")
        self.assertTrue(c is None or "CONTROL ONLY" in c["note"])

    @unittest.skipUnless(VECTOR.is_dir() and _have("chromadb") and _model_available(), "needs the store and model")
    def test_rerun_is_identical(self):
        ev = _mod("evaluate_card_retrieval")
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "r.json"
            ev.run(UNITS, QUESTIONS, VECTOR, "sap_m2c_card_v1", None, out, MANIFEST)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), self.res)


if __name__ == "__main__":
    unittest.main()
