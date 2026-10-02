#!/usr/bin/env python3
"""Phase 11.1 - read-only diagnosis of the Phase 11 E2E cases (no tuning): router / identity / chunks / answer / citation / expected.

Runs the REAL default pipeline in-process (``rag_pipeline.build_pipeline``, extractive) for a question once with the real router and, when the
expected card is known, once with oracle routing, and records where the chain loses the expected evidence.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rag_pipeline as RP  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def trace(pipe, q, oracle=None, evidence=None):
    r = pipe.answer(q, debug=True, oracle_source_id=oracle)
    d = r.get("debug") or {}
    ctx = (d.get("context") or {}).get("items") or []
    ev = norm(evidence) if evidence else None
    retrieved = d.get("retrieved") or []
    cited = (d.get("grounding") or {}).get("cited_markers") or []
    return {
        "router_top3": [(c["source_id"], c["similarity"]) for c in (r["routing"].get("candidates") or [])[:3]],
        "selected": r["routing"]["selected_source_id"],
        "identity": (r.get("topic") or {}).get("identity_status"),
        "corpus": (r.get("topic") or {}).get("corpus_status"),
        "status": r["status"], "reason": r["reason_code"],
        "gate_topic_cov": (d.get("gate_topic") or {}).get("coverage"),
        "retrieved": [{"chunk": h["chunk_id"].split("::")[-1][-12:], "rank": h["rank"], "sim": h["similarity"]} for h in retrieved],
        "context": [{"marker": i["marker"], "rank": i["rank"], "section": " > ".join(i["heading_path"])[-60:], "has_evidence": (ev in norm(i["text"])) if ev else None} for i in ctx],
        "evidence_in_retrieved_top5": any(ev in norm(i["text"]) for i in ctx) if ev else None,
        "answer": r["answer"], "cited": cited,
        "cited_has_evidence": any(ev in norm(i["text"]) for i in ctx if i["marker"] in cited) if ev else None,
        "dropped": (d.get("context") or {}).get("dropped"),
    }


def main() -> int:
    qs = json.loads((ROOT / "data/evaluation/phase11_e2e_questions.json").read_text(encoding="utf-8"))["questions"]
    pipe = RP.build_pipeline(generator="extractive")
    out = []
    for q in qs:
        real = trace(pipe, q["question"], None, q.get("evidence"))
        orc = trace(pipe, q["question"], q["expected_card"], q.get("evidence")) if q.get("expected_card") else None
        out.append({"id": q["id"], "question": q["question"], "expected_status": q["expected_status"], "expected_card": q["expected_card"], "evidence": q.get("evidence"), "real_router": real, "oracle_card": orc})
    dest = ROOT / "data/phase11_1/diagnosis.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for o in out:
        r, c = o["real_router"], o["oracle_card"]
        print(o["id"], "exp", o["expected_status"], o["expected_card"], "| real:", r["selected"], r["status"], r["identity"], "top3", [x[0] for x in r["router_top3"]],
              "| ev_in_ctx", r["evidence_in_retrieved_top5"], "cited_ev", r["cited_has_evidence"], "| oracle:", (c["status"], c["evidence_in_retrieved_top5"], c["cited_has_evidence"]) if c else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
