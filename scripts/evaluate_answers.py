"""Answer-quality evaluation for the local RAG chatbot (no external APIs).

Usage (from the repository root):
    python scripts/evaluate_answers.py                    # full run (needs Ollama + llama3.2:3b)
    python scripts/evaluate_answers.py --retrieval-only   # no LLM: checks retrieval + refusal gate
    python scripts/evaluate_answers.py --ids a01 g02      # subset
    python scripts/evaluate_answers.py --self-test        # unit-test the checker itself

Questions live in data/answer_quality_questions.json.  Each item has:

  expect            "answer" | "refuse" | "answer_or_refuse"
  expected_sources  list of groups of acceptable page titles; every group must
                    be satisfied (one title per group). One group = a
                    single-source question, several groups = multi-source.
  multi_source      if true, the answer must *cite* a title from every group
  must_include      list of groups of alternative keywords; every group must
                    have at least one hit (case-insensitive) -> correctness /
                    grounding
  must_not_include  strings that must not appear   -> hallucination canaries
  must_not_match    regexes that must not match    -> invented figures
  manual_review     flag answers a human should read (ambiguous questions)

Automatic checks are deliberately simple keyword/title checks.  They catch
regressions and obvious hallucinations; they do not replace reading the
answers, which are written to data/answer_results.json.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from rag_core import (
    DEFAULT_STRATEGY,
    LLM_MODEL_NAME,
    NO_ANSWER_MESSAGE,
    REPO_ROOT,
    STRATEGIES,
    generate_answer,
    get_collection,
    search,
    TOP_K,
)

QUESTIONS_FILE = REPO_ROOT / "data" / "answer_quality_questions.json"
RESULTS_FILE = REPO_ROOT / "data" / "answer_results.json"

MAX_REFUSAL_CHARS = 400  # a refusal that keeps talking is probably leaking content


# ============================================================
# Checks (pure functions - no models needed)
# ============================================================

def is_refusal(answer: str) -> bool:
    return bool(
        re.search(r"couldn.t find this information", answer, re.IGNORECASE)
    )


def title_pattern(title: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(title.lower()) + r"(?!\w)")


def cited_region(answer: str) -> str:
    """The part of the answer that lists sources.

    The prompt asks the model to name its source titles at the end, so look
    from the last 'Source' keyword; otherwise use the last two lines.
    """
    matches = list(re.finditer(r"sources?\b", answer, re.IGNORECASE))
    if matches:
        return answer[matches[-1].start():]

    lines = [ln for ln in answer.splitlines() if ln.strip()]
    return "\n".join(lines[-2:])


def cited_titles(answer: str, candidate_titles: list[str]) -> list[str]:
    """Which retrieved titles does the answer's source section name?

    Whole-phrase matching, and a title is ignored when it is only a fragment
    of a longer cited title ("Contract Account" inside "Contract Account
    Category").
    """
    region = cited_region(answer).lower()
    found = sorted({t for t in candidate_titles if title_pattern(t).search(region)})
    return [
        t for t in found
        if not any(t != o and t.lower() in o.lower() for o in found)
    ]


def sources_satisfied(groups, titles) -> tuple[bool, list]:
    """Every group needs at least one (exactly-equal) title in ``titles``."""
    lowered = {t.strip().lower() for t in titles}
    missing = [g for g in groups if not any(t.lower() in lowered for t in g)]
    return not missing, missing


def evaluate_item(item: dict, answer: str, results: list[dict], gate_refused: bool):
    """Return (checks, warnings).  ``checks`` maps check name -> bool."""
    expect = item["expect"]
    refused = gate_refused or is_refusal(answer)
    retrieved_titles = [r["metadata"].get("title", "") for r in results]
    checks: dict[str, bool] = {}
    warnings: list[str] = []
    text = answer.lower()

    # --- refusal behaviour -------------------------------------------------
    if expect == "refuse":
        checks["refused_unsupported_question"] = refused
        if refused:
            checks["refusal_is_clean"] = (
                gate_refused or len(answer) <= MAX_REFUSAL_CHARS
            )
    elif expect == "answer":
        checks["answered_supported_question"] = not refused

    # --- hallucination resistance -----------------------------------------
    canaries = [s for s in item.get("must_not_include", []) if s.lower() in text]
    patterns = [
        p for p in item.get("must_not_match", []) if re.search(p, answer, re.IGNORECASE)
    ]
    if item.get("must_not_include") or item.get("must_not_match"):
        checks["no_hallucination_canaries"] = not canaries and not patterns
        if canaries or patterns:
            warnings.append(f"canary hit: {canaries + patterns}")

    if refused:
        return checks, warnings  # nothing further to grade on a refusal

    # --- correctness / grounding ------------------------------------------
    groups = item.get("must_include", [])
    if groups:
        missing = [g for g in groups if not any(k.lower() in text for k in g)]
        checks["contains_expected_facts"] = not missing
        if missing:
            warnings.append(f"missing facts (any of): {missing}")

    # --- retrieval + attribution ------------------------------------------
    expected_groups = item.get("expected_sources", [])
    if expected_groups:
        ok, missing = sources_satisfied(expected_groups, retrieved_titles)
        checks["expected_source_retrieved"] = ok
        if not ok:
            warnings.append(f"expected source not retrieved: {missing}")

        cited = cited_titles(answer, retrieved_titles)
        if item.get("multi_source"):
            ok, missing = sources_satisfied(expected_groups, cited)
            checks["multi_source_all_cited"] = ok
            if not ok:
                warnings.append(f"sources not cited: {missing}")
        else:
            flat = {t.lower() for g in expected_groups for t in g}
            checks["cites_expected_source"] = any(t.lower() in flat for t in cited)

        flat = {t.lower() for g in expected_groups for t in g}
        extra = [t for t in cited if t.lower() not in flat]
        if extra:
            warnings.append(f"cites non-expected retrieved source(s): {extra}")

    return checks, warnings


# ============================================================
# Runner
# ============================================================

def run_item(item, strategy, retrieval_only, model):
    if retrieval_only:
        results = search(item["question"], top_k=TOP_K, strategy=strategy)
        return "", results, not results

    answer, results = generate_answer(item["question"], strategy=strategy, model=model)
    return answer, results, not results


def grade_retrieval_only(item, results, gate_refused):
    """Retrieval-only mode: no answer text exists, so grade the parts we can."""
    checks, warnings = {}, []
    expect = item["expect"]

    if expect == "refuse":
        if gate_refused:
            checks["distance_gate_refuses"] = True
        else:
            warnings.append(
                "passed the distance gate -> refusal depends on the LLM"
            )

    groups = item.get("expected_sources", [])
    if expect != "refuse" and groups:
        titles = [r["metadata"].get("title", "") for r in results]
        ok, missing = sources_satisfied(groups, titles)
        checks["expected_source_retrieved"] = ok
        if not ok:
            warnings.append(f"expected source not retrieved: {missing}")

    if expect == "answer" and gate_refused:
        checks["not_blocked_by_distance_gate"] = False

    return checks, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), default=DEFAULT_STRATEGY)
    parser.add_argument("--model", default=LLM_MODEL_NAME)
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--ids", nargs="*", help="only run these question ids")
    parser.add_argument("--output", default=str(RESULTS_FILE))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        raise SystemExit(self_test())

    with open(QUESTIONS_FILE, encoding="utf-8") as f:
        items = json.load(f)

    if args.ids:
        items = [i for i in items if i["id"] in set(args.ids)]

    try:
        get_collection()
    except (FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(f"Error: {exc}")

    mode = "retrieval-only" if args.retrieval_only else f"generation ({args.model})"
    print(f"Answer-quality evaluation: {len(items)} questions, strategy={args.strategy}, {mode}\n")

    records = []
    for item in items:
        try:
            answer, results, gate_refused = run_item(
                item, args.strategy, args.retrieval_only, args.model
            )
        except Exception as exc:
            print(f"Error on {item['id']}: {exc}")
            print("Is Ollama running and the model pulled?  (ollama pull llama3.2:3b)")
            raise SystemExit(1)

        if args.retrieval_only:
            checks, warnings = grade_retrieval_only(item, results, gate_refused)
        else:
            checks, warnings = evaluate_item(item, answer, results, gate_refused)

        passed = all(checks.values())
        status = "PASS" if passed else "FAIL"
        if item.get("manual_review"):
            status += " (manual review)"

        print(f"[{status}] {item['id']} ({item['type']}): {item['question']}")
        for name, ok in checks.items():
            if not ok:
                print(f"    x {name}")
        for w in warnings:
            print(f"    ! {w}")
        if not args.retrieval_only:
            print("    answer:", answer.replace("\n", " ")[:300])

        records.append({
            "id": item["id"],
            "type": item["type"],
            "question": item["question"],
            "expect": item["expect"],
            "answer": answer,
            "gate_refused": gate_refused,
            "retrieved_titles": [r["metadata"].get("title", "") for r in results],
            "checks": checks,
            "warnings": warnings,
            "passed": passed,
            "manual_review": bool(item.get("manual_review")),
        })

    print_summary(records)

    out = Path(args.output)
    if args.retrieval_only and out == RESULTS_FILE:
        out = RESULTS_FILE.with_name("answer_results_retrieval_only.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed results saved to: {out}")


def print_summary(records):
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    by_type: dict[str, list[bool]] = {}
    for r in records:
        by_type.setdefault(r["type"], []).append(r["passed"])
    for t, flags in by_type.items():
        print(f"{t:20} {sum(flags)}/{len(flags)}")

    total = sum(r["passed"] for r in records)
    print(f"{'TOTAL':20} {total}/{len(records)}")

    check_totals: dict[str, list[bool]] = {}
    for r in records:
        for name, ok in r["checks"].items():
            check_totals.setdefault(name, []).append(ok)
    print("\nBy check:")
    for name, flags in sorted(check_totals.items()):
        print(f"  {name:32} {sum(flags)}/{len(flags)}")


# ============================================================
# Self-test: proves the checker accepts good answers and catches bad ones
# ============================================================

def self_test() -> int:
    def res(*titles):
        return [{"metadata": {"title": t}} for t in titles]

    two_types = {
        "expect": "answer", "expected_sources": [["Master Data"]],
        "must_include": [["business master data"], ["technical master data"]],
    }
    refuse = {"expect": "refuse", "must_not_include": ["$", "usd"]}
    multi = {
        "expect": "answer", "multi_source": True,
        "expected_sources": [["SAP Business Partner"], ["Contract Account", "Contract Accounts"]],
        "must_include": [["organization"], ["payment", "bill"]],
    }
    r = NO_ANSWER_MESSAGE

    cases = [
        ("good single-source answer", two_types,
         "There are business master data and technical master data.\n\nSource: Master Data",
         res("Master Data", "Contract Account"), False, True),
        ("missing fact -> fail", two_types,
         "There are business master data.\n\nSource: Master Data",
         res("Master Data"), False, False),
        ("answers from wrong source -> fail", two_types,
         "There are business master data and technical master data.\n\nSource: Contract Account",
         res("Master Data", "Contract Account"), False, False),
        ("expected page never retrieved -> fail", two_types,
         "There are business master data and technical master data.\n\nSource: Contract Account",
         res("Contract Account"), False, False),
        ("refuses supported question -> fail", two_types, r, res("Master Data"), False, False),
        ("clean refusal", refuse, r, res("Foo"), False, True),
        ("gate refusal", refuse, r, [], True, True),
        ("answers unsupported question -> fail", refuse,
         "SAP HANA costs about $100.", res("Foo"), False, False),
        ("refusal that leaks content -> fail", refuse,
         r + " " + "However, " + "blah " * 100, res("Foo"), False, False),
        ("multi-source, both cited", multi,
         "A business partner is an organization or person. A contract account is used for payment.\n\nSources: SAP Business Partner, Contract Accounts",
         res("SAP Business Partner", "Contract Accounts"), False, True),
        ("multi-source, one cited -> fail", multi,
         "A business partner is an organization; a contract account handles payment.\n\nSource: SAP Business Partner",
         res("SAP Business Partner", "Contract Accounts"), False, False),
        ("title fragment not double counted", multi,
         "A business partner is an organization; a contract account handles payment.\n\nSources: SAP Business Partner, Contract Account Category",
         res("SAP Business Partner", "Contract Account Category", "Contract Account"), False, False),
    ]

    failures = 0
    for name, item, answer, results, gate, want_pass in cases:
        checks, _ = evaluate_item(item, answer, results, gate)
        got = all(checks.values())
        ok = got == want_pass
        failures += not ok
        print(f"{'ok  ' if ok else 'BAD '} {name}  (checks passed={got}, expected={want_pass})")

    print(f"\n{len(cases) - failures}/{len(cases)} checker self-tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
