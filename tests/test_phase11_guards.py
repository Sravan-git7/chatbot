"""Phase 11 - guards: no canned answers in the UI, the front end builds no SAP URLs, E2E results are internally consistent and match the frozen questions,
protected Phase 1-10 artifacts are unchanged."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_SRC = ROOT / "web" / "src"
EVAL = ROOT / "data" / "evaluation"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ui_sources():
    return [p for p in WEB_SRC.rglob("*") if p.suffix in (".ts", ".tsx") and "__tests__" not in p.parts]


class FrontEndStaticGuards(unittest.TestCase):
    def test_sources_exist(self):
        self.assertTrue(ui_sources())

    def test_ui_never_contains_sap_urls_or_card_ids(self):
        for p in ui_sources():
            t = p.read_text(encoding="utf-8")
            self.assertNotIn("help.sap.com", t, p.name)
            if p.name != "DebugPanel.tsx":
                self.assertFalse(re.search(r"M2C-\d", t), p.name)

    def test_ui_only_talks_to_the_api_through_relative_urls(self):
        t = (WEB_SRC / "api.ts").read_text(encoding="utf-8")
        self.assertEqual(sorted(set(re.findall(r"\$\{BASE\}(/api/[a-z]+)", t))), ["/api/chat", "/api/health"])
        for p in ui_sources():
            self.assertNotRegex(re.sub(r"/\*.*?\*/|//[^\n]*", "", p.read_text(encoding="utf-8"), flags=re.S), r"https?://", p.name)
        for p in ui_sources():
            self.assertEqual(len(re.findall(r"\bfetch\(", p.read_text(encoding="utf-8"))), 2 if p.name == "api.ts" else 0, p.name)

    def test_no_demo_answers_or_fake_delays(self):
        for p in ui_sources():
            t = p.read_text(encoding="utf-8")
            self.assertNotRegex(t, r"(?i)lorem ipsum|demo answer|mock(ed)? (answer|response)", p.name)
            self.assertNotRegex(t, r"setTimeout\([^)]*\b(2000|3000|1500)\b[^)]*\)\s*$", p.name)
        app = (WEB_SRC / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("sendChat(", app)

    def test_no_dangerous_html_apis(self):
        for p in ui_sources():
            t = p.read_text(encoding="utf-8")
            for bad in ("dangerouslySetInnerHTML", "innerHTML", "eval(", "document.write"):
                self.assertNotIn(bad, t, f"{bad} in {p.name}")
        pkg = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
        self.assertNotIn("rehype-raw", {**pkg["dependencies"], **pkg["devDependencies"]})

    def test_loading_text_matches_a_single_real_backend_call(self):
        t = (WEB_SRC / "components" / "MessageView.tsx").read_text(encoding="utf-8")
        self.assertIn("Searching the SAP Utilities documentation and preparing an answer", t)
        self.assertNotIn("Generating answer", t)           # the backend does not report separate stages, so no second stage is shown

    def test_node_modules_and_dist_are_not_tracked(self):
        self.assertIn("node_modules/", (ROOT / "web" / ".gitignore").read_text(encoding="utf-8"))
        self.assertIn("dist/", (ROOT / "web" / ".gitignore").read_text(encoding="utf-8"))


class BackendStaticGuards(unittest.TestCase):
    def test_service_and_api_add_no_second_rag_implementation(self):
        for name in ("rag_service", "rag_api"):
            tree = ast.parse((ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8"))
            imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            for banned in ("chromadb", "sentence_transformers", "rag_optimised", "ollama", "urllib.request", "http.client", "requests", "socket"):
                self.assertNotIn(banned, imported, name)
        svc = (ROOT / "scripts" / "rag_service.py").read_text(encoding="utf-8")
        self.assertIn("pipeline.answer(", svc)
        self.assertNotIn("def retrieve", svc)

    def test_entry_point_never_falls_back_between_generators(self):
        api = (ROOT / "scripts" / "rag_api.py").read_text(encoding="utf-8")
        self.assertEqual(sorted(re.findall(r'choices=\(("[a-z]+"), ("[a-z]+")\)', api)[0]), ['"extractive"', '"ollama"'])
        self.assertNotRegex(api, r"except[^\n]*:\s*\n\s*(gen|generator)\s*=")


class E2EResultsConsistency(unittest.TestCase):
    def setUp(self):
        self.res = json.loads((ROOT / "data" / "phase11_e2e_results.json").read_text(encoding="utf-8"))
        self.qs = json.loads((EVAL / "phase11_e2e_questions.json").read_text(encoding="utf-8"))["questions"]

    def test_results_are_for_the_current_question_file(self):
        self.assertEqual(self.res["questions_sha256"], sha(EVAL / "phase11_e2e_questions.json"))
        self.assertEqual([r["id"] for r in self.res["results"]], [q["id"] for q in self.qs])
        for r, q in zip(self.res["results"], self.qs):
            self.assertEqual((r["question"], r["expected_status"], r["expected_card"]), (q["question"], q["expected_status"], q["expected_card"]))

    def test_summary_recomputes_from_the_rows(self):
        rows = self.res["results"]
        s = self.res["summary"]
        self.assertEqual(s["questions"], len(rows))
        self.assertEqual(s["passed"], sum(1 for r in rows if r["passed"]))
        self.assertEqual(s["answerable_passed"], sum(1 for r in rows if r["type"] == "answerable" and r["passed"]))
        self.assertEqual(sorted(f["id"] for f in s["failures"]), sorted(r["id"] for r in rows if not r["passed"]))
        self.assertGreaterEqual(len(rows), 10)

    def test_a_passing_row_has_every_check_true_and_failures_name_a_mode(self):
        for r in self.res["results"]:
            vals = [v for v in r["checks"].values() if v is not None]
            self.assertEqual(r["passed"], all(vals), r["id"])
            self.assertEqual(r["failure_mode"] is None, r["passed"], r["id"])

    def test_every_recorded_citation_is_a_stored_card_url(self):
        d = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))
        stored = {u["source_url"] for u in (d["units"] if isinstance(d, dict) else d)}
        for r in self.res["results"]:
            for c in r["citations"]:
                self.assertIn(c["url"], stored, r["id"])
            if r["status"] != "answered":
                self.assertEqual(r["citations"], [], r["id"])
                self.assertNotRegex(r["answer"], r"M2C-\d", r["id"])

    def test_answered_rows_are_grounded_and_the_generator_is_declared(self):
        self.assertEqual(self.res["generator"], "extractive")
        for r in self.res["results"]:
            if r["status"] == "answered":
                self.assertTrue(r["grounded"], r["id"])
                self.assertTrue(r["grounding"]["checked"] and r["grounding"]["violations"] == 0, r["id"])

    def test_error_paths_are_controlled(self):
        for k, v in self.res["error_paths"].items():
            if isinstance(v, dict):
                self.assertEqual(v["http_status"], 422, k)
                self.assertEqual(v["code"], "invalid_request", k)
        self.assertTrue(self.res["error_paths"]["html_in_question_not_reflected"])

    def test_browser_run_passed_completely(self):
        b = self.res["browser"]
        self.assertIsNotNone(b)
        self.assertEqual(b["passed"], b["total"])
        self.assertTrue(all(c["passed"] for c in b["checks"]))
        self.assertGreaterEqual(b["total"], 20)


class ProtectedFiles(unittest.TestCase):
    PINS = {"scripts/rag_chat.py": "e862ce38", "scripts/rag_core.py": "881316e4", "data/evaluation/phase8_results.json": "735f7061", "data/source_manifest.json": "08ad208c",
            "data/card_collection_manifest.json": "5b3a5c30", "data/m2c_page_identity.json": "fccb0bb8"}

    def test_pins(self):
        for rel, prefix in self.PINS.items():
            self.assertTrue(sha(ROOT / rel).startswith(prefix), rel)

    def test_phase10_frozen_artifacts_unchanged(self):
        freeze = json.loads((EVAL / "phase10_queries_freeze.json").read_text(encoding="utf-8"))
        self.assertEqual(sha(EVAL / "phase10_dev_queries.json"), freeze["files"]["dev"]["sha256"])
        self.assertEqual(sha(EVAL / "phase10_test_queries.json"), freeze["files"]["test"]["sha256"])
        res = json.loads((EVAL / "phase10_results.json").read_text(encoding="utf-8"))
        self.assertEqual(res["test_sha256"], freeze["files"]["test"]["sha256"])

    def test_pipeline_and_cli_modules_unchanged_in_behaviour_surface(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import rag_pipeline as RP
        self.assertEqual(RP.SCHEMA_VERSION, "8.1")
        self.assertEqual(RP.STATUSES, ("answered", "insufficient_context", "unresolved_identity", "page_not_ingested", "out_of_domain", "no_relevant_page"))
        self.assertEqual((RP.OOD_MIN_COVERAGE, RP.CONTEXT_MIN_COVERAGE), (0.25, 0.5))


if __name__ == "__main__":
    unittest.main()
