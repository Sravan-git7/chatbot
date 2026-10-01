"""Phase-2 source corpus (scripts/build_source_corpus.py): offline, deterministic, traceable."""
import ast
import hashlib
import importlib.util
import json
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    import pypdf  # noqa: F401
    HAVE_PYPDF = True
except ImportError:
    HAVE_PYPDF = False


def _mod():
    spec = importlib.util.spec_from_file_location("bsc", ROOT / "scripts" / "build_source_corpus.py")
    m = importlib.util.module_from_spec(spec); sys.modules["bsc"] = m; spec.loader.exec_module(m)
    return m


MANIFEST = ROOT / "data" / "source_manifest.json"
URL = "https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/" + "a" * 32 + "/" + "b" * 32 + ".html"


class NormalisationUnitTests(unittest.TestCase):
    def test_wrapped_lines_joined_paragraphs_and_blanks(self):
        m = _mod(); ops = m.Ops()
        out = m.normalise_lines(["Explains the  move-in", "process and", "", "", "  second   paragraph ", ""], ops)
        self.assertEqual(out, "Explains the move-in process and\n\nsecond paragraph")
        self.assertEqual(ops["wrapped_lines_joined"], 1)
        self.assertGreaterEqual(ops["repeated_spaces_collapsed"], 2)
        self.assertGreaterEqual(ops["repeated_or_edge_blank_lines_dropped"], 1)

    def test_words_are_never_merged_split_or_corrected(self):
        m = _mod(); ops = m.Ops()
        lines = ["Meter-", "reading of the compo-", "nent Utlities"]                 # hyphen breaks + a typo
        out = m.normalise_lines(lines, ops)
        self.assertEqual(out.split(), ["Meter-", "reading", "of", "the", "compo-", "nent", "Utlities"])
        self.assertEqual(ops["hyphen_line_end_candidates_preserved_as_is"], 2)       # 'Meter-'/'compo-' line-end hyphens: counted, kept, NOT joined

    def test_mechanical_code_points(self):
        m = _mod(); ops = m.Ops()
        out = m.normalise_lines(["e\ufb03cient\u00a0use\u200b of\tit"], ops)
        self.assertEqual(out, "efficient use of it")
        self.assertEqual((ops["ligature_code_points_mapped"], ops["nbsp_like_spaces_mapped_to_space"],
                          ops["zero_width_characters_removed"], ops["tabs_mapped_to_space"]), (1, 1, 1, 1))

    def test_bullets_stay_separate_lines(self):
        m = _mod()
        self.assertEqual(m.normalise_lines(["Intro text", "- first item", "continues here", "- second item"], m.Ops()),
                         "Intro text\n- first item continues here\n- second item")

    def test_printed_url_rejoined_only_if_equal_to_the_annotation(self):
        m = _mod(); ops = m.Ops()
        printed = ["Open this topic on SAP Help Portal",
                   "https:/&#8203;/&#8203;help.sap.com/&#8203;docs/&#8203;SAP_S4HANA_ON-PREMISE/&#8203;" + "a" * 32, "/&#8203;" + "b" * 32 + ".html"]
        text, info = m.normalise_url_block(printed, URL, ops)
        self.assertEqual(text, "Open this topic on SAP Help Portal\n" + URL)
        self.assertTrue(info["url_equals_manifest_annotation"])
        self.assertEqual(ops["printed_url_zwsp_entities_removed"], 6)
        ops2 = m.Ops()
        text2, info2 = m.normalise_url_block(printed, URL.replace("b" * 32, "c" * 32), ops2)      # differs: nothing is repaired
        self.assertFalse(info2["url_equals_manifest_annotation"])
        self.assertIn("&#8203;", info2["printed_url_raw"])
        self.assertEqual(ops2["printed_url_preserved_verbatim_not_equal_to_annotation"], 1)
        self.assertNotIn("c" * 32, text2)


class NoNetworkTests(unittest.TestCase):
    def test_scripts_import_no_network_modules(self):
        banned = {"socket", "requests", "ftplib", "ssl", "httpx", "aiohttp", "urllib3", "smtplib", "xmlrpc", "http",
                  "urllib", "urllib.request", "urllib.error", "http.client"}          # urllib.parse (string parsing only) is allowed
        for f in ("build_source_corpus.py", "build_source_manifest.py"):
            tree = ast.parse((ROOT / "scripts" / f).read_text(encoding="utf-8"))
            names = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    names |= {a.name for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.module:
                    names.add(n.module)
                    names |= {n.module + "." + a.name for a in n.names}
            self.assertFalse(names & banned, (f, names & banned))


@unittest.skipUnless(HAVE_PYPDF and MANIFEST.is_file() and (ROOT / "01_Utilities_Master_Data.pdf").is_file(), "needs pypdf, the manifest and the PDFs")
class RealCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _mod()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pdf_hash = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("[0-9][0-9]_*.pdf")}
        cls.manifest_hash = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        real_connect, real_gai = socket.socket.connect, socket.getaddrinfo

        def boom(*a, **k):
            raise AssertionError("network access attempted")
        socket.socket.connect, socket.getaddrinfo = boom, boom               # any network use would fail the build
        try:
            cls.rc = cls.m.main(["--out-dir", str(cls.tmp / "a")])
        finally:
            socket.socket.connect, socket.getaddrinfo = real_connect, real_gai
        cls.corpus = json.loads((cls.tmp / "a" / "source_corpus.json").read_text(encoding="utf-8"))
        cls.docs = cls.corpus["documents"]
        cls.man = json.loads(MANIFEST.read_text(encoding="utf-8"))["documents"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_exactly_29_documents_each_manifest_entry_once_in_order(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual((self.corpus["document_count"], self.corpus["extracted_count"], self.corpus["failed_count"]), (29, 29, 0))
        self.assertEqual([d["source_number"] for d in self.docs], list(range(1, 30)))
        self.assertEqual(len({d["source_number"] for d in self.docs}), 29)
        self.assertEqual(len({d["source_id"] for d in self.docs}), 29)
        self.assertEqual(sorted(d["filename"] for d in self.docs), sorted(m["filename"] for m in self.man))

    def test_metadata_matches_manifest_and_pdfs(self):
        for d, m in zip(self.docs, self.man):
            self.assertEqual((d["filename"], d["title"], d["category"], d["sha256"], d["page_count"], d["status"]),
                             (m["filename"], m["title"], m["category"], m["pdf_sha256"], m["pdf_pages"], m["status"]), m["id"])
            self.assertEqual(d["sha256"], self.pdf_hash[d["filename"]])
            self.assertEqual(d["authoritative_source"], m["authoritative_source"])          # URL untouched
            self.assertEqual(d["extraction_status"], "extracted")
            self.assertFalse(d["sap_page_externally_verified"])

    def test_no_empty_content_and_nothing_lost(self):
        for d in self.docs:
            self.assertTrue(d["content"].strip(), d["source_id"])
            self.assertGreater(d["stats"]["words"], 20)
            keys = [s["key"] for s in d["sections"]]
            self.assertEqual(keys, ["reference_line", "title", "category", "what_it_covers", "meter_to_cash_relevance",
                                    "authoritative_source", "library_use", "copyright_note"], d["source_id"])
            for s in d["sections"]:
                self.assertEqual(d["content"][s["char_start"]:s["char_end"]], s["text"], s["section_id"])   # offsets trace into content
                self.assertEqual((s["page_start"], s["page_end"]), (1, 1))
                if s["key"] != "authoritative_source":
                    self.assertEqual(s["text"].split(), " ".join(s["text_raw"].split("\n")).split(), s["section_id"])   # no word lost/changed
            self.assertIn(d["authoritative_source"], d["content"])                        # exact manifest URL is in the content
            self.assertNotIn("&#8203;", d["content"])
            self.assertIn("Library use", d["content"])
            self.assertIn("Copyright / distribution note", d["content"])

    def test_chunking_provenance_fields(self):
        for d in self.docs:
            p = d["provenance"]
            for k in ("source_id", "source_number", "filename", "sha256", "title", "category", "status", "authoritative_source", "citation"):
                self.assertTrue(p[k], (d["source_id"], k))
            self.assertIn(d["sha256"][:12], p["citation"])
            for s in d["sections"]:
                self.assertTrue(s["section_id"].startswith(d["source_id"] + "#"))

    def test_review_flags_and_corrections_are_preserved_as_metadata(self):
        for d, m in zip(self.docs, self.man):
            self.assertEqual((d["review"]["manifest_status"], d["review"]["source_url_status"],
                              d["review"]["source_url_reasons"], d["review"]["review_reasons"]),
                             (m["status"], m["source_url_status"], m["source_url_reasons"], m["review_reasons"]))
        by = {d["source_number"]: d for d in self.docs}
        self.assertEqual(sorted(n for n, d in by.items() if d["status"] != "verified"), [14, 18, 23])
        self.assertIn("sap_s4hana_on-premise", by[14]["authoritative_source"])              # casing NOT repaired
        self.assertIn("sap_s4hana_on-premise", by[14]["content"])
        for n in (18, 23):
            self.assertTrue(by[n]["authoritative_source"].endswith("?version=2025.001"))   # query kept
            self.assertIn("?version=2025.001", by[n]["content"])
        c = by[5]["source_correction"]
        self.assertEqual((c["type"], c["card_guide_id"][:8], c["resolved_guide_id"][:8], c["applied_to_content"]),
                         ("card_guide_correction", "021b182b", "2ac7fe29", False))
        self.assertIn("021b182b0c47416c8fafed67ebfd78a9", by[5]["authoritative_source"])   # source of record unchanged
        self.assertEqual([n for n, d in by.items() if d["source_correction"]], [5])        # no other correction is invented
        self.assertFalse(by[18]["external_finding"]["is_correction"])
        self.assertIsNone(by[18]["source_correction"])

    def test_inputs_unmodified(self):
        self.assertEqual(self.pdf_hash, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("[0-9][0-9]_*.pdf")})
        self.assertEqual(self.manifest_hash, hashlib.sha256(MANIFEST.read_bytes()).hexdigest())

    def test_two_runs_are_byte_identical(self):
        self.m.main(["--out-dir", str(self.tmp / "b")])
        for n in ("source_corpus.json", "source_corpus.md", "source_corpus_validation_report.md"):
            self.assertEqual((self.tmp / "a" / n).read_bytes(), (self.tmp / "b" / n).read_bytes(), n)

    def test_report_separates_verified_extracted_and_external_verification(self):
        rep = (self.tmp / "a" / "source_corpus_validation_report.md").read_text(encoding="utf-8")
        for h in ("`verified` (manifest `status`)", "extracted successfully", "SAP page externally verified", "Normalisation operations",
                  "Per-document status", "Review items", "total documents", "empty content", "total pages", "Test results"):
            self.assertIn(h, rep)
        self.assertIn("None were", rep.replace("none were", "None were"))
        self.assertEqual(self.corpus["sap_pages_externally_verified"], 0)

    def test_failures_are_reported_not_hidden(self):
        t = Path(tempfile.mkdtemp())
        try:
            man = json.loads(MANIFEST.read_text(encoding="utf-8"))
            man["documents"][0]["pdf_sha256"] = "0" * 64                                 # sha mismatch
            man["documents"][1]["filename"] = "does_not_exist.pdf"                        # missing PDF
            (t / "m.json").write_text(json.dumps(man), encoding="utf-8")
            rc = self.m.main(["--manifest", str(t / "m.json"), "--out-dir", str(t / "o")])
            c = json.loads((t / "o" / "source_corpus.json").read_text(encoding="utf-8"))
            self.assertEqual(rc, 1)
            self.assertEqual((c["document_count"], c["extracted_count"], c["failed_count"]), (29, 27, 2))
            bad = [d for d in c["documents"] if d["extraction_status"] != "extracted"]
            self.assertEqual(len(bad), 2)
            self.assertTrue(all(d["extraction_error"] and d["content"] == "" for d in bad))
        finally:
            shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
