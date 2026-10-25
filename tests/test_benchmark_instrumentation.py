#!/usr/bin/env python3
"""Regression tests for the benchmark instrumentation (per-stage timings in ``RagPipeline.answer``) and the
benchmark harness invariants (``benchmarks/run_benchmark.py``, ``benchmarks/workload_v1.json``).

The stage timers (``embed_ms``, ``card_query_ms``, ``rerank_ms``, ``verify_ms``) are measurement-only: they must
appear in ``timings_ms`` for the paths that actually execute them, must be non-negative, must stay inside their
parent window (``route_ms``), and must not change any routing/answer/abstention behavior. The behavior itself is
covered by the full existing suite; these tests lock the instrumentation contract the benchmark reports against.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "benchmarks"))

import rag_service as S  # noqa: E402


def _timings(res: dict) -> dict:
    return ((res.get("debug") or {}).get("timings_ms")) or {}


class StageInstrumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.svc = S.build_service("extractive")
        except FileNotFoundError as e:
            if "Page store is unavailable" in str(e) or "protected" in str(e).lower():
                raise unittest.SkipTest("production-only integration environment blocked: protected page store unavailable")
            raise

    def test_answered_query_reports_full_stage_breakdown(self):
        res = self.svc.ask("How does billing work in SAP Utilities?", conversation_id="instr-1", debug=True)
        self.assertEqual(res.get("status"), "answered")
        tm = _timings(res)
        for key in ("route_ms", "embed_ms", "card_query_ms", "rerank_ms", "retrieve_ms",
                    "context_ms", "generate_ms", "verify_ms", "total_ms"):
            self.assertIn(key, tm, f"missing stage timing {key}")
            self.assertGreaterEqual(tm[key], 0.0, f"negative stage timing {key}")
        # Sub-stage windows live inside the routing window (rounded to 2 decimals; allow 1 ms slack).
        self.assertLessEqual(tm["embed_ms"] + tm["card_query_ms"] + tm["rerank_ms"], tm["route_ms"] + 1.0)
        # And the whole pipeline stays inside the total (same slack per component).
        parts = tm["route_ms"] + tm["retrieve_ms"] + tm["context_ms"] + tm["generate_ms"]
        self.assertLessEqual(parts, tm["total_ms"] + 2.0)

    def test_out_of_scope_query_has_routing_stages_but_no_generation_stages(self):
        res = self.svc.ask("What is the weather in Berlin today?", conversation_id="instr-2", debug=True)
        self.assertEqual(res.get("status"), "out_of_scope")
        tm = _timings(res)
        self.assertIn("embed_ms", tm)          # the single query embedding still ran (routing happened)
        self.assertIn("card_query_ms", tm)
        self.assertIn("route_ms", tm)
        self.assertIn("total_ms", tm)
        self.assertNotIn("generate_ms", tm)    # nothing was generated ...
        self.assertNotIn("verify_ms", tm)      # ... so nothing was verified

    def test_m2c18_fail_closed_short_circuits_before_embedding(self):
        res = self.svc.ask("Tell me about the Contract Account Business Object page.", conversation_id="instr-3", debug=True)
        self.assertEqual(res.get("status"), "documentation_unavailable")
        tm = _timings(res)
        self.assertIn("total_ms", tm)
        # The focused unavailable-topic gate refuses before card routing: no embedding work is spent on it.
        self.assertNotIn("embed_ms", tm)
        self.assertNotIn("generate_ms", tm)
        self.assertNotIn("verify_ms", tm)

    def test_followup_turn_keeps_stage_breakdown_and_answer(self):
        res1 = self.svc.ask("How does billing work in SAP Utilities?", conversation_id="instr-4", debug=True)
        self.assertEqual(res1.get("status"), "answered")
        res2 = self.svc.ask("elaborate", conversation_id="instr-4", debug=True)
        self.assertEqual(res2.get("status"), "answered")
        self.assertEqual(res2["metadata"]["card_id"], res1["metadata"]["card_id"])
        tm = _timings(res2)
        for key in ("route_ms", "total_ms"):
            self.assertIn(key, tm)


class HarnessUnitTests(unittest.TestCase):
    def test_percentile_is_nearest_rank(self):
        import run_benchmark as B
        samples = [float(x) for x in range(1, 101)]           # 1..100
        self.assertEqual(B.pctl(sorted(samples), 50), 50.0)   # ceil(0.50*100)=50th -> 50
        self.assertEqual(B.pctl(sorted(samples), 95), 95.0)
        self.assertEqual(B.pctl(sorted(samples), 99), 99.0)
        self.assertEqual(B.pctl(sorted([7.0]), 99), 7.0)      # tiny sample stays honest
        self.assertIsNone(B.pctl([], 50))

    def test_summarize_reports_sample_count(self):
        import run_benchmark as B
        s = B.summarize([10.0, 20.0, 30.0])
        self.assertEqual(s["n"], 3)
        self.assertEqual(s["p50_ms"], 20.0)
        self.assertEqual(s["min_ms"], 10.0)
        self.assertEqual(s["max_ms"], 30.0)
        self.assertIsNotNone(s["stdev_ms"])

    def test_workload_v1_schema_and_category_coverage(self):
        import run_benchmark as B
        workload, sha = B.load_workload()
        self.assertEqual(len(sha), 64)
        self.assertEqual(workload["workload_version"], "v1")
        vocab = set(workload["status_vocabulary"])
        ids = set()
        categories = set()
        for item in workload["items"]:
            self.assertTrue(item["id"] not in ids, f"duplicate workload id {item['id']}")
            ids.add(item["id"])
            categories.add(item["category"])
            self.assertIn(item["expected_status"], vocab)
            self.assertGreaterEqual(len(item["turns"]), 1)
            mt = item.get("measured_turn", len(item["turns"]))
            self.assertGreaterEqual(mt, 1)
            self.assertLessEqual(mt, len(item["turns"]))
        # The mission-mandated workload dimensions must all be present.
        for required in ("simple_supported", "complex_supported", "followup", "out_of_scope",
                         "insufficient_evidence", "unresolved_identity", "doc_length_variation"):
            self.assertIn(required, categories)

    def test_quality_evaluator_rejects_plausible_answer_citing_wrong_source(self):
        import run_quality as Q
        gold = {"gold_doc_id": "gold-guide/gold-page", "evidence": ["Verified purpose"]}
        raw = {"status": "answered", "answer": "Verified purpose [S1]",
               "citations": {"answer_sources": [{"chunk_id": "c", "guide_id": "other", "page_id": "page"}]},
               "debug": {"context": {"items": [{"chunk_id": "c", "guide_id": "other", "page_id": "page",
                                                   "text": "Verified purpose"}]}}}
        self.assertFalse(Q.strict_evidence_correct(gold, raw))
        raw["citations"]["answer_sources"][0].update(guide_id="gold-guide", page_id="gold-page")
        # Citation metadata cannot lie about the source content.
        self.assertFalse(Q.strict_evidence_correct(gold, raw))
        raw["debug"]["context"]["items"][0].update(guide_id="gold-guide", page_id="gold-page")
        self.assertTrue(Q.strict_evidence_correct(gold, raw))
        raw["answer"] = "Some plausible but irrelevant sentence [S1]"
        self.assertFalse(Q.strict_evidence_correct(gold, raw))


if __name__ == "__main__":
    unittest.main()
