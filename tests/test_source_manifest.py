"""Phase-0 source registry (scripts/build_source_manifest.py)."""
import csv
import hashlib
import importlib.util
import json
import shutil
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
    spec = importlib.util.spec_from_file_location("bsm", ROOT / "scripts" / "build_source_manifest.py")
    m = importlib.util.module_from_spec(spec); sys.modules["bsm"] = m; spec.loader.exec_module(m)
    return m


G, P = "a" * 32, "b" * 32
GOOD = f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G}/{P}.html"
CARD = """SAP Utilities M2C Source Reference 07
 Some Title
 Continued
Category: Cat A
What it covers
Covers x
and y.
Meter-to-Cash
relevance
Relevant z.
Authoritative SAP Help source
Open this topic on SAP Help Portal
https:/&#8203;/&#8203;help.sap.com/&#8203;docs/&#8203;SAP_S4HANA_ON-PREMISE/&#8203;aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/&#8203;bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.html
Library use
Use this.
Copyright / distribution note
Note.
"""


class ParseTests(unittest.TestCase):
    def test_parse_card_joins_wrapped_lines_and_keeps_words(self):
        m = _mod()
        c = m.parse_card(CARD)
        self.assertEqual((c["reference_number_text"], c["title"], c["category"]), ("07", "Some Title Continued", "Cat A"))
        self.assertEqual(m._squash(c["sections"]["What it covers"]), "Covers x and y.")
        self.assertEqual(m._squash(c["sections"]["Meter-to-Cash relevance"]), "Relevant z.")
        self.assertEqual(c["issues"], [])

    def test_missing_pieces_are_reported_not_guessed(self):
        m = _mod()
        self.assertTrue(m.parse_card("nothing here")["issues"])
        c = m.parse_card(CARD.replace("Category: Cat A\n", ""))
        self.assertIsNone(c["category"])
        self.assertTrue(any("Category" in i for i in c["issues"]))

    def test_url_assessment(self):
        m = _mod()
        disp = ["Open this topic on SAP Help Portal",
                "https:/&#8203;/&#8203;help.sap.com/&#8203;docs/&#8203;SAP_S4HANA_ON-PREMISE/&#8203;" + G, "/&#8203;" + P + ".html"]
        a = m.assess_url([GOOD], disp)
        self.assertEqual((a["url"], a["status"]), (GOOD, "ok"))                     # value = annotation, unchanged
        self.assertTrue(a["notes"] and "&#8203;" in a["display_raw"])               # printed text preserved verbatim
        self.assertEqual(m.assess_url([], disp)["status"], "needs_review")          # printed text alone is never trusted
        self.assertIsNone(m.assess_url([], disp)["url"])
        self.assertEqual(m.assess_url([], None)["status"], "missing")
        for bad in (GOOD + "?version=2025.001", GOOD.replace("SAP_S4HANA_ON-PREMISE", "sap_s4hana_on-premise"),
                    GOOD.replace("https://", "http://"), GOOD.replace("help.sap.com", "example.com"),
                    GOOD.replace(G, G[:-3]), GOOD[:-10]):
            r = m.assess_url([bad], None)
            self.assertEqual((r["status"], r["url"]), ("needs_review", bad), bad)    # flagged, never repaired
        self.assertEqual(m.assess_url([GOOD, GOOD.replace(P, "c" * 32)], None)["status"], "needs_review")   # two different links
        self.assertEqual(m.assess_url([GOOD], ["x", GOOD.replace("a" * 4, "a" * 3 + "c")])["status"], "needs_review")  # printed != annotation

    def test_numbering_validation(self):
        m = _mod()
        tmp = Path(tempfile.mkdtemp())
        try:
            names = list(m.EXPECTED_FILENAMES)
            names.remove("05_Device_Management_Overview.pdf")                          # missing 05
            names.append("05_Something_Else.pdf")                                      # wrong name for 05
            names.append("12_Duplicate_Twelve.pdf")                                    # duplicate number 12
            names.append("Readme.pdf")                                                 # no prefix
            pdfs = []
            for n in names:
                (tmp / n).write_bytes(b"%PDF-1.4 " + n.encode())
                pdfs.append(tmp / n)
            docs = [{"filename": p.name, "pdf_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "authoritative_source": None, "title": None} for p in pdfs]
            v = m.validate_numbering(pdfs, docs)
            self.assertFalse(v["numbering_ok"])
            self.assertEqual(v["duplicate_numbers"], ["12"])
            self.assertIn("05_Device_Management_Overview.pdf", v["missing_expected_filenames"])
            self.assertEqual(v["files_without_number_prefix"], ["Readme.pdf"])
            self.assertEqual(sorted(v["filename_number_mismatches"], key=lambda x: x["file"]),
                             [{"file": "05_Something_Else.pdf", "expected": "05_Device_Management_Overview.pdf"},
                              {"file": "12_Duplicate_Twelve.pdf", "expected": "12_Automatic_Billing.pdf"}])
            self.assertEqual(v["missing_numbers"], [])                                 # number 05 is present, only the name differs
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(HAVE_PYPDF and (ROOT / "01_Utilities_Master_Data.pdf").is_file(), "needs pypdf and the 29 PDFs")
class RealPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _mod()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("[0-9][0-9]_*.pdf")}
        cls.rc = cls.m.main(["--out-dir", str(cls.tmp)])
        cls.docs = json.loads((cls.tmp / "source_manifest.json").read_text(encoding="utf-8"))["documents"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_29_documents_in_order_with_expected_names(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual([d["id"] for d in self.docs], [f"{i:02d}" for i in range(1, 30)])
        self.assertEqual([d["filename"] for d in self.docs], self.m.EXPECTED_FILENAMES)
        for d in self.docs:
            for k in ("title", "category", "what_it_covers", "meter_to_cash_relevance", "authoritative_source"):
                self.assertTrue(d[k], (d["id"], k))
            self.assertEqual(d["source_type"], "SAP Help Portal")
            self.assertEqual(d["reference_number_in_text"].lstrip("0"), d["id"].lstrip("0"))
            self.assertTrue(d["extraction_ok"])

    def test_urls_are_the_exact_annotations(self):
        from pypdf import PdfReader
        for d in self.docs:
            r = PdfReader(str(ROOT / d["filename"]))
            uris = [str(a.get_object()["/A"].get_object()["/URI"]) for p in r.pages for a in (p.get("/Annots") or [])]
            self.assertEqual(d["authoritative_source"], uris[0], d["id"])
            self.assertNotIn("&#8203;", d["authoritative_source"])
            self.assertIn("&#8203;", d["source_url_display"])                          # printed form preserved verbatim

    def test_known_deviations_are_flagged_not_repaired(self):
        by = {d["id"]: d for d in self.docs}
        self.assertEqual(sorted(i for i, d in by.items() if d["source_url_status"] == "needs_review"), ["14", "18", "23"])
        self.assertIn("sap_s4hana_on-premise", by["14"]["authoritative_source"])       # lowercase product kept as found
        self.assertTrue(by["18"]["authoritative_source"].endswith("?version=2025.001"))
        self.assertTrue(all(d["status"] == "verified" for i, d in by.items() if i not in ("14", "18", "23")))

    def test_outputs_exist_csv_has_29_rows_and_pdfs_untouched(self):
        for n in ("source_manifest.json", "source_manifest.csv", "source_inventory.md", "source_validation_report.md"):
            self.assertTrue((self.tmp / n).is_file(), n)
        rows = list(csv.DictReader((self.tmp / "source_manifest.csv").open(encoding="utf-8", newline="")))
        self.assertEqual(len(rows), 29)
        self.assertEqual(rows[17]["id"], "18")
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("[0-9][0-9]_*.pdf")}
        self.assertEqual(self.before, after)
        rep = (self.tmp / "source_validation_report.md").read_text(encoding="utf-8")
        for h in ("Total PDFs found", "Missing numbers", "Duplicate", "Extraction failures", "missing SAP Help URL", "suspicious", "manual verification"):
            self.assertIn(h, rep)

    def test_deterministic(self):
        t2 = Path(tempfile.mkdtemp())
        try:
            self.m.main(["--out-dir", str(t2)])
            for n in ("source_manifest.json", "source_manifest.csv", "source_inventory.md", "source_validation_report.md"):
                self.assertEqual((self.tmp / n).read_bytes(), (t2 / n).read_bytes(), n)
        finally:
            shutil.rmtree(t2, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
