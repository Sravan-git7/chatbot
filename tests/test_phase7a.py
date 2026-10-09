"""Phase 7A tests: M2C router, card->page join, routing orchestrator.

Everything except the clearly marked ChromaDB round-trip tests runs on mocked retrieval data: no model, no vector store,
no Ollama, no network. The ChromaDB tests build a throw-away collection under pytest's tmp_path with hand-made vectors
(not the real card store) to check the real Chroma result shape and the refusal/safety paths of the default backend.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import m2c_orchestrator as orch  # noqa: E402
import m2c_page_join as pj  # noqa: E402
import m2c_router as rt  # noqa: E402

try:
    import chromadb  # noqa: F401
    HAVE_CHROMA = True
except ImportError:  # pragma: no cover
    HAVE_CHROMA = False

NEW_MODULES = [SCRIPTS / "m2c_router.py", SCRIPTS / "m2c_page_join.py", SCRIPTS / "m2c_orchestrator.py"]
VECTOR_STORE_EXISTED_AT_IMPORT = (ROOT / "data" / "vector_store").exists()
CHECKPOINT = ROOT / "data" / "phase7_checkpoint.md"

G1 = "e52c8ee6197147ec97dfc2eb8c46a3ad"
P17 = "0bfcc5536a51204be10000000a174cb4"
G2 = "2ac7fe29" + "0" * 24
P2 = "a" * 32


def url(guide=G1, page=P17, product="SAP_S4HANA_ON-PREMISE", suffix=""):
    return f"https://help.sap.com/docs/{product}/{guide}/{page}.html{suffix}"


def meta(n=17, **over):
    m = {
        "retrieval_unit_id": f"M2C-{n:02d}", "source_id": f"M2C-{n:02d}", "source_number": n, "title": f"Title {n}",
        "category": "FI-CA / Contract Accounting", "filename": f"{n:02d}_x.pdf", "source_url": url(),
        "source_status": "verified", "source_url_status": "ok", "has_source_correction": False,
        "citation": f"[{n}] Title {n} ({n:02d}_x.pdf, sha256:abcdef012345)", "sha256": "f" * 64,
        "corpus_document": f"doc-{n}", "page_start": 1, "page_end": 1,
        "embedding_text_sha256": "e" * 64, "full_text_sha256": "d" * 64,
    }
    m.update(over)
    return m


class FakeBackend:
    """Chroma-shaped results in a fixed order; records every call."""

    distance_metric = "cosine"

    def __init__(self, rows):
        self.rows = rows                     # list of (metadata, distance)
        self.calls = []

    def query(self, query, n_results):
        self.calls.append((query, n_results))
        rows = self.rows[:n_results]
        return {"ids": [[m.get("source_id", "M2C-01") for m, _ in rows]], "metadatas": [[m for m, _ in rows]], "distances": [[d for _, d in rows]]}


def write_page(root: Path, guide, page, status="OK", text="Some SAP page text.", topic_ids=(17,)):
    d = root / guide
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{page}.json").write_text(json.dumps({
        "guide_id": guide, "page_id": page, "doc_id": f"{guide}/{page}", "status": status, "text": text,
        "topic_ids": list(topic_ids), "page_title": "Page"}), encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------------------ router

class RouterTests(unittest.TestCase):
    def test_returns_normalised_metadata(self):
        b = FakeBackend([(meta(17), 0.31), (meta(3, source_status="needs_review", source_url_status="needs_review"), 0.52)])
        r = rt.route("contract accounts", b, top_k=2)
        self.assertEqual([c.rank for c in r.candidates], [1, 2])
        c = r.candidates[0]
        for f in ("source_id", "title", "category", "source_url", "source_status", "source_url_status",
                  "has_source_correction", "citation", "distance", "rank"):
            self.assertTrue(hasattr(c, f), f)
        self.assertEqual((c.source_id, c.title, c.category), ("M2C-17", "Title 17", "FI-CA / Contract Accounting"))
        self.assertIs(c.has_source_correction, False)
        self.assertEqual(r.candidates[1].source_status, "needs_review")
        self.assertEqual(c.source_number, 17)
        self.assertEqual(c.distance_metric, "cosine")
        d = c.to_dict()
        json.dumps(d)
        self.assertEqual(d["distance"], 0.31)

    def test_source_url_is_preserved_unmodified(self):
        odd = url(guide="9442486404b54071b4ebeab6a16628e7", page="b1a202c9bb3011da2b24000f20dac9ef", suffix="?version=2025.001")
        r = rt.route("q", FakeBackend([(meta(18, source_url=odd), 0.4)]))
        self.assertEqual(r.candidates[0].source_url, odd)
        lower = url(product="sap_s4hana_on-premise")
        r = rt.route("q", FakeBackend([(meta(1, source_url=lower), 0.4)]))
        self.assertEqual(r.candidates[0].source_url, lower)

    def test_legacy_url_key_is_not_assumed(self):
        legacy_only = meta(5)
        del legacy_only["source_url"]
        legacy_only["url"] = url()
        with self.assertRaises(rt.CardMetadataError) as cm:
            rt.route("q", FakeBackend([(legacy_only, 0.2)]))
        self.assertIn("source_url", str(cm.exception))
        self.assertIn("legacy", str(cm.exception))
        # both keys present: source_url wins, and no url attribute/key is exposed
        both = meta(6, url="https://legacy.example/other")
        c = rt.route("q", FakeBackend([(both, 0.2)])).candidates[0]
        self.assertEqual(c.source_url, url())
        self.assertFalse(hasattr(c, "url"))
        self.assertNotIn("url", c.to_dict())

    def test_no_legacy_max_distance_is_applied(self):
        far = [(meta(i), d) for i, d in [(1, 0.3), (2, 1.0), (3, 1.4), (4, 1.99)]]
        r = rt.route("q", FakeBackend(far), top_k=4)
        self.assertEqual([c.distance for c in r.candidates], [0.3, 1.0, 1.4, 1.99])
        # AST: the modules never reference the legacy constant in code (docstrings may mention it)
        for p in NEW_MODULES:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
            self.assertNotIn("MAX_DISTANCE", names, p.name)

    def test_ranking_order_is_preserved(self):
        rows = [(meta(9), 0.50), (meta(2), 0.20), (meta(7), 0.90)]   # deliberately not sorted by distance
        r = rt.route("q", FakeBackend(rows), top_k=3)
        self.assertEqual([c.source_id for c in r.candidates], ["M2C-09", "M2C-02", "M2C-07"])
        self.assertEqual([c.rank for c in r.candidates], [1, 2, 3])

    def test_top_k_limits_and_is_validated(self):
        rows = [(meta(i), i / 10) for i in range(1, 8)]
        b = FakeBackend(rows)
        self.assertEqual(len(rt.route("q", b, top_k=3).candidates), 3)
        self.assertEqual(b.calls[-1][1], 3)
        self.assertEqual(len(rt.route("q", b).candidates), rt.DEFAULT_TOP_K)
        for bad in (0, -1, True, "5", 2.5, None):
            with self.assertRaises(rt.RouterConfigError):
                rt.route("q", b, top_k=bad)

    def test_empty_query_does_not_call_backend(self):
        b = FakeBackend([(meta(1), 0.1)])
        for q in ("", "   ", "\n\t"):
            r = rt.route(q, b)
            self.assertEqual(r.candidates, ())
        self.assertEqual(b.calls, [])
        with self.assertRaises(rt.RouterConfigError):
            rt.route(None, b)  # type: ignore[arg-type]

    def test_query_is_stripped_before_backend_call(self):
        b = FakeBackend([(meta(1), 0.1)])
        r = rt.route("  hello  ", b)
        self.assertEqual(b.calls[0][0], "hello")
        self.assertEqual(r.query, "  hello  ")

    def test_non_cosine_backend_is_refused(self):
        class L2(FakeBackend):
            distance_metric = "l2"
        with self.assertRaises(rt.RouterConfigError):
            rt.route("q", L2([(meta(1), 0.1)]))
        class Nothing:
            def query(self, q, n): return {}
        with self.assertRaises(rt.RouterConfigError):
            rt.route("q", Nothing())  # type: ignore[arg-type]

    def test_malformed_records_fail_loudly(self):
        for bad in ("title", "citation", "source_status", "source_url_status", "has_source_correction", "category", "source_id"):
            m = meta(1)
            del m[bad]
            with self.assertRaises(rt.CardMetadataError, msg=bad):
                rt.route("q", FakeBackend([(m, 0.1)]))
        for d in (float("nan"), float("inf"), "0.1", None, True):
            with self.assertRaises(rt.CardMetadataError, msg=repr(d)):
                rt.route("q", FakeBackend([(meta(1), d)]))
        with self.assertRaises(rt.CardMetadataError):
            rt.route("q", FakeBackend([(meta(1, has_source_correction="no"), 0.1)]))

        class Mismatch(FakeBackend):
            def query(self, q, n):
                r = super().query(q, n)
                r["ids"] = [["M2C-99"]]
                return r
        with self.assertRaises(rt.CardMetadataError):
            rt.route("q", Mismatch([(meta(1), 0.1)]))

        class BadShape(FakeBackend):
            def query(self, q, n):
                return {"ids": [], "metadatas": [], "distances": []}
        with self.assertRaises(rt.CardMetadataError):
            rt.route("q", BadShape([]))

    def test_real_card_metadata_shape_from_units_is_accepted(self):
        """All 29 real cards, with the metadata exactly as build_card_collection stores it, normalise without error."""
        bcc = importlib.import_module("build_card_collection")
        units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))["units"]
        rows = [(bcc.metadata_for(u), 0.1 * (i % 7)) for i, u in enumerate(units)]
        r = rt.route("q", FakeBackend(rows), top_k=len(rows))
        self.assertEqual(len(r.candidates), 29)
        by_id = {c.source_id: c for c in r.candidates}
        for u in units:
            self.assertEqual(by_id[u["source_id"]].source_url, u["source_url"])
            self.assertEqual(by_id[u["source_id"]].citation, u["citation"])
        self.assertEqual({c.source_id for c in r.candidates if c.source_status == "needs_review"}, {"M2C-14", "M2C-18", "M2C-23"})

    def test_default_backend_refuses_legacy_names_and_never_creates_a_store(self):
        with self.assertRaises(rt.RouterConfigError):
            rt.ChromaCardBackend(collection_name="sap_docs")
        with self.assertRaises(rt.RouterConfigError):
            rt.ChromaCardBackend(vector_dir=ROOT / "chroma_db")

    def test_default_backend_missing_store_raises_and_creates_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "no_store_here"
            b = rt.ChromaCardBackend(vector_dir=missing, embedder=lambda t: [[1.0, 0.0, 0.0]])
            with self.assertRaises(rt.CardStoreUnavailable):
                rt.route("q", b)
            self.assertFalse(missing.exists())
            empty_dir = Path(td) / "empty"
            empty_dir.mkdir()
            b2 = rt.ChromaCardBackend(vector_dir=empty_dir, embedder=lambda t: [[1.0, 0.0, 0.0]])
            with self.assertRaises(rt.CardStoreUnavailable):
                rt.route("q", b2)
            self.assertEqual(list(empty_dir.iterdir()), [])


@unittest.skipUnless(HAVE_CHROMA, "chromadb not installed")
class ChromaRoundTripTests(unittest.TestCase):
    """Throw-away collection in a temp dir (3-d hand-made vectors). NOT the real sap_m2c_card_v1 store."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from chromadb.config import Settings
        cls.td = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.td.name) / "store"
        client = chromadb.PersistentClient(path=str(cls.dir), settings=Settings(anonymized_telemetry=False))
        col = client.create_collection("test_cards", metadata={"hnsw:space": "cosine"})
        vecs = {1: [1.0, 0.0, 0.0], 2: [0.8, 0.6, 0.0], 3: [0.0, 1.0, 0.0]}
        col.add(ids=[f"M2C-{i:02d}" for i in vecs], embeddings=list(vecs.values()), documents=[f"d{i}" for i in vecs],
                metadatas=[meta(i) for i in vecs])
        l2 = client.create_collection("l2_cards")      # default space = squared L2
        l2.add(ids=["M2C-01"], embeddings=[[1.0, 0.0, 0.0]], documents=["d"], metadatas=[meta(1)])
        del client

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def backend(self, name="test_cards"):
        return rt.ChromaCardBackend(vector_dir=self.dir, collection_name=name, embedder=lambda texts: [[1.0, 0.0, 0.0]] * len(texts))

    def test_real_chroma_shape_and_cosine_distance(self):
        r = rt.route("anything", self.backend(), top_k=3)
        self.assertEqual([c.source_id for c in r.candidates], ["M2C-01", "M2C-02", "M2C-03"])
        self.assertAlmostEqual(r.candidates[0].distance, 0.0, places=5)
        self.assertAlmostEqual(r.candidates[1].distance, 1 - 0.8, places=5)      # cosine distance = 1 - cos
        self.assertAlmostEqual(r.candidates[2].distance, 1.0, places=5)
        self.assertEqual(r.candidates[0].source_url, url())

    def test_health_check_requires_a_nonempty_card_collection(self):
        self.assertEqual(self.backend().health_check(), 3)
        from chromadb.config import Settings
        client = chromadb.PersistentClient(path=str(self.dir), settings=Settings(anonymized_telemetry=False))
        client.create_collection("empty_cards", metadata={"hnsw:space": "cosine"})
        with self.assertRaises(rt.CardStoreUnavailable):
            self.backend("empty_cards").health_check()
        mismatched = client.create_collection("mismatched_cards", metadata={"hnsw:space": "cosine", "unit_count": 2})
        mismatched.add(ids=["M2C-01"], embeddings=[[1.0, 0.0, 0.0]], documents=["d"], metadatas=[meta(1)])
        with self.assertRaises(rt.CardStoreUnavailable):
            self.backend("mismatched_cards").health_check()

    def test_top_k_larger_than_collection_is_clamped(self):
        self.assertEqual(len(rt.route("q", self.backend(), top_k=50).candidates), 3)

    def test_non_cosine_collection_is_refused(self):
        with self.assertRaises(rt.RouterConfigError):
            rt.route("q", self.backend("l2_cards"))

    def test_missing_collection_raises_store_unavailable(self):
        with self.assertRaises(rt.CardStoreUnavailable):
            rt.route("q", self.backend("nope"))

    def test_router_does_not_modify_collection_contents(self):
        b = self.backend()
        from chromadb.config import Settings
        client = chromadb.PersistentClient(path=str(self.dir), settings=Settings(anonymized_telemetry=False))
        before = client.get_collection("test_cards").get(include=["metadatas", "documents", "embeddings"])
        rt.route("q", b, top_k=3)
        after = client.get_collection("test_cards").get(include=["metadatas", "documents", "embeddings"])
        self.assertEqual(before["ids"], after["ids"])
        self.assertEqual(before["metadatas"], after["metadatas"])
        self.assertEqual(before["documents"], after["documents"])
        self.assertEqual([list(map(float, e)) for e in before["embeddings"]], [list(map(float, e)) for e in after["embeddings"]])


# ------------------------------------------------------------------------------------------------------ page join

class PageJoinTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.td = tempfile.TemporaryDirectory()
        self.pages = Path(self.td.name) / "pages"
        self.addCleanup(self.td.cleanup)

    def card(self, n=17, **over):
        return rt.normalize_candidate(1, None, meta(n, **over), 0.3)

    def test_url_parsing(self):
        self.assertEqual(pj.parse_source_url(url()), (G1, P17))
        self.assertEqual(pj.parse_source_url(url(suffix="?version=2025.001")), (G1, P17))
        self.assertEqual(pj.parse_source_url(url(guide=G1.upper())), (G1, P17))
        for bad in (None, "", "   ", 5, "https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/40374631/" + P17 + ".html",
                    "https://example.com/docs/x/" + G1 + "/" + P17 + ".html", "https://help.sap.com/docs/x/" + G1 + ".html"):
            self.assertIsNone(pj.parse_source_url(bad), repr(bad))

    def test_all_29_real_card_urls_parse(self):
        units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))["units"]
        self.assertEqual(len(units), 29)
        for u in units:
            self.assertIsNotNone(pj.parse_source_url(u["source_url"]), u["source_id"])

    def test_resolved_page_when_valid_local_record_exists(self):
        write_page(self.pages, G1, P17)
        idx = pj.PageContentIndex.from_directory(self.pages)
        r = pj.resolve_card_page(self.card(17), idx)
        self.assertEqual(r.state, pj.RESOLVED_PAGE)
        self.assertTrue(r.card_exists and r.url_exists and r.local_page_content)
        self.assertIsNone(r.reason)
        self.assertEqual((r.guide_id, r.page_id, r.doc_id), (G1, P17, f"{G1}/{P17}"))
        self.assertGreater(r.content_chars, 0)
        self.assertEqual(r.source_url, url())

    def test_url_only_is_not_local_content(self):
        idx = pj.PageContentIndex.from_directory(self.pages)            # directory does not exist -> empty index
        self.assertEqual(len(idx), 0)
        r = pj.resolve_card_page(self.card(2, source_url=url(G2, P2)), idx)
        self.assertEqual(r.state, pj.URL_ONLY)
        self.assertTrue(r.card_exists and r.url_exists)
        self.assertFalse(r.local_page_content)
        self.assertEqual(r.reason, pj.REASON_NO_LOCAL_PAGE)
        self.assertIsNone(r.content_path)
        self.assertEqual(r.source_url, url(G2, P2))

    def test_missing_content_is_never_resolved(self):
        """Wrong guide, failed record, empty text: none of these may count as local page content."""
        write_page(self.pages, G2, P17)                                 # same page id, different guide
        write_page(self.pages, G1, P2, status="FAILED")
        write_page(self.pages, G1, "b" * 32, text="   ")
        idx = pj.PageContentIndex.from_directory(self.pages)
        r1 = pj.resolve_card_page(self.card(17), idx)                   # card -> (G1, P17); only (G2, P17) exists
        self.assertEqual((r1.state, r1.local_page_content), (pj.URL_ONLY, False))
        r2 = pj.resolve_card_page(self.card(2, source_url=url(G1, P2)), idx)
        self.assertEqual((r2.state, r2.local_page_content, r2.reason), (pj.URL_ONLY, False, pj.REASON_PAGE_NOT_USABLE))
        self.assertTrue(r2.warnings)
        r3 = pj.resolve_card_page(self.card(3, source_url=url(G1, "b" * 32)), idx)
        self.assertEqual((r3.state, r3.local_page_content, r3.reason), (pj.URL_ONLY, False, pj.REASON_PAGE_NOT_USABLE))

    def test_unresolved_states(self):
        idx = pj.PageContentIndex.empty()
        r = pj.resolve_card_page(None, idx)
        self.assertEqual((r.state, r.card_exists, r.url_exists, r.reason), (pj.UNRESOLVED, False, False, pj.REASON_CARD_MISSING))
        r = pj.resolve_card_page(self.card(4, source_url=""), idx)
        self.assertEqual((r.state, r.card_exists, r.url_exists, r.reason), (pj.UNRESOLVED, True, False, pj.REASON_NO_SOURCE_URL))
        # numeric-deliverable (legacy-style) URL: a guide id is never inferred from it
        numeric = "https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/40374631/" + P17 + ".html"
        r = pj.resolve_card_page(self.card(5, source_url=numeric), idx)
        self.assertEqual((r.state, r.url_exists, r.reason), (pj.UNRESOLVED, False, pj.REASON_URL_NOT_PARSEABLE))
        self.assertEqual(r.source_url, numeric)
        # a mapping carrying only the legacy 'url' key has no source_url
        r = pj.resolve_card_page({"source_id": "M2C-01", "url": url()}, idx)
        self.assertEqual((r.state, r.reason), (pj.UNRESOLVED, pj.REASON_NO_SOURCE_URL))

    def test_topic_mismatch_is_reported_as_warning_not_hidden(self):
        write_page(self.pages, G1, P17, topic_ids=(99,))
        r = pj.resolve_card_page(self.card(17), pj.PageContentIndex.from_directory(self.pages))
        self.assertEqual(r.state, pj.RESOLVED_PAGE)
        self.assertTrue(any("99" in w for w in r.warnings))

    def test_corrupt_or_misplaced_records_raise(self):
        write_page(self.pages, G1, P17)
        (self.pages / G1 / ("c" * 32 + ".json")).write_text("{not json", encoding="utf-8")
        with self.assertRaises(pj.PageIndexError):
            pj.PageContentIndex.from_directory(self.pages)
        (self.pages / G1 / ("c" * 32 + ".json")).unlink()
        (self.pages / G2).mkdir()
        (self.pages / G2 / f"{P17}.json").write_text(json.dumps({"guide_id": G1, "page_id": P17, "status": "OK", "text": "x"}), encoding="utf-8")
        with self.assertRaises(pj.PageIndexError):
            pj.PageContentIndex.from_directory(self.pages)

    def test_index_does_not_write(self):
        write_page(self.pages, G1, P17)
        before = sorted((p.name, sha(p)) for p in self.pages.rglob("*") if p.is_file())
        pj.resolve_card_page(self.card(17), pj.PageContentIndex.from_directory(self.pages))
        self.assertEqual(before, sorted((p.name, sha(p)) for p in self.pages.rglob("*") if p.is_file()))

    def test_real_repository_state_is_reported_as_it_is(self):
        """Derive expectations independently from the files on disk (no hard-coded 'N resolved')."""
        ok_pages = set()
        for p in (ROOT / "data" / "sap_help" / "pages").glob("*/*.json"):
            rec = json.loads(p.read_text(encoding="utf-8"))
            if rec.get("status") == "OK" and str(rec.get("text") or "").strip():
                ok_pages.add((rec["guide_id"].lower(), rec["page_id"].lower()))
        units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))["units"]
        idx = pj.PageContentIndex.from_directory()
        states = {}
        for u in units:
            res = pj.resolve_card_page(u, idx)
            states[u["source_id"]] = res
            expected_local = pj.parse_source_url(u["source_url"]) in ok_pages
            self.assertEqual(res.local_page_content, expected_local, u["source_id"])
            self.assertEqual(res.state == pj.RESOLVED_PAGE, expected_local, u["source_id"])
            self.assertIn(res.state, pj.STATES)
        self.assertEqual(states["M2C-17"].state, pj.RESOLVED_PAGE)        # the one topic with processed page text
        self.assertTrue(all(r.url_exists for r in states.values()))        # all 29 cards carry a parseable SAP Help URL
        # a URL-only card exists in the repo today and must not be reported as resolved
        self.assertTrue(any(r.state == pj.URL_ONLY and not r.local_page_content for r in states.values()) or len(ok_pages) >= 29)


# ------------------------------------------------------------------------------------------------------ orchestrator

def make_index(tmp: Path, *present):
    for g, p in present:
        write_page(tmp, g, p)
    return pj.PageContentIndex.from_directory(tmp)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.pages = Path(self.td.name) / "pages"

    def test_resolved_page(self):
        idx = make_index(self.pages, (G1, P17))
        b = FakeBackend([(meta(17), 0.35), (meta(2, source_url=url(G2, P2)), 0.6)])
        o = orch.route_to_page("what is a contract account", b, idx)
        self.assertEqual(o.state, orch.RESOLVED_PAGE)
        self.assertEqual(o.selected_card.source_id, "M2C-17")
        self.assertTrue(o.page_content_available)
        self.assertEqual(o.source_url, url())
        self.assertIsNone(o.fallback_reason)
        self.assertEqual(len(o.candidates), 2)
        self.assertEqual(o.resolution.content_path.endswith(f"{P17}.json"), True)

    def test_url_only(self):
        idx = make_index(self.pages)
        o = orch.route_to_page("q", FakeBackend([(meta(2, source_url=url(G2, P2)), 0.4)]), idx)
        self.assertEqual(o.state, orch.URL_ONLY)
        self.assertFalse(o.page_content_available)
        self.assertEqual(o.source_url, url(G2, P2))
        self.assertEqual(o.fallback_reason, pj.REASON_NO_LOCAL_PAGE)

    def test_unresolved_when_card_has_no_usable_url(self):
        idx = make_index(self.pages)
        o = orch.route_to_page("q", FakeBackend([(meta(4, source_url=""), 0.4)]), idx)
        self.assertEqual(o.state, orch.UNRESOLVED)
        self.assertIsNone(o.source_url)
        self.assertFalse(o.page_content_available)
        self.assertEqual(o.fallback_reason, pj.REASON_NO_SOURCE_URL)

    def test_no_card_candidate(self):
        idx = make_index(self.pages)
        o = orch.route_to_page("   ", FakeBackend([(meta(1), 0.1)]), idx)
        self.assertEqual((o.state, o.fallback_reason, o.selected_card, o.resolution), (orch.NO_CARD_CANDIDATE, orch.FALLBACK_EMPTY_QUERY, None, None))
        o = orch.route_to_page("q", FakeBackend([]), idx)
        self.assertEqual((o.state, o.fallback_reason), (orch.NO_CARD_CANDIDATE, orch.FALLBACK_NO_CANDIDATES))
        self.assertFalse(o.page_content_available)
        self.assertIsNone(o.source_url)

    def test_caller_side_selector_is_the_only_place_for_a_cutoff(self):
        idx = make_index(self.pages, (G1, P17))
        b = FakeBackend([(meta(17), 0.9)])
        default = orch.route_to_page("q", b, idx)
        self.assertEqual(default.state, orch.RESOLVED_PAGE)              # the router itself applied no cut-off (0.9 is kept)

        def strict(cands):
            return next((c for c in cands if c.distance <= 0.5), None)
        o = orch.route_to_page("q", b, idx, selector=strict)
        self.assertEqual((o.state, o.fallback_reason), (orch.NO_CARD_CANDIDATE, orch.FALLBACK_SELECTOR_REJECTED))
        self.assertEqual(len(o.candidates), 1)                           # candidates remain visible to the caller

        def second(cands):
            return cands[1] if len(cands) > 1 else None
        b2 = FakeBackend([(meta(17), 0.2), (meta(2, source_url=url(G2, P2)), 0.3)])
        o2 = orch.route_to_page("q", b2, idx, selector=second)
        self.assertEqual((o2.selected_card.source_id, o2.state), ("M2C-02", orch.URL_ONLY))

        def foreign(cands):
            return rt.normalize_candidate(1, None, meta(29), 0.0)
        with self.assertRaises(ValueError):
            orch.route_to_page("q", b, idx, selector=foreign)

    def test_states_are_the_documented_four(self):
        self.assertEqual(set(orch.OUTCOME_STATES), {"resolved_page", "url_only", "unresolved", "no_card_candidate"})

    def test_deterministic_with_mocked_data(self):
        idx = make_index(self.pages, (G1, P17))
        rows = [(meta(17), 0.35), (meta(2, source_url=url(G2, P2)), 0.6), (meta(3), 0.7)]
        a = orch.route_to_page("same query", FakeBackend(rows), idx, top_k=3)
        b = orch.route_to_page("same query", FakeBackend(rows), idx, top_k=3)
        self.assertEqual(a, b)
        self.assertEqual(json.dumps(a.to_dict(), sort_keys=True), json.dumps(b.to_dict(), sort_keys=True))

    def test_backend_failure_is_not_turned_into_no_card_candidate(self):
        class Down(FakeBackend):
            def query(self, q, n):
                raise rt.CardStoreUnavailable("store missing")
        with self.assertRaises(rt.CardStoreUnavailable):
            orch.route_to_page("q", Down([]), make_index(self.pages))

    def test_outcome_serialises(self):
        idx = make_index(self.pages, (G1, P17))
        d = orch.route_to_page("q", FakeBackend([(meta(17), 0.3)]), idx).to_dict()
        json.dumps(d)
        self.assertEqual(d["state"], "resolved_page")
        self.assertNotIn("url", d["selected_card"])


# ------------------------------------------------------------------------------------------------------ isolation

BANNED_IMPORT_ROOTS = {"ollama", "requests", "urllib3", "httpx", "aiohttp", "socket", "rag_core", "rag_chat", "retrieve",
                       "evaluate_retrieval", "create_embeddings", "sap_resolver", "openai", "anthropic"}
BANNED_DOTTED = {"urllib.request", "urllib.error", "http.client"}


def imported_names(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append(n.module or "")
            out += [f"{n.module}.{a.name}" for a in n.names]
    return out


class IsolationTests(unittest.TestCase):
    def test_no_llm_network_or_legacy_imports_anywhere_in_the_new_modules(self):
        for p in NEW_MODULES:
            for name in imported_names(p):
                self.assertNotIn(name.split(".")[0], BANNED_IMPORT_ROOTS, f"{p.name} imports {name}")
                self.assertNotIn(name, BANNED_DOTTED, f"{p.name} imports {name}")

    def test_third_party_packages_are_only_imported_lazily(self):
        """No module-level import of chromadb / sentence_transformers / numpy: importing the modules is dependency-free."""
        for p in NEW_MODULES:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in tree.body:                                   # module level only
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for n in names:
                    self.assertNotIn(n.split(".")[0], {"chromadb", "sentence_transformers", "numpy", "torch"}, f"{p.name}: {n}")

    def test_running_orchestration_loads_no_llm_model_store_or_legacy_module_and_uses_no_network(self):
        code = r"""
import json, socket, sys, tempfile
from pathlib import Path
def _blocked(*a, **k): raise AssertionError("network attempt")
socket.socket.connect = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
sys.path.insert(0, %r)
import m2c_orchestrator as o, m2c_page_join as pj
class B:
    distance_metric = "cosine"
    def query(self, q, n):
        m = {"source_id": "M2C-17", "title": "t", "category": "c", "source_url": "https://help.sap.com/docs/P/%s/%s.html",
             "source_status": "verified", "source_url_status": "ok", "has_source_correction": False, "citation": "x"}
        return {"ids": [["M2C-17"]], "metadatas": [[m]], "distances": [[0.4]]}
out = o.route_to_page("q", B(), pj.PageContentIndex.empty())
assert out.state == "url_only", out.state
bad = sorted(m for m in ("ollama", "rag_core", "rag_chat", "retrieve", "evaluate_retrieval", "create_embeddings", "chromadb",
                         "sentence_transformers", "torch", "numpy", "requests", "sap_resolver") if m in sys.modules)
print(json.dumps(bad))
""" % (str(SCRIPTS), G1, P17)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), [])

    def test_in_process_network_is_not_needed(self):
        real_connect = socket.socket.connect

        def blocked(*a, **k):
            raise AssertionError("network attempt")
        socket.socket.connect = blocked
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                idx = make_index(Path(td) / "p", (G1, P17))
                o = orch.route_to_page("q", FakeBackend([(meta(17), 0.3)]), idx)
            self.assertEqual(o.state, orch.RESOLVED_PAGE)
        finally:
            socket.socket.connect = real_connect

    def test_orchestrator_does_not_modify_legacy_retrieval(self):
        legacy = ["scripts/rag_core.py", "scripts/rag_chat.py", "scripts/retrieve.py", "scripts/evaluate_retrieval.py",
                  "scripts/create_embeddings.py", "scripts/chunk_pages.py", "scripts/clean_sap_pages.py", "scripts/audit_corpus.py",
                  "chunks.json", "cleaned_pages.json"]
        before = {p: sha(ROOT / p) for p in legacy}
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            orch.route_to_page("q", FakeBackend([(meta(17), 0.3)]), make_index(Path(td) / "p", (G1, P17)))
        self.assertEqual(before, {p: sha(ROOT / p) for p in legacy})
        # the legacy modules do not know the new modules (one-way dependency)
        for p in legacy:
            if p.endswith(".py"):
                text = (ROOT / p).read_text(encoding="utf-8")
                for new in ("m2c_router", "m2c_page_join", "m2c_orchestrator"):
                    self.assertNotIn(new, text, f"{p} references {new}")


class ProtectedArtifactTests(unittest.TestCase):
    """Every file recorded in data/phase7_checkpoint.md still has the recorded SHA-256 (nothing protected was modified)."""

    @staticmethod
    def recorded():
        text = CHECKPOINT.read_text(encoding="utf-8")
        block = text.split("<!-- sha256-begin -->", 1)[1].split("<!-- sha256-end -->", 1)[0]
        entries = {}
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("```"):
                continue
            digest, path = line.split(None, 1)
            entries[path.strip()] = digest
        return entries

    def test_checkpoint_hashes_still_match(self):
        entries = self.recorded()
        self.assertGreater(len(entries), 100)
        mismatched = [p for p, d in entries.items() if not (ROOT / p).is_file() or sha(ROOT / p) != d]
        self.assertEqual(mismatched, [])

    def test_checkpoint_covers_the_required_protected_set(self):
        entries = self.recorded()
        must = ["data/source_manifest.json", "data/source_corpus.json", "data/retrieval_units.json", "data/retrieval_token_stats.json",
                "data/card_collection_manifest.json", "data/retrieval_phase4_report.md", "data/retrieval_phase5_report.md",
                "scripts/rag_core.py", "scripts/rag_chat.py", "scripts/retrieve.py", "scripts/evaluate_retrieval.py",
                "scripts/create_embeddings.py", "scripts/chunk_pages.py", "scripts/clean_sap_pages.py", "scripts/audit_corpus.py",
                "scripts/build_card_collection.py", "scripts/evaluate_phase5.py", "tests/test_phase5.py"]
        for m in must:
            self.assertIn(m, entries, m)
        self.assertEqual(len([p for p in entries if p.endswith(".pdf")]), 29)
        self.assertTrue(any(p.startswith("data/chunk_candidates/") for p in entries))
        self.assertTrue(any(p.startswith("data/evaluation/") for p in entries))

    def test_no_card_store_was_created_by_these_tests(self):
        self.assertEqual((ROOT / "data" / "vector_store").exists(), VECTOR_STORE_EXISTED_AT_IMPORT)


if __name__ == "__main__":
    unittest.main()
