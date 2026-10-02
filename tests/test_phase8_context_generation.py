"""Phase 8F/8G/8H - context assembly, generators, grounding verifier, citations. Store-free."""
from __future__ import annotations

import ast
import json
import unittest
from types import SimpleNamespace

from tests.phase8_support import ROOT, SCRIPTS, regex_count

import m2c_citations as MC  # noqa: E402
import m2c_page_identity as pid  # noqa: E402
import page_citations as PCIT  # noqa: E402
import rag_context as RC  # noqa: E402
import rag_generate as RG  # noqa: E402
import rag_text as T  # noqa: E402

G, P = "g" * 32, "p" * 32


def hit(i, text, rank=None, path=("Page", "Use"), guide=G, page=P, ch=None, h=None, url="https://help.sap.com/docs/P/x/y.html"):
    import hashlib
    return SimpleNamespace(rank=rank or i + 1, chunk_id=f"{guide}/{page}/{i:03d}", guide_id=guide, page_id=page, source_url=url, title="Page",
                           heading_path=tuple(path), section_title=path[-1], chunk_index=i, chunk_count=9, content_hash=h or hashlib.sha256(text.encode()).hexdigest(),
                           text=text, distance=0.3, similarity=0.7)


class ContextTests(unittest.TestCase):
    def test_document_order_and_markers_provenance(self):
        ctx = RC.build_context([hit(5, "Fifth chunk text about alpha.", rank=1), hit(2, "Second chunk text about beta.", rank=2)], regex_count)
        self.assertEqual([i.chunk_index for i in ctx.items], [2, 5])
        self.assertEqual(ctx.markers, ["S1", "S2"])
        self.assertEqual(ctx.items[1].rank, 1)                      # retrieval rank kept in provenance
        r = ctx.render()
        self.assertTrue(r.startswith("[S1] Page > Use\nSecond chunk"))

    def test_dedup_by_hash_and_containment(self):
        a = hit(1, "Alpha beta gamma delta.", rank=1)
        dup = hit(2, "Alpha beta gamma delta.", rank=2, h=a.content_hash)
        contained = hit(3, "beta gamma", rank=3)
        ctx = RC.build_context([a, dup, contained], regex_count)
        self.assertEqual(len(ctx.items), 1)
        self.assertEqual({d["reason"] for d in ctx.dropped}, {"duplicate"})

    def test_budget_and_max_chunks(self):
        hs = [hit(i, ("word%d " % i) * 100, rank=i + 1) for i in range(6)]
        ctx = RC.build_context(hs, regex_count, budget_tokens=300, max_chunks=4)
        self.assertLessEqual(ctx.total_tokens, 300)
        self.assertTrue(any(d["reason"] == "budget" for d in ctx.dropped))
        ctx2 = RC.build_context(hs, regex_count, budget_tokens=10 ** 6, max_chunks=2)
        self.assertEqual(len(ctx2.items), 2)
        self.assertTrue(any(d["reason"] == "max_chunks" for d in ctx2.dropped))

    def test_top_chunk_kept_even_if_over_budget_and_flagged(self):
        ctx = RC.build_context([hit(0, "word " * 500, rank=1)], regex_count, budget_tokens=100)
        self.assertEqual(len(ctx.items), 1)
        self.assertTrue(ctx.over_budget)
        self.assertEqual(ctx.items[0].text, "word " * 500)          # nothing cut silently

    def test_overlap_prefix_removed_from_render_only(self):
        a = hit(1, "First sentence here. Second sentence here.")
        b = hit(2, "Second sentence here.\nThird sentence is new.")
        ctx = RC.build_context([a, b], regex_count)
        self.assertEqual(ctx.items[1].rendered_text, "Third sentence is new.")
        self.assertEqual(ctx.items[1].text, b.text)
        self.assertGreater(ctx.items[1].overlap_removed_chars, 0)

    def test_prompt_contains_no_url_or_card(self):
        ctx = RC.build_context([hit(0, "Alpha text about billing.")], regex_count)
        prompt = RG.build_prompt("What about billing?", ctx)
        self.assertNotIn("http", prompt.split("DOCUMENTATION EXCERPTS:")[1])
        self.assertNotIn("M2C-", prompt)
        self.assertIn("[S1]", prompt)
        self.assertIn(RG.NO_ANSWER_TEXT, prompt)

    def test_empty_hits(self):
        ctx = RC.build_context([], regex_count)
        self.assertEqual((ctx.items, ctx.total_tokens), ([], 0))


def ctx_of(*texts):
    return RC.build_context([hit(i, t) for i, t in enumerate(texts)], regex_count, max_chunks=9)


class GroundingTests(unittest.TestCase):
    ctx = ctx_of("You create an installment plan when open items exist. Use transaction FPR1 to start it.", "The limit is 30 days. Nothing else applies.")

    def test_faithful_answer_passes(self):
        r = RG.verify_grounding("You create an installment plan when open items exist. [S1]", self.ctx)
        self.assertTrue(r.ok)
        self.assertEqual(r.cited_markers, ["S1"])

    def test_phantom_marker_fails(self):
        r = RG.verify_grounding("You create an installment plan when open items exist. [S7]", self.ctx)
        self.assertFalse(r.ok)
        self.assertEqual(r.phantom_markers, ["S7"])
        self.assertEqual(r.cited_markers, [])

    def test_uncited_sentence_fails(self):
        r = RG.verify_grounding("You create an installment plan when open items exist.", self.ctx)
        self.assertIn("NO_CITATION", {v["kind"] for v in r.violations})

    def test_invented_url_fails_but_url_in_context_is_allowed(self):
        r = RG.verify_grounding("You create an installment plan when open items exist. [S1] See https://help.sap.com/docs/x/y.html.", self.ctx)
        self.assertIn("URL_NOT_IN_CONTEXT", {v["kind"] for v in r.violations})
        r2 = RG.verify_grounding("Visit help.sap.com/docs/a for items. [S1]", ctx_of("Visit help.sap.com/docs/a for items."))
        self.assertTrue(r2.ok, r2.violations)

    def test_invented_identifier_and_number_fail(self):
        for bad in ("Use transaction ZQ99 to start it. [S1]", "The limit is 4711 days. [S2]"):
            r = RG.verify_grounding(bad, self.ctx)
            self.assertFalse(r.ok, bad)
            self.assertIn("TOKEN_NOT_IN_CONTEXT", {v["kind"] for v in r.violations})

    def test_real_token_cited_to_wrong_chunk_fails(self):
        r = RG.verify_grounding("Use transaction FPR1 to start it. [S2]", self.ctx)
        self.assertIn("TOKEN_NOT_IN_CITED_CHUNK", {v["kind"] for v in r.violations})

    def test_off_context_claim_fails(self):
        r = RG.verify_grounding("The moon orbits the earth every month. [S1]", self.ctx)
        self.assertIn("LOW_SUPPORT", {v["kind"] for v in r.violations})

    def test_hex_identifier_not_in_context_fails(self):
        r = RG.verify_grounding("The guide is 0123456789abcdef0123456789abcdef. [S1]", self.ctx)
        self.assertIn("IDENTIFIER_NOT_IN_CONTEXT", {v["kind"] for v in r.violations})

    def test_refusal_is_accepted_and_has_no_citations(self):
        r = RG.verify_grounding(RG.NO_ANSWER_TEXT, self.ctx)
        self.assertTrue(r.ok and r.refusal)
        self.assertEqual(r.cited_markers, [])

    def test_empty_or_marker_only_answer_fails(self):
        self.assertTrue(RG.verify_grounding("", self.ctx).refusal)
        self.assertFalse(RG.verify_grounding("[S1]", self.ctx).ok)

    def test_one_bad_sentence_fails_the_whole_answer(self):
        r = RG.verify_grounding("You create an installment plan when open items exist. [S1]\nUse transaction ZQ99 now. [S1]", self.ctx)
        self.assertFalse(r.ok)
        self.assertEqual(r.cited_markers, [])


class GeneratorTests(unittest.TestCase):
    def test_extractive_is_deterministic_cited_and_grounded(self):
        ctx = ctx_of("You create an installment plan when open items exist.", "Weather is unrelated to anything here.")
        g = RG.ExtractiveGenerator()
        a, b = g.generate("When do I create an installment plan?", ctx), g.generate("When do I create an installment plan?", ctx)
        self.assertEqual(a.text, b.text)
        self.assertFalse(a.refused)
        self.assertTrue(RG.verify_grounding(a.text, ctx).ok)
        self.assertIn("[S1]", a.text)
        self.assertNotIn("Weather", a.text)

    def test_extractive_refuses_without_matching_sentence(self):
        r = RG.ExtractiveGenerator().generate("quantum entanglement spectroscopy", ctx_of("You create an installment plan when open items exist."))
        self.assertTrue(r.refused)
        self.assertEqual(r.text, RG.NO_ANSWER_TEXT)

    def test_llm_generator_uses_stub_and_detects_refusal(self):
        seen = []
        class Stub:
            def generate(self, prompt):
                seen.append(prompt)
                return "  " + RG.NO_ANSWER_TEXT + " "
        r = RG.LLMGenerator(Stub()).generate("q?", ctx_of("Some text about things."))
        self.assertTrue(r.refused)
        self.assertEqual(len(seen), 1)
        self.assertIn("[S1] Page > Use", seen[0])

    def test_ollama_client_uses_rag_core_model_and_options_with_injected_chat(self):
        import rag_core
        calls = []
        def chat(**kw):
            calls.append(kw)
            return {"message": {"content": "hi [S1]"}}
        c = RG.OllamaClient(chat=chat)
        self.assertEqual(c.generate("PROMPT"), "hi [S1]")
        self.assertEqual(calls[0]["model"], rag_core.LLM_MODEL_NAME)
        self.assertEqual(calls[0]["options"], rag_core.LLM_OPTIONS)
        self.assertEqual(calls[0]["messages"], [{"role": "user", "content": "PROMPT"}])

    def test_no_network_or_ollama_import_at_module_level(self):
        for name in ("rag_generate", "rag_context", "page_citations", "rag_text"):
            tree = ast.parse((SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
            for n in tree.body:
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    mods = [a.name for a in n.names] + ([n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
                    self.assertFalse({"ollama", "requests", "socket", "urllib.request"} & set(mods), (name, mods))

    def test_text_helpers(self):
        self.assertEqual(T.stem("plans"), "plan")
        self.assertEqual(T.code_tokens("transaction FPR1 and ISU_AMI_1 in 2025"), {"FPR1", "ISU_AMI_1", "2025"})
        self.assertEqual(T.coverage([], "x"), 0.0)
        self.assertEqual(T.split_cited_sentences("One. [S1] Two e.g. here. [S2]"), ["One. [S1]", "Two e.g. here. [S2]"])


class CitationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx_id = pid.IdentityContext.from_root(ROOT)
        cls.cards = {c["source_id"]: c for c in pid.load_cards(ROOT)}

    def _build(self, sid, texts, answer):
        card = self.cards[sid]
        ident = pid.resolve_identity(card, self.ctx_id)
        g, p = ident.effective_guide_id or G, ident.effective_page_id or P
        hits = [hit(i, t, guide=g, page=p, url=card["source_url"]) for i, t in enumerate(texts)]
        ctx = RC.build_context(hits, regex_count, max_chunks=9)
        rep = RG.verify_grounding(answer, ctx)
        return PCIT.build_citations(card, ident, self.ctx_id, ctx, rep), ctx, rep

    def test_only_cited_verified_chunks_are_answer_sources(self):
        cit, ctx, rep = self._build("M2C-24", ["You create an installment plan when open items exist.", "Unrelated second chunk about weather."], "You create an installment plan when open items exist. [S1]")
        self.assertTrue(rep.ok)
        self.assertEqual([s["marker"] for s in cit["answer_sources"]], ["S1"])
        self.assertTrue(all(s["verified_used"] and s["used_as_answer_text"] and s["provided_as_context"] for s in cit["answer_sources"]))
        self.assertEqual([n["marker"] for n in cit["context_not_cited"]], ["S2"])
        self.assertFalse(cit["context_not_cited"][0]["used_as_answer_text"])

    def test_topic_pointer_is_never_evidence(self):
        cit, _, _ = self._build("M2C-24", ["You create an installment plan when open items exist."], "You create an installment plan when open items exist. [S1]")
        p = cit["topic_pointer"]
        self.assertEqual(p["origin"], MC.ORIGIN_CARD_ROUTE)
        self.assertFalse(p["used_as_answer_text"])
        self.assertFalse(p["verified_used"])
        self.assertFalse(p["provided_as_context"])
        self.assertTrue(all(s["origin"] == MC.ORIGIN_PAGE_CHUNK for s in cit["answer_sources"]))

    def test_failed_verification_gives_no_answer_sources(self):
        cit, _, rep = self._build("M2C-24", ["You create an installment plan when open items exist."], "You create an installment plan when open items exist. [S9]")
        self.assertFalse(rep.ok)
        self.assertEqual(cit["answer_sources"], [])
        self.assertEqual(cit["label"], PCIT.LABEL_NONE)

    def test_refusal_gives_no_answer_sources(self):
        cit, _, rep = self._build("M2C-24", ["x text here."], RG.NO_ANSWER_TEXT)
        self.assertEqual(cit["answer_sources"], [])

    def test_url_is_card_url_unchanged(self):
        cit, _, _ = self._build("M2C-14", ["Invoicing creates the link to contract accounting and provides the basis for bill creation."],
                                "Invoicing creates the link to contract accounting and provides the basis for bill creation. [S1]")
        self.assertEqual(cit["topic_pointer"]["url"], self.cards["M2C-14"]["source_url"])
        for s in cit["answer_sources"]:
            self.assertEqual(s["url"], self.cards["M2C-14"]["source_url"])
        self.assertTrue(cit["topic_pointer"]["review_flag"])
        self.assertTrue(any("needs_review" in n for n in cit["notes"]))

    def test_m2c05_correction_note_and_join(self):
        cit, _, _ = self._build("M2C-05", ["This component manages technical data, installations, meter readings, and the inspection of devices."],
                                "This component manages technical data, installations, meter readings, and the inspection of devices. [S1]")
        self.assertTrue(any("corrected identity" in n for n in cit["notes"]))
        self.assertTrue(cit["answer_sources"][0]["join"]["joined_to_card"])
        self.assertEqual(cit["answer_sources"][0]["join"]["guide_relation"], MC.JOIN_ESTABLISHED_GUIDE_ID)

    def test_m2c18_conflict_is_shown_not_resolved(self):
        card = self.cards["M2C-18"]
        ident = pid.resolve_identity(card, self.ctx_id)
        cit = PCIT.build_citations(card, ident, self.ctx_id)
        self.assertEqual(cit["answer_sources"], [])
        self.assertTrue(any("conflicting identity" in n for n in cit["notes"]))
        self.assertEqual(cit["topic_pointer"]["identity"]["status"], pid.CONFLICTING_IDENTITY)

    def test_format_marks_pointer_as_not_evidence(self):
        cit, _, _ = self._build("M2C-24", ["You create an installment plan when open items exist."], "You create an installment plan when open items exist. [S1]")
        txt = PCIT.format_answer_sources(cit)
        self.assertIn("NOT answer evidence", txt)
        self.assertIn("[S1]", txt)


if __name__ == "__main__":
    unittest.main()
