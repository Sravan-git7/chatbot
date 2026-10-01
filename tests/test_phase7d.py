"""Phase 7D - citation flow (spec section 5). Local files only; no network, no LLM, no store needed."""
import ast
import copy
import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pid = importlib.import_module("m2c_page_identity")
cit = importlib.import_module("m2c_citations")

G17 = "e52c8ee6197147ec97dfc2eb8c46a3ad"
P17 = "0bfcc5536a51204be10000000a174cb4"
URL17_LOIO = f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G17}/{P17}.html"
URL17_NUM = f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/40374631/{P17}.html"
PINNED = {
    "data/source_manifest.json": "08ad208c0187e935377c828faef36ec9fe077704cd580bb38004356f51b740b1",
    "data/card_collection_manifest.json": "5b3a5c30bc637c8b61573983a16cf252f7899d2c279eae3895e06476482d2731",
}

_CTX = None
_CARDS = None


def ctx():
    global _CTX
    if _CTX is None:
        _CTX = pid.IdentityContext.from_root(ROOT)
    return _CTX


def cards():
    global _CARDS
    if _CARDS is None:
        _CARDS = {c.source_id if hasattr(c, "source_id") else c["source_id"]: c for c in pid.load_cards(ROOT)}
    return _CARDS


def card(n):
    return cards()[f"M2C-{n:02d}"]


def sha(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def chunk(url, title="Contract Accounts", text="x" * 10, **meta):
    return {"document": text, "metadata": {"title": title, "url": url, **meta}, "distance": 0.5}


class OriginAndLabelTests(unittest.TestCase):
    def test_every_card_has_title_url_origin(self):
        for n in range(1, 30):
            cs = cit.cite_card(card(n), ctx())
            self.assertEqual(len(cs.sources), 1)
            e = cs.sources[0]
            self.assertEqual(e["origin"], "card_route")
            self.assertIn(e["origin"], cit.ORIGINS)
            self.assertIn("title", e)
            self.assertTrue(e["title"])
            self.assertTrue(e["url"] or e["url_flag"], e["source_id"])
            for k in ("citation", "source_id", "source_status", "review_flag", "review_reasons"):
                self.assertIn(k, e)

    def test_chunk_origin_is_page_chunk(self):
        cs = cit.cite_card(card(17), ctx(), [chunk(URL17_NUM)])
        self.assertEqual([s["origin"] for s in cs.sources], ["card_route", "page_chunk"])
        self.assertEqual(cs.sources[1]["title"], "Contract Accounts")
        self.assertEqual(cs.sources[1]["url"], URL17_NUM)

    def test_label_is_sources_provided_to_the_model(self):
        self.assertTrue(cit.cite_card(card(17), ctx()).label.startswith("Sources provided to the model"))
        self.assertTrue(cit.cite_card(card(17), ctx(), [chunk(URL17_NUM)]).label.startswith("Sources provided to the model"))
        txt = cit.format_sources(cit.cite_card(card(17), ctx(), [chunk(URL17_NUM)]))
        self.assertIn("Sources provided to the model", txt)
        self.assertIn("not verified as used", txt)

    def test_card_route_never_presented_as_used_text(self):
        for n in range(1, 30):
            e = cit.cite_card(card(n), ctx()).sources[0]
            self.assertIs(e["used_as_answer_text"], False)
            self.assertIs(e["verified_used"], False)
            self.assertIs(e["provided_as_context"], False)
        txt = cit.format_sources(cit.cite_card(card(17), ctx()))
        self.assertNotIn("used as answer", txt.lower().replace("not verified as used", ""))

    def test_page_chunk_usage_is_unknown_not_claimed(self):
        e = cit.cite_card(card(17), ctx(), [chunk(URL17_NUM)]).sources[1]
        self.assertIsNone(e["used_as_answer_text"])
        self.assertIs(e["verified_used"], False)
        self.assertIs(e["provided_as_context"], True)
        self.assertNotIn("document", e)  # the chunk text is not copied


class UrlTests(unittest.TestCase):
    def test_card_urls_byte_identical_to_manifest(self):
        for n in range(1, 30):
            c = card(n)
            want = c.source_url if hasattr(c, "source_url") else c["source_url"]
            self.assertEqual(cit.cite_card(c, ctx()).sources[0]["url"], want)

    def test_both_urls_shown_unrewritten_and_joined_by_page_id(self):
        cs = cit.cite_card(card(17), ctx(), [chunk(URL17_NUM)])
        card_e, chunk_e = cs.sources
        self.assertEqual(card_e["url"], URL17_LOIO)
        self.assertEqual(chunk_e["url"], URL17_NUM)
        self.assertNotEqual(card_e["url"], chunk_e["url"])
        self.assertEqual(chunk_e["card_url"], URL17_LOIO)
        j = chunk_e["join"]
        self.assertTrue(j["joined_to_card"])
        self.assertEqual(j["by"], "page_id")
        self.assertEqual(j["chunk_page_id"], P17)
        self.assertEqual(j["guide_relation"], cit.JOIN_ESTABLISHED_RECORDED_PAIR)
        txt = cit.format_sources(cs)
        self.assertIn(URL17_LOIO, txt)
        self.assertIn(URL17_NUM, txt)

    def test_loio_chunk_joins_by_guide_id(self):
        e = cit.cite_card(card(17), ctx(), [chunk(URL17_LOIO)]).sources[1]
        self.assertTrue(e["join"]["joined_to_card"])
        self.assertEqual(e["join"]["guide_relation"], cit.JOIN_ESTABLISHED_GUIDE_ID)
        self.assertEqual(e["url"], URL17_LOIO)

    def test_equal_page_id_without_guide_relation_does_not_join(self):
        url = f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/99999999/{P17}.html"
        e = cit.cite_card(card(17), ctx(), [chunk(url)]).sources[1]
        self.assertFalse(e["join"]["joined_to_card"])
        self.assertEqual(e["join"]["reason"], "PAGE_ID_EQUAL_GUIDE_NOT_ESTABLISHED")
        self.assertEqual(e["url"], url)

    def test_ambiguous_numeric_deliverable_is_not_paired(self):
        self.assertNotIn("40374657", cit.recorded_numeric_pairs(ctx()))
        url = f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/40374657/{P17}.html"
        e = cit.cite_card(card(17), ctx(), [chunk(url)]).sources[1]
        self.assertFalse(e["join"]["joined_to_card"])

    def test_different_page_id_does_not_join(self):
        url = f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G17}/" + "a" * 32 + ".html"
        e = cit.cite_card(card(17), ctx(), [chunk(url)]).sources[1]
        self.assertFalse(e["join"]["joined_to_card"])
        self.assertEqual(e["join"]["reason"], "PAGE_ID_DIFFERS")

    def test_missing_url_is_flagged_not_invented(self):
        e = cit.cite_card(card(17), ctx(), [chunk("")]).sources[1]
        self.assertIsNone(e["url"])
        self.assertEqual(e["url_flag"], cit.URL_FLAG_NO_URL)
        self.assertFalse(e["join"]["joined_to_card"])

    def test_unparseable_url_kept_verbatim_and_flagged(self):
        e = cit.cite_card(card(17), ctx(), [chunk("https://example.com/x")]).sources[1]
        self.assertEqual(e["url"], "https://example.com/x")
        self.assertEqual(e["url_flag"], cit.URL_FLAG_NOT_PARSEABLE)

    def test_recorded_pairs_exclude_ambiguous_keep_unique(self):
        pairs = cit.recorded_numeric_pairs(ctx())
        self.assertEqual(pairs.get("40374631"), G17)


class ReviewFlagTests(unittest.TestCase):
    def test_needs_review_cards_carry_flag_and_reason(self):
        for n in (14, 18, 23):
            e = cit.cite_card(card(n), ctx()).sources[0]
            self.assertTrue(e["review_flag"], n)
            self.assertTrue(e["review_reasons"], n)
            self.assertTrue(e["url"], n)  # shown, not dropped
            self.assertIn("[REVIEW]", cit.format_sources(cit.cite_card(card(n), ctx())))

    def test_only_review_cards_are_flagged(self):
        flagged = [n for n in range(1, 30) if cit.cite_card(card(n), ctx()).sources[0]["review_flag"]]
        self.assertEqual(flagged, [14, 18, 23])

    def test_review_card_urls_not_corrected(self):
        for n in (14, 18, 23):
            c = card(n)
            want = c.source_url if hasattr(c, "source_url") else c["source_url"]
            self.assertEqual(cit.cite_card(c, ctx()).sources[0]["url"], want)
        self.assertIn("?version=2025.001", cit.cite_card(card(18), ctx()).sources[0]["url"])
        self.assertIn("sap_s4hana_on-premise", cit.cite_card(card(14), ctx()).sources[0]["url"])

    def test_18_conflict_preserved_with_no_effective_guide(self):
        e = cit.cite_card(card(18), ctx()).sources[0]
        i = e["identity"]
        self.assertEqual(i["status"], pid.CONFLICTING_IDENTITY)
        self.assertIsNone(i["effective_guide_id"])
        self.assertTrue(i["conflict"])
        self.assertTrue(i["probe_evidence"])
        self.assertIn("e4375c1cad104b2eb7d027369bd76638", json.dumps(i["conflict"]))

    def test_18_chunk_is_not_joined(self):
        cs = cit.cite_card(card(18), ctx(), [chunk(URL17_LOIO)])
        self.assertFalse(cs.sources[1]["join"]["joined_to_card"])
        self.assertTrue(cs.sources[1]["join"]["reason"].startswith("CARD_HAS_NO_EFFECTIVE_IDENTITY"))

    def test_05_correction_preserved_not_applied_to_url(self):
        e = cit.cite_card(card(5), ctx()).sources[0]
        self.assertEqual(e["identity"]["status"], pid.CORRECTED_IDENTITY)
        self.assertTrue(e["identity"]["correction"])
        c = card(5)
        self.assertEqual(e["url"], c.source_url if hasattr(c, "source_url") else c["source_url"])
        self.assertNotEqual(e["identity"]["effective_guide_id"], e["identity"]["card_guide_id"])

    def test_identity_only_cards_stay_identity_only(self):
        for n in (1, 13, 16):
            i = cit.cite_card(card(n), ctx()).sources[0]["identity"]
            self.assertEqual(i["status"], pid.CARD_IDENTITY_ONLY)
            self.assertFalse(i["local_page_available"])

    def test_identified_not_local_is_not_resolved(self):
        counts = {}
        for n in range(1, 30):
            s = cit.cite_card(card(n), ctx()).sources[0]["identity"]["status"]
            counts[s] = counts.get(s, 0) + 1
        self.assertEqual(counts, {"card_identity_only": 3, "conflicting_identity": 1, "corrected_identity": 1,
                                  "identified_not_local": 23, "resolved_local_page": 1})

    def test_local_content_provenance_not_relabelled(self):
        lc = cit.cite_card(card(17), ctx()).sources[0]["identity"]["local_content"]
        self.assertTrue(lc["is_legacy_local_copy"])
        self.assertEqual(lc["record_source_type"], "legacy_local_copy")
        self.assertIs(lc["fresh_network_fetch_claimed"], False)


class OutcomeTests(unittest.TestCase):
    class _O:
        def __init__(self, sel):
            self.selected_card = sel
            self.query = "q"
            self.fallback_reason = "NO_CARD_SELECTED" if sel is None else None

    def test_no_card_yields_no_sources(self):
        cs = cit.cite_outcome(self._O(None), ctx())
        self.assertEqual(cs.sources, ())
        self.assertEqual(cs.route_state, pid.NO_CARD_CANDIDATE)
        self.assertIn("(none)", cit.format_sources(cs))
        self.assertTrue(cs.notes)

    def test_selected_card_yields_card_route(self):
        cs = cit.cite_outcome(self._O(card(17)), ctx())
        self.assertEqual(cs.sources[0]["source_id"], "M2C-17")
        self.assertEqual(cs.route_state, pid.RESOLVED_LOCAL_PAGE)

    def test_to_dict_roundtrips_json(self):
        json.dumps(cit.cite_card(card(17), ctx(), [chunk(URL17_NUM)]).to_dict())


class AuditTests(unittest.TestCase):
    def test_audit_covers_29_and_is_deterministic(self):
        a = cit.render_json(cit.build_audit(ctx()))
        b = cit.render_json(cit.build_audit(pid.IdentityContext.from_root(ROOT)))
        self.assertEqual(a, b)
        d = json.loads(a)
        self.assertEqual(d["card_count"], 29)
        self.assertEqual(d["review_flag_cards"], ["M2C-14", "M2C-18", "M2C-23"])
        self.assertEqual(d["cards_with_local_content"], ["M2C-17"])
        for r in d["cards"]:
            self.assertTrue(r["url"] or r["url_flag"])
            self.assertIs(r["used_as_answer_text"], False)

    def test_committed_audit_matches_generator(self):
        p = ROOT / "data" / "m2c_citation_audit.json"
        self.assertTrue(p.exists())
        self.assertEqual(p.read_text(encoding="utf-8"), cit.render_json(cit.build_audit(ctx())))

    def test_cli_writes_identical_file(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "a.json"
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "m2c_citations.py"), "--out", str(out)],
                               capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(out.read_bytes(), (ROOT / "data" / "m2c_citation_audit.json").read_bytes())

    def test_inputs_not_mutated(self):
        before = copy.deepcopy(cit.build_audit(ctx()))
        cit.cite_card(card(18), ctx(), [chunk(URL17_LOIO)])
        self.assertEqual(before, cit.build_audit(ctx()))
        for f, h in PINNED.items():
            self.assertEqual(sha(f), h, f)


class StaticTests(unittest.TestCase):
    def _imports(self):
        tree = ast.parse((ROOT / "scripts" / "m2c_citations.py").read_text(encoding="utf-8"))
        out = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                out |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                out.add(n.module)
        return out

    def test_no_network_imports(self):
        banned = {"urllib.request", "urllib.error", "http.client", "requests", "socket", "httpx", "aiohttp", "openai", "anthropic"}
        self.assertFalse(self._imports() & banned)

    def test_no_legacy_or_store_imports(self):
        banned = {"rag_core", "rag_chat", "retrieve", "chromadb", "sentence_transformers", "create_embeddings", "evaluate_retrieval"}
        self.assertFalse(self._imports() & banned)

    def test_rag_chat_untouched_by_7d(self):
        self.assertNotIn("m2c_citations", (ROOT / "scripts" / "rag_chat.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
