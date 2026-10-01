"""Phase-4 retrieval units (scripts/build_retrieval_units.py): 29 card-level units, full_text + embedding_text."""
import ast
import copy
import hashlib
import importlib.util
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "source_corpus.json"
MANIFEST = ROOT / "data" / "source_manifest.json"
UNITS = ROOT / "data" / "retrieval_units.json"


def _mod(name="build_retrieval_units"):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
    return m


def _imports(path):
    names = set()
    for n in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            names |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module)
            names |= {n.module + "." + a.name for a in n.names}
    return names


class NoNetworkNoLlmTests(unittest.TestCase):
    PHASE4 = ["m2c_common", "build_retrieval_units", "validate_token_lengths", "build_card_collection",
              "build_card_eval_questions", "evaluate_card_retrieval", "build_phase4_report"]
    NETWORK = {"socket", "requests", "ftplib", "ssl", "httpx", "aiohttp", "urllib3", "smtplib", "http", "urllib",
               "urllib.request", "urllib.error", "http.client", "huggingface_hub"}
    LLM = {"ollama", "openai", "anthropic", "llama_cpp", "google.generativeai", "cohere", "mistralai", "groq"}

    def test_phase4_scripts_import_no_network_or_llm_modules(self):
        for n in self.PHASE4:
            p = ROOT / "scripts" / f"{n}.py"
            if not p.is_file():
                continue
            im = _imports(p)
            self.assertFalse(im & self.NETWORK, (n, im & self.NETWORK))
            self.assertFalse({i.split(".")[0] for i in im} & {x.split(".")[0] for x in self.LLM}, (n, "LLM client imported"))

    def test_collection_builder_cannot_touch_the_legacy_store(self):
        m = _mod("build_card_collection")
        with self.assertRaises(SystemExit):
            m.guard_names("sap_docs", ROOT / "data" / "vector_store")
        with self.assertRaises(SystemExit):
            m.guard_names("sap_m2c_card_v1", ROOT / "chroma_db")
        m.guard_names("sap_m2c_card_v1", ROOT / "data" / "vector_store")
        self.assertEqual(m.COLLECTION_NAME, "sap_m2c_card_v1")


@unittest.skipUnless(CORPUS.is_file(), "needs data/source_corpus.json")
class RetrievalUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _mod()
        cls.corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        cls.docs = {d["source_id"]: d for d in cls.corpus["documents"]}
        cls.corpus_bytes = CORPUS.read_bytes()
        cls.manifest_bytes = MANIFEST.read_bytes()
        cls.pdf_hash = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("[0-9][0-9]_*.pdf")}
        real_c, real_g = socket.socket.connect, socket.getaddrinfo

        def boom(*a, **k):
            raise AssertionError("network access attempted")
        socket.socket.connect, socket.getaddrinfo = boom, boom
        try:
            cls.payload = cls.m.build_payload(cls.corpus, hashlib.sha256(cls.corpus_bytes).hexdigest())
            cls.payload2 = cls.m.build_payload(json.loads(cls.corpus_bytes), hashlib.sha256(cls.corpus_bytes).hexdigest())
        finally:
            socket.socket.connect, socket.getaddrinfo = real_c, real_g
        cls.units = cls.payload["units"]

    def test_exactly_29_units_one_per_source_unique_deterministic_ids(self):
        self.assertEqual((len(self.units), self.payload["unit_count"]), (29, 29))
        self.assertEqual([u["retrieval_unit_id"] for u in self.units], [f"M2C-{n:02d}" for n in range(1, 30)])
        self.assertEqual(len({u["retrieval_unit_id"] for u in self.units}), 29)
        self.assertEqual(sorted(u["source_id"] for u in self.units), sorted(self.docs))
        for u in self.units:
            self.assertEqual(u["retrieval_unit_id"], u["source_id"])
            self.assertEqual(u["source_id"], f"M2C-{u['source_number']:02d}")
        self.assertEqual([u["retrieval_unit_id"] for u in self.units], [u["retrieval_unit_id"] for u in self.payload2["units"]])

    def test_output_is_deterministic_and_committed_file_is_current(self):
        a = json.dumps(self.payload, ensure_ascii=False, indent=2)
        b = json.dumps(self.payload2, ensure_ascii=False, indent=2)
        self.assertEqual(a, b)
        if UNITS.is_file():
            self.assertEqual(UNITS.read_text(encoding="utf-8"), a + "\n", "data/retrieval_units.json is stale: run scripts/build_retrieval_units.py")
        with tempfile.TemporaryDirectory() as t:
            self.m.main(["--out", str(Path(t) / "u1.json")]); self.m.main(["--out", str(Path(t) / "u2.json")])
            self.assertEqual((Path(t) / "u1.json").read_bytes(), (Path(t) / "u2.json").read_bytes())

    def test_texts_non_empty(self):
        for u in self.units:
            self.assertTrue(u["embedding_text"].strip(), u["source_id"])
            self.assertTrue(u["full_text"].strip(), u["source_id"])
            self.assertLess(len(u["embedding_text"]), len(u["full_text"]))

    def test_full_text_is_unchanged_corpus_content(self):
        for u in self.units:
            d = self.docs[u["source_id"]]
            self.assertEqual(u["full_text"], d["content"])
            self.assertEqual(u["full_text_sha256"], hashlib.sha256(d["content"].encode("utf-8")).hexdigest())

    def test_embedding_text_is_derived_only_from_corpus_content(self):
        for u in self.units:
            d = self.docs[u["source_id"]]
            start = next(s for s in d["sections"] if s["key"] == "library_use")["char_start"] - len("Library use\n")
            self.assertEqual(u["embedding_text"], d["content"][:start].strip(), u["source_id"])      # an exact prefix of the source
            self.assertIn(u["embedding_text"], d["content"])
            self.assertEqual(u["embedding_text_sha256"], hashlib.sha256(u["embedding_text"].encode("utf-8")).hexdigest())

    def test_boilerplate_exclusion_is_exact_and_documented(self):
        self.assertEqual(self.payload["boilerplate_section_keys"], ["library_use", "copyright_note"])
        self.assertIn("library_use", self.payload["embedding_text_rule"])
        for u in self.units:
            d = self.docs[u["source_id"]]
            secs = {s["key"]: s for s in d["sections"]}
            excluded = [(e["key"], e["char_start"], e["char_end"]) for e in u["embedding_text_spec"]["excluded_sections"]]
            self.assertEqual([e[0] for e in excluded], ["library_use", "copyright_note"])
            for key, a, b in excluded:
                block = d["content"][a:b]
                self.assertTrue(block.startswith(secs[key]["heading"] + "\n") and block.endswith(secs[key]["text"]))
                self.assertNotIn(block, u["embedding_text"])
                self.assertNotIn(secs[key]["text"], u["embedding_text"])
                self.assertNotIn(secs[key]["heading"], u["embedding_text"])
            # every kept section is present verbatim, in order
            pos = 0
            for sid in u["embedding_text_spec"]["kept_section_ids"]:
                s = next(x for x in d["sections"] if x["section_id"] == sid)
                i = u["embedding_text"].find(s["text"], pos)
                self.assertGreaterEqual(i, 0, sid)
                pos = i + len(s["text"])
            # nothing else was removed: words(full) == words(embedding) + words(excluded blocks)
            words = u["embedding_text"].split() + [w for _, a, b in excluded for w in d["content"][a:b].split()]
            self.assertEqual(sorted(words), sorted(d["content"].split()), u["source_id"])
            for needle in (u["title"], "Category: " + u["category"], "What it covers", "Meter-to-Cash relevance",
                           "Authoritative SAP Help source", u["source_url"], secs["reference_line"]["text"]):
                self.assertIn(needle, u["embedding_text"], (u["source_id"], needle))

    def test_boilerplate_rule_refuses_non_identical_sections(self):
        bad = copy.deepcopy(self.corpus)
        next(s for s in bad["documents"][3]["sections"] if s["key"] == "copyright_note")["text"] += " extra"
        with self.assertRaises(ValueError):
            self.m.build_units(bad)
        bad2 = copy.deepcopy(self.corpus)
        bad2["documents"][0]["extraction_status"] = "failed"
        with self.assertRaises(ValueError):
            self.m.build_units(bad2)

    def test_metadata_and_provenance_resolve_to_one_pdf(self):
        for u in self.units:
            d = self.docs[u["source_id"]]
            for k, dk in (("filename", "filename"), ("title", "title"), ("category", "category"), ("sha256", "sha256"),
                          ("source_status", "status"), ("source_url", "authoritative_source"), ("citation", None)):
                self.assertEqual(u[k], d[dk] if dk else d["provenance"]["citation"], (u["source_id"], k))
            self.assertEqual(u["source_url_status"], d["review"]["source_url_status"])
            p = u["provenance"]
            self.assertEqual(p["corpus_document"], f"data/source_corpus.json#{u['source_id']}")
            self.assertEqual((p["page_start"], p["page_end"]), (1, 1))
            self.assertEqual((p["pdf_filename"], p["pdf_sha256"]), (u["filename"], u["sha256"]))
            pdf = ROOT / p["pdf_filename"]
            if pdf.is_file():
                self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), p["pdf_sha256"], "PDF changed")
        self.assertEqual(len({u["filename"] for u in self.units}), 29)
        self.assertEqual(len({u["sha256"] for u in self.units}), 29)

    def test_source_correction_and_review_metadata_survive(self):
        by = {u["source_number"]: u for u in self.units}
        self.assertEqual([n for n, u in by.items() if u["has_source_correction"]], [5])
        c = by[5]["source_correction"]
        self.assertEqual((c["type"], c["card_guide_id"][:8], c["resolved_guide_id"][:8], c["applied_to_content"]),
                         ("card_guide_correction", "021b182b", "2ac7fe29", False))
        self.assertEqual(c, self.docs["M2C-05"]["source_correction"])
        self.assertIn("021b182b0c47416c8fafed67ebfd78a9", by[5]["source_url"])             # source of record unchanged
        self.assertEqual(sorted(n for n, u in by.items() if u["source_status"] != "verified"), [14, 18, 23])
        for n in (14, 18, 23):
            self.assertEqual(by[n]["source_url_status"], "needs_review")
            self.assertTrue(by[n]["review_reasons"])
        self.assertTrue(all(u["source_correction"] is None for n, u in by.items() if n != 5))

    def test_inputs_unmodified(self):
        self.assertEqual(self.corpus_bytes, CORPUS.read_bytes())
        self.assertEqual(self.manifest_bytes, MANIFEST.read_bytes())
        self.assertEqual(self.pdf_hash, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("[0-9][0-9]_*.pdf")})


if __name__ == "__main__":
    unittest.main()
