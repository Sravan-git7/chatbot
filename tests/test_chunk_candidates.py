"""Phase-3 chunk candidates (scripts/build_chunk_candidates.py): structural, offline, deterministic. No embeddings."""
import ast
import hashlib
import importlib.util
import json
import re
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "source_corpus.json"
MANIFEST = ROOT / "data" / "source_manifest.json"
STRATS = ("whole_document", "section_based", "bounded_sections")


def _mod():
    spec = importlib.util.spec_from_file_location("bcc", ROOT / "scripts" / "build_chunk_candidates.py")
    m = importlib.util.module_from_spec(spec); sys.modules["bcc"] = m; spec.loader.exec_module(m)
    return m


class SplitUnitTests(unittest.TestCase):
    TEXT = ("Heading\nFirst sentence is here. Second sentence follows it. Third sentence closes the section.")

    def test_no_split_when_short(self):
        m = _mod()
        self.assertEqual(m.split_span(self.TEXT, 0, len(self.TEXT), 500), [(0, len(self.TEXT), False)])

    def test_splits_at_sentence_boundaries_only_and_respects_max(self):
        m = _mod()
        parts = m.split_span(self.TEXT, 0, len(self.TEXT), 50)
        self.assertGreater(len(parts), 1)
        for s, e, over in parts:
            self.assertFalse(over)
            self.assertLessEqual(e - s, 50)
            self.assertTrue(self.TEXT[s:e].rstrip().endswith((".", "Heading")) or self.TEXT[s:e].endswith("."), self.TEXT[s:e])
        # exact, ordered, non-overlapping slices; only whitespace between them
        pos = 0
        for s, e, _ in parts:
            self.assertGreaterEqual(s, pos)
            self.assertEqual(self.TEXT[pos:s].strip(), "")
            pos = e
        self.assertEqual(self.TEXT[pos:].strip(), "")
        self.assertEqual("".join("".join(self.TEXT[s:e].split()) for s, e, _ in parts), "".join(self.TEXT.split()))

    def test_long_sentence_falls_back_to_words_and_token_is_never_cut(self):
        m = _mod()
        t = "alpha beta gamma delta epsilon zeta eta theta"
        parts = m.split_span(t, 0, len(t), 15)
        self.assertTrue(all(t[s:e] == t[s:e].strip() and " " not in t[s:e].strip() or len(t[s:e]) <= 15 for s, e, _ in parts))
        url = "https://help.sap.com/docs/" + "a" * 60
        (s, e, over), = m.split_span(url, 0, len(url), 20)
        self.assertEqual((url[s:e], over), (url, True))                     # kept whole and flagged, never cut

    def test_invalid_max(self):
        with self.assertRaises(ValueError):
            _mod().split_span("abc", 0, 3, 0)


class NoNetworkTests(unittest.TestCase):
    def test_script_imports_no_network_modules(self):
        banned = {"socket", "requests", "ftplib", "ssl", "httpx", "aiohttp", "urllib3", "smtplib", "http", "urllib",
                  "urllib.request", "urllib.error", "http.client", "sentence_transformers", "chromadb", "torch", "numpy"}
        tree = ast.parse((ROOT / "scripts" / "build_chunk_candidates.py").read_text(encoding="utf-8"))
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                names.add(n.module)
        self.assertFalse(names & banned, names & banned)


@unittest.skipUnless(CORPUS.is_file(), "needs data/source_corpus.json")
class RealChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _mod()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.corpus_hash = hashlib.sha256(CORPUS.read_bytes()).hexdigest()
        cls.manifest_hash = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        cls.pdf_hash = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("[0-9][0-9]_*.pdf")}
        real_c, real_g = socket.socket.connect, socket.getaddrinfo

        def boom(*a, **k):
            raise AssertionError("network access attempted")
        socket.socket.connect, socket.getaddrinfo = boom, boom
        try:
            cls.rc = cls.m.main(["--out-dir", str(cls.tmp / "a")])
        finally:
            socket.socket.connect, socket.getaddrinfo = real_c, real_g
        cls.out = {s: json.loads((cls.tmp / "a" / f"{s}.json").read_text(encoding="utf-8")) for s in STRATS}
        cls.corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        cls.docs = {d["source_id"]: d for d in cls.corpus["documents"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def chunks(self, s):
        return self.out[s]["chunks"]

    def test_run_succeeds_and_inputs_unmodified(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual(self.corpus_hash, hashlib.sha256(CORPUS.read_bytes()).hexdigest())
        self.assertEqual(self.manifest_hash, hashlib.sha256(MANIFEST.read_bytes()).hexdigest())
        self.assertEqual(self.pdf_hash, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("[0-9][0-9]_*.pdf")})

    def test_all_29_sources_represented_in_every_strategy(self):
        for s in STRATS:
            self.assertEqual({c["source_number"] for c in self.chunks(s)}, set(range(1, 30)), s)
            self.assertEqual({c["source_id"] for c in self.chunks(s)}, set(self.docs), s)

    def test_ids_unique_deterministic_and_well_formed(self):
        for s in STRATS:
            ids = [c["chunk_id"] for c in self.chunks(s)]
            self.assertEqual(len(ids), len(set(ids)), s)
            for c in self.chunks(s):
                self.assertRegex(c["chunk_id"], r"^M2C-\d{2}-C\d{2}$")
                self.assertEqual(c["chunk_id"], f"{c['source_id']}-C{c['chunk_index']:02d}")
                self.assertEqual(c["source_id"], f"M2C-{c['source_number']:02d}")
                self.assertEqual(c["strategy"], s)
        self.assertEqual(self.chunks("whole_document")[0]["chunk_id"], "M2C-01-C01")

    def test_every_chunk_maps_to_corpus_document_and_section(self):
        for s in STRATS:
            for c in self.chunks(s):
                d = self.docs[c["source_id"]]
                for k, dk in (("source_number", "source_number"), ("filename", "filename"), ("title", "title"), ("category", "category"),
                              ("sha256", "sha256"), ("source_status", "status"), ("source_url", "authoritative_source")):
                    self.assertEqual(c[k], d[dk], (c["chunk_id"], k))
                ids = {x["section_id"] for x in d["sections"]}
                self.assertTrue(set(c["section_ids"]) <= ids)
                if c["section_id"] is not None:
                    self.assertIn(c["section_id"], ids)
                self.assertEqual((c["page_start"], c["page_end"]), (1, 1))
                self.assertIn(d["provenance"]["citation"], c["citation"])
                self.assertTrue(c["citation"].endswith(f"chars {c['char_start']}-{c['char_end']}"))
                self.assertIn(c["sha256"][:12], c["citation"])

    def test_no_empty_text_and_text_is_exact_source_slice(self):
        for s in STRATS:
            for c in self.chunks(s):
                self.assertTrue(c["text"].strip(), c["chunk_id"])
                self.assertEqual(c["text"], self.docs[c["source_id"]]["content"][c["char_start"]:c["char_end"]], c["chunk_id"])
                self.assertEqual((c["char_count"], c["word_count"]), (len(c["text"]), len(c["text"].split())))

    def test_no_source_text_lost_or_introduced_and_only_separator_whitespace_omitted(self):
        for s in STRATS:
            per = {}
            for c in self.chunks(s):
                per.setdefault(c["source_id"], []).append(c)
            for sid, cs in per.items():
                content = self.docs[sid]["content"]
                cs.sort(key=lambda c: c["char_start"])
                self.assertEqual("".join(content.split()), "".join("".join(c["text"].split()) for c in cs), (s, sid))
                pos = 0
                for c in cs:
                    self.assertGreaterEqual(c["char_start"], pos, "overlap")
                    self.assertEqual(content[pos:c["char_start"]].strip(), "", (s, c["chunk_id"]))
                    pos = c["char_end"]
                self.assertEqual(content[pos:].strip(), "")

    def test_whole_document_strategy_is_exactly_29_chunks(self):
        cs = self.chunks("whole_document")
        self.assertEqual(len(cs), 29)
        for c in cs:
            d = self.docs[c["source_id"]]
            self.assertEqual(c["text"], d["content"].strip())
            self.assertEqual((c["chunks_in_source"], c["section_id"]), (1, None))
            self.assertEqual(len(c["section_ids"]), len(d["sections"]))

    def test_section_strategy_uses_only_existing_section_boundaries(self):
        m = self.m
        self.assertEqual(len(self.chunks("section_based")), sum(len(d["sections"]) for d in self.docs.values()))
        for c in self.chunks("section_based"):
            d = self.docs[c["source_id"]]
            sec = next(x for x in d["sections"] if x["section_id"] == c["section_id"])
            self.assertEqual((c["char_start"], c["char_end"]), m.section_span(d, sec))
            self.assertEqual(c["section_key"], sec["key"])
            self.assertTrue(c["text"].endswith(sec["text"]))                      # body is the corpus section text
            if sec["heading"]:
                self.assertTrue(c["text"].startswith(sec["heading"] + "\n"))
            self.assertEqual((c["section_part_index"], c["section_part_count"]), (1, 1))
        per = {}
        for c in self.chunks("section_based"):
            per.setdefault(c["source_id"], set()).add(c["section_id"])
        for sid, ids in per.items():
            self.assertEqual(ids, {x["section_id"] for x in self.docs[sid]["sections"]})

    def test_bounded_strategy_default_and_its_limit(self):
        m = self.m
        mx = m.DEFAULT_MAX_CHARS
        self.assertEqual(self.out["bounded_sections"]["parameters"]["max_chars"], mx)
        cs = self.chunks("bounded_sections")
        self.assertGreater(len(cs), len(self.chunks("section_based")))             # the default does split something
        for c in cs:
            if not c["exceeds_max_chars"]:
                self.assertLessEqual(c["char_count"], mx, c["chunk_id"])
            d = self.docs[c["source_id"]]
            sec = next(x for x in d["sections"] if x["section_id"] == c["section_id"])
            a, b = m.section_span(d, sec)
            self.assertTrue(a <= c["char_start"] and c["char_end"] <= b, "chunk crosses its section")      # never crosses sections
            if c["section_part_count"] > 1:
                self.assertTrue(c["text"].rstrip().endswith("."), c["chunk_id"])  # default splits land on sentence ends
            else:
                self.assertEqual((c["char_start"], c["char_end"]), (a, b))         # small sections are NOT split

    def test_bounded_max_is_configurable(self):
        m = self.m
        docs = sorted(self.corpus["documents"], key=lambda d: d["source_number"])
        self.assertEqual(len(m.build_strategy("bounded_sections", docs, 1200)), len(self.chunks("section_based")))
        small = m.build_strategy("bounded_sections", docs, 150)
        self.assertGreater(len(small), len(self.chunks("bounded_sections")))
        self.assertTrue(all(c["char_count"] <= 150 or c["exceeds_max_chars"] for c in small))
        an = m.analyse(small, docs)
        self.assertEqual((an["lost_nonwhitespace_chars"], an["introduced_nonwhitespace_chars"], an["offset_overlaps"]), (0, 0, 0))

    def test_analysis_results(self):
        docs = sorted(self.corpus["documents"], key=lambda d: d["source_number"])
        for s in STRATS:
            a = self.m.analyse(self.chunks(s), docs, pdf_dir=ROOT, max_chars=self.m.DEFAULT_MAX_CHARS if s == "bounded_sections" else None)
            self.assertEqual((a["sources"], a["lost_nonwhitespace_chars"], a["introduced_nonwhitespace_chars"], a["text_slice_mismatches"],
                              a["offset_overlaps"], a["duplicated_chars_within_source"], a["exact_duplicate_chunks_within_source"],
                              a["adjacent_repeats_ge_min"], a["boundary_nonwhitespace_chars"]), (29, 0, 0, 0, 0, 0, 0, 0, 0), s)
            self.assertEqual(a["provenance_failures"], [], s)
            self.assertEqual(a["provenance_resolved"], a["chunks"])
            self.assertEqual(a["provenance_pdf_hash_checked"], a["chunks"])
        self.assertEqual(self.m.analyse(self.chunks("section_based"), docs)["chunks_crossing_section_boundaries"], 0)
        self.assertEqual(self.m.analyse(self.chunks("bounded_sections"), docs)["chunks_crossing_section_boundaries"], 0)

    def test_analysis_detects_problems(self):
        docs = sorted(self.corpus["documents"], key=lambda d: d["source_number"])
        cs = json.loads(json.dumps(self.chunks("section_based")))
        victim = next(c for c in cs if c["section_key"] == "what_it_covers")
        cs.remove(victim)                                                               # drop a chunk -> content lost
        a = self.m.analyse(cs, docs)
        self.assertGreater(a["lost_nonwhitespace_chars"], 0)
        cs2 = json.loads(json.dumps(self.chunks("section_based")))
        cs2[3]["text"] = cs2[3]["text"] + " invented"                                    # text not equal to its source slice
        self.assertGreater(self.m.analyse(cs2, docs)["text_slice_mismatches"], 0)
        cs3 = json.loads(json.dumps(self.chunks("section_based")))
        cs3[0]["sha256"] = "0" * 64
        self.assertTrue(self.m.analyse(cs3, docs)["provenance_failures"])

    def test_review_state_is_visible_on_chunks(self):
        for c in self.chunks("whole_document"):
            d = self.docs[c["source_id"]]
            self.assertEqual(c["source_status"], d["status"])
            self.assertEqual(c["source_url_status"], d["review"]["source_url_status"])
        flagged = {c["source_number"] for c in self.chunks("whole_document") if c["source_status"] != "verified"}
        self.assertEqual(flagged, {14, 18, 23})
        self.assertEqual({c["source_number"] for c in self.chunks("whole_document") if c["has_source_correction"]}, {5})

    def test_two_runs_are_byte_identical_and_match_committed_candidates(self):
        self.m.main(["--out-dir", str(self.tmp / "b")])
        for n in [f"{s}.json" for s in STRATS] + ["chunk_candidate_report.md"]:
            self.assertEqual((self.tmp / "a" / n).read_bytes(), (self.tmp / "b" / n).read_bytes(), n)
        committed = ROOT / "data" / "chunk_candidates"
        for s in STRATS:
            if (committed / f"{s}.json").is_file():
                self.assertEqual((committed / f"{s}.json").read_bytes(), (self.tmp / "a" / f"{s}.json").read_bytes(), f"{s}.json is stale")

    def test_report_contents(self):
        rep = (self.tmp / "a" / "chunk_candidate_report.md").read_text(encoding="utf-8")
        for h in ("| Strategy | Chunks | Avg chars | Min | Max | Avg words | Max words |", "Integrity checks", "Duplication", "Chunks per source",
                  "Section distribution", "Unusually small and large chunks", "Sensitivity of strategy C", "Provenance validation",
                  "no strategy has been chosen", "Test results"):
            self.assertIn(h, rep)

    def test_missing_source_or_bad_corpus_fails_clearly(self):
        t = Path(tempfile.mkdtemp())
        try:
            bad = json.loads(CORPUS.read_text(encoding="utf-8"))
            bad["documents"][0]["extraction_status"] = "failed"
            (t / "c.json").write_text(json.dumps(bad), encoding="utf-8")
            self.assertEqual(self.m.main(["--corpus", str(t / "c.json"), "--out-dir", str(t / "o")]), 2)
            self.assertFalse((t / "o" / "whole_document.json").exists())
            missing = self.m.run(CORPUS, t / "nopdfs", t / "o2", 250, 60, 600, None)[0]      # PDFs absent -> provenance failure reported
            self.assertEqual(missing, 1)
        finally:
            shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
