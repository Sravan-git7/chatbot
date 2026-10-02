#!/usr/bin/env python3
"""Phase 18 unit tests for E1 (phrase-aware reranker page-evidence deepening).

Pure-mechanism tests run without stores (fakes); a store-based regression test pins that with all
Phase 18 flags OFF the reranker reproduces the committed Phase 16 baseline routing exactly.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import phase13_reranker as PR13  # noqa: E402
from m2c_router import CardCandidate  # noqa: E402
import m2c_page_identity as pid  # noqa: E402


# ------------------------------------------------------------------------------------------------------------- fakes
class FakeIdentity:
    def __init__(self, status=pid.RESOLVED_LOCAL_PAGE, guide="g1", page="p1"):
        self.resolution_status = status
        self.effective_guide_id = guide
        self.effective_page_id = page
        self.card_title = "t"
        self.card_url = "https://help.sap.com/x"
        self.source_id = None
        self.card_guide_id = None
        self.card_needs_review = False


class FakeHit:
    def __init__(self, title, text, sim, rank=1):
        self.title, self.text, self.similarity, self.rank = title, text, sim, rank
        self.chunk_id = f"c{rank}"
        self.metadata = {}


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits

    def retrieve_in_page(self, query, guide_id, page_id, top_k=3, query_embedding=None):
        return list(self.hits[:top_k])

    def embed(self, texts):
        return [[0.0] * 8 for _ in texts]


class FakeCorpus:
    """entries: {sid: {"corpus_status": ...}}; texts: {sid: full page text}"""

    def __init__(self, entries, texts):
        self.entries = entries
        self._texts = texts

    def entry(self, sid):
        return self.entries.get(sid) or {}

    def page_text(self, sid):
        return self._texts.get(sid, "")


def make_candidate(sid, rank, distance):
    return CardCandidate(rank=rank, source_id=sid, title=sid, category="c", source_url="u",
                         source_status="verified", source_url_status="ok", has_source_correction=False,
                         citation="c", distance=distance, distance_metric="cosine")


def patch_identity(identity=FakeIdentity()):
    original = PR13.pid.resolve_identity

    def fake(card, ctx):
        return identity

    PR13.pid.resolve_identity = fake
    return original


# ------------------------------------------------------------------------------------------------------------- phrases
class TestDiscriminativePhrases(unittest.TestCase):
    def test_stopwords_kept_for_verbatim_matching(self):
        q = "In which step of the procedure do I save the installment plan?"
        phrases = PR13.discriminative_phrases(q)
        self.assertIn("save the installment", phrases)
        self.assertIn("the installment plan", phrases)
        self.assertIn("installment plan", phrases)
        # tokens < 3 chars never form part of a phrase ("in", "do", "i")
        self.assertFalse(any(p.startswith(("in ", "do ", "i ")) or p.endswith((" in", " do", " i")) for p in phrases))

    def test_cap_and_order(self):
        q = " ".join(f"word{i:02d}" for i in range(40))
        phrases = PR13.discriminative_phrases(q)
        self.assertLessEqual(len(phrases), PR13.PHRASE_MAX)
        self.assertEqual(phrases[0], "word00 word01 word02")  # 3grams first

    def test_short_query_has_no_phrases(self):
        self.assertEqual(PR13.discriminative_phrases("a b"), [])


class TestUniquePhrasePageMap(unittest.TestCase):
    def setUp(self):
        self.entries = {"A": {"corpus_status": "ingested"}, "B": {"corpus_status": "ingested"},
                        "C": {"corpus_status": "ingested"}, "D": {"corpus_status": "excluded_card_identity_only"}}
        self.texts = {
            "A": "The Prio column enables you to influence the clearing priority of the selected original items.",
            "B": "Clearing of incoming payments happens in steps. The clearing priority is not set here.",
            "C": "Installment plans. A list of selected items appears.",
            "D": "Unique phrase lives on this uningested page.",
        }
        self.corpus = FakeCorpus(self.entries, self.texts)

    def test_unique_phrase_maps_to_single_page(self):
        m = PR13.unique_phrase_page_map(["a list of selected items"], self.corpus)
        self.assertEqual(m, {"a list of selected items": "C"})

    def test_phrase_in_two_pages_is_dropped(self):
        m = PR13.unique_phrase_page_map(["the clearing priority"], self.corpus)
        self.assertEqual(m, {})

    def test_phrase_in_zero_pages_is_dropped(self):
        m = PR13.unique_phrase_page_map(["nonexistent phrase here"], self.corpus)
        self.assertEqual(m, {})

    def test_uningested_pages_never_count(self):
        m = PR13.unique_phrase_page_map(["unique phrase lives"], self.corpus)
        self.assertEqual(m, {})

    def test_no_page_text_support(self):
        class Bare:
            entries = self.entries
        self.assertEqual(PR13.unique_phrase_page_map(["x"], Bare()), {})


# ------------------------------------------------------------------------------------------------------------- scoring
class TestScoringMechanics(unittest.TestCase):
    def setUp(self):
        self.original_resolve = patch_identity()
        self.hits = [FakeHit("S1", "clearing of original items with priority settings", 0.80, 1),
                     FakeHit("S2", "unrelated billing text about master data", 0.55, 2),
                     FakeHit("S3", "another unrelated section", 0.40, 3)]
        self.retriever = FakeRetriever(self.hits)
        self.entries = {"SIB": {"corpus_status": "ingested"}, "GOLD": {"corpus_status": "ingested"}}
        self.texts = {
            "SIB": "Clearing control for incoming payments. Original items are selected and cleared. Priority is discussed generally.",
            "GOLD": "You can assign numerical key figures in the Prio column. This enables you to influence the clearing priority of the selected original items when payments are received.",
        }
        self.corpus = FakeCorpus(self.entries, self.texts)
        # SIB: dense rank 1 (card 0.70); GOLD: dense rank 2 (card 0.55). Off-flag gap 0.075; the 0.10
        # phrase channel (minus the 0.035 card-weight shift for both) flips the order only with the flag.
        self.cands = [make_candidate("SIB", 1, 0.30), make_candidate("GOLD", 2, 0.45)]
        self.cards = {"SIB": {}, "GOLD": {}}

    def tearDown(self):
        PR13.pid.resolve_identity = self.original_resolve

    def test_flag_off_matches_phase13_formula_exactly(self):
        # code_aware True but phrase_reranker False => no phrase channel, Phase 13 weights (0.50/0.40/0.10)
        _, scored = PR13.rerank_candidates(
            "Which indicator sets the clearing priority of original items?", self.cands, self.cards,
            self.retriever, object(), self.corpus, top_k_evaluate=2, code_aware=True, phrase_reranker=False)
        by = {s.candidate.source_id: s for s in scored}
        for s in scored:
            expected = 0.50 * s.card_similarity + 0.40 * s.page_similarity + 0.10 * s.coverage
            self.assertAlmostEqual(s.final_score, round(expected, 4), places=4)
            self.assertEqual(s.phrase_match, 0.0)
        # sibling (dense rank 1) must still win with the flag off
        self.assertEqual(by["SIB"].rerank, 1)

    def test_flag_on_unique_phrase_beats_sibling(self):
        # "the clearing priority" occurs in BOTH pages here (SIB mentions it) -> use a GOLD-unique phrase instead:
        # "influence the clearing priority" is unique to GOLD.
        q = "How do I influence the clearing priority of the selected original items?"
        _, scored_off = PR13.rerank_candidates(q, self.cands, self.cards, self.retriever, object(), self.corpus,
                                               top_k_evaluate=2, code_aware=True, phrase_reranker=False)
        self.assertEqual(scored_off[0].candidate.source_id, "SIB")
        _, scored_on = PR13.rerank_candidates(q, self.cands, self.cards, self.retriever, object(), self.corpus,
                                              top_k_evaluate=2, code_aware=True, phrase_reranker=True)
        by = {s.candidate.source_id: s for s in scored_on}
        self.assertEqual(by["GOLD"].phrase_match, 1.0)
        self.assertEqual(by["SIB"].phrase_match, 0.0)
        # GOLD wins once the unique phrase fires
        self.assertEqual(scored_on[0].candidate.source_id, "GOLD")
        # the gain is exactly the 0.10 tech channel (weights shift card 0.50 -> 0.40 for BOTH candidates)
        sib_off = next(s for s in scored_off if s.candidate.source_id == "SIB")
        sib_on = by["SIB"]
        expected_sib_on = 0.40 * sib_off.card_similarity + 0.40 * sib_off.page_similarity + 0.10 * sib_off.coverage
        self.assertAlmostEqual(sib_on.final_score, round(expected_sib_on, 4), places=4)

    def test_code_only_query_keeps_phase15_formula(self):
        # query with a code token unique to GOLD; flag on; phrase channel also available -> tech = max(code, phrase)
        self.texts["GOLD"] += " Use transaction ELDM to display meter reading data."
        q = "What does transaction ELDM display?"
        _, scored = PR13.rerank_candidates(q, self.cands, self.cards, self.retriever, object(), self.corpus,
                                           top_k_evaluate=2, code_aware=True, phrase_reranker=True)
        by = {s.candidate.source_id: s for s in scored}
        self.assertEqual(by["GOLD"].code_match, 1.0)
        expected = 0.40 * by["GOLD"].card_similarity + 0.40 * by["GOLD"].page_similarity + 0.10 * by["GOLD"].coverage + 0.10 * 1.0
        self.assertAlmostEqual(by["GOLD"].final_score, round(expected, 4), places=4)
        self.assertEqual(by["SIB"].code_match, 0.0)

    def test_full_page_coverage_changes_coverage_source(self):
        # The shared top-2 chunks carry only 2 of the 6 query terms (clear, priority); GOLD's FULL page
        # additionally carries "prio column" -> full-page coverage must differ from and exceed chunk coverage.
        q = "Which indicator is set in the Prio column for the clearing priority?"
        _, scored_chunks = PR13.rerank_candidates(q, self.cands, self.cards, self.retriever, object(), self.corpus,
                                                  top_k_evaluate=2, full_page_coverage=False)
        _, scored_page = PR13.rerank_candidates(q, self.cands, self.cards, self.retriever, object(), self.corpus,
                                                top_k_evaluate=2, full_page_coverage=True)
        gc_c = {s.candidate.source_id: s.coverage for s in scored_chunks}
        gc_p = {s.candidate.source_id: s.coverage for s in scored_page}
        self.assertNotEqual(gc_c["GOLD"], gc_p["GOLD"])
        self.assertGreater(gc_p["GOLD"], gc_c["GOLD"])  # full page carries the terms the top-2 chunks miss

    def test_to_dict_carries_phrase_match(self):
        _, scored = PR13.rerank_candidates("How do I influence the clearing priority of the selected original items?",
                                           self.cands, self.cards, self.retriever, object(), self.corpus,
                                           top_k_evaluate=2, code_aware=True, phrase_reranker=True)
        for s in scored:
            self.assertIn("phrase_match", s.to_dict())

    def test_deterministic(self):
        q = "How do I influence the clearing priority of the selected original items?"
        a = PR13.rerank_candidates(q, self.cands, self.cards, self.retriever, object(), self.corpus,
                                   top_k_evaluate=2, code_aware=True, phrase_reranker=True, full_page_coverage=True)
        b = PR13.rerank_candidates(q, self.cands, self.cards, self.retriever, object(), self.corpus,
                                   top_k_evaluate=2, code_aware=True, phrase_reranker=True, full_page_coverage=True)
        self.assertEqual([s.to_dict() for s in a[1]], [s.to_dict() for s in b[1]])

    def test_min_corroboration_filters_single_phrase_flips(self):
        # Single unique phrase owned by SIB ("when bill") vs multiple unique phrases owned by GOLD:
        # with min_corroboration=1 SIB also earns phrase_match=1.0; with min_corroboration=2 only GOLD
        # (which owns >=2 distinct unique phrases) earns the phrase channel.
        self.texts["SIB"] += " This occurs when bill processing runs."
        q = "When bill runs, how do I influence the clearing priority of the selected original items?"
        pmap1 = PR13.unique_phrase_page_map(PR13.discriminative_phrases(q), self.corpus, min_corroboration=1)
        pmap2 = PR13.unique_phrase_page_map(PR13.discriminative_phrases(q), self.corpus, min_corroboration=2)
        self.assertIn("SIB", set(pmap1.values()))
        self.assertNotIn("SIB", set(pmap2.values()))
        self.assertIn("GOLD", set(pmap2.values()))
        sel, scored = PR13.rerank_candidates(q, self.cands, self.cards, self.retriever, object(), self.corpus,
                                             top_k_evaluate=2, code_aware=True, phrase_reranker=True,
                                             phrase_min_corroboration=2)
        by = {s.candidate.source_id: s for s in scored}
        self.assertEqual(sel.source_id, "GOLD")
        self.assertEqual(by["GOLD"].phrase_match, 1.0)
        self.assertEqual(by["SIB"].phrase_match, 0.0)


# ----------------------------------------------------------------------------------------------------- store regression
P16 = ROOT / "data" / "phase16" / "phase16_comparison.json"

from tests.test_phase9 import NEED_STORES  # noqa: E402


@NEED_STORES
class TestFlagOffReproducesPhase16Routing(unittest.TestCase):
    """With every Phase 18 flag OFF, reranked routing must EXACTLY reproduce the committed Phase 16
    baseline selections (data/phase16/phase16_comparison.json, real mode)."""

    @classmethod
    def setUpClass(cls):
        import rag_pipeline as RP
        # The verified Phase 16 production baseline with every Phase 18 flag OFF. This pins the
        # reconciliation invariant: the Phase 18 code paths must be exact no-ops relative to Phase 16.
        cls.cfg = RP.PipelineConfig(
            top_k_cards=10,
            rerank_router=True,
            code_aware_router=True,
            in_page_grounding=True,
            citation_normalization=True,
            relaxed_context_gate=True,
            evidence_frame_normalization=False,
            phrase_reranker=False,
            full_page_coverage=False,
            citation_repair=False,
        )
        cls.pipe = RP.build_pipeline(generator="extractive", config=cls.cfg)
        payload = json.loads(P16.read_text(encoding="utf-8"))
        cls.per = payload["results"]["phase16_combined_ABC"]["per_query"]
        queries = json.loads((ROOT / "data" / "evaluation" / "phase12_queries.json").read_text(encoding="utf-8"))["queries"]
        cls.qmap = {q["id"]: q for q in queries}
        # the 7 answerable R@1 misses + the Phase 15 recoveries + the M2C-18 hub case + controls
        cls.ids = ["P12-007", "P12-015", "P12-027", "P12-034", "P12-041", "P12-045", "P12-047",
                   "P12-002", "P12-013", "P12-038", "P12-042", "P12-011", "P12-001", "P12-058"]

    def test_selections_pinned(self):
        for qid in self.ids:
            q = self.qmap[qid]
            got = self.pipe.answer(q["query"])["routing"]["selected_source_id"]
            want = self.per[qid]["real"]["selected"]
            self.assertEqual(got, want, f"{qid}: flag-off reranking diverged from the committed Phase 16 baseline")


if __name__ == "__main__":
    unittest.main()
