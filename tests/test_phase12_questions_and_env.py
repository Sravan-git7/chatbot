"""Phase 12 - frozen question set integrity, Ollama environment check (injected), corpus status and the import validator (temp folders)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import phase10_lib as L  # noqa: E402
import phase12_import_pages as IMP  # noqa: E402
import phase12_ollama_check as OC  # noqa: E402

QS = ROOT / "data" / "evaluation" / "phase12_queries.json"
FREEZE = ROOT / "data" / "evaluation" / "phase12_freeze.json"
EARLIER = ["phase8_queries", "phase9_queries", "phase10_dev_queries", "phase10_test_queries", "phase11_1_holdout_questions", "phase11_1_holdout2_questions"]


def norm(s):
    return " ".join((s or "").lower().split())


class FrozenSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(QS.read_text(encoding="utf-8"))
        cls.q = cls.data["queries"]

    def test_hash_matches_freeze(self):
        self.assertEqual(L.sha(QS), json.loads(FREEZE.read_text(encoding="utf-8"))["sha256"])

    def test_size_composition_and_authorship(self):
        self.assertEqual(len(self.q), 113)
        c = {}
        for x in self.q:
            c[x["type"]] = c.get(x["type"], 0) + 1
        self.assertEqual(c, {"answerable": 65, "absent_detail": 16, "not_ingested": 10, "unresolved_identity": 6, "ambiguous": 8, "out_of_domain": 8})
        self.assertIn("AI coding assistant", self.data["authorship"])
        self.assertIn("NOT human-labelled", self.data["authorship"])
        self.assertTrue(all(len(x["authorship"]) > 20 for x in self.q))

    def test_ids_unique_and_fields_present(self):
        self.assertEqual(len({x["id"] for x in self.q}), 113)
        for x in self.q:
            for k in ("id", "category", "query", "type", "gold_source_id", "gold_doc_id", "acceptable_source_ids", "evidence", "absent_terms" if x["type"] == "absent_detail" else "expected_status", "expected_status"):
                self.assertIn(k, x)
            if x["type"] == "answerable":
                self.assertTrue(x["evidence"] and x["gold_doc_id"])

    def test_no_query_overlaps_an_earlier_set(self):
        seen = set()
        for f in EARLIER:
            d = json.loads((ROOT / "data" / "evaluation" / f"{f}.json").read_text(encoding="utf-8"))
            seen |= {norm(r.get("query") or r.get("question")) for r in d.get("queries") or d.get("questions")}
        self.assertEqual([x["id"] for x in self.q if norm(x["query"]) in seen], [])

    def test_all_seven_ingested_pages_are_covered(self):
        self.assertEqual({x["gold_source_id"] for x in self.q if x["type"] == "answerable"}, {"M2C-02", "M2C-05", "M2C-07", "M2C-11", "M2C-14", "M2C-17", "M2C-24"})

    def test_not_ingested_questions_point_at_cards_without_a_page(self):
        pages = {"M2C-02", "M2C-05", "M2C-07", "M2C-11", "M2C-14", "M2C-17", "M2C-24"}
        for x in self.q:
            if x["type"] == "not_ingested":
                self.assertNotIn(x["gold_source_id"], pages)

    def test_builder_refuses_to_rewrite_the_frozen_set(self):
        import subprocess
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_phase12_queries.py")], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(p.returncode, 2)
        self.assertIn("frozen", p.stderr)
        self.assertEqual(L.sha(QS), json.loads(FREEZE.read_text(encoding="utf-8"))["sha256"])


class OllamaCheck(unittest.TestCase):
    def ok_http(self, path, timeout):
        if path == "/api/version":
            return 200, '{"version": "0.0.1"}', None
        return 200, '{"models": [{"name": "llama3.2:3b"}]}', None

    def test_everything_missing_is_blocked_with_all_blockers(self):
        def boom():
            raise ImportError("no ollama")
        rec = OC.check(which=lambda _: None, http_get=lambda p, t: (None, "", "refused"), import_ollama=boom)
        self.assertFalse(rec["ready"])
        self.assertEqual(rec["blockers"], ["NO_OLLAMA_EXECUTABLE", "NO_PYTHON_OLLAMA_PACKAGE", "OLLAMA_SERVER_NOT_RESPONDING"])
        self.assertIn("NOT available", rec["statement"])

    def test_server_up_but_model_not_pulled(self):
        http = lambda p, t: (200, '{"version":"x"}', None) if p == "/api/version" else (200, '{"models": []}', None)  # noqa: E731
        rec = OC.check(which=lambda _: "/usr/bin/ollama", http_get=http, import_ollama=lambda: object())
        self.assertFalse(rec["ready"])
        self.assertEqual(rec["blockers"], ["CONFIGURED_MODEL_NOT_PULLED"])

    def test_ready_requires_a_real_generation_round_trip(self):
        rec = OC.check(which=lambda _: "/x/ollama", http_get=self.ok_http, import_ollama=lambda: object(), generate=lambda p: "ok", model="llama3.2:3b")
        self.assertTrue(rec["ready"], rec["blockers"])
        bad = OC.check(which=lambda _: "/x/ollama", http_get=self.ok_http, import_ollama=lambda: object(), generate=lambda p: "  ", model="llama3.2:3b")
        self.assertFalse(bad["ready"])
        self.assertIn("GENERATION_ROUND_TRIP_FAILED", bad["blockers"])

        def raises(p):
            raise RuntimeError("down")
        self.assertIn("GENERATION_ROUND_TRIP_FAILED", OC.check(which=lambda _: "/x/ollama", http_get=self.ok_http, import_ollama=lambda: object(), generate=raises, model="llama3.2:3b")["blockers"])

    def test_recorded_environment_is_self_consistent(self):
        """The record is a snapshot of whichever machine ran ``phase12_ollama_check.py`` last (the sandbox: not ready; the Windows host: ready), so only its consistency is pinned."""
        rec = json.loads((ROOT / "data" / "phase12" / "ollama_environment.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["ready"], not rec["blockers"])
        self.assertEqual(rec["ready"], all(c.get("ok") for c in rec["checks"].values()))
        self.assertEqual(rec["configured_model"], "llama3.2:3b")
        if rec["ready"]:
            self.assertTrue(rec["checks"]["generation"]["ok"])
            self.assertIn("REAL Ollama is available", rec["statement"])
        else:
            self.assertIn("NOT available", rec["statement"])


class CorpusStatus(unittest.TestCase):
    def test_recorded_status_is_honest(self):
        s = json.loads((ROOT / "data" / "phase12" / "corpus_status.json").read_text(encoding="utf-8"))
        t = s["totals"]
        self.assertEqual((t["cards"], t["local_pages"], t["identified_not_local_without_page"], t["not_fetchable"]), (29, 7, 18, 4))
        self.assertFalse(s["corpus_complete"])
        self.assertIn("NOT complete", s["statement"])
        self.assertNotIn("M2C-18", [c["source_id"] for c in s["cards"] if c["fetchable_with_recorded_ids"]])
        blocked = {p["host"]: p for p in s["network_probe"]}
        self.assertEqual(blocked["help.sap.com"]["failed_stage"], "tls_handshake")

    def test_import_manifest_lists_only_the_18_fetchable_pages(self):
        m = json.loads((ROOT / "data" / "phase12" / "import_manifest.json").read_text(encoding="utf-8"))
        ids = [i["source_id"] for i in m["items"]]
        self.assertEqual(m["count"], 18)
        self.assertTrue(set(ids).isdisjoint({"M2C-01", "M2C-13", "M2C-16", "M2C-18", "M2C-07", "M2C-05", "M2C-24", "M2C-14", "M2C-17", "M2C-11", "M2C-02"}))
        self.assertTrue(all(i["request_url"].startswith("https://help.sap.com/http.svc/pagecontent?") for i in m["items"]))

    def test_fetch_attempt_saved_nothing(self):
        log = json.loads((ROOT / "data" / "phase12" / "fetch_attempt_log.json").read_text(encoding="utf-8"))
        run = log[-1]
        self.assertEqual(run["saved"], [])
        self.assertEqual(run["stopped_reason"], "CIRCUIT_BREAKER_3_CONSECUTIVE_FAILURES")
        self.assertTrue(all(not a["ok"] for a in run["attempts"]))


def envelope(guide, page, body="<p>text</p>", **kw):
    data = {"currentPage": {"loio": page + ".html"}, "deliverable": {"loio": guide}, "body": body}
    data.update(kw)
    return {"status": "OK", "data": data}


class ImportValidator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.plan = self.t / "plan.json"
        self.plan.write_text(json.dumps({"pages_to_fetch": [
            {"source_id": "M2C-03", "guide_id": "g3", "page_id": "p3", "numeric_deliverable_id": 11, "build_no": 1},
            {"source_id": "M2C-04", "guide_id": "g4", "page_id": "p4", "numeric_deliverable_id": 12, "build_no": 1}]}), encoding="utf-8")
        self.src = self.t / "saved"
        self.src.mkdir()
        self.out = self.t / "fetched"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, obj):
        (self.src / name).write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")

    def test_dry_run_accepts_valid_rejects_invalid_and_writes_nothing(self):
        self.put("a.json", envelope("g3", "p3"))
        self.put("b.json", envelope("WRONG", "p4"))
        self.put("c.json", envelope("g4", "unknown"))
        self.put("d.json", "not json at all")
        self.put("e.json", envelope("g4", "p4", fallback=True))
        rep = IMP.run(self.src, apply=False, plan_path=self.plan, out_dir=self.out)
        self.assertEqual(rep["accepted"], ["M2C-03"])
        reasons = {r["file"]: r["reasons"] for r in rep["rejected"]}
        self.assertIn("RESPONSE_GUIDE_ID_DIFFERS_FROM_PLAN", reasons["b.json"])
        self.assertEqual(reasons["c.json"], ["PAGE_ID_NOT_IN_PLAN"])
        self.assertTrue(reasons["d.json"][0].startswith("UNREADABLE_OR_NOT_JSON"))
        self.assertIn("FALLBACK_PAGE", reasons["e.json"])
        self.assertEqual(rep["still_missing"], ["M2C-04"])
        self.assertFalse(self.out.exists())

    def test_apply_copies_only_accepted_files_with_the_ingest_name(self):
        self.put("a.json", envelope("g3", "p3"))
        self.put("b.json", envelope("g4", "p4", body="   "))
        rep = IMP.run(self.src, apply=True, plan_path=self.plan, out_dir=self.out)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["1_11_p3.json"])
        self.assertEqual(len(rep["written"]), 1)
        self.assertEqual(json.loads((self.out / "1_11_p3.json").read_text(encoding="utf-8"))["data"]["deliverable"]["loio"], "g3")

    def test_duplicate_for_the_same_page_is_rejected(self):
        self.put("a.json", envelope("g3", "p3"))
        self.put("b.json", envelope("g3", "p3"))
        rep = IMP.run(self.src, apply=False, plan_path=self.plan, out_dir=self.out)
        self.assertEqual(rep["accepted"], ["M2C-03"])
        self.assertEqual([r["reasons"] for r in rep["rejected"]], [["DUPLICATE_FOR_SAME_PAGE"]])

    def test_tool_has_no_network_code(self):
        src = (ROOT / "scripts" / "phase12_import_pages.py").read_text(encoding="utf-8")
        for bad in ("urllib", "requests", "http.client", "socket", "allow_network"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
