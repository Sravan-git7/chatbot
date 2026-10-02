"""Tests for the ingestion / corpus pipeline (schema, clean, chunk, dedupe, fetch hardening, build_corpus).

Synthetic two-guide world for structure/edge cases, real topic #17 data for end-to-end.
    python -m pytest tests -q        (or)        python -m unittest discover -s tests -t .
"""
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from sap_resolver import events as ev                                                   # noqa: E402
from sap_resolver.chunk import ChunkConfig, chunk_document, embedding_record            # noqa: E402
from sap_resolver.clean import check_faithful, clean_text, content_hash                 # noqa: E402
from sap_resolver.fetch import (FetchedPage, GuideMismatchError, HttpApiError, PageParseError,   # noqa: E402
                                SapHelpApiFetcher)
from sap_resolver.pipeline import (EXIT_FETCH_OR_REGISTRATION, EXIT_INCOMPLETE, EXIT_OK, BuildConfig,  # noqa: E402
                                   ManifestError, build_corpus, validate_topic_manifest)
from sap_resolver.plan import ConfigError, IngestConfig, ScopeMode                      # noqa: E402
from sap_resolver.registry import GuideRegistry                                         # noqa: E402
from sap_resolver.schema import validate_chunk, validate_page                           # noqa: E402

try:
    import pypdf  # noqa: F401
    HAVE_PYPDF = True
except ImportError:
    HAVE_PYPDF = False
try:
    import bs4  # noqa: F401
    HAVE_BS4 = True
except ImportError:
    HAVE_BS4 = False

H = lambda n: f"{n:032x}"                      # synthetic 32-hex ids
GA, GB = H(0xA0), H(0xB0)                      # GA has a TOC, GB does not
PA, P1, P11, P2, PD, PMISSING = H(1), H(2), H(3), H(4), H(5), H(99)
G17 = "e52c8ee6197147ec97dfc2eb8c46a3ad"
P17 = "0bfcc5536a51204be10000000a174cb4"
PRODUCT = "SAP_S4HANA_ON-PREMISE"


def toc_response(loio, nodes):
    def conv(n):
        return {"t": n[0], "u": n[1], "c": [conv(c) for c in (n[2] if len(n) > 2 else [])]}
    return {"data": {"deliverable": {"loio": loio, "title": "Synthetic", "version": "1", "languageCode": "en-US",
                                     "landingPage": PA + ".html", "buildableMapLoio": H(0xFF),
                                     "fullToc": [conv(n) for n in nodes]}}}


# Alpha (PA) -> [Child1 (P1) -> [Grandchild (P11)], Child2 (P2), Child1-alias (P1-5)], Delta (PD)
SYN_TOC = toc_response(GA, [("Alpha", PA + ".html", [("Child 1", P1 + ".html", [("Grandchild", P11 + ".html")]),
                                                    ("Child 2", P2 + ".html"), ("Child 1", P1 + "-5.html")]),
                            ("Delta", PD + ".html")])
SAME = "Same Title\nSame Title\nUse\nIdentical body text for the duplicate-content test."
TEXTS = {PA + ".html": "Alpha\nAlpha\nPurpose\nAlpha overview.",
         P1 + ".html": "Child 1\nChild 1\nUse\nShared body of child one.",
         P1 + "-5.html": "Child 1\nChild 1\nUse\nShared body of child one.",
         P11 + ".html": SAME, P2 + ".html": SAME, PD + ".html": "Delta\nDelta\nPurpose\nDelta text."}


def topic(tid, guide, page, title=None):
    return {"topic_id": tid, "title": title or f"Topic {tid}", "category": "Cat", "pdf_file": f"{tid:02d}_T.pdf",
            "guide_id": guide, "page_id": page, "product": PRODUCT, "url_as_given": f"https://help.sap.com/docs/{PRODUCT}/{guide}/{page}.html",
            "canonical_url": f"https://help.sap.com/docs/{PRODUCT}/{guide}/{page}.html"}


def manifest(topics):
    guides = {}
    for t in topics:
        guides.setdefault(t["guide_id"], []).append(t["topic_id"])
    return {"topics": topics, "guides": [{"guide_id": g, "product": PRODUCT, "topic_ids": ids} for g, ids in guides.items()]}


class FakeFetcher:
    def __init__(self, texts=None, fail=None):
        self.texts, self.fail, self.calls = dict(TEXTS if texts is None else texts), fail or {}, []

    def fetch_page(self, e):
        self.calls.append((e.guide_id, e.file_path))
        if e.file_path in self.fail:
            raise self.fail[e.file_path]
        return FetchedPage(self.texts[e.file_path], None, "fake", "2026-01-01T00:00:00+00:00", "sap_help_api")


class World(unittest.TestCase):
    """Synthetic repo root with guide GA registered (TOC + ids) and guide GB unknown."""
    scope_default = ScopeMode.PAGE_ONLY

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="corpus_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "data").mkdir()
        (self.tmp / "data" / "toc_ga.json").write_text(json.dumps(SYN_TOC), encoding="utf-8")
        self.topics = [topic(1, GA, PA), topic(2, GA, P1), topic(3, GB, PD), topic(4, GA, PMISSING)]
        self.registry = {"guides": {GA: {"guide_id": GA, "numeric_deliverable_id": "111", "build_no": "7", "toc_file": "data/toc_ga.json",
                                         "fetch_identifiers_status": "manual_unverified", "topic_ids": [1, 2, 4], "evidence": []},
                                    GB: {"guide_id": GB, "numeric_deliverable_id": None, "build_no": None, "toc_file": None,
                                         "fetch_identifiers_status": "unresolved", "topic_ids": [3], "evidence": []}}}

    def build(self, out="out", topics=None, scope=None, fetcher=None, expected=None, **kw):
        ing = kw.pop("ingest", None) or IngestConfig(default_scope=scope or self.scope_default)
        cfg = BuildConfig(repo_root=self.tmp, out_dir=Path(out), manifest_dir=Path(out), mode=kw.pop("mode", "offline"),
                          ingest=ing, topic_manifest=manifest(topics or self.topics), registry=kw.pop("registry", self.registry),
                          fetcher=fetcher if fetcher is not None else FakeFetcher(), expected_topics=expected,
                          log=ev.EventLog(), **kw)
        return build_corpus(cfg), cfg

    def docs(self, out="out"):
        return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (self.tmp / out / "pages").rglob("*.json")}

    def chunks(self, out="out"):
        return [json.loads(l) for l in (self.tmp / out / "chunks" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------------------- manifests
class ManifestTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_PYPDF, "pypdf not installed")
    def test_all_29_topics_exist_with_valid_guides(self):
        from sap_resolver.pdf_cards import build_topic_manifest
        m = build_topic_manifest(ROOT)
        self.assertEqual(sorted(t["topic_id"] for t in m["topics"]), list(range(1, 30)))
        self.assertEqual(validate_topic_manifest(m, 29), [])
        self.assertEqual(m["guide_count"], 7)
        for t in m["topics"]:
            self.assertRegex(t["guide_id"], r"^[0-9a-f]{32}$")
            self.assertRegex(t["page_id"], r"^[0-9a-f]{32}$")

    def test_invalid_manifests_are_rejected(self):
        good = manifest([topic(1, GA, PA), topic(2, GA, P1)])
        self.assertEqual(validate_topic_manifest(good, 2), [])
        self.assertTrue(validate_topic_manifest(good, 29))                                     # wrong count
        self.assertTrue(validate_topic_manifest(manifest([topic(1, GA, PA), topic(1, GA, P1)]), 2))  # duplicate id
        self.assertTrue(validate_topic_manifest(manifest([topic(1, "not-a-guide", PA)]), 1))   # bad guide id
        bad = manifest([topic(1, GA, PA)])
        del bad["topics"][0]["title"]
        self.assertTrue(validate_topic_manifest(bad, 1))

    def test_build_refuses_invalid_manifest(self):
        w = World("setUp")
        w.setUp()
        self.addCleanup(shutil.rmtree, w.tmp, ignore_errors=True)
        with self.assertRaises(ManifestError):
            w.build(expected=29)            # only 4 synthetic topics


# ---------------------------------------------------------------------------------------- cleaning
class CleanTests(unittest.TestCase):
    def test_title_fragments_and_headings(self):
        raw = ("Contract Accounts\nContract Accounts\nPurpose\nIn\nContract Accounts Receivable\n, each partner is assigned.\n"
               "Features\nSee\nthe list (\nindustry\n) below.\n.")
        r = clean_text(raw, "Contract Accounts")
        lines = r.text.split("\n")
        self.assertEqual(lines[0], "Contract Accounts")                # one title only
        self.assertIn("Purpose", lines)                                # heading NOT glued to body
        self.assertIn("Features", lines)
        self.assertIn("In Contract Accounts Receivable, each partner is assigned.", lines)
        self.assertTrue(any(l.startswith("See the list (industry) below") for l in lines))
        self.assertEqual(r.stats["title_duplicates_removed"], 1)
        self.assertTrue(check_faithful(raw, r))

    def test_deterministic_and_idempotent(self):
        raw = "T\nT\nUse\nfoo\nbar baz.\nBaz"
        a, b = clean_text(raw, "T"), clean_text(raw, "T")
        self.assertEqual(a.text, b.text)
        self.assertEqual(clean_text(a.text, "T").text, a.text)

    def test_invisible_characters_and_whitespace(self):
        r = clean_text("A\u200bB\u00a0 C\t\tD\r\n\r\nE\ufeff", "")
        self.assertEqual(r.text, "AB C D\nE")

    def test_content_hash_ignores_case_and_whitespace_only(self):
        self.assertEqual(content_hash("Hello   World\n"), content_hash("hello world"))
        self.assertNotEqual(content_hash("hello world"), content_hash("hello worlds"))

    def test_empty_text(self):
        self.assertEqual(clean_text("", "T").text, "")
        self.assertEqual(clean_text(" \n\u200b\n ", "T").text, "")

    @unittest.skipUnless((ROOT / "sap_pages" / "001.json").is_file(), "legacy pages not present")
    def test_faithful_on_all_81_legacy_pages(self):
        bad = []
        for i in range(1, 82):
            p = json.loads((ROOT / "sap_pages" / f"{i:03d}.json").read_text(encoding="utf-8"))
            r = clean_text(p["text"], p["title"])
            if not check_faithful(p["text"], r):
                bad.append(i)
        self.assertEqual(bad, [])


# ---------------------------------------------------------------------------------------- chunking
def doc_for(text, **kw):
    d = {"guide_id": GA, "page_id": PA, "topic_id": 1, "topic_title": "Topic 1", "topic_ids": [1], "page_title": "Alpha",
         "toc_path": ["Alpha"], "source_url": "https://x/s", "canonical_url": "https://x/c", "content_hash": "ch", "text": text,
         "numeric_deliverable_id": "111", "build_no": "7", "source_type": "sap_help_api"}
    d.update(kw)
    return d


class ChunkTests(unittest.TestCase):
    TEXT = ("Alpha\nPurpose\n" + "First sentence is here. " * 20 + "\nFeatures\n" + "Feature sentence number two. " * 25 +
            "\nNote\nShort note.\nActivities\nLead in:\nitem one\nitem two")

    def test_deterministic_ids_and_format(self):
        a, b = chunk_document(doc_for(self.TEXT)), chunk_document(doc_for(self.TEXT))
        self.assertEqual(a, b)
        self.assertEqual([c["chunk_id"] for c in a], [f"{GA}/{PA}#{i:04d}" for i in range(len(a))])
        self.assertTrue(all(c["chunk_count"] == len(a) for c in a))

    def test_metadata_survives_on_every_chunk(self):
        for c in chunk_document(doc_for(self.TEXT)):
            self.assertEqual(validate_chunk(c), [])
            self.assertEqual((c["topic_id"], c["topic_title"], c["guide_id"], c["page_id"], c["page_title"], c["toc_path"],
                              c["source_url"], c["content_hash"]), (1, "Topic 1", GA, PA, "Alpha", ["Alpha"], "https://x/s", "ch"))

    def test_size_headings_and_no_content_loss(self):
        cfg = ChunkConfig(max_chars=400)
        chunks = chunk_document(doc_for(self.TEXT), cfg)
        self.assertGreater(len(chunks), 3)
        for c in chunks:
            self.assertLessEqual(len(c["text"]), cfg.max_chars, c["chunk_id"])
        # a heading is never the last line of a chunk
        labels = {"purpose", "use", "features", "note", "activities"}
        for c in chunks:
            self.assertNotIn(c["text"].split("\n")[-1].lower(), labels)
        # lead-in stays with its list
        self.assertTrue(any("Lead in:\nitem one" in c["text"] for c in chunks))
        # all body text is present (overlap 0 => concatenation minus repeated headings == source minus nothing)
        body_lines = [l for c in chunks for l in c["text"].split("\n")]
        for l in self.TEXT.split("\n"):
            if len(l) < 400:
                self.assertIn(l, body_lines)

    def test_continuation_repeats_section_heading(self):
        chunks = chunk_document(doc_for(self.TEXT), ChunkConfig(max_chars=400))
        cont = [c for c in chunks if c["heading_prefixed"]]
        self.assertTrue(cont)
        for c in cont:
            self.assertEqual(c["text"].split("\n")[0], c["section"])

    def test_oversize_block_is_split_on_sentences(self):
        long_block = " ".join(f"Sentence number {i} ends here." for i in range(80))
        chunks = chunk_document(doc_for("Alpha\nUse\n" + long_block), ChunkConfig(max_chars=500))
        self.assertGreater(len(chunks), 3)
        for c in chunks:
            self.assertLessEqual(len(c["text"]), 500)
        self.assertTrue(all(c["text"].rstrip().endswith((".", "Use", "Alpha")) for c in chunks))

    def test_overlap_is_explicit_and_configurable(self):
        text = "Alpha\nUse\n" + "\n".join(f"Paragraph {i} " + "word " * 30 for i in range(12))
        none = chunk_document(doc_for(text), ChunkConfig(max_chars=500, overlap_chars=0))
        some = chunk_document(doc_for(text), ChunkConfig(max_chars=500, overlap_chars=250))
        self.assertTrue(all(c["overlap_chars_prev"] == 0 for c in none))
        self.assertTrue(all(c["overlap_chars_prev"] == 0 for c in some[:1]))
        self.assertTrue(any(0 < c["overlap_chars_prev"] <= 250 for c in some[1:]))
        self.assertTrue(all(len(c["text"]) <= 500 for c in some))         # overlap + heading are inside the budget
        for prev, nxt in zip(some, some[1:]):
            if nxt["overlap_chars_prev"]:
                tail = prev["text"].split("\n")[-1]
                self.assertIn(tail, nxt["text"].split("\n"))
        with self.assertRaises(ValueError):
            chunk_document(doc_for(text), ChunkConfig(max_chars=500, overlap_chars=400))

    def test_embedding_record_has_scalar_metadata_only(self):
        c = chunk_document(doc_for(self.TEXT))[0]
        rec = embedding_record(c)
        self.assertEqual(rec["id"], c["chunk_id"])
        self.assertEqual(rec["document"], c["text"])                         # default: embed the chunk text unchanged
        self.assertTrue(all(isinstance(v, (str, int, float, bool)) for v in rec["metadata"].values()))
        self.assertEqual((rec["metadata"]["title"], rec["metadata"]["url"]), ("Alpha", "https://x/c"))
        self.assertIn("Alpha", embedding_record(c, "title")["document"])
        self.assertEqual(rec["metadata"]["topic_ids"], "1")

    def test_empty_document_has_no_chunks(self):
        self.assertEqual(chunk_document(doc_for("")), [])


# ---------------------------------------------------------------------------------------- fetch hardening
class _Resp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code, self._p, self.headers = status, payload, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            e = requests.HTTPError(f"{self.status_code}")
            e.response = self
            raise e

    def json(self):
        return self._p


class _Seq:
    """Session returning/raising a scripted sequence."""
    def __init__(self, *steps):
        self.steps, self.calls = list(steps), 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        s = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(s, Exception):
            raise s
        return s


def ok_payload(guide=GA, page=PA):
    return {"data": {"body": "<p>Hello</p>", "currentPage": {"loio": page}, "deliverable": {"loio": guide}}}


@unittest.skipUnless(HAVE_BS4, "beautifulsoup4 not installed")
class FetcherRobustnessTests(unittest.TestCase):
    def setUp(self):
        from sap_resolver.plan import PlanEntry
        self.entry = PlanEntry(GA, PA, PA + ".html", "Alpha", "u", ["Alpha"], None, 0, f"{GA}/{PA}.json", {1: "topic_page"})
        self.reg = GuideRegistry({"guides": {GA: {"numeric_deliverable_id": "111", "build_no": "7"}}}, ROOT)
        self.log, self.sleeps = ev.EventLog(), []

    def fetcher(self, session, **kw):
        return SapHelpApiFetcher(self.reg, self.log, allow_network=True, session=session, delay_s=0,
                                 sleep=self.sleeps.append, **kw)

    def test_transient_failures_are_retried_then_succeed(self):
        s = _Seq(_Resp(503), _Resp(429, headers={"Retry-After": "5"}), _Resp(200, ok_payload()))
        fp = self.fetcher(s).fetch_page(self.entry)
        self.assertEqual((fp.text, s.calls, fp.source_type), ("Hello", 3, "sap_help_api"))
        self.assertTrue(fp.retrieved_at)
        errs = self.log.of(ev.HTTP_ERROR)
        self.assertEqual([e["status"] for e in errs], [503, 429])
        self.assertTrue(all(e["will_retry"] for e in errs))
        self.assertIn(5.0, self.sleeps)                                  # Retry-After honoured (>= backoff)

    def test_connection_errors_retry_but_404_and_tls_do_not(self):
        import requests
        s = _Seq(requests.ConnectionError("reset"), _Resp(200, ok_payload()))
        self.assertEqual(self.fetcher(s).fetch_page(self.entry).text, "Hello")
        for exc_or_resp in (_Resp(404), _Resp(403), requests.exceptions.SSLError("tls closed")):
            s = _Seq(exc_or_resp)
            with self.assertRaises(HttpApiError):
                self.fetcher(s).fetch_page(self.entry)
            self.assertEqual(s.calls, 1, exc_or_resp)                     # never retried, never bypassed

    def test_retries_are_bounded(self):
        s = _Seq(_Resp(500))
        with self.assertRaises(HttpApiError):
            self.fetcher(s, max_retries=2).fetch_page(self.entry)
        self.assertEqual(s.calls, 3)

    def test_wrong_guide_or_page_in_response_is_rejected(self):
        with self.assertRaises(GuideMismatchError):
            self.fetcher(_Seq(_Resp(200, ok_payload(guide=GB)))).fetch_page(self.entry)
        with self.assertRaises(GuideMismatchError):
            self.fetcher(_Seq(_Resp(200, ok_payload(page=P1)))).fetch_page(self.entry)

    def test_parse_failure(self):
        with self.assertRaises(PageParseError):
            self.fetcher(_Seq(_Resp(200, {"data": {}}))).fetch_page(self.entry)


# ---------------------------------------------------------------------------------------- pipeline: scope
class ScopeTests(World):
    def pages(self, out="out"):
        return sorted(d["page_title"] for d in self.docs(out).values())

    def test_page_only(self):
        res, _ = self.build(topics=[self.topics[0]], scope=ScopeMode.PAGE_ONLY)
        self.assertEqual(self.pages(), ["Alpha"])
        self.assertEqual(res.manifest["topics"][0]["page_count"], 1)

    def test_page_and_descendants_folds_alias(self):
        ff = FakeFetcher()
        res, _ = self.build(topics=[self.topics[0]], scope=ScopeMode.PAGE_AND_DESCENDANTS, fetcher=ff)
        t = res.manifest["topics"][0]
        self.assertEqual((t["page_count"], t["unique_page_count"], t["duplicate_page_count"]), (5, 4, 1))   # alias P1-5 folded
        self.assertEqual(self.pages(), ["Alpha", "Child 1", "Child 2", "Grandchild"])
        self.assertNotIn((GA, P1 + "-5.html"), ff.calls)                  # alias never fetched separately

    def test_max_depth(self):
        res, _ = self.build(topics=[self.topics[0]], ingest=IngestConfig(default_scope=ScopeMode.PAGE_AND_DESCENDANTS, max_depth=1))
        self.assertEqual(self.pages(), ["Alpha", "Child 1", "Child 2"])
        self.assertEqual(res.manifest["topics"][0]["max_depth"], 1)

    def test_per_topic_override(self):
        ing = IngestConfig(default_scope=ScopeMode.PAGE_ONLY, topic_scopes={1: ScopeMode.PAGE_AND_DESCENDANTS})
        res, _ = self.build(topics=[self.topics[0], topic(5, GA, PD)], ingest=ing)
        rows = {r["topic_id"]: r for r in res.manifest["topics"]}
        self.assertEqual((rows[1]["scope"], rows[5]["scope"]), ("page_and_descendants", "page_only"))
        self.assertEqual((rows[1]["unique_page_count"], rows[5]["unique_page_count"]), (4, 1))


# ---------------------------------------------------------------------------------------- pipeline: dedupe / refs
class DedupeTests(World):
    def test_overlapping_topics_keep_all_relationships_on_one_document(self):
        # topic 1 (descendants) contains P1; topic 2 is P1 itself
        res, _ = self.build(topics=[self.topics[0], self.topics[1]], scope=ScopeMode.PAGE_AND_DESCENDANTS)
        d = self.docs()[P1]
        self.assertEqual(d["topic_ids"], [1, 2])
        self.assertEqual({(r["topic_id"], r["role"]) for r in d["topic_refs"]}, {(1, "descendant"), (2, "topic_page")})
        self.assertEqual(d["topic_id"], 2)                                # direct topic_page beats descendant
        self.assertEqual(len(self.docs()), 4)                             # still ONE document for P1
        self.assertTrue(any(c["topic_ids"] == [1, 2] for c in self.chunks() if c["page_id"] == P1))
        rows = {r["topic_id"]: r for r in res.manifest["topics"]}
        self.assertEqual(rows[2]["unique_page_count"], 2)                 # topic 2 = P1 + its descendant P11
        self.assertEqual(rows[1]["unique_page_count"], 4)                 # P1 counted for BOTH topics

    def test_content_duplicates_keep_one_canonical_and_all_topic_links(self):
        t2 = topic(2, GA, P2)
        t1 = topic(1, GA, P11)
        res, _ = self.build(topics=[t1, t2])               # page_only, two topics, two pages, IDENTICAL text
        docs = self.docs()
        canon, dup = docs[P11], docs[P2]
        self.assertEqual((canon["duplicate_of"], canon["status"]), (None, "OK"))
        self.assertEqual(dup["duplicate_of"], f"{GA}/{P11}")
        self.assertEqual(dup["status"], "DUPLICATE_CONTENT")
        self.assertEqual(canon["duplicate_docs"], [f"{GA}/{P2}"])
        self.assertEqual(canon["topic_ids"], [1, 2])                      # canonical inherits topic 2
        self.assertIn(f"{GA}/{P2}", [r["via_doc_id"] for r in canon["topic_refs"] if r["topic_id"] == 2])
        self.assertEqual(dup["topic_ids"], [2])                           # duplicate metadata is NOT deleted
        self.assertEqual({c["doc_id"] for c in self.chunks()}, {f"{GA}/{P11}"})   # only canonical is chunked
        rows = {r["topic_id"]: r for r in res.manifest["topics"]}
        self.assertEqual(rows[2]["duplicate_content_count"], 1)
        self.assertGreater(rows[2]["chunk_count"], 0)                     # topic 2 still has content (via canonical)
        self.assertEqual(res.manifest["totals"]["duplicate_content_pages"], 1)

    def test_no_false_content_duplicates(self):
        res, _ = self.build(topics=[self.topics[0]], scope=ScopeMode.PAGE_AND_DESCENDANTS)
        d = self.docs()
        self.assertIsNone(d[P1]["duplicate_of"])
        # P11 'Grandchild' and P2 'Child 2' have identical text in the fixture -> exactly one duplicate
        self.assertEqual(sum(1 for x in d.values() if x["duplicate_of"]), 1)


# ---------------------------------------------------------------------------------------- pipeline: behaviour
class BehaviourTests(World):
    def test_unresolved_guide_is_reported_not_zero_and_never_fetched(self):
        ff = FakeFetcher()
        res, _ = self.build(fetcher=ff)
        rows = {r["topic_id"]: r for r in res.manifest["topics"]}
        self.assertEqual(rows[3]["status"], "UNRESOLVED_GUIDE")
        self.assertIsNone(rows[3]["page_count"])                         # UNKNOWN, not 0
        self.assertFalse(rows[3]["pages_known"])
        self.assertIn("UNKNOWN", rows[3]["note"])
        self.assertEqual(rows[4]["status"], "UNRESOLVED_PAGE")
        self.assertNotIn(GB, [c[0] for c in ff.calls])                    # unknown guide cannot be ingested
        self.assertFalse(res.manifest["corpus_complete"])
        self.assertIn("INCOMPLETE", res.manifest["completeness"])
        self.assertIn(GB[:8], res.manifest["completeness"])
        self.assertEqual([g["guide_id"] for g in res.manifest["unresolved_guides"]], [GB])
        self.assertEqual(rows[1]["status"], "RESOLVED")                   # other guides still built

    def test_failed_page_is_recorded_and_others_continue(self):
        ff = FakeFetcher(fail={P2 + ".html": PageParseError("broken html")})
        res, _ = self.build(topics=[self.topics[0]], scope=ScopeMode.PAGE_AND_DESCENDANTS, fetcher=ff)
        row = res.manifest["topics"][0]
        self.assertEqual(row["status"], "FETCH_FAILED")
        self.assertEqual(row["failed_page_count"], 1)
        self.assertEqual(row["failed_pages"][0]["page_id"], P2)
        self.assertEqual(len(self.docs()), 3)                             # the other pages were built
        self.assertEqual(res.exit_code, EXIT_FETCH_OR_REGISTRATION)
        self.assertEqual(res.manifest["failed_pages"][0]["failure"], "PageParseError")

    def test_empty_content_status(self):
        ff = FakeFetcher(texts={**TEXTS, PD + ".html": " \n\u200b"})
        res, _ = self.build(topics=[topic(5, GA, PD)], fetcher=ff)
        self.assertEqual(res.manifest["topics"][0]["status"], "EMPTY_CONTENT")
        self.assertEqual(self.docs()[PD]["status"], "EMPTY_CONTENT")

    def test_network_off_fails_clearly_instead_of_silently_incomplete(self):
        cfg = BuildConfig(repo_root=self.tmp, out_dir=Path("out"), manifest_dir=Path("out"), mode="cache",
                          topic_manifest=manifest([self.topics[0]]), registry=self.registry, expected_topics=None, log=ev.EventLog())
        res = build_corpus(cfg)
        self.assertEqual(res.exit_code, EXIT_FETCH_OR_REGISTRATION)
        self.assertEqual(res.manifest["failed_pages"][0]["failure"], "NETWORK_DISABLED")
        self.assertEqual(res.manifest["topics"][0]["status"], "FETCH_FAILED")
        self.assertFalse(res.manifest["corpus_complete"])

    def test_circuit_breaker_stops_network_fetching(self):
        class Down:
            calls = 0

            def fetch_page(self, e):
                Down.calls += 1
                raise HttpApiError("503", 503)
        res, _ = self.build(topics=[self.topics[0]], scope=ScopeMode.PAGE_AND_DESCENDANTS, fetcher=Down(), mode="network",
                            max_consecutive_failures=2)
        self.assertEqual(Down.calls, 2)
        kinds = [f["failure"] for f in res.manifest["failed_pages"]]
        self.assertEqual(kinds.count("ABORTED"), 2)
        self.assertEqual(res.exit_code, EXIT_FETCH_OR_REGISTRATION)

    def test_raw_cache_is_reused_and_survives_rebuild(self):
        ff = FakeFetcher()
        self.build(topics=[self.topics[0]], fetcher=ff)
        ff2 = FakeFetcher()
        res, _ = self.build(topics=[self.topics[0]], fetcher=ff2)
        self.assertEqual(ff2.calls, [])                                   # served from out/raw
        self.assertEqual(res.exit_code, EXIT_OK)

    def test_corrupt_cache_entry_is_not_trusted(self):
        self.build(topics=[self.topics[0]])
        p = self.tmp / "out" / "raw" / GA / f"{PA}.json"
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["guide_id"] = GB                                              # would silently substitute another guide
        p.write_text(json.dumps(rec), encoding="utf-8")
        ff = FakeFetcher()
        self.build(topics=[self.topics[0]], fetcher=ff)
        self.assertEqual(len(ff.calls), 1)                                # ignored + refetched
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["guide_id"], GA)

    def test_metadata_preserved_end_to_end(self):
        res, _ = self.build(topics=[self.topics[0]], scope=ScopeMode.PAGE_AND_DESCENDANTS)
        for d in self.docs().values():
            self.assertEqual(validate_page(d), [], d["doc_id"])
            self.assertEqual((d["numeric_deliverable_id"], d["build_no"], d["guide_id"]), ("111", "7", GA))
            self.assertEqual(d["page_hash"], hashlib.sha256(d["text_raw"].encode()).hexdigest())
            self.assertTrue(d["canonical_url"].endswith(f"/{GA}/{d['page_id']}.html"))
        grand = self.docs()[P11]
        self.assertEqual((grand["toc_path"], grand["parent_page_id"]), (["Alpha", "Child 1", "Grandchild"], P1))
        src = {d["page_id"]: d for d in self.docs().values()}
        for c in self.chunks():
            self.assertEqual(validate_chunk(c), [])
            d = src[c["page_id"]]
            self.assertEqual((c["topic_id"], c["guide_id"], c["page_title"], c["toc_path"], c["source_url"], c["content_hash"]),
                             (d["topic_id"], GA, d["page_title"], d["toc_path"], d["source_url"], d["content_hash"]))
        for line in (self.tmp / "out" / "chunks" / "embedding_input.jsonl").read_text(encoding="utf-8").splitlines():
            md = json.loads(line)["metadata"]
            self.assertTrue(all(isinstance(v, (str, int, float, bool)) for v in md.values()))

    def test_build_is_deterministic(self):
        for out in ("a", "b"):
            self.build(out=out, topics=[self.topics[0], self.topics[1], self.topics[2]], scope=ScopeMode.PAGE_AND_DESCENDANTS)
        files = lambda o: {str(p.relative_to(self.tmp / o)): p.read_bytes() for p in (self.tmp / o).rglob("*")
                           if p.is_file() and not p.parts[-2] == "logs" and "raw" not in p.parts}
        fa, fb = files("a"), files("b")
        self.assertEqual(fa.keys(), fb.keys())
        for k in fa:
            if k == "final_corpus_manifest.json":
                self.assertEqual(json.loads(fa[k])["corpus_fingerprint"], json.loads(fb[k])["corpus_fingerprint"])
                continue
            if k == "final_corpus_manifest.md":          # only the corpus-dir name differs
                self.assertEqual(fa[k].replace(b"`a`", b"`X`"), fb[k].replace(b"`b`", b"`X`"), k)
                continue
            self.assertEqual(fa[k], fb[k], k)
        ids = [c["chunk_id"] for c in self.chunks("a")]
        self.assertEqual(ids, [c["chunk_id"] for c in self.chunks("b")])
        self.assertEqual(len(ids), len(set(ids)))

    def test_rebuild_removes_stale_derived_files(self):
        self.build(topics=[self.topics[0]], scope=ScopeMode.PAGE_AND_DESCENDANTS)
        self.assertEqual(len(self.docs()), 4)
        self.build(topics=[self.topics[0]], scope=ScopeMode.PAGE_ONLY)
        self.assertEqual(len(self.docs()), 1)                             # no stale pages from the bigger scope

    def test_statistics_present(self):
        res, _ = self.build(topics=[self.topics[0]], scope=ScopeMode.PAGE_AND_DESCENDANTS)
        st = json.loads((self.tmp / "out" / "corpus_stats.json").read_text(encoding="utf-8"))
        for k in ("total_chunks", "avg_chunk_chars", "median_chunk_chars", "min_chunk_chars", "max_chunk_chars",
                  "total_chars_cleaned", "unique_pages_planned", "duplicate_pages_identity", "duplicate_content_pages"):
            self.assertIn(k, st["totals"])
        self.assertEqual(st["pages_per_topic"]["1"], 4)
        self.assertGreater(st["chunks_per_topic"]["1"], 0)


# ---------------------------------------------------------------------------------------- completeness / exit codes
class CompletenessTests(World):
    def test_complete_corpus_and_require_complete(self):
        ok_topics = [self.topics[0], self.topics[1]]
        res, _ = self.build(topics=ok_topics, expected=2, require_complete=True)
        self.assertTrue(res.manifest["corpus_complete"])
        self.assertEqual(res.exit_code, EXIT_OK)
        self.assertEqual(res.manifest["topic_status_counts"], {"RESOLVED": 2})

    def test_incomplete_corpus_detected_and_require_complete_exits_nonzero(self):
        res, _ = self.build(expected=4)
        self.assertFalse(res.manifest["corpus_complete"])
        self.assertEqual(res.exit_code, EXIT_OK)                          # reported, build itself fine
        res, _ = self.build(expected=4, require_complete=True)
        self.assertEqual(res.exit_code, EXIT_INCOMPLETE)
        self.assertNotEqual(res.exit_code, 0)

    def test_final_manifest_files_written_with_all_required_columns(self):
        self.build()
        m = json.loads((self.tmp / "out" / "final_corpus_manifest.json").read_text(encoding="utf-8"))
        md = (self.tmp / "out" / "final_corpus_manifest.md").read_text(encoding="utf-8")
        for r in m["topics"]:
            for k in ("topic_id", "topic_title", "guide_id", "resolution_status", "page_count", "unique_page_count",
                      "chunk_count", "duplicate_page_count", "scope", "status"):
                self.assertIn(k, r)
        self.assertEqual(len(m["topics"]), 4)
        self.assertIn("INCOMPLETE", md)
        self.assertIn("UNRESOLVED_GUIDE", md)
        self.assertIn("UNKNOWN", md)


# ---------------------------------------------------------------------------------------- phase 12: registrations
class RegistrationWithoutCodeChangeTests(World):
    def write_regs(self, regs):
        (self.tmp / "data" / "guide_registrations.json").write_text(json.dumps({"registrations": regs}), encoding="utf-8")

    def build_regs(self, **kw):
        cfg = BuildConfig(repo_root=self.tmp, out_dir=Path("out"), manifest_dir=Path("out"), mode="offline",
                          topic_manifest=manifest(self.topics), registry=self.registry, expected_topics=None, log=ev.EventLog(),
                          fetcher=kw.pop("fetcher", FakeFetcher()), **kw)
        return build_corpus(cfg)

    def gb_toc(self):
        p = self.tmp / "data" / "toc_gb.json"
        p.write_text(json.dumps(toc_response(GB, [("Delta", PD + ".html", [("Kid", H(0x77) + ".html")])])), encoding="utf-8")
        return p

    def test_registering_a_guide_resolves_all_its_topics_with_no_code_change(self):
        before = self.build_regs()
        self.assertEqual({r["topic_id"]: r["status"] for r in before.manifest["topics"]}[3], "UNRESOLVED_GUIDE")
        self.gb_toc()
        self.write_regs([{"guide_id": GB, "numeric_id": "222", "build_no": "9", "toc_file": "data/toc_gb.json", "evidence": "unit test"}])
        ff = FakeFetcher(texts={**TEXTS, PD + ".html": "Delta\nDelta\nPurpose\nGuide B text."})
        after = self.build_regs(fetcher=ff)
        rows = {r["topic_id"]: r for r in after.manifest["topics"]}
        self.assertEqual(rows[3]["status"], "RESOLVED")
        self.assertEqual(rows[3]["chunk_count"], 1)
        self.assertEqual(after.manifest["unresolved_guides"], [])
        d = self.docs()[PD]
        self.assertEqual((d["guide_id"], d["numeric_deliverable_id"], d["build_no"]), (GB, "222", "9"))
        self.assertIn((GB, PD + ".html"), ff.calls)
        self.assertEqual(self.registry["guides"][GB]["numeric_deliverable_id"], None)   # injected registry not mutated

    def test_invalid_registrations_are_reported_and_never_applied(self):
        self.gb_toc()
        self.write_regs([
            {"guide_id": GB, "numeric_id": "222", "build_no": "9", "toc_file": "data/toc_ga.json"},        # TOC belongs to GA
            {"guide_id": H(0xCC), "numeric_id": "1", "build_no": "1", "toc_file": "data/toc_gb.json"},    # not a card guide
            {"guide_id": GB, "numeric_id": "12x", "build_no": "9", "toc_file": "data/toc_gb.json"},       # non-digit
            {"guide_id": GB, "numeric_id": "222", "toc_file": "data/toc_gb.json"},                        # build missing
            {"guide_id": GA, "numeric_id": "999", "build_no": "7", "toc_file": "data/toc_ga.json"},       # conflicts with known id
            {"guide_id": GB, "numeric_id": "222", "build_no": "9", "toc_file": "data/missing.json"}])     # file missing
        res = self.build_regs()
        self.assertEqual(len(res.manifest["registration_errors"]), 6)
        self.assertEqual(res.exit_code, EXIT_FETCH_OR_REGISTRATION)
        rows = {r["topic_id"]: r for r in res.manifest["topics"]}
        self.assertEqual(rows[3]["status"], "UNRESOLVED_GUIDE")           # nothing was guessed or half-applied
        d = self.docs()[PA]
        self.assertEqual(d["numeric_deliverable_id"], "111")              # GA's known id was not overwritten

    def test_toc_only_registration_resolves_but_cannot_fetch_without_ids(self):
        self.gb_toc()
        self.write_regs([{"guide_id": GB, "toc_file": "data/toc_gb.json"}])
        cfg = BuildConfig(repo_root=self.tmp, out_dir=Path("out"), manifest_dir=Path("out"), mode="network",
                          topic_manifest=manifest([self.topics[2]]), registry=self.registry, expected_topics=None,
                          log=ev.EventLog(), fetcher=None)
        # network mode builds a real SapHelpApiFetcher: no numeric id -> refuses to guess, nothing requested
        res = build_corpus(cfg)
        self.assertEqual(res.manifest["failed_pages"][0]["failure"], "GUIDE_IDS_UNKNOWN")
        self.assertEqual(res.manifest["topics"][0]["resolution_status"], "RESOLVED")
        self.assertEqual(res.manifest["topics"][0]["status"], "FETCH_FAILED")


# ---------------------------------------------------------------------------------------- guide intake / TOC acquisition
class TocFetcher(FakeFetcher):
    """FakeFetcher that can also serve/deny TOC requests (the one-request-per-guide acquisition step)."""
    def __init__(self, tocs=None, errors=None, **kw):
        super().__init__(**kw)
        self.tocs, self.errors, self.toc_calls = tocs or {}, errors or {}, []

    def fetch_toc_response(self, guide_id, any_page_file):
        self.toc_calls.append((guide_id, any_page_file))
        err = self.errors.get(any_page_file) or self.errors.get(guide_id)
        if err:
            raise err
        return self.tocs[guide_id]


class GuideIntakeTests(World):
    GB_TOC = toc_response(GB, [("Delta", PD + ".html", [("Kid", H(0x77) + ".html")])])

    def setUp(self):
        super().setUp()
        self.topics = [topic(1, GA, PA), topic(3, GB, PD)]
        self.regs_path = self.tmp / "data" / "guide_registrations.json"

    def write_regs(self, regs):
        self.regs_path.write_text(json.dumps({"registrations": regs}), encoding="utf-8")

    def run_build(self, fetcher, mode="network", **kw):
        cfg = BuildConfig(repo_root=self.tmp, out_dir=Path("out"), manifest_dir=Path("out"), mode=mode, expected_topics=None,
                          topic_manifest=manifest(self.topics), registry=self.registry, log=ev.EventLog(), fetcher=fetcher, **kw)
        return build_corpus(cfg)

    def test_pagecontent_url_parsing_is_strict(self):
        from sap_resolver.registry import RegistrationError, parse_pagecontent_url
        ok = parse_pagecontent_url("https://help.sap.com/http.svc/pagecontent?deliverableInfo=1&deliverable_id=40374631&buildNo=1779&file_path=x.html")
        self.assertEqual(ok, {"numeric_id": "40374631", "build_no": "1779"})
        for bad in ("https://help.sap.com/http.svc/pagecontent?deliverable_id=%s&buildNo=1" % GB,     # 32-hex is NOT a numeric id
                    "https://help.sap.com/http.svc/pagecontent?deliverable_id=12",                      # build missing
                    "https://help.sap.com/docs/X/%s/%s.html" % (GB, PD)):                               # a card URL carries no ids
            with self.assertRaises(RegistrationError):
                parse_pagecontent_url(bad)

    def test_empty_skeleton_is_pending_not_an_error_and_guide_stays_unresolved(self):
        self.write_regs([{"guide_id": GB, "_topics": [3], "numeric_id": None, "build_no": None, "pagecontent_url": None, "toc_file": None}])
        res = self.run_build(TocFetcher(), mode="offline")
        self.assertEqual(res.manifest["registration_errors"], [])
        self.assertEqual(res.manifest["pending_registrations"][0]["state"], "EMPTY_SKELETON")
        self.assertEqual(res.manifest["unresolved_guides"][0]["missing"][-1], "numeric_id + build_no")
        self.assertEqual(res.exit_code, EXIT_OK)
        self.assertEqual({r["topic_id"]: r["status"] for r in res.manifest["topics"]}[3], "UNRESOLVED_GUIDE")

    def test_ids_only_registration_downloads_verified_toc_in_network_mode(self):
        self.write_regs([{"guide_id": GB, "pagecontent_url": "https://help.sap.com/http.svc/pagecontent?deliverable_id=222&buildNo=9&file_path=a.html"}])
        ff = TocFetcher(tocs={GB: self.GB_TOC}, texts={**TEXTS, PD + ".html": "Delta\nDelta\nPurpose\nGuide B."})
        res = self.run_build(ff)
        self.assertEqual(ff.toc_calls, [(GB, PD + ".html")])                     # one request, for the card's own page
        self.assertTrue((self.tmp / "data" / "toc" / f"{GB}.json").is_file())
        row = {r["topic_id"]: r for r in res.manifest["topics"]}[3]
        self.assertEqual((row["status"], row["chunk_count"]), ("RESOLVED", 1))
        self.assertEqual(self.docs()[PD]["numeric_deliverable_id"], "222")
        self.assertEqual(res.exit_code, EXIT_OK)
        ff2 = TocFetcher(tocs={GB: self.GB_TOC})
        self.run_build(ff2)                                                      # second run: saved TOC reused, no new request
        self.assertEqual(ff2.toc_calls, [])

    def test_wrong_ids_are_rejected_nothing_saved_nothing_substituted(self):
        self.write_regs([{"guide_id": GB, "numeric_id": "222", "build_no": "9"}])
        ff = TocFetcher(errors={GB: GuideMismatchError("API answered for another guide")})
        res = self.run_build(ff)
        self.assertFalse((self.tmp / "data" / "toc" / f"{GB}.json").exists())
        self.assertEqual(res.exit_code, EXIT_FETCH_OR_REGISTRATION)
        self.assertIn("TOC could not be acquired", res.manifest["registration_errors"][0]["error"])
        self.assertEqual({r["topic_id"]: r["status"] for r in res.manifest["topics"]}[3], "UNRESOLVED_GUIDE")
        self.assertNotIn(GB, [c[0] for c in ff.calls])                           # no page was fetched with unverified ids

    def test_toc_request_prefers_the_captured_page(self):
        self.topics = [topic(1, GA, PA), topic(3, GB, PD), topic(6, GB, PMISSING)]
        self.write_regs([{"guide_id": GB, "numeric_id": "222", "build_no": "9", "captured_page_ids": [PMISSING]}])
        ff = TocFetcher(tocs={GB: self.GB_TOC})
        self.run_build(ff)
        self.assertEqual(ff.toc_calls[0], (GB, PMISSING + ".html"))

    def test_toc_request_tries_next_card_page_on_404_only(self):
        self.topics = [topic(1, GA, PA), topic(3, GB, PD), topic(6, GB, PMISSING)]
        self.write_regs([{"guide_id": GB, "numeric_id": "222", "build_no": "9"}])
        ff = TocFetcher(tocs={GB: self.GB_TOC}, errors={PD + ".html": HttpApiError("404", 404)})
        self.run_build(ff)
        self.assertEqual([c[1] for c in ff.toc_calls], [PD + ".html", PMISSING + ".html"])
        ff = TocFetcher(tocs={GB: self.GB_TOC}, errors={PD + ".html": HttpApiError("503", 503)})
        shutil.rmtree(self.tmp / "data" / "toc")
        res = self.run_build(ff)
        self.assertEqual(len(ff.toc_calls), 1)                                   # 5xx: stop, do not hammer other pages
        self.assertTrue(res.manifest["registration_errors"])

    def test_no_download_unless_network_is_enabled(self):
        self.write_regs([{"guide_id": GB, "numeric_id": "222", "build_no": "9"}])
        ff = TocFetcher(tocs={GB: self.GB_TOC})
        res = self.run_build(ff, mode="cache")
        self.assertEqual(ff.toc_calls, [])
        self.assertEqual(res.manifest["pending_registrations"][0]["state"], "TOC_NOT_AVAILABLE")
        self.assertFalse((self.tmp / "data" / "toc").exists())

    def test_existing_toc_is_never_overwritten(self):
        (self.tmp / "data" / "toc").mkdir()
        (self.tmp / "data" / "toc" / f"{GB}.json").write_text(json.dumps(self.GB_TOC), encoding="utf-8")
        self.write_regs([{"guide_id": GB, "numeric_id": "222", "build_no": "9"}])
        ff = TocFetcher(tocs={GB: toc_response(GB, [("Other", H(0x88) + ".html")])})
        self.run_build(ff)
        self.assertEqual(ff.toc_calls, [])
        self.assertIn("Delta", (self.tmp / "data" / "toc" / f"{GB}.json").read_text(encoding="utf-8"))


class CapturedUrlTests(World):
    """Captured browser URLs -> guide identity. Never forced; response loio is authoritative."""
    def url(self, num, build, page):
        return f"https://help.sap.com/http.svc/pagecontent?deliverableInfo=1&amp;deliverable_id={num}&amp;buildNo={build}&amp;file_path={page}.html"

    class Raw:
        def __init__(self, answers):
            self.answers, self.calls = answers, []

        def fetch_raw(self, num, build, file_path):
            self.calls.append((num, build, file_path))
            a = self.answers[file_path]
            if isinstance(a, Exception):
                raise a
            return toc_response(a, [("Root", file_path)])

    def setUp(self):
        super().setUp()
        self.topics = [topic(1, GA, PA), topic(2, GB, PD), topic(3, H(0xC0), P1)]
        self.m = manifest(self.topics)

    def test_html_escaped_urls_are_parsed(self):
        from sap_resolver.registry import parse_pagecontent_request
        r = parse_pagecontent_request(self.url("40374657", "1779", PA))
        self.assertEqual(r, {"numeric_id": "40374657", "build_no": "1779", "file_path": PA + ".html"})

    def test_offline_maps_by_card_page_id_and_shared_numeric_id_is_allowed(self):
        from sap_resolver.intake import capture_mapping
        rows = capture_mapping([self.url("111", "1", PA), self.url("222", "1", PD), self.url("111", "1", P1)], self.m, self.tmp)
        self.assertEqual([r["decision"] for r in rows], ["MAPPED", "MAPPED", "MAPPED"])
        self.assertEqual((rows[0]["guide_id"], rows[2]["guide_id"], rows[1]["evidence"]), (GA, H(0xC0), "card_page_id"))
        self.assertIn("also used by guide", rows[0]["reason"])          # recorded, not hidden

    def test_unmatched_and_malformed_urls_are_not_mapped(self):
        from sap_resolver.intake import capture_mapping
        rows = capture_mapping([self.url("5", "1", H(0x123)), "https://help.sap.com/http.svc/pagecontent?deliverable_id=5&buildNo=1",
                                f"https://help.sap.com/http.svc/pagecontent?deliverable_id={GA}&buildNo=1&file_path={PA}.html"], self.m, self.tmp)
        self.assertEqual([r["decision"] for r in rows], ["UNMATCHED", "REJECTED", "REJECTED"])

    def test_response_loio_confirms_and_two_urls_can_share_one_guide(self):
        from sap_resolver.intake import capture_mapping
        m = manifest([topic(1, GA, PA), topic(2, GA, P1), topic(3, GB, PD)])            # two cards in guide GA
        raw = self.Raw({PA + ".html": GA, P1 + ".html": GA, PD + ".html": H(0xEE)})
        rows = capture_mapping([self.url("111", "7", PA), self.url("111", "7", P1), self.url("222", "7", PD)], m, self.tmp, raw)
        self.assertEqual([r["decision"] for r in rows], ["MAPPED", "MAPPED", "NOT_A_CARD_GUIDE"])
        self.assertTrue(all(r["evidence"] == "response_loio" for r in rows[:2]))
        self.assertEqual((rows[0]["guide_id"], rows[1]["guide_id"]), (GA, GA))
        self.assertIn("shares guide", rows[0]["reason"])
        self.assertIsNone(rows[2]["guide_id"])                 # card says GB but the response says a non-card guide: nothing registered

    def test_response_disagreeing_with_card_is_not_registered_and_conflicting_builds_are_held(self):
        from sap_resolver.intake import capture_mapping
        raw = self.Raw({PA + ".html": GB, PD + ".html": GB})     # card for PA names GA, the response says GB
        rows = capture_mapping([self.url("111", "7", PA)], self.m, self.tmp, raw)
        self.assertEqual((rows[0]["decision"], rows[0]["guide_id"]), ("CARD_MISMATCH", None))
        rows = capture_mapping([self.url("222", "7", PD), self.url("222", "8", PD)], self.m, self.tmp, self.Raw({PD + ".html": GB}))
        self.assertEqual([r["decision"] for r in rows], ["AMBIGUOUS", "AMBIGUOUS"])     # same guide, two build numbers

    def test_response_for_another_page_is_rejected(self):
        from sap_resolver.intake import capture_mapping

        class WrongPage(self.Raw):
            def fetch_raw(self, num, build, fp):
                r = super().fetch_raw(num, build, fp)
                r["data"]["currentPage"] = {"loio": P11}
                return r
        rows = capture_mapping([self.url("111", "7", PA)], self.m, self.tmp, WrongPage({PA + ".html": GA}))
        self.assertEqual(rows[0]["decision"], "PAGE_MISMATCH")

    def test_saved_responses_give_the_same_verdicts_without_network(self):
        from sap_resolver.intake import SavedResponses, capture_mapping
        d = self.tmp / "saved"
        d.mkdir()
        (d / f"1_111_{PA}.json").write_text(json.dumps(toc_response(GA, [("Root", PA + ".html")])), encoding="utf-8")
        (d / f"2_222_{PD}.json").write_text("{not json", encoding="utf-8")
        rows = capture_mapping([self.url("111", "7", PA), self.url("222", "7", PD), self.url("333", "7", P1)], self.m, self.tmp, SavedResponses(d))
        self.assertEqual([r["decision"] for r in rows], ["MAPPED", "FETCH_FAILED", "FETCH_FAILED"])
        self.assertEqual((rows[0]["evidence"], rows[0]["response_source"], rows[0]["page_in_toc"]), ("response_loio", "saved_response", True))
        self.assertIn("agree", rows[0]["reason"])

    def test_capture_responses_reuses_saved_responses_without_any_request(self):
        spec = importlib.util.spec_from_file_location("capture_responses_cli2", ROOT / "scripts" / "capture_responses.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out = self.tmp / "cap2"
        out.mkdir()
        (out / f"1_555_{PA}.json").write_text(json.dumps(toc_response(GA, [("Root", PA + ".html")])), encoding="utf-8")
        (out / "summary.json").write_text("[]", encoding="utf-8")
        f = self.tmp / "urls2.txt"
        f.write_bytes(b"\xef\xbb\xbf" + f"http://127.0.0.1:9/http.svc/pagecontent?deliverable_id=555&buildNo=1&file_path={PA}.html\n".encode())   # port 9: any request would fail
        self.assertEqual(mod.main(["--urls-file", str(f), "--out-dir", str(out), "--delay", "0"]), 0)
        s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual((s[0]["http"], s[0]["loio"]), ("saved", GA))
        self.assertTrue((out / "summary.previous.json").is_file())                       # earlier summary never lost
        self.assertTrue((out / f"1_555_{PA}.json").is_file())

    def test_capture_responses_script_saves_responses_and_flags_shared_ids(self):
        import http.server
        import threading
        bodies = {PA: toc_response(GA, [("Root", PA + ".html")]), P1: toc_response(GB, [("Root", P1 + ".html")])}

        class H_(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                b = json.dumps(bodies[q["file_path"][0][:32]]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H_)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_port}/http.svc/pagecontent?deliverableInfo=1&amp;deliverable_id=555&amp;buildNo=1&amp;file_path="
        f = self.tmp / "urls.txt"
        f.write_text("# c\n" + base + PA + ".html\n" + base + P1 + ".html\nnot a url\n", encoding="utf-8")
        spec = importlib.util.spec_from_file_location("capture_responses_cli", ROOT / "scripts" / "capture_responses.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.main(["--urls-file", str(f), "--out-dir", str(self.tmp / "cap"), "--delay", "0"])
        self.assertEqual(rc, 1)                                                  # the malformed line is reported
        summ = json.loads((self.tmp / "cap" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual([r.get("loio") for r in summ[:2]], [GA, GB])
        self.assertTrue((self.tmp / "cap" / f"1_555_{PA}.json").is_file())
        self.assertIn("error", summ[2])


    def test_fetch_failure_is_recorded_not_mapped(self):
        from sap_resolver.intake import capture_mapping
        raw = self.Raw({PA + ".html": HttpApiError("SSLError", None)})
        rows = capture_mapping([self.url("111", "7", PA)], self.m, self.tmp, raw)
        self.assertEqual((rows[0]["decision"], rows[0]["guide_id"]), ("FETCH_FAILED", None))

    def test_existing_registration_is_never_overwritten(self):
        from sap_resolver.intake import capture_mapping
        existing = [{"guide_id": GB, "numeric_id": "999", "build_no": "1"}]
        rows = capture_mapping([self.url("222", "1", PD)], self.m, self.tmp, None, existing)
        self.assertEqual(rows[0]["decision"], "CONFLICTS_WITH_EXISTING")

    def test_registrations_sharing_a_numeric_id_across_guides_are_both_kept_and_reported(self):
        from sap_resolver.registry import apply_registrations_ex, shared_numeric_ids
        reg = json.loads(json.dumps(self.registry))
        regs = [{"guide_id": GA, "numeric_id": "111", "build_no": "7"}, {"guide_id": GB, "numeric_id": "111", "build_no": "7"}]
        reg2, errs, pend = apply_registrations_ex(reg, self.m, regs, self.tmp)
        self.assertEqual(errs, [])
        self.assertEqual(shared_numeric_ids(reg2), {"111": sorted([GA, GB])})
        self.assertEqual(reg2["guides"][GB]["numeric_deliverable_id"], "111")
        # ...but the same guide can still never be re-pointed at different ids
        _, errs2, _ = apply_registrations_ex(json.loads(json.dumps(self.registry)), self.m,
                                             [{"guide_id": GA, "numeric_id": "999", "build_no": "7"}], self.tmp)
        self.assertEqual(len(errs2), 1)

    def test_mojibake_bom_is_stripped_before_parsing(self):
        from sap_resolver.intake import clean_url_line, read_url_lines
        from sap_resolver.registry import parse_pagecontent_request
        u = self.url("40374657", "1779", PA).replace("&amp;", "&")
        for prefix in ("\ufeff", "\u00ef\u00bb\u00bf", "\ufeff\ufeff", "\u00ef\u00bb\u00bf\ufeff", "\u200b\u00ef\u00bb\u00bf ", "\u00c3\u00af\u00c2\u00bb\u00c2\u00bf"):
            self.assertEqual(clean_url_line(prefix + u), u, repr(prefix))
            self.assertEqual(parse_pagecontent_request(prefix + u)["numeric_id"], "40374657", repr(prefix))   # even if an uncleaned URL arrives
        f = self.tmp / "m.txt"
        f.write_bytes(("\u00ef\u00bb\u00bf" + u + "\n" + u.replace("40374657", "40374682") + "\n").encode("utf-8"))      # mojibake as text
        self.assertEqual(len(read_url_lines(f)), 2)
        self.assertTrue(read_url_lines(f)[0].startswith("https://"))
        f.write_bytes(b"\xef\xbb\xbf" + "\u00ef\u00bb\u00bf".encode("utf-8") + u.encode())                                # real BOM + mojibake BOM
        self.assertEqual(read_url_lines(f), [u])

    def test_url_file_reader_strips_bom_utf16_zero_width_and_wrappers(self):
        from sap_resolver.intake import read_url_lines
        u = self.url("111", "7", PA).replace("&amp;", "&")
        f = self.tmp / "u.txt"
        for data in (b"\xef\xbb\xbf" + u.encode() + b"\r\n", ("\ufeff" + u + "\r\n").encode("utf-16"), ("# c\n\u200b " + u + "\n").encode(),
                     f"[{u}]({u.replace('&', '&amp;')})\n".encode(), ("\ufeff\u00a0<" + u + ">\n").encode()):
            f.write_bytes(data)
            self.assertEqual(read_url_lines(f), [u], data[:12])


class IntakeCliTests(unittest.TestCase):
    """scripts/guide_intake.py against a scratch repo root (real 29-topic manifest, nothing in the real repo touched)."""
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("guide_intake_cli", ROOT / "scripts" / "guide_intake.py")
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="intake_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "data").mkdir()
        shutil.copy(ROOT / "data" / "topic_manifest.json", self.tmp / "data" / "topic_manifest.json")
        self.cli.ROOT, self.cli.REG_FILE = self.tmp, self.tmp / "data" / "guide_registrations.json"
        self.real = ROOT / "data" / "guide_registrations.json"
        self.before = self.real.read_bytes()
        self.addCleanup(lambda: self.assertEqual(self.real.read_bytes(), self.before))
        self.G = "9442486404b54071b4ebeab6a16628e7"

    def regs(self):
        return json.loads(self.cli.REG_FILE.read_text(encoding="utf-8"))["registrations"]

    def test_template_add_and_check(self):
        self.assertEqual(self.cli.main(["template"]), 0)
        self.assertEqual(len(self.regs()), 7)
        self.assertEqual(self.cli.main(["template"]), 0)
        self.assertEqual(len(self.regs()), 7)                                    # idempotent
        self.assertEqual(self.cli.main(["add", "--guide-id", self.G, "--pagecontent-url",
                                        "https://help.sap.com/http.svc/pagecontent?deliverableInfo=1&deliverable_id=555&buildNo=66&file_path=x.html"]), 0)
        entry = [r for r in self.regs() if r["guide_id"] == self.G]
        self.assertEqual(len(entry), 1)
        self.assertEqual((entry[0]["numeric_id"], entry[0]["build_no"]), ("555", "66"))
        self.assertEqual(self.cli.main(["check"]), 0)
        self.assertEqual(self.cli.main(["add", "--guide-id", self.G, "--numeric-id", "999", "--build-no", "66"]), 3)   # conflict refused
        self.assertEqual([r["numeric_id"] for r in self.regs() if r["guide_id"] == self.G], ["555"])

    def test_capture_offline_registers_all_card_matched_guides_incl_shared_numeric_id(self):
        real = json.loads((ROOT / "data" / "topic_manifest.json").read_text(encoding="utf-8"))
        by = {t["topic_id"]: t for t in real["topics"]}
        u = lambda n, p: f"https://help.sap.com/http.svc/pagecontent?deliverableInfo=1&amp;deliverable_id={n}&amp;buildNo=1&amp;file_path={by[p]['page_id']}.html"
        (self.tmp / "data" / "captured_pagecontent_urls.txt").write_bytes(
            b"\xef\xbb\xbf" + "\n".join(["# c", u(10, 5), u(11, 2), u(10, 7)]).encode() + b"\n")          # BOM on purpose
        self.assertEqual(self.cli.main(["template"]), 0)
        self.assertEqual(self.cli.main(["capture", "--dry-run"]), 0)
        self.assertFalse(any(r.get("numeric_id") for r in self.regs()))                 # dry-run wrote no ids
        self.assertEqual(self.cli.main(["capture"]), 0)
        regs = {r["guide_id"]: r for r in self.regs()}
        for t, n in ((2, "11"), (5, "10"), (7, "10")):
            r = regs[by[t]["guide_id"]]
            self.assertEqual((r["numeric_id"], r["build_no"]), (n, "1"))
            self.assertIn("unverified", r["verification"])
            self.assertIn(f"&deliverable_id={n}&", r["pagecontent_url"])                # source URL kept, un-escaped
            self.assertEqual(r["captured_page_ids"], [by[t]["page_id"]])
        rep = json.loads((self.tmp / "data" / "captured_url_mapping.json").read_text(encoding="utf-8"))
        self.assertEqual([r["decision"] for r in rep["rows"]], ["MAPPED"] * 3)
        self.assertEqual(self.cli.main(["check"]), 0)

    def test_add_merges_into_existing_registration_and_keeps_provenance(self):
        real = json.loads((ROOT / "data" / "topic_manifest.json").read_text(encoding="utf-8"))
        by = {t["topic_id"]: t for t in real["topics"]}
        (self.tmp / "data" / "captured_pagecontent_urls.txt").write_text(
            f"https://help.sap.com/http.svc/pagecontent?deliverableInfo=1&deliverable_id=11&buildNo=1&file_path={by[2]['page_id']}.html\n", encoding="utf-8")
        self.assertEqual(self.cli.main(["capture"]), 0)
        g = by[2]["guide_id"]
        self.assertEqual(self.cli.main(["add", "--guide-id", g, "--numeric-id", "11", "--build-no", "1", "--evidence", "user reported loio",
                                        "--verification", "user_reported_response_loio"]), 0)
        r = [x for x in self.regs() if x["guide_id"] == g]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["verification"], "user_reported_response_loio")
        self.assertIn("user reported loio", r[0]["evidence"])
        self.assertIn("captured URL #1", r[0]["evidence"])                              # earlier provenance kept
        self.assertEqual(r[0]["captured_page_ids"], [by[2]["page_id"]])

    def test_add_refuses_unknown_guides_and_bad_ids(self):
        self.assertEqual(self.cli.main(["add", "--guide-id", H(0xEE), "--numeric-id", "1", "--build-no", "2"]), 3)
        self.assertEqual(self.cli.main(["add", "--guide-id", self.G, "--numeric-id", self.G, "--build-no", "2"]), 3)   # loio in numeric slot
        self.assertEqual(self.cli.main(["add", "--guide-id", self.G, "--numeric-id", "1"]), 3)                          # build missing
        self.assertFalse(self.cli.REG_FILE.exists() and self.regs())

    def test_add_toc_file_infers_guide_and_saves_toc(self):
        toc = toc_response(self.G, [("Root", H(1) + ".html")])
        f = self.tmp / "saved.json"
        f.write_text(json.dumps(toc), encoding="utf-8")
        self.assertEqual(self.cli.main(["add", "--toc-file", str(f), "--numeric-id", "5", "--build-no", "6"]), 0)
        self.assertTrue((self.tmp / "data" / "toc" / f"{self.G}.json").is_file())
        bad = toc_response(H(0xEE), [("Root", H(1) + ".html")])
        f.write_text(json.dumps(bad), encoding="utf-8")
        self.assertEqual(self.cli.main(["add", "--toc-file", str(f)]), 3)
        self.assertEqual(self.cli.main(["status"]), 0)


# ---------------------------------------------------------------------------------------- isolation + real topic #17
class IsolationTests(World):
    def test_refuses_legacy_chroma_nonempty_and_root_dirs(self):
        for bad in ("sap_pages", "chroma_db", "."):
            (self.tmp / "sap_pages").mkdir(exist_ok=True)
            with self.assertRaises(ConfigError, msg=bad):
                self.build(out=bad)
        (self.tmp / "stuff").mkdir()
        (self.tmp / "stuff" / "keep.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(ConfigError):
            self.build(out="stuff")
        self.assertTrue((self.tmp / "stuff" / "keep.txt").exists())


def _load_cli():
    spec = importlib.util.spec_from_file_location("build_corpus_cli", ROOT / "scripts" / "build_corpus.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_PYPDF and HAVE_BS4 and (ROOT / "sap_pages" / "041.json").is_file(), "needs pypdf, bs4 and legacy pages")
class RealTopic17EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="e2e17_"))
        cls.legacy_hash = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in ("chunks.json", "cleaned_pages.json", "sap_pages/041.json")}
        cli = _load_cli()
        cls.codes, cls.m, cls.docs, cls.chunks = {}, {}, {}, {}
        # hermetic: an EMPTY registrations file = the "only topic #17 is known" world this class
        # asserts on, independent of which guides are registered in data/ at the moment.
        cls.no_regs = cls.tmp / "no_registrations.json"
        cls.no_regs.write_text(json.dumps({"registrations": []}), encoding="utf-8")
        for scope in ("page_only", "page_and_descendants"):
            out = cls.tmp / scope
            cls.codes[scope] = cli.main(["--offline", "--scope", scope, "--out-dir", str(out), "--registrations-file", str(cls.no_regs), "--corrections-file", str(cls.no_regs)])
            cls.m[scope] = json.loads((out / "final_corpus_manifest.json").read_text(encoding="utf-8"))
            cls.docs[scope] = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (out / "pages").rglob("*.json")}
            cls.chunks[scope] = [json.loads(l) for l in (out / "chunks" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_topic17_is_the_only_resolved_topic_and_corpus_is_flagged_incomplete(self):
        for scope in cls_scopes():
            m = self.m[scope]
            self.assertEqual(self.codes[scope], 0)
            self.assertEqual(m["topic_status_counts"], {"RESOLVED": 1, "UNRESOLVED_GUIDE": 28})
            self.assertFalse(m["corpus_complete"])
            self.assertEqual(len(m["topics"]), 29)
            unresolved = [t for t in m["topics"] if t["status"] != "RESOLVED"]
            self.assertTrue(all(t["page_count"] is None and t["chunk_count"] is None for t in unresolved))

    def test_page_only_and_descendant_counts(self):
        a, b = self.m["page_only"]["totals"], self.m["page_and_descendants"]["totals"]
        self.assertEqual((a["unique_pages_planned"], a["duplicate_pages_identity"], a["duplicate_content_pages"]), (1, 0, 0))
        self.assertEqual((b["unique_pages_planned"], b["duplicate_pages_identity"], b["duplicate_content_pages"]), (22, 0, 0))
        self.assertEqual(len(self.docs["page_only"]), 1)
        self.assertEqual(len(self.docs["page_and_descendants"]), 22)
        self.assertEqual(a["pages_failed"] + b["pages_failed"], 0)

    def test_raw_text_equals_legacy_sap_pages_exactly(self):
        legacy = {}
        for i in range(1, 82):
            p = json.loads((ROOT / "sap_pages" / f"{i:03d}.json").read_text(encoding="utf-8"))
            legacy[p["file_path"]] = p
        for d in self.docs["page_and_descendants"].values():
            self.assertEqual(d["text_raw"], legacy[d["file_path"]]["text"], d["page_title"])
            self.assertEqual(d["source_type"], "legacy_local_copy")
            self.assertIsNone(d["retrieved_at"])                          # local copy: no fake timestamp
            self.assertEqual((d["numeric_deliverable_id"], d["build_no"]), ("40374631", "1779"))
            self.assertEqual(d["guide_id"], G17)

    def test_cleaned_text_keeps_every_letter_of_the_source(self):
        for d in self.docs["page_and_descendants"].values():
            r = clean_text(d["text_raw"], d["page_title"])
            self.assertEqual(r.text, d["text"])
            self.assertTrue(check_faithful(d["text_raw"], r), d["page_title"])

    def test_chunks_keep_identity_and_cover_the_cleaned_text(self):
        docs = self.docs["page_and_descendants"]
        for c in self.chunks["page_and_descendants"]:
            self.assertEqual(validate_chunk(c), [])
            self.assertEqual((c["topic_id"], c["guide_id"]), (17, G17))
            self.assertTrue(c["canonical_url"].startswith(f"https://help.sap.com/docs/{PRODUCT}/{G17}/"))
        for doc_id_, d in docs.items():
            lines = [l for c in self.chunks["page_and_descendants"] if c["page_id"] == d["page_id"] for l in c["text"].split("\n")]
            for l in d["text"].split("\n"):
                if len(l) <= 1000:
                    self.assertIn(l, lines, d["page_title"])
        ids = [c["chunk_id"] for c in self.chunks["page_and_descendants"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_topic_page_is_chunks_subset_and_topic_row(self):
        row = self.m["page_and_descendants"]["topics"][16]
        self.assertEqual((row["topic_id"], row["page_count"], row["unique_page_count"], row["status"]), (17, 22, 22, "RESOLVED"))
        self.assertEqual(row["chunk_count"], len(self.chunks["page_and_descendants"]))
        self.assertEqual(self.m["page_only"]["topics"][16]["chunk_count"], len(self.chunks["page_only"]))
        self.assertEqual({c["page_id"] for c in self.chunks["page_only"]}, {P17})

    def test_require_complete_and_default_cache_mode_exit_codes(self):
        cli = _load_cli()
        out = self.tmp / "rc"
        self.assertEqual(cli.main(["--offline", "--require-complete", "--out-dir", str(out), "--registrations-file", str(self.no_regs), "--corrections-file", str(self.no_regs)]), EXIT_INCOMPLETE)
        self.assertEqual(cli.main(["--out-dir", str(self.tmp / "empty_cache")]), EXIT_FETCH_OR_REGISTRATION)   # network off, cache empty
        self.assertEqual(cli.main(["--offline", "--max-chunk-chars", "50", "--out-dir", str(self.tmp / "bad")]), 3)  # invalid config

    def test_audit_script_reports_incomplete_corpus_and_clean_pages(self):
        spec = importlib.util.spec_from_file_location("audit_corpus_cli", ROOT / "scripts" / "audit_corpus.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.main([str(self.tmp / "page_and_descendants")]), 1)          # incomplete -> NOT READY
        a = json.loads((self.tmp / "page_and_descendants" / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual((a["topics_resolved"], a["guides_resolved"]), ("1/29", "1/7"))
        self.assertFalse(a["ready_for_embedding"])
        self.assertEqual((a["suspicious_pages"], a["cross_guide_page_ids"], a["pages_not_in_any_target_topic"]), ([], [], []))
        self.assertEqual((a["totals"]["unique_pages"], a["totals"]["chunks"], a["totals"]["duplicate_chunks_exact"]), (22, 51, 0))
        self.assertEqual(sum(g["chunks"] for g in a["per_guide"].values()), 51)

    def test_legacy_corpus_untouched(self):
        for p, h in self.legacy_hash.items():
            self.assertEqual(hashlib.sha256((ROOT / p).read_bytes()).hexdigest(), h, p)
        self.assertFalse((ROOT / "chroma_db").exists())


def cls_scopes():
    return ("page_only", "page_and_descendants")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(list((ROOT / "data" / "toc").glob("*.json")) if (ROOT / "data" / "toc").is_dir() else [], "no saved TOCs")
class SavedRealTocs(unittest.TestCase):
    def test_every_saved_toc_loads_and_is_named_by_its_response_loio(self):
        from sap_resolver.toc import TocTree
        for f in sorted((ROOT / "data" / "toc").glob("*.json")):
            tree = TocTree.from_file(f)
            self.assertEqual(tree.guide_id, f.stem, f.name)
            self.assertGreater(len(tree), 0, f.name)
