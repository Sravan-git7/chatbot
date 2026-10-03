"""Phase 19B — Ollama Generation Latency Engineering & Safety Regression Tests."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_core  # noqa: E402
import rag_evidence as EV  # noqa: E402
import rag_generate as RG  # noqa: E402
import rag_pipeline as RP  # noqa: E402
import rag_service as S  # noqa: E402
from rag_context import ContextBlock, ContextItem  # noqa: E402


def _make_sample_context() -> ContextBlock:
    item = ContextItem(
        marker="S1",
        chunk_id="chk-001",
        guide_id="g1",
        page_id="p1.html",
        title="Monitor AMI Capabilities",
        heading_path=["Monitor AMI Capabilities", "Selection Criteria"],
        section_title="Selection Criteria",
        chunk_index=0,
        rank=1,
        similarity=0.88,
        text="You can use transaction EL31 to monitor AMI capabilities and filter meter reading orders by status.",
        rendered_text="You can use transaction EL31 to monitor AMI capabilities and filter meter reading orders by status.",
        tokens=32,
        content_hash="abc123",
        source_url="https://help.sap.com/docs/g1/p1.html",
    )
    return ContextBlock(
        items=[item],
        total_tokens=32,
        budget_tokens=700,
    )


class Phase19BGenerationLatencyTests(unittest.TestCase):
    """Verify Phase 19B telemetry, experiment knobs, and safety invariants."""

    def test_01_default_ollama_client_preserves_rag_core_options_and_model(self) -> None:
        calls: List[Dict[str, Any]] = []

        def fake_chat(**kwargs: Any) -> Dict[str, Any]:
            calls.append(kwargs)
            return {"message": {"content": "You can use transaction EL31 to monitor AMI capabilities. [S1]"}}

        client = RG.OllamaClient(chat=fake_chat)
        out = client.generate("test prompt")
        self.assertIn("EL31", out)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "llama3.2:3b")
        self.assertEqual(calls[0]["model"], rag_core.LLM_MODEL_NAME)
        self.assertEqual(calls[0]["options"], {"temperature": 0, "seed": 42})
        self.assertEqual(calls[0]["options"], rag_core.LLM_OPTIONS)
        self.assertNotIn("keep_alive", calls[0])

    def test_02_ollama_client_num_predict_and_keep_alive_knobs_do_not_mutate_rag_core(self) -> None:
        calls: List[Dict[str, Any]] = []

        def fake_chat(**kwargs: Any) -> Dict[str, Any]:
            calls.append(kwargs)
            return {
                "message": {"content": "You can use transaction EL31. [S1]"},
                "prompt_eval_count": 640,
                "eval_count": 28,
                "total_duration": 540_000_000,
                "load_duration": 12_000_000,
                "prompt_eval_duration": 140_000_000,
                "eval_duration": 380_000_000,
            }

        client = RG.OllamaClient(chat=fake_chat, num_predict=192, keep_alive=-1)
        _ = client.generate("test prompt")
        self.assertEqual(calls[0]["options"], {"temperature": 0, "seed": 42, "num_predict": 192})
        self.assertEqual(calls[0]["keep_alive"], -1)
        # Ensure rag_core.LLM_OPTIONS was not mutated
        self.assertEqual(rag_core.LLM_OPTIONS, {"temperature": 0, "seed": 42})
        self.assertNotIn("num_predict", rag_core.LLM_OPTIONS)

    def test_03_telemetry_extraction_and_privacy_no_prompt_or_doc_leak(self) -> None:
        secret_doc_phrase = "CONFIDENTIAL_SAP_UTILITIES_SECRET_SPAN_998877"
        secret_question = "CONFIDENTIAL_USER_QUESTION_112233"

        def fake_chat(**kwargs: Any) -> Dict[str, Any]:
            return {
                "message": {"content": "You can use transaction EL31 to monitor AMI capabilities. [S1]"},
                "prompt_eval_count": 654,
                "eval_count": 29,
                "total_duration": 538_460_000,
                "load_duration": 6_200_000_000,
                "prompt_eval_duration": 142_010_000,
                "eval_duration": 396_430_000,
            }

        ctx = _make_sample_context()
        ctx.items[0].rendered_text += f" {secret_doc_phrase}"
        gen = RG.LLMGenerator(RG.OllamaClient(chat=fake_chat))
        res = gen.generate(secret_question, ctx)
        self.assertIsNotNone(res.telemetry)
        tel = res.telemetry or {}
        self.assertEqual(tel["prompt_eval_count"], 654)
        self.assertEqual(tel["eval_count"], 29)
        self.assertAlmostEqual(tel["total_duration_ms"], 538.46, places=2)
        self.assertAlmostEqual(tel["load_duration_ms"], 6200.0, places=1)
        self.assertAlmostEqual(tel["prompt_eval_duration_ms"], 142.01, places=2)
        self.assertAlmostEqual(tel["eval_duration_ms"], 396.43, places=2)
        self.assertTrue(tel["cold_load"])
        self.assertGreater(tel["tokens_per_sec"], 70.0)
        self.assertIn("prompt_build_ms", tel)
        self.assertIn("ollama_http_ms", tel)
        self.assertGreater(tel["context_chars"], 0)
        self.assertGreater(tel["prompt_chars"], 0)
        self.assertGreater(tel["output_chars"], 0)
        # Verify telemetry contains NO document text or question text
        serialized = json.dumps(tel)
        self.assertNotIn(secret_doc_phrase, serialized)
        self.assertNotIn(secret_question, serialized)
        self.assertNotIn("EL31", serialized)

    def test_04_evidence_guard_preserves_telemetry_when_postcheck_withholds(self) -> None:
        def fake_chat(**kwargs: Any) -> Dict[str, Any]:
            # Lacks a transaction code when the question asks for a transaction code
            return {
                "message": {"content": "You can monitor AMI capabilities and filter meter reading orders by status. [S1]"},
                "prompt_eval_count": 500,
                "eval_count": 20,
                "total_duration": 410_000_000,
                "load_duration": 5_000_000,
                "prompt_eval_duration": 120_000_000,
                "eval_duration": 285_000_000,
            }

        ctx = _make_sample_context()
        inner = RG.LLMGenerator(RG.OllamaClient(chat=fake_chat))
        guard = EV.EvidenceGuard(inner, tau=EV.TAU)
        res = guard.generate("Which transaction code can be used to monitor AMI capabilities?", ctx)
        self.assertTrue(res.refused)
        self.assertEqual(res.text, RG.NO_ANSWER_TEXT)
        self.assertEqual(guard.last.get("reason"), "ANSWER_LACKS_ASKED_DETAIL")
        self.assertIsNotNone(res.telemetry)
        self.assertEqual(res.telemetry["eval_count"], 20)
        self.assertFalse(res.telemetry["cold_load"])

    def test_05_evidence_retriever_accepts_query_embedding_kwarg(self) -> None:
        seen_kwargs: List[Dict[str, Any]] = []

        class StubRetriever:
            def retrieve_in_page(self, query: str, guide_id: str, page_id: str, top_k: int = 5, **kwargs: Any) -> List[Any]:
                seen_kwargs.append(kwargs)
                return []

            def page_chunks(self, guide_id: str, page_id: str) -> List[Any]:
                return []

        er = EV.EvidenceRetriever(StubRetriever())
        hits = er.retrieve_in_page("What is EL31?", "g1", "p1.html", top_k=5, query_embedding=[0.1, 0.2, 0.3])
        self.assertEqual(hits, [])
        self.assertEqual(seen_kwargs[0].get("query_embedding"), [0.1, 0.2, 0.3])

    def test_06_grounding_safety_gates_reject_phantom_spoofed_url_and_invented_codes(self) -> None:
        ctx = _make_sample_context()
        # 1. Phantom citation marker [S4] when only [S1] is in context
        r_phantom = RG.verify_grounding(
            "You can use transaction EL31 to monitor AMI capabilities. [S4]",
            ctx,
            in_page_grounding=True,
            citation_normalization=True,
        )
        self.assertFalse(r_phantom.ok)
        self.assertIn("S4", r_phantom.phantom_markers)

        # 2. Invented transaction code EL99 not in context
        r_code = RG.verify_grounding(
            "You can use transaction EL99 to monitor AMI capabilities. [S1]",
            ctx,
            in_page_grounding=True,
            citation_normalization=True,
        )
        self.assertFalse(r_code.ok)
        self.assertTrue(any(v["kind"] == "TOKEN_NOT_IN_CONTEXT" for v in r_code.violations))

        # 3. Altered URL not in context
        r_url = RG.verify_grounding(
            "You can use transaction EL31 at https://help.sap.com/docs/g1/spoofed.html to monitor AMI capabilities. [S1]",
            ctx,
            in_page_grounding=True,
            citation_normalization=True,
        )
        self.assertFalse(r_url.ok)
        self.assertTrue(any(v["kind"] == "URL_NOT_IN_CONTEXT" for v in r_url.violations))

    def test_07_production_pipeline_config_preserves_safe_generation_defaults(self) -> None:
        cfg = S.production_pipeline_config()
        self.assertEqual(cfg.context_budget_tokens, 700)
        self.assertEqual(cfg.max_context_chunks, 4)
        self.assertIsNone(cfg.ollama_num_predict)
        self.assertIsNone(cfg.ollama_keep_alive)
        self.assertTrue(cfg.phrase_reranker)
        self.assertEqual(cfg.phrase_min_corroboration, 2)
        self.assertFalse(cfg.full_page_coverage)
        self.assertFalse(cfg.citation_repair)
        self.assertFalse(cfg.evidence_frame_normalization)


if __name__ == "__main__":
    unittest.main()
