#!/usr/bin/env python3
"""Two-stage follow-up elaboration - MEASUREMENT ONLY (nothing in the product imports this script).

Architecture under test:
    RETRIEVED EVIDENCE
      -> STAGE 1: the LLM proposes a JSON claim plan (each claim: one factual sentence + its source markers)
      -> DETERMINISTIC CLAIM VALIDATION (markers, acronyms/numbers/code tokens, evidence terms, support, topicality)
      -> STAGE 2: the LLM rewrites ONLY the validated claims as a natural explanation (no markers, no new facts)
      -> DETERMINISTIC sentence->claim mapping; citations are attached from the validated claim->source mapping.

Every gate is deterministic and never repairs text: if a claim fails it is rejected; if the synthesis introduces an
unsupported sentence the arm refuses and the pipeline falls back to the scoped extractive elaboration (arm B2). The
product's own verification (EvidenceGuard + the shipped ``verify_grounding``) runs on the final text unchanged - this
script adds no relaxation of any existing rule and touches no product file.

Usage
  real run (needs Ollama)   python scripts/evaluate_two_stage_llm.py
  offline guard check       python scripts/evaluate_two_stage_llm.py --stub faithful --out /tmp/ts.json --markdown /tmp/ts.md
  hostile stub battery      python scripts/evaluate_two_stage_llm.py --stub all --out /tmp/ts_all.json --markdown /tmp/ts_all.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

TWO_STAGE_STUB_MODES = ("off", "faithful", "miscited", "invented", "benefit", "markerless", "badjson",
                        "synth_markers", "synth_newfact", "synth_example", "synth_filler", "all")
parser = argparse.ArgumentParser(description="Two-stage elaboration measurement (claim plan -> validation -> synthesis).")
parser.add_argument("--questions", default="data/phase_elaboration/elaboration_questions.json")
parser.add_argument("--out", default="data/phase_elaboration/two_stage_run.json")
parser.add_argument("--markdown", default="data/phase_elaboration/two_stage_report.md")
parser.add_argument("--model", default=None, help="defaults to rag_core.LLM_MODEL_NAME")
parser.add_argument("--timeout", type=float, default=20.0, help="seconds per model call (0 disables the bound)")
parser.add_argument("--num-predict", type=int, default=None, help="optional cap on generated tokens per call")
parser.add_argument("--limit", type=int, default=None, help="only the first N topics")
parser.add_argument("--stub", choices=TWO_STAGE_STUB_MODES, default="off",
                    help="off = use Ollama; otherwise a canned two-stage model for offline checks")
parser.add_argument("--strict-plan", action="store_true",
                    help="abort the whole plan when ANY claim fails validation (default: drop only that claim)")
parser.add_argument("--force", action="store_true", help="allow overwriting existing output files")
args = parser.parse_args()

SEALED = ("data/phase12/", "data/phase16/", "data/phase17a/", "data/phase18/", "data/evaluation/", "benchmark/")


# --------------------------------------------------------------------------------- two-stage experiment (harness only)
# Measurement-only prototype of a two-stage elaboration architecture:
#   evidence -> LLM claim plan (JSON) -> DETERMINISTIC claim validation -> LLM synthesis of the VALIDATED claims only
#   -> DETERMINISTIC sentence->claim mapping with citations attached from that mapping.
# Both model calls are separate; a failure at ANY deterministic gate aborts the arm and the pipeline's existing
# fallback (the scoped extractive elaboration, arm B2) takes over. Nothing here is imported by the product.
ELAB2_MAX_CLAIMS = 6
ELAB2_MAX_SENTENCES = 6
ELAB2_CLAIM_SUPPORT_FLOOR = 0.5        # claim sentence vs the union of the excerpts the claim itself cites
ELAB2_CLAIM_IN_EVIDENCE_FLOOR = 0.6    # claim terms must exist in the supplied evidence (no new terminology)
ELAB2_CLAIM_DISTINCTIVE_FLOOR = 0.6    # distinctive (in-evidence, df <= ELAB_RARE_MAX_DF) terms must come from the cited excerpts
ELAB2_MATCH_FLOOR = 0.34               # first sentence->claim match: share of the sentence's terms covered by that claim
ELAB2_SENTENCE_COVER_FLOOR = 0.7       # sentence terms covered by the union of its matched claims
# shared grounding primitives the claim validator reuses (same semantics as the product verifier)
ELAB_RARE_MAX_DF = 2                # in-evidence terms present in at most this many excerpts count as distinctive
ELAB_ENTITY_RE = r"\b(?:\d[\w.,/-]*|[A-Z]{2,}[\w/-]*|[A-Z][a-z]+[A-Z][\w/-]*)\b"  # acronyms, numbers, identifiers

ELAB2_STUB_MODES = ("faithful", "miscited", "invented", "benefit", "markerless", "badjson",
                    "synth_markers", "synth_newfact", "synth_example", "synth_filler", "all")

TWO_STAGE_PLAN_PROMPT = """You are an SAP documentation analyst. Turn the documentation excerpts into a claim plan.

OUTPUT CONTRACT - reply with JSON only, no prose, no code fences, no heading:
{"claims": [{"claim": "<one factual sentence>", "sources": ["S1", "S3"]}]}

RULES
1. Each claim is ONE factual sentence written only with facts, terms, numbers and names taken from the excerpts named in sources.
2. sources must list one or more markers from the excerpts below - exactly the excerpt(s) that contain the facts of the claim. Never write a marker that is not in the excerpts.
3. Never add outside knowledge, benefits, advice, examples, guesses, transaction codes, numbers, URLs, guide identifiers, section names or synonyms for SAP terms.
4. At most {max_claims} claims. Prefer claims that build a coherent explanation of the topic.
5. If the excerpts support no claim, reply exactly: {"claims": []}

DOCUMENTATION EXCERPTS:

{context}

TOPIC: {question}
USER REQUEST: {request}

JSON:
"""

TWO_STAGE_SYNTH_PROMPT = """You are an SAP documentation editor. Rewrite the verified facts below as one natural, readable explanation.

RULES
1. Use ONLY the facts in the list. Never add facts, examples, benefits, numbers, names, transaction codes or advice that are not in the list.
2. Every sentence must stay supported by the fact(s) it rephrases. Do not generalize, do not speculate, do not add examples.
3. Do not write citation markers such as [S1] - citations are added later.
4. Keep the exact SAP terminology of the facts. You may join facts and add short connecting words.
5. Write 2 to {max_sentences} sentences, one paragraph, no heading, no title, no closing sentence.
6. If the list is empty, reply exactly: {no_answer}

VERIFIED FACTS:
{claims}

TOPIC: {question}
USER REQUEST: {request}

EXPLANATION:
"""


def _fill(template: str, **kw: Any) -> str:
    """Placeholder substitution that leaves literal JSON braces in the prompt alone (str.format cannot)."""
    out = template
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _conflate(token: str) -> str:
    """Crude word-form conflator for the topicality rule only (the stemmer maps 'devices' to 'devic' but 'device' to
    'device', so a question/claim pair like 'devices managed' / 'device number' would otherwise look unrelated)."""
    w = re.sub(r"[^a-z0-9]", "", (token or "").lower())
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[: -len(suf)]
            break
    if w.endswith("e") and len(w) - 1 >= 4:
        w = w[:-1]
    return w


def _conflated_terms(text: str) -> set:
    import rag_text as T
    return {_conflate(w) for w in re.findall(r"[A-Za-z0-9]+", text or "") if w.lower() not in T.STOPWORDS and len(w) > 2}


def _claim_sources(value: Any) -> List[str]:
    """Normalise the model's ``sources`` field: 'S1', '[S1][S2]', 'S1, S3' or a list of those."""
    out: List[str] = []
    if value is None:
        return out
    if isinstance(value, str):
        value = re.findall(r"S\d+", value.upper())
    if isinstance(value, (list, tuple, set)):
        for v in value:
            out += re.findall(r"S\d+", str(v).upper())
    seen: set = set()
    return [m for m in out if not (m in seen or seen.add(m))]


def parse_claim_plan(text: str) -> Dict[str, Any]:
    """Parse the stage-1 JSON liberally (small models add prose and fences); it never repairs or invents a claim."""
    raw = (text or "").strip()
    if not raw:
        return {"claims": [], "error": "EMPTY_PLAN"}
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    blob = raw[start:end + 1] if 0 <= start < end else raw
    try:
        data = json.loads(blob)
    except Exception as exc:  # noqa: BLE001 - a parse failure is a plan failure, not a crash
        m = re.search(r"\[(?:.|\n)*\]", raw)
        if not m:
            return {"claims": [], "error": f"JSON_PARSE_FAILED: {type(exc).__name__}"}
        try:
            data = json.loads(m.group(0))
        except Exception as exc2:  # noqa: BLE001
            return {"claims": [], "error": f"JSON_PARSE_FAILED: {type(exc2).__name__}"}
    if isinstance(data, dict):
        items = data.get("claims") or data.get("facts") or data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    claims: List[Dict[str, Any]] = []
    for it in (items if isinstance(items, list) else []):
        if isinstance(it, str):
            claims.append({"claim": it.strip(), "sources": []})
            continue
        if not isinstance(it, dict):
            continue
        ctext = next((str(it.get(k)) for k in ("claim", "text", "statement", "fact", "sentence") if it.get(k)), "")
        src = next((it.get(k) for k in ("sources", "source", "citations", "citation", "markers", "marker")
                    if it.get(k) is not None), [])
        claims.append({"claim": ctext.strip(), "sources": _claim_sources(src)})
    return {"claims": claims, "error": ""}


def validate_claim(claim_text: str, sources: Any, context: Any, question: str, *, base: Any = None) -> Dict[str, Any]:
    """Deterministic stage-1 check of ONE claim: markers, tokens/entities, evidence terms, support, topicality.

    Returns ``{"ok", "reasons", "metrics"}`` and never edits the claim; a rejected claim is simply not used.
    """
    import rag_generate as RG
    import rag_text as T
    base = base or RG.verify_grounding
    items = {i.marker: i for i in context.items}
    srcs = _claim_sources(sources)
    reasons: List[str] = []
    metrics: Dict[str, Any] = {"sources": srcs, "support": None, "in_evidence": None, "distinctive": None, "sentences": 0}
    if not srcs:
        return {"ok": False, "reasons": ["CLAIM_NO_SOURCE"], "metrics": metrics}
    missing = [m for m in srcs if m not in items]
    if missing:
        return {"ok": False, "reasons": ["CLAIM_INVALID_MARKER: " + ",".join(missing)], "metrics": metrics}
    evidence_terms: set = set()
    df: Dict[str, int] = {}
    for i in context.items:
        ts = T.term_set(i.text)
        evidence_terms |= ts
        for t in ts:
            df[t] = df.get(t, 0) + 1
    cited_text = "\n".join(items[m].text for m in srcs)
    cited_lower, cited_terms = cited_text.lower(), T.term_set(cited_text)
    sentences = [s for s in T.split_sentences(claim_text) if T.term_set(s)] or [claim_text]
    plan_terms, q_terms = _conflated_terms(claim_text), _conflated_terms(question)
    supports, in_evs, rares = [], [], []
    for s in sentences:
        terms = T.term_set(s)
        in_ev = (len(terms & evidence_terms) / len(terms)) if terms else 1.0
        sup = (len(terms & cited_terms) / len(terms)) if terms else 1.0
        rare = {t for t in terms if 1 <= df.get(t, 0) <= ELAB_RARE_MAX_DF}
        rare_sup = (len(rare & cited_terms) / len(rare)) if rare else 1.0
        supports.append(round(sup, 3))
        in_evs.append(round(in_ev, 3))
        rares.append(round(rare_sup, 3))
        if in_ev < ELAB2_CLAIM_IN_EVIDENCE_FLOOR:
            reasons.append(f"CLAIM_OUT_OF_EVIDENCE: {in_ev:.2f} < {ELAB2_CLAIM_IN_EVIDENCE_FLOOR}")
        if rare_sup < ELAB2_CLAIM_DISTINCTIVE_FLOOR:
            reasons.append(f"CLAIM_LOW_DISTINCTIVE: {rare_sup:.2f} < {ELAB2_CLAIM_DISTINCTIVE_FLOOR}")
        bad_entities = sorted({e for e in re.findall(ELAB_ENTITY_RE, s) if e.lower() not in cited_lower})
        if bad_entities:
            reasons.append("CLAIM_UNSUPPORTED_ENTITY: " + ",".join(bad_entities[:5]))
        bad_tokens = sorted(t for t in T.code_tokens(s) if t not in cited_text)
        if bad_tokens:
            reasons.append("CLAIM_UNSUPPORTED_TOKEN: " + ",".join(bad_tokens[:5]))
        rep = base(f"{s} " + "".join(f"[{m}]" for m in srcs), context, min_support=ELAB2_CLAIM_SUPPORT_FLOOR,
                   require_citations=True, in_page_grounding=False, citation_normalization=False)
        for v in rep.violations:
            reasons.append(f"CLAIM_{v.get('kind')}: {v.get('detail')}")
    topical = bool((plan_terms & q_terms) or (_conflated_terms(cited_text) & q_terms))
    seen: set = set()
    uniq = [r for r in reasons if not (r in seen or seen.add(r))]
    metrics.update({"support": min(supports) if supports else None,
                    "in_evidence": min(in_evs) if in_evs else None,
                    "distinctive": min(rares) if rares else None,
                    "sentences": len(sentences), "topical": topical})
    return {"ok": not uniq, "reasons": uniq, "metrics": metrics}


def validate_claim_plan(text: str, context: Any, question: str, *, base: Any = None) -> Dict[str, Any]:
    """Parse and validate every claim of a stage-1 plan. Invalid claims are rejected individually and counted.

    Off-topic handling is plan-aware: a claim that neither its own wording nor its cited excerpts relate to the asked
    topic is dropped while the plan still has topical claims; if NO claim relates to the topic the whole plan is
    rejected (``PLAN_OFF_TOPIC``) and the arm falls back.
    """
    parsed = parse_claim_plan(text)
    out: Dict[str, Any] = {"parse_error": parsed["error"], "claims": [], "validated": [], "rejected": 0}
    rows: List[Dict[str, Any]] = []
    for idx, c in enumerate(parsed["claims"]):
        v = validate_claim(c["claim"], c["sources"], context, question, base=base)
        rows.append({"index": idx, "claim": c["claim"], "sources": v["metrics"].get("sources") or [],
                     "ok": v["ok"], "reasons": v["reasons"], "metrics": v["metrics"],
                     "topical": bool(v["metrics"].get("topical"))})
    anchor = bool(_conflated_terms(question) & _conflated_terms("\n".join(i.text for i in context.items)))
    any_topical = any(r["ok"] and r["topical"] for r in rows)
    off_topic_plan = bool(anchor and rows and not any_topical)
    for r in rows:
        if r["ok"] and not off_topic_plan and anchor and not r["topical"] and any_topical:
            r["ok"], r["reasons"] = False, ["CLAIM_OFF_TOPIC"]
        out["claims"].append(r)
        if r["ok"]:
            out["validated"].append(r)
        else:
            out["rejected"] += 1
    if off_topic_plan:
        for r in out["claims"]:
            if r["ok"]:
                r["ok"], r["reasons"] = False, ["PLAN_OFF_TOPIC"]
        out["validated"] = []
        out["rejected"] = len(out["claims"])
        out["parse_error"] = out["parse_error"] or "PLAN_OFF_TOPIC"
    return out


def attach_citations(text: str, validated: List[Dict[str, Any]], context: Any, question: str) -> Dict[str, Any]:
    """Deterministic stage-2 acceptance + citation attachment.

    Every sentence of the synthesis must map back to one or more validated claims (greedy set cover over its terms),
    and its acronyms / numbers / code tokens must exist in the excerpts those claims cite. Citations are attached from
    the claim->source mapping the claim plan already carries; nothing is repaired and no marker is invented.
    """
    import rag_text as T
    items = {i.marker: i for i in context.items}
    stripped = len(re.findall(r"\[S\d+\]", text or ""))
    cleaned = re.sub(r"\s+", " ", re.sub(r"\[S\d+\]", " ", text or "")).strip()
    claims = []
    for idx, c in enumerate(validated):
        terms = T.term_set(c["claim"])
        srcs = [m for m in (c.get("metrics", {}).get("sources") or c.get("sources") or []) if m in items]
        if terms and srcs:
            claims.append({"index": idx, "claim": c["claim"], "terms": terms, "sources": srcs})
    problems: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    dropped: List[str] = []
    for s in T.split_sentences(cleaned):
        s = s.strip()
        if not s:
            continue
        terms = T.term_set(s)
        if not terms:
            dropped.append(s)
            continue
        scored = sorted(claims, key=lambda c: len(terms & c["terms"]) / len(terms), reverse=True)
        if not scored or (len(terms & scored[0]["terms"]) / len(terms)) < ELAB2_MATCH_FLOOR:
            problems.append({"kind": "SENTENCE_NOT_BACKED", "sentence": s})
            continue
        matched = [scored[0]]
        covered = terms & scored[0]["terms"]
        remaining = terms - covered
        while remaining and (len(covered) / len(terms)) < ELAB2_SENTENCE_COVER_FLOOR:
            best = max((c for c in claims if c not in matched), key=lambda c: len(remaining & c["terms"]), default=None)
            if best is None or (len(remaining & best["terms"]) / len(remaining)) < 0.25:
                break
            matched.append(best)
            covered |= (terms & best["terms"])
            remaining = terms - covered
        cover = len(covered) / len(terms)
        if cover < ELAB2_SENTENCE_COVER_FLOOR:
            problems.append({"kind": "SENTENCE_NEW_CONTENT", "detail": f"{cover:.2f} < {ELAB2_SENTENCE_COVER_FLOOR}", "sentence": s})
            continue
        cited_text = "\n".join(items[m].text for c in matched for m in c["sources"])
        cited_lower = cited_text.lower()
        bad_entities = sorted({e for e in re.findall(ELAB_ENTITY_RE, s) if e.lower() not in cited_lower})
        bad_tokens = sorted(t for t in T.code_tokens(s) if t not in cited_text)
        if bad_entities:
            problems.append({"kind": "SENTENCE_UNSUPPORTED_ENTITY", "detail": ",".join(bad_entities[:5]), "sentence": s})
            continue
        if bad_tokens:
            problems.append({"kind": "SENTENCE_UNSUPPORTED_TOKEN", "detail": ",".join(bad_tokens[:5]), "sentence": s})
            continue
        markers: List[str] = []
        for c in matched:
            for m in c["sources"]:
                if m not in markers:
                    markers.append(m)
        markers.sort(key=lambda m: int(m[1:]))
        kept.append({"text": s, "markers": markers, "claims": [c["index"] for c in matched], "coverage": round(cover, 3)})
    result: Dict[str, Any] = {"stripped_markers": stripped, "dropped": dropped, "problems": problems,
                              "sentences": kept, "claims": len(claims)}
    if problems or not kept:
        result.update({"ok": False, "answer": ""})
        return result
    result.update({"ok": True, "answer": "\n".join(f"{k['text']} " + "".join(f"[{m}]" for m in k["markers"]) for k in kept)})
    return result


class TwoStageElaborationGenerator:
    """``rag_generate``-compatible generator: claim plan -> deterministic validation -> synthesis -> citation mapping.

    Any deterministic failure returns the project's refusal text so the pipeline's own unsafe-answer handling and the
    harness's extractive fallback stay in charge. The two model calls are timed separately in ``self.stats``.
    """

    name = "llm"

    def __init__(self, client: Any, request: str, timeout: float = 20.0, num_predict: Optional[int] = None,
                 strict_plan: bool = False) -> None:
        self.client, self.request, self.timeout, self.num_predict = client, request, timeout, num_predict
        self.strict_plan = strict_plan
        self.calls: List[Dict[str, Any]] = []
        self.stats: Dict[str, Any] = {}

    def reset_request_state(self) -> None:
        if hasattr(self.client, "reset_request_state"):
            self.client.reset_request_state()

    def _model(self, prompt: str) -> Tuple[str, bool, str, float]:
        if self.num_predict is not None:
            try:
                self.client.options["num_predict"] = int(self.num_predict)
            except Exception:  # noqa: BLE001 - stubs have no options
                pass
        t0 = time.perf_counter()
        timed_out, error, raw = False, "", ""
        if self.timeout and self.timeout > 0:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self.client.generate, prompt)
            try:
                raw = future.result(timeout=self.timeout) or ""
            except concurrent.futures.TimeoutError:
                timed_out = True
            except Exception as exc:  # noqa: BLE001 - a failed call must fall back, never abort the run
                error = f"{type(exc).__name__}: {exc}"
            finally:
                pool.shutdown(wait=False)
        else:
            try:
                raw = self.client.generate(prompt) or ""
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
        return raw.strip(), timed_out, error, round((time.perf_counter() - t0) * 1000.0, 3)

    def generate(self, question: str, context: Any) -> Any:
        import rag_generate as RG
        plan_prompt = _fill(TWO_STAGE_PLAN_PROMPT, max_claims=ELAB2_MAX_CLAIMS, context=context.render(),
                            question=question, request=self.request)
        plan_fn = getattr(self.client, "plan", None)
        if callable(plan_fn):                                     # stub: it reads the real context object directly
            raw1, t1, e1, ms1 = plan_fn(context, question, self.request) or "", False, "", 0.0
        else:
            raw1, t1, e1, ms1 = self._model(plan_prompt)
        self.calls.append({"stage": "plan", "prompt": plan_prompt, "raw": raw1, "timeout": t1, "error": e1})
        plan = validate_claim_plan(raw1, context, question, base=RG.verify_grounding)
        stats: Dict[str, Any] = {
            "plan_chars": len(raw1), "plan_ms": ms1, "plan_parse_error": plan["parse_error"],
            "claims_total": len(plan["claims"]), "claims_valid": len(plan["validated"]), "claims_rejected": plan["rejected"],
            "claim_rejections": [{"index": c["index"], "claim": c["claim"][:160], "sources": c["sources"],
                                  "reasons": c["reasons"]} for c in plan["claims"] if not c["ok"]],
            "claim_sources": [c["sources"] for c in plan["claims"]],
            "claim_support": [c["metrics"].get("support") for c in plan["claims"]],
            "claim_in_evidence": [c["metrics"].get("in_evidence") for c in plan["claims"]],
            "claim_distinctive": [c["metrics"].get("distinctive") for c in plan["claims"]],
        }
        if self.strict_plan and plan["rejected"]:
            stats["abort"] = "PLAN_HAS_REJECTED_CLAIMS"
            stats["synth_ms"] = 0.0
            self.stats = stats
            return RG.GenerationResult(RG.NO_ANSWER_TEXT, True, self.name, raw1, plan_prompt, telemetry=dict(stats))
        if not plan["validated"]:
            stats["abort"] = (plan["parse_error"].split(":")[0] if plan["parse_error"] else "NO_VALID_CLAIMS")
            stats["synth_ms"] = 0.0
            self.stats = stats
            return RG.GenerationResult(RG.NO_ANSWER_TEXT, True, self.name, raw1, plan_prompt, telemetry=dict(stats))
        claims_text = "\n".join(f"{i + 1}. {c['claim']}" for i, c in enumerate(plan["validated"]))
        synth_prompt = _fill(TWO_STAGE_SYNTH_PROMPT, max_sentences=ELAB2_MAX_SENTENCES, no_answer=RG.NO_ANSWER_TEXT,
                             claims=claims_text, question=question, request=self.request)
        synth_fn = getattr(self.client, "synthesize", None)
        if callable(synth_fn):                                    # stub: it sees the validated claim texts only
            raw2, t2, e2, ms2 = synth_fn([c["claim"] for c in plan["validated"]], question, self.request) or "", False, "", 0.0
        else:
            raw2, t2, e2, ms2 = self._model(synth_prompt)
        self.calls.append({"stage": "synth", "prompt": synth_prompt, "raw": raw2, "timeout": t2, "error": e2})
        final = attach_citations(raw2, plan["validated"], context, question)
        stats.update({"synth_chars": len(raw2), "synth_ms": ms2, "stage2_markers_stripped": final["stripped_markers"],
                      "dropped_fragments": final["dropped"], "sentences_kept": len(final["sentences"]),
                      "sentence_mapping": [{"markers": k["markers"], "claims": k["claims"], "coverage": k["coverage"]}
                                           for k in final["sentences"]],
                      "final_problems": final["problems"], "abort": "" if final["ok"] else "FINAL_VALIDATION_FAILED"})
        self.stats = stats
        if not final["ok"]:
            return RG.GenerationResult(RG.NO_ANSWER_TEXT, True, self.name, raw2, synth_prompt, telemetry=dict(stats))
        return RG.GenerationResult(final["answer"], False, self.name, raw2, synth_prompt, telemetry=dict(stats))


class TwoStageStubClient:
    """Canned two-stage model for offline checks. It derives its plan from the REAL evidence it is handed, so the
    faithful mode exercises the genuine path and the hostile modes exercise every deterministic rejection class."""

    name = "llm"

    def __init__(self, mode: str = "faithful") -> None:
        self.mode = mode
        self.calls = 0

    def reset_request_state(self) -> None:
        pass

    @staticmethod
    def _facts(context: Any) -> List[Tuple[str, str]]:
        import rag_text as T
        out: List[Tuple[str, str]] = []
        for item in context.items:
            body = getattr(item, "rendered_text", None) or item.text
            lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
            if len(lines) > 1 and (">" in lines[0] or not re.search(r"[.!?]$", lines[0])):
                lines = lines[1:]                                  # a real model does not echo the heading path
            flat = re.sub(r"\s+", " ", " ".join(lines)).strip()
            sentence = next((s.strip() for s in T.split_sentences(flat)
                             if len(s.strip()) >= 40 and s.strip()[:1].isupper()
                             and s.count(";") < 2 and not re.match(r"^[A-Z][a-z]+ in [A-Z]", s.strip())), None)
            if sentence:
                out.append((item.marker, sentence))
            if len(out) >= 4:
                break
        return out

    def plan(self, context: Any, question: str, request: str) -> str:
        self.calls += 1
        if self.mode == "badjson":
            return "I am sorry, I cannot produce a JSON claim plan for this request."
        facts = self._facts(context)
        claims = [{"claim": s, "sources": [m]} for m, s in facts]
        if self.mode == "miscited" and len(facts) >= 2:
            claims = [{"claim": facts[0][1], "sources": [facts[1][0]]}] + \
                     [{"claim": s, "sources": [m]} for m, s in facts[1:3]]
        elif self.mode == "invented":
            claims.append({"claim": "Use transaction FPR9 to change the billing master data.", "sources": ["S1"]})
        elif self.mode == "benefit":
            claims.append({"claim": "This improves overall efficiency and reduces manual data-entry errors.", "sources": ["S1"]})
        elif self.mode == "markerless":
            claims.append({"claim": "The component also supports automatic processing of the documents.", "sources": []})
        return json.dumps({"claims": claims})

    def synthesize(self, claims: List[str], question: str, request: str) -> str:
        self.calls += 1
        if not claims:
            return ""

        def lower1(s: str) -> str:
            return s[:1].lower() + s[1:] if s else s

        merged = f"{claims[0].rstrip('.')}, and {lower1(claims[1])}" if len(claims) > 1 else claims[0].rstrip(".")
        text = merged.rstrip(".") + "."
        if len(claims) > 2:
            text += " " + " ".join(c if c.endswith((".", "!", "?")) else c + "." for c in claims[2:])
        if self.mode == "synth_markers":
            return f"{claims[0]} [S1] " + " ".join(claims[1:])
        if self.mode == "synth_newfact":
            return text + " The system also sends an automatic notification to the customer."
        if self.mode == "synth_example":
            return text + " For example, a customer receives a bill every month."
        if self.mode == "synth_filler":
            return text + " This is important for compliance and should be configured carefully."
        return text

    def generate(self, prompt: str) -> str:
        return ""



# ----------------------------------------------------------------------------------------------------------- runner
def _resolve(p: str) -> Path:
    path = (ROOT / p).resolve() if not os.path.isabs(p) else Path(p).resolve()
    rel = path.relative_to(ROOT).as_posix() + "/" if path.is_relative_to(ROOT) else ""
    if rel.startswith(SEALED) and not args.force:
        sys.exit(f"refusing to write {path}: sealed artifact directory. Use --force only if you are certain.")
    return path


def _write(path: Path, text: str) -> None:
    if path.exists() and not args.force:
        sys.exit(f"refusing to overwrite {path} (pass --force, or choose new --out / --markdown).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def median(rows: Iterable[Optional[float]]) -> Optional[float]:
    vals = [v for v in rows if isinstance(v, (int, float))]
    return round(statistics.median(vals), 1) if vals else None


def describe(res: Dict[str, Any], *, wall_ms: float, arm: str, topic_id: str, message: Optional[str] = None) -> Dict[str, Any]:
    dbg = res.get("debug") or {}
    pipe = dbg.get("pipeline") or {}
    grounding = pipe.get("grounding") or {}
    gen = pipe.get("generation") or {}
    answer = res.get("answer") or ""
    markers = re.findall(r"\[(S\d+)\]", answer)
    items = ((pipe.get("context") or {}).get("items")) or []
    ctx_markers = [i.get("marker") for i in items]
    sentences = grounding.get("sentences") or []
    supports = [s.get("support") for s in sentences if isinstance(s, dict) and isinstance(s.get("support"), (int, float))]
    body = re.sub(r"\[S\d+\]", " ", answer)
    uncited = 0
    for frag in (f.strip() for f in re.split(r"(?<=[.!?])\\s+|\\n+", body)):
        if frag and re.search(r"[A-Za-z0-9]", frag) and not re.search(r"\[S\d+\]", frag):
            pass
    return {
        "arm": arm, "topic_id": topic_id, "message": message,
        "status": res.get("status"), "reason": (res.get("metadata") or {}).get("reason_code"),
        "pipeline_status": (res.get("metadata") or {}).get("pipeline_status"),
        "answer": answer, "chars": len(answer), "markers": markers,
        "phantom": sorted(set(m for m in markers if m not in ctx_markers)),
        "context_markers": ctx_markers, "context_items": len(items),
        "pages": sorted({s.get("url") for s in (res.get("sources") or []) if s.get("url")}),
        "grounding": {"violations": [v.get("kind") for v in (grounding.get("violations") or [])],
                      "sentences": len(sentences),
                      "min_support": round(min(supports), 3) if supports else None,
                      "median_support": round(statistics.median(supports), 3) if supports else None},
        "generation": {k: gen.get(k) for k in ("generator", "refused") if k in gen},
        "withheld_text": (pipe.get("answer_withheld") or ""),
        "latency": dict(dbg.get("timings_ms") or {}, wall_ms=round(wall_ms, 2)),
    }


def uncited_sentences(answer: str) -> int:
    import rag_text as T
    n = 0
    for s in T.split_cited_sentences(answer or ""):
        if re.search(r"[A-Za-z0-9]", re.sub(r"\[S\d+\]", " ", s)) and not re.search(r"\[S\d+\]", s):
            n += 1
    return n


def main() -> int:
    qpath = _resolve(args.questions)
    out_path = _resolve(args.out)
    md_path = _resolve(args.markdown)
    questions = json.loads(qpath.read_text(encoding="utf-8"))
    topics = questions["topics"][: args.limit] if args.limit else questions["topics"]

    import rag_core
    import rag_elaborate as EL
    import rag_evidence as EV
    import rag_generate as RG
    import rag_pipeline as RP
    import rag_service as S

    model = args.model or rag_core.LLM_MODEL_NAME
    env: Dict[str, Any] = {"python": sys.version.split()[0], "platform": platform.platform(), "model": model,
                           "stub": args.stub, "timeout_s": args.timeout, "two_stage": True,
                           "questions_sha256": _sha256(qpath), "questions": len(topics),
                           "claim_support_floor": ELAB2_CLAIM_SUPPORT_FLOOR,
                           "claim_in_evidence_floor": ELAB2_CLAIM_IN_EVIDENCE_FLOOR,
                           "sentence_cover_floor": ELAB2_SENTENCE_COVER_FLOOR,
                           "strict_plan": bool(args.strict_plan)}
    try:
        import subprocess
        env["git_head"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa: BLE001
        env["git_head"] = None
    if args.stub == "off":
        try:
            import ollama
            tags = ollama.Client().list()
            names = [(m.get("model") or m.get("name"), m.get("digest")) for m in (tags.get("models") or [])]
            env["ollama"] = {"models": [n for n, _d in names], "digest": next((d for n, d in names if n == model), None),
                             "reachable": any(n == model for n, _d in names)}
        except Exception as exc:  # noqa: BLE001
            env["ollama"] = {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}
        if not env["ollama"].get("reachable"):
            sys.exit(f"Ollama with model {model!r} is not available here: {env['ollama']}. "
                     "Run this on the machine that hosts Ollama, or pass --stub faithful for an offline check.")
    _write(_resolve("data/phase_elaboration/two_stage_environment.json"), json.dumps(env, indent=1))

    client = None
    if args.stub == "off":
        chat = None
        if args.timeout and args.timeout > 0:
            try:
                import ollama
                chat = ollama.Client(timeout=args.timeout).chat
            except Exception as exc:  # noqa: BLE001
                print(f"note: the Ollama HTTP timeout could not be set ({type(exc).__name__}: {exc})")
        client = RG.OllamaClient(model=model, num_predict=args.num_predict, chat=chat)

    base = RP.build_pipeline(generator="extractive", config=S.production_pipeline_config())
    svc_ext = S.RagService(base, "extractive")

    def ask(svc: Any, message: str, context: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], float]:
        t0 = time.perf_counter()
        res = svc.ask(message, debug=True, context=context) if context else svc.ask(message, debug=True)
        return res, (time.perf_counter() - t0) * 1000.0

    def two_stage_service(stub_mode: str) -> Tuple[S.RagService, TwoStageElaborationGenerator]:
        this_client = client if args.stub == "off" else TwoStageStubClient(stub_mode)
        inner = TwoStageElaborationGenerator(this_client, request="", timeout=args.timeout, num_predict=args.num_predict,
                                             strict_plan=args.strict_plan)
        guard = EV.EvidenceGuard(inner, tau=EV.SHIPPED_TAU, generation_concurrency=1)
        pipe = RP.RagPipeline(base.backend, base.retriever, base.ctx, base.corpus, guard, base.count_tokens,
                              cards=list(base.cards.values()), config=EL.scoped_config(base.cfg))
        return S.RagService(pipe, "ollama"), inner

    stub_modes = [args.stub] if args.stub in ("off", "faithful") else (
        ELAB2_STUB_MODES[:-1] if args.stub == "all" else [args.stub])
    records: List[Dict[str, Any]] = []
    for topic in topics:
        tid, q, msg = topic["id"], topic["question"], topic["message"]
        rec: Dict[str, Any] = {"id": tid, "group": topic.get("group"), "question": q, "message": msg,
                               "expect": topic.get("expect"), "runs": {}}
        a, wa = ask(svc_ext, q)
        rec["runs"]["A_normal_extractive"] = describe(a, wall_ms=wa, arm="A_normal_extractive", topic_id=tid)
        ctx = {"questions": [q], "answer": a.get("answer") or ""}
        b2 = EL.scoped_pipeline(base, "elaborate", previous_answer=a.get("answer") or "", anchor=q)
        b2res, wb2 = ask(S.RagService(b2, "extractive"), q)
        rec["runs"]["B2_elaboration_extractive_scoped"] = describe(b2res, wall_ms=wb2, arm="B2_elaboration_extractive_scoped",
                                                                   topic_id=tid, message=msg)
        for mode in stub_modes:
            svc_d, gen_d = two_stage_service(mode)
            gen_d.request = msg
            d, wd = ask(svc_d, q)                                  # shipped verifier only: arm D's gates are its own
            desc = describe(d, wall_ms=wd, arm=f"D_two_stage[{mode}]", topic_id=tid, message=msg)
            desc["two_stage"] = dict(gen_d.stats)
            desc["plan_raw"] = (gen_d.calls[0]["raw"] if gen_d.calls else "")
            desc["synth_raw"] = (gen_d.calls[1]["raw"] if len(gen_d.calls) > 1 else "")
            desc["model_timeout"] = any(c.get("timeout") for c in gen_d.calls)
            desc["model_error"] = next((c.get("error") for c in gen_d.calls if c.get("error")), "")
            gates = []
            if desc["status"] != "answered":
                gates.append(desc["reason"] or desc["status"])
            if desc["status"] == "answered" and desc["phantom"]:
                gates.append("PHANTOM_MARKER")
            desc["gates"], desc["shipped"] = gates, not gates
            if gates:
                fb = dict(rec["runs"]["B2_elaboration_extractive_scoped"])
                fb["arm"], fb["fallback_because"] = f"D_effective_fallback[{mode}]", gates
                rec["runs"][f"D_effective_fallback[{mode}]"] = fb
            else:
                rec["runs"][f"D_effective_shipped[{mode}]"] = dict(desc, arm=f"D_effective_shipped[{mode}]")
            rec["runs"][f"D_two_stage[{mode}]"] = desc
        records.append(rec)
        print(f"  {tid} done")

    per_arm: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        for arm, run in rec["runs"].items():
            b = per_arm.setdefault(arm, {"n": 0, "answered": 0, "withheld": {}, "grounding_violations": {}, "phantom": 0,
                                         "uncited": 0, "citation_errors": 0})
            b["n"] += 1
            b["answered"] += 1 if run.get("status") == "answered" else 0
            if run.get("status") != "answered":
                key = run.get("reason") or run.get("status")
                b["withheld"][key] = b["withheld"].get(key, 0) + 1
            for v in (run.get("grounding") or {}).get("violations") or []:
                b["grounding_violations"][v] = b["grounding_violations"].get(v, 0) + 1
            b["phantom"] += len(run.get("phantom") or [])
            if run.get("status") == "answered":
                b["uncited"] += uncited_sentences(run.get("answer") or "")
            b["citation_errors"] += len([m for m in (run.get("markers") or []) if m not in (run.get("context_markers") or [])])
    for arm, b in per_arm.items():
        runs = [r for rec in records for k, r in rec["runs"].items() if k == arm]
        b["median_total_ms"] = median(r.get("latency", {}).get("total_ms") for r in runs)
        b["median_generate_ms"] = median(r.get("latency", {}).get("generate_ms") for r in runs)
        b["median_chars"] = median(r.get("chars") for r in runs)
        d_runs = [r for r in runs if r.get("two_stage")]
        b["median_plan_ms"] = median((r.get("two_stage") or {}).get("plan_ms") for r in d_runs)
        b["median_synth_ms"] = median((r.get("two_stage") or {}).get("synth_ms") for r in d_runs)

    ts: Dict[str, Any] = {"runs": 0, "answered": 0, "claims_total": 0, "claims_valid": 0, "claims_rejected": 0,
                          "rejection_reasons": {}, "aborts": {}, "final_failures": {}, "stage2_markers_stripped": 0,
                          "unsupported_claims": 0, "plan_parse_errors": 0}
    for rec in records:
        for arm, run in rec["runs"].items():
            if not arm.startswith("D_two_stage"):
                continue
            info = run.get("two_stage") or {}
            ts["runs"] += 1
            ts["answered"] += 1 if run.get("status") == "answered" else 0
            ts["claims_total"] += int(info.get("claims_total") or 0)
            ts["claims_valid"] += int(info.get("claims_valid") or 0)
            ts["claims_rejected"] += int(info.get("claims_rejected") or 0)
            ts["stage2_markers_stripped"] += int(info.get("stage2_markers_stripped") or 0)
            ts["plan_parse_errors"] += 1 if info.get("plan_parse_error") else 0
            for rej in info.get("claim_rejections") or []:
                for reason in rej.get("reasons") or []:
                    key = str(reason).split(":")[0]
                    ts["rejection_reasons"][key] = ts["rejection_reasons"].get(key, 0) + 1
                    if key in ("CLAIM_OUT_OF_EVIDENCE", "CLAIM_UNSUPPORTED_ENTITY", "CLAIM_UNSUPPORTED_TOKEN",
                               "CLAIM_LOW_SUPPORT", "CLAIM_LOW_DISTINCTIVE", "CLAIM_TOKEN_NOT_IN_CONTEXT",
                               "CLAIM_TOKEN_NOT_IN_CITED_CHUNK", "CLAIM_NO_SOURCE", "CLAIM_INVALID_MARKER"):
                        ts["unsupported_claims"] += 1
            if info.get("abort"):
                ts["aborts"][info["abort"]] = ts["aborts"].get(info["abort"], 0) + 1
            for p in info.get("final_problems") or []:
                key = p.get("kind")
                ts["final_failures"][key] = ts["final_failures"].get(key, 0) + 1

    payload = {"schema_version": 1,
               "experiment": "two-stage elaboration: claim plan -> deterministic validation -> synthesis -> citations (measurement only)",
               "environment": env, "questions": str(qpath.relative_to(ROOT)), "summary": {"per_arm": per_arm, "two_stage": ts},
               "records": records}
    _write(out_path, json.dumps(payload, indent=1))
    _write(md_path, _markdown(payload))
    print(json.dumps({"per_arm": {k: v for k, v in per_arm.items() if k.startswith("D")}, "two_stage": ts}, indent=1))
    print(f"\\nwrote {out_path}\\n      {md_path}")
    return 0


def _markdown(payload: Dict[str, Any]) -> str:
    env, summary, records = payload["environment"], payload["summary"], payload["records"]
    out = ["# Two-stage elaboration experiment (measurement only)", "",
           f"* Model: `{env['model']}` | stub: `{env.get('stub')}` | timeout {env.get('timeout_s')} s | "
           f"questions sha256 `{env['questions_sha256'][:12]}…` | git `{(env.get('git_head') or '')[:9]}`",
           f"* claim support floor {env['claim_support_floor']} | in-evidence floor {env['claim_in_evidence_floor']} | "
           f"sentence coverage floor {env['sentence_cover_floor']} | strict plan {env['strict_plan']}", "",
           "Architecture: evidence -> LLM claim plan (JSON) -> deterministic claim validation -> LLM synthesis of the "
           "validated claims only -> deterministic sentence->claim mapping with citations attached from the mapping. "
           "A failure at any gate falls back to the scoped extractive elaboration (B2).", "",
           "## Summary", "",
           "| arm | runs | answered | withheld | grounding violations | phantom | uncited | citation errors | "
           "median total ms | median generate ms | median chars |",
           "|---|:--:|:--:|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|"]
    for arm, b in sorted(summary["per_arm"].items()):
        out.append(f"| `{arm}` | {b['n']} | {b['answered']} | {b['withheld'] or '—'} | {b['grounding_violations'] or '—'} | "
                   f"{b['phantom']} | {b['uncited']} | {b['citation_errors']} | {b['median_total_ms']} | "
                   f"{b['median_generate_ms']} | {b['median_chars']} |")
    t = summary["two_stage"]
    out += ["", "## Two-stage metrics", "",
            f"* claim plans: {t['runs']} runs | {t['claims_valid']}/{t['claims_total']} claims valid | "
            f"{t['claims_rejected']} rejected | {t['unsupported_claims']} unsupported-class rejections | "
            f"plan parse errors {t['plan_parse_errors']}",
            f"* claim rejection reasons: {t['rejection_reasons'] or '—'}",
            f"* aborts: {t['aborts'] or '—'} | final-validation failures: {t['final_failures'] or '—'}",
            f"* stage-2 citation markers stripped: {t['stage2_markers_stripped']}", ""]
    for rec in records:
        out += [f"## {rec['id']} — {rec['question']} → *{rec['message']}*", ""]
        if rec.get("expect"):
            out += [f"*Expected:* {rec['expect']}", ""]
        for arm, run in rec["runs"].items():
            out += [f"**{arm}** — `{run.get('status')}`{(' / ' + str(run.get('reason'))) if run.get('reason') else ''}"
                    f" | {run.get('chars')} chars | {run.get('latency', {}).get('total_ms')} ms "
                    f"(gen {run.get('latency', {}).get('generate_ms')} ms) | markers {run.get('markers')}", "",
                    "```text", (run.get("answer") or "(no answer)")[:1600], "```", ""]
            if arm.startswith("D_two_stage"):
                info = run.get("two_stage") or {}
                if info:
                    out += [f"two-stage: claims {info.get('claims_valid')}/{info.get('claims_total')} valid | "
                            f"abort {info.get('abort') or '—'} | plan {info.get('plan_ms')} ms | synth {info.get('synth_ms')} ms | "
                            f"markers stripped {info.get('stage2_markers_stripped')} | sentences kept {info.get('sentences_kept')}", ""]
                if info.get("claim_rejections"):
                    out += ["```json", json.dumps(info["claim_rejections"], indent=1)[:1400], "```", ""]
    return "\\n".join(out) + "\\n"


if __name__ == "__main__":
    raise SystemExit(main())
