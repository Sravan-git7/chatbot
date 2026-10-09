"""Phase 8 - end-to-end and artefact tests against the REAL page store, card store and embedding model (skipped, with reasons, when absent),
plus the evaluation-set integrity checks and the protection of Phase 4-7 artefacts."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.phase8_support import CARD_STORE, HAVE_BS4, HAVE_CHROMA, HAVE_NUMPY, PAGE_STORE, ROOT, SCRIPTS, have

import m2c_common as C  # noqa: E402

HAVE_MODEL = False
try:
    C.resolve_model()
    HAVE_MODEL = have("sentence_transformers")
except Exception:                                                      # noqa: BLE001
    HAVE_MODEL = False
STORES = HAVE_CHROMA and HAVE_MODEL and PAGE_STORE.is_dir() and (CARD_STORE / "chroma.sqlite3").is_file() and (PAGE_STORE / "chroma.sqlite3").is_file()
NEED_STORES = unittest.skipUnless(STORES, "needs chromadb, the embedding model, the card store (data/vector_store) and the page store (data/vector_store/page_collection)")

QUERIES = ROOT / "data" / "evaluation" / "phase8_queries.json"
RESULTS = ROOT / "data" / "evaluation" / "phase8_results.json"


def sha(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


class ProtectionTests(unittest.TestCase):
    PINS = {"scripts/rag_chat.py": "e862ce38d06e2ef74f39e366a5a8b65948ba03f00dfab5baa0c61bc281673a15",
            "scripts/rag_core.py": "881316e4f9f2c164b2109f416b2a309f8ab829f185d231b09990274f56567b2c",
            "data/card_collection_manifest.json": "5b3a5c30bc637c8b61573983a16cf252f7899d2c279eae3895e06476482d2731",
            "data/sap_help/CORPUS.json": "19ca34a6222a65c148293202cc40a52890fcc677852de22851bf2af2772d7c52",
            "data/m2c_page_identity.json": "fccb0bb87fc6309ac0fa9e1205387c68aeb6f93fff73d6aab457a2164587787c"}

    def test_phase4_to_7_artefacts_unchanged(self):
        for p, h in self.PINS.items():
            self.assertEqual(sha(p), h, p)

    def test_no_legacy_store_and_no_two_stage_file(self):
        self.assertFalse((ROOT / "chroma_db").exists())
        self.assertFalse((SCRIPTS / "rag_two_stage.py").exists())

    def test_rag_modes_still_rejects_routed(self):
        import rag_modes as rm
        self.assertNotIn("routed", rm.IMPLEMENTED_MODES)
        self.assertIn("routed", rm.SPECIFIED_NOT_IMPLEMENTED)

    def test_page_corpus_is_outside_data_sap_help(self):
        self.assertEqual(len(list((ROOT / "data" / "sap_help" / "pages").glob("*/*.json"))), 1)

    def test_gitignore_covers_the_page_store(self):
        self.assertIn("data/vector_store/", (ROOT / ".gitignore").read_text(encoding="utf-8"))


class EvaluationSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(QUERIES.read_text(encoding="utf-8"))

    def test_size_types_and_disclosure(self):
        qs = self.payload["queries"]
        self.assertTrue(50 <= len(qs) <= 100)
        self.assertEqual(self.payload["counts"], {t: sum(1 for q in qs if q["type"] == t) for t in self.payload["counts"]})
        a = self.payload["authorship"]
        self.assertIn("AI", a["authored_by"])
        self.assertTrue(a["written_before_evaluation"])
        self.assertFalse(a["labels_changed_after_retrieval"])
        self.assertEqual(len({q["id"] for q in qs}), len(qs))
        self.assertEqual(len({q["query"] for q in qs}), len(qs))

    @unittest.skipUnless(HAVE_BS4, "bs4 missing")
    def test_every_evidence_quote_is_verbatim_in_its_gold_page(self):
        import page_corpus as PC
        recs = {r["doc_id"]: " ".join(r["text"].split()) for r in PC.load_records()}
        for q in self.payload["queries"]:
            if q["type"] == "answerable":
                self.assertTrue(q["evidence"])
                for e in q["evidence"]:
                    self.assertIn(" ".join(e.split()), recs[q["gold_doc_id"]], q["id"])
            if q["type"] == "absent_detail":
                for t in q["absent_terms"]:
                    self.assertNotIn(t.lower(), recs[q["gold_doc_id"]].lower(), q["id"])

    def test_queries_do_not_copy_evidence_wholesale(self):
        for q in self.payload["queries"]:
            for e in q.get("evidence", []):
                self.assertNotEqual(" ".join(q["query"].lower().split()).rstrip("?"), " ".join(e.lower().split()).rstrip("."), q["id"])

    def test_gold_cards_have_expected_identity_roles(self):
        import m2c_page_identity as pid
        ctx = pid.IdentityContext.from_root(ROOT)
        idn = {i.source_id: i for i in pid.resolve_all(ctx)}
        for q in self.payload["queries"]:
            if q["type"] == "unresolved_identity":
                self.assertIn(idn[q["gold_source_id"]].resolution_status, (pid.CONFLICTING_IDENTITY, pid.CARD_IDENTITY_ONLY))
            if q["type"] == "not_ingested":
                self.assertEqual(idn[q["gold_source_id"]].resolution_status, pid.IDENTIFIED_NOT_LOCAL)

    def test_preregistered_constants_match_code(self):
        import evaluate_phase8 as ev
        ev.check_preregistered(self.payload)

    @unittest.skipUnless(RESULTS.is_file(), "phase8_results.json not generated")
    def test_results_file_matches_inputs_and_is_not_blended(self):
        res = json.loads(RESULTS.read_text(encoding="utf-8"))
        self.assertEqual(res["queries_file_sha256"], sha("data/evaluation/phase8_queries.json"))
        import page_corpus as PC
        self.assertEqual(res["corpus"]["sha256"], json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))["corpus_sha256"])
        for stage in ("routing", "identity"):
            self.assertIn(stage, res["end_to_end_router_rank1"])
        for stage in ("retrieval", "generation", "citation"):
            self.assertIn(stage, res["end_to_end_oracle_routing"])
        self.assertFalse(res["llm_generation"]["validated"])
        self.assertEqual(res["end_to_end_oracle_routing"]["citation"]["phantom_citations"], 0)
        self.assertEqual(res["end_to_end_router_rank1"]["citation"]["phantom_citations"], 0)
        self.assertEqual(res["end_to_end_router_rank1"]["citation"]["topic_pointer_counted_as_evidence"], 0)
        self.assertTrue(res["end_to_end_router_rank1"]["identity"]["m2c18_never_answered"])
        halluc = res["hallucination_guard"]["cases"]
        self.assertEqual(halluc["faithful_control"]["fabricated_answer_shown"], halluc["faithful_control"]["queries"])
        for name, c in halluc.items():
            if name != "faithful_control":
                self.assertEqual(c["fabricated_answer_shown"], 0, name)


@unittest.skipUnless(HAVE_CHROMA, "chromadb not installed")
class PageStoreValidationTests(unittest.TestCase):
    def test_from_store_rejects_wrong_metric_empty_and_count_mismatch(self):
        import chromadb
        from chromadb.config import Settings
        import page_retriever as PR

        embed = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]
        with tempfile.TemporaryDirectory() as td:
            client = chromadb.PersistentClient(path=td, settings=Settings(anonymized_telemetry=False))
            wrong_metric = client.create_collection("wrong_metric")
            with self.assertRaises(PR.PageStoreUnavailable):
                PR.PageRetriever.from_store(Path(td), "wrong_metric", embed=embed)

            empty = client.create_collection("empty_pages", metadata={"hnsw:space": "cosine", "vector_count": 1})
            with self.assertRaises(PR.PageStoreUnavailable):
                PR.PageRetriever.from_store(Path(td), "empty_pages", embed=embed)

            mismatched = client.create_collection("mismatched_count", metadata={"hnsw:space": "cosine", "vector_count": 2})
            mismatched.add(ids=["chunk-1"], embeddings=[[1.0, 0.0, 0.0]], documents=["text"], metadatas=[{"chunk_id": "chunk-1"}])
            with self.assertRaises(PR.PageStoreUnavailable):
                PR.PageRetriever.from_store(Path(td), "mismatched_count", embed=embed)

    def test_from_store_accepts_nonempty_cosine_collection(self):
        import chromadb
        from chromadb.config import Settings
        import page_retriever as PR

        embed = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]
        with tempfile.TemporaryDirectory() as td:
            client = chromadb.PersistentClient(path=td, settings=Settings(anonymized_telemetry=False))
            collection = client.create_collection("good_pages", metadata={"hnsw:space": "cosine", "vector_count": 1})
            collection.add(ids=["chunk-1"], embeddings=[[1.0, 0.0, 0.0]], documents=["text"], metadatas=[{"chunk_id": "chunk-1"}])
            retriever = PR.PageRetriever.from_store(Path(td), "good_pages", embed=embed)
            self.assertEqual(retriever.count(), 1)


@NEED_STORES
class RealStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import chromadb
        from chromadb.config import Settings
        cls.manifest = json.loads((ROOT / "data" / "page_collection_manifest.json").read_text(encoding="utf-8"))
        cls.page_client = chromadb.PersistentClient(path=str(PAGE_STORE), settings=Settings(anonymized_telemetry=False))
        cls.card_client = chromadb.PersistentClient(path=str(CARD_STORE), settings=Settings(anonymized_telemetry=False))

    def test_page_collection_is_separate_from_card_collection(self):
        names = lambda c: [x.name if hasattr(x, "name") else x for x in c.list_collections()]
        self.assertEqual(names(self.page_client), ["sap_pages_v1"])
        self.assertEqual(names(self.card_client), ["sap_m2c_card_v1"])
        self.assertEqual(self.card_client.get_collection("sap_m2c_card_v1").count(), 29)

    def test_manifest_records_model_dims_metric_corpus_config_count(self):
        m = self.manifest
        col = self.page_client.get_collection("sap_pages_v1")
        self.assertEqual(m["vector_count"], col.count())
        self.assertEqual((m["embedding_dimensions"], m["distance_space"], m["embedding_model"]), (384, "cosine", "all-MiniLM-L6-v2"))
        self.assertEqual(m["chunk_config"]["name"], "B_heading_200")
        self.assertEqual(col.metadata["hnsw:space"], "cosine")
        import page_corpus as PC
        self.assertEqual(m["corpus_sha256"], json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))["corpus_sha256"])
        self.assertEqual(m["card_collection_untouched"]["opened_by_this_script"], False)

    def test_store_matches_a_fresh_chunking_of_the_corpus(self):
        import page_chunker as PK
        import page_corpus as PC
        import build_page_collection as BP
        count, info = PK.make_token_counter()
        chunks = PK.chunk_corpus(PC.load_records(), PK.STRATEGIES["B_heading_200"], count)
        self.assertEqual(BP.chunks_fingerprint(chunks), self.manifest["chunks_fingerprint"])
        col = self.page_client.get_collection("sap_pages_v1")
        got = col.get(include=["documents", "metadatas"])
        self.assertEqual(sorted(got["ids"]), sorted(c["chunk_id"] for c in chunks))
        by_id = {c["chunk_id"]: c for c in chunks}
        for i, d, md in zip(got["ids"], got["documents"], got["metadatas"]):
            self.assertEqual(d, by_id[i]["text"])
            self.assertEqual(md["content_hash"], by_id[i]["content_hash"])
            self.assertEqual(md["source_url"], by_id[i]["source_url"])

    def test_build_is_reproducible_in_a_scratch_directory(self):
        import build_page_collection as BP
        with tempfile.TemporaryDirectory() as d:
            m = BP.build(Path(d) / "pc", "sap_pages_v1", "B_heading_200", False, None, Path(d) / "m.json")
        self.assertEqual(m["chunks_fingerprint"], self.manifest["chunks_fingerprint"])
        self.assertEqual(m["vector_count"], self.manifest["vector_count"])
        self.assertEqual(m["corpus_sha256"], self.manifest["corpus_sha256"])
        self.assertTrue(HAVE_NUMPY)
        self.assertEqual(m["embeddings_float32_sha256"], self.manifest["embeddings_float32_sha256"])

    def test_card_manifest_untouched_by_page_build(self):
        self.assertEqual(sha("data/card_collection_manifest.json"), ProtectionTests.PINS["data/card_collection_manifest.json"])


@NEED_STORES
class RealPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import rag_pipeline as RP
        cls.pipe = RP.build_pipeline(generator="extractive")

    def test_card_first_chain_answers_with_real_page_citations(self):
        a = self.pipe.answer("Which transaction monitors meter reading results?", debug=True)
        self.assertEqual(a["routing"]["selected_source_id"], "M2C-07")
        self.assertEqual(a["status"], "answered")
        self.assertEqual({s["guide_id"] + "/" + s["page_id"] for s in a["citations"]["answer_sources"]}, {"2ac7fe29a0c94cdd88fb80c2cb9f7758/4d76765c1e012b8ae10000000a42189b"})
        self.assertTrue(all(h["guide_id"] == "2ac7fe29a0c94cdd88fb80c2cb9f7758" for h in a["debug"]["retrieved"]))
        self.assertIn("EL31", " ".join(i["text"] for i in a["debug"]["context"]["items"]))

    def test_unresolved_and_not_ingested_and_ood_paths(self):
        a = self.pipe.answer("How do I disconnect a utility installation for non-payment?")
        self.assertEqual(a["status"], "page_not_ingested")
        self.assertEqual(a["citations"]["answer_sources"], [])
        b = self.pipe.answer("What is the contract account business object and what does it represent?")
        self.assertEqual(b["status"], "unresolved_identity")
        c = self.pipe.answer("What is the capital of France?")
        self.assertEqual(c["status"], "out_of_domain")

    def test_oracle_mode_page_answers_cite_gold_page_only(self):
        a = self.pipe.answer("What does invoicing with bill creation result in?", oracle_source_id="M2C-14", debug=True)
        self.assertEqual(a["status"], "answered", a["reason_code"])
        self.assertTrue(all(s["page_id"] == "cc7bce53118d4308e10000000a174cb4" for s in a["citations"]["answer_sources"]))
        self.assertTrue(a["topic"]["review_flag"])

    def test_every_answer_in_the_eval_set_is_verifier_clean_and_never_phantom(self):
        qs = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"][:25]
        for q in qs:
            a = self.pipe.answer(q["query"], debug=True)
            if a["status"] == "answered":
                self.assertTrue(a["debug"]["grounding"]["ok"])
                ctx_ids = {i["chunk_id"] for i in a["debug"]["context"]["items"]}
                self.assertTrue({s["chunk_id"] for s in a["citations"]["answer_sources"]} <= ctx_ids)
            else:
                self.assertEqual(a["citations"]["answer_sources"], [])


if __name__ == "__main__":
    unittest.main()


class ReportConsistencyTests(unittest.TestCase):
    @unittest.skipUnless(RESULTS.is_file() and (ROOT / "data" / "phase8_report.md").is_file(), "report or results missing")
    def test_report_headline_numbers_match_results_json(self):
        res = json.loads(RESULTS.read_text(encoding="utf-8"))
        text = (ROOT / "data" / "phase8_report.md").read_text(encoding="utf-8")
        rr = res["end_to_end_router_rank1"]
        self.assertIn("%.4f" % rr["routing"]["top1"]["rate"], text)
        self.assertIn("%.3f" % rr["routing"]["mrr"], text)
        o = res["end_to_end_oracle_routing"]["generation"]
        self.assertIn("%d/%d" % (o["answered_given_answerable"]["k"], o["answered_given_answerable"]["n"]), text)
        self.assertIn(res["corpus"]["sha256"][:8], text)
        for t in ("1. Executive summary", "20. Phase 9 recommendations"):
            self.assertIn("## " + t, text)
        self.assertEqual(text.count("\n## "), 20)
