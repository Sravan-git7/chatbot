"""Phase 7B tests: the REAL `sap_m2c_card_v1` collection and the REAL embedding model, accessed through the Phase 7A router.

Store-dependent classes skip (with an explicit reason) when `data/vector_store/`, chromadb, sentence-transformers or the local
all-MiniLM-L6-v2 files are missing; rebuild the store with `python scripts/build_card_collection.py`. No mock collection is used
for the primary tests. No LLM, no legacy retriever, no network.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import m2c_common as C  # noqa: E402
import m2c_orchestrator as orch  # noqa: E402
import m2c_page_join as pj  # noqa: E402
import m2c_router as rt  # noqa: E402

VECTOR = C.VECTOR_DIR
EVAL = ROOT / "data" / "evaluation"
CHECKPOINT = ROOT / "data" / "phase7_checkpoint.md"
VALIDATION = ROOT / "data" / "phase7B_validation.json"
KNOWN_SOURCE_ISSUES = ("M2C-05", "M2C-14", "M2C-18", "M2C-23")


def _have(mod):
    return importlib.util.find_spec(mod) is not None


def _model_available():
    try:
        C.resolve_model()
        return True
    except Exception:
        return False


LIVE = VECTOR.is_dir() and (VECTOR / "chroma.sqlite3").is_file() and _have("chromadb") and _have("sentence_transformers") and _model_available()
SKIP_MSG = "needs data/vector_store (build_card_collection.py), chromadb, sentence-transformers and the local all-MiniLM-L6-v2 files"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


UNITS = load(C.UNITS_PATH)["units"]
BY_ID = {u["source_id"]: u for u in UNITS}
MANIFEST = load(ROOT / "data" / "card_collection_manifest.json")
P4 = load(EVAL / "card_retrieval_results.json")["per_question"]
P5_QUERIES = {q["query_id"]: q["query"] for q in load(EVAL / "independent_queries.json")["queries"]}
P5_ROWS = load(EVAL / "phase5_results.json")["datasets"]["phase5"]["systems"]["dense"]["rows"]

_STATE: dict = {}


def live():
    """Shared real resources (one model load for the module)."""
    if not _STATE:
        bcc = importlib.import_module("build_card_collection")
        backend = rt.ChromaCardBackend(vector_dir=VECTOR)
        _STATE.update(bcc=bcc, backend=backend, routes={}, index=pj.PageContentIndex.from_directory())
    return _STATE


def route_full(query):
    st = live()
    if query not in st["routes"]:
        st["routes"][query] = rt.route(query, st["backend"], top_k=29)
    return st["routes"][query]


def open_collection():
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(path=str(VECTOR), settings=Settings(anonymized_telemetry=False))
    return client, client.get_collection(C.COLLECTION_NAME)


@unittest.skipUnless(LIVE, SKIP_MSG)
class RealCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client, cls.col = open_collection()
        got = cls.col.get(include=["documents", "metadatas", "embeddings"])
        cls.got = got

    def test_collection_name_and_only_collection(self):
        names = sorted(getattr(c, "name", c) for c in self.client.list_collections())
        self.assertEqual(names, ["sap_m2c_card_v1"])
        self.assertNotIn("sap_docs", names)

    def test_count_dimension_metric(self):
        import numpy as np
        self.assertEqual(self.col.count(), 29)
        emb = np.asarray(self.got["embeddings"])
        self.assertEqual(emb.shape, (29, 384))
        self.assertEqual(self.col.metadata.get("hnsw:space"), "cosine")
        self.assertEqual(self.col.metadata.get("embedding_dimensions"), 384)
        self.assertEqual(self.col.metadata.get("embedding_model"), "all-MiniLM-L6-v2")

    def test_configuration_and_hashes_match_the_recorded_manifest(self):
        md = self.col.metadata
        self.assertEqual(json.loads(md["config_json"]), MANIFEST["configuration"])
        self.assertEqual(md["retrieval_units_file_sha256"], MANIFEST["retrieval_units_file_sha256"])
        self.assertEqual(md["retrieval_units_file_sha256"], sha(C.UNITS_PATH))
        self.assertEqual(md["source_corpus_file_sha256"], MANIFEST["source_corpus_file_sha256"])
        self.assertEqual(md["source_corpus_file_sha256"], sha(C.CORPUS_PATH))
        self.assertEqual(MANIFEST["token_stats_file_sha256"], sha(C.TOKEN_STATS_PATH))

    def test_model_identity_matches_the_recorded_manifest(self):
        _dir, info = C.resolve_model()
        rec = MANIFEST["embedding_model_provenance"]
        self.assertEqual(info["origin"], rec["origin"])
        self.assertEqual(info["files_sha256"], rec["files_sha256"])

    def test_every_source_id_once_and_metadata_complete_and_unchanged(self):
        bcc = live()["bcc"]
        ids = self.got["ids"]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(BY_ID))
        for i, meta, doc in zip(ids, self.got["metadatas"], self.got["documents"]):
            self.assertEqual(meta, bcc.metadata_for(BY_ID[i]), i)
            self.assertEqual(doc, BY_ID[i]["embedding_text"], i)
            self.assertIn("source_url", meta)
            self.assertNotIn("url", meta, f"{i}: legacy 'url' alias must not exist")

    def test_stored_vectors_match_the_model_within_tolerance(self):
        import numpy as np
        from sentence_transformers import SentenceTransformer
        model_dir, _ = C.resolve_model()
        model = SentenceTransformer(model_dir, device="cpu")
        order = sorted(range(29), key=lambda k: self.got["ids"][k])
        ids = [self.got["ids"][k] for k in order]
        stored = np.asarray([self.got["embeddings"][k] for k in order], dtype="float32")
        fresh = model.encode([BY_ID[i]["embedding_text"] for i in ids], batch_size=16, normalize_embeddings=True,
                             convert_to_numpy=True, show_progress_bar=False).astype("float32")
        self.assertLess(float(np.max(np.abs(fresh - stored))), 1e-6)

    def test_legacy_stores_not_created(self):
        self.assertFalse((ROOT / "chroma_db").exists())


@unittest.skipUnless(LIVE, SKIP_MSG)
class RealRouterTests(unittest.TestCase):
    QUERIES = ["Contract Accounts Overview", "Move-In Process", "extrapolation", "dunning", "What is needed for final billing when a customer moves out?"]

    def test_round_trip_normalises_metadata_and_preserves_source_url(self):
        for q in self.QUERIES:
            res = route_full(q)
            self.assertEqual(len(res.candidates), 29)
            for c in res.candidates:
                u = BY_ID[c.source_id]
                self.assertEqual(c.source_url, u["source_url"])
                self.assertEqual((c.title, c.category, c.source_status, c.source_url_status, c.citation),
                                 (u["title"], u["category"], u["source_status"], u["source_url_status"], u["citation"]))
                self.assertIs(c.has_source_correction, bool(u["has_source_correction"]))
                self.assertFalse(hasattr(c, "url"))
                self.assertNotIn("url", c.to_dict())

    def test_rank_ordering_and_cosine_distance_are_the_real_values(self):
        import numpy as np
        from sentence_transformers import SentenceTransformer
        _client, col = open_collection()
        got = col.get(include=["embeddings"])
        order = sorted(range(29), key=lambda k: got["ids"][k])
        ids = [got["ids"][k] for k in order]
        mat = np.asarray([got["embeddings"][k] for k in order], dtype="float32")
        model_dir, _ = C.resolve_model()
        model = SentenceTransformer(model_dir, device="cpu")
        qv = model.encode(self.QUERIES, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype("float32")
        ref = 1.0 - qv @ mat.T
        for q, refrow in zip(self.QUERIES, ref):
            res = route_full(q)
            d = [c.distance for c in res.candidates]
            self.assertEqual([c.rank for c in res.candidates], list(range(1, 30)))
            self.assertEqual(d, sorted(d))
            self.assertEqual(d[0], min(d))
            self.assertEqual(res.distance_metric, "cosine")
            ref_by = dict(zip(ids, map(float, refrow)))
            for c in res.candidates:
                self.assertAlmostEqual(c.distance, ref_by[c.source_id], places=5)
            self.assertEqual([c.source_id for c in res.candidates], [i for i, _ in sorted(ref_by.items(), key=lambda kv: (kv[1], kv[0]))])

    def test_no_legacy_threshold_or_undocumented_cutoff(self):
        for q in ("extrapolation", "subledger processing"):      # weak-signal queries: nearest distances are large
            res = route_full(q)
            self.assertEqual(len(res.candidates), 29)
            self.assertGreater(res.candidates[0].distance, 0.5)        # would be dropped by a legacy-style gate; it is returned
            self.assertGreater(sum(1 for c in res.candidates if c.distance > 0.5), 20)   # far cards are returned too (no gate)
        res5 = rt.route("dunning", live()["backend"], top_k=5)
        self.assertEqual(len(res5.candidates), 5)
        self.assertEqual([c.source_id for c in res5.candidates], [c.source_id for c in route_full("dunning").candidates[:5]])

    def test_known_source_issues_remain_visible(self):
        by = {c.source_id: c for c in route_full("meter to cash reference").candidates}
        for sid in KNOWN_SOURCE_ISSUES:
            c, u = by[sid], BY_ID[sid]
            self.assertEqual((c.source_status, c.source_url_status, c.has_source_correction),
                             (u["source_status"], u["source_url_status"], bool(u["has_source_correction"])))
            self.assertTrue(c.source_status != "verified" or c.source_url_status != "ok" or c.has_source_correction, sid)
        self.assertTrue(by["M2C-05"].has_source_correction)
        for sid in ("M2C-14", "M2C-18", "M2C-23"):
            self.assertEqual((by[sid].source_status, by[sid].source_url_status), ("needs_review", "needs_review"))
        self.assertIn("?version=2025.001", by["M2C-18"].source_url)            # not altered
        self.assertIn("sap_s4hana_on-premise", by["M2C-14"].source_url)        # not altered


@unittest.skipUnless(LIVE, SKIP_MSG)
class RegressionTests(unittest.TestCase):
    def test_phase4_top5_rankings_reproduce(self):
        for r in P4:
            res = route_full(r["question"])
            ids = [c.source_id for c in res.candidates]
            rec = r["retrieved_top5"]
            self.assertEqual(ids[:5], [x["source_id"] for x in rec], r["question_id"])
            for c, x in zip(res.candidates[:5], rec):
                self.assertEqual(round(1.0 - c.distance, 4), x["cosine_similarity"], r["question_id"])
            first = min((ids.index(e) + 1 for e in r["expected_source_ids"] if e in ids), default=None)
            self.assertEqual(first, r["first_expected_rank"], r["question_id"])

    def test_phase5_retrieval_rankings_reproduce(self):
        self.assertEqual(len(P5_ROWS), 54)
        for r in P5_ROWS:
            res = route_full(P5_QUERIES[r["id"]])
            ids = [c.source_id for c in res.candidates]
            self.assertEqual(ids[:5], [x["source_id"] for x in r["top5"]], r["id"])
            for c, x in zip(res.candidates[:5], r["top5"]):
                self.assertEqual(round(1.0 - c.distance, 4), x["score"], r["id"])
            first = min((ids.index(e) + 1 for e in r["expected_source_ids"] if e in ids), default=None)
            self.assertEqual(first, r["first_expected_rank"], r["id"])

    def test_recorded_metrics_reproduce(self):
        rec4 = load(EVAL / "card_retrieval_results.json")["metrics"]["overall"]
        ranks = []
        for r in P4:
            ids = [c.source_id for c in route_full(r["question"]).candidates]
            ranks.append(min((ids.index(e) + 1 for e in r["expected_source_ids"] if e in ids), default=None))
        self.assertEqual(round(sum(1 for x in ranks if x == 1) / 50, 4), rec4["recall@1"])
        self.assertEqual(round(sum(1 for x in ranks if x and x <= 3) / 50, 4), rec4["recall@3"])
        self.assertEqual(round(sum(1.0 / x for x in ranks if x) / 50, 4), rec4["mrr"])


class RealJoinTests(unittest.TestCase):
    """Card -> page join against the real repository (no store needed: uses the units and the local page records)."""

    @staticmethod
    def ok_pages():
        out = set()
        for p in (ROOT / "data" / "sap_help" / "pages").glob("*/*.json"):
            rec = load(p)
            if rec.get("status") == "OK" and str(rec.get("text") or "").strip():
                out.add((rec["guide_id"].lower(), rec["page_id"].lower()))
        return out

    def test_all_29_cards_are_classified_by_the_join_criteria_only(self):
        index = pj.PageContentIndex.from_directory()
        ok = self.ok_pages()
        states = {}
        for u in UNITS:
            r = pj.resolve_card_page(u, index)
            states[u["source_id"]] = r
            expected = pj.RESOLVED_PAGE if pj.parse_source_url(u["source_url"]) in ok else pj.URL_ONLY
            self.assertEqual(r.state, expected, u["source_id"])
            self.assertTrue(r.card_exists and r.url_exists, u["source_id"])
            self.assertEqual(r.local_page_content, r.state == pj.RESOLVED_PAGE)
        self.assertEqual(len(states), 29)
        self.assertEqual(states["M2C-17"].state, pj.RESOLVED_PAGE)
        resolved = {k for k, v in states.items() if v.state == pj.RESOLVED_PAGE}
        self.assertEqual(len(resolved), len(ok & {pj.parse_source_url(u["source_url"]) for u in UNITS}))

    def test_url_only_is_not_treated_as_page_content(self):
        index = pj.PageContentIndex.from_directory()
        url_only = [pj.resolve_card_page(u, index) for u in UNITS if pj.resolve_card_page(u, index).state == pj.URL_ONLY]
        self.assertTrue(url_only)
        for r in url_only:
            self.assertFalse(r.local_page_content)
            self.assertIsNone(r.content_path)
            self.assertEqual(r.reason, pj.REASON_NO_LOCAL_PAGE)

    def test_unprocessed_files_are_not_counted_as_page_content(self):
        """Captured raw responses and saved TOCs exist in the repository but never make a card resolved."""
        self.assertTrue(any((ROOT / "captured_responses").glob("*.json")))
        self.assertTrue(any((ROOT / "data" / "toc").glob("*")))
        index = pj.PageContentIndex.from_directory()
        self.assertEqual(len(index), len(list((ROOT / "data" / "sap_help" / "pages").glob("*/*.json"))))


@unittest.skipUnless(LIVE, SKIP_MSG)
class RealOrchestratorTests(unittest.TestCase):
    def test_real_collection_router_join_chain(self):
        st = live()
        ok = RealJoinTests.ok_pages()
        o = orch.route_to_page("Contract Accounts Overview", st["backend"], st["index"])
        self.assertEqual(o.selected_card.source_id, "M2C-17")
        self.assertEqual(o.state, orch.RESOLVED_PAGE if pj.parse_source_url(BY_ID["M2C-17"]["source_url"]) in ok else orch.URL_ONLY)
        self.assertEqual(o.source_url, BY_ID["M2C-17"]["source_url"])
        self.assertTrue(o.page_content_available)
        o2 = orch.route_to_page("Move-In Process", st["backend"], st["index"])
        self.assertEqual(o2.selected_card.source_id, "M2C-03")
        self.assertEqual(o2.state, orch.URL_ONLY)
        self.assertFalse(o2.page_content_available)
        self.assertEqual(o2.fallback_reason, pj.REASON_NO_LOCAL_PAGE)
        o3 = orch.route_to_page("control role of the contract account for postings, payments and dunning", st["backend"], st["index"])
        self.assertEqual(o3.selected_card.source_id, "M2C-18")
        self.assertEqual(o3.selected_card.source_status, "needs_review")
        self.assertEqual(len(o3.candidates), 5)
        o4 = orch.route_to_page("Installment Plan Overview", st["backend"], st["index"])       # recorded sibling near-tie (Q07)
        self.assertEqual([c.source_id for c in o4.candidates[:2]], ["M2C-24", "M2C-23"])
        self.assertLess(o4.candidates[1].distance - o4.candidates[0].distance, 0.01)
        o5 = orch.route_to_page("   ", st["backend"], st["index"])
        self.assertEqual((o5.state, o5.fallback_reason), (orch.NO_CARD_CANDIDATE, orch.FALLBACK_EMPTY_QUERY))
        o6 = orch.route_to_page("extrapolation", st["backend"], st["index"], selector=lambda cs: None)
        self.assertEqual(o6.state, orch.NO_CARD_CANDIDATE)
        self.assertEqual(len(o6.candidates), 5)

    def test_fresh_process_loads_no_llm_or_legacy_module_and_uses_no_network(self):
        code = r"""
import json, socket, sys
attempts = []
def blocked(*a, **k):
    attempts.append(1); raise OSError("network disabled")
socket.socket.connect = blocked; socket.create_connection = blocked; socket.getaddrinfo = blocked
sys.path.insert(0, %r)
import m2c_router as rt, m2c_page_join as pj, m2c_orchestrator as o
out = o.route_to_page("Contract Accounts Overview", rt.ChromaCardBackend(), pj.PageContentIndex.from_directory())
bad = sorted(m for m in ("ollama", "rag_core", "rag_chat", "retrieve", "evaluate_retrieval", "create_embeddings", "requests", "sap_resolver") if m in sys.modules)
print(json.dumps({"state": out.state, "bad": bad, "attempts": len(attempts)}))
""" % str(SCRIPTS)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        res = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(res["bad"], [])
        self.assertEqual(res["attempts"], 0)
        self.assertEqual(res["state"], "resolved_page")


@unittest.skipUnless(LIVE and VALIDATION.is_file(), SKIP_MSG)
class ReproducibilityTests(unittest.TestCase):
    def test_recorded_validation_is_ok_and_a_fresh_run_reproduces_it(self):
        rec = load(VALIDATION)
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["network_attempts"], 0)
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "again.json"
            r = subprocess.run([sys.executable, str(SCRIPTS / "phase7b_validate.py"), "--stage", "all", "--out", str(out)],
                               capture_output=True, text=True, timeout=300, cwd=ROOT)
            self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
            new = load(out)
        self.assertEqual(new["stages"]["router"], rec["stages"]["router"])          # rankings, distances (6 dp), metadata, joins, scenarios
        self.assertEqual(new["stages"]["preflight"], rec["stages"]["preflight"])
        for k in ("stored_vs_recomputed_max_abs_diff", "recomputed_embeddings_float32_sha256", "stored_embeddings_float32_sha256"):
            self.assertEqual(new["stages"]["collection"][k], rec["stages"]["collection"][k], k)
        self.assertTrue(new["ok"])


class SafetyTests(unittest.TestCase):
    # SHA-256 of the Phase 7A deliverables, recorded at the start of Phase 7B (they are not edited in 7B)
    PHASE_7A = {
        "scripts/m2c_router.py": "b846f18d098406c17859d053ae5b9c0ddb5b82e247e92ac709edeed1113ea8f4",
        "scripts/m2c_page_join.py": "a7744701a710df9575eea3861a61204ee63deb995f761cc715dcd150b6dee156",
        "scripts/m2c_orchestrator.py": "89bcfcc1c57669f492d92d12e2f720b2e9d9b36035c678737db4d081213782dd",
        "tests/test_phase7a.py": "58aa1bed1984d5918861e5f292652956941f01f4bb886700cc15ceb739997bda",
        "data/phase7_checkpoint.md": "9d5dc410e1f97c42c182453ebd707af7f2722b79a472a7cea84db774b75b568c",
        "data/phase7A_report.md": "3c215c54286ccc090951760dab182238465d6d1babb4d3d2f014f4ab88679737",
    }

    def test_checkpoint_protected_set_is_unchanged(self):
        text = CHECKPOINT.read_text(encoding="utf-8")
        block = text.split("<!-- sha256-begin -->", 1)[1].split("<!-- sha256-end -->", 1)[0]
        entries = {}
        for line in block.splitlines():
            line = line.strip()
            if line and not line.startswith("```"):
                d, p = line.split(None, 1)
                entries[p.strip()] = d
        self.assertGreater(len(entries), 200)
        bad = [p for p, d in entries.items() if not (ROOT / p).is_file() or sha(ROOT / p) != d]
        self.assertEqual(bad, [])
        for p in ("data/retrieval_units.json", "data/retrieval_token_stats.json", "data/card_collection_manifest.json",
                  "data/source_corpus.json", "data/source_manifest.json", "data/evaluation/card_retrieval_results.json",
                  "data/evaluation/phase5_results.json", "data/retrieval_phase4_report.md", "data/retrieval_phase5_report.md",
                  "scripts/rag_core.py", "scripts/rag_chat.py", "scripts/retrieve.py", "scripts/evaluate_retrieval.py",
                  "scripts/create_embeddings.py", "scripts/chunk_pages.py", "scripts/clean_sap_pages.py", "scripts/audit_corpus.py"):
            self.assertIn(p, entries, p)

    def test_phase_4_and_5_inputs_and_manifest_hashes_are_consistent(self):
        p4 = load(EVAL / "card_retrieval_results.json")
        self.assertEqual(p4["retrieval_units_file_sha256"], sha(C.UNITS_PATH))
        self.assertEqual(p4["collection_manifest_sha256"], sha(ROOT / "data" / "card_collection_manifest.json"))
        self.assertEqual(p4["questions_file_sha256"], sha(EVAL / "card_retrieval_questions.json"))
        self.assertEqual(MANIFEST["retrieval_units_file_sha256"], sha(C.UNITS_PATH))
        self.assertEqual(MANIFEST["token_stats_file_sha256"], sha(C.TOKEN_STATS_PATH))
        self.assertEqual(MANIFEST["source_corpus_file_sha256"], sha(C.CORPUS_PATH))
        p5 = load(EVAL / "phase5_results.json")["inputs"]
        self.assertEqual(p5["independent_queries_sha256"], sha(EVAL / "independent_queries.json"))
        self.assertEqual(p5["phase4_results_sha256"], sha(EVAL / "card_retrieval_results.json"))

    def test_phase_7a_deliverables_are_unchanged(self):
        for p, d in self.PHASE_7A.items():
            self.assertEqual(sha(ROOT / p), d, p)

    def test_legacy_store_does_not_exist_and_card_store_is_not_named_like_it(self):
        self.assertFalse((ROOT / "chroma_db").exists())
        self.assertNotEqual(C.COLLECTION_NAME, C.LEGACY_COLLECTION_NAME)
        self.assertEqual(VECTOR.name, "vector_store")

    def test_validation_script_is_read_only_with_respect_to_protected_code(self):
        import ast
        src = (SCRIPTS / "phase7b_validate.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add((n.module or "").split(".")[0])
        for banned in ("ollama", "requests", "rag_core", "rag_chat", "retrieve", "evaluate_retrieval", "create_embeddings", "sap_resolver"):
            self.assertNotIn(banned, names)
        for attr in ("add", "upsert", "delete", "delete_collection", "create_collection", "modify"):
            self.assertNotIn(f".{attr}(", src, f"validation script must not call .{attr}(")


if __name__ == "__main__":
    unittest.main()
