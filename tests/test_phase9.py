"""Phase 9 - corpus audit, frozen fresh query set, chunk invariants on the real corpus, retrieval/answer/citation/failure behaviour,
Ollama detection and explicit generator selection (no silent fallback), results consistency, regression guards.

Tests that need the card store, the page store and the embedding weights skip with a reason when those are absent (they are generated, git-ignored data).
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
import sys
import types
import unittest
from unittest import mock

from tests.phase8_support import HAVE_BS4, HAVE_CHROMA, ROOT, StubBackend, corpus_records, make_pipeline, regex_count

import m2c_common as C  # noqa: E402
import m2c_page_identity as pid  # noqa: E402
import page_chunker as PK  # noqa: E402
import rag_generate as RG  # noqa: E402

try:
    C.resolve_model()
    from tests.phase8_support import have
    HAVE_MODEL = have("sentence_transformers")
except Exception:                                                        # noqa: BLE001
    HAVE_MODEL = False
from tests.phase8_support import CARD_STORE, PAGE_STORE  # noqa: E402

STORES = HAVE_CHROMA and HAVE_MODEL and (CARD_STORE / "chroma.sqlite3").is_file() and (PAGE_STORE / "chroma.sqlite3").is_file()
NEED_STORES = unittest.skipUnless(STORES, "needs chromadb, the embedding model, the card store and the page store")
NEED_PIPE = unittest.skipUnless(HAVE_CHROMA and HAVE_BS4, "chromadb / bs4 not installed")

EVAL = ROOT / "data" / "evaluation"
QUERIES = EVAL / "phase9_queries.json"
FREEZE = EVAL / "phase9_queries_freeze.json"
RESULTS = EVAL / "phase9_results.json"
AUDIT = EVAL / "phase9_failure_audit.json"
STATUS = ROOT / "data" / "phase9" / "corpus_status.json"
FETCHLOG = ROOT / "data" / "phase9" / "fetch_attempt_log.json"


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def norm(t):
    return " ".join((t or "").replace("\xa0", " ").split())


# ------------------------------------------------------------------------------------------------------------ 9A corpus audit

class CorpusAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load(STATUS)
        cls.rows = {r["card_id"]: r for r in cls.doc["cards"]}

    def test_all_29_cards_present_with_required_fields(self):
        self.assertEqual(len(self.rows), 29)
        for r in self.rows.values():
            for k in ("card_id", "title", "category", "source_url", "identity_status_7c", "effective_guide_id", "effective_page_id", "page_url", "local_page_available", "page_provenance",
                      "page_hash_sha256", "corpus_status", "fetched_in_phase9", "previously_present_in_phase8_corpus", "verification_status", "review_flag"):
                self.assertIn(k, r, (r["card_id"], k))

    def test_protected_identity_statuses_are_preserved_not_rewritten(self):
        ident = {c["source_id"]: c for c in load(ROOT / "data" / "m2c_page_identity.json")["cards"]}
        for sid, r in self.rows.items():
            self.assertEqual(r["identity_status_7c"], ident[sid]["resolution_status"], sid)
            self.assertEqual(r["effective_guide_id"], ident[sid]["effective_guide_id"], sid)
        self.assertEqual(self.rows["M2C-05"]["identity_status_7c"], pid.CORRECTED_IDENTITY)
        self.assertTrue(self.rows["M2C-05"]["corrected_identity"])
        self.assertEqual(self.rows["M2C-18"]["identity_status_7c"], pid.CONFLICTING_IDENTITY)
        for sid in ("M2C-01", "M2C-13", "M2C-16"):
            self.assertEqual(self.rows[sid]["identity_status_7c"], pid.CARD_IDENTITY_ONLY)
            self.assertFalse(self.rows[sid]["local_page_available"])
        self.assertEqual(self.rows["M2C-17"]["identity_status_7c"], pid.RESOLVED_LOCAL_PAGE)
        self.assertEqual([k for k, r in self.rows.items() if r["review_flag"]], ["M2C-14", "M2C-18", "M2C-23"])

    def test_available_and_missing_counts_and_pending_list(self):
        s = self.doc["summary"]
        self.assertEqual((s["pages_available"], s["pages_missing"], s["cards"]), (7, 22, 29))
        self.assertEqual(sorted(k for k, r in self.rows.items() if r["local_page_available"]), ["M2C-02", "M2C-05", "M2C-07", "M2C-11", "M2C-14", "M2C-17", "M2C-24"])
        self.assertEqual(len(s["pending_external_retrieval"]) + len(s["protected_unresolved"]), 22)
        self.assertEqual(set(s["protected_unresolved"]), {"M2C-01", "M2C-13", "M2C-16", "M2C-18"})

    def test_no_page_was_fetched_in_phase9_and_none_is_claimed(self):
        self.assertEqual(self.doc["summary"]["fetched_in_phase9"], [])
        self.assertTrue(all(not r["fetched_in_phase9"] for r in self.rows.values()))
        self.assertFalse((ROOT / "data" / "page_corpus" / "fetched").exists())

    def test_unavailable_pages_have_no_hash_or_url_and_are_not_called_verified_pages(self):
        for r in self.rows.values():
            if not r["local_page_available"]:
                self.assertIsNone(r["page_hash_sha256"])
                self.assertIsNone(r["page_url"])
                self.assertNotIn("page_verified", r["verification_status"])

    @unittest.skipUnless(HAVE_BS4, "bs4 missing")
    def test_page_hashes_match_page_text_and_doc_ids_are_unique(self):
        recs = corpus_records()
        ids = [r["doc_id"] for r in recs]
        self.assertEqual(len(ids), len(set(ids)))
        for r in recs:
            self.assertEqual(hashlib.sha256(r["text"].encode("utf-8")).hexdigest(), r["text_sha256"], r["doc_id"])
            self.assertEqual(self.rows[r["source_ids"][0]]["page_hash_sha256"], r["text_sha256"])
            self.assertTrue(r["validation"]["ok"])
            self.assertEqual(self.rows[r["source_ids"][0]]["page_url"], r["source_url"])
            self.assertEqual(r["guide_id"], self.rows[r["source_ids"][0]]["effective_guide_id"])

    @unittest.skipUnless(HAVE_BS4, "bs4 missing")
    def test_malformed_and_empty_pages_are_rejected_by_validation(self):
        import page_extract as PE
        self.assertFalse(PE.validate_extraction({"text": "", "blocks": []})["ok"])
        self.assertFalse(PE.validate_extraction({"text": "404 Not Found", "title": "404", "blocks": [{"text": "404 Not Found"}]})["ok"])

    def test_audit_script_is_idempotent(self):
        import phase9_corpus_audit as A
        before = (A.OUT_JSON.read_bytes(), A.OUT_MD.read_bytes())
        self.assertEqual(A.main(), 0)
        self.assertEqual((A.OUT_JSON.read_bytes(), A.OUT_MD.read_bytes()), before)


class FetchAttemptTests(unittest.TestCase):
    def test_failed_attempt_is_recorded_with_urls_from_the_plan_only(self):
        log = load(FETCHLOG)
        plan = load(ROOT / "data" / "page_corpus" / "fetch_plan.json")
        allowed = {e["request"].replace("GET ", "") for e in plan["pages_to_fetch"]}
        self.assertTrue(log)
        for run in log:
            self.assertEqual(run["saved"], [])
            self.assertIn(run["stopped_reason"], ("CIRCUIT_BREAKER_3_CONSECUTIVE_FAILURES", None))
            for a in run["attempts"]:
                self.assertIn(a["url"], allowed)                       # never a guessed URL
                self.assertTrue(a["http_status"] is None or a["http_status"] != 200 or a.get("error"))
                self.assertTrue(a["url"].startswith("https://help.sap.com/"))


# ------------------------------------------------------------------------------------------------------------ 9B query set

class QuerySetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = QUERIES.read_bytes()
        cls.payload = json.loads(cls.raw.decode("utf-8"))
        cls.qs = cls.payload["queries"]

    def test_frozen_hash_matches(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), load(FREEZE)["sha256"])
        self.assertEqual(load(FREEZE)["queries"], len(self.qs))

    def test_size_fields_and_authorship(self):
        self.assertTrue(100 <= len(self.qs) <= 150)
        for q in self.qs:
            for k in ("id", "query", "type", "facet", "answerability", "gold_source_id", "gold_doc_id", "evidence", "expected_status", "authorship", "authored_phase", "authored_on", "notes"):
                self.assertIn(k, q, q["id"])
            self.assertEqual(q["authored_phase"], 9)
        a = self.payload["authorship"]
        self.assertIn("AI", a["authored_by"])
        self.assertTrue(a["written_before_evaluation"])
        self.assertFalse(a["labels_changed_after_retrieval"])
        self.assertEqual(len({q["id"] for q in self.qs}), len(self.qs))
        self.assertEqual(len({" ".join(re.findall(r"[a-z0-9]+", q["query"].lower())) for q in self.qs}), len(self.qs))

    def test_required_query_kinds_are_covered(self):
        facets = {q["facet"] for q in self.qs}
        for f in ("keyword", "natural", "paraphrase", "entity", "rare_term", "multi_concept", "section_specific", "sibling_ambiguous", "terminology_mismatch"):
            self.assertIn(f, facets)
        self.assertEqual({q["type"] for q in self.qs}, {"answerable", "absent_detail", "not_ingested", "unresolved_identity", "out_of_domain"})
        self.assertEqual(self.payload["counts"], {t: sum(1 for q in self.qs if q["type"] == t) for t in self.payload["counts"]})

    @unittest.skipUnless(HAVE_BS4, "bs4 missing")
    def test_evidence_is_verbatim_and_absent_terms_are_absent(self):
        pages = {r["doc_id"]: norm(r["text"]) for r in corpus_records()}
        for q in self.qs:
            if q["type"] == "answerable":
                self.assertTrue(q["evidence"], q["id"])
                for e in q["evidence"]:
                    self.assertIn(norm(e), pages[q["gold_doc_id"]], q["id"])
            if q["type"] == "absent_detail":
                for t in q["absent_terms"]:
                    self.assertNotIn(t.lower(), pages[q["gold_doc_id"]].lower(), q["id"])
            if q["type"] in ("not_ingested", "unresolved_identity", "out_of_domain"):
                self.assertIsNone(q["gold_doc_id"])

    def test_queries_are_fresh_against_every_earlier_set(self):
        import build_phase9_queries as B
        prior = B.prior_queries()
        units = {u["source_id"]: B.words(u["embedding_text"]) for u in load(ROOT / "data" / "retrieval_units.json")["units"]}
        for q in self.qs:
            w = B.words(q["query"])
            self.assertNotIn(" ".join(w), prior, q["id"])
            self.assertTrue(all(B.jaccard(w, p.split()) < 0.8 for p in prior), q["id"])
            if q["type"] != "out_of_domain":
                self.assertLessEqual(max(B.longest_shared_run(w, cw) for cw in units.values()), 3, q["id"])

    def test_gold_cards_have_the_identity_role_the_label_assumes(self):
        ctx = pid.IdentityContext.from_root(ROOT)
        status = {c["source_id"]: c["resolution_status"] for c in load(ROOT / "data" / "m2c_page_identity.json")["cards"]}
        ingested = {r["card_id"] for r in load(STATUS)["cards"] if r["local_page_available"]}
        for q in self.qs:
            if q["type"] in ("answerable", "absent_detail"):
                self.assertIn(q["gold_source_id"], ingested)
            if q["type"] == "not_ingested":
                self.assertNotIn(q["gold_source_id"], ingested)
                self.assertEqual(status[q["gold_source_id"]], pid.IDENTIFIED_NOT_LOCAL)
            if q["type"] == "unresolved_identity":
                self.assertIn(status[q["gold_source_id"]], (pid.CONFLICTING_IDENTITY, pid.CARD_IDENTITY_ONLY))
        self.assertIsNotNone(ctx)

    def test_preregistered_constants_equal_code(self):
        import evaluate_phase9 as E
        E.check_preregistered(self.payload["preregistered"])
        tampered = dict(self.payload["preregistered"], ood_min_coverage=0.99)
        with self.assertRaises(SystemExit):
            E.check_preregistered(tampered)

    def test_evaluator_refuses_a_changed_query_file(self):
        import evaluate_phase9 as E
        with self.assertRaises(SystemExit):
            E.check_frozen(self.raw + b" ")
        self.assertEqual(E.check_frozen(self.raw)["sha256"], load(FREEZE)["sha256"])

    def test_prior_sets_and_phase8_set_are_untouched(self):
        self.assertTrue(hashlib.sha256((EVAL / "phase8_queries.json").read_bytes()).hexdigest().startswith("a7677ff6"))


# ------------------------------------------------------------------------------------------------------------ 9A.5 chunk invariants

@unittest.skipUnless(HAVE_BS4, "bs4 missing")
class RealCorpusChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs = corpus_records()
        cls.cfg = PK.STRATEGIES[PK.DEFAULT_STRATEGY]
        cls.chunks = PK.chunk_corpus(cls.recs, cls.cfg, regex_count)

    def test_default_strategy_is_unchanged_from_phase8(self):
        self.assertEqual(PK.DEFAULT_STRATEGY, "B_heading_200")

    def test_no_text_loss_every_block_is_in_a_chunk_of_its_page(self):
        for r in self.recs:
            joined = norm(" ".join(c["text"] for c in self.chunks if c["page_id"] == r["page_id"]))
            for b in r["blocks"]:
                t = norm(b["text"])
                if t:
                    self.assertIn(t, joined, (r["doc_id"], t[:60]))

    def test_no_duplicated_chunks_ids_or_texts(self):
        ids = [c["chunk_id"] for c in self.chunks]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len({norm(c["text"]) for c in self.chunks}), len(self.chunks))
        for r in self.recs:
            idx = [c["chunk_index"] for c in self.chunks if c["page_id"] == r["page_id"]]
            self.assertEqual(idx, list(range(len(idx))))

    def test_deterministic_rebuild(self):
        import build_page_collection as BP
        again = PK.chunk_corpus(corpus_records(), self.cfg, regex_count)
        self.assertEqual(BP.chunks_fingerprint(again), BP.chunks_fingerprint(self.chunks))

    def test_every_chunk_maps_to_a_valid_page_with_provenance(self):
        pages = {r["page_id"]: r for r in self.recs}
        for c in self.chunks:
            r = pages[c["page_id"]]
            self.assertEqual((c["guide_id"], c["source_url"], c["title"]), (r["guide_id"], r["source_url"], r["title"]))
            self.assertEqual(hashlib.sha256(c["text"].encode("utf-8")).hexdigest(), c["content_hash"])
            self.assertTrue(c["heading_path"] and c["heading_path"][0] == r["title"])
            for k in ("chunk_id", "section_title", "chunk_index"):
                self.assertIn(k, c)

    @unittest.skipUnless(HAVE_MODEL, "embedding model tokenizer missing")
    def test_token_limits_with_the_exact_model_tokenizer(self):
        count, info = PK.make_token_counter()
        self.assertTrue(info["exact"])
        chunks = PK.chunk_corpus(self.recs, self.cfg, count)
        self.assertLessEqual(max(count(c["text"]) for c in chunks), self.cfg.max_tokens)
        self.assertLessEqual(self.cfg.max_tokens, 256)


# ------------------------------------------------------------------------------------------------------------ pipeline behaviour on frozen queries (stubbed card layer)

@NEED_PIPE
class FrozenQueryPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qs = load(QUERIES)["queries"]
        cls.by_type = lambda s, t: [q for q in cls.qs if q["type"] == t]

    def pipe(self, generator=None, ranking=None):
        return make_pipeline(generator or RG.ExtractiveGenerator(), ranking=ranking)

    def test_oracle_answers_cite_only_gold_page_and_card_url_is_unchanged(self):
        units = {u["source_id"]: u for u in load(ROOT / "data" / "retrieval_units.json")["units"]}
        p = self.pipe()
        answered = 0
        for q in self.by_type("answerable")[:30]:
            a = p.answer(q["query"], oracle_source_id=q["gold_source_id"], debug=True)
            if a["status"] != "answered":
                continue
            answered += 1
            ctx_ids = {i["chunk_id"] for i in a["debug"]["context"]["items"]}
            for s in a["citations"]["answer_sources"]:
                self.assertEqual(f"{s['guide_id']}/{s['page_id']}", q["gold_doc_id"])
                self.assertEqual(s["url"], units[q["gold_source_id"]]["source_url"])
                self.assertIn(s["chunk_id"], ctx_ids)
            self.assertFalse(a["citations"]["topic_pointer"]["used_as_answer_text"])
            self.assertFalse(a["citations"]["topic_pointer"]["verified_used"])
        self.assertGreater(answered, 5)

    def test_not_ingested_cards_are_never_answered(self):
        for q in self.by_type("not_ingested"):
            a = self.pipe().answer(q["query"], oracle_source_id=q["gold_source_id"])
            self.assertIn(a["status"], ("page_not_ingested", "out_of_domain"), q["id"])      # out_of_domain only through the lexical gate, never answered
            self.assertIsNone(a["answer"])
            self.assertEqual(a["citations"]["answer_sources"], [])

    def test_unresolved_and_conflicting_identities_return_unresolved_without_generation(self):
        class Boom:
            def generate(self, prompt):
                raise AssertionError("the generator must not be called")
        for q in self.by_type("unresolved_identity"):
            a = make_pipeline(RG.LLMGenerator(Boom())).answer(q["query"], oracle_source_id=q["gold_source_id"])
            self.assertEqual(a["status"], "unresolved_identity", q["id"])
            self.assertEqual(a["citations"]["answer_sources"], [])
            if q["gold_source_id"] == "M2C-18":
                self.assertEqual(a["reason_code"], "CONFLICTING_IDENTITY")

    def test_no_card_candidate_gives_no_relevant_page_and_no_generation(self):
        p = make_pipeline(RG.ExtractiveGenerator(), ranking={"anything at all": []})
        a = p.answer("anything at all")
        self.assertEqual(a["status"], "no_relevant_page")
        self.assertIsNone(a["answer"])

    def test_out_of_domain_queries_are_refused_by_the_gate_with_a_stubbed_router(self):
        flagged = 0
        p = self.pipe()
        for q in self.by_type("out_of_domain")[:14]:
            a = p.answer(q["query"])
            self.assertNotEqual(a["status"], "answered", q["id"])
            flagged += a["status"] == "out_of_domain"
        self.assertGreaterEqual(flagged, 10)

    def test_absent_detail_never_gets_a_fabricated_detail_from_stub_fabricators(self):
        import evaluate_phase8 as EP8
        q = self.by_type("absent_detail")[0]
        for name, fn in EP8.FABRICATIONS.items():
            if name == "faithful_control":
                continue
            a = make_pipeline(RG.LLMGenerator(EP8._Stub(fn), name=name)).answer(q["query"], oracle_source_id=q["gold_source_id"])
            self.assertNotEqual(a["status"], "answered", name)

    def test_generator_unavailable_propagates_and_is_not_replaced_by_extractive(self):
        class Down:
            def generate(self, prompt):
                raise ConnectionError("ollama is not running")
        q = self.by_type("answerable")[0]
        with self.assertRaises(ConnectionError):
            make_pipeline(RG.LLMGenerator(Down(), name="ollama")).answer(q["query"], oracle_source_id=q["gold_source_id"])

    def test_empty_query(self):
        self.assertEqual(self.pipe().answer("   ")["status"], "no_relevant_page")

    def test_answers_are_deterministic(self):
        q = self.by_type("answerable")[3]
        a = self.pipe().answer(q["query"], oracle_source_id=q["gold_source_id"], debug=True)
        b = self.pipe().answer(q["query"], oracle_source_id=q["gold_source_id"], debug=True)
        for x in (a, b):
            x.pop("timings_ms", None)
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))


# ------------------------------------------------------------------------------------------------------------ Ollama detection, explicit selection, LLM evaluation path

class OllamaPathTests(unittest.TestCase):
    def test_detection_reports_blocked_when_nothing_is_reachable(self):
        import evaluate_phase9 as E
        with mock.patch("socket.create_connection", side_effect=OSError("refused")), mock.patch("shutil.which", return_value=None):
            d = E.detect_ollama()
        self.assertFalse(d["available"])
        self.assertTrue(d["status"].startswith("BLOCKED"))
        self.assertFalse(d["server_reachable_127_0_0_1_11434"])

    def test_detection_requires_server_package_and_the_configured_model(self):
        import evaluate_phase9 as E
        import rag_core
        fake = types.ModuleType("ollama")
        fake.list = lambda: {"models": [{"model": rag_core.LLM_MODEL_NAME}]}
        cm = mock.MagicMock()
        with mock.patch("socket.create_connection", return_value=cm), mock.patch.dict(sys.modules, {"ollama": fake}), mock.patch("importlib.util.find_spec", return_value=object()):
            self.assertTrue(E.detect_ollama()["available"])
        fake.list = lambda: {"models": [{"model": "some-other-model:1b"}]}
        with mock.patch("socket.create_connection", return_value=cm), mock.patch.dict(sys.modules, {"ollama": fake}), mock.patch("importlib.util.find_spec", return_value=object()):
            d = E.detect_ollama()
        self.assertFalse(d["available"])                                   # a different model is never substituted
        self.assertFalse(d["configured_model_listed"])

    def test_recorded_ollama_status_matches_this_environment(self):
        import evaluate_phase9 as E
        res = load(RESULTS)["ollama_evaluation"]
        if E.detect_ollama()["available"]:
            self.skipTest("Ollama is available here; the recorded BLOCKED status describes the evaluation environment")
        self.assertTrue(res["status"].startswith("BLOCKED"))
        self.assertFalse(res["detection"]["available"])
        self.assertIn("LLM latency", res["not_measured"])

    def test_cli_generator_choices_are_explicit_and_default_is_ollama(self):
        import rag_answer
        with self.assertRaises(SystemExit):
            rag_answer.main(["--generator", "gpt-4", "--question", "x"])
        import inspect
        self.assertIn('default="ollama"', inspect.getsource(rag_answer))

    def test_cli_ollama_failure_exits_nonzero_and_prints_no_answer(self):
        import contextlib
        import io
        import rag_answer

        class P:
            def answer(self, q, debug=False):
                raise ModuleNotFoundError("No module named 'ollama'")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = rag_answer.main(["--generator", "ollama", "--question", "hi"], pipeline=P())
        self.assertEqual(rc, 3)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("generation failed", err.getvalue())

    def test_build_pipeline_selects_the_requested_generator_without_fallback(self):
        import rag_pipeline as RP
        src = (ROOT / "scripts" / "rag_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('ExtractiveGenerator() if generator == "extractive" else LLMGenerator(', src)
        class Stub:
            def generate(self, prompt):
                return "x"
        self.assertTrue(callable(RP.build_pipeline))
        self.assertEqual(RG.LLMGenerator(Stub(), name="ollama").name, "ollama")

    @NEED_PIPE
    def test_llm_evaluation_path_with_a_stub_client_and_runtime_failures_are_recorded(self):
        import evaluate_phase8 as EP8
        import evaluate_phase9 as E
        qs = [q for q in load(QUERIES)["queries"] if q["type"] == "answerable"][:3]
        ranking = {q["query"]: [q["gold_source_id"]] for q in qs}
        pipe = make_pipeline(RG.ExtractiveGenerator(), ranking=ranking)

        class Faithful:
            def generate(self, prompt):
                m, s = EP8._first_context(prompt)
                return f"{s} [{m}]"
        out = E.run_llm_eval(pipe, qs, Faithful(), regex_count, name="stub_llm")
        self.assertEqual(out["generator"], "stub_llm")
        self.assertEqual(out["runtime_failures"], [])
        self.assertGreaterEqual(out["oracle_routing"]["generation"]["answered_given_answerable"]["k"], 1)

        class Down:
            def generate(self, prompt):
                raise ConnectionError("down")
        bad = E.run_llm_eval(pipe, qs, Down(), regex_count, name="stub_llm")
        self.assertEqual(len(bad["runtime_failures"]), 6)
        self.assertTrue(all(f["failure_category"] == "model_runtime_failure" for f in bad["runtime_failures"]))
        self.assertEqual(bad["oracle_routing"]["generation"]["answered_given_answerable"]["k"], 0)       # nothing was answered by a fallback


# ------------------------------------------------------------------------------------------------------------ results consistency / regression

class ResultsConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = load(RESULTS)
        cls.audit = load(AUDIT)

    def test_results_bound_to_the_frozen_query_file_and_corpus(self):
        self.assertEqual(self.r["freeze"]["sha256"], load(FREEZE)["sha256"])
        self.assertEqual(self.r["corpus"]["sha256"], load(ROOT / "data" / "page_corpus" / "manifest.json")["corpus_sha256"])
        self.assertEqual((self.r["corpus"]["pages_available"], self.r["corpus"]["pages_missing"]), (7, 22))
        self.assertEqual(self.r["official_page_fetch"]["pages_saved"], 0)
        self.assertTrue(self.r["official_page_fetch"]["status"].startswith("FAILED"))

    def test_router_metrics_are_internally_consistent(self):
        c = self.r["card_router"]
        n = c["all_gold_card_queries"]["n"]
        k1 = c["all_gold_card_queries"]["recall@1"]["k"]
        self.assertEqual(c["failure_count"], n - k1)
        self.assertEqual(len(self.r["router_failures"]), n - k1)
        self.assertEqual(sum(c["failure_causes_heuristic"].values()), n - k1)
        self.assertLessEqual(c["all_gold_card_queries"]["recall@1"]["rate"], c["all_gold_card_queries"]["recall@3"]["rate"])
        self.assertLessEqual(c["all_gold_card_queries"]["recall@3"]["rate"], c["all_gold_card_queries"]["recall@5"]["rate"])
        self.assertIn("NOT a proven root cause", c["failure_classification_note"])
        self.assertTrue(all(f["gold_rank"] != 1 for f in self.r["router_failures"]))

    def test_page_retrieval_is_reported_for_the_default_strategy_only(self):
        p = self.r["page_retrieval"]
        self.assertEqual(p["strategy"], "B_heading_200")
        self.assertEqual(p["in_gold_page"]["recall@5"]["n"], self.r["query_counts"]["answerable"])
        self.assertEqual(self.r["chunking"]["strategy"], "B_heading_200")

    def test_stages_are_reported_separately_and_citation_invariants_hold(self):
        for key in ("end_to_end_router_rank1_extractive", "end_to_end_oracle_routing_extractive"):
            e = self.r[key]
            self.assertEqual(e["citation"]["phantom_citations"], 0)
            self.assertEqual(e["citation"]["topic_pointer_counted_as_evidence"], 0)
            self.assertEqual(e["citation"]["answer_source_url_differs_from_card_url"], 0)
            self.assertEqual(e["generation"]["grounding_verifier_passed_among_answered"]["k"], e["generation"]["answered_given_answerable"]["k"])
        r1 = self.r["end_to_end_router_rank1_extractive"]
        self.assertTrue(r1["identity"]["m2c18_never_answered"])
        self.assertEqual(r1["identity"]["unresolved_card_routed_but_never_answered"]["of_those_answered"], 0)
        self.assertEqual(r1["identity"]["m2c05_correction_preserved"]["k"], r1["identity"]["m2c05_correction_preserved"]["n"])

    def test_fabrication_stubs_are_withheld_and_control_passes(self):
        cases = self.r["hallucination_guard_stub_generators"]["cases"]
        self.assertGreater(cases["faithful_control"]["fabricated_answer_shown"], 0)
        for name, c in cases.items():
            if name != "faithful_control":
                self.assertEqual(c["fabricated_answer_shown"], 0, name)
                self.assertEqual(c["withheld_by_verifier"], cases["faithful_control"]["fabricated_answer_shown"], name)

    def test_failure_audit_rows_have_all_required_fields_and_counts_match(self):
        need = ("query", "selected_card", "identity_status", "retrieved_chunk_ids", "answer", "cited_chunk_ids", "expected_evidence", "failure_category")
        counts = {}
        for row in self.audit["rows"]:
            for k in need:
                self.assertIn(k, row)
            counts.setdefault(row["mode"], {}).setdefault(row["failure_category"], 0)
            counts[row["mode"]][row["failure_category"]] += 1
            self.assertIn(row["failure_category"], self.audit["taxonomy"])
        self.assertEqual({m: dict(sorted(c.items())) for m, c in counts.items()}, self.r["failure_audit_counts_by_mode"])
        for cat in ("unsupported_claim", "hallucinated_detail", "model_runtime_failure"):
            self.assertTrue(all(row["failure_category"] != cat for row in self.audit["rows"]))       # cannot occur with the extractive generator

    def test_regression_block_matches_recorded_baselines(self):
        reg = self.r["regression"]
        self.assertTrue(reg["phase4"]["matches_recorded_4dp"], reg["phase4"])
        self.assertTrue(reg["phase5_independent"]["matches_recorded_4dp"], reg["phase5_independent"])
        self.assertTrue(reg["phase8_results_unchanged_since_phase8"])

    def test_no_timing_values_in_the_deterministic_results(self):
        text = RESULTS.read_text(encoding="utf-8")
        for needle in ("_ms\"", "seconds", "latency_ms", "peak_rss"):
            self.assertNotIn(needle, text.replace('"ollama_latency"', ""))

    def test_performance_file_has_timings_and_states_ollama_not_measured(self):
        perf = load(EVAL / "phase9_performance.json")
        self.assertIn("per_query_ms_router_mode_extractive", perf)
        self.assertTrue(perf["ollama_latency"].startswith("NOT MEASURED") or "see llm" in perf["ollama_latency"])

    @NEED_STORES
    def test_router_and_page_results_reproduce_live(self):
        import evaluate_phase9 as E
        import page_corpus as PC
        import rag_pipeline as RP
        qs = load(QUERIES)["queries"]
        sample = [q for q in qs if q["type"] == "answerable"][:12]
        pipe = RP.build_pipeline()
        routes = E.route_all(pipe, sample)
        again = E.route_all(pipe, sample)
        self.assertEqual(routes, again)                                    # ranking determinism
        recorded = {f["id"]: f for f in self.r["router_failures"]}
        for q in sample:
            top1 = routes[q["id"]][0]["source_id"]
            self.assertEqual(top1 != q["gold_source_id"], q["id"] in recorded, q["id"])
            if q["id"] in recorded:
                self.assertEqual(recorded[q["id"]]["routed"], top1)
        for q in sample:
            g, p = q["gold_doc_id"].split("/")
            hits = pipe.retriever.retrieve_in_page(q["query"], g, p, top_k=5)
            self.assertTrue(all(h.guide_id == g and h.page_id == p for h in hits))
            self.assertEqual(self.r["page_retrieval"]["rank_by_query"][q["id"]], next((h.rank for h in hits if E.has_evidence(h.text, q["evidence"])), None))
        self.assertIsNotNone(PC)


class ExtrasTests(unittest.TestCase):
    """Chunking comparison, gate distributions, source chains and CLI evidence (scripts/phase9_extras.py)."""

    @classmethod
    def setUpClass(cls):
        cls.x = load(EVAL / "phase9_extras.json")
        cls.chains = load(EVAL / "phase9_source_chains.json")

    def test_bound_to_frozen_queries_and_rules_equal_code(self):
        import phase9_extras as X
        self.assertEqual(self.x["queries_sha256"], load(FREEZE)["sha256"])
        self.assertEqual(self.x["preregistered_rules"], X.RULES)
        self.assertEqual(X.RULES["chunking"], {"min_mrr_gain": 0.03, "recall@5_not_lower": True, "sign_test_p_below": 0.05, "adopt_without_held_out": False})
        self.assertFalse(X.RULES["chunking"]["adopt_without_held_out"])

    def test_chunking_default_kept_and_nothing_adopted_without_held_out_data(self):
        c = self.x["chunking_comparison"]
        self.assertEqual(c["default_kept"], "B_heading_200")
        for name, v in c["verdicts"].items():
            self.assertFalse(v["adopted"], name)
        s = c["strategies"]
        self.assertEqual(s["B_heading_200"]["chunk_stats"]["chunks"], 32)
        self.assertTrue(s["B_heading_200"]["metadata_preserved"])
        self.assertEqual(s["B_heading_200"]["retrieval"]["in_gold_page"]["recall@1"]["rate"], load(RESULTS)["page_retrieval"]["in_gold_page"]["recall@1"]["rate"])
        self.assertEqual(s["B_heading_200"]["multi_evidence_queries"], 0)          # multi-section questions are NOT evaluable with this set; the report must say so

    def test_gate_threshold_is_not_justified_and_constants_unchanged(self):
        import rag_pipeline as RP
        g = self.x["gate_distribution"]
        self.assertFalse(g["threshold_justified"])
        self.assertTrue(g["router_rank1"]["distributions_overlap"])
        self.assertEqual((g["ood_min_coverage_in_force"], g["context_min_coverage_in_force"]), (RP.OOD_MIN_COVERAGE, RP.CONTEXT_MIN_COVERAGE))
        self.assertEqual((RP.OOD_MIN_COVERAGE, RP.CONTEXT_MIN_COVERAGE), (0.25, 0.5))
        self.assertEqual(g["router_rank1"]["out_of_domain_answered"], 0)
        self.assertEqual(g["router_rank1"]["in_domain_refused_by_topic_gate_false_refusals"]["k"], load(RESULTS)["ood_observations"]["in_domain_wrongly_flagged_out_of_domain"]["k"])

    def test_every_source_chain_passes_every_check(self):
        sm = self.chains["summary"]
        self.assertEqual(sm["chains"], len(self.chains["rows"]))
        self.assertEqual(sm["chains"], 127 + 111)
        for k, v in sm.items():
            if isinstance(v, dict):
                self.assertEqual(v["passed"], v["of"], k)
        for r in self.chains["rows"]:
            if r["status"] == "answered":
                self.assertTrue(r["cited_chunk_ids"] and r["answer"] and r["citation_urls"])
                self.assertTrue(set(r["cited_chunk_ids"]) <= set(r["context_chunk_ids"]))
            else:
                self.assertEqual((r["cited_chunk_ids"], r["citation_urls"]), ([], []))
        self.assertTrue(all(r["card"] != "M2C-18" for r in self.chains["rows"] if r["status"] == "answered"))

    def test_cli_evidence_ollama_failure_is_loud_and_never_falls_back(self):
        c = self.x["cli_evidence"]
        self.assertEqual(c["extractive_answerable"]["status"], "answered")
        self.assertEqual(c["extractive_out_of_domain"]["status"], "out_of_domain")
        o = c["ollama_requested"]
        if o["exit_code"] == 0:
            self.skipTest("Ollama was available when the evidence was recorded")
        self.assertEqual(o["exit_code"], 3)
        self.assertTrue(o["stdout_empty"])
        self.assertIn("generation failed", o["stderr_last_line"])

    def test_second_fetch_attempt_also_saved_nothing(self):
        log = load(ROOT / "data" / "phase9" / "fetch_attempt_log_run2.json")
        self.assertTrue(all(run["saved"] == [] for run in log))
        self.assertTrue(all(a["url"].startswith("https://help.sap.com/") for run in log for a in run["attempts"]))

    def test_pipeline_start_failure_is_graceful_when_stores_are_missing(self):
        import contextlib
        import io
        import rag_answer
        import rag_pipeline as RP
        err = io.StringIO()
        with mock.patch.object(RP, "build_pipeline", side_effect=RuntimeError("card collection not found")), contextlib.redirect_stderr(err):
            rc = rag_answer.main(["--generator", "extractive", "--question", "x"])
        self.assertEqual(rc, 2)
        self.assertIn("cannot start the pipeline", err.getvalue())

    @NEED_STORES
    def test_recorded_chains_reproduce_live(self):
        import evaluate_phase8 as EP8
        import rag_pipeline as RP
        qs = load(QUERIES)["queries"]
        sample = [qs[i] for i in range(0, len(qs), 11)]
        pipe = RP.build_pipeline(generator="extractive")
        rec = {(r["id"], r["mode"]): r for r in self.chains["rows"]}
        for row in EP8.run_pipeline(pipe, sample, oracle=False):
            r = rec[(row["q"]["id"], "router_rank1")]
            self.assertEqual((row["a"]["status"], row["a"]["routing"]["selected_source_id"]), (r["status"], r["card"]))
            self.assertEqual([s["chunk_id"] for s in row["a"]["citations"]["answer_sources"]], r["cited_chunk_ids"])
            self.assertEqual(row["a"]["answer"], r["answer"])


class ReportConsistencyTests(unittest.TestCase):
    def test_report_headline_numbers_match_results_and_blocked_text_is_exact(self):
        rep = (ROOT / "data" / "phase9_report.md").read_text(encoding="utf-8")
        r = load(RESULTS)
        self.assertIn("Ollama evaluation blocked: local model unavailable.", rep)
        self.assertIn("PARTIALLY COMPLETE", rep)
        c = r["card_router"]["all_gold_card_queries"]
        for v in (c["recall@1"]["rate"], c["recall@3"]["rate"], c["recall@5"]["rate"], c["mrr"]):
            self.assertIn(f"{v:.4f}".rstrip("0") if f"{v:.4f}".endswith("0") and f"{v:.4f}"[-2] != "0" else f"{v:.4f}", rep)
        p = r["page_retrieval"]["in_gold_page"]
        self.assertIn(f"{p['recall@1']['rate']:.4f}", rep)
        self.assertIn(f"{p['mrr']:.4f}", rep)
        counts = load(RESULTS)["failure_audit_counts_by_mode"]
        self.assertIn(f"{sum(counts['oracle'].values())} oracle-routing failures and {sum(counts['router_rank1'].values())} real-router failures", rep)
        self.assertEqual(r["freeze"]["sha256"][:8], "28f03e57")
        self.assertIn("28f03e57", rep)
        self.assertNotIn("29/29 covered", rep)
        x = load(EVAL / "phase9_extras.json")
        for sec in ("COMPLETED", "BLOCKED", "NOT CLAIMED", "Reproducibility"):
            self.assertIn(sec, rep)
        self.assertIn(f"{x['source_chain_summary']['chains']} source chains", rep)
        self.assertIn("help.sap.com", rep)
        self.assertIn("fetch_attempt_log_run2.json", rep)


class ProtectedArtefactTests(unittest.TestCase):
    PINS = {"scripts/rag_chat.py": "e862ce38d06e2ef74f39e366a5a8b65948ba03f00dfab5baa0c61bc281673a15",
            "scripts/rag_core.py": "881316e4f9f2c164b2109f416b2a309f8ab829f185d231b09990274f56567b2c",
            "data/card_collection_manifest.json": "5b3a5c30bc637c8b61573983a16cf252f7899d2c279eae3895e06476482d2731",
            "data/m2c_page_identity.json": "fccb0bb87fc6309ac0fa9e1205387c68aeb6f93fff73d6aab457a2164587787c",
            "data/page_corpus/manifest.json": None}

    def test_phase8_and_earlier_artefacts_unchanged(self):
        for p, h in self.PINS.items():
            if h:
                self.assertEqual(hashlib.sha256((ROOT / p).read_bytes()).hexdigest(), h, p)
        self.assertTrue(hashlib.sha256((EVAL / "phase8_results.json").read_bytes()).hexdigest().startswith("735f706188d8154e"))
        self.assertFalse((ROOT / "chroma_db").exists())
        self.assertFalse((ROOT / "scripts" / "rag_two_stage.py").exists())

    def test_phase9_scripts_do_not_import_network_modules(self):
        import ast
        for name in ("build_phase9_queries", "evaluate_phase9", "phase9_corpus_audit"):
            tree = ast.parse((ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8"))
            mods = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            self.assertFalse(mods & {"urllib.request", "http.client", "requests", "urllib.error"}, (name, mods))
            top = {n.names[0].name for n in tree.body if isinstance(n, ast.Import)} | {n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.module}
            self.assertNotIn("ollama", top)                                                  # the local-model client is only ever imported lazily, inside detection

    def test_no_env_or_secret_files_in_the_repository(self):
        bad = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and (p.name == ".env" or p.name.endswith((".pem", ".key")))]
        self.assertEqual(bad, [])

    def test_socket_detection_is_local_only(self):
        import inspect
        import evaluate_phase9 as E
        src = inspect.getsource(E.detect_ollama)
        self.assertIn('("127.0.0.1", 11434)', src)
        self.assertNotIn("http", src.replace("# ", ""))
        self.assertTrue(callable(socket.create_connection))


if __name__ == "__main__":
    unittest.main()
