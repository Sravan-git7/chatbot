#!/usr/bin/env python3
"""Phase 10 - OPT-IN optimisation candidates for the card-first RAG pipeline (see data/phase10_contract.md).

Nothing here changes the default pipeline: ``rag_pipeline``, ``rag_answer``, ``rag_chat`` and every protected artefact are untouched. The candidates are
built around them:

* ``FusionBackend`` (router candidate R): wraps the card backend and re-orders the router's FULL card list by
  ``fused(c) = card_sim(c) + lam * e(c)`` where ``e(c)`` is the best page-chunk cosine similarity of the card's local page, and ``card_sim(c)`` itself when the card has no
  local page (unknown pages are not penalised). ``lam = 0`` returns the card backend's own order untouched. Distances in the returned records stay the original card
  distances (the fused score is kept in ``last_fusion`` for debugging). Identity, gates, grounding and citations are downstream and unchanged.
* ``DetailCueGenerator`` (generation candidate G2): wraps the extractive generator; if the question asks for a specific kind of detail (cue table below) and the selected
  answer sentences do not contain that kind of detail, it abstains with the normal no-answer text. It only ever turns an answer into an abstention.
* ``build_optimised_pipeline`` / CLI: ``python scripts/rag_optimised.py --lam 1.0 --theta 0.5 --cue-check --generator extractive --question "..."``.

No network, no LLM call, no new threshold on the legacy distance. ``lam`` and ``theta`` are experiment parameters, not defaults.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_generate as RG  # noqa: E402
import rag_pipeline as RP  # noqa: E402

LAMBDA_GRID = (0.0, 0.5, 1.0, 2.0)
THETA_GRID = (0.34, 0.5, 0.67)
CODE_RE = re.compile(r"\b[A-Z]{2,5}\d{1,3}[A-Z]?\b")
NUMBER_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "twenty", "thirty", "hundred")
# (cue phrases, kind of detail the answer must contain). Declared in data/phase10_contract.md before any run.
CUE_RULES: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("transaction code", "which transaction", "what transaction", "t-code", "tcode"), "code"),
    (("maximum", "minimum", "at most", "at least", "limit"), "word_or_digit"),
    (("how many", "how much", "how long", "what percentage"), "digit_or_number_word"),
    (("default",), "word"),
    (("cost", "price", "fee"), "word_or_digit"),
)


def cue_unmet(question: str, answer_text: str) -> Optional[str]:
    """Return the first unmet cue (``"<phrase>:<kind>"``) or ``None`` when every cue present in the question is satisfied by ``answer_text``."""
    q = (question or "").lower()
    a = answer_text or ""
    al = a.lower()
    for phrases, kind in CUE_RULES:
        for ph in phrases:
            if re.search(r"(?<![a-z])" + re.escape(ph) + r"(?![a-z])", q):
                if kind == "code":
                    ok = bool(CODE_RE.search(a))
                elif kind == "word_or_digit":
                    ok = bool(re.search(r"(?<![a-z])" + re.escape(ph) + r"(?![a-z])", al)) or bool(re.search(r"\d", a))
                elif kind == "digit_or_number_word":
                    ok = bool(re.search(r"\d", a)) or any(re.search(r"(?<![a-z])" + w + r"(?![a-z])", al) for w in NUMBER_WORDS)
                else:
                    ok = bool(re.search(r"(?<![a-z])" + re.escape(ph) + r"(?![a-z])", al))
                if not ok:
                    return f"{ph}:{kind}"
    return None


class DetailCueGenerator:
    """Extractive generator + detail-cue check. Wraps any generator with a ``generate(question, context)`` method."""

    def __init__(self, base: Any, name: Optional[str] = None) -> None:
        self.base = base
        self.name = name or f"{getattr(base, 'name', 'generator')}+detail_cue"

    def generate(self, question: str, context: Any) -> RG.GenerationResult:
        res = self.base.generate(question, context)
        if res.refused:
            return res
        # only the answer sentences are checked; the [S1] markers are removed so a marker is never mistaken for a code
        body = re.sub(r"\[S\d+\]", " ", res.text)
        unmet = cue_unmet(question, body)
        if unmet is None:
            return res
        return RG.GenerationResult(RG.NO_ANSWER_TEXT, True, self.name, "")


class FusionBackend:
    """Card backend wrapper implementing the evidence-equalised page-evidence re-ranking (candidate R)."""
    distance_metric = "cosine"

    def __init__(self, card_backend: Any, retriever: Any, corpus: Any, lam: float, n_cards: int = 29) -> None:
        if lam < 0:
            raise ValueError("lam must be >= 0")
        self.card_backend, self.retriever, self.lam, self.n_cards = card_backend, retriever, float(lam), n_cards
        self.pages: Dict[str, Tuple[str, str]] = {}
        for sid, e in corpus.entries.items():
            if e.get("corpus_status") == "ingested" and e.get("doc_id"):
                g, p = str(e["doc_id"]).split("/")
                self.pages[sid] = (g, p)
        self.last_fusion: List[Dict[str, Any]] = []

    def query(self, query: str, n_results: int) -> Mapping[str, Any]:
        if self.lam == 0:
            self.last_fusion = []
            return self.card_backend.query(query, n_results)
        raw = self.card_backend.query(query, max(n_results, self.n_cards))
        ids, metas, dists = list(raw["ids"][0]), list(raw["metadatas"][0]), list(raw["distances"][0])
        best: Dict[Tuple[str, str], float] = {}
        for h in self.retriever.retrieve_corpus(query, top_k=max(1, self.retriever.count())):
            k = (h.guide_id, h.page_id)
            best[k] = max(best.get(k, -1.0), h.similarity)
        rows = []
        for i, (cid, md, d) in enumerate(zip(ids, metas, dists)):
            sim = 1.0 - float(d)
            e = best.get(self.pages.get(md["source_id"], ("", "")), None) if md["source_id"] in self.pages else None
            e = sim if e is None else e
            rows.append((sim + self.lam * e, i, cid, md, d, sim, e))
        rows.sort(key=lambda r: (-r[0], r[1]))
        self.last_fusion = [{"source_id": r[3]["source_id"], "card_sim": round(r[5], 4), "page_evidence": round(r[6], 4), "fused": round(r[0], 4)} for r in rows]
        top = rows[:n_results]
        return {"ids": [[r[2] for r in top]], "metadatas": [[r[3] for r in top]], "distances": [[r[4] for r in top]]}


def build_optimised_pipeline(lam: float = 0.0, theta: float = RG.EXTRACTIVE_MIN_SCORE, cue_check: bool = False, generator: str = "extractive",
                             llm_client: Any = None, base: Optional[RP.RagPipeline] = None) -> RP.RagPipeline:
    pipe = base or RP.build_pipeline(generator=generator, llm_client=llm_client)
    backend = FusionBackend(pipe.backend, pipe.retriever, pipe.corpus, lam) if lam else pipe.backend
    gen = pipe.generator
    if generator == "extractive":
        gen = RG.ExtractiveGenerator(min_score=theta)
        if cue_check:
            gen = DetailCueGenerator(gen)
    return RP.RagPipeline(backend, pipe.retriever, pipe.ctx, pipe.corpus, gen, pipe.count_tokens, config=pipe.cfg)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Opt-in Phase 10 optimisation candidates (default pipeline unchanged).", add_help=True)
    ap.add_argument("--question", "-q")
    ap.add_argument("--generator", choices=("ollama", "extractive"), default="ollama")
    ap.add_argument("--lam", type=float, default=0.0, help="page-evidence fusion weight (0 = current router)")
    ap.add_argument("--theta", type=float, default=RG.EXTRACTIVE_MIN_SCORE, help="extractive minimum sentence score (extractive generator only)")
    ap.add_argument("--cue-check", action="store_true", help="detail-cue abstention (extractive generator only)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args(argv)
    import rag_answer
    try:
        pipe = build_optimised_pipeline(a.lam, a.theta, a.cue_check, a.generator)
    except Exception as e:                                           # noqa: BLE001
        print(f"cannot start the pipeline: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    fwd = ["--generator", a.generator] + (["--json"] if a.json else []) + (["--debug"] if a.debug else []) + (["--question", a.question] if a.question is not None else [])
    return rag_answer.main(fwd, pipeline=pipe)


if __name__ == "__main__":
    sys.exit(main())
