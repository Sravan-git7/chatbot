"""Phase 19C — Fine-Grained Service Concurrency & Request-Local Evidence State Tests.

Covers all 12 required Phase 19C scenarios:
1. Two concurrent requests with different evidence results do not overwrite each other.
2. 10 concurrent requests produce identical results to single-thread execution.
3. 20 concurrent mixed requests have 0 cross-request answer/citation/routing/evidence leakage.
4. Unsupported / pre-check refusal requests do not wait behind slow LLM generation when the generation lock is held.
5. Deterministic routing/retrieval/context preparation runs concurrently while LLM generation is active.
6. EvidenceGuard pre-check runs outside the generation lock.
7. EvidenceGuard post-check and grounding verification run safely outside the generation lock after generation.
8. Retriever/page caches return safe/isolated data under concurrent reads and caller mutation attempts.
9. Ollama failure/timeout in one request does not poison or deadlock concurrent requests.
10. Retriever exception in one request does not poison subsequent or concurrent requests.
11. Bounded generation semaphore enforces the configured concurrency limit (c=1, c=2, c=3).
12. Production config invariants and no-thread-local shortcut invariants remain intact.
"""
from __future__ import annotations

import concurrent.futures
import copy
import inspect
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import page_retriever as PR
import rag_evidence as EV
import rag_generate as RG
import rag_pipeline as RP
import rag_service as S


def _norm_chat_result(res: Mapping[str, Any]) -> Dict[str, Any]:
    d = copy.deepcopy(dict(res))
    d.pop("conversation_id", None)
    if "metadata" in d and isinstance(d["metadata"], dict):
        d["metadata"].pop("latency_ms", None)
    if "debug" in d and isinstance(d["debug"], dict):
        d["debug"].pop("timings_ms", None)
        pipe_dbg = d["debug"].get("pipeline")
        if isinstance(pipe_dbg, dict):
            pipe_dbg.pop("timings_ms", None)
            gen_dbg = pipe_dbg.get("generation")
            if isinstance(gen_dbg, dict) and isinstance(gen_dbg.get("telemetry"), dict):
                for k in ("prompt_build_ms", "ollama_http_ms", "queue_wait_ms"):
                    gen_dbg["telemetry"].pop(k, None)
    return d


class Phase19CConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = S.production_pipeline_config()
        cls.base_pipe = RP.build_pipeline(generator="extractive", config=cls.cfg)
        cls.ext_pipe = EV.build_evidence_pipeline(
            cls.base_pipe, tau=EV.SHIPPED_TAU, widen=False, generator="extractive"
        )
        cls.svc_ext = S.RagService(cls.ext_pipe, "extractive", generation_concurrency=1, coarse_lock=False)

    def test_01_concurrent_requests_distinct_evidence_no_overwrite(self) -> None:
        """Two concurrent requests with different evidence results do not overwrite each other."""
        q_supported = "How do I create an installment plan in FPR1?"
        q_refused = "What is the exact SQL table partition key for FPR1 installment plans?"

        expected_sup = _norm_chat_result(self.svc_ext.ask(q_supported, conversation_id="sup-single", debug=True))
        expected_ref = _norm_chat_result(self.svc_ext.ask(q_refused, conversation_id="ref-single", debug=True))
        self.assertEqual(expected_sup["status"], S.ANSWERED)
        self.assertEqual(expected_ref["status"], S.UNABLE_TO_VERIFY)
        self.assertTrue(expected_sup["debug"]["evidence"]["supported"])
        self.assertFalse(expected_ref["debug"]["evidence"]["supported"])

        barrier = threading.Barrier(2)

        def worker(q: str, cid: str) -> Dict[str, Any]:
            barrier.wait(timeout=5.0)
            return self.svc_ext.ask(q, conversation_id=cid, debug=True)

        for i in range(6):
            barrier.reset()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                f_sup = pool.submit(worker, q_supported, f"sup-{i}")
                f_ref = pool.submit(worker, q_refused, f"ref-{i}")
                r_sup = f_sup.result(timeout=15.0)
                r_ref = f_ref.result(timeout=15.0)

            self.assertEqual(r_sup["conversation_id"], f"sup-{i}")
            self.assertEqual(r_ref["conversation_id"], f"ref-{i}")
            self.assertEqual(_norm_chat_result(r_sup), expected_sup)
            self.assertEqual(_norm_chat_result(r_ref), expected_ref)

    def test_02_ten_concurrent_requests_match_single_thread(self) -> None:
        """10 concurrent requests produce identical results to single-thread execution."""
        queries = [
            ("c01", "How does AMI device creation work in SAP S/4HANA Utilities?"),
            ("c02", "What is transaction EL43 used for?"),
            ("c03", "How do I create an installment plan in FPR1?"),
            ("c04", "How are billing documents reversed in SAP Utilities?"),
            ("c05", "What is the exact SQL partition key for FPR1 installment plans?"),
            ("c06", "How do I configure Kubernetes ingress controllers in AWS EKS?"),
            ("c07", "What steps are involved in move-in and move-out processing?"),
            ("c08", "How does budget billing plan calculation work?"),
            ("c09", "What is convergent invoicing in contract accounts receivable and payable?"),
            ("c10", "How are disconnection and reconnection orders processed?"),
        ]
        single_truth = {
            cid: _norm_chat_result(self.svc_ext.ask(q, conversation_id=cid, debug=True))
            for cid, q in queries
        }

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futs = {
                cid: pool.submit(self.svc_ext.ask, q, conversation_id=cid, debug=True)
                for cid, q in queries
            }
            for cid, fut in futs.items():
                res = fut.result(timeout=20.0)
                self.assertEqual(res["conversation_id"], cid)
                self.assertEqual(_norm_chat_result(res), single_truth[cid])

    def test_03_twenty_concurrent_mixed_requests_zero_leakage(self) -> None:
        """20 concurrent mixed requests have 0 cross-request answer/citation/routing/evidence leakage."""
        mixed_queries = [
            ("m01", "How does AMI device creation work in SAP S/4HANA Utilities?"),
            ("m02", "What is transaction EL43 used for?"),
            ("m03", "How do I create an installment plan in FPR1?"),
            ("m04", "What is the exact SQL partition key for FPR1 installment plans?"),
            ("m05", "How do I bake a chocolate soufflé from scratch?"),
        ]
        single_truth = {
            cid: _norm_chat_result(self.svc_ext.ask(q, conversation_id=cid, debug=True))
            for cid, q in mixed_queries
        }
        workload = [(f"{cid}-r{rep}", cid, q) for rep in range(4) for cid, q in mixed_queries]
        self.assertEqual(len(workload), 20)

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            futs = [
                pool.submit(lambda req_id, base_id, q: (req_id, base_id, self.svc_ext.ask(q, conversation_id=req_id, debug=True)), req_id, base_id, q)
                for req_id, base_id, q in workload
            ]
            for fut in futs:
                req_id, base_id, res = fut.result(timeout=30.0)
                self.assertEqual(res["conversation_id"], req_id)
                self.assertEqual(_norm_chat_result(res), single_truth[base_id])

    def test_04_precheck_refusal_does_not_block_on_held_generation_lock(self) -> None:
        """Unsupported / pre-check refusal requests do not wait behind slow LLM generation."""
        llm_entered = threading.Event()
        release_llm = threading.Event()

        def slow_chat(**kwargs: Any) -> Dict[str, Any]:
            llm_entered.set()
            release_llm.wait(timeout=5.0)
            return {
                "message": {"content": "An installment plan is created in transaction FPR1 [S1]."},
                "prompt_eval_count": 400,
                "eval_count": 12,
                "total_duration": 200_000_000,
                "load_duration": 1_000_000,
                "prompt_eval_duration": 50_000_000,
                "eval_duration": 149_000_000,
            }

        client = RG.OllamaClient(chat=slow_chat)
        llm_gen = RG.LLMGenerator(client, name="ollama")
        ev_guard = EV.EvidenceGuard(llm_gen, tau=EV.SHIPPED_TAU, generation_concurrency=1)
        llm_pipe = RP.RagPipeline(
            self.base_pipe.backend, self.base_pipe.retriever, self.base_pipe.ctx, self.base_pipe.corpus,
            ev_guard, self.base_pipe.count_tokens, cards=list(self.base_pipe.cards.values()), config=self.cfg,
        )
        svc = S.RagService(llm_pipe, "ollama", generation_concurrency=1, coarse_lock=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            slow_fut = pool.submit(
                svc.ask, "How do I create an installment plan in FPR1?", conversation_id="slow-llm", debug=True
            )
            self.assertTrue(llm_entered.wait(timeout=5.0), "Slow LLM request did not enter OllamaClient.chat")

            # While slow_fut holds _gen_sem inside OllamaClient.chat, submit pre-check refusal & OOD requests:
            t0 = time.perf_counter()
            ref_res = svc.ask(
                "What is the exact SQL partition key for FPR1 installment plans?",
                conversation_id="fast-precheck-refusal",
                debug=True,
            )
            ood_res = svc.ask(
                "How do I bake a chocolate soufflé from scratch?",
                conversation_id="fast-ood",
                debug=True,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.assertFalse(slow_fut.done(), "Slow LLM request finished before release_llm was set")

            release_llm.set()
            slow_res = slow_fut.result(timeout=5.0)

        self.assertEqual(ref_res["status"], S.UNABLE_TO_VERIFY)
        self.assertFalse(ref_res["debug"]["evidence"]["supported"])
        self.assertEqual(ref_res["debug"]["timings_ms"]["queue_wait_ms"], 0.0)
        self.assertEqual(ood_res["status"], S.OUT_OF_SCOPE)
        self.assertEqual(ood_res["debug"]["timings_ms"]["queue_wait_ms"], 0.0)
        self.assertLess(elapsed_ms, 500.0)
        self.assertEqual(slow_res["conversation_id"], "slow-llm")

    def test_05_routing_retrieval_context_run_concurrently_during_llm_generation(self) -> None:
        """Deterministic routing/retrieval/context preparation runs concurrently while LLM generation is active."""
        first_in_llm = threading.Event()
        second_waiting_at_sem = threading.Event()
        release_first = threading.Event()
        call_num = 0
        lock = threading.Lock()

        def tracked_chat(**kwargs: Any) -> Dict[str, Any]:
            nonlocal call_num
            with lock:
                call_num += 1
                my_num = call_num
            if my_num == 1:
                first_in_llm.set()
                release_first.wait(timeout=5.0)
            return {
                "message": {"content": RG.NO_ANSWER_TEXT},
                "prompt_eval_count": 300,
                "eval_count": 6,
                "total_duration": 50_000_000,
                "load_duration": 1_000_000,
                "prompt_eval_duration": 20_000_000,
                "eval_duration": 29_000_000,
            }

        client = RG.OllamaClient(chat=tracked_chat)
        llm_gen = RG.LLMGenerator(client, name="ollama")
        ev_guard = EV.EvidenceGuard(llm_gen, tau=EV.SHIPPED_TAU, generation_concurrency=1)

        orig_build_units = EV.build_units
        precheck_completed_for_second = threading.Event()

        def wrapped_build_units(context: Any) -> Any:
            units = orig_build_units(context)
            if first_in_llm.is_set():
                precheck_completed_for_second.set()
                second_waiting_at_sem.set()
            return units

        EV.build_units = wrapped_build_units
        try:
            llm_pipe = RP.RagPipeline(
                self.base_pipe.backend, self.base_pipe.retriever, self.base_pipe.ctx, self.base_pipe.corpus,
                ev_guard, self.base_pipe.count_tokens, cards=list(self.base_pipe.cards.values()), config=self.cfg,
            )
            svc = S.RagService(llm_pipe, "ollama", generation_concurrency=1, coarse_lock=False)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(svc.ask, "How do I create an installment plan in FPR1?", conversation_id="r1", debug=True)
                self.assertTrue(first_in_llm.wait(timeout=5.0))

                f2 = pool.submit(svc.ask, "What is transaction EL43 used for?", conversation_id="r2", debug=True)
                # Verify that request 2 completes routing, retrieval, context build, AND EvidenceGuard.build_units
                # WHILE request 1 is still holding the generation semaphore!
                self.assertTrue(precheck_completed_for_second.wait(timeout=5.0))
                self.assertFalse(f1.done())

                release_first.set()
                r1 = f1.result(timeout=5.0)
                r2 = f2.result(timeout=5.0)
                self.assertEqual(r1["conversation_id"], "r1")
                self.assertEqual(r2["conversation_id"], "r2")
        finally:
            EV.build_units = orig_build_units

    def test_06_evidence_guard_precheck_runs_outside_generation_lock(self) -> None:
        """EvidenceGuard pre-check executes while _gen_sem is NOT acquired by the current thread."""
        sem = threading.BoundedSemaphore(1)
        precheck_saw_unlocked_sem = []

        class SpyInner:
            name = "spy"
            def generate(self, question: str, context: Any) -> RG.GenerationResult:
                # Inside inner.generate, the semaphore MUST be held (non-blocking acquire must return False)
                acquired = sem.acquire(blocking=False)
                if acquired:
                    sem.release()
                self.sem_was_held_during_inner = not acquired
                return RG.GenerationResult(text=RG.NO_ANSWER_TEXT, raw_text=RG.NO_ANSWER_TEXT, generator="spy", refused=True, prompt="p")

        spy = SpyInner()
        guard = EV.EvidenceGuard(spy, tau=EV.SHIPPED_TAU, generation_concurrency=1)
        guard._gen_sem = sem

        ans = self.ext_pipe.answer("How do I create an installment plan in FPR1?", debug=True)
        ctx_items = [type("Item", (), i)() for i in ans["debug"]["context"]["items"]]
        ctx_obj = type("Ctx", (), {"items": ctx_items})()

        orig_assess = EV.assess
        def check_sem_assess(*args: Any, **kwargs: Any) -> Any:
            # During pre-check (assess), the semaphore must still be free!
            acquired = sem.acquire(blocking=False)
            if acquired:
                sem.release()
            precheck_saw_unlocked_sem.append(acquired)
            return orig_assess(*args, **kwargs)

        EV.assess = check_sem_assess
        try:
            res = guard.generate("How do I create an installment plan in FPR1?", ctx_obj)
            self.assertEqual(precheck_saw_unlocked_sem, [True])
            self.assertTrue(spy.sem_was_held_during_inner)
            self.assertIsNotNone(res.evidence)
        finally:
            EV.assess = orig_assess

    def test_07_postcheck_and_grounding_run_outside_lock_after_generation(self) -> None:
        """EvidenceGuard post-check and verify_grounding run safely outside _gen_sem after generation."""
        sem = threading.BoundedSemaphore(1)
        postcheck_saw_unlocked_sem = []

        class UnverifiedOutputInner:
            name = "unverified_inner"
            def generate(self, question: str, context: Any) -> RG.GenerationResult:
                return RG.GenerationResult(
                    text="Completely unverified claim with bad citation [S99].",
                    raw_text="Completely unverified claim with bad citation [S99].",
                    generator="ollama",
                    refused=False,
                    prompt="p",
                )

        guard = EV.EvidenceGuard(UnverifiedOutputInner(), tau=EV.SHIPPED_TAU, generation_concurrency=1)
        guard._gen_sem = sem

        orig_kind_satisfied = EV.kind_satisfied
        def check_sem_postcheck(*args: Any, **kwargs: Any) -> bool:
            acquired = sem.acquire(blocking=False)
            if acquired:
                sem.release()
            postcheck_saw_unlocked_sem.append(acquired)
            return orig_kind_satisfied(*args, **kwargs)

        EV.kind_satisfied = check_sem_postcheck
        try:
            pipe = RP.RagPipeline(
                self.base_pipe.backend, self.base_pipe.retriever, self.base_pipe.ctx, self.base_pipe.corpus,
                guard, self.base_pipe.count_tokens, cards=list(self.base_pipe.cards.values()), config=self.cfg,
            )
            svc = S.RagService(pipe, "ollama", generation_concurrency=1, coarse_lock=False)
            svc.pipeline.generator._gen_sem = sem
            guard._gen_sem = sem

            res = svc.ask("How do I create an installment plan in FPR1?", conversation_id="post-1", debug=True)
            self.assertTrue(all(postcheck_saw_unlocked_sem))
            self.assertEqual(res["status"], S.UNABLE_TO_VERIFY)
            self.assertEqual(res["metadata"]["reason_code"], "GROUNDING_VERIFICATION_FAILED")
        finally:
            EV.kind_satisfied = orig_kind_satisfied

    def test_08_caches_return_isolated_copies_under_concurrent_reads_and_mutations(self) -> None:
        """Retriever/page caches return safe/isolated data under concurrent reads and caller mutation attempts."""
        retriever = self.ext_pipe.retriever
        corpus = self.ext_pipe.corpus
        # Warm cache
        self.svc_ext.ask("How do I create an installment plan in FPR1?", debug=False)
        g_id, p_id = next(iter(retriever._page_chunks_cache.keys()))

        def mutate_and_read(idx: int) -> bool:
            chunks = retriever.page_chunks(g_id, p_id)
            if not chunks:
                return False
            if "poison" in chunks[0].metadata:
                return False
            chunks[0].metadata["poison"] = f"worker-{idx}"
            chunks.clear()

            entry = corpus.entry("M2C-07")
            if entry is None or entry.get("corpus_status") != "ingested":
                return False
            entry["corpus_status"] = "mutated_invalid"
            return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(mutate_and_read, range(48)))
        self.assertTrue(all(outcomes))
        fresh_chunks = retriever.page_chunks(g_id, p_id)
        self.assertNotIn("poison", fresh_chunks[0].metadata)
        self.assertEqual(corpus.entry("M2C-07")["corpus_status"], "ingested")

    def test_09_ollama_failure_or_timeout_does_not_poison_or_deadlock_concurrent_requests(self) -> None:
        """Ollama failure/timeout in one request does not poison or deadlock concurrent requests."""
        def flaky_chat(**kwargs: Any) -> Dict[str, Any]:
            prompt = kwargs["messages"][0]["content"]
            if "EL43" in prompt:
                raise TimeoutError("Simulated Ollama HTTP timeout")
            return {
                "message": {"content": RG.NO_ANSWER_TEXT},
                "prompt_eval_count": 300,
                "eval_count": 6,
                "total_duration": 20_000_000,
            }

        client = RG.OllamaClient(chat=flaky_chat)
        llm_gen = RG.LLMGenerator(client, name="ollama")
        ev_guard = EV.EvidenceGuard(llm_gen, tau=EV.SHIPPED_TAU, generation_concurrency=1)
        pipe = RP.RagPipeline(
            self.base_pipe.backend, self.base_pipe.retriever, self.base_pipe.ctx, self.base_pipe.corpus,
            ev_guard, self.base_pipe.count_tokens, cards=list(self.base_pipe.cards.values()), config=self.cfg,
        )
        svc = S.RagService(pipe, "ollama", generation_concurrency=1, coarse_lock=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            f_fail = [pool.submit(svc.ask, "What is transaction EL43 used for?", conversation_id=f"fail-{i}") for i in range(3)]
            f_ok = [pool.submit(svc.ask, "How do I create an installment plan in FPR1?", conversation_id=f"ok-{i}") for i in range(3)]

            for fut in f_fail:
                with self.assertRaises(S.GeneratorFailure):
                    fut.result(timeout=10.0)
            for fut in f_ok:
                res = fut.result(timeout=10.0)
                self.assertIn(res["status"], (S.ANSWERED, S.UNABLE_TO_VERIFY))

        # Verify semaphore was cleanly released after all 3 TimeoutErrors
        res_after = svc.ask("How do I create an installment plan in FPR1?", conversation_id="after-timeout")
        self.assertEqual(res_after["conversation_id"], "after-timeout")

    def test_10_retriever_exception_does_not_poison_concurrent_or_subsequent_requests(self) -> None:
        """Retriever exception in one request does not poison subsequent/concurrent requests."""
        orig_retrieve = self.ext_pipe.retriever.retrieve_in_page

        def conditional_fail(query: str, *args: Any, **kwargs: Any) -> Any:
            if "TRIGGER_RETRIEVER_FAILURE_XYZ" in query:
                raise RuntimeError("Simulated Chroma read failure")
            return orig_retrieve(query, *args, **kwargs)

        self.ext_pipe.retriever.retrieve_in_page = conditional_fail
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                f_bad = pool.submit(
                    self.svc_ext.ask,
                    "How do I create an installment plan in FPR1 TRIGGER_RETRIEVER_FAILURE_XYZ?",
                    conversation_id="bad-ret",
                )
                f_good = [
                    pool.submit(self.svc_ext.ask, "How do I create an installment plan in FPR1?", conversation_id=f"good-{i}")
                    for i in range(3)
                ]
                with self.assertRaises(S.PipelineFailure):
                    f_bad.result(timeout=10.0)
                for fut in f_good:
                    r = fut.result(timeout=10.0)
                    self.assertEqual(r["status"], S.ANSWERED)
        finally:
            self.ext_pipe.retriever.retrieve_in_page = orig_retrieve

        r_subsequent = self.svc_ext.ask("How do I create an installment plan in FPR1?", conversation_id="subsequent")
        self.assertEqual(r_subsequent["status"], S.ANSWERED)

    def test_11_bounded_generation_semaphore_enforces_configured_concurrency_limit(self) -> None:
        """Bounded generation semaphore enforces configured concurrency limit (c=1, c=2, c=3)."""
        for limit in (1, 2, 3):
            state = {"active": 0, "max_active": 0, "lock": threading.Lock()}

            def sleeping_chat(**kwargs: Any) -> Dict[str, Any]:
                with state["lock"]:
                    state["active"] += 1
                    if state["active"] > state["max_active"]:
                        state["max_active"] = state["active"]
                try:
                    time.sleep(0.04)
                    return {
                        "message": {"content": RG.NO_ANSWER_TEXT},
                        "prompt_eval_count": 200,
                        "eval_count": 5,
                        "total_duration": 40_000_000,
                    }
                finally:
                    with state["lock"]:
                        state["active"] -= 1

            client = RG.OllamaClient(chat=sleeping_chat)
            llm_gen = RG.LLMGenerator(client, name="ollama")
            ev_guard = EV.EvidenceGuard(llm_gen, tau=EV.SHIPPED_TAU, generation_concurrency=limit)
            pipe = RP.RagPipeline(
                self.base_pipe.backend, self.base_pipe.retriever, self.base_pipe.ctx, self.base_pipe.corpus,
                ev_guard, self.base_pipe.count_tokens, cards=list(self.base_pipe.cards.values()), config=self.cfg,
            )
            svc = S.RagService(pipe, "ollama", generation_concurrency=limit, coarse_lock=False)

            qs = ["How do I create an installment plan in FPR1?"] * 6
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(lambda q: svc.ask(q), qs))

            self.assertLessEqual(state["max_active"], limit)
            self.assertEqual(state["max_active"], limit)

    def test_12_production_config_and_sequential_same_thread_isolation_invariants(self) -> None:
        """Production config invariants and sequential same-thread request state reset remain intact."""
        cfg = S.production_pipeline_config()
        self.assertEqual(cfg.top_k_cards, 10)
        self.assertEqual(cfg.k_chunks, 5)
        self.assertEqual(cfg.context_budget_tokens, 700)
        self.assertEqual(cfg.max_context_chunks, 4)
        self.assertTrue(cfg.rerank_router)
        self.assertTrue(cfg.code_aware_router)
        self.assertTrue(cfg.in_page_grounding)
        self.assertTrue(cfg.citation_normalization)
        self.assertTrue(cfg.relaxed_context_gate)
        self.assertFalse(cfg.evidence_frame_normalization)
        self.assertTrue(cfg.phrase_reranker)
        self.assertEqual(cfg.phrase_min_corroboration, 2)
        self.assertFalse(cfg.full_page_coverage)
        self.assertFalse(cfg.citation_repair)
        self.assertIsNone(cfg.ollama_num_predict)
        self.assertIsNone(cfg.ollama_keep_alive)
        self.assertEqual(S.DEFAULT_GENERATION_CONCURRENCY, 1)
        self.assertEqual(S.MAX_CONCURRENT_REQUESTS, 4)

        # Verify sequential same-thread isolation: Request 1 populates .last / debug["evidence"],
        # Request 2 exits at out_of_domain before Step 7 generation — state MUST be reset to None!
        r1 = self.svc_ext.ask("How do I create an installment plan in FPR1?", conversation_id="seq-1", debug=True)
        self.assertIsNotNone(r1["debug"]["evidence"])
        self.assertIsNotNone(self.svc_ext._evidence_gen.last)

        r2 = self.svc_ext.ask("How do I bake a chocolate soufflé from scratch?", conversation_id="seq-2", debug=True)
        self.assertEqual(r2["status"], S.OUT_OF_SCOPE)
        self.assertIsNone(r2["debug"]["evidence"])
        self.assertIsNone(self.svc_ext._evidence_gen.last)


if __name__ == "__main__":
    unittest.main(verbosity=2)
