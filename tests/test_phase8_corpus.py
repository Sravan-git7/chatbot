"""Phase 8A/8B - page corpus: extraction, validation, admission rules, manifest, opt-in fetcher."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.phase8_support import HAVE_BS4, ROOT, SCRIPTS

import m2c_page_identity as pid  # noqa: E402

if HAVE_BS4:
    import page_corpus as PC
    import page_extract as PE
    import page_fetch as PF

HTML = """<html><head><title>T</title><script>var x=1;</script></head><body><nav>menu</nav>
<div class="page topic"><h1 class="title topictitle1">Creating Things</h1><div class="body"><section class="section"><h2 class="section_title">Use</h2>
<p class="p">You create a thing when the rule applies. Then you save it.</p>
<ul class="ul"><li class="li">First item</li><li class="li">Second item <ul><li>nested</li></ul></li></ul></section>
<section class="section"><h2 class="section_title">Features</h2>
<table class="table"><thead><tr><th class="entry">Name</th><th class="entry">Value</th></tr></thead><tbody><tr><td class="entry">alpha</td><td class="entry">1</td></tr></tbody></table>
<aside class="note"><div class="title">Note</div><p class="p">A prerequisite is the business function ISU_X_1.</p></aside>
<p class="p">Go to <span class="menucascade"><span class="uicontrol">Account</span><span class="uicontrol">Plan</span><span class="uicontrol">Create</span></span> now.</p>
<img alt="Start of the navigation path" src="x.png"/>
<div class="related-links"><a>Other topic</a></div>
<footer>copyright</footer></section></div></div></body></html>"""


@unittest.skipUnless(HAVE_BS4, "beautifulsoup4 not installed")
class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.ex = PE.extract_html(HTML)

    def test_title_and_headings(self):
        self.assertEqual(self.ex["title"], "Creating Things")
        self.assertEqual(self.ex["headings"], ["Creating Things", "Use", "Features"])

    def test_chrome_removed(self):
        t = self.ex["text"]
        for junk in ("menu", "copyright", "var x", "navigation path"):
            self.assertNotIn(junk, t)

    def test_structure_kinds_and_heading_paths(self):
        kinds = [b["kind"] for b in self.ex["blocks"]]
        self.assertEqual(kinds, ["paragraph", "list", "table", "note", "paragraph", "related"])
        self.assertEqual(self.ex["blocks"][0]["heading_path"], ["Creating Things", "Use"])
        self.assertEqual(self.ex["blocks"][2]["heading_path"], ["Creating Things", "Features"])

    def test_list_table_note_menucascade(self):
        by = {b["kind"]: b["text"] for b in self.ex["blocks"]}
        self.assertIn("- First item", by["list"])
        self.assertIn("  - nested", by["list"])
        self.assertEqual(by["table"], "Name: alpha; Value: 1")
        self.assertTrue(by["note"].startswith("Note: A prerequisite"))
        self.assertIn("Account > Plan > Create", self.ex["blocks"][4]["text"])

    def test_deterministic(self):
        self.assertEqual(PE.extract_html(HTML), self.ex)

    def test_validation_rejects_error_and_empty(self):
        self.assertTrue(PE.validate_extraction(self.ex)["ok"])
        for body in ("", "<html><body></body></html>", "<html><head><title>404 Not Found</title></head><body><div class='page topic'><h1>404 Not Found</h1><p>" + "x " * 100 + "</p></div></body></html>"):
            v = PE.validate_extraction(PE.extract_html(body))
            self.assertFalse(v["ok"], body[:40])
            self.assertTrue(v["reasons"])

    def test_legit_title_with_error_word_is_not_rejected(self):
        body = "<div class='page topic'><h1 class='title'>Error Handling in Billing</h1><p>" + "Valid content sentence. " * 10 + "</p></div>"
        self.assertTrue(PE.validate_extraction(PE.extract_html(body))["ok"])

    def test_flat_text_marked_heuristic(self):
        ex = PE.extract_flat_text("Contract Accounts\nPurpose\nThis component enables you to create and manage master data for the accounts.\n", "Contract Accounts")
        self.assertEqual(ex["stats"]["structure"], "flat_text_heuristic")
        self.assertEqual(ex["blocks"][0]["heading_path"], ["Contract Accounts", "Purpose"])


def _cap(**kw):
    base = {"file": "captured_responses/x.json", "file_sha256": "0" * 64, "numeric_deliverable_id": "1", "build_no": "1", "ok": True, "reasons": [], "envelope_status": "OK",
            "page_id": "a" * 32, "guide_id": "b" * 32, "body": HTML + "<p>" + "More text here. " * 10 + "</p>", "language": "en-US", "version": "1", "deliverable_title": "G",
            "breadcrumb": ["G", "T"], "state": "PRODUCTION"}
    base.update(kw)
    return base


def _identity(**kw):
    d = dict(source_id="M2C-99", card_title="Card", card_url="https://help.sap.com/docs/P/" + "b" * 32 + "/" + "a" * 32 + ".html", card_guide_id="b" * 32, card_page_id="a" * 32,
             effective_guide_id="b" * 32, effective_page_id="a" * 32, resolution_basis="X", resolution_status=pid.IDENTIFIED_NOT_LOCAL, local_page_path=None, local_page_available=False)
    d.update(kw)
    return pid.PageIdentity(**d)


@unittest.skipUnless(HAVE_BS4, "beautifulsoup4 not installed")
class AdmissionTests(unittest.TestCase):
    def test_valid_capture_is_admitted_with_provenance(self):
        rec, notes = PC._admit_from_capture(_identity(), [_cap()])
        self.assertIsNotNone(rec)
        self.assertEqual(rec["doc_id"], "b" * 32 + "/" + "a" * 32)
        self.assertEqual(rec["source_url"], _identity().card_url)
        a = rec["acquisition"]
        self.assertIsNone(a["retrieved_at"])
        self.assertIn("no timestamp", a["retrieved_at_note"])
        self.assertIsNone(a["http_status"])
        self.assertEqual(rec["text_sha256"], hashlib.sha256(rec["text"].encode()).hexdigest())

    def test_guide_mismatch_rejected(self):
        rec, notes = PC._admit_from_capture(_identity(), [_cap(guide_id="c" * 32)])
        self.assertIsNone(rec)
        self.assertIn("DIFFERS_FROM_EFFECTIVE_GUIDE", notes[0]["reasons"][0])

    def test_page_mismatch_ignored(self):
        rec, notes = PC._admit_from_capture(_identity(), [_cap(page_id="d" * 32)])
        self.assertIsNone(rec)
        self.assertEqual(notes, [])

    def test_invalid_captures_rejected(self):
        for kw in ({"ok": False, "reasons": ["FALLBACK_PAGE"]}, {"body": "<html></html>"}):
            rec, notes = PC._admit_from_capture(_identity(), [_cap(**kw)])
            self.assertIsNone(rec)
            self.assertEqual(notes[0]["outcome"], "rejected")

    def test_load_captures_flags_bad_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / ("1_111_" + "a" * 32 + ".json")).write_text("{not json", encoding="utf-8")
            (d / ("2_111_" + "b" * 32 + ".json")).write_text(json.dumps({"status": "ERROR", "data": {"body": "x"}}), encoding="utf-8")
            (d / ("3_111_" + "c" * 32 + ".json")).write_text(json.dumps({"status": "OK", "data": {"fallback": True, "body": "<p>x</p>", "currentPage": {"loio": "c" * 32},
                                                                                              "deliverable": {"loio": "e" * 32}}}), encoding="utf-8")
            (d / "summary.json").write_text("[]", encoding="utf-8")
            caps = PC.load_captures([d], root=d)
            self.assertEqual(len(caps), 3)
            self.assertTrue(all(not c["ok"] for c in caps))
            self.assertIn("MALFORMED_JSON", caps[0]["reasons"][0])
            self.assertIn("ENVELOPE_STATUS_ERROR", caps[1]["reasons"])
            self.assertIn("FALLBACK_PAGE", caps[2]["reasons"])


@unittest.skipUnless(HAVE_BS4, "beautifulsoup4 not installed")
class CorpusManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = PC.build_corpus(write=False)
        cls.m = cls.res["manifest"]
        cls.cards = {c["source_id"]: c for c in cls.m["cards"]}

    def test_all_29_cards_have_one_explicit_status(self):
        self.assertEqual(len(self.cards), 29)
        self.assertTrue(all(c["corpus_status"] for c in self.cards.values()))
        self.assertEqual(sum(self.m["totals"]["status_counts"].values()), 29)

    def test_expected_pages_ingested(self):
        got = sorted(s for s, c in self.cards.items() if c["corpus_status"] == PC.S_INGESTED)
        self.assertEqual(got, ["M2C-02", "M2C-05", "M2C-07", "M2C-11", "M2C-14", "M2C-17", "M2C-24"])
        self.assertEqual(self.m["totals"]["pages_ingested"], 7)

    def test_m2c18_conflict_is_protected(self):
        c = self.cards["M2C-18"]
        self.assertEqual(c["corpus_status"], PC.S_CONFLICT)
        self.assertIsNone(c["effective_guide_id"])
        self.assertNotIn("record", c)
        self.assertEqual([u["page_id"] for u in self.m["unused_captures"]], ["b1a202c9bb3011da2b24000f20dac9ef"])

    def test_identity_only_cards_excluded(self):
        for s in ("M2C-01", "M2C-13", "M2C-16"):
            self.assertEqual(self.cards[s]["corpus_status"], PC.S_IDENTITY_ONLY)

    def test_m2c05_keeps_correction(self):
        rec = [r for r in self.res["records"].values() if r["source_ids"] == ["M2C-05"]][0]
        self.assertEqual(rec["identity"]["status"], pid.CORRECTED_IDENTITY)
        self.assertTrue(rec["identity"]["effective_guide_id_differs_from_card"])
        self.assertEqual(rec["guide_id"], "2ac7fe29a0c94cdd88fb80c2cb9f7758")
        self.assertNotEqual(rec["card"]["card_guide_id"], rec["guide_id"])

    def test_m2c14_review_flag_carried(self):
        rec = [r for r in self.res["records"].values() if r["source_ids"] == ["M2C-14"]][0]
        self.assertTrue(rec["card"]["review_flag"])
        self.assertEqual(self.cards["M2C-14"]["review_flag"], True)

    def test_every_record_is_valid_and_traceable(self):
        for r in self.res["records"].values():
            self.assertGreaterEqual(r["validation"]["text_chars"], PE.MIN_TEXT_CHARS)
            self.assertTrue(r["validation"]["ok"])
            self.assertEqual(r["doc_id"], f"{r['guide_id']}/{r['page_id']}")
            self.assertTrue(r["source_url"].startswith("https://help.sap.com/docs/"))
            if r["acquisition"]["type"] == "saved_sap_help_pagecontent_response":
                self.assertIsNone(r["acquisition"]["retrieved_at"])
            self.assertTrue((ROOT / r["acquisition"]["file"]).is_file())
            self.assertEqual(hashlib.sha256((ROOT / r["acquisition"]["file"]).read_bytes()).hexdigest(), r["acquisition"]["file_sha256"])
            self.assertTrue(r["breadcrumb"])

    def test_card_url_is_never_rewritten(self):
        cards = {c["source_id"]: c for c in pid.load_cards(ROOT)}
        for r in self.res["records"].values():
            self.assertEqual(r["source_url"], cards[r["source_ids"][0]]["source_url"])

    def test_no_raw_html_in_text(self):
        for r in self.res["records"].values():
            self.assertNotRegex(r["text"], r"</?(div|p|span|table|li|ul)\b")

    def test_deterministic_manifest(self):
        again = PC.build_corpus(write=False)
        self.assertEqual(PC.canonical_json(again["manifest"]), PC.canonical_json(self.m))
        self.assertEqual(again["manifest"]["corpus_sha256"], self.m["corpus_sha256"])

    def test_fetch_plan_has_no_guessed_ids(self):
        recorded = {c["guide_id"]: (c["numeric_deliverable_id"], c["build_no"]) for c in PC.load_captures() if c["ok"]}
        for p in self.res["fetch_plan"]["pages_to_fetch"]:
            if p["fetchable_with_recorded_ids"]:
                self.assertEqual((p["numeric_deliverable_id"], p["build_no"]), recorded[p["guide_id"]])
            else:
                self.assertIsNone(p["request"])
                self.assertTrue(p["blocker"])

    def test_committed_manifest_matches_rebuild(self):
        p = PC.CORPUS_DIR / "manifest.json"
        if not p.is_file():
            self.skipTest("data/page_corpus/manifest.json not built")
        self.assertEqual(p.read_text(encoding="utf-8"), PC.canonical_json(self.m))
        for r in self.res["records"].values():
            f = PC.CORPUS_DIR / "pages" / r["guide_id"] / f"{r['page_id']}.json"
            self.assertEqual(f.read_text(encoding="utf-8"), PC.canonical_json(r))

    def test_legacy_corpus_not_touched(self):
        self.assertFalse((ROOT / "data" / "sap_help" / "pages" / "9442486404b54071b4ebeab6a16628e7").exists())
        self.assertEqual(len(list((ROOT / "data" / "sap_help" / "pages").glob("*/*.json"))), 1)


@unittest.skipUnless(HAVE_BS4, "beautifulsoup4 not installed")
class FetcherTests(unittest.TestCase):
    ENTRY = {"source_id": "M2C-03", "guide_id": "b" * 32, "page_id": "a" * 32, "numeric_deliverable_id": "11", "build_no": "7", "fetchable_with_recorded_ids": True, "blocker": None}

    @staticmethod
    def good(entry=None):
        e = entry or FetcherTests.ENTRY
        return json.dumps({"status": "OK", "data": {"body": "<p>x</p>", "currentPage": {"loio": e["page_id"]}, "deliverable": {"loio": e["guide_id"]}}}).encode()

    def run_fetch(self, transport, plan=None, **kw):
        with tempfile.TemporaryDirectory() as d:
            kw.setdefault("sleep", lambda s: None)
            kw.setdefault("out_dir", Path(d))
            log = PF.fetch_plan(plan or {"pages_to_fetch": [self.ENTRY]}, transport=transport, **kw)
            saved = [p.name for p in Path(d).glob("*.json")]
            return log, saved

    def test_network_off_makes_no_request(self):
        calls = []
        log, saved = self.run_fetch(lambda u, t: calls.append(u), allow_network=False)
        self.assertEqual(calls, [])
        self.assertEqual(saved, [])
        self.assertIn("NETWORK_DISABLED", log["stopped_reason"])

    def test_robots_disallow_all_refuses_without_acknowledgement(self):
        urls = []
        def tr(u, t):
            urls.append(u)
            return 200, b"User-agent: *\nDisallow: /\n", None
        log, saved = self.run_fetch(tr, allow_network=True)
        self.assertEqual(len(urls), 1)
        self.assertTrue(urls[0].endswith("/robots.txt"))
        self.assertIn("ROBOTS_DISALLOW_ALL", log["stopped_reason"])
        self.assertEqual(saved, [])

    def test_acknowledged_fetch_saves_only_valid_matching_response(self):
        def tr(u, t):
            return (200, b"User-agent: *\nDisallow: /\n", None) if u.endswith("robots.txt") else (200, self.good(), None)
        log, saved = self.run_fetch(tr, allow_network=True, acknowledge_robots=True)
        self.assertEqual(len(saved), 1)
        self.assertTrue(log["robots"]["operator_acknowledged"])

    def test_mismatched_or_bad_responses_are_not_saved(self):
        bad = {"guide": json.dumps({"status": "OK", "data": {"body": "<p>x</p>", "currentPage": {"loio": "a" * 32}, "deliverable": {"loio": "f" * 32}}}).encode(),
               "page": json.dumps({"status": "OK", "data": {"body": "<p>x</p>", "currentPage": {"loio": "f" * 32}, "deliverable": {"loio": "b" * 32}}}).encode(),
               "fallback": json.dumps({"status": "OK", "data": {"fallback": True, "body": "<p>x</p>", "currentPage": {"loio": "a" * 32}, "deliverable": {"loio": "b" * 32}}}).encode(),
               "empty": json.dumps({"status": "OK", "data": {"body": " ", "currentPage": {"loio": "a" * 32}, "deliverable": {"loio": "b" * 32}}}).encode(),
               "notjson": b"<html>captcha</html>"}
        for name, body in bad.items():
            log, saved = self.run_fetch(lambda u, t, body=body: (404, b"", None) if u.endswith("robots.txt") else (200, body, None), allow_network=True)
            self.assertEqual(saved, [], name)
            self.assertFalse(log["attempts"][0]["ok"], name)

    def test_http_blocks_are_logged_not_bypassed_and_breaker_stops(self):
        plan = {"pages_to_fetch": [dict(self.ENTRY, source_id=f"M2C-{i}", page_id=f"{i:032x}") for i in range(10)]}
        calls = []
        def tr(u, t):
            calls.append(u)
            return (404, b"", None) if u.endswith("robots.txt") else (429, b"", None)
        log, saved = self.run_fetch(tr, plan=plan, allow_network=True, breaker=3)
        self.assertEqual(len(log["attempts"]), 3)
        self.assertIn("CIRCUIT_BREAKER", log["stopped_reason"])
        self.assertEqual(saved, [])
        self.assertEqual(len(calls), 4)                               # robots + 3 attempts, no retries

    def test_entries_without_recorded_ids_are_skipped(self):
        plan = {"pages_to_fetch": [dict(self.ENTRY, fetchable_with_recorded_ids=False, numeric_deliverable_id=None, build_no=None, blocker="never guessed")]}
        calls = []
        log, _ = self.run_fetch(lambda u, t: calls.append(u) or (404, b"", None), plan=plan, allow_network=True)
        self.assertEqual(log["attempts"], [])
        self.assertEqual(log["skipped"][0]["reason"], "never guessed")

    def test_rate_limit_delay_applied_between_requests(self):
        plan = {"pages_to_fetch": [dict(self.ENTRY, source_id=f"M2C-{i}", page_id=f"{i:032x}") for i in range(3)]}
        sleeps = []
        def tr(u, t):
            if u.endswith("robots.txt"):
                return 404, b"", None
            pid_ = u.split("file_path=")[1][:32]
            return 200, self.good(dict(self.ENTRY, page_id=pid_)), None
        log, saved = self.run_fetch(tr, plan=plan, allow_network=True, delay_s=2.5, sleep=sleeps.append)
        self.assertEqual(sleeps, [2.5, 2.5])
        self.assertEqual(len(saved), 3)

    def test_saved_file_is_ingestible_by_the_corpus_loader(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            PF.fetch_plan({"pages_to_fetch": [self.ENTRY]}, True, transport=lambda u, t: (404, b"", None) if u.endswith("robots.txt") else (200, self.good(), None),
                          out_dir=d, sleep=lambda s: None)
            caps = PC.load_captures([d], root=d)
            self.assertEqual(len(caps), 1)
            self.assertTrue(caps[0]["ok"])
            self.assertEqual((caps[0]["guide_id"], caps[0]["page_id"]), ("b" * 32, "a" * 32))

    def test_only_fetcher_and_cli_may_use_network_libraries(self):
        banned = {"requests", "urllib.request", "urllib.error", "http.client", "socket", "ollama"}
        for name in ("page_extract", "page_corpus", "page_chunker", "build_page_collection", "page_retriever", "rag_context", "rag_generate", "page_citations",
                     "rag_pipeline", "rag_text", "evaluate_phase8", "rag_answer"):
            p = SCRIPTS / f"{name}.py"
            if not p.is_file():
                continue
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for m in mods:
                    top_level = isinstance(node, (ast.Import, ast.ImportFrom)) and node in ast.parse(p.read_text(encoding="utf-8")).body
                    if m in banned and top_level:
                        self.fail(f"{name} imports {m} at module level")
        src = (SCRIPTS / "page_fetch.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        self.assertFalse([n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) and any(getattr(a, "name", "") == "requests" for a in getattr(n, "names", []))])


if __name__ == "__main__":
    unittest.main()
