"""Phase 7E - router and regression evaluation (spec section 5, step 7E).

Most tests need no store: they check the committed evaluation document against the recorded Phase 4/5 data, exercise the
evaluator's functions with a deterministic stub backend, and enforce the scope rules (no retrieval change, no threshold, no
network, no LLM, no legacy import, no write to a collection). The store-gated test re-runs the evaluation in a fresh process
against the real store and real model and requires a byte-identical document (skipped, with a reason, when they are missing).
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import m2c_common as C  # noqa: E402

ev = importlib.import_module("evaluate_two_stage")
pid = importlib.import_module("m2c_page_identity")
cit = importlib.import_module("m2c_citations")

EVAL = ROOT / "data" / "evaluation"
DOC_PATH = ROOT / "data" / "phase7E_evaluation.json"
VECTOR = C.VECTOR_DIR


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


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


DOC = load(DOC_PATH)
P4 = load(EVAL / "card_retrieval_results.json")
P5 = load(EVAL / "phase5_results.json")["datasets"]["phase5"]["systems"]["dense"]
UNITS = load(C.UNITS_PATH)["units"]

PINNED = {
    # Phases 7A-7D implementation (must not change for 7E)
    "scripts/m2c_router.py": "b846f18d098406c17859d053ae5b9c0ddb5b82e247e92ac709edeed1113ea8f4",
    "scripts/m2c_page_join.py": "a7744701a710df9575eea3861a61204ee63deb995f761cc715dcd150b6dee156",
    "scripts/m2c_orchestrator.py": "89bcfcc1c57669f492d92d12e2f720b2e9d9b36035c678737db4d081213782dd",
    "scripts/m2c_page_identity.py": "877b4f52d841bf475b149d9bcb601ad858b97bf2c6d3059ad5fbd5abe2c96163",
    "scripts/m2c_citations.py": "379fc6b89c587df227fa23e4053c8d4927b5902cf4484c61c0080abf3fdd4fb9",
    "data/m2c_page_identity.json": "fccb0bb87fc6309ac0fa9e1205387c68aeb6f93fff73d6aab457a2164587787c",
    "data/m2c_citation_audit.json": "009ede7a187d11850a1c7e3cd72f964090ef4f0d161daffab6ecd3206901ded6",
    # Phase 4/5 expected labels and results, legacy questions and recorded results, collection manifest
    "data/evaluation/card_retrieval_questions.json": "530f2d96cb644518fcbe20b0082870b01a08fd4bc524c10d208fd9c72c1ceb36",
    "data/evaluation/card_retrieval_results.json": "c1b0459779eeb0ac0f4dbf26c6e128302c91ad7be0aa75db6a2d657e45c49206",
    "data/evaluation/independent_queries.json": "1ce1306db646981b68245d75a1a912310ad3d760d90593bd005dfcc3500956e4",
    "data/evaluation/phase5_results.json": "2ca554287c9c2397f125e086cd121e5bd67983588bf798011e0298b286f0ef6d",
    "data/evaluation_questions.json": "dc0801cce3ec63e176062ea46914500169b5cfd8c8a1f2991b060edb3108a674",
    "data/retrieval_results.json": "8edaa6cea367cc814c5ed5de550e061220a7231893c2f702b499b2d89f3de063",
    "data/card_collection_manifest.json": "5b3a5c30bc637c8b61573983a16cf252f7899d2c279eae3895e06476482d2731",
}


class StubBackend:
    """Deterministic 29-card backend (no store, no model): a fixed pseudo-random order per query, ascending cosine distances."""
    distance_metric = "cosine"

    def __init__(self):
        bcc = importlib.import_module("build_card_collection")
        self.meta = {u["source_id"]: bcc.metadata_for(u) for u in UNITS}
        self.calls = 0

    def query(self, query, n_results):
        self.calls += 1
        ids = sorted(self.meta, key=lambda i: (zlib.crc32((query + i).encode()), i))[:n_results]
        return {"ids": [ids], "metadatas": [[self.meta[i] for i in ids]], "distances": [[0.3 + 0.01 * k for k in range(len(ids))]]}


_CTX = None


def ctx():
    global _CTX
    if _CTX is None:
        _CTX = pid.IdentityContext.from_root(ROOT)
    return _CTX


# ------------------------------------------------------------------------------------------------ committed document vs recorded data


class CommittedDocumentTests(unittest.TestCase):
    def test_all_recorded_checks_ok_and_document_scope(self):
        self.assertTrue(DOC["ok"])
        self.assertTrue(all(c["ok"] for c in DOC["checks"]), [c["check"] for c in DOC["checks"] if not c["ok"]])
        s = DOC["scope"]
        self.assertFalse(s["retrieval_changed"])
        self.assertFalse(s["threshold_applied"])
        self.assertFalse(s["answer_generated"])
        self.assertFalse(s["pages_fetched_or_ingested"])
        self.assertTrue(s["rank1_is_not_confidence"])
        self.assertEqual(DOC["isolation"], {"network_attempts": 0, "banned_modules_loaded": []})

    def test_input_hashes_are_the_protected_ones(self):
        i = DOC["inputs"]
        self.assertEqual(i["collection_manifest_sha256"], PINNED["data/card_collection_manifest.json"])
        self.assertEqual(i["phase4_results_sha256"], PINNED["data/evaluation/card_retrieval_results.json"])
        self.assertEqual(i["phase5_results_sha256"], PINNED["data/evaluation/phase5_results.json"])
        self.assertEqual(i["phase5_queries_sha256"], PINNED["data/evaluation/independent_queries.json"])
        self.assertEqual(i["legacy_results_sha256"], PINNED["data/retrieval_results.json"])
        self.assertEqual(i["legacy_questions_sha256"], PINNED["data/evaluation_questions.json"])

    def test_phase4_top1_top5_and_expected_ranks_equal_recorded_independently(self):
        per = {p["id"]: p for p in DOC["per_query"]["phase4"]}
        self.assertEqual(len(per), 50)
        for r in P4["per_question"]:
            p = per[r["question_id"]]
            self.assertEqual(p["top5"], [x["source_id"] for x in r["retrieved_top5"]], r["question_id"])
            self.assertEqual(p["rank1"], r["retrieved_top5"][0]["source_id"])
            self.assertEqual(p["first_expected_rank"], r["first_expected_rank"], r["question_id"])
            for d, x in zip(p["top5_distances"], r["retrieved_top5"]):   # distances are stored to 6 dp, recorded similarities to 4 dp
                self.assertLessEqual(abs((1 - d) - x["cosine_similarity"]), 5.1e-5, r["question_id"])

    def test_phase5_top1_top5_and_expected_ranks_equal_recorded_independently(self):
        per = {p["id"]: p for p in DOC["per_query"]["phase5"]}
        self.assertEqual(len(per), 54)
        for r in P5["rows"]:
            p = per[r["id"]]
            self.assertEqual(p["top5"], [x["source_id"] for x in r["top5"]], r["id"])
            self.assertEqual(p["first_expected_rank"], r["first_expected_rank"], r["id"])
            for d, x in zip(p["top5_distances"], r["top5"]):
                self.assertLessEqual(abs((1 - d) - x["score"]), 5.1e-5, r["id"])

    def test_metrics_recomputed_from_committed_ranks_equal_recorded(self):
        for name, rec, n in (("phase4", P4["metrics"]["overall"], 50), ("phase5", P5["summary"]["overall"], 54)):
            frs = [p["first_expected_rank"] for p in DOC["per_query"][name]]
            self.assertEqual(len(frs), n)
            self.assertEqual(round(sum(1 for f in frs if f == 1) / n, 4), round(rec["recall@1"], 4))
            self.assertEqual(round(sum(1 for f in frs if f and f <= 3) / n, 4), round(rec["recall@3"], 4))
            self.assertEqual(round(sum(1 for f in frs if f and f <= 5) / n, 4), round(rec["recall@5"], 4))
            self.assertEqual(round(sum(1 / f for f in frs if f) / n, 4), round(rec["mrr"], 4))
            m = DOC["router_regression"][name]
            self.assertTrue(m["metrics_equal_to_recorded"])
            self.assertTrue(m["by_type_equal_to_recorded"])
            self.assertEqual(m["differing_queries"], [])

    def test_headline_metrics_are_the_spec_values(self):
        m4 = DOC["router_regression"]["phase4"]["router_metrics"]
        m5 = DOC["router_regression"]["phase5"]["router_metrics"]
        self.assertEqual((m4["recall@1"], m4["recall@3"], m4["recall@5"], m4["mrr"]), (0.92, 0.96, 1.0, 0.95))
        self.assertEqual((m5["recall@1"], m5["recall@3"], m5["recall@5"], m5["mrr"]), (0.7222, 0.7963, 0.8704, 0.7873))

    def test_comparison_counters_are_complete(self):
        for name, n in (("phase4", 50), ("phase5", 54)):
            c = DOC["router_regression"][name]["comparison_with_recorded"]
            for k in ("top1_identical", "top5_ordering_identical", "expected_rank_identical", "first_expected_rank_identical",
                      "default_path_equals_prefix_of_full_ranking"):
                self.assertEqual(c[k], n, (name, k))
            self.assertEqual(c["similarity_mismatches_after_4dp"], 0)

    def test_near_ties_cross_checked_against_the_independent_7b_validation(self):
        v = load(ROOT / "data" / "phase7B_validation.json")["stages"]["router"]["datasets"]
        for name in ("phase4", "phase5"):
            gaps7b = {p["id"]: round(p["top5_distances"][1] - p["top5_distances"][0], 6) for p in v[name]["per_query"]}
            for p in DOC["per_query"][name]:
                self.assertAlmostEqual(p["gap_rank1_rank2"], gaps7b[p["id"]], places=5, msg=p["id"])
        cum = {k: sum(DOC["routing_layers"][n]["near_ties_cumulative"][k]["queries"] for n in ("phase4", "phase5")) for k in ("gap<0.01", "gap<0.05")}
        self.assertEqual(cum, {"gap<0.01": 15, "gap<0.05": 45})   # the 7B figures
        wrong = {k: sum(DOC["routing_layers"][n]["near_ties_cumulative"][k]["rank1_not_expected"] for n in ("phase4", "phase5")) for k in cum}
        self.assertEqual(wrong, {"gap<0.01": 10, "gap<0.05": 16})

    def test_rank_one_is_not_availability(self):
        for name, hits in (("phase4", 46), ("phase5", 39)):
            l = DOC["routing_layers"][name]
            self.assertEqual(l["rank1_is_expected"], hits)
            self.assertEqual(l["rank1_is_expected_and_local_page_available"] + l["rank1_is_expected_but_no_local_page"], hits)
        self.assertEqual(DOC["routing_layers"]["phase4"]["rank1_is_expected_and_local_page_available"], 1)
        self.assertEqual(DOC["routing_layers"]["phase4"]["rank1_is_expected_but_no_local_page"], 45)
        self.assertEqual(DOC["routing_layers"]["phase5"]["rank1_is_expected_and_local_page_available"], 0)
        # every hit is an identified card, not a resolved page, except M2C-17
        for name in ("phase4", "phase5"):
            for p in DOC["per_query"][name]:
                if p["routing"]["route_state_7c"] != "resolved_local_page":
                    self.assertFalse(p["routing"]["page_content_available"], p["id"])
                    self.assertIsNotNone(p["routing"]["fallback_reason"], p["id"])

    def test_citation_layer_for_every_routed_query(self):
        for name in ("phase4", "phase5"):
            c = DOC["routing_layers"][name]["citation"]
            self.assertTrue(all(c.values()), (name, c))
            for p in DOC["per_query"][name]:
                self.assertEqual(p["citation"]["origin"], "card_route")
                self.assertTrue(p["citation"]["url_present"])
                self.assertIs(p["citation"]["used_as_answer_text"], False)

    def test_edge_cases(self):
        e = DOC["edge_cases"]
        f = lambda s: e[s]["forced"]
        self.assertEqual(f("M2C-05")["route_state_7c"], "corrected_identity")
        self.assertTrue(f("M2C-05")["citation"]["correction_present"])
        self.assertTrue(f("M2C-05")["has_source_correction"])
        self.assertFalse(f("M2C-05")["citation"]["review_flag"])
        for s in ("M2C-14", "M2C-23"):
            self.assertEqual(f(s)["route_state_7c"], "identified_not_local")
            self.assertTrue(f(s)["citation"]["review_flag"])
            self.assertEqual(f(s)["source_status"], "needs_review")
        self.assertEqual(f("M2C-18")["route_state_7c"], "conflicting_identity")
        self.assertIsNone(f("M2C-18")["effective_guide_id"])
        self.assertTrue(f("M2C-18")["citation"]["conflict_present"])
        self.assertFalse(f("M2C-18")["citation"]["probe_evidence_used_as_effective_guide"])
        self.assertTrue(f("M2C-18")["citation"]["review_flag"])
        for s in ("M2C-01", "M2C-13", "M2C-16"):
            self.assertEqual(f(s)["route_state_7c"], "card_identity_only")
            self.assertIsNone(f(s)["effective_guide_id"])
            self.assertFalse(f(s)["page_content_available"])
        self.assertEqual(f("M2C-17")["route_state_7c"], "resolved_local_page")
        self.assertTrue(f("M2C-17")["page_content_available"])
        self.assertTrue(f("M2C-17")["citation"]["local_content_is_legacy_copy"])
        self.assertIs(f("M2C-17")["citation"]["fresh_network_fetch_claimed"], False)
        self.assertEqual(f("M2C-07")["route_state_7c"], "identified_not_local")
        self.assertEqual(f("M2C-07")["join_state_7a"], "url_only")
        self.assertFalse(f("M2C-07")["page_content_available"])
        for s in e:
            if s != "no_card_candidate":
                self.assertTrue(f(s)["citation"]["url_byte_identical_to_card"], s)
                self.assertIs(f(s)["citation"]["used_as_answer_text"], False, s)
                self.assertIs(f(s)["citation"]["verified_used"], False, s)
        self.assertEqual(e["no_card_candidate"]["empty_query"], {"fallback_reason": "EMPTY_QUERY", "route_state_7c": "no_card_candidate", "sources": 0})
        self.assertEqual(e["no_card_candidate"]["selector_rejects_all"]["fallback_reason"], "SELECTOR_REJECTED_ALL_CANDIDATES")

    def test_forced_edge_cases_are_labelled_as_forced_and_keep_the_real_rank(self):
        for s, v in DOC["edge_cases"].items():
            if s == "no_card_candidate":
                continue
            self.assertIn("forced_on_query", v)
            self.assertGreaterEqual(v["forced"]["rank_of_card"], 1)
            self.assertIn("rank1_of_that_query", v["forced"])
        self.assertEqual(DOC["edge_cases"]["M2C-23"]["forced"]["rank_of_card"], 2)   # a card forced from rank 2 is visible as such

    def test_legacy_section_is_honest_about_what_was_not_run(self):
        l = DOC["legacy_regression"]
        self.assertFalse(l["mode_legacy"]["run_live"])
        self.assertFalse(l["mode_routed"]["implemented"])
        self.assertFalse(l["mode_routed"]["run_live"])
        r = l["mode_legacy"]["recorded_rescore"]
        self.assertEqual((r["loose_hits"], r["scored_questions"], r["out_of_domain_questions"]), ({"top1": 22, "top3": 24, "top5": 25}, 25, 5))
        self.assertEqual(r["stored_match_ranks_agree_with_rescoring"], 25)

    def test_legacy_overlay_keeps_urls_and_does_not_claim_correctness(self):
        o = DOC["legacy_regression"]["card_overlay"]
        self.assertEqual(o["questions"], 30)
        self.assertTrue(o["legacy_chunk_urls_unmodified_for_all"])
        self.assertNotIn("40374657", o["numeric_pairs_used_for_joins"])
        self.assertIn("not correctness", o["note"])
        self.assertEqual(sum(o["route_state_counts"].values()), 30)
        rows = DOC["legacy_per_question"]
        self.assertEqual(len(rows), 30)
        self.assertEqual(sum(1 for r in rows if not r["in_domain"]), 5)
        for r in rows:
            self.assertIs(r["card_route_used_as_text"], False)
            if r["legacy_top5_joined_to_routed_card_at_ranks"]:
                self.assertEqual(r["route_state_7c"], "resolved_local_page")   # only an effective identity can be joined

    def test_answerable_subset_is_too_small_and_routed_stays_off(self):
        a = DOC["answerable_subset"]
        self.assertEqual((a["topics_with_local_page_text"], a["count"], a["of"]), (["M2C-17"], 1, 29))
        self.assertFalse(a["subset_large_enough"])
        self.assertTrue(a["routed_mode_stays_off"])
        self.assertFalse(a["routed_mode_implemented"])
        self.assertFalse(a["page_level_labels_available"])

    def test_store_unchanged_by_the_evaluation_and_document_is_deterministic_text(self):
        self.assertEqual(DOC["store"]["before"], DOC["store"]["after"])
        self.assertEqual(DOC["store"]["after"]["collections"], ["sap_m2c_card_v1"])
        self.assertEqual(DOC["store"]["after"]["count"], 29)
        text = DOC_PATH.read_text(encoding="utf-8")
        for bad in ("/home/", "/tmp/", "created_utc", "C:\\"):
            self.assertNotIn(bad, text)
        self.assertEqual(text, ev.render_json(json.loads(text)))


# ------------------------------------------------------------------------------------------------ evaluator functions (no store)


class FunctionTests(unittest.TestCase):
    def test_first_rank_and_expected_ranks(self):
        self.assertEqual(ev.first_rank(["B", "C"], ["A", "C", "B"]), 2)
        self.assertIsNone(ev.first_rank(["Z"], ["A"]))
        self.assertEqual(ev.expected_ranks(["B", "Z"], ["A", "B"]), {"B": 2, "Z": None})

    def test_metrics_from(self):
        rows = [{"expected": ["A"], "ranking": ["A", "B"]}, {"expected": ["B"], "ranking": ["A", "C", "B"]}, {"expected": ["Z"], "ranking": ["A"]}]
        m = ev.metrics_from(rows)
        self.assertEqual((m["recall@1"], m["recall@3"], m["recall@5"]), (0.3333, 0.6667, 0.6667))
        self.assertEqual(m["mrr"], round((1 + 1 / 3) / 3, 4))
        self.assertEqual(m["hits@1"], 1)
        self.assertEqual(m["mean_expected_coverage@1"], 0.3333)

    def test_gap_and_tie_bins_are_descriptive(self):
        self.assertEqual(ev.gap12([0.3, 0.3001]), 0.0001)
        self.assertEqual(ev.tie_bin(0.0001), "gap<0.01")
        self.assertEqual(ev.tie_bin(0.02), "gap<0.05")
        self.assertEqual(ev.tie_bin(0.06), "gap>=0.05")
        self.assertEqual(ev.tie_bin(None), "no_rank2")
        self.assertEqual(ev.NEAR_TIE_BINS, (0.01, 0.05))   # the bins Phase 7B used; changing them is a decision, not a tuning step

    def test_legacy_matchers_follow_the_legacy_rules(self):
        self.assertTrue(ev.legacy_is_match("Contract Account Category", ["Contract Account"]))
        self.assertFalse(ev.legacy_is_strict("Contract Account Category", ["Contract Account"]))
        self.assertTrue(ev.legacy_is_strict(" contract account ", ["Contract Account"]))
        self.assertFalse(ev.legacy_is_match("x", []))

    def test_legacy_rescore_on_recorded_data(self):
        r = ev.legacy_rescore(load(ROOT / "data" / "evaluation_questions.json"), load(ROOT / "data" / "retrieval_results.json"))
        self.assertEqual((r["loose_hits"]["top1"], r["loose_hits"]["top3"], r["loose_hits"]["top5"]), (22, 24, 25))
        self.assertEqual(r["stored_match_ranks_agree_with_rescoring"], 25)

    def test_answerable_subset_from_the_real_repository(self):
        a = ev.answerable_subset(ctx(), {"phase4": {"per_query": []}, "phase5": {"per_query": []}}, [])
        self.assertEqual(a["topics_with_local_page_text"], ["M2C-17"])
        self.assertFalse(a["subset_large_enough"])

    def test_aggregate_layers_keeps_rank_and_availability_apart(self):
        def row(i, state, avail, exp, gap, review=False, r2=("identified_not_local", False, False)):
            return {"id": i, "rank1_is_expected": exp, "rank2_is_expected": not exp, "gap_rank1_rank2": gap, "near_tie_bin": ev.tie_bin(gap),
                    "rank1_distance": 0.4, "routing": {"route_state_7c": state, "page_content_available": avail, "card_needs_review": review},
                    "rank2_routing": {"route_state_7c": r2[0], "page_content_available": r2[1], "card_needs_review": r2[2]},
                    "citation": {"url_present": True, "url_byte_identical_to_card": True, "used_as_answer_text": False, "verified_used": False,
                                 "provided_as_context": False, "review_flag": review}}
        per = [row("a", "identified_not_local", False, True, 0.2), row("b", "resolved_local_page", True, True, 0.003, r2=("conflicting_identity", False, True)),
               row("c", "conflicting_identity", False, False, 0.004, review=True)]
        a = ev.aggregate_layers(per)
        self.assertEqual((a["rank1_is_expected"], a["rank1_is_expected_and_local_page_available"], a["rank1_is_expected_but_no_local_page"]), (2, 1, 1))
        self.assertEqual(a["near_ties_cumulative"]["gap<0.01"], {"queries": 2, "rank1_not_expected": 1})
        self.assertEqual(a["near_ties_below_first_bin_where_rank1_and_rank2_differ_in_routing_status"], ["b", "c"])
        self.assertEqual(a["routed_to_card_needing_review"], 1)
        self.assertTrue(all(a["citation"].values()))


class StubBackendTests(unittest.TestCase):
    """The evaluator's machinery with a deterministic stub: it must DETECT a difference from the recorded rankings."""

    def test_router_regression_detects_differences(self):
        data = ev.recorded_datasets()["phase4"]
        reg = ev.router_regression("phase4", data, StubBackend(), ctx())
        self.assertEqual(reg["queries"], 50)
        self.assertLess(reg["comparison_with_recorded"]["top5_ordering_identical"], 50)   # a stub is not the recorded router
        self.assertTrue(reg["differing_queries"])
        self.assertFalse(reg["metrics_equal_to_recorded"])
        self.assertEqual(reg["comparison_with_recorded"]["default_path_equals_prefix_of_full_ranking"], 50)   # the default path is a prefix of the full ranking
        for p in reg["per_query"]:
            self.assertIs(p["citation"]["used_as_answer_text"], False)
            self.assertTrue(p["citation"]["url_byte_identical_to_card"])

    def test_edge_cases_machinery(self):
        b = StubBackend()
        datasets = ev.recorded_datasets()
        regs = {n: ev.router_regression(n, d, b, ctx()) for n, d in datasets.items()}
        e = ev.edge_cases(datasets, regs, b, ctx())
        self.assertEqual(e["M2C-18"]["forced"]["route_state_7c"], "conflicting_identity")
        self.assertEqual(e["M2C-17"]["forced"]["route_state_7c"], "resolved_local_page")
        self.assertEqual(e["M2C-05"]["forced"]["route_state_7c"], "corrected_identity")
        self.assertEqual(e["no_card_candidate"]["empty_query"]["sources"], 0)

    def test_empty_query_does_not_call_the_backend(self):
        b = StubBackend()
        pid.route_to_identity("   ", b, ctx())
        self.assertEqual(b.calls, 0)

    def test_legacy_overlay_machinery(self):
        o = ev.legacy_overlay(load(ROOT / "data" / "evaluation_questions.json"), load(ROOT / "data" / "retrieval_results.json"), StubBackend(), ctx())
        self.assertEqual(o["questions"], 30)
        self.assertTrue(o["legacy_chunk_urls_unmodified_for_all"])
        for r in o["per_question"]:
            self.assertIs(r["card_route_used_as_text"], False)


# ------------------------------------------------------------------------------------------------ scope / protection


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse((SCRIPTS / "evaluate_two_stage.py").read_text(encoding="utf-8"))
        self.imports = set()
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Import):
                self.imports |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                self.imports.add(n.module)

    def test_no_network_llm_or_legacy_imports(self):
        banned = {"urllib.request", "urllib.error", "http.client", "requests", "httpx", "aiohttp", "ollama", "openai", "anthropic",
                  "rag_core", "rag_chat", "retrieve", "evaluate_retrieval", "create_embeddings", "build_card_collection", "sap_resolver"}
        self.assertFalse(self.imports & banned, self.imports & banned)

    def test_no_collection_mutation_calls(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        names = {n.func.attr for n in calls}
        self.assertFalse(names & {"add", "upsert", "delete", "modify", "create_collection", "get_or_create_collection", "delete_collection"}, names)
        # the only .update() is the hashlib object of the read-only store snapshot
        self.assertEqual({n.func.value.id for n in calls if n.func.attr == "update" and isinstance(n.func.value, ast.Name)}, {"h"})

    def test_no_threshold_or_retrieval_parameters_in_the_evaluator(self):
        text = (SCRIPTS / "evaluate_two_stage.py").read_text(encoding="utf-8")
        for token in ("min_cosine", "MAX_DISTANCE =", "CANDIDATE_K =", "rerank", "bm25", "hybrid"):
            self.assertNotIn(token, text.replace("hybrid retrieval", ""), token)

    def test_phase_7a_to_7d_and_evaluation_inputs_unchanged(self):
        for rel, h in PINNED.items():
            self.assertEqual(sha(rel), h, rel)

    def test_legacy_and_production_files_do_not_reference_7e(self):
        for rel in ("scripts/rag_core.py", "scripts/rag_chat.py", "scripts/retrieve.py", "scripts/evaluate_retrieval.py", "scripts/create_embeddings.py"):
            t = (ROOT / rel).read_text(encoding="utf-8")
            for token in ("evaluate_two_stage", "m2c_citations", "m2c_router", "m2c_orchestrator", "m2c_page_identity"):
                self.assertNotIn(token, t, (rel, token))

    def test_no_card_or_legacy_store_created_by_this_phase(self):
        self.assertFalse((ROOT / "chroma_db").exists())

    def test_evaluator_has_no_answer_generation(self):
        text = (SCRIPTS / "evaluate_two_stage.py").read_text(encoding="utf-8")
        for token in ("generate_answer", "build_prompt", "temperature", "LLM_OPTIONS", "import ollama"):
            self.assertNotIn(token, text, token)

    def test_subprocess_import_loads_no_llm_or_legacy_module(self):
        code = ("import sys; sys.path.insert(0, 'scripts'); import evaluate_two_stage; "
                "bad=[m for m in ('ollama','rag_core','rag_chat','retrieve','evaluate_retrieval','create_embeddings','requests','chromadb','sentence_transformers') if m in sys.modules]; "
                "print(bad)")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "[]")


# ------------------------------------------------------------------------------------------------ real store, real model


@unittest.skipUnless(LIVE, SKIP_MSG)
class LiveEvaluationTests(unittest.TestCase):
    def test_fresh_process_reproduces_the_committed_document_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "e.json"
            r = subprocess.run([sys.executable, str(SCRIPTS / "evaluate_two_stage.py"), "--out", str(out)], capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(out.read_bytes(), DOC_PATH.read_bytes())

    def test_real_router_reproduces_recorded_rankings_on_a_sample(self):
        import m2c_router as rt
        backend = rt.ChromaCardBackend(vector_dir=VECTOR)
        for r in P4["per_question"][:10]:
            got = [c.source_id for c in rt.route(r["question"], backend, top_k=5).candidates]
            self.assertEqual(got, [x["source_id"] for x in r["retrieved_top5"]], r["question_id"])


if __name__ == "__main__":
    unittest.main()
