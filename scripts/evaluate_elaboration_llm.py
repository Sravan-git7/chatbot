#!/usr/bin/env python3
"""Measure whether the guarded LLM path can carry follow-up elaboration (measurement harness, ADDITIVE).

This script changes nothing in the product: it builds the same objects the production service builds, runs the three
arms below for every topic of ``data/phase_elaboration/elaboration_questions.json`` and writes its own reports. It
never reads or writes the frozen benchmark, the corpus or any sealed Phase-12/16/17/18 artifact.

Arms per topic (topic = a normal question, message = the follow-up the user types next):
  A   normal production answer                     svc(extractive).ask(topic)
  A2  normal answer on the LLM path                svc(ollama).ask(topic)          [reference only]
  B   shipped extractive elaboration               svc(extractive).ask(message, context={topic, A})   <- current product
  C   prototype generative elaboration             elaboration prompt over the WIDENED evidence of the same page,
                                                   through EvidenceGuard + verify_grounding + citation
                                                   normalization, then the same-page scope gate + the novelty
                                                   gate, with arm B as the mandatory fallback
  C_effective is what a user would actually see for the follow-up: C when every gate passes, otherwise B
  (with the reason recorded). Nothing unverified is ever part of any arm.

The prototype generator lives in this file only (``ElaborationLLMGenerator``); ``scripts/rag_generate.py``,
``rag_service.py``, ``rag_evidence.py`` and ``rag_elaborate.py`` are imported unchanged.

Usage
  preflight only          python scripts/evaluate_elaboration_llm.py --preflight
  real run (needs Ollama) python scripts/evaluate_elaboration_llm.py
  offline guard check     python scripts/evaluate_elaboration_llm.py --generator-llm stub --stub-mode all --out data/phase_elaboration/stub_run.json
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import os
import platform
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

TWO_STAGE_STUB_MODES = ("faithful", "miscited", "invented", "benefit", "markerless", "badjson",
                    "synth_markers", "synth_newfact", "synth_example", "synth_filler", "all")

parser = argparse.ArgumentParser(description="Follow-up elaboration measurement (additive; measures A/B/C arms).")
parser.add_argument("--questions", default="data/phase_elaboration/elaboration_questions.json")
parser.add_argument("--out", default=None)
parser.add_argument("--markdown", default=None)
parser.add_argument("--checkpoint", default="data/phase_elaboration/elaboration_run.ckpt.jsonl")
parser.add_argument("--environment", default="data/phase_elaboration/elaboration_environment.json")
parser.add_argument("--generator-llm", choices=("ollama", "stub"), default="ollama")
parser.add_argument("--stub-mode", choices=("faithful", "uncited", "phantom", "invented", "inversion", "refusal", "all"),
                    default="faithful")
parser.add_argument("--model", default=None, help="defaults to rag_core.LLM_MODEL_NAME")
parser.add_argument("--timeout", type=float, default=20.0, help="seconds per model call (0 disables the bound)")
parser.add_argument("--num-predict", type=int, default=None, help="optional cap on generated tokens")
parser.add_argument("--limit", type=int, default=None, help="only the first N topics")
parser.add_argument("--replay", default=None, help="re-validate the recorded model outputs of a run file (no model needed)")
parser.add_argument("--preflight", action="store_true", help="check the environment and exit (no generation)")
parser.add_argument("--force", action="store_true", help="allow overwriting existing output files")
parser.add_argument("--two-stage", action="store_true",
                    help="also run the two-stage claim-plan experiment (arm D; measurement only)")
parser.add_argument("--two-stage-stub", choices=TWO_STAGE_STUB_MODES, default="faithful",
                    help="question plan / synthesis stub behaviour for arm D offline checks")
parser.add_argument("--two-stage-strict-plan", action="store_true",
                    help="abort the whole claim plan when ANY claim fails validation (default: drop only that claim)")
args = parser.parse_args()

SEALED = ("data/phase12/", "data/phase16/", "data/phase17a/", "data/phase18/", "data/evaluation/", "benchmark/")
# Elaboration-specific validation layer (HARNESS ONLY - the product's verify_grounding, its 0.6 floor and every
# production call site are untouched). Synthesis legitimately merges facts from several excerpts and re-orders them, so
# a single per-sentence lexical floor against one excerpt rejects good explanations. This layer keeps every HARD check
# of the shipped verifier and replaces ONLY the support rule, with a stricter multi-condition contract:
#   1. every sentence cites at least one supplied marker                     (shipped NO_CITATION)
#   2. no marker outside the supplied evidence                               (shipped PHANTOM_MARKER)
#   3. no code token / number / identifier outside the excerpts it cites     (STRICTER than the shipped context-wide rule)
#   4. no out-of-evidence ENTITY or NUMBER (acronyms, digit-bearing tokens, identifiers) - the invention guard; plain
#      connective/paraphrase vocabulary is allowed, but only within the glue budget of rule 5
#   5. two support measurements against the UNION of the excerpts the sentence itself cites:
#        a. in-evidence support >= ELAB_IN_EVIDENCE_FLOOR   (at least half of the sentence's content terms must exist
#           in the supplied evidence; the remainder is the connective/paraphrase budget - no new terminology)
#        b. overall (cited) support >= ELAB_SUPPORT_FLOOR   (synthesis across excerpts is allowed, so this floor is
#           below the shipped 0.6: a sentence may merge facts from several cited excerpts, and evidence-wide vocabulary
#           shared by the whole page need not be re-cited in every sentence)
#      additionally the sentence's DISTINCTIVE terms (in-evidence, present in <= ELAB_RARE_MAX_DF excerpts) must be
#      covered by its own citations at the shipped 0.6 floor - so a distinctive fact may never be asserted while citing
#      only an excerpt that does not carry it
#   6. every cited marker contributes at least one term or code token        (no citation inflation)
#   7. the question is answered by the excerpts the answer cites: when the supplied evidence can echo the question's
#      own vocabulary, at least one sentence must cite an excerpt that shares a content term with the question
#      (off-topic guard); when the evidence cannot echo the question at all, the guard records ELAB_OFF_TOPIC_UNCHECKED
#      instead of rejecting a legitimately grounded answer
ELAB_SUPPORT_FLOOR = 0.45
ELAB_IN_EVIDENCE_FLOOR = 0.5
ELAB_RARE_MAX_DF = 2
ELAB_ENTITY_RE = r"\b(?:\d[\w.,/-]*|[A-Z]{2,}[\w/-]*|[A-Z][a-z]+[A-Z][\w/-]*)\b"

_ELAB_MARKER_RE = re.compile(r"\[S\d+\]")

ELAB_HARD_KINDS = ("NO_CITATION", "PHANTOM_MARKER", "TOKEN_NOT_IN_CONTEXT", "URL_NOT_IN_CONTEXT",
                   "IDENTIFIER_NOT_IN_CONTEXT", "EMPTY_ANSWER", "TOKEN_NOT_IN_CITED_CHUNK")


def validate_elaboration_grounding(answer: str, context: Any, *, question: str = "", base: Any = None,
                                   in_page_grounding: bool = True, citation_normalization: bool = True) -> Any:
    """Validate one synthesized elaboration against the evidence it cites. Returns a ``GroundingReport``.

    Hard failures are decided by the SHIPPED verifier (called here with its support floor disabled because rule 5
    replaces it); every other kind of violation keeps the shipped semantics and kind names.
    """
    import rag_generate as RG
    import rag_text as T
    base = base or RG.verify_grounding
    hard = base(answer, context, min_support=0.0, require_citations=True,
                in_page_grounding=in_page_grounding, citation_normalization=citation_normalization)
    if hard.refusal or not hard.ok:
        return hard                                            # uncited / phantom / out-of-context tokens: shipped verdict
    items = {i.marker: i for i in context.items}
    evidence_terms = set()
    df: Dict[str, int] = {}
    for i in context.items:
        item_terms = T.term_set(i.text)
        evidence_terms |= item_terms
        for t in item_terms:
            df[t] = df.get(t, 0) + 1
    q_terms = T.term_set(question)
    # the question may be lexically distant from the page (abstention-style asks), so the off-topic rule only fires
    # when the supplied evidence itself can echo the question: then every cited excerpt must address the question
    evidence_anchor = bool(q_terms & evidence_terms)
    violations = []
    notes = [] if evidence_anchor else ["ELAB_OFF_TOPIC_UNCHECKED"]
    topical = not q_terms
    for entry in hard.sentences:
        body = entry.get("text") or ""
        terms = T.term_set(body)
        if not terms:
            continue
        markers = [m for m in entry.get("markers") or [] if m in items]
        cited_terms, cited_text = set(), []
        for m in markers:
            cited_terms |= T.term_set(items[m].text)
            cited_text.append(items[m].text)
        cited_blob = "\n".join(cited_text)
        cited_lower = (cited_blob or "").lower()
        support = round((len(terms & cited_terms) / len(terms)) if terms else 1.0, 3)
        rare = {t for t in terms if 1 <= df.get(t, 0) <= ELAB_RARE_MAX_DF}   # in-evidence but not page-wide vocabulary
        rare_support = round((len(rare & cited_terms) / len(rare)) if rare else 1.0, 3)
        entry["elab_support"] = support
        entry["elab_rare_support"] = rare_support
        if T.term_set(cited_blob) & q_terms:
            topical = True
        in_evidence = round((len(terms & evidence_terms) / len(terms)) if terms else 1.0, 3)
        entry["elab_in_evidence_support"] = in_evidence
        plain = _ELAB_MARKER_RE.sub(" ", body)
        bad_entities = sorted({e for e in re.findall(ELAB_ENTITY_RE, plain) if e.lower() not in cited_lower})
        bad_tokens = sorted(t for t in T.code_tokens(body) if t not in cited_blob)
        weak = [m for m in markers if not ((T.term_set(items[m].text) & terms) or (T.code_tokens(items[m].text) & T.code_tokens(body)))]
        if bad_entities:
            violations.append({"kind": "ELAB_UNSUPPORTED_ENTITY", "detail": ", ".join(bad_entities[:8]), "sentence": body})
        if in_evidence < ELAB_IN_EVIDENCE_FLOOR:
            violations.append({"kind": "ELAB_GLUE_BUDGET_EXCEEDED",
                               "detail": f"{in_evidence:.2f} < {ELAB_IN_EVIDENCE_FLOOR}", "sentence": body})
        if bad_tokens:
            violations.append({"kind": "ELAB_UNSUPPORTED_TOKEN", "detail": ", ".join(bad_tokens[:8]), "sentence": body})
        if weak:
            violations.append({"kind": "ELAB_UNJUSTIFIED_CITATION", "detail": ", ".join(weak), "sentence": body})
        if rare_support < RG.MIN_SENTENCE_SUPPORT:
            violations.append({"kind": "ELAB_LOW_DISTINCTIVE_SUPPORT", "detail": f"{rare_support:.2f} < {RG.MIN_SENTENCE_SUPPORT}", "sentence": body})
        if support < ELAB_SUPPORT_FLOOR:
            violations.append({"kind": "ELAB_LOW_SYNTHESIS_SUPPORT", "detail": f"{support:.2f} < {ELAB_SUPPORT_FLOOR}", "sentence": body})
    if not topical:
        violations.append({"kind": "ELAB_OFF_TOPIC",
                           "detail": "no sentence cites an excerpt that shares a content term with the question",
                           "sentence": None})
    if violations:
        report = RG.GroundingReport(ok=False, refusal=False, violations=violations, sentences=hard.sentences,
                                    cited_markers=hard.cited_markers, phantom_markers=hard.phantom_markers)
    else:
        report = hard
    if notes:
        for n in notes:
            report.sentences.append({"text": None, "markers": [], "support": None, "note": n})
    return report


@contextlib.contextmanager
def elaboration_verifier(question: str):
    """Route ``rag_pipeline``'s grounding call through the elaboration validator for one arm-C request.

    The pipeline looks the verifier up at call time, so a harness-local rebind is enough; the product modules and the
    production service keep using their own imported ``verify_grounding`` exactly as before.
    """
    import rag_pipeline as RP
    original = RP.verify_grounding
    base = original

    def _wrapped(answer: str, context: Any, **kw: Any) -> Any:
        return validate_elaboration_grounding(answer, context, question=question, base=base,
                                              in_page_grounding=bool(kw.get("in_page_grounding", False)),
                                              citation_normalization=bool(kw.get("citation_normalization", False)))

    RP.verify_grounding = _wrapped
    try:
        yield
    finally:
        RP.verify_grounding = original
ELABORATION_PROMPT = """You are an SAP documentation assistant. The user has already read a short answer and now asks for a fuller explanation.

OUTPUT CONTRACT - an answer that breaks any rule below is invalid and will be rejected:
1. EVERY sentence MUST end with one or more excerpt markers. One excerpt supports it: end with [S2]. It combines facts from several excerpts: end with all of them, like [S1][S3]. Never leave a sentence without its markers.
2. Use ONLY the markers shown below, and cite the excerpt(s) that actually contain the facts of that sentence. Never write a marker that is not in the excerpts.
3. Use only facts, terms, numbers and names that appear in the excerpts. Never add outside knowledge, examples, advice, guesses, transaction codes, numbers, URLs, guide identifiers or section names - and never guess a detail the excerpts do not contain.
4. Keep the exact SAP terminology of the excerpts; you may add only short connecting words (for example: and, or, so, then, when, after, before, while, with, because, that, which, such as). Never replace a technical term with a synonym.
5. Write a real explanation, not a copy of the excerpts: merge facts that belong together into one sentence when that reads better, order them so the explanation reads as one coherent description of the topic, and connect them. Do not repeat what the short answer already said unless the explanation needs it as its starting point.
6. Format: at most six short sentences or bullets, one per line, each line ending with its marker(s). No heading, no title, no introduction, no closing sentence, and no line without markers.
7. If a line cannot be supported by the excerpts, delete the line. Never pad the answer, and never repeat a fact to make it longer.
8. If the excerpts do not contain enough information for a fuller explanation, reply with exactly: {no_answer}

CHECK BEFORE ANSWERING: every line ends with [S#] markers, and every term in it appears in the excerpt(s) it cites.

DOCUMENTATION EXCERPTS:

{context}

TOPIC: {question}
USER REQUEST: {request}

ANSWER:
"""


# ----------------------------------------------------------------------------------------------------------- safety
def _resolve(p: str) -> Path:
    path = (ROOT / p).resolve() if not os.path.isabs(p) else Path(p).resolve()
    rel = path.relative_to(ROOT).as_posix() + "/" if path.is_relative_to(ROOT) else ""
    if rel.startswith(SEALED) and not args.force:
        sys.exit(f"refusing to write {path}: sealed artifact directory. Use --force only if you are certain.")
    return path


def _write(path: Path, text: str) -> None:
    if path.exists() and not args.force:
        sys.exit(f"refusing to overwrite {path} (pass --force, or choose a new --out / --markdown / --checkpoint).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------------------------------------------------------------------------- stubs
class StubClient:
    """A canned model for offline validation of the guard chain. It only ever sees the real prompt from the real generator."""

    def __init__(self, mode: str = "faithful") -> None:
        self.mode = mode
        self.prompt = ""
        self.calls = 0

    def reset_request_state(self) -> None:
        pass

    def generate(self, prompt: str) -> str:
        self.prompt, self.calls = prompt, self.calls + 1
        import rag_generate as RG
        if self.mode == "refusal":
            return RG.NO_ANSWER_TEXT
        excerpts = re.findall(r"(?m)^\[(S\d+)\]\s*(.+)$", prompt)
        facts: List[Tuple[str, str]] = []
        for marker, _head in excerpts:
            head = re.search(rf"(?ms)^\[{marker}\]\s*(.*?)(?=^\[S\d+\]|\Z)", prompt)
            if not head:
                continue
            lines = [ln for ln in head.group(1).splitlines() if ln.strip()]
            if len(lines) > 1 and (">" in lines[0] or not re.search(r"[.!?]$", lines[0].strip())):
                lines = lines[1:]                      # a real model does not echo the heading path
            text = re.sub(r"\s+", " ", " ".join(lines)).strip()
            sentence = re.split(r"(?<=[.:])\s", text)[0]
            if sentence and (marker, sentence) not in facts:
                facts.append((marker, sentence))
        body = " ".join(f"{s} [{m}]" for m, s in facts[:3])
        if self.mode == "faithful":
            return body
        if self.mode == "uncited":
            return " ".join(s for _m, s in facts[:3])
        if self.mode == "phantom":
            return body + " The account is closed automatically. [S99]"
        if self.mode == "invented":
            return body + " Use transaction FPR9 to change this. [S1]"
        if self.mode == "inversion":
            first = facts[0][1] if facts else "This is required."
            flipped = re.sub(r"\bcan\b", "cannot", first) if re.search(r"\bcan\b", first) else f"It is not true that {first[0].lower()}{first[1:]}"
            return f"{flipped} [{facts[0][0]}]" if facts else flipped
        return body


# ----------------------------------------------------------------------------------------------------------- prototype generator (this file only)
class ElaborationLLMGenerator:
    """``rag_generate.LLMGenerator`` with the elaboration prompt. Same client, same refusal rule, same telemetry shape."""

    name = "llm"

    def __init__(self, client: Any, request: str, timeout: float = 20.0, num_predict: Optional[int] = None) -> None:
        self.client, self.request, self.timeout, self.num_predict = client, request, timeout, num_predict
        self.calls: List[Dict[str, Any]] = []

    def reset_request_state(self) -> None:
        if hasattr(self.client, "reset_request_state"):
            self.client.reset_request_state()

    def generate(self, question: str, context: Any) -> Any:
        import rag_generate as RG
        import rag_core
        prompt = ELABORATION_PROMPT.format(no_answer=RG.NO_ANSWER_TEXT, context=context.render(),
                                           question=question, request=self.request)
        t_p0 = time.perf_counter()
        prompt_build_ms = round((time.perf_counter() - t_p0) * 1000.0, 3)
        if self.num_predict is not None:
            try:
                self.client.options["num_predict"] = int(self.num_predict)
            except Exception:  # noqa: BLE001 - stubs have no options
                pass
        t_g0 = time.perf_counter()
        timed_out, error = False, ""
        if self.timeout and self.timeout > 0:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self.client.generate, prompt)
            try:
                raw = future.result(timeout=self.timeout) or ""
            except concurrent.futures.TimeoutError:
                raw, timed_out = "", True
            except Exception as exc:                                   # noqa: BLE001 - a failed call must fall back, never abort the run
                raw, error = "", f"{type(exc).__name__}: {exc}"
            finally:
                pool.shutdown(wait=False)                              # never block on a stuck call (the client also has an HTTP timeout)
        else:
            try:
                raw = self.client.generate(prompt) or ""
            except Exception as exc:                                   # noqa: BLE001
                raw, error = "", f"{type(exc).__name__}: {exc}"
        http_ms = round((time.perf_counter() - t_g0) * 1000.0, 3)
        text = raw.strip()
        refused = timed_out or bool(error) or RG.NO_ANSWER_TEXT.lower() in text.lower() or not text
        client_tel = getattr(self.client, "last_telemetry", None)
        tel = dict(client_tel) if isinstance(client_tel, dict) else {}
        tel.update({"prompt_build_ms": prompt_build_ms, "ollama_http_ms": http_ms, "context_chars": len(context.render()),
                    "prompt_chars": len(prompt), "output_chars": len(text), "model": getattr(self.client, "model", "stub"),
                    "timeout": timed_out, "error": error})
        self.calls.append({"prompt": prompt, "raw": text, "timeout": timed_out, "error": error})
        return RG.GenerationResult(RG.NO_ANSWER_TEXT if refused else text, refused, self.name, raw, prompt, telemetry=tel)


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


# ----------------------------------------------------------------------------------------------------------- helpers
MARKER_RE = re.compile(r"\[S\d+\]")


def _sentences(text: str) -> List[str]:
    """Sentence-ish fragments that carry content: a fragment consisting only of markers (``[S2]``) is not a sentence."""
    out: List[str] = []
    for frag in re.split(r"(?<=[.!?:])\s+|\n+", text or ""):
        frag = frag.strip()
        if frag and re.search(r"[A-Za-z0-9]", MARKER_RE.sub("", frag)):
            out.append(frag)
    return out


def _terms(text: str) -> set:
    """Content words only - citation markers are not content, so a sentence repeated under a different marker is a repeat."""
    return set(re.findall(r"[a-z0-9]+", MARKER_RE.sub(" ", text or "").lower()))


def novelty_vs(previous: str, answer: str) -> Dict[str, Any]:
    """How much of ``answer`` is not already in ``previous`` (sentence-level, deterministic)."""
    prev = [_terms(s) for s in _sentences(previous)]
    new = []
    for s in _sentences(answer):
        t = _terms(s)
        if not any(t and len(t & p) / len(t) >= 0.6 for p in prev):
            new.append(s)
    return {"new_sentences": len(new), "sentences": len(_sentences(answer))}


def similarity(a: str, b: str) -> float:
    ta, tb = _terms(a), _terms(b)
    return round(len(ta & tb) / max(1, len(ta | tb)), 3)


def fu_view(message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    import rag_followup as FU
    try:
        fu = FU.resolve(message, context)
    except Exception as exc:  # noqa: BLE001 - the resolver is total, but a measurement must not crash the run
        return {"error": f"{type(exc).__name__}: {exc}"}
    if not fu:
        try:
            return {"resolved": False, "classify": FU.classify(message)}
        except Exception:  # noqa: BLE001
            return {"resolved": False}
    return {"resolved": True, "category": fu.get("category"), "form": fu.get("form"), "anchor": fu.get("anchor"),
            "resolved_query": fu.get("query")}


def describe(res: Dict[str, Any], *, wall_ms: float, arm: str, topic_id: str, message: Optional[str] = None) -> Dict[str, Any]:
    dbg = res.get("debug") or {}
    pipe = dbg.get("pipeline") or {}
    grounding = pipe.get("grounding") or {}
    gen = pipe.get("generation") or {}
    answer = res.get("answer") or ""
    markers = re.findall(r"\[(S\d+)\]", answer)
    items = ((pipe.get("context") or {}).get("items")) or []
    ctx_markers = [i.get("marker") for i in items]
    sources = [{"marker": s.get("marker"), "title": s.get("title"), "section": s.get("section"), "url": s.get("url")}
               for s in (res.get("sources") or [])]
    violations = [v.get("kind") for v in (grounding.get("violations") or [])]
    sentences = grounding.get("sentences") or []
    supports = [s.get("support") for s in sentences if isinstance(s, dict) and isinstance(s.get("support"), (int, float))]
    return {
        "arm": arm, "topic_id": topic_id, "message": message,
        "status": res.get("status"), "reason": (res.get("metadata") or {}).get("reason_code"),
        "pipeline_status": (res.get("metadata") or {}).get("pipeline_status"),
        "answer": answer, "chars": len(answer), "markers": markers,
        "phantom": sorted(set(m for m in markers if m not in ctx_markers)),
        "context_markers": ctx_markers, "context_items": len(items),
        "sources": sources, "pages": sorted({s["url"] for s in sources if s.get("url")}),
        "grounding": {"violations": violations, "sentences": len(sentences),
                      "min_support": round(min(supports), 3) if supports else None,
                      "median_support": round(statistics.median(supports), 3) if supports else None},
        "generation": {k: gen.get(k) for k in ("generator", "refused") if k in gen},
        "withheld_text": (pipe.get("answer_withheld") or ""),
        "elab_floor": ELAB_SUPPORT_FLOOR,
        "sentence_support": [{"support": s.get("support"), "elab_support": s.get("elab_support"), "markers": s.get("markers")}
                             for s in sentences],
        "latency": dict(dbg.get("timings_ms") or {}, wall_ms=round(wall_ms, 2)),
    }


def median(rows: Iterable[Optional[float]]) -> Optional[float]:
    vals = [v for v in rows if isinstance(v, (int, float))]
    return round(statistics.median(vals), 1) if vals else None


# ----------------------------------------------------------------------------------------------------------- environment
def preflight(model: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {"python": sys.version.split()[0], "platform": platform.platform(),
                            "generator_llm": args.generator_llm,
                            "stub_mode": (args.stub_mode if args.generator_llm == "stub" else None),
                            "two_stage": bool(args.two_stage),
                            "two_stage_stub": (args.two_stage_stub if args.two_stage and args.generator_llm == "stub" else None),
                            "two_stage_strict_plan": bool(args.two_stage_strict_plan),
                            "model": model, "timeout_s": args.timeout, "num_predict": args.num_predict,
                            "git_head": None, "ollama": {"import": False, "reachable": False, "models": [], "digest": None}}
    try:
        import subprocess
        info["git_head"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa: BLE001
        pass
    try:
        import ollama
        info["ollama"]["import"] = True
        client = ollama.Client()
        tags = client.list()
        models = [(m.get("model") or m.get("name"), m.get("digest")) for m in (tags.get("models") or [])]
        info["ollama"]["models"] = [m for m, _d in models]
        info["ollama"]["digest"] = next((d for m, d in models if m == model), None)
        info["ollama"]["reachable"] = any(m == model for m, _d in models)
    except Exception as exc:  # noqa: BLE001
        info["ollama"]["error"] = f"{type(exc).__name__}: {exc}"
        try:
            urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3).read()
            info["ollama"]["http"] = True
        except Exception as exc2:  # noqa: BLE001
            info["ollama"]["http_error"] = f"{type(exc2).__name__}: {exc2}"
    return info


# ----------------------------------------------------------------------------------------------------------- run
def main() -> int:
    qpath = _resolve(args.questions)
    out_path = _resolve(args.out or ("data/phase_elaboration/elaboration_replay.json" if args.replay
                                     else "data/phase_elaboration/elaboration_run.json"))
    md_path = _resolve(args.markdown or ("data/phase_elaboration/elaboration_replay_report.md" if args.replay
                                         else "data/phase_elaboration/elaboration_report.md"))
    ck_path, env_path = _resolve(args.checkpoint), _resolve(args.environment)
    questions = json.loads(qpath.read_text(encoding="utf-8"))
    topics = questions["topics"][: args.limit] if args.limit else questions["topics"]

    import rag_core
    model = args.model or rag_core.LLM_MODEL_NAME
    env = preflight(model)
    env["questions_sha256"] = _sha256(qpath)
    env["questions"] = len(topics)
    _write(env_path, json.dumps(env, indent=1))
    print(json.dumps({"environment": env_path.name, "ollama": env["ollama"], "model": model}, indent=1))
    if args.preflight:
        return 0
    if args.replay:
        return run_replay(_resolve(args.replay), out_path, md_path, topics)
    if args.generator_llm == "ollama" and not env["ollama"].get("reachable"):
        sys.exit(f"Ollama with model {model!r} is not available here: {env['ollama']}. "
                 "Run this on the machine that hosts Ollama, or use --generator-llm stub for the offline guard check.")

    import rag_elaborate as EL
    import rag_evidence as EV
    import rag_generate as RG
    import rag_pipeline as RP
    import rag_service as S

    chat = None
    if args.generator_llm == "ollama" and args.timeout and args.timeout > 0:
        try:
            import ollama
            chat = ollama.Client(timeout=args.timeout).chat          # a real per-call HTTP bound as well
        except Exception as exc:                                     # noqa: BLE001 - the elab generator still bounds every call itself
            print(f"note: the Ollama HTTP timeout could not be set ({type(exc).__name__}: {exc})")
    client = (RG.OllamaClient(model=model, num_predict=args.num_predict, chat=chat)
              if args.generator_llm == "ollama" else StubClient(args.stub_mode))
    base = RP.build_pipeline(generator="extractive", config=S.production_pipeline_config())
    cfg = S.production_pipeline_config()
    svc_ext = S.RagService(EV.build_evidence_pipeline(base, tau=EV.SHIPPED_TAU, widen=False, generator="extractive"), "extractive")
    svc_llm = None
    if args.generator_llm == "ollama":
        svc_llm = S.RagService(EV.build_evidence_pipeline(base, tau=EV.SHIPPED_TAU, widen=False, generator="ollama",
                                                          llm_client=client), "ollama")
    stub_modes = [args.stub_mode] if args.generator_llm == "ollama" or args.stub_mode != "all" else \
        ["faithful", "uncited", "phantom", "invented", "inversion", "refusal"]

    def ask(svc: Any, message: str, context: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], float]:
        t0 = time.perf_counter()
        res = svc.ask(message, debug=True, context=context) if context else svc.ask(message, debug=True)
        wall = (time.perf_counter() - t0) * 1000.0
        res["_wall_ms"] = wall
        return res, wall

    def scoped_service(stub_mode: str) -> Tuple[S.RagService, ElaborationLLMGenerator]:
        this_client = client if args.generator_llm == "ollama" else StubClient(stub_mode)
        inner = ElaborationLLMGenerator(this_client, request="", timeout=args.timeout, num_predict=args.num_predict)
        guard = EV.EvidenceGuard(inner, tau=EV.SHIPPED_TAU, generation_concurrency=1)
        pipe = RP.RagPipeline(base.backend, base.retriever, base.ctx, base.corpus, guard, base.count_tokens,
                              cards=list(base.cards.values()), config=EL.scoped_config(base.cfg))
        return S.RagService(pipe, "ollama"), inner

    def two_stage_service(two_stage_mode: str) -> Tuple[S.RagService, TwoStageElaborationGenerator]:
        this_client = client if args.generator_llm == "ollama" else TwoStageStubClient(two_stage_mode)
        inner = TwoStageElaborationGenerator(this_client, request="", timeout=args.timeout, num_predict=args.num_predict,
                                             strict_plan=args.two_stage_strict_plan)
        guard = EV.EvidenceGuard(inner, tau=EV.SHIPPED_TAU, generation_concurrency=1)
        pipe = RP.RagPipeline(base.backend, base.retriever, base.ctx, base.corpus, guard, base.count_tokens,
                              cards=list(base.cards.values()), config=EL.scoped_config(base.cfg))
        return S.RagService(pipe, "ollama"), inner

    two_stage_modes: List[str] = [] if not args.two_stage else (
        list(ELAB2_STUB_MODES[:-1]) if args.two_stage_stub == "all" else [args.two_stage_stub])

    records: List[Dict[str, Any]] = []
    checkpoint = ck_path.open("a", encoding="utf-8")
    checkpoint.write(json.dumps({"header": {"model": model, "generator_llm": args.generator_llm, "stub_modes": stub_modes,
                                            "two_stage": bool(args.two_stage), "two_stage_modes": two_stage_modes,
                                            "questions_sha256": env["questions_sha256"], "git_head": env["git_head"]}}) + "\n")

    for topic in topics:
        tid, q, msg = topic["id"], topic["question"], topic["message"]
        rec: Dict[str, Any] = {"id": tid, "group": topic.get("group"), "question": q, "message": msg,
                               "expect": topic.get("expect"), "runs": {}, "fu": {}}
        a, wa = ask(svc_ext, q)
        rec["runs"]["A_normal_extractive"] = describe(a, wall_ms=wa, arm="A_normal_extractive", topic_id=tid)
        ctx = {"questions": [q], "answer": a.get("answer") or ""}
        rec["fu"] = fu_view(msg, ctx)
        if svc_llm is not None:
            a2, wa2 = ask(svc_llm, q)
            rec["runs"]["A2_normal_llm"] = describe(a2, wall_ms=wa2, arm="A2_normal_llm", topic_id=tid)
        b, wb = ask(svc_ext, msg, ctx)
        rec["runs"]["B_elaboration_extractive_shipped"] = describe(b, wall_ms=wb, arm="B_elaboration_extractive_shipped",
                                                                  topic_id=tid, message=msg)
        rec["runs"]["B_elaboration_extractive_shipped"]["novelty_vs_A"] = novelty_vs(a.get("answer") or "", b.get("answer") or "")
        rec["runs"]["B_elaboration_extractive_shipped"]["similarity_vs_A"] = similarity(a.get("answer") or "", b.get("answer") or "")

        # Page-scoped extractive elaboration: the same intent-aware pass the product runs, but always anchored to the
        # topic's own page (pipeline query = the anchor question). This is the fallback the generative arm must use:
        # the shipped B can leave the page when the resolver does not recognise the message (measured on EL-005).
        intent = (rec["fu"].get("category") if rec["fu"].get("resolved") else None) or "elaborate"
        scope_ext = EL.scoped_pipeline(base, intent, previous_answer=a.get("answer") or "", anchor=q)
        b2, wb2 = ask(S.RagService(scope_ext, "extractive"), q)
        rec["runs"]["B2_elaboration_extractive_scoped"] = describe(b2, wall_ms=wb2, arm="B2_elaboration_extractive_scoped",
                                                                   topic_id=tid, message=msg)
        rec["runs"]["B2_elaboration_extractive_scoped"]["novelty_vs_A"] = novelty_vs(a.get("answer") or "", b2.get("answer") or "")
        rec["runs"]["B2_elaboration_extractive_scoped"]["similarity_vs_A"] = similarity(a.get("answer") or "", b2.get("answer") or "")

        for mode in stub_modes:
            svc_c, gen_c = scoped_service(mode)
            gen_c.request = msg
            with elaboration_verifier(q):               # harness-local: only this arm-C request uses the elaboration validator
                c, wc = ask(svc_c, q)                   # the anchor question is the pipeline query: the same page as A
            desc = describe(c, wall_ms=wc, arm=f"C_generative_elaboration[{mode}]", topic_id=tid, message=msg)
            desc["novelty_vs_A"] = novelty_vs(a.get("answer") or "", c.get("answer") or "")
            desc["similarity_vs_A"] = similarity(a.get("answer") or "", c.get("answer") or "")
            desc["model_raw"] = (gen_c.calls[-1]["raw"] if gen_c.calls else "")
            desc["model_timeout"] = bool(gen_c.calls and gen_c.calls[-1]["timeout"])
            desc["model_error"] = (gen_c.calls[-1].get("error") if gen_c.calls else "")
            gate_reasons = []
            if desc["status"] != "answered":
                gate_reasons.append(desc["reason"] or desc["status"])
            if desc["status"] == "answered":
                if desc["phantom"]:
                    gate_reasons.append("PHANTOM_MARKER")
                a_pages = set(rec["runs"]["A_normal_extractive"]["pages"])
                if a_pages and not set(desc["pages"]) <= a_pages:
                    gate_reasons.append("SCOPE_PAGE_CHANGED")
                if desc["novelty_vs_A"]["new_sentences"] < 1:
                    gate_reasons.append("NO_NEW_EVIDENCE")
            desc["gates"] = gate_reasons
            desc["shipped"] = not gate_reasons
            if gate_reasons:
                fallback = dict(rec["runs"]["B2_elaboration_extractive_scoped"])
                fallback["arm"] = f"C_effective_fallback[{mode}]"
                fallback["fallback_because"] = gate_reasons
                rec["runs"][f"C_effective_fallback[{mode}]"] = fallback
            else:
                effective = dict(desc, arm=f"C_effective_shipped[{mode}]")
                rec["runs"][f"C_effective_shipped[{mode}]"] = effective
            rec["runs"][f"C_generative_elaboration[{mode}]"] = desc

        for tmode in two_stage_modes:
            svc_d, gen_d = two_stage_service(tmode)
            gen_d.request = msg
            d, wd = ask(svc_d, q)                       # shipped verifier only: arm D's extra gates are its own deterministic checks
            desc = describe(d, wall_ms=wd, arm=f"D_two_stage[{tmode}]", topic_id=tid, message=msg)
            desc["novelty_vs_A"] = novelty_vs(a.get("answer") or "", d.get("answer") or "")
            desc["similarity_vs_A"] = similarity(a.get("answer") or "", d.get("answer") or "")
            desc["two_stage"] = dict(gen_d.stats)
            desc["plan_raw"] = (gen_d.calls[0]["raw"] if gen_d.calls else "")
            desc["synth_raw"] = (gen_d.calls[1]["raw"] if len(gen_d.calls) > 1 else "")
            desc["model_timeout"] = any(c.get("timeout") for c in gen_d.calls)
            desc["model_error"] = next((c.get("error") for c in gen_d.calls if c.get("error")), "")
            gate_reasons = []
            if desc["status"] != "answered":
                gate_reasons.append(desc["reason"] or desc["status"])
            if desc["status"] == "answered":
                if desc["phantom"]:
                    gate_reasons.append("PHANTOM_MARKER")
                a_pages = set(rec["runs"]["A_normal_extractive"]["pages"])
                if a_pages and not set(desc["pages"]) <= a_pages:
                    gate_reasons.append("SCOPE_PAGE_CHANGED")
                if desc["novelty_vs_A"]["new_sentences"] < 1:
                    gate_reasons.append("NO_NEW_EVIDENCE")
            desc["gates"] = gate_reasons
            desc["shipped"] = not gate_reasons
            if gate_reasons:
                fallback = dict(rec["runs"]["B2_elaboration_extractive_scoped"])
                fallback["arm"] = f"D_effective_fallback[{tmode}]"
                fallback["fallback_because"] = gate_reasons
                rec["runs"][f"D_effective_fallback[{tmode}]"] = fallback
            else:
                rec["runs"][f"D_effective_shipped[{tmode}]"] = dict(desc, arm=f"D_effective_shipped[{tmode}]")
            rec["runs"][f"D_two_stage[{tmode}]"] = desc
        records.append(rec)
        checkpoint.write(json.dumps({"id": tid, "record": rec}) + "\n")
        checkpoint.flush()
        print(f"  {tid} done ({len(rec['runs'])} runs)")
    checkpoint.close()

    summary = _summarise(records)
    payload = {"schema_version": 1, "experiment": "follow-up elaboration: extractive vs guarded generative (measurement only)",
               "environment": env, "questions": str(qpath.relative_to(ROOT)), "summary": summary, "records": records}
    _write(out_path, json.dumps(payload, indent=1))
    _write(md_path, _markdown(payload))
    print(json.dumps({k: summary[k] for k in ("per_arm", "generative_gate_outcomes")}, indent=1))
    print(f"\nwrote {out_path}\n      {md_path}\n      {env_path}\n      {ck_path}")
    return 0


def run_replay(source: Path, out_path: Path, md_path: Path, topics: List[Dict[str, Any]]) -> int:
    """Re-validate the model outputs recorded in ``source`` under the CURRENT validation layer - no model needed.

    For every recorded ``C_generative_elaboration[...]`` entry that stored its raw model text, the exact arm-C request
    is repeated with that text as the model output, so the elaboration validator decides again on the same bytes. The
    extractive arms (A / B / B2) are taken from the file: they are deterministic and need no model.
    """
    import rag_elaborate as EL
    import rag_evidence as EV
    import rag_pipeline as RP
    import rag_service as S

    src = json.loads(source.read_text(encoding="utf-8"))
    by_id = {r.get("id"): r for r in src.get("records", [])}
    base = RP.build_pipeline(generator="extractive", config=S.production_pipeline_config())

    class ReplayClient:
        name = "llm"

        def __init__(self) -> None:
            self.raw = ""

        def reset_request_state(self) -> None:
            pass

        def generate(self, prompt: str) -> str:
            return self.raw

    records, replayed = [], 0
    for topic in topics:
        old = by_id.get(topic["id"])
        if not old:
            continue
        rec: Dict[str, Any] = {"id": topic["id"], "group": topic.get("group"), "question": topic["question"],
                               "message": topic["message"], "expect": topic.get("expect"), "fu": old.get("fu"),
                               "replay_of": source.name, "runs": {}}
        for arm in ("A_normal_extractive", "A2_normal_llm", "B_elaboration_extractive_shipped", "B2_elaboration_extractive_scoped"):
            if arm in (old.get("runs") or {}):
                rec["runs"][arm] = old["runs"][arm]
        for key, run in (old.get("runs") or {}).items():
            if not key.startswith("C_generative_elaboration[") or not (run.get("model_raw") or "").strip():
                continue
            mode = key[key.index("[") + 1:-1]
            client = ReplayClient()
            client.raw = run["model_raw"]
            inner = ElaborationLLMGenerator(client, request=topic["message"], timeout=args.timeout)
            guard = EV.EvidenceGuard(inner, tau=EV.SHIPPED_TAU, generation_concurrency=1)
            pipe = RP.RagPipeline(base.backend, base.retriever, base.ctx, base.corpus, guard, base.count_tokens,
                                  cards=list(base.cards.values()), config=EL.scoped_config(base.cfg))
            with elaboration_verifier(topic["question"]):
                c = S.RagService(pipe, "ollama").ask(topic["question"], debug=True)
            desc = describe(c, wall_ms=0.0, arm=f"C_generative_elaboration[{mode}]", topic_id=topic["id"], message=topic["message"])
            desc["model_raw"] = run["model_raw"]
            desc["recorded_status"] = run.get("status")
            desc["recorded_violations"] = (run.get("grounding") or {}).get("violations") or []
            desc["novelty_vs_A"] = novelty_vs((rec["runs"].get("A_normal_extractive") or {}).get("answer") or "", c.get("answer") or "")
            desc["similarity_vs_A"] = similarity((rec["runs"].get("A_normal_extractive") or {}).get("answer") or "", c.get("answer") or "")
            gates = []
            if desc["status"] != "answered":
                gates.append(desc["reason"] or desc["status"])
            else:
                if desc["phantom"]:
                    gates.append("PHANTOM_MARKER")
                a_pages = set((rec["runs"].get("A_normal_extractive") or {}).get("pages") or [])
                if a_pages and not set(desc["pages"]) <= a_pages:
                    gates.append("SCOPE_PAGE_CHANGED")
                if desc["novelty_vs_A"]["new_sentences"] < 1:
                    gates.append("NO_NEW_EVIDENCE")
            desc["gates"], desc["shipped"] = gates, not gates
            b2 = rec["runs"].get("B2_elaboration_extractive_scoped")
            if gates and b2:
                fb = dict(b2)
                fb["arm"], fb["fallback_because"] = f"C_effective_fallback[{mode}]", gates
                rec["runs"][f"C_effective_fallback[{mode}]"] = fb
            elif not gates:
                rec["runs"][f"C_effective_shipped[{mode}]"] = dict(desc, arm=f"C_effective_shipped[{mode}]")
            rec["runs"][key] = desc
            replayed += 1
        records.append(rec)
    summary = _summarise(records)
    payload = {"schema_version": 1, "experiment": "REPLAY - recorded model outputs re-validated under the elaboration validator",
               "environment": {"replay_of": str(source), "generator_llm": "replay", "model": (src.get("environment") or {}).get("model"),
                               "timeout_s": (src.get("environment") or {}).get("timeout_s"),
                               "questions_sha256": (src.get("environment") or {}).get("questions_sha256"),
                               "questions": len(topics), "git_head": (src.get("environment") or {}).get("git_head"),
                               "elab_support_floor": ELAB_SUPPORT_FLOOR},
               "questions": str(source), "summary": summary, "records": records}
    _write(out_path, json.dumps(payload, indent=1))
    _write(md_path, _markdown(payload))
    print(json.dumps({"per_arm": summary["per_arm"], "generative_gate_outcomes": summary["generative_gate_outcomes"]}, indent=1))
    print(f"\nreplayed {replayed} recorded model outputs from {source}\nwrote {out_path}\n      {md_path}")
    return 0


def _summarise(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    per_arm: Dict[str, Dict[str, Any]] = {}
    gate_counts: Dict[str, int] = {}
    for rec in records:
        for arm, run in rec["runs"].items():
            bucket = per_arm.setdefault(arm, {"n": 0, "answered": 0, "withheld": {}, "grounding_violations": {}, "phantom": 0})
            bucket["n"] += 1
            if run.get("status") == "answered":
                bucket["answered"] += 1
            else:
                reason = run.get("reason") or run.get("status")
                bucket["withheld"][reason] = bucket["withheld"].get(reason, 0) + 1
            for v in run.get("grounding", {}).get("violations") or []:
                bucket["grounding_violations"][v] = bucket["grounding_violations"].get(v, 0) + 1
            bucket["phantom"] += len(run.get("phantom") or [])
            if arm.startswith(("C_generative", "D_two_stage")):
                for g in run.get("gates") or []:
                    gate_counts[g] = gate_counts.get(g, 0) + 1
    for arm, bucket in per_arm.items():
        runs = [r for rec in records for k, r in rec["runs"].items() if k == arm]
        bucket["median_total_ms"] = median(r.get("latency", {}).get("total_ms") for r in runs)
        bucket["median_generate_ms"] = median(r.get("latency", {}).get("generate_ms") for r in runs)
        bucket["median_chars"] = median(r.get("chars") for r in runs)
        bucket["markers_total"] = sum(len(r.get("markers") or []) for r in runs)
    ts: Dict[str, Any] = {"runs": 0, "answered": 0, "plans_with_parse_error": 0, "claims_total": 0, "claims_valid": 0,
                          "claims_rejected": 0, "claim_rejection_reasons": {}, "claims_per_run": [],
                          "stage2_markers_stripped": 0, "final_validation_failures": {}, "aborts": {},
                          "sentences_kept": 0, "citation_errors": 0, "uncited_sentences": 0}
    for rec in records:
        for arm, run in rec["runs"].items():
            if not arm.startswith("D_two_stage"):
                continue
            info = run.get("two_stage") or {}
            ts["runs"] += 1
            ts["answered"] += 1 if run.get("status") == "answered" else 0
            ts["plans_with_parse_error"] += 1 if info.get("plan_parse_error") else 0
            ts["claims_total"] += int(info.get("claims_total") or 0)
            ts["claims_valid"] += int(info.get("claims_valid") or 0)
            ts["claims_rejected"] += int(info.get("claims_rejected") or 0)
            ts["claims_per_run"].append(int(info.get("claims_total") or 0))
            for rej in info.get("claim_rejections") or []:
                for reason in rej.get("reasons") or []:
                    key = str(reason).split(":")[0]
                    ts["claim_rejection_reasons"][key] = ts["claim_rejection_reasons"].get(key, 0) + 1
            ts["stage2_markers_stripped"] += int(info.get("stage2_markers_stripped") or 0)
            ts["sentences_kept"] += int(info.get("sentences_kept") or 0)
            for p in info.get("final_problems") or []:
                key = p.get("kind")
                ts["final_validation_failures"][key] = ts["final_validation_failures"].get(key, 0) + 1
            if info.get("abort"):
                ts["aborts"][info["abort"]] = ts["aborts"].get(info["abort"], 0) + 1
            answer = run.get("answer") or ""
            if run.get("status") == "answered":
                import rag_text as _T2                                      # sentence split that keeps trailing [S#] markers
                for s_ in _T2.split_cited_sentences(answer):
                    body = MARKER_RE.sub(" ", s_).strip()
                    if not re.search(r"[A-Za-z0-9]", body):
                        continue
                    if not re.search(r"\[S\d+\]", s_):
                        ts["uncited_sentences"] += 1
            markers = run.get("markers") or []
            ts["citation_errors"] += len([m for m in markers if m not in (run.get("context_markers") or [])])
            ts["citation_errors"] += 0 if not markers else sum(1 for x in (run.get("grounding", {}).get("violations") or [])
                                                               if x in ("NO_CITATION", "PHANTOM_MARKER"))
    return {"topics": len(records), "per_arm": per_arm, "generative_gate_outcomes": gate_counts, "two_stage": ts}


def _markdown(payload: Dict[str, Any]) -> str:
    env, summary, records = payload["environment"], payload["summary"], payload["records"]
    out = ["# Follow-up elaboration: extractive vs guarded generative (measurement run)", "",
           f"* Model: `{env['model']}` | LLM source: `{env['generator_llm']}`"
           + (f" (stub mode: {env.get('stub_mode')})" if env["generator_llm"] == "stub" else "")
           + f" | timeout {env.get('timeout_s')} s | questions sha256 `{(env.get('questions_sha256') or '')[:12]}…` | git `{(env.get('git_head') or '')[:9]}`",
           f"* Ollama: {json.dumps(env.get('ollama') or {'source': 'replay - no model contacted'})}", "",
           "Arms: **A** normal production answer · **A2** normal answer on the LLM path · **B** shipped extractive elaboration · "
           "**B2** page-scoped extractive elaboration (proposed fallback) · "
           "**C** prototype generative elaboration (widened evidence + EvidenceGuard + grounding + scope/novelty gates) · "
           "**C_effective** what the user would see (C when every gate passes, otherwise B2).", "",
           "## Summary", "",
           "| arm | runs | answered | withheld | grounding violations | phantom | median total ms | median generate ms | median chars |",
           "|---|:--:|:--:|---|:--:|:--:|:--:|:--:|:--:|"]
    for arm, b in sorted(summary["per_arm"].items()):
        out.append(f"| `{arm}` | {b['n']} | {b['answered']} | {b['withheld'] or '—'} | {b['grounding_violations'] or '—'} | "
                   f"{b['phantom']} | {b['median_total_ms']} | {b['median_generate_ms']} | {b['median_chars']} |")
    out += ["", f"Gate rejections (generative arms): {summary['generative_gate_outcomes'] or 'none'}", ""]
    if summary.get("two_stage") and summary["two_stage"]["runs"]:
        t = summary["two_stage"]
        out += ["## Two-stage experiment (arm D)", "",
                f"* runs {t['runs']} | answered {t['answered']} | claims {t['claims_valid']}/{t['claims_total']} valid "
                f"| rejected {t['claims_rejected']} | parse errors {t['plans_with_parse_error']}",
                f"* claim rejection reasons: {t['claim_rejection_reasons'] or '—'}",
                f"* stage-2 citation markers stripped: {t['stage2_markers_stripped']} | final validation failures "
                f"{t['final_validation_failures'] or '—'} | aborts {t['aborts'] or '—'}",
                f"* uncited sentences in answered output: {t['uncited_sentences']} | citation errors: {t['citation_errors']}",
                ""]
    for rec in records:
        out += [f"## {rec['id']} — {rec['question']} → *{rec['message']}*", ""]
        if rec.get("expect"):
            out += [f"*Expected:* {rec['expect']}", ""]
        out += [f"*Resolver on the follow-up:* `{json.dumps(rec['fu'])}`", ""]
        for arm, run in rec["runs"].items():
            head = (f"**{arm}** — `{run.get('status')}`{' / ' + str(run.get('reason')) if run.get('reason') else ''}"
                    f" | {run.get('chars')} chars | {run.get('latency', {}).get('total_ms')} ms "
                    f"(gen {run.get('latency', {}).get('generate_ms')} ms) | markers {run.get('markers')}"
                    + (f" | gates {run['gates']}" if run.get("gates") is not None else "")
                    + (f" | fallback: {run['fallback_because']}" if run.get("fallback_because") else "")
                    + (f" | novelty {run['novelty_vs_A']}" if run.get("novelty_vs_A") else ""))
            out += [head, "", "```text", (run.get("answer") or "(no answer)")[:1600], "```", ""]
            if arm.startswith("C_generative") and run.get("model_raw") and run.get("status") != "answered":
                out += ["withheld model text:", "", "```text", run["model_raw"][:800], "```", ""]
            if arm.startswith("D_two_stage"):
                info = run.get("two_stage") or {}
                if info:
                    out += [f"two-stage: claims {info.get('claims_valid')}/{info.get('claims_total')} valid"
                            f" | abort {info.get('abort') or '—'} | stage-2 markers stripped {info.get('stage2_markers_stripped')}"
                            f" | sentences kept {info.get('sentences_kept')} | plan {info.get('plan_ms')} ms"
                            f" | synth {info.get('synth_ms')} ms", ""]
                if info.get("claim_rejections"):
                    out += ["```json", json.dumps(info["claim_rejections"], indent=1)[:1200], "```", ""]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
