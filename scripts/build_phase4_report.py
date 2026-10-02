#!/usr/bin/env python3
"""Phase 4 / final report: assemble `data/retrieval_phase4_report.md` from the recorded artefacts (no computation of new
facts): token statistics, retrieval units, collection manifest, evaluation results. The interpretation text is read from
`data/evaluation/card_retrieval_failure_analysis.md` (hand-written after the run). Offline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import ROOT, TOKEN_STATS_PATH, UNITS_PATH, sha256_file  # noqa: E402

OUT = ROOT / "data" / "retrieval_phase4_report.md"
MANIFEST = ROOT / "data" / "card_collection_manifest.json"
RESULTS = ROOT / "data" / "evaluation" / "card_retrieval_results.json"
QUESTIONS = ROOT / "data" / "evaluation" / "card_retrieval_questions.json"
ANALYSIS = ROOT / "data" / "evaluation" / "card_retrieval_failure_analysis.md"


def _t(head: List[str], rows: List[List[Any]], align: Optional[List[str]] = None) -> str:
    align = align or ["---"] * len(head)
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "|".join(align) + "|"] + ["| " + " | ".join(str(x) for x in r) + " |" for r in rows])


def build(test_summary: Optional[str]) -> str:
    tok = json.loads(TOKEN_STATS_PATH.read_text(encoding="utf-8"))
    units_payload = json.loads(UNITS_PATH.read_text(encoding="utf-8"))
    units = units_payload["units"]
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    res = json.loads(RESULTS.read_text(encoding="utf-8"))
    qs = {q["question_id"]: q for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]}
    by_id = {u["source_id"]: u for u in units}
    m = res["metrics"]["overall"]
    L: List[str] = ["# Phase 4 report - card-level retrieval units, embeddings and retrieval evaluation", "",
                    "Decision applied: **Strategy A (one retrieval unit per card)**. Every card keeps two representations: `full_text` (complete normalised card, unchanged) and `embedding_text` (card text without the two boilerplate sections). "
                    "Section-based and bounded-section strategies were not used. No SAP page content was added, no protected RAG script was modified, and the new collection is not connected to the existing application.", ""]
    # 1-3 tokenizer
    tk = tok["tokenizer"]
    L += ["## 1. Tokenizer and model", "",
          f"* embedding model: **{tok['model']['model_name']}** (the name configured in `scripts/rag_core.py`; unchanged)",
          f"* model files come from: {tok['model']['origin']}. huggingface.co is not reachable from the build sandbox, so the weights were taken from this PyPI package; it is a **third-party packaging, not an official release**. File hashes are recorded below.",
          f"* tokenizer: `{tk['class']}` (vocabulary {tk['vocab_size']}) loaded from the packaged model files; sentence-transformers `max_seq_length` = **{tk['model_max_seq_length_sentence_transformers']}** tokens (position-embedding limit {tk['position_embeddings_limit']})",
          "* counts include the special tokens `[CLS]` and `[SEP]` and were made **without truncation**",
          "", _t(["Model file", "sha256"], [[f"`{k}`", f"`{v}`"] for k, v in tok["model"]["files_sha256"].items()]), "",
          "## 2. Token statistics", "",
          _t(["Text", "Min", "Median", "Mean", "Max", "Model limit"],
             [["full_text (not embedded)", tok["full_text"]["min"], tok["full_text"]["median"], tok["full_text"]["mean"], tok["full_text"]["max"], tok["max_seq_length"]],
              ["embedding_text (embedded)", tok["embedding_text"]["min"], tok["embedding_text"]["median"], tok["embedding_text"]["mean"], tok["embedding_text"]["max"], tok["max_seq_length"]]],
             ["---", "--:", "--:", "--:", "--:", "--:"]), "",
          "Per-source token counts:", "",
          _t(["Source", "Title", "full_text tokens", "embedding_text tokens", "Headroom under limit (embedding_text)"],
             [[r["source_id"], by_id[r["source_id"]]["title"], r["full_text_tokens"], r["embedding_text_tokens"], r["embedding_text_headroom"]] for r in tok["sources"]],
             ["---", "---", "--:", "--:", "--:"]), "",
          "## 3. Truncation findings", "",
          f"* verdict: **{tok['verdict']}**",
          f"* embedding_text over the limit: {tok['embedding_text_over_limit'] or 'none'}; full_text over the limit: {tok['full_text_over_limit'] or 'none'}",
          f"* the largest full_text is {tok['full_text']['max']} tokens, below {tok['max_seq_length']}, so even the complete card would not be truncated. The earlier chars/4 estimate (about 279) in the Phase 3 report was too high; the real tokenizer count replaces it.",
          "* no text was truncated and the model was not changed. The embedding stage ran only after this check passed.", ""]
    # 4-5 units
    st = units_payload["stats"]
    L += ["## 4. Retrieval-unit statistics", "",
          f"* units: **{units_payload['unit_count']}** (one per source PDF; ids `M2C-01`..`M2C-29`) in `data/retrieval_units.json` (sha256 `{sha256_file(UNITS_PATH)}`)",
          f"* full_text characters: {st['full_text_chars_total']} in total; embedding_text characters: {st['embedding_text_chars_total']} in total ({round(100.0 * st['embedding_text_chars_total'] / st['full_text_chars_total'], 1)}% of full_text)",
          f"* per unit: full_text {min(u['char_counts']['full_text'] for u in units)}-{max(u['char_counts']['full_text'] for u in units)} chars; embedding_text {min(u['char_counts']['embedding_text'] for u in units)}-{max(u['char_counts']['embedding_text'] for u in units)} chars",
          f"* review state carried on every unit: {sum(1 for u in units if u['source_status'] == 'verified')} verified, {sum(1 for u in units if u['source_status'] != 'verified')} needs_review ({', '.join(u['source_id'] for u in units if u['source_status'] != 'verified')}); source correction metadata on {', '.join(u['source_id'] for u in units if u['has_source_correction'])}; none of it resolved",
          "", "## 5. Boilerplate exclusion rule", "",
          f"> {units_payload['embedding_text_rule']}", "",
          f"* excluded sections (fixed list): {', '.join('`' + k + '`' for k in units_payload['boilerplate_section_keys'])}. The builder refuses to run if these sections are not identical in all 29 cards.",
          "* kept verbatim: reference line, title, category line, *What it covers*, *Meter-to-Cash relevance*, *Authoritative SAP Help source* and its URL.",
          "* `embedding_text` is an exact prefix of `full_text` for every card; the excluded character ranges are stored in each unit (`embedding_text_spec`). Nothing was rewritten or generated.", ""]
    # 6-10 vectors
    L += ["## 6-10. Embedding collection", "",
          _t(["Item", "Value"], [
              ["embedding model", f"`{man['embedding_model']}`"], ["vector dimensions", f"**{man['embedding_dimensions']}**"],
              ["collection name", f"`{man['collection_name']}` (new; the legacy `sap_docs` collection was not touched)"],
              ["vector store directory", f"`{man['vector_store_dir']}` (separate from the legacy `chroma_db/`, git-ignored, rebuilt by script)"],
              ["vector count", f"**{man['vector_count']}**"], ["distance space / normalisation", f"{man['configuration']['distance_space']} / normalised embeddings"],
              ["document embedded", "`embedding_text`"], ["created (UTC)", man["created_utc"]],
              ["source corpus file sha256", f"`{man['source_corpus_file_sha256']}`"],
              ["source corpus content fingerprint", f"`{man['source_corpus_content_fingerprint']}`"],
              ["retrieval units file sha256", f"`{man['retrieval_units_file_sha256']}`"],
              ["token statistics file sha256", f"`{man['token_stats_file_sha256']}`"],
              ["embeddings (float32) sha256", f"`{man['embeddings_float32_sha256']}` (this machine only)"],
              ["chromadb", man["configuration"]["chromadb"]], ["rebuild", f"`{man['reproduce_with']}`"]]), "",
          "Each vector record holds the embedded text plus readable metadata: retrieval_unit_id, source_id, source_number, title, category, filename, source_url, source_status, source_url_status, has_source_correction, citation, sha256, corpus_document, page_start/page_end, embedding_text_sha256 and full_text_sha256. Before inserting, the script verified the collection was new and empty, and afterwards that it held 29 vectors.", ""]
    # 11-15 eval
    ov = res["metrics"]
    L += ["## 11-15. Evaluation", "",
          f"* evaluation set: **{res['question_count']} questions** in `data/evaluation/card_retrieval_questions.json` (sha256 `{res['questions_file_sha256']}`), written by hand from the card text before any retrieval was run; every expected source has a verbatim evidence quote from that card. No LLM was used.",
          "* a question is a **hit@k** if any expected source is among the top k of the 29 cards; MRR uses the rank of the first expected source.", "",
          _t(["Metric", "All questions", "Unambiguous only", "Ambiguous only"],
             [[k, ov["overall"][k], ov["unambiguous_questions_only"][k], ov["ambiguous_questions_only"][k]] for k in ("questions", "recall@1", "recall@3", "recall@5", "mrr")],
             ["---", "--:", "--:", "--:"]), "",
          f"**Recall@1 = {m['recall@1']}**, **Recall@3 = {m['recall@3']}**, **Recall@5 = {m['recall@5']}**, **MRR = {m['mrr']}** ({m['hits@1']} of {m['questions']} questions have the expected card at rank 1).", "",
          "By question type:", "",
          _t(["Type", "Questions", "Recall@1", "Recall@3", "Recall@5", "MRR", "Mean share of expected cards found in top 3"],
             [[t, v["questions"], v["recall@1"], v["recall@3"], v["recall@5"], v["mrr"], v["mean_expected_coverage@3"]] for t, v in ov["by_question_type"].items()],
             ["---", "--:", "--:", "--:", "--:", "--:", "--:"]), "",
          "How to read this: the set is small (one question moves Recall@1 by 2 points), and many questions reuse wording from the cards, so the numbers describe retrieval over card text, not over real user phrasing. "
          "Chance level on 29 cards is about 3% for Recall@1 and 17% for Recall@5 for a single expected card. This is not a claim that retrieval is 'good'; it is a measurement.", ""]
    ctl = res.get("control_full_text_in_memory")
    if ctl:
        c = ctl["metrics"]["overall"]
        L += ["### Control: boilerplate included (in memory, nothing stored)", "",
              _t(["Text embedded", "Recall@1", "Recall@3", "Recall@5", "MRR"],
                 [["embedding_text (evaluated collection)", m["recall@1"], m["recall@3"], m["recall@5"], m["mrr"]],
                  ["full_text (control, not a collection)", c["recall@1"], c["recall@3"], c["recall@5"], c["mrr"]]], ["---", "--:", "--:", "--:", "--:"]), "",
              "The two rows differ by a few questions in either direction, which this set is too small to call a difference. The control shows that excluding the boilerplate did not cost measurable retrieval here; it does not prove it helps.", ""]
    L += ["## 16. Per-question results", "",
          "Rank = position of the first expected source among all 29 cards. Retrieved = top 3 as `source id title (cosine similarity)`.", "",
          _t(["ID", "Type", "Question", "Expected", "Rank", "Top-1 retrieved", "Top-2", "Top-3", "Amb."],
             [[r["question_id"], r["question_type"], r["question"].replace("|", "/"), ", ".join(r["expected_source_ids"]), ("**" + str(r["first_expected_rank"]) + "**") if r["first_expected_rank"] > 1 else r["first_expected_rank"]] +
              [f"{t['source_id']} {t['title']} ({t['cosine_similarity']})" for t in r["retrieved_top5"][:3]] + ["yes" if r["ambiguous"] else ""] for r in res["per_question"]],
             ["---", "---", "---", "---", "--:", "---", "---", "---", "---"]), ""]
    L += ["## 17. Failed cases", "",
          f"* not at rank 1 (failed@1): {', '.join(res['failed_at_1']) or 'none'}", f"* not in top 3 (failed@3): {', '.join(res['failed_at_3']) or 'none'}",
          f"* not in top 5 (failed@5): {', '.join(res['failed_at_5']) or 'none'}",
          f"* questions labelled ambiguous before the run: {', '.join(res['ambiguous_question_ids'])} ({len(res['ambiguous_question_ids'])})", ""]
    if ANALYSIS.is_file():
        L += [ANALYSIS.read_text(encoding="utf-8").rstrip(), ""]
    # 18 provenance
    L += ["## 18. Provenance validation", "",
          "* every retrieval unit resolves to exactly one original PDF: `retrieval_unit_id` = `source_id` -> `data/source_corpus.json#<source_id>` -> `filename` + `sha256` (equal to the manifest hash and, in the tests, to the current hash of the PDF in the repository).",
          "* all 29 units have distinct filenames and distinct sha256 values; page range is 1-1 for all cards.",
          "* every vector record carries the same identifiers and hashes as its unit, and the stored document equals the unit's `embedding_text` (checked before evaluating; evaluation aborts otherwise).",
          "* PDFs, `source_manifest.json` and `source_corpus.json` were not modified (hash-checked in the tests).",
          "* no SAP page was externally verified; `verified` still means only what Phase 1 defined. Unresolved items #05, #14, #18 and #23 are carried unchanged in `source_status`, `source_url_status`, `review_reasons` and `source_correction`.", "",
          "## 19. Tests", "", test_summary or "_Not recorded in this run. Pass `--test-summary \"<pytest result>\"`._", "",
          "## 20. Recommendation for the next phase", "",
          "1. Review this report, in particular the four rank-1 misses and the evaluation set, before wiring anything into the application.",
          "2. Enlarge the evaluation set with independently written queries (for example short keyword queries and natural user phrasing) before drawing conclusions; 50 questions over 29 cards cannot separate small differences.",
          "3. Decide how to handle short rare-term queries (Q39, Q42): a keyword/hybrid component is the natural candidate and should be tested on the same set. It was not implemented here.",
          "4. Only after that, plan the integration into the RAG pipeline as a separate, reviewed step (prompt, retrieval threshold, citation format), and add SAP page content as its own phase. The card collection describes what each topic covers; it does not contain the SAP answers.",
          "5. Keep `sap_docs` and the protected RAG scripts untouched until that integration is approved.", ""]
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
