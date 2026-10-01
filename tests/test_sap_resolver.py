"""Tests for the multi-guide resolver. Offline; use the locally saved topic #17 TOC
(master_data.json) and the 29 reference-card PDFs. Run from the repo root:

    python -m pytest tests -q          (or)          python -m unittest discover -s tests -t .
"""
import glob
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from sap_resolver import events as ev                                              # noqa: E402
from sap_resolver.fetch import (FetchedPage, HttpApiError, LegacyLocalFetcher, NetworkDisabledError,  # noqa: E402
                                PageNotAvailableLocally, SapHelpApiFetcher, UnresolvedGuideError, ingest_plan)
from sap_resolver.pdf_cards import build_topic_manifest                            # noqa: E402
from sap_resolver.plan import (ConfigError, IngestConfig, ScopeMode, assert_safe_out_dir, build_plan,  # noqa: E402
                               storage_key)
from sap_resolver.registry import (GuideRegistry, RegistrationError, discover_local_evidence,  # noqa: E402
                                   refresh_registry, register_guide)
from sap_resolver.resolver import PAGE_NOT_IN_TOC, RESOLVED, UNRESOLVED, resolve_topics, summarize  # noqa: E402
from sap_resolver.toc import TocTree                                               # noqa: E402
from sap_resolver.urls import UrlParseError, canonical_help_url, parse_help_url    # noqa: E402

try:
    import pypdf  # noqa: F401
    HAVE_PYPDF = True
except ImportError:
    HAVE_PYPDF = False

G17 = "e52c8ee6197147ec97dfc2eb8c46a3ad"
P17 = "0bfcc5536a51204be10000000a174cb4"
URL17 = f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G17}/{P17}.html"
BP_PAGE = "78d96b574080" # prefix of 'SAP Business Partner'


def _topic17():
    return {"topic_id": 17, "title": "Contract Accounts Overview", "category": "FI-CA / Contract Accounting",
            "pdf_file": "17_Contract_Accounts_Overview.pdf", "guide_id": G17, "page_id": P17,
            "product": "SAP_S4HANA_ON-PREMISE", "canonical_url": URL17}


def _registry():
    try:
        import bs4  # noqa: F401  (needed to prove the numeric-id <-> loio binding by content match)
    except ImportError:
        raise unittest.SkipTest("beautifulsoup4 not installed")
    return GuideRegistry(refresh_registry({"guides": [{"guide_id": G17, "product": "SAP_S4HANA_ON-PREMISE",
                                                        "topic_ids": [17]}]}, ROOT), ROOT)


class UrlTests(unittest.TestCase):
    def test_parse_card_url(self):
        p = parse_help_url(URL17)
        self.assertEqual((p.product, p.guide_id, p.guide_id_kind, p.page_id, p.alias_suffix),
                         ("SAP_S4HANA_ON-PREMISE", G17, "loio", P17, ""))
        self.assertEqual(canonical_help_url(p.product, p.guide_id, p.page_id), URL17)

    def test_query_alias_numeric_and_case(self):
        p = parse_help_url(URL17 + "?version=2025.001")
        self.assertEqual(p.version, "2025.001")
        self.assertEqual(p.page_id, P17)                      # query is not identity
        a = parse_help_url("https://help.sap.com/docs/X/40374631/4371ce53118d4308e10000000a174cb4-35.html")
        self.assertEqual((a.guide_id_kind, a.alias_suffix, a.page_id[:4]), ("numeric", "-35", "4371"))
        self.assertEqual(parse_help_url(URL17.upper().replace("HTTPS", "https").replace("HELP.SAP.COM", "help.sap.com")
                                        .replace("/DOCS/", "/docs/").replace(".HTML", ".html")).page_id, P17)

    def test_rejects_garbage(self):
        for bad in ["", "https://example.com/docs/a/b/c.html", "https://help.sap.com/docs/a/b.html",
                    "https://help.sap.com/docs/P/notaguide/0bfcc5536a51204be10000000a174cb4.html",
                    "https://help.sap.com/docs/P/" + G17 + "/short.html"]:
            with self.assertRaises(UrlParseError, msg=bad):
                parse_help_url(bad)


@unittest.skipUnless(HAVE_PYPDF, "pypdf not installed")
class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log = ev.EventLog()
        cls.m = build_topic_manifest(ROOT, cls.log)
        cls.topics = {t["topic_id"]: t for t in cls.m["topics"]}

    def test_29_topics_1_to_1_with_pdfs(self):
        self.assertEqual(self.m["topic_count"], 29)
        self.assertEqual(sorted(self.topics), list(range(1, 30)))
        self.assertEqual(len({t["pdf_file"] for t in self.topics.values()}), 29)
        self.assertEqual(len(glob.glob(str(ROOT / "[0-9][0-9]_*.pdf"))), 29)
        self.assertEqual(self.log.of(ev.PAGE_FAILED), [])

    def test_every_topic_has_required_fields(self):
        for t in self.topics.values():
            for k in ("title", "category", "pdf_file", "guide_id", "page_id", "canonical_url", "pdf_sha256"):
                self.assertTrue(t[k], (t["topic_id"], k))
            self.assertEqual(len(t["guide_id"]), 32)
            self.assertEqual(len(t["page_id"]), 32)
            self.assertNotIn("&#8203;", t["canonical_url"])
            self.assertTrue(t["pdf_file"].startswith(f"{t['topic_id']:02d}_"))   # cross-check, not trust

    def test_topic17(self):
        t = self.topics[17]
        self.assertEqual((t["title"], t["category"], t["guide_id"], t["page_id"], t["canonical_url"]),
                         ("Contract Accounts Overview", "FI-CA / Contract Accounting", G17, P17, URL17))

    def test_seven_guides_and_url_anomalies(self):
        self.assertEqual(self.m["guide_count"], 7)
        self.assertEqual(self.topics[18]["url_version"], "2025.001")
        self.assertEqual(self.topics[23]["url_version"], "2025.001")
        self.assertIn("/SAP_S4HANA_ON-PREMISE/", self.topics[14]["canonical_url"])   # lower-case product normalised
        self.assertIn("sap_s4hana_on-premise", self.topics[14]["url_as_given"])      # original preserved

    def test_agrees_with_earlier_audit_manifest(self):
        p = ROOT / "data" / "corpus_manifest.json"
        if not p.is_file():
            self.skipTest("data/corpus_manifest.json not present")
        for t in json.loads(p.read_text(encoding="utf-8"))["topics"]:
            mine = self.topics[t["topic_no"]]
            self.assertEqual((mine["guide_id"], mine["page_id"], mine["title"]),
                             (t["guide_id"], t["page_id"], t["title"]))


class TocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = TocTree.from_file(ROOT / "master_data.json")

    def test_shape(self):
        self.assertEqual((self.tree.guide_id, len(self.tree)), (G17, 81))
        self.assertEqual(sum(n.is_alias for n in self.tree.nodes.values()), 6)

    def test_topic17_node_and_tree(self):
        n = self.tree.find_page(P17)[0]
        self.assertEqual((n.title, n.depth, n.parent, n.toc_path), ("Contract Accounts", 0, None, ("Contract Accounts",)))
        self.assertEqual(len(n.children), 10)
        self.assertEqual(len(list(self.tree.descendants(n))), 21)
        self.assertEqual(len(list(self.tree.descendants(n, max_depth=1))), 10)
        deep = [d for d in self.tree.descendants(n) if d.depth == 2][0]
        self.assertEqual(self.tree.parent_of(deep).depth, 1)
        self.assertEqual(deep.toc_path[0], "Contract Accounts")
        self.assertEqual(len(deep.toc_path), 3)

    def test_alias_nodes_share_page_id(self):
        aliases = [n for n in self.tree.nodes.values() if n.is_alias]
        for a in aliases:
            nodes = self.tree.find_page(a.page_id)
            self.assertEqual(len(nodes), 2)
            self.assertFalse(nodes[0].is_alias)     # primary first
            self.assertEqual(nodes[0].title, a.title)

    def test_map_root_is_not_a_node(self):
        self.assertTrue(self.tree.is_map_root("0a6ace53118d4308e10000000a174cb4"))
        self.assertEqual(self.tree.find_page("0a6ace53118d4308e10000000a174cb4"), [])


class RegistryTests(unittest.TestCase):
    def test_only_proven_guide_has_fetch_ids(self):
        _registry()   # skips when bs4 is missing
        ev_ = discover_local_evidence(ROOT)
        self.assertEqual(list(ev_), [G17])
        e = ev_[G17]
        self.assertEqual((e["numeric_deliverable_id"], e["build_no"], e["fetch_identifiers_status"]),
                         ("40374631", "1779", "verified"))
        self.assertTrue(any("byte-identical" in s for s in e["evidence"]))

    def test_unknown_guides_are_never_guessed(self):
        other = "f4a255a5de524e3992155767996fb1fd"
        reg = refresh_registry({"guides": [{"guide_id": G17, "product": "P", "topic_ids": [17]},
                                           {"guide_id": other, "product": "P", "topic_ids": [2]}]}, ROOT)
        g = reg["guides"][other]
        self.assertIsNone(g["numeric_deliverable_id"])
        self.assertIsNone(g["build_no"])
        self.assertIsNone(g["toc_file"])
        self.assertEqual(g["fetch_identifiers_status"], "unresolved")

    def test_hand_entered_values_survive_refresh(self):
        other = "f4a255a5de524e3992155767996fb1fd"
        man = {"guides": [{"guide_id": other, "product": "P", "topic_ids": [2]}]}
        first = refresh_registry(man, ROOT)
        first["guides"][other].update(numeric_deliverable_id="111", build_no="7")
        second = refresh_registry(man, ROOT, first)
        self.assertEqual(second["guides"][other]["numeric_deliverable_id"], "111")
        self.assertEqual(second["guides"][other]["fetch_identifiers_status"], "manual_unverified")


class RegisterGuideTests(unittest.TestCase):
    OTHER = "f4a255a5de524e3992155767996fb1fd"
    P2 = "8082ce53118d4308e10000000a174cb4"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reg_test_", dir=ROOT / "data"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.man = {"guides": [{"guide_id": G17, "product": "P", "topic_ids": [17]},
                               {"guide_id": self.OTHER, "product": "P", "topic_ids": [2]}]}
        self.reg = refresh_registry(self.man, ROOT)
        self.resp = {"data": {"deliverable": {"loio": self.OTHER, "title": "Synthetic", "version": "1", "languageCode": "en-US",
                                              "landingPage": "a" * 32 + ".html", "buildableMapLoio": "b" * 32,
                                              "fullToc": [{"t": "Move-In/Out", "u": self.P2 + ".html",
                                                           "c": [{"t": "Child", "u": "c" * 32 + ".html", "c": []}]}]}}}

    def test_registering_a_user_supplied_toc_resolves_its_topics(self):
        reg = register_guide(self.reg, self.man, self.resp, self.tmp / "toc" / "x.json", ROOT, "111", "7", "from browser")
        g = reg["guides"][self.OTHER]
        self.assertEqual((g["numeric_deliverable_id"], g["build_no"], g["fetch_identifiers_status"]), ("111", "7", "manual_unverified"))
        self.assertIn("NOT machine-verified", g["evidence"][-1])
        t = dict(_topic17(), topic_id=2, guide_id=self.OTHER, page_id=self.P2)
        r = resolve_topics([t], GuideRegistry(reg, ROOT))[0][0]
        self.assertEqual((r.status, r.direct_child_count, r.fetch_ready), (RESOLVED, 1, True))

    def test_never_silently_overwrites_or_accepts_foreign_guides(self):
        reg = register_guide(self.reg, self.man, self.resp, self.tmp / "t.json", ROOT, "111", "7")
        with self.assertRaises(RegistrationError):
            register_guide(reg, self.man, self.resp, self.tmp / "t.json", ROOT, "222", "7")      # different numeric id
        other = json.loads(json.dumps(self.resp))
        other["data"]["deliverable"]["loio"] = "d" * 32
        with self.assertRaises(RegistrationError):
            register_guide(reg, self.man, other, self.tmp / "u.json", ROOT)                        # not a card guide
        changed = json.loads(json.dumps(self.resp))
        changed["data"]["deliverable"]["title"] = "changed"
        with self.assertRaises(RegistrationError):
            register_guide(reg, self.man, changed, self.tmp / "t.json", ROOT)                      # existing TOC differs
        with self.assertRaises(RegistrationError):
            register_guide(reg, self.man, self.resp, self.tmp / "v.json", ROOT, "abc", None)       # non-digit id


class ResolverTests(unittest.TestCase):
    def test_topic17_resolved_with_full_metadata(self):
        log = ev.EventLog()
        res, guides, trees = resolve_topics([_topic17()], _registry(), log)
        r = res[0]
        self.assertEqual(r.status, RESOLVED)
        self.assertEqual((r.topic_id, r.title, r.source_pdf, r.guide_id, r.page_id, r.canonical_url),
                         (17, "Contract Accounts Overview", "17_Contract_Accounts_Overview.pdf", G17, P17, URL17))
        self.assertEqual(r.toc_path, ["Contract Accounts"])
        self.assertIsNone(r.parent_page_id)
        self.assertEqual((r.direct_child_count, r.descendant_count, len(r.child_page_ids)), (10, 21, 10))
        self.assertTrue(r.fetch_ready)
        self.assertEqual(len(log.of(ev.PAGE_RESOLVED)), 1)
        self.assertEqual(len(log.of(ev.GUIDE_RESOLVED)), 1)
        self.assertEqual(log.of(ev.TOPIC_UNRESOLVED), [])

    def test_child_reports_parent(self):
        tree = trees = TocTree.from_file(ROOT / "master_data.json")
        child = next(n for n in tree.nodes.values() if n.title == "Contract Account Category")
        t = dict(_topic17(), topic_id=99, page_id=child.page_id)
        r = resolve_topics([t], _registry())[0][0]
        self.assertEqual((r.parent_page_id, r.parent_title, r.depth), (P17, "Contract Accounts", 1))
        self.assertEqual(r.toc_path, ["Contract Accounts", "Contract Account Category"])

    def test_unknown_guide_unresolved_not_guessed(self):
        t = dict(_topic17(), topic_id=2, guide_id="f4a255a5de524e3992155767996fb1fd", page_id="8082ce53118d4308e10000000a174cb4")
        log = ev.EventLog()
        res, guides, _ = resolve_topics([t], _registry(), log)
        self.assertEqual(res[0].status, UNRESOLVED)
        self.assertEqual(res[0].reason, "GUIDE_NOT_IN_REGISTRY")
        self.assertEqual(len(log.of(ev.TOPIC_UNRESOLVED)), 1)
        self.assertEqual(len(log.of(ev.GUIDE_UNRESOLVED)), 1)

    def test_page_missing_from_known_toc_unresolved(self):
        t = dict(_topic17(), page_id="0" * 32)
        res, _, _ = resolve_topics([t], _registry())
        self.assertEqual((res[0].status, res[0].reason), (UNRESOLVED, PAGE_NOT_IN_TOC))

    def test_map_root_of_other_guide_is_a_note_not_a_resolution(self):
        t = dict(_topic17(), topic_id=1, guide_id="021b182b0c47416c8fafed67ebfd78a9",
                 page_id="0a6ace53118d4308e10000000a174cb4")
        reg = GuideRegistry(refresh_registry({"guides": [
            {"guide_id": G17, "product": "P", "topic_ids": [17]},
            {"guide_id": t["guide_id"], "product": "P", "topic_ids": [1]}]}, ROOT), ROOT)
        res, _, _ = resolve_topics([_topic17(), t], reg)
        r = {x.topic_id: x for x in res}
        self.assertEqual(r[17].status, RESOLVED)
        self.assertEqual(r[1].status, UNRESOLVED)
        self.assertIn("NOT confirmed", r[1].candidate_note)

    def test_toc_guide_mismatch_is_rejected(self):
        reg = _registry()
        other = "f4a255a5de524e3992155767996fb1fd"
        reg.guides[other] = {"guide_id": other, "toc_file": "master_data.json"}   # wrong TOC for that guide
        t = dict(_topic17(), guide_id=other, topic_id=2)
        r = resolve_topics([t], reg)[0][0]
        self.assertEqual((r.status, r.reason), (UNRESOLVED, "TOC_GUIDE_MISMATCH"))

    def test_duplicate_topic_page_logged(self):
        log = ev.EventLog()
        resolve_topics([_topic17(), dict(_topic17(), topic_id=88)], _registry(), log)
        self.assertTrue(any(e["kind"] == "two_topics_same_page" for e in log.of(ev.DUPLICATE_PAGE)))

    def test_summary_counts(self):
        res, guides, _ = resolve_topics([_topic17(),
                                         dict(_topic17(), topic_id=2, guide_id="f4a255a5de524e3992155767996fb1fd")], _registry())
        s = summarize(res, guides)
        self.assertEqual((s["topics_resolved"], s["topics_unresolved"], s["guides_resolved"], s["guides_unresolved"]),
                         (1, 1, 1, 1))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.log = ev.EventLog()
        self.topics = {17: _topic17()}
        self.res, _, self.trees = resolve_topics([_topic17()], _registry(), self.log)

    def plan(self, scope, **kw):
        return build_plan(self.res, self.trees, self.topics, IngestConfig(default_scope=scope, **kw), self.log)

    def test_page_only(self):
        p = self.plan(ScopeMode.PAGE_ONLY)
        self.assertEqual([e.page_id for e in p.entries], [P17])
        self.assertEqual(p.entries[0].topic_roles, {17: "topic_page"})

    def test_page_and_descendants(self):
        p = self.plan(ScopeMode.PAGE_AND_DESCENDANTS)
        self.assertEqual(len(p.entries), 22)
        self.assertEqual(p.entries[0].page_id, P17)
        self.assertEqual({e.topic_roles[17] for e in p.entries[1:]}, {"descendant"})
        legacy = {json.loads(Path(f).read_text(encoding="utf-8"))["file_path"] for f in glob.glob(str(ROOT / "sap_pages/*.json"))}
        self.assertTrue({e.file_path for e in p.entries} <= legacy)       # all 22 exist in legacy corpus
        self.assertEqual(len({e.storage_key for e in p.entries}), 22)
        self.assertTrue(all(e.storage_key.startswith(G17 + "/") for e in p.entries))
        self.assertTrue(all(e.canonical_url.startswith("https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/" + G17) for e in p.entries))

    def test_max_depth(self):
        self.assertEqual(len(self.plan(ScopeMode.PAGE_AND_DESCENDANTS, max_depth=1).entries), 11)

    def test_per_topic_override(self):
        cfg = IngestConfig(default_scope=ScopeMode.PAGE_ONLY, topic_scopes={17: ScopeMode.PAGE_AND_DESCENDANTS})
        self.assertEqual(len(build_plan(self.res, self.trees, self.topics, cfg, self.log).entries), 22)

    def test_config_parsing_and_validation(self):
        c = IngestConfig.from_dict({"default_scope": "page_and_descendants", "topic_scopes": {"17": "page_only"}})
        self.assertEqual((c.scope_for(17), c.scope_for(1)), (ScopeMode.PAGE_ONLY, ScopeMode.PAGE_AND_DESCENDANTS))
        with self.assertRaises(ConfigError):
            IngestConfig.from_dict({"default_scope": "everything"})
        with self.assertRaises(ConfigError):
            IngestConfig.from_dict({"max_depth": 0})
        shipped = IngestConfig.load(ROOT / "data" / "ingest_config.json")
        self.assertEqual(shipped.default_scope, ScopeMode.PAGE_ONLY)

    def test_unresolved_topics_are_skipped_not_planned(self):
        res, _, trees = resolve_topics([_topic17(), dict(_topic17(), topic_id=2, guide_id="f4a255a5de524e3992155767996fb1fd")], _registry())
        p = build_plan(res, trees, {17: _topic17(), 2: _topic17()}, IngestConfig(), self.log)
        self.assertEqual(len(p.entries), 1)
        self.assertEqual([s["topic_id"] for s in p.skipped_topics], [2])

    def test_alias_and_overlap_are_deduplicated(self):
        tree = self.trees[G17]
        bp = next(n for n in tree.nodes.values() if n.page_id.startswith(BP_PAGE))
        t = dict(_topic17(), topic_id=50, page_id=bp.page_id)
        res, _, trees = resolve_topics([_topic17(), t], _registry(), self.log)
        self.log.events.clear()
        p = build_plan(res, trees, {17: _topic17(), 50: t}, IngestConfig(default_scope=ScopeMode.PAGE_AND_DESCENDANTS), self.log)
        keys = [(e.guide_id, e.page_id) for e in p.entries]
        self.assertEqual(len(keys), len(set(keys)))                      # no page planned twice
        merging = [e for e in p.entries if e.title == "Merging Business Partners (IS-U)"]
        self.assertEqual(len(merging), 1)
        self.assertEqual(len(merging[0].alias_file_paths), 1)            # -35 alias folded in
        self.assertTrue(any(e["kind"] == "plan_dedup" for e in self.log.of(ev.DUPLICATE_PAGE)))

    def test_topic_page_role_wins_over_descendant(self):
        child = next(n for n in self.trees[G17].nodes.values() if n.title == "Contract Account Category")
        t = dict(_topic17(), topic_id=51, page_id=child.page_id)
        res, _, trees = resolve_topics([_topic17(), t], _registry(), self.log)
        p = build_plan(res, trees, {17: _topic17(), 51: t}, IngestConfig(default_scope=ScopeMode.PAGE_AND_DESCENDANTS), self.log)
        e = next(x for x in p.entries if x.page_id == child.page_id)
        self.assertEqual(e.topic_roles, {17: "descendant", 51: "topic_page"})
        self.assertEqual(len(p.entries), 22)


class NamingSafetyTests(unittest.TestCase):
    def test_guides_cannot_collide(self):
        a = storage_key(G17, P17)
        b = storage_key("f4a255a5de524e3992155767996fb1fd", P17)         # same page id, different guide
        self.assertNotEqual(a, b)
        self.assertEqual(a, storage_key(G17.upper(), P17.upper()))        # deterministic / case-insensitive

    def test_bad_ids_rejected(self):
        for g, p in [("../x", P17), (G17, "../../etc/passwd"), (G17, "short")]:
            with self.assertRaises(ValueError):
                storage_key(g, p)

    def test_protected_output_dirs(self):
        for d in ("sap_pages", "sap_pages/x", "chroma_db", "."):
            with self.assertRaises(ConfigError, msg=d):
                assert_safe_out_dir(d, ROOT)
        assert_safe_out_dir("data/sap_help", ROOT)


class _FakeResp:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code, self._p, self._bad = status, payload, bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            err = requests.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._p


class _FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.resp


class FetcherTests(unittest.TestCase):
    def setUp(self):
        self.log = ev.EventLog()
        self.reg = _registry()
        res, _, trees = resolve_topics([_topic17()], self.reg, self.log)
        self.entry = build_plan(res, trees, {17: _topic17()}, IngestConfig(), self.log).entries[0]

    def test_request_params_match_legacy_scraper_mechanism(self):
        f = SapHelpApiFetcher(self.reg, self.log)
        self.assertEqual(f.request_params(G17, self.entry.file_path),
                         {"deliverableInfo": "1", "deliverable_id": "40374631", "buildNo": "1779",
                          "file_path": self.entry.file_path})

    def test_unknown_guide_refuses_to_guess(self):
        other = "f4a255a5de524e3992155767996fb1fd"
        self.reg.guides[other] = {"guide_id": other, "numeric_deliverable_id": None, "build_no": None}
        f = SapHelpApiFetcher(self.reg, self.log, allow_network=True, session=_FakeSession(_FakeResp()))
        with self.assertRaises(UnresolvedGuideError):
            f.fetch_page(type(self.entry)(**{**self.entry.__dict__, "guide_id": other}))
        self.assertEqual(f._session.calls, [])                           # no request was made

    def test_network_disabled_by_default(self):
        s = _FakeSession(_FakeResp())
        with self.assertRaises(NetworkDisabledError):
            SapHelpApiFetcher(self.reg, self.log, session=s).fetch_page(self.entry)
        self.assertEqual(s.calls, [])

    def test_http_error_is_logged(self):
        s = _FakeSession(_FakeResp(status=503))
        f = SapHelpApiFetcher(self.reg, self.log, allow_network=True, session=s, delay_s=0, sleep=lambda _s: None)
        with self.assertRaises(HttpApiError) as cm:
            f.fetch_page(self.entry)
        self.assertEqual(cm.exception.status, 503)
        e = self.log.of(ev.HTTP_ERROR)
        self.assertEqual((len(e), e[0]["status"], e[-1]["will_retry"]), (4, 503, False))   # 1 try + 3 retries

    def test_success_and_parse_failures(self):
        ok = _FakeSession(_FakeResp(payload={"data": {"body": "<html><body><h1>Hi</h1><p>there</p></body></html>",
                                                       "currentPage": {"t": "x"}}}))
        fp = SapHelpApiFetcher(self.reg, self.log, allow_network=True, session=ok, delay_s=0).fetch_page(self.entry)
        self.assertEqual(fp.text, "Hi\nthere")
        self.assertEqual(ok.calls[0][0], "https://help.sap.com/http.svc/pagecontent")
        for resp in (_FakeResp(payload={"data": {}}), _FakeResp(bad_json=True)):
            from sap_resolver.fetch import PageParseError
            with self.assertRaises(PageParseError):
                SapHelpApiFetcher(self.reg, self.log, allow_network=True, session=_FakeSession(resp), delay_s=0).fetch_page(self.entry)


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ingest_test_", dir=ROOT / "data"))   # inside repo, outside protected dirs
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = ev.EventLog()
        self.reg = _registry()
        res, _, trees = resolve_topics([_topic17()], self.reg, self.log)
        self.plan = build_plan(res, trees, {17: _topic17()},
                               IngestConfig(default_scope=ScopeMode.PAGE_AND_DESCENDANTS), self.log)

    def test_local_ingest_of_topic17_matches_legacy_pages_and_is_idempotent(self):
        f = LegacyLocalFetcher(ROOT, self.reg)
        stats = ingest_plan(self.plan, f, ROOT, self.tmp, self.log)
        self.assertEqual((stats["planned"], stats["stored"], stats["failed"]), (22, 22, 0))
        files = sorted((self.tmp / G17).glob("*.json"))
        self.assertEqual(len(files), 22)
        rec = json.loads((self.tmp / G17 / f"{P17}.json").read_text(encoding="utf-8"))
        legacy = json.loads((ROOT / "sap_pages" / "041.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["text"], legacy["text"])
        self.assertEqual((rec["guide_id"], rec["page_id"], rec["canonical_url"], rec["toc_path"], rec["topic_roles"]),
                         (G17, P17, URL17, ["Contract Accounts"], {"17": "topic_page"}))
        again = ingest_plan(self.plan, f, ROOT, self.tmp, self.log)
        self.assertEqual((again["stored"], again["skipped_existing"]), (0, 22))
        self.assertEqual(len(self.log.of(ev.PAGE_STORED)), 22)

    def test_failed_page_and_http_error_are_logged_and_do_not_abort(self):
        class Flaky:
            def __init__(self, log):
                self.n, self.log = 0, log

            def fetch_page(self, e):
                self.n += 1
                if self.n == 2:
                    raise PageNotAvailableLocally("gone")
                if self.n == 3:
                    self.log.emit(ev.HTTP_ERROR, status=500)
                    raise HttpApiError("500", 500)
                return FetchedPage(f"text {self.n}", None, "fake")
        stats = ingest_plan(self.plan, Flaky(self.log), ROOT, self.tmp, self.log)
        self.assertEqual((stats["stored"], stats["failed"]), (20, 2))
        self.assertEqual(len(self.log.of(ev.PAGE_FAILED)), 1)
        self.assertEqual(len(self.log.of(ev.HTTP_ERROR)), 1)

    def test_duplicate_content_is_flagged_but_kept(self):
        class Same:
            def fetch_page(self, e):
                return FetchedPage("identical text", None, "fake")
        stats = ingest_plan(self.plan, Same(), ROOT, self.tmp, self.log)
        self.assertEqual((stats["stored"], stats["duplicate_content"]), (22, 21))
        d = self.log.of(ev.DUPLICATE_CONTENT)[0]
        self.assertEqual(d["duplicate_of"], f"{G17}/{P17}.json")
        self.assertEqual(len(list((self.tmp / G17).glob("*.json"))), 22)

    def test_refuses_legacy_and_chroma_dirs_and_dry_run_writes_nothing(self):
        for d in ("sap_pages", "chroma_db"):
            with self.assertRaises(ConfigError):
                ingest_plan(self.plan, LegacyLocalFetcher(ROOT, self.reg), ROOT, ROOT / d, self.log)
        stats = ingest_plan(self.plan, LegacyLocalFetcher(ROOT, self.reg), ROOT, self.tmp, self.log, dry_run=True)
        self.assertEqual(stats["stored"], 0)
        self.assertFalse(list(self.tmp.iterdir()))

    def test_legacy_fetcher_refuses_unverified_guide(self):
        other = "f4a255a5de524e3992155767996fb1fd"
        e = type(self.plan.entries[0])(**{**self.plan.entries[0].__dict__, "guide_id": other})
        with self.assertRaises(PageNotAvailableLocally):
            LegacyLocalFetcher(ROOT, self.reg).fetch_page(e)


class CorpusAuditArtifactTests(unittest.TestCase):
    """Sanity-checks the generated data/corpus_audit.json against the raw legacy files."""

    def setUp(self):
        p = ROOT / "data" / "corpus_audit.json"
        if not p.is_file():
            self.skipTest("run scripts/corpus_audit.py first")
        self.a = json.loads(p.read_text(encoding="utf-8"))

    def test_legacy_numbers(self):
        chunks = json.loads((ROOT / "chunks.json").read_text(encoding="utf-8"))
        texts = [c["text"] for c in chunks]
        self.assertEqual(self.a["legacy_corpus"]["chunks"], len(chunks))
        self.assertEqual(self.a["legacy_corpus"]["duplicate_chunks"], len(texts) - len(set(texts)))
        self.assertEqual(len(glob.glob(str(ROOT / "sap_pages" / "*.json"))), self.a["legacy_corpus"]["pages"])

    def test_plan_counts_for_topic17_and_unknowns(self):
        a, b = self.a["plans"]["page_only"], self.a["plans"]["page_and_descendants"]
        self.assertEqual((a["unique_pages"], b["unique_pages"], b["duplicate_pages"]), (1, 22, 0))
        self.assertEqual((a["legacy_pages_outside_confirmed_target"], b["legacy_pages_outside_confirmed_target"]), (80, 59))
        for plan in (a, b):
            self.assertEqual(plan["estimated_chunks_for_unresolved_topics"], "UNKNOWN")
        rows = {r["topic_id"]: r for r in self.a["topics"]["page_and_descendants"]}
        self.assertEqual((rows[17]["pages"], rows[17]["chunks"]), (22, 50))
        self.assertEqual({rows[t]["pages"] for t in rows if t != 17}, {"UNKNOWN"})   # never 0 / extrapolated


class IsolationTests(unittest.TestCase):
    def test_runtime_modules_do_not_reference_resolver(self):
        for name in ("rag_chat.py", "retrieve.py", "evaluate_retrieval.py", "rag_core.py", "create_embeddings.py"):
            src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn("sap_resolver", src, name)

    def test_resolver_package_never_imports_rag_or_chroma(self):
        import ast
        banned = {"chromadb", "sentence_transformers", "ollama", "rag_core", "rag_chat", "retrieve", "scripts"}
        for p in (ROOT / "sap_resolver").glob("*.py"):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                for m in mods:
                    self.assertNotIn(m.split(".")[0], banned, f"{p.name} imports {m}")


if __name__ == "__main__":
    unittest.main()


def test_toc_with_pageless_heading_nodes_is_loadable():
    """Real SAP TOCs contain heading nodes with u == '' (title + children only)."""
    from sap_resolver.toc import TocTree
    a, b, c = ("a" * 32), ("b" * 32), ("c" * 32)
    resp = {"data": {"deliverable": {"loio": "f" * 32, "title": "G", "landingPage": a + ".html",
            "fullToc": [{"t": "Root", "u": a + ".html", "c": [
                {"t": "Heading only", "u": "", "h": "", "c": [
                    {"t": "Child B", "u": b + ".html", "c": []},
                    {"t": "Child C", "u": c + ".html", "c": []}]}]}]}}}
    tree = TocTree.from_pagecontent_response(resp)
    assert len(tree) == 3 and tree.pageless_headings == ["Heading only"]
    nb = tree.find_page(b)[0]
    assert nb.parent == a + ".html"                       # attaches to nearest real page
    assert nb.toc_path == ("Root", "Heading only", "Child B")
    assert [n.page_id for n in tree.children_of(tree.find_page(a)[0])] == [b, c]
