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

parser = argparse.ArgumentParser(description="Follow-up elaboration measurement (additive; measures A/B/C arms).")
parser.add_argument("--questions", default="data/phase_elaboration/elaboration_questions.json")
parser.add_argument("--out", default="data/phase_elaboration/elaboration_run.json")
parser.add_argument("--markdown", default="data/phase_elaboration/elaboration_report.md")
parser.add_argument("--checkpoint", default="data/phase_elaboration/elaboration_run.ckpt.jsonl")
parser.add_argument("--environment", default="data/phase_elaboration/elaboration_environment.json")
parser.add_argument("--generator-llm", choices=("ollama", "stub"), default="ollama")
parser.add_argument("--stub-mode", choices=("faithful", "uncited", "phantom", "invented", "inversion", "refusal", "all"),
                    default="faithful")
parser.add_argument("--model", default=None, help="defaults to rag_core.LLM_MODEL_NAME")
parser.add_argument("--timeout", type=float, default=20.0, help="seconds per model call (0 disables the bound)")
parser.add_argument("--num-predict", type=int, default=None, help="optional cap on generated tokens")
parser.add_argument("--limit", type=int, default=None, help="only the first N topics")
parser.add_argument("--preflight", action="store_true", help="check the environment and exit (no generation)")
parser.add_argument("--force", action="store_true", help="allow overwriting existing output files")
args = parser.parse_args()

SEALED = ("data/phase12/", "data/phase16/", "data/phase17a/", "data/phase18/", "data/evaluation/", "benchmark/")
ELABORATION_PROMPT = """You are an SAP documentation assistant. The user has already read a short answer and now asks for a fuller explanation.

RULES:
1. Explain the topic ONLY from the numbered documentation excerpts below. Do not use outside knowledge, do not give advice, do not guess.
2. After every sentence add the marker of the excerpt that supports it, for example [S4]. Use only the markers shown below.
3. Prefer the wording of the excerpts. Never invent transaction codes, numbers, URLs, guide identifiers or section names.
4. You may group related facts into at most three short paragraphs and use a plain list when the excerpts contain one. Do not invent headings or sections.
5. Explain, do not repeat: if the short answer stated a fact, express it only as part of a fuller explanation.
6. If the excerpts do not contain enough information for a fuller explanation, reply with exactly: {no_answer}

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
    out_path, md_path, ck_path, env_path = (_resolve(args.out), _resolve(args.markdown), _resolve(args.checkpoint),
                                            _resolve(args.environment))
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

    records: List[Dict[str, Any]] = []
    checkpoint = ck_path.open("a", encoding="utf-8")
    checkpoint.write(json.dumps({"header": {"model": model, "generator_llm": args.generator_llm, "stub_modes": stub_modes,
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
            c, wc = ask(svc_c, q)                       # the anchor question is the pipeline query: the same page as A
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
            if arm.startswith("C_generative"):
                for g in run.get("gates") or []:
                    gate_counts[g] = gate_counts.get(g, 0) + 1
    for arm, bucket in per_arm.items():
        runs = [r for rec in records for k, r in rec["runs"].items() if k == arm]
        bucket["median_total_ms"] = median(r.get("latency", {}).get("total_ms") for r in runs)
        bucket["median_generate_ms"] = median(r.get("latency", {}).get("generate_ms") for r in runs)
        bucket["median_chars"] = median(r.get("chars") for r in runs)
        bucket["markers_total"] = sum(len(r.get("markers") or []) for r in runs)
    return {"topics": len(records), "per_arm": per_arm, "generative_gate_outcomes": gate_counts}


def _markdown(payload: Dict[str, Any]) -> str:
    env, summary, records = payload["environment"], payload["summary"], payload["records"]
    out = ["# Follow-up elaboration: extractive vs guarded generative (measurement run)", "",
           f"* Model: `{env['model']}` | LLM source: `{env['generator_llm']}`"
           + (f" (stub mode: {env.get('stub_mode')})" if env["generator_llm"] == "stub" else "")
           + f" | timeout {env['timeout_s']} s | questions sha256 `{env['questions_sha256'][:12]}…` | git `{(env.get('git_head') or '')[:9]}`",
           f"* Ollama: {json.dumps(env['ollama'])}", "",
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
    out += ["", f"Gate rejections (generative arm): {summary['generative_gate_outcomes'] or 'none'}", ""]
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
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
