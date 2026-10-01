"""Phase 7F - out-of-domain evidence for the card router (spec section 5, step 7F).

Most tests need no store: they check the labelled query set, the committed results document, the statistics functions, the
caller-side selector semantics and the scope rules. One store-gated test re-runs the evaluation in a fresh process against the
real store and real model and requires a byte-identical results file (skipped, with a reason, when they are missing).
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
import math
import re
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

eo = importlib.import_module("evaluate_ood")
rt = importlib.import_module("m2c_router")
orch = importlib.import_module("m2c_orchestrator")

EVAL = ROOT / "data" / "evaluation"
QPATH = EVAL / "phase7F_ood_queries.json"
RPATH = EVAL / "phase7F_results.json"
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


Q = load(QPATH)
R = load(RPATH)
QS = Q["queries"]
UNITS = {u["source_id"]: u for u in load(C.UNITS_PATH)["units"]}
P4 = load(EVAL / "card_retrieval_results.json")
P5 = load(EVAL / "phase5_results.json")["datasets"]["phase5"]["systems"]["dense"]
P4_QUERIES = {r["question"].strip().lower() for r in P4["per_question"]}
P5_QUERIES = {q["query"].strip().lower() for q in load(EVAL / "independent_queries.json")["queries"]}

QUERIES_SHA256 = "631c7a524edecb5f78205334dd86256638fe1473998e86e7926ec619801dbe14"
ROUTER_PINS = {   # the router and the 7A-7D implementation must be untouched by 7F
    "scripts/m2c_router.py": "b846f18d098406c17859d053ae5b9c0ddb5b82e247e92ac709edeed1113ea8f4",
    "scripts/m2c_page_join.py": "a7744701a710df9575eea3861a61204ee63deb995f761cc715dcd150b6dee156",
    "scripts/m2c_orchestrator.py": "89bcfcc1c57669f492d92d12e2f720b2e9d9b36035c678737db4d081213782dd",
    "scripts/m2c_page_identity.py": "877b4f52d841bf475b149d9bcb601ad858b97bf2c6d3059ad5fbd5abe2c96163",
    "scripts/m2c_citations.py": "379fc6b89c587df227fa23e4053c8d4927b5902cf4484c61c0080abf3fdd4fb9",
    "data/card_collection_manifest.json": "5b3a5c30bc637c8b61573983a16cf252f7899d2c279eae3895e06476482d2731",
    "data/evaluation/card_retrieval_questions.json": "530f2d96cb644518fcbe20b0082870b01a08fd4bc524c10d208fd9c72c1ceb36",
    "data/evaluation/independent_queries.json": "1ce1306db646981b68245d75a1a912310ad3d760d90593bd005dfcc3500956e4",
    "data/evaluation_questions.json": "dc0801cce3ec63e176062ea46914500169b5cfd8c8a1f2991b060edb3108a674",
}


def words(s):
    return re.findall(r"[a-z0-9\-]+", s.lower())


def longest_shared_run(a, b):
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


class FixedBackend:
    """Backend with caller-chosen cosine distances (ascending), over the 29 real card metadata records."""
    distance_metric = "cosine"

    def __init__(self, distances=None, salt=""):
        bcc = importlib.import_module("build_card_collection")
        self.meta = {s: bcc.metadata_for(u) for s, u in UNITS.items()}
        self.distances = distances
        self.salt = salt

    def query(self, query, n_results):
        ids = sorted(self.meta, key=lambda i: (zlib.crc32((self.salt + query + i).encode()), i))[:n_results]
        d = self.distances or [0.3 + 0.01 * k for k in range(len(ids))]
        return {"ids": [ids], "metadatas": [[self.meta[i] for i in ids]], "distances": [list(d[:len(ids)])]}


# ------------------------------------------------------------------------------------------------ query set validity


class QuerySetTests(unittest.TestCase):
    def test_file_is_pinned(self):
        self.assertEqual(sha("data/evaluation/phase7F_ood_queries.json"), QUERIES_SHA256, "the labelled set changed after evaluation")
        self.assertEqual(R["inputs"]["queries_file_sha256"], QUERIES_SHA256)

    def test_counts_and_header_agree(self):
        by = {}
        for q in QS:
            by[q["label"]] = by.get(q["label"], 0) + 1
        self.assertEqual(by, {"in_domain": 40, "out_of_domain": 62, "ambiguous_excluded": 8})
        self.assertEqual(Q["counts"], by)
        self.assertGreaterEqual(by["in_domain"], 30)
        self.assertGreaterEqual(by["out_of_domain"], 50)

    def test_ids_and_queries_unique_and_well_formed(self):
        ids = [q["id"] for q in QS]
        self.assertEqual(len(ids), len(set(ids)))
        texts = [q["query"].strip().lower() for q in QS]
        self.assertEqual(len(texts), len(set(texts)))
        for q in QS:
            self.assertRegex(q["id"], r"^7F-[IOA]\d\d$")
            self.assertTrue(q["query"].strip())
            self.assertEqual({"I": "in_domain", "O": "out_of_domain", "A": "ambiguous_excluded"}[q["id"][3]], q["label"], q["id"])

    def test_every_in_domain_query_has_expected_cards_and_quoted_evidence(self):
        for q in QS:
            if q["label"] != "in_domain":
                continue
            self.assertTrue(q["expected_source_ids"], q["id"])
            self.assertTrue(set(q["expected_source_ids"]) <= set(UNITS), q["id"])
            self.assertTrue(q["evidence_basis"], q["id"])
            basis = {e["source_id"] for e in q["evidence_basis"]}
            self.assertTrue(set(q["expected_source_ids"]) <= basis, q["id"])
            for e in q["evidence_basis"]:
                self.assertIn(e["what_it_covers"], UNITS[e["source_id"]]["embedding_text"], f"{q['id']}: evidence is not a quote of the card text")

    def test_ood_and_ambiguous_have_no_expected_card_and_ood_has_a_category(self):
        cats = {}
        for q in QS:
            if q["label"] == "in_domain":
                continue
            self.assertEqual(q["expected_source_ids"] if "expected_source_ids" in q else [], [], q["id"])
            if q["label"] == "out_of_domain":
                self.assertTrue(q["category"], q["id"])
                cats[q["category"]] = cats.get(q["category"], 0) + 1
        self.assertEqual(set(cats), {"unrelated_general", "other_software_it", "sap_other_modules", "utilities_adjacent_not_covered", "lexical_overlap_trap", "very_short_unrelated"})
        self.assertTrue(all(n >= 6 for n in cats.values()), cats)

    def test_no_overlap_with_phase4_phase5_queries(self):
        for q in QS:
            self.assertNotIn(q["query"].strip().lower(), P4_QUERIES | P5_QUERIES, q["id"])

    def test_in_domain_queries_do_not_copy_card_text(self):
        card_words = [words(u["embedding_text"]) for u in UNITS.values()]
        for q in QS:
            if q["label"] == "in_domain":
                qw = words(q["query"])
                worst = max(longest_shared_run(qw, cw) for cw in card_words)
                self.assertLessEqual(worst, 3, f"{q['id']} shares {worst} contiguous words with a card")

    def test_authorship_disclosure_is_truthful(self):
        a = Q["authorship"]
        text = json.dumps(a).lower()
        self.assertIn("ai coding agent", text)
        self.assertIn("not human-written", text)
        self.assertIn("cannot be made", text)         # the 'not LLM-generated' claim is explicitly withdrawn
        self.assertIn("before any of its queries was embedded or routed", text)
        self.assertEqual(a["labels_changed_after_retrieval"].split(";")[0], "never")
        self.assertTrue(Q["labelling_criteria"])

    def test_decision_rule_text_matches_the_evaluator_constants(self):
        text = json.dumps(Q["decision_rule"])
        for token in ("100", "50", "25", "0.90", "0.05", "0.20", "0.10", "0.25", "inclusive"):
            self.assertIn(token, text, token)
        self.assertEqual(eo.RULE, {"min_in_domain": 100, "min_ood": 50, "min_ood_per_split": 25, "auroc_min": 0.90, "pooled_max_fn": 0.05,
                                   "pooled_max_fp": 0.20, "dev_max_fn": 0.05, "test_max_fn": 0.10, "test_max_fp": 0.25})


# ------------------------------------------------------------------------------------------------ results document integrity


class ResultsDocumentTests(unittest.TestCase):
    def test_checks_ok_and_scope(self):
        self.assertTrue(R["ok"])
        self.assertTrue(all(c["ok"] for c in R["checks"]), [c["check"] for c in R["checks"] if not c["ok"]])
        s = R["scope"]
        self.assertFalse(s["retrieval_changed"])
        self.assertFalse(s["router_modified"])
        self.assertFalse(s["answer_generated"])
        self.assertFalse(s["pages_fetched_or_ingested"])
        self.assertFalse(s["threshold_enabled_in_router"])
        self.assertIsNone(s["default_min_cosine"])
        self.assertEqual(R["isolation"], {"network_attempts": 0, "banned_modules_loaded": []})

    def test_counts(self):
        self.assertEqual(R["counts"], {"phase4": 50, "phase5": 54, "7f_in_domain": 40, "7f_ood": 62, "7f_ambiguous": 8, "legacy_ood": 5})
        self.assertEqual(len(R["per_query"]), 219)

    def test_labels_are_exactly_those_of_the_locked_file_and_of_phase4_5(self):
        label = {q["id"]: (q["label"], q["query"], q["expected_source_ids"]) for q in QS}
        for r in R["per_query"]:
            if r["group"].startswith("7f"):
                self.assertEqual((r["label"], r["query"], r["expected_source_ids"]), label[r["id"]], r["id"])
        p4 = {x["question_id"]: x for x in P4["per_question"]}
        for r in R["per_query"]:
            if r["group"] == "phase4":
                self.assertEqual(r["label"], "in_domain")
                self.assertEqual(r["expected_source_ids"], p4[r["id"]]["expected_source_ids"])
        legacy = {q["id"]: q for q in load(ROOT / "data" / "evaluation_questions.json")}
        for r in R["per_query"]:
            if r["group"] == "legacy_ood":
                self.assertEqual(r["query"], legacy[r["id"]]["question"])
                self.assertEqual(legacy[r["id"]]["expected_titles"], [])
        self.assertEqual({r["id"] for r in R["per_query"] if r["group"] == "legacy_ood"}, {"q26", "q27", "q28", "q29", "q30"})

    def test_similarity_and_distance_are_separate_and_consistent(self):
        for r in R["per_query"]:
            self.assertAlmostEqual(r["rank1_cosine_similarity"], 1 - r["rank1_cosine_distance"], delta=2e-6, msg=r["id"])
            self.assertAlmostEqual(r["rank2_cosine_similarity"], 1 - r["rank2_cosine_distance"], delta=2e-6, msg=r["id"])
            self.assertLessEqual(r["rank1_cosine_distance"], r["rank2_cosine_distance"], r["id"])
            self.assertAlmostEqual(r["gap_cosine_distance_rank1_rank2"], r["rank2_cosine_distance"] - r["rank1_cosine_distance"], delta=2e-6, msg=r["id"])
            self.assertIn("rank1_cosine_similarity", r)
            self.assertIn("rank1_cosine_distance", r)
            self.assertNotIn("distance", r)             # no ambiguous field name

    def test_correctness_flag_matches_expected_cards(self):
        for r in R["per_query"]:
            if r["expected_source_ids"]:
                self.assertEqual(r["rank1_is_correct"], r["rank1_source_id"] in r["expected_source_ids"], r["id"])
            else:
                self.assertIsNone(r["rank1_is_correct"])

    def test_phase4_phase5_scores_equal_recorded_data(self):
        p4 = {x["question_id"]: x for x in P4["per_question"]}
        for r in R["per_query"]:
            if r["group"] == "phase4":
                rec = p4[r["id"]]["retrieved_top5"][0]
                self.assertEqual(r["rank1_source_id"], rec["source_id"])
                self.assertAlmostEqual(r["rank1_cosine_similarity"], rec["cosine_similarity"], delta=5.1e-5, msg=r["id"])

    def test_split_rule_reproduced_independently(self):
        for label in ("in_domain", "out_of_domain"):
            order = {"phase4": 0, "phase5": 1, "7f_in_domain": 2, "7f_ood": 2}
            rows = sorted([r for r in R["per_query"] if r["label"] == label], key=lambda r: (order[r["group"]], r["id"]))
            for i, r in enumerate(rows):
                self.assertEqual(r["split"], "dev" if i % 2 == 0 else "test", r["id"])
        for r in R["per_query"]:
            if r["label"] not in ("in_domain", "out_of_domain"):
                self.assertIsNone(r["split"])

    def test_verdict_is_reproducible_from_the_rows_and_no_threshold_is_justified(self):
        v = eo.decide(R["per_query"])
        self.assertEqual(json.loads(json.dumps(v)), R["verdict"])
        self.assertFalse(R["verdict"]["threshold_justified"])
        self.assertIsNone(R["verdict"]["min_cosine"])
        self.assertIsNone(R["verdict"]["proposed_min_cosine"])
        self.assertTrue(R["verdict"]["C1_sample_adequacy"]["pass"])
        self.assertFalse(R["verdict"]["C2_separation_pooled"]["pass"])
        self.assertFalse(R["verdict"]["C3_held_out"]["pass"])

    def test_distribution_figures_are_reproducible_from_the_rows(self):
        D = R["distributions"]
        s_in = sorted(r["rank1_cosine_similarity"] for r in R["per_query"] if r["label"] == "in_domain")
        s_ood = sorted(r["rank1_cosine_similarity"] for r in R["per_query"] if r["label"] == "out_of_domain")
        self.assertEqual((len(s_in), len(s_ood)), (D["in_domain_n"], D["ood_n"]))
        self.assertEqual(D["in_domain_all"]["min"], s_in[0])
        self.assertEqual(D["in_domain_all"]["max"], s_in[-1])
        self.assertEqual(D["out_of_domain_all"]["max"], s_ood[-1])
        self.assertEqual(D["overlap"]["clean_gap_exists"], s_ood[-1] < s_in[0])
        self.assertFalse(D["overlap"]["clean_gap_exists"])
        self.assertEqual(D["overlap"]["ood_scores_at_or_above_min_in_domain"], sum(1 for s in s_ood if s >= s_in[0]))
        self.assertEqual(D["auroc_in_vs_ood_rank1_similarity"], round(eo.auroc(s_in, s_ood), 4))

    def test_grid_is_fixed_and_unchanged_by_results(self):
        self.assertEqual(eo.GRID, tuple(round(0.10 + 0.05 * i, 2) for i in range(13)))
        self.assertEqual([g["t"] for g in R["grid_what_if_refused_counts"]], list(eo.GRID))
        counts = [g["phase4"]["refused"] for g in R["grid_what_if_refused_counts"]]
        self.assertEqual(counts, sorted(counts))            # refusals are monotone in t

    def test_regression_block_reports_no_change_and_no_refusal(self):
        for g in ("phase4", "phase5"):
            x = R["regression"][g]
            self.assertEqual(x["rank1_equals_7e"], x["queries"])
            self.assertEqual(x["top5_equals_7e"], x["queries"])
            self.assertEqual(x["first_expected_rank_equals_7e"], x["queries"])
            self.assertEqual(x["rank1_distance_equals_7e_to_6dp"], x["queries"])
            self.assertTrue(x["metrics_equal_7e"])
            self.assertEqual(x["refused_with_default_selector"], 0)
            self.assertNotIn("with_proposed_threshold", x)
        self.assertEqual(R["regression"]["phase4"]["metrics"]["recall@1"], 0.92)
        self.assertEqual(R["regression"]["phase4"]["metrics"]["recall@5"], 1.0)
        self.assertEqual(R["regression"]["phase5"]["metrics"]["hits@1"], 39)

    def test_legacy_five_all_still_return_a_card(self):
        rows = {r["id"]: r for r in R["per_query"] if r["group"] == "legacy_ood"}
        self.assertEqual({k: r["rank1_cosine_distance"] for k, r in rows.items()},
                         {"q26": 0.598722, "q27": 0.58626, "q28": 0.917152, "q29": 0.930419, "q30": 0.958423})
        for r in rows.values():
            self.assertTrue(r["rank1_source_id"].startswith("M2C-"))


# ------------------------------------------------------------------------------------------------ statistics


class StatisticsTests(unittest.TestCase):
    def test_similarity_distance_conversion(self):
        self.assertEqual(eo.similarity(0.0), 1.0)
        self.assertEqual(eo.similarity(1.0), 0.0)
        self.assertAlmostEqual(eo.similarity(0.598722), 0.401278, places=9)
        self.assertAlmostEqual(eo.similarity(1.2), -0.2, places=9)       # cosine distance can exceed 1

    def test_score_extraction_from_router(self):
        be = FixedBackend(distances=[0.25 + 0.05 * k for k in range(29)])
        rows = eo.route_rows([{"id": "x", "group": "7f_ood", "label": "out_of_domain", "category": "c", "query": "anything", "expected": [], "split": "dev"}], be)
        r = rows[0]
        self.assertEqual(r["rank1_cosine_distance"], 0.25)
        self.assertEqual(r["rank1_cosine_similarity"], 0.75)
        self.assertEqual(r["rank2_cosine_distance"], 0.3)
        self.assertEqual(r["rank2_cosine_similarity"], 0.7)
        self.assertEqual(r["gap_cosine_distance_rank1_rank2"], 0.05)
        self.assertEqual(len(r["_ranking"]), 29)
        self.assertIsNone(r["rank1_is_correct"])
        rows = eo.route_rows([{"id": "y", "group": "phase4", "label": "in_domain", "category": "c", "query": "anything", "expected": [r["rank1_source_id"]], "split": "test"}], be)
        self.assertTrue(rows[0]["rank1_is_correct"])
        self.assertEqual(rows[0]["first_expected_rank"], 1)

    def test_percentile_describe(self):
        v = [0.0, 1.0, 2.0, 3.0, 4.0]
        self.assertEqual(eo.percentile(v, 50), 2.0)
        self.assertEqual(eo.percentile(v, 25), 1.0)
        self.assertEqual(eo.percentile(v, 90), 3.6)
        d = eo.describe([3, 1, 2])
        self.assertEqual((d["n"], d["min"], d["max"], d["median"], d["mean"]), (3, 1, 3, 2, 2))
        self.assertEqual(eo.describe([])["n"], 0)

    def test_auroc_known_values(self):
        self.assertEqual(eo.auroc([3, 4], [1, 2]), 1.0)
        self.assertEqual(eo.auroc([1, 2], [3, 4]), 0.0)
        self.assertEqual(eo.auroc([1, 1], [1, 1]), 0.5)
        self.assertEqual(eo.auroc([1, 3], [2]), 0.5)
        self.assertIsNone(eo.auroc([], [1]))

    def test_wilson_interval(self):
        lo, hi = eo.wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=3)
        lo, hi = eo.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)
        self.assertIsNone(eo.wilson(0, 0))

    def test_rates_are_inclusive_at_the_boundary(self):
        r = eo.rates_at(0.5, [0.5, 0.6, 0.4], [0.5, 0.2])
        self.assertEqual(r["in_domain_refused"], 1)      # 0.4 < 0.5 refused, 0.5 accepted
        self.assertEqual(r["ood_accepted"], 1)           # 0.5 >= 0.5 accepted, 0.2 refused

    def test_candidate_thresholds_are_midpoints_of_distinct_scores(self):
        self.assertEqual(eo.candidate_thresholds([0.1, 0.1, 0.3, 0.7]), [0.2, 0.5])
        self.assertEqual(eo.candidate_thresholds([0.2, 0.2]), [])

    def test_select_on_dev_follows_the_declared_rule(self):
        in_s = [0.5 + 0.01 * i for i in range(20)]       # 0.50 .. 0.69
        ood = [0.1, 0.2, 0.3, 0.55]                      # one overlaps
        sel = eo.select_on_dev(in_s, ood)
        self.assertLessEqual(sel["in_domain_refusal_rate"], 0.05)
        self.assertEqual(sel["ood_accepted"], 1)
        # ties -> lowest t: every threshold between 0.3 and 0.5 gives the same counts; the lowest such midpoint is (0.3+0.5)/2
        self.assertAlmostEqual(sel["t"], 0.4, places=6)

    def test_select_on_dev_none_when_refusal_limit_unreachable(self):
        self.assertIsNone(eo.select_on_dev([0.5, 0.5], [0.5]))      # no midpoint at all

    def test_decide_justifies_only_clean_large_separation(self):
        def rows(n_in, n_ood, in_lo, in_hi, ood_lo, ood_hi):
            out = []
            for i in range(n_in):
                out.append({"label": "in_domain", "split": "dev" if i % 2 == 0 else "test", "rank1_cosine_similarity": in_lo + (in_hi - in_lo) * i / (n_in - 1)})
            for i in range(n_ood):
                out.append({"label": "out_of_domain", "split": "dev" if i % 2 == 0 else "test", "rank1_cosine_similarity": ood_lo + (ood_hi - ood_lo) * i / (n_ood - 1)})
            return out
        sep = eo.decide(rows(120, 60, 0.4, 0.7, -0.1, 0.3))
        self.assertTrue(sep["threshold_justified"])
        self.assertTrue(0.3 < sep["min_cosine"] < 0.4)
        lap = eo.decide(rows(120, 60, 0.2, 0.7, -0.1, 0.5))
        self.assertFalse(lap["threshold_justified"])
        self.assertIsNone(lap["min_cosine"])
        small = eo.decide(rows(120, 20, 0.4, 0.7, -0.1, 0.3))       # separated but too few OOD queries
        self.assertFalse(small["C1_sample_adequacy"]["pass"])
        self.assertFalse(small["threshold_justified"])
        self.assertIsNone(small["min_cosine"])


# ------------------------------------------------------------------------------------------------ selector (caller side, default off)


class SelectorTests(unittest.TestCase):
    def cands(self, distances):
        return rt.route("q", FixedBackend(distances=distances), top_k=len(distances)).candidates

    def test_default_is_none_and_selects_rank_one(self):
        self.assertIsNone(eo.DEFAULT_MIN_COSINE)
        c = self.cands([0.95, 0.96])
        self.assertIs(eo.make_selector()(c), c[0])
        self.assertIs(eo.make_selector(None), orch.select_top_ranked)

    def test_threshold_applies_to_similarity_inclusively(self):
        c = self.cands([0.60, 0.70])          # rank-1 similarity 0.40
        self.assertIs(eo.make_selector(0.40)(c), c[0])     # equal -> accepted
        self.assertIs(eo.make_selector(0.399999)(c), c[0])
        self.assertIsNone(eo.make_selector(0.400001)(c))   # just above -> refused
        self.assertIsNone(eo.make_selector(0.6)(c))

    def test_distance_is_not_the_compared_quantity(self):
        c = self.cands([0.10, 0.20])                       # distance 0.10 -> similarity 0.90
        self.assertIs(eo.make_selector(0.8)(c), c[0])      # comparing the distance (0.10 < 0.8) would wrongly refuse
        self.assertIsNone(eo.make_selector(0.95)(c))       # similarity 0.90 < 0.95
        c = self.cands([0.90, 0.95])                       # distance 0.90 -> similarity 0.10
        self.assertIsNone(eo.make_selector(0.2)(c))        # comparing the distance (0.90 >= 0.2) would wrongly accept

    def test_selector_never_reorders_or_filters(self):
        c = self.cands([0.2 + 0.01 * k for k in range(29)])
        before = [x.source_id for x in c]
        eo.make_selector(0.99)(c)
        self.assertEqual([x.source_id for x in c], before)
        self.assertIsNone(eo.make_selector(0.5)([]))

    def test_validation_rejects_distances_and_junk(self):
        for bad in (1.5, -1.5, float("nan"), float("inf"), True, "0.3"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                eo.validate_min_cosine(bad)
        for ok in (None, 0, 0.0, 0.3, -0.2, 1, 1.0):
            eo.validate_min_cosine(ok)

    def test_no_threshold_behaviour_is_the_router_default(self):
        be = FixedBackend(distances=[0.99 + 0.0001 * k for k in range(29)])
        res = rt.route("irrelevant question", be, top_k=29)
        self.assertEqual(len(res.candidates), 29)               # even a very far card is returned: the router has no cut-off
        self.assertAlmostEqual(res.candidates[0].distance, 0.99)

    def test_selector_can_be_plugged_into_the_orchestrator(self):
        import inspect
        self.assertIn("selector", inspect.signature(orch.route_to_page).parameters)


# ------------------------------------------------------------------------------------------------ regression and scope rules


class RegressionAndScopeTests(unittest.TestCase):
    def test_router_and_earlier_phases_are_untouched(self):
        for rel, h in ROUTER_PINS.items():
            self.assertEqual(sha(rel), h, rel)

    @staticmethod
    def _code_names(path):
        """Identifiers, attributes, argument names and string constants used as code (docstrings are excluded)."""
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        doc_nodes = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                    and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                doc_nodes.add(id(n.body[0].value))
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.Attribute):
                names.add(n.attr)
            elif isinstance(n, ast.arg):
                names.add(n.arg)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_nodes:
                names.add(n.value)
        return names

    def test_router_has_no_threshold_parameter_or_distance_cutoff(self):
        names = self._code_names(SCRIPTS / "m2c_router.py")
        for token in ("min_cosine", "MAX_DISTANCE", "max_distance", "min_similarity", "threshold"):
            self.assertNotIn(token, names, token)
        import inspect
        self.assertEqual(list(inspect.signature(rt.route).parameters), ["query", "backend", "top_k"])

    def test_legacy_max_distance_is_not_used_by_7f(self):
        names = self._code_names(SCRIPTS / "evaluate_ood.py")
        self.assertNotIn("MAX_DISTANCE", names)
        self.assertFalse(hasattr(eo, "MAX_DISTANCE"))
        self.assertFalse(hasattr(rt, "MAX_DISTANCE"))
        self.assertFalse(hasattr(orch, "MAX_DISTANCE"))

    def test_rag_chat_and_cli_have_no_card_threshold_or_routed_mode(self):
        for rel in ("scripts/rag_chat.py", "scripts/rag_core.py"):
            p = ROOT / rel
            if p.is_file():
                text = p.read_text(encoding="utf-8")
                self.assertNotIn("min_cosine", text, rel)
                self.assertNotIn("m2c_router", text, rel)
        self.assertFalse((SCRIPTS / "rag_two_stage.py").exists())

    def test_no_network_llm_or_generation_in_the_evaluator(self):
        tree = ast.parse((SCRIPTS / "evaluate_ood.py").read_text(encoding="utf-8"))
        banned = {"requests", "socket", "ollama", "http", "rag_core", "rag_chat", "retrieve", "create_embeddings"}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.assertNotIn(a.name.split(".")[0], banned, a.name)
            if isinstance(n, ast.ImportFrom):
                self.assertNotIn((n.module or "").split(".")[0], banned, n.module)
                self.assertNotIn(n.module, ("urllib.request", "urllib.error", "http.client"))
        text = (SCRIPTS / "evaluate_ood.py").read_text(encoding="utf-8")
        for token in ("generate_answer", "build_prompt", "import ollama", "temperature"):
            self.assertNotIn(token, text, token)

    def test_evaluator_does_not_write_the_collection(self):
        text = (SCRIPTS / "evaluate_ood.py").read_text(encoding="utf-8")
        for token in (".add(", ".upsert(", "delete_collection", "create_collection", "get_or_create_collection", ".delete("):
            self.assertNotIn(token, text, token)

    def test_subprocess_import_loads_no_llm_or_legacy_module(self):
        code = ("import sys; sys.path.insert(0, 'scripts'); import evaluate_ood; "
                "bad=[m for m in ('ollama','rag_core','rag_chat','retrieve','evaluate_retrieval','create_embeddings','requests','chromadb','sentence_transformers') if m in sys.modules]; print(bad)")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "[]")


# ------------------------------------------------------------------------------------------------ determinism


class DeterminismTests(unittest.TestCase):
    def test_repeated_stub_evaluation_is_byte_identical(self):
        a = eo.render_json(eo.evaluate(backend=FixedBackend(salt="a"), snapshot=False))
        b = eo.render_json(eo.evaluate(backend=FixedBackend(salt="a"), snapshot=False))
        self.assertEqual(a, b)
        self.assertNotEqual(a, eo.render_json(eo.evaluate(backend=FixedBackend(salt="b"), snapshot=False)))

    def test_stub_evaluation_flags_the_regression_check_when_rankings_differ(self):
        doc = eo.evaluate(backend=FixedBackend(), snapshot=False)
        self.assertFalse(doc["ok"])            # a stub cannot reproduce the recorded Phase 4/5 rankings, and the checks say so
        self.assertIsNone(doc["verdict"]["min_cosine"])


# ------------------------------------------------------------------------------------------------ real store, real model


@unittest.skipUnless(LIVE, SKIP_MSG)
class LiveEvaluationTests(unittest.TestCase):
    def test_fresh_process_reproduces_the_committed_results_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "r.json"
            r = subprocess.run([sys.executable, str(SCRIPTS / "evaluate_ood.py"), "--out", str(out)], capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(out.read_bytes(), RPATH.read_bytes())

    def test_real_router_scores_match_the_results_on_a_sample(self):
        backend = rt.ChromaCardBackend(vector_dir=VECTOR)
        rows = {r["id"]: r for r in R["per_query"]}
        for qid in ("7F-I01", "7F-O26", "7F-O05", "q26", "q30", "Q01", "P5-24"):
            r = rows[qid]
            c = rt.route(r["query"], backend, top_k=29).candidates
            self.assertEqual(c[0].source_id, r["rank1_source_id"], qid)
            self.assertAlmostEqual(c[0].distance, r["rank1_cosine_distance"], delta=1e-6, msg=qid)
            self.assertAlmostEqual(1 - c[0].distance, r["rank1_cosine_similarity"], delta=2e-6, msg=qid)


if __name__ == "__main__":
    unittest.main()
