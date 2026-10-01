#!/usr/bin/env python3
"""Phase 5 report: assemble `data/retrieval_phase5_report.md` from recorded artefacts only (no retrieval is run here):
`data/evaluation/phase5_results.json`, `independent_queries.json`, the Phase-4 baseline files and the hand-written
`phase5_failure_analysis.md`. Every number in the tables is read from those files. Offline and deterministic."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import ROOT, sha256_file  # noqa: E402

OUT = ROOT / "data" / "retrieval_phase5_report.md"
RESULTS = ROOT / "data" / "evaluation" / "phase5_results.json"
QUERIES = ROOT / "data" / "evaluation" / "independent_queries.json"
ANALYSIS = ROOT / "data" / "evaluation" / "phase5_failure_analysis.md"
P4_RESULTS = ROOT / "data" / "evaluation" / "card_retrieval_results.json"
P4_MANIFEST = ROOT / "data" / "card_collection_manifest.json"

SYSTEM_LABEL = {"dense": "A dense only", "bm25": "B BM25 only", "hybrid_0.75": "C hybrid w_dense=0.75",
                "hybrid_0.5": "C hybrid w_dense=0.5 (primary)", "hybrid_0.25": "C hybrid w_dense=0.25"}
SYSTEMS = list(SYSTEM_LABEL)


def table(head: List[str], rows: List[List[Any]], align: Optional[List[str]] = None) -> str:
    align = align or ["---"] * len(head)
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "|".join(align) + "|"]
                     + ["| " + " | ".join(str(x) for x in r) + " |" for r in rows])


def f(x: float) -> str:
    return f"{x:.4f}"


def mrow(label: str, m: Dict[str, Any]) -> List[Any]:
    if not m.get("questions"):
        return [label, 0, "-", "-", "-", "-"]
    return [label, m["questions"], f(m["recall@1"]), f(m["recall@3"]), f(m["recall@5"]), f(m["mrr"])]


MHEAD = ["System", "Queries", "Recall@1", "Recall@3", "Recall@5", "MRR"]
MALIGN = ["---", "--:", "--:", "--:", "--:", "--:"]


def overall_table(ds: Dict[str, Any], systems: Sequence[str]) -> str:
    return table(MHEAD, [mrow(SYSTEM_LABEL[s], ds["systems"][s]["summary"]["overall"]) for s in systems], MALIGN)


def breakdown(ds: Dict[str, Any], key: str, order: Optional[Sequence[str]] = None) -> str:
    groups = list(order) if order else sorted(ds["systems"]["dense"]["summary"][key])
    rows = []
    for g in groups:
        for s in SYSTEMS:
            m = ds["systems"][s]["summary"][key].get(g, {})
            rows.append(mrow(f"{g} / {SYSTEM_LABEL[s]}", m))
    return table(["Group / system", "Queries", "Recall@1", "Recall@3", "Recall@5", "MRR"], rows, MALIGN)


def build(test_summary: Optional[str]) -> str:
    res = json.loads(RESULTS.read_text(encoding="utf-8"))
    qs_payload = json.loads(QUERIES.read_text(encoding="utf-8"))
    qs = {q["query_id"]: q for q in qs_payload["queries"]}
    p5, p4 = res["datasets"]["phase5"], res["datasets"]["phase4"]
    base = res["protected_baseline"]
    rec = base["phase4_recorded_metrics"]
    dec = p5["decision"]
    comp = p5["composition"]
    fp = res["failure_pattern_counts_phase5"]
    tk = res["tokenization"]
    d5 = p5["systems"]["dense"]["summary"]["overall"]
    primary = res["settings"]["primary_hybrid"]
    h5 = p5["systems"][primary]["summary"]["overall"]
    L: List[str] = ["# Phase 5 report - retrieval robustness evaluation (evidence only)", "",
                    "Question: does retrieval stay reliable when queries are written like real users instead of being copied from the cards? "
                    "The Phase 4 collection `sap_m2c_card_v1` and its results are a protected baseline and were **not** changed. "
                    "Nothing here is integrated into the application, no production hybrid or new production collection exists, the embedding model is unchanged, "
                    "and no SAP page was fetched. The output is evidence for the architecture decision and nothing more.", "",
                    f"**Headline:** on independently worded queries the unchanged dense retriever scores Recall@1 **{f(d5['recall@1'])}** and MRR **{f(d5['mrr'])}** "
                    f"(Phase 4 wording: {rec['recall@1']} and {rec['mrr']}). The controlled hybrid experiment does **not** meet the pre-declared rule for a measurable benefit "
                    f"(failed criteria: {', '.join(dec['failed_criteria'])}). **Recommendation: retain dense-only retrieval.**", ""]

    def r1(system: str, typ: str) -> float:
        return p5["systems"][system]["summary"]["by_query_type"][typ]["recall@1"]

    pv = p5["paired_vs_dense"]
    w75 = p5["systems"]["hybrid_0.75"]["summary"]["overall"]
    n_nolex = sum(1 for k, v in fp["patterns"].items() if k.startswith("no_lexical_path") for _ in range(v))
    ctl = json.loads(P4_RESULTS.read_text(encoding="utf-8")).get("control_full_text_in_memory", {}).get("metrics", {}).get("overall", {})
    # 1
    L += ["## 1. Phase 4 baseline", "",
          f"* 29 cards, one vector per card, collection `{res['inputs']['collection']}`, {res['inputs']['collection_metadata']['embedding_model']}, "
          f"{res['inputs']['collection_metadata']['embedding_dimensions']} dimensions, cosine distance, `embedding_text` (only `library_use` and `copyright_note` excluded).",
          f"* Recorded Phase 4 results on its 50 questions: Recall@1 {rec['recall@1']}, Recall@3 {rec['recall@3']}, Recall@5 {rec['recall@5']}, MRR {rec['mrr']} "
          "(failed at rank 1: Q07, Q39, Q42, Q49).",
          f"* The baseline was reproduced before anything else: top-5 lists for all {base['phase4_questions_checked']} questions are identical to the recorded ones "
          f"(`{base['top5_identical_to_recorded_phase4_results']}`, max similarity difference {base['max_abs_similarity_difference_vs_recorded']}).",
          "* The protected store was queried through a temporary copy. Raw store-file hashes are not a stable identity (any process that opens a Chroma store updates its bookkeeping files, and every rebuild creates a new segment id), "
          f"so they were compared within the run only (unchanged by this evaluation = **{base['vector_store_unchanged_by_this_evaluation']}**). The store's identity is its content: "
          f"the vectors read back from the collection differ from freshly encoded `embedding_text` vectors by at most {base['stored_vs_recomputed_embedding_max_abs_diff']} (consistent = **{base['stored_embeddings_consistent_with_embedding_text']}**), and the top-5 lists reproduce exactly. "
          f"The hash of the freshly encoded float32 vectors equals the Phase 4 manifest hash: {base['recomputed_hash_equals_phase4_manifest_hash_informational']} (informational only: a bitwise hash is sensitive to encoding batch size, CPU and library version, and the per-vector difference is about 1e-7).",
          "* Important: the Phase 4 questions were worded from the cards' own text, so they share vocabulary with the cards. Section 10 shows the consequence.", ""]

    # 2
    lens = [q["max_verbatim_overlap_words"] for q in qs.values()]
    L += ["## 2. Independent dataset description", "",
          f"* `data/evaluation/independent_queries.json`: **{p5['query_count']}** queries (sha256 `{res['inputs']['independent_queries_sha256']}`), each with an expected card, rationale, query type, difficulty and a **verbatim** evidence quote from the expected card's `full_text` "
          "(the builder refuses to write the file if a quote is not found).",
          "* **Authorship disclosure:** the queries were written by hand by the AI coding agent working on this repository, inside `scripts/build_independent_queries.py`, "
          "before any Phase 5 retrieval was run, and were not changed after seeing results. They were not produced by an automated LLM generation pipeline, retrieval was not in the loop, and labels come from the card text only. "
          "They were **not** written by a human domain expert or collected from real users, which would be a stronger test (see limitations).",
          f"* Independence rules enforced by the builder: no query equals a Phase 4 question; no query shares more than {qs_payload['independence_rules']['max_verbatim_overlap_words']} consecutive words with its expected card(s). "
          f"Longest verbatim run per query: 1 word x {lens.count(1)}, 2 words x {lens.count(2)}, 3 words x {lens.count(3)}.",
          f"* Query types: {', '.join(f'{k} {v}' for k, v in comp['by_query_type'].items())}.",
          f"* Length buckets by word count: {', '.join(f'{k} {v}' for k, v in comp['by_length'].items())} (very_short = 1-4 words, short = 5-7, long = 8-20; no query is longer than 20 words).",
          f"* Difficulty (assigned by hand from written criteria before any run): {', '.join(f'{k} {v}' for k, v in comp['by_difficulty'].items())}.",
          f"* {comp['ambiguous']} of {p5['query_count']} queries are flagged `ambiguous` (a sibling card is plausible) and {comp['multi_expected']} have more than one accepted card. "
          "The flag is broad, so the `ambiguous` flag is not a clean subset; the query type `ambiguous` (7 queries) is the narrow group.",
          f"* Diagnostic slices (defined mechanically before the run): "
          + ", ".join(f"`{k}` {len(v)}" for k, v in p5["slices"].items())
          + ". `rare_term` = a query term found in at most 2 of the 29 cards; `fragmented_term` = a term the tokenizer splits into 3 or more pieces; `no_lexical_overlap` = no query term appears in the expected card.",
          "* Metric definition is the Phase 4 one: a hit is any expected card; `also_relevant` cards are listed for information and do not count.", ""]

    # 3-5
    L += ["## 3. Dense-only results (system A, the unchanged Phase 4 retriever)", "", overall_table(p5, ["dense"]), "",
          f"Chance level on 29 cards is about 3% for Recall@1 and 17% for Recall@5 (single expected card). Of {p5['query_count']} queries, {fp['dense_not_rank1']} miss rank 1 and {fp['dense_not_top3']} miss the top 3. "
          f"Paired Phase 4 vs independent: Recall@1 {rec['recall@1']} to {d5['recall@1']}, MRR {rec['mrr']} to {d5['mrr']}.", "",
          "## 4. BM25-only results (system B)", "",
          "Transparent Okapi BM25 (k1 1.5, b 0.75) over the same `embedding_text` that is embedded, lowercase alphanumeric tokens, 33 Lucene English stopwords, **no stemming** (a documented limitation), min-max normalised only when combined.", "",
          table(["Set", *MHEAD], [["independent", *mrow(SYSTEM_LABEL["bm25"], p5["systems"]["bm25"]["summary"]["overall"])],
                                  ["Phase 4", *mrow(SYSTEM_LABEL["bm25"], p4["systems"]["bm25"]["summary"]["overall"])]], ["---"] + MALIGN), "",
          "BM25 is strongest on the Phase 4 set and weakest on the independent set, which is what copied wording would produce (section 10).", "",
          "## 5. Hybrid results (system C)", "",
          "Score = `w_dense * minmax(cosine) + (1 - w_dense) * minmax(BM25)`, min-max per query over the 29 cards. Three fixed weights were chosen **before** any result: 0.75, 0.5 (declared primary, equal weight) and 0.25. "
          "No weight, stopword list or token rule was changed after looking at results, and nothing was tuned to an individual query.", "",
          table(["Set", *MHEAD], [[n, *mrow(SYSTEM_LABEL[s], ds["systems"][s]["summary"]["overall"])]
                                  for n, ds in (("independent", p5), ("Phase 4", p4)) for s in SYSTEMS], ["---"] + MALIGN), "",
          "Paired comparison with dense on the independent set (rank of the first expected card):", "",
          table(["System", "Improved", "Worsened", "Unchanged", "Sign-test p (2-sided)", "Gained rank 1", "Lost rank 1"],
                [[SYSTEM_LABEL[s], v["improved"], v["worsened"], v["unchanged"], v["sign_test_p_two_sided"], len(v["gained_rank1"]), len(v["lost_rank1"])]
                 for s, v in p5["paired_vs_dense"].items()], ["---", "--:", "--:", "--:", "--:", "--:", "--:"]), "",
          f"Primary hybrid ({primary}) against dense: MRR {f(h5['mrr'])} vs {f(d5['mrr'])}, Recall@1 {f(h5['recall@1'])} vs {f(d5['recall@1'])}. "
          "Weight 0.75 is the only setting above dense, and only slightly (see section 11).", ""]

    # 6-7
    L += ["## 6. Breakdown by query type (independent set)", "", breakdown(p5, "by_query_type", ["keyword", "entity", "natural", "paraphrase", "ambiguous"]), "",
          "By difficulty:", "", breakdown(p5, "by_difficulty", ["easy", "medium", "hard"]), "",
          "Diagnostic slices (a query can belong to several):", "", breakdown(p5, "slices", list(p5["slices"])), "",
          "Reading: lexical and hybrid retrieval help on keyword and entity queries and on the rare-term slice; they hurt on natural and paraphrase queries, where users' words are absent from the card text. "
          "Groups have 4 to 14 queries each, so single-digit differences are not reliable.", "",
          "## 7. Breakdown by query length (independent set)", "", breakdown(p5, "by_length", ["very_short", "short", "long"]), "",
          "Very short = 1-4 words, short = 5-7, long = 8-20. The `short` bucket has only 7 queries.", ""]

    # 8
    L += ["## 8. Failure analysis", "",
          "### 8.1 Dense failures on the independent set", "",
          table(["ID", "Query", "Expected", "Dense rank", "Dense top-1 (cos)", "Expected cos", "BM25 rank", "Hybrid 0.5 rank", "Pattern"],
                [[d["id"], d["query"].replace("|", "/"), d["expected"], d["dense_rank_expected"], f"{d['top1']} ({d['dense_sim_top1']})", d["dense_sim_expected"],
                  d["bm25_rank_expected"], d["hybrid_primary_rank_expected"], d["failure_pattern"].split(" (")[0]]
                 for d in res["failure_diagnostics"]["phase5_dense_not_rank1"]], ["---", "---", "---", "--:", "---", "--:", "--:", "--:", "---"]), "",
          "### 8.2 The four known Phase 4 failures under every system", "",
          table(["ID", "Query", "Expected", *[SYSTEM_LABEL[s] for s in SYSTEMS]],
                [[d["id"], d["query"].replace("|", "/"), d["expected"], *[d["ranks_all_systems"][s] for s in SYSTEMS]]
                 for d in res["failure_diagnostics"]["phase4_known_failures"]], ["---", "---", "---"] + ["--:"] * len(SYSTEMS)), "",
          "Cells are the rank of the expected card (1 = correct). All four known failures reach rank 1 under BM25 and the primary hybrid. That is a fact about these four queries, which are copied from card wording; it does not show the hybrid is better in general.", "",
          f"Counts: {fp['dense_not_rank1']} dense misses at rank 1; {fp['patterns']} ; near-ties (top-1 gap below 0.02): {fp['near_ties']}; top-1 card in the expected card's category: {fp['top1_same_category_as_expected']}; "
          f"failures containing a fragmented query term: {fp['with_fragmented_query_terms']}; fixed to rank 1 by the primary hybrid: {fp['fixed_to_rank1_by_primary_hybrid']}.", "",
          f"Card similarity structure: mean cosine between cards of the same category {res['card_similarity']['mean_cosine_same_category_pairs']} ({res['card_similarity']['same_category_pairs']} pairs), "
          f"across categories {res['card_similarity']['mean_cosine_cross_category_pairs']} ({res['card_similarity']['cross_category_pairs']} pairs).", ""]
    if ANALYSIS.is_file():
        body = ANALYSIS.read_text(encoding="utf-8").rstrip().split("\n")
        L += ["### 8.3 Analysis (hand-written, evidence-referenced)", ""] + [(re.sub(r"^## (\d+)\. ", r"#### 8.3.\1 ", ln) if ln.startswith("## ") else ln) for ln in body[1:]] + [""]

    # 9
    L += ["## 9. Tokenization findings", "",
          f"`{tk['tokenizer']}` (vocabulary {tk['vocab_size']}), the tokenizer of the unchanged model (`max_seq_length` {tk['model_max_seq_length']}). Terms of the card vocabulary that split into {tk['fragment_threshold_pieces']} or more word pieces "
          f"({round(100 * tk['card_terms_fragmented_share'], 1)}% of {tk['card_vocabulary_terms']} alphabetic card terms; {tk['query_terms_fragmented']} of {tk['query_terms']} query terms are fragmented):", "",
          table(["Term", "Word pieces", "Cards containing it (- = not a query term, not counted)"],
                [[f"`{t}`", "`" + " ".join(p) + "`", tk["term_card_document_frequency"].get(t, "-")] for t, p in tk["card_terms_fragmented"].items()]), "",
          f"* The hexadecimal identifiers inside the printed SAP URLs fragment into many pieces and take {round(100 * tk['url_wordpiece_share_of_embedding_text']['min'], 1)}% to "
          f"{round(100 * tk['url_wordpiece_share_of_embedding_text']['max'], 1)}% of each card's `embedding_text` word pieces (mean {round(100 * tk['url_wordpiece_share_of_embedding_text']['mean'], 1)}%). See the ablation in 8.3.6: removing them did not improve retrieval.",
          "* Fragmentation of the failed Phase 4 terms is factual (`clarification`, `subledger`). Fragmentation as the **cause** of the failures is not supported (8.3.3): no independent failure contains a fragmented query term, and the effect on retrieval points in opposite directions on the two sets.",
          "* Effect of a fragmented term in the expected card (MRR with / without, dense | BM25 | hybrid 0.5):", ""]
    for name in ("phase5", "phase4"):
        e = tk["fragmented_expected_term_effect"][name]
        w = e["systems"]
        L.append(f"  * {name}: {len(e['with_fragmented_expected_term_ids'])} queries with / rest without: "
                 + " | ".join(f"{s} {w[s]['with_fragmented_expected_term']['mrr']} / {w[s]['without']['mrr']}" for s in ("dense", "bm25", "hybrid_0.5")))
    L += ["", "The model was not changed. The study only shows the splits and correlates them with outcomes.", ""]

    # 10
    ph4_bm = p4["systems"]["bm25"]["summary"]["overall"]
    ph4_d = p4["systems"]["dense"]["summary"]["overall"]
    L += ["## 10. Comparison against Phase 4", "",
          table(["Retriever", "Phase 4 R@1", "Independent R@1", "Phase 4 MRR", "Independent MRR", "Drop in MRR"],
                [[SYSTEM_LABEL[s], f(p4["systems"][s]["summary"]["overall"]["recall@1"]), f(p5["systems"][s]["summary"]["overall"]["recall@1"]),
                  f(p4["systems"][s]["summary"]["overall"]["mrr"]), f(p5["systems"][s]["summary"]["overall"]["mrr"]),
                  f(p4["systems"][s]["summary"]["overall"]["mrr"] - p5["systems"][s]["summary"]["overall"]["mrr"])] for s in SYSTEMS],
                ["---", "--:", "--:", "--:", "--:", "--:"]), "",
          f"* Dense drops from MRR {f(ph4_d['mrr'])} to {f(d5['mrr'])} and Recall@5 from {f(ph4_d['recall@5'])} to {f(d5['recall@5'])}. The Phase 4 figures overstate retrieval quality for user-style wording.",
          f"* On the Phase 4 set a plain lexical retriever (BM25) scores MRR {f(ph4_bm['mrr'])}, **higher than dense** ({f(ph4_d['mrr'])}); on the independent set the order reverses "
          f"({f(p5['systems']['bm25']['summary']['overall']['mrr'])} vs {f(d5['mrr'])}). That reversal is consistent with the Phase 4 questions sharing words with the cards. "
          "The Phase 4 set is therefore used here only as a harm check for hybrid, not as evidence for it.",
          "* Both sets are small (one query is about 2 points) and share the same 29 cards, so neither number is a production estimate.",
          f"* Phase 4 control (`full_text` embedded in memory): R@1 {ctl.get('recall@1')}, MRR {ctl.get('mrr')} against {rec['recall@1']} and {rec['mrr']} - inconclusive, unchanged. "
          f"Prose-only ablation (8.3.6): independent MRR {p5['diagnostic_prose_only_dense']['summary']['overall']['mrr']} and Phase 4 MRR {p4['diagnostic_prose_only_dense']['summary']['overall']['mrr']}, both below the evaluated `embedding_text`, so no representation change is indicated by this phase.", ""]

    # 11
    crit = dec["criteria"]
    L += ["## 11. Whether hybrid gives a measurable benefit", "",
          "The decision rule was written into `scripts/evaluate_phase5.py` before any Phase 5 result existed. Hybrid counts as beneficial only if every criterion holds for the primary weight (0.5):", "",
          table(["Criterion", "Rule", "Evidence", "Result"],
                [["C1", crit["C1"]["rule"], f"dense {crit['C1']['dense']}, hybrid {crit['C1']['hybrid']}, delta {crit['C1']['delta']}", "pass" if crit["C1"]["pass"] else "**FAIL**"],
                 ["C2", crit["C2"]["rule"], f"delta R@3 {crit['C2']['delta_recall@3']}, delta R@5 {crit['C2']['delta_recall@5']}", "pass" if crit["C2"]["pass"] else "**FAIL**"],
                 ["C3", crit["C3"]["rule"], f"improved {crit['C3']['improved']}, worsened {crit['C3']['worsened']}, p {crit['C3']['p']}", "pass" if crit["C3"]["pass"] else "**FAIL**"],
                 ["C4", crit["C4"]["rule"], "; ".join(f"{k}: {v['dense_mrr']} to {v['hybrid_mrr']}" for k, v in crit["C4"]["slices"].items()), "pass" if crit["C4"]["pass"] else "**FAIL**"],
                 ["C5", crit["C5"]["rule"], f"hybrid minus dense on the Phase 4 set: MRR {crit['C5']['delta_mrr']:+.4f}, R@1 {crit['C5']['delta_recall@1']:+.4f} (no drop)", "pass" if crit["C5"]["pass"] else "**FAIL**"],
                 ["C6", crit["C6"]["rule"], "delta MRR by dense weight: " + ", ".join(f"{k}: {v:+.4f}" for k, v in crit["C6"]["delta_mrr_by_w_dense"].items()), "pass" if crit["C6"]["pass"] else "**FAIL**"]],
                ["---", "---", "---", "---"]), "",
          f"**Verdict from the rule: {dec['verdict']}**", "",
          "What the evidence does and does not show:", "",
          f"* Recall@1 alone is not the criterion, and it is not even favourable for the primary weight ({f(h5['recall@1'])} vs {f(d5['recall@1'])}).",
          f"* Where hybrid clearly helps: very short queries, keyword and entity queries and the rare-term slice (sections 6-7), and it fixes the four known Phase 4 failures and {fp['fixed_to_rank1_by_primary_hybrid']} of the {fp['dense_not_rank1']} independent dense misses at rank 1.",
          f"* Where it clearly hurts: natural-language and paraphrase queries (R@1 at w=0.5: natural {r1('dense', 'natural'):.2f} to {r1(primary, 'natural'):.2f}; paraphrase {r1('dense', 'paraphrase'):.2f} to {r1(primary, 'paraphrase'):.2f}) and queries with no lexical overlap with the card. More queries worsen than improve at w=0.5 ({pv[primary]['improved']} improved vs {pv[primary]['worsened']} worsened).",
          f"* Weight 0.75 changes less: MRR {w75['mrr'] - d5['mrr']:+.4f} and Recall@3 {w75['recall@3'] - d5['recall@3']:+.4f} over dense, but {pv['hybrid_0.75']['improved']} queries improve and {pv['hybrid_0.75']['worsened']} worsen (sign test p = {pv['hybrid_0.75']['sign_test_p_two_sided']}) and the MRR gain is below the +0.03 threshold. It is the only weight of three that beats dense, so it cannot be called robust.",
          "* The per-slice gains are a post-hoc reading of a 54-query set. They are a hypothesis for a new held-out set, not a finding to act on. The weights were not adjusted to rescue the hybrid.",
          "* The benefit of a lexical signal therefore depends on the mix of queries users actually send. This report cannot estimate that mix.", ""]

    # 12
    L += ["## 12. Recommendation for the next phase", "",
          "1. **Retain dense-only retrieval** (`sap_m2c_card_v1`, unchanged) as the retriever. The evidence does not justify a hybrid in production, and it does not justify changing the embedding text or the model.",
          f"2. Do not treat the Phase 4 scores as the expected quality. With user-style wording, about {round(100 * (1 - d5['recall@5']))}% of queries miss the top 5 and about {round(100 * (1 - d5['recall@1']))}% miss rank 1. "
          "Any downstream answer-quality evaluation should run with top-k of at least 5 and should report retrieval misses separately from generation errors.",
          f"3. The largest group of independent failures ({n_nolex} of {fp['dense_not_rank1']}) is a vocabulary gap between the user's words and the card text, which neither BM25 nor the hybrid fixed. "
          "Candidate remedies (for example how user queries are phrased or expanded, or whether card descriptions cover user vocabulary) would each need their own phase and their own evidence; none is tested here, and no source content may be invented.",
          "4. If a lexical component is revisited, test it on a **new** query set written before looking at these results, ideally by a human or from real user questions, and pre-declare any condition (for example a query-length rule) in advance. "
          "The short-query and rare-term gains seen here are the hypothesis to test, not a result.",
          "5. Enlarge the evaluation set beyond 54 queries before drawing conclusions from differences of a few points. One query is about 2 points.",
          "6. Keep the application, `sap_docs` and the protected RAG scripts untouched until an integration is explicitly approved.", "",
          "## Limitations", "",
          "* Small query sets (54 and 50 on 29 cards); one query is about 2 points; per-group tables have 4 to 27 queries.",
          "* The independent queries were written by the AI coding agent, not by domain experts or real users (section 2); they may share the writer's habits of phrasing with any other model-written text.",
          "* BM25 uses no stemming. A lexical retriever with stemming would behave differently (example: `cash desk` vs `desks`), and was not tested.",
          "* Failure-pattern labels are mechanical and do not prove a cause; section-level similarities are diagnostic only.",
          "* The embedding model weights come from the third-party PyPI package `gt-all-minilm-l6-v2`, validated earlier by reproducing the baseline; this is not the official download.",
          "* Unresolved source-review items (#05, #14, #18, #23) are carried unchanged as metadata and were not touched.", ""]

    # appendices
    dense_rows = p5["systems"]["dense"]["rows"]
    L += ["## Appendix A. Per-query results (dense, the unchanged retriever)", "",
          "Rank = position of the first expected card among 29. Top 5 = `card id (cosine)`.", "",
          table(["ID", "Type", "Len", "Diff", "Query", "Expected", "Rank", "Top 5 (cosine)", "Pass"],
                [[r["id"], r["query_type"], r["length_bucket"], r["difficulty"], r["query"].replace("|", "/"), ", ".join(r["expected_source_ids"]),
                  (f"**{r['first_expected_rank']}**" if r["first_expected_rank"] > 1 else 1),
                  "; ".join(f"{t['source_id']} ({t['score']})" for t in r["top5"]), "PASS" if r["pass"] else "FAIL"] for r in dense_rows],
                ["---", "---", "---", "---", "---", "---", "--:", "---", "---"]), "",
          "## Appendix B. Rank of the expected card per query and system (independent set)", "",
          table(["ID", "Query", *[SYSTEM_LABEL[s] for s in SYSTEMS]],
                [[r["id"], r["query"].replace("|", "/"), *[p5["systems"][s]["rows"][i]["first_expected_rank"] for s in SYSTEMS]] for i, r in enumerate(dense_rows)],
                ["---", "---"] + ["--:"] * len(SYSTEMS)), "",
          "## Appendix C. Files and integrity", "",
          f"* `data/evaluation/independent_queries.json` sha256 `{sha256_file(QUERIES)}`",
          f"* `data/evaluation/phase5_results.json` sha256 `{sha256_file(RESULTS)}`",
          f"* protected, read only: `data/evaluation/card_retrieval_results.json` sha256 `{sha256_file(P4_RESULTS)}`; `data/card_collection_manifest.json` sha256 `{sha256_file(P4_MANIFEST)}`",
          f"* retrieval units sha256 `{res['inputs']['retrieval_units_sha256']}`; source corpus sha256 `{res['inputs']['source_corpus_sha256']}`",
          "* Phase 5 code: `scripts/build_independent_queries.py`, `scripts/phase5_retrievers.py`, `scripts/evaluate_phase5.py`, `scripts/build_phase5_report.py`; tests in `tests/test_phase5.py`.",
          "* Reproduce: `python scripts/build_independent_queries.py && python scripts/evaluate_phase5.py && python scripts/build_phase5_report.py` (the store must exist; rebuild it with `build_card_collection.py --manifest <tmp path>` so the Phase 4 manifest is not overwritten). No network is used.", "",
          "## Tests", "", test_summary or "_Not recorded in this run. Pass `--test-summary \"<pytest result>\"`._", ""]
    return "\n".join(L)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--test-summary", default=None)
    a = ap.parse_args(argv)
    Path(a.out).write_text(build(a.test_summary), encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
