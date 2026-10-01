"""Phase 7C - card -> SAP page identity resolution. Local files only; no network, no LLM, no store needed."""
import ast
import copy
import hashlib
import importlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

pid = importlib.import_module("m2c_page_identity")
pj = importlib.import_module("m2c_page_join")

G_A = "021b182b0c47416c8fafed67ebfd78a9"
G_C = "2ac7fe29a0c94cdd88fb80c2cb9f7758"
G_F = "9442486404b54071b4ebeab6a16628e7"
G_17 = "e52c8ee6197147ec97dfc2eb8c46a3ad"
P5 = "8990d0533f8e4308e10000000a174cb4"
P18 = "b1a202c9bb3011da2b24000f20dac9ef"
P17 = "0bfcc5536a51204be10000000a174cb4"
E437 = "e4375c1cad104b2eb7d027369bd76638"

PINNED = {
    "data/topic_corrections.json": "68adee37c1bf8dcaf044a070458e27b5548d72e43520406c8042e4bda5950b06",
    "data/guide_registrations.json": "fe83f7d69ab6f5ee3511d5aa4b933293e1b9ece6c92d75f45aa71c1782b92a53",
    "data/guide_registry.json": "3ce74f9747c73f0a2cb24b0cb6c1073d71c4d2b22ff8fee00203ffd99151d01b",
    "data/topic_manifest.json": "936500096311853a69c9100aca155f5fed4c352f3b2a74ec4d2fe54f78ee08f6",
    "data/source_manifest.json": "08ad208c0187e935377c828faef36ec9fe077704cd580bb38004356f51b740b1",
    "data/retrieval_units.json": "f5e9b908c9b7374ffab5adbc6f8afb9b5597de91cb50ec3fea8b9b3db2d3ff21",
    "data/final_corpus_manifest.json": "77ad52cce25deb7aa5b4e44169d2efd087bb864fd1ffa9185bfd92138e979dbc",
    "scripts/m2c_page_join.py": "a7744701a710df9575eea3861a61204ee63deb995f761cc715dcd150b6dee156",
    "scripts/m2c_orchestrator.py": "89bcfcc1c57669f492d92d12e2f720b2e9d9b36035c678737db4d081213782dd",
    "scripts/m2c_router.py": "b846f18d098406c17859d053ae5b9c0ddb5b82e247e92ac709edeed1113ea8f4",
    "data/toc/2ac7fe29a0c94cdd88fb80c2cb9f7758.json": "ff0f6c77cf09496a51cb566776633aa1c5f9aa17baf06edfbde6aaec1b6d755d",
    "data/toc/9442486404b54071b4ebeab6a16628e7.json": "6c3da0345b96cd246ac779d7b1d6f1cbb70698d829bc63496b8d2c5453ad4112",
    "data/toc/a003b275c98148ee8a4c3fafe9588fe3.json": "77d48416c1bae5ff7fe804e0805e8e42bbccba2cbd27e7b8daa2dfd78f681294",
    "data/toc/ed84b70c199d4470ae2e5ccb93b2e45b.json": "dadb19b61b47a11b0188ed1283622404a07dd74eda9b6d223ed9ed74c8564bf6",
    "data/toc/f4a255a5de524e3992155767996fb1fd.json": "70e661ebce5fdfd26c5efc2513417cd510be68bb3e53f731490116e7f69f6941",
    "captured_responses/1_40374490_b1a202c9bb3011da2b24000f20dac9ef.json": "02347ba7114d855d038aceac7d509071aa48f438729584fb3ef43c65b70fa8ce",
    "captured_responses/1_40374657_8990d0533f8e4308e10000000a174cb4.json": "c5d70f3a66f517f066c91fde745eb7efd09c3ef71dd98682079a3d520579b9c0",
    "captured_responses/2_40374682_8082ce53118d4308e10000000a174cb4.json": "b579297432b2092b904570e3290922277b27d80fdb29dafb5626d27c30aa38f8",
    "captured_responses/3_40374657_4d76765c1e012b8ae10000000a42189b.json": "943c100f3dc33ed2d282dd92f5a3df78c19398724ec8764fa57e5fd41313daf0",
    "captured_responses/4_40404052_147bce53118d4308e10000000a174cb4.json": "587bcb7a409247515c193d1dfd409bf49de23c5071fb9efcfe40044fc91bd25f",
    "captured_responses/5_40374633_cc7bce53118d4308e10000000a174cb4.json": "ac3164f8c1b6cb8cbf0c67453ce5f100af67d0c05fcdd291a3b0b01b147a78a8",
    "captured_responses/6_40374790_790dc5536a51204be10000000a174cb4.json": "769ae06af51e73a9fa7858ddf0d9c59a8164a4c38ae7c8f06ced0381733137aa",
    "data/sap_help/pages/e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4.json": "648fe4b1e28249841dc0be8442a78cd31632934c59d547306cff8a926ace9e59",
    "master_data.json": "e700a061480050b9bdcd7ea9a3a7b85a610a282400f47a5898bdd2c0a9d7e032",
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


_CTX = None


def real_ctx():
    global _CTX
    if _CTX is None:
        _CTX = pid.IdentityContext.from_root(ROOT)
    return _CTX


def real_ids():
    return {i.source_id: i for i in pid.resolve_all(real_ctx())}


# ---------------------------------------------------------------------------------------------- synthetic fixtures
def toc_json(guide, pages, map_root="f" * 32, landing=None):
    items = [{"c": [], "t": f"Page {n}", "u": f"{p}.html", "id": n} for n, p in enumerate(pages)]
    return {"status": "ok", "data": {"deliverable": {"title": "T", "loio": guide, "landingPage": f"{landing or pages[0]}.html",
                                                     "buildableMapLoio": map_root, "fullToc": items}}}


def capture_json(loio, page):
    return {"status": "ok", "data": {"deliverable": {"loio": loio, "title": "D", "fullToc": []},
                                     "currentPage": {"loio": page, "t": "Some title", "u": f"{page}.html"}, "body": "<p>raw body</p>"}}


class Fx:
    """A minimal repository root: registrations, TOCs, captures, corrections, local pages."""

    def __init__(self, td):
        self.root = Path(td)
        self.regs, self.corrs, self.registry = [], [], {}

    def toc(self, guide, pages, **kw):
        p = self.root / "data" / "toc" / f"{guide}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(toc_json(guide, pages, **kw)), encoding="utf-8")

    def capture(self, n, numeric, loio, page):
        d = self.root / "captured_responses"
        d.mkdir(exist_ok=True)
        (d / f"{n}_{numeric}_{page}.json").write_text(json.dumps(capture_json(loio, page)), encoding="utf-8")

    def register(self, guide, verification="response_loio_verified", captured=()):
        self.regs.append({"guide_id": guide, "numeric_id": "1", "build_no": "1", "verification": verification,
                          "captured_page_ids": list(captured)})

    def correct(self, topic, card_guide, card_page, resolved, saved=None):
        ev = [{"kind": "saved_response", "file": saved}] if saved else []
        ev.append({"kind": "user_reported_browser", "machine_verified": False, "observation": "x"})
        self.corrs.append({"topic_id": topic, "card_guide_id": card_guide, "card_page_id": card_page, "resolved_guide_id": resolved,
                           "card_url": f"https://help.sap.com/docs/P/{card_guide}/{card_page}.html", "reason": "r", "evidence": ev})

    def page(self, guide, page, status="OK", text="real page text"):
        d = self.root / "data" / "sap_help" / "pages" / guide
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{page}.json").write_text(json.dumps({"guide_id": guide, "page_id": page, "doc_id": f"{guide}/{page}", "status": status,
                                                     "text": text, "topic_ids": [1], "page_title": "P"}), encoding="utf-8")

    def ctx(self):
        (self.root / "data").mkdir(exist_ok=True)
        (self.root / "data" / "guide_registrations.json").write_text(json.dumps({"registrations": self.regs}), encoding="utf-8")
        (self.root / "data" / "topic_corrections.json").write_text(json.dumps({"corrections": self.corrs}), encoding="utf-8")
        (self.root / "data" / "guide_registry.json").write_text(json.dumps({"guides": self.registry}), encoding="utf-8")
        return pid.IdentityContext.from_root(self.root)


def card(n=1, guide="a" * 32, page="b" * 32, url=None, **kw):
    d = {"source_id": f"M2C-{n:02d}", "source_number": n, "title": f"Card {n}",
         "source_url": url if url is not None else f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{guide}/{page}.html",
         "source_status": "verified", "source_url_status": "ok"}
    d.update(kw)
    return d


GA, GB, PA, PB = "a" * 32, "b" * 32, "c" * 32, "d" * 32


# ---------------------------------------------------------------------------------------------- identity (real data)
class IdentityTests(unittest.TestCase):
    def test_29_cards_with_the_required_fields(self):
        ids = pid.resolve_all(real_ctx())
        self.assertEqual(len(ids), 29)
        self.assertEqual([i.source_id for i in ids], [f"M2C-{n:02d}" for n in range(1, 30)])
        need = {"source_id", "card_title", "card_url", "card_guide_id", "card_page_id", "effective_guide_id", "effective_page_id",
                "resolution_basis", "resolution_status", "local_page_path", "local_page_available", "evidence"}
        for i in ids:
            self.assertTrue(need <= set(i.to_dict()), i.source_id)
            self.assertIn(i.resolution_status, pid.STATUSES)
            self.assertTrue(i.evidence)

    def test_status_counts_are_the_verified_baseline(self):
        c = {}
        for i in real_ids().values():
            c[i.resolution_status] = c.get(i.resolution_status, 0) + 1
        self.assertEqual(c, {"resolved_local_page": 1, "identified_not_local": 23, "corrected_identity": 1,
                             "card_identity_only": 3, "conflicting_identity": 1})

    def test_card_url_guide_and_page_are_preserved_exactly(self):
        units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))["units"]
        tm = {t["topic_id"]: t for t in json.loads((ROOT / "data" / "topic_manifest.json").read_text(encoding="utf-8"))["topics"]}
        sm = {int(d["id"]): d for d in json.loads((ROOT / "data" / "source_manifest.json").read_text(encoding="utf-8"))["documents"]}
        ids = real_ids()
        for u in units:
            i = ids[u["source_id"]]
            m = re.match(r"^https://help\.sap\.com/docs/[^/]+/([0-9a-f]{32})/([0-9a-f]{32})\.html(\?.*)?$", u["source_url"])
            self.assertEqual(i.card_url, u["source_url"])
            self.assertEqual((i.card_guide_id, i.card_page_id), (m.group(1), m.group(2)))
            n = u["source_number"]
            self.assertEqual(i.card_url, sm[n]["authoritative_source"])
            self.assertEqual(i.card_url, tm[n]["url_as_given"])
            self.assertEqual((i.card_guide_id, i.card_page_id), (tm[n]["guide_id"], tm[n]["page_id"]))
            self.assertEqual(i.card_title, u["title"])
            self.assertEqual(i.disagreements, (), i.source_id)

    def test_no_guide_is_inferred_from_a_numeric_id_title_probe_or_other_deliverable(self):
        ctx = real_ctx()
        verified = {g["guide_id"] for g in pid.build_audit(ctx)["guides"] if g["verified"]}
        for i in real_ids().values():
            self.assertIn(i.effective_guide_id, {None, i.card_guide_id, G_C if i.source_id == "M2C-05" else None}, i.source_id)
            if i.effective_guide_id is not None:
                self.assertIn(i.effective_guide_id, verified, i.source_id)
            for v in (i.effective_guide_id, i.effective_page_id):
                self.assertTrue(v is None or re.fullmatch(r"[0-9a-f]{32}", v), v)
            self.assertNotEqual(i.effective_guide_id, E437)
        blob = json.dumps([i.to_dict() for i in real_ids().values()])
        for numeric in ("40374657", "40374490"):   # probe ids only ever appear inside evidence, never as an identity field
            for i in real_ids().values():
                d = i.to_dict()
                for k in ("card_guide_id", "effective_guide_id", "effective_page_id", "card_page_id"):
                    self.assertNotIn(numeric, str(d[k]))
        self.assertIn("40374490", blob)

    def test_page_present_in_another_toc_does_not_change_the_identity(self):
        ids = real_ids()
        for sid in ("M2C-14", "M2C-15"):          # both pages are also nodes of ed84b70c's TOC
            e = [x for x in ids[sid].evidence if x["kind"] == "page_also_in_other_saved_toc"]
            self.assertTrue(e, sid)
            self.assertEqual(ids[sid].effective_guide_id, ids[sid].card_guide_id)
            self.assertEqual(e[0]["authority"], "non_authoritative_hint")

    def test_14_and_23_review_state_and_url_are_preserved(self):
        ids = real_ids()
        self.assertTrue(ids["M2C-14"].card_needs_review)
        self.assertIn("sap_s4hana_on-premise", ids["M2C-14"].card_url)
        self.assertEqual(ids["M2C-14"].resolution_status, "identified_not_local")
        c = [e for e in ids["M2C-14"].evidence if e["kind"] == "card"][0]
        self.assertTrue(any("product segment" in r for r in c["source_url_status_reasons"]))
        self.assertTrue(ids["M2C-23"].card_needs_review)
        self.assertTrue(ids["M2C-23"].card_url.endswith("?version=2025.001"))
        c = [e for e in ids["M2C-23"].evidence if e["kind"] == "card"][0]
        self.assertEqual(c["card_url_query"], "version=2025.001")
        self.assertEqual(ids["M2C-23"].resolution_status, "identified_not_local")

    def test_guide_verification_history_is_represented(self):
        a = pid.build_audit(real_ctx())
        s = a["guide_verification_summary"]
        self.assertEqual((s["guides_known"], s["guides_verified"], s["verified_by_registration"],
                          s["verified_by_registry_local_evidence_only"]), (7, 6, 5, 1))
        self.assertEqual((s["saved_tocs_in_data_toc"], s["saved_tocs_readable"]), (5, 6))
        g = {x["guide_id"]: x for x in a["guides"]}
        self.assertFalse(g[G_A]["verified"])
        self.assertEqual(g[G_A]["registry_json_status"], "unresolved")
        self.assertEqual(g[G_C]["registry_json_status"], "unresolved")            # stale older registry preserved
        self.assertEqual(g[G_C]["declared_verification"], "response_loio_verified")
        self.assertEqual(g[G_17]["verification_basis"], "registry_local_evidence_only")
        self.assertEqual(a["stale_sources"]["data/final_corpus_manifest.json"]["topic_status_counts"],
                         {"RESOLVED": 1, "UNRESOLVED_GUIDE": 28})
        for gid in (G_A, G_F):
            self.assertNotIn(E437, g)

    def test_unverified_guide_cards_are_card_identity_only_without_an_effective_identity(self):
        ids = real_ids()
        for sid in ("M2C-01", "M2C-13", "M2C-16"):
            i = ids[sid]
            self.assertEqual(i.resolution_status, "card_identity_only")
            self.assertEqual(i.card_guide_id, G_A)
            self.assertIsNone(i.effective_guide_id)
            self.assertIsNone(i.effective_page_id)
            self.assertFalse(i.local_page_available)
        hint = [e for e in ids["M2C-01"].evidence if e["kind"] == "page_is_map_root_of_saved_toc"]
        self.assertEqual(hint[0]["guide_ids"], [G_17])
        self.assertEqual(hint[0]["authority"], "non_authoritative_hint")


# ---------------------------------------------------------------------------------------------- #05
class Card05Tests(unittest.TestCase):
    def test_correction_is_recognised_and_explicit(self):
        i = real_ids()["M2C-05"]
        self.assertEqual(i.resolution_status, "corrected_identity")
        self.assertEqual((i.card_guide_id, i.card_page_id), (G_A, P5))
        self.assertEqual((i.effective_guide_id, i.effective_page_id), (G_C, P5))
        self.assertEqual(i.resolution_basis, pid.B_CORRECTION)
        self.assertFalse(i.local_page_available)
        self.assertIsNone(i.local_page_path)

    def test_original_card_and_correction_are_unchanged_and_no_guide_registered(self):
        for f in ("data/topic_corrections.json", "data/topic_manifest.json", "data/source_manifest.json",
                  "data/retrieval_units.json", "data/guide_registrations.json"):
            self.assertEqual(sha(ROOT / f), PINNED[f], f)
        i = real_ids()["M2C-05"]
        self.assertIn(G_A, i.card_url)
        self.assertFalse(real_ctx().guide_status(G_A)["verified"])
        regs = json.loads((ROOT / "data/guide_registrations.json").read_text(encoding="utf-8"))["registrations"]
        self.assertEqual(len(regs), 6)
        self.assertEqual(sum(1 for r in regs if r["verification"] == "response_loio_verified"), 5)

    def test_correction_evidence_is_preserved_and_machine_vs_user_reported_is_distinguished(self):
        i = real_ids()["M2C-05"]
        c = [e for e in i.evidence if e["kind"] == "correction"][0]
        self.assertEqual((c["card_guide_id"], c["resolved_guide_id"]), (G_A, G_C))
        self.assertTrue(c["correction_matches_card_ids"])
        self.assertFalse(c["registers_a_guide"])
        self.assertFalse(c["card_record_modified"])
        kinds = {x["kind"]: x for x in c["evidence_items"]}
        self.assertTrue(kinds["saved_response"]["machine_checked"])
        self.assertTrue(kinds["saved_response"]["passed"])
        self.assertEqual(kinds["saved_response"]["response_loio"], G_C)
        self.assertFalse(kinds["user_reported_browser"]["machine_checked"])
        self.assertIsNone(kinds["user_reported_browser"]["passed"])
        self.assertFalse(kinds["user_reported_browser"]["machine_verified_declared"])
        mem = [e for e in i.evidence if e["kind"] == "toc_membership" and e["role"] == "corrected_guide"][0]
        self.assertTrue(mem["page_is_toc_node"])
        self.assertTrue(mem["page_is_landing_page"])

    def test_the_capture_is_labelled_as_correction_evidence_not_a_registration(self):
        i = real_ids()["M2C-05"]
        caps = [e for e in i.evidence if e["kind"] == "captured_response"]
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["authority"], "topic_correction")
        self.assertEqual(caps[0]["numeric_deliverable_id"], "40374657")
        self.assertFalse(caps[0]["used_as_effective_guide"])


# ---------------------------------------------------------------------------------------------- #18
class Card18Tests(unittest.TestCase):
    def test_conservative_conflict_not_a_correction(self):
        i = real_ids()["M2C-18"]
        self.assertEqual(i.resolution_status, "conflicting_identity")
        self.assertEqual((i.card_guide_id, i.card_page_id), (G_F, P18))
        self.assertIsNone(i.effective_guide_id)
        self.assertIsNone(i.effective_page_id)
        self.assertFalse(i.local_page_available)
        self.assertNotIn(18, real_ctx().corrections)
        self.assertNotIn("corrected_identity", i.resolution_status)

    def test_probe_is_evidence_only_and_never_promoted(self):
        i = real_ids()["M2C-18"]
        caps = [e for e in i.evidence if e["kind"] == "captured_response"]
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["response_loio"], E437)
        self.assertEqual(caps[0]["authority"], "probe_evidence_only")
        self.assertEqual(caps[0]["numeric_deliverable_id"], "40374490")
        self.assertFalse(caps[0]["used_as_effective_guide"])
        self.assertFalse(caps[0]["response_loio_registered_verified"])
        self.assertFalse(caps[0]["response_loio_is_card_guide"])
        self.assertNotIn(E437, (i.effective_guide_id, i.card_guide_id))
        self.assertNotIn(E437, real_ctx().registrations)
        self.assertFalse(real_ctx().guide_status(E437)["verified"])
        self.assertNotIn(E437, {g["guide_id"] for g in pid.build_audit(real_ctx())["guides"]})

    def test_needs_review_and_card_toc_fact_are_visible(self):
        i = real_ids()["M2C-18"]
        self.assertTrue(i.card_needs_review)
        self.assertEqual((i.card_source_status, i.card_source_url_status), ("needs_review", "needs_review"))
        mem = [e for e in i.evidence if e["kind"] == "toc_membership" and e["role"] == "card_guide"][0]
        self.assertTrue(mem["toc_available"])
        self.assertFalse(mem["page_is_toc_node"])
        conflict = [e for e in i.evidence if e["kind"] == "conflict"][0]
        self.assertIn("PAGE_NOT_A_NODE_OF_CARD_GUIDE_TOC", conflict["reasons"])
        self.assertIn(E437, conflict["other_loios_seen"])


# ---------------------------------------------------------------------------------------------- local content
class LocalContentTests(unittest.TestCase):
    def test_only_m2c_17_has_local_content_and_it_is_real(self):
        ids = real_ids()
        self.assertEqual([s for s, i in ids.items() if i.local_page_available], ["M2C-17"])
        i = ids["M2C-17"]
        self.assertEqual(i.resolution_status, "resolved_local_page")
        self.assertEqual((i.effective_guide_id, i.effective_page_id), (G_17, P17))
        self.assertEqual(i.local_page_path, f"data/sap_help/pages/{G_17}/{P17}.json")
        v = pid.validate_local_page(i, ROOT)
        self.assertTrue(v["ok"], v)
        self.assertGreater(v["record"]["text_chars"], 0)
        self.assertTrue(all(v["checks"].values()))
        self.assertEqual(sha(ROOT / i.local_page_path), PINNED[i.local_page_path])       # the page was not modified

    def test_every_other_card_is_not_local(self):
        for s, i in real_ids().items():
            if s != "M2C-17":
                self.assertFalse(i.local_page_available, s)
                self.assertIsNone(i.local_page_path, s)
                self.assertNotEqual(i.resolution_status, "resolved_local_page", s)
                self.assertFalse(pid.validate_local_page(i, ROOT)["ok"])

    def test_identified_not_local_is_never_a_resolved_page(self):
        for s, i in real_ids().items():
            if i.resolution_status == "identified_not_local":
                self.assertFalse(i.local_page_available)
                self.assertIsNone(i.local_page_path)
                j = pj.resolve_card_page({"source_id": s, "source_url": i.card_url}, real_ctx().page_index)
                self.assertEqual(j.state, pj.URL_ONLY)

    def test_toc_capture_and_title_do_not_make_a_page_local(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GA, captured=[PA])
            fx.toc(GA, [PA, PB])
            fx.capture(1, "111", GA, PA)            # raw capture of exactly the card's page, plus a TOC
            ctx = fx.ctx()
            i = pid.resolve_identity(card(1, GA, PA), ctx)
            self.assertEqual(i.resolution_status, "identified_not_local")
            self.assertFalse(i.local_page_available)
            self.assertIsNone(i.local_page_path)

    def test_bad_local_records_are_not_content(self):
        for status, text in (("FAILED", "real text"), ("OK", ""), ("OK", "   \n "), ("EMPTY", "x")):
            with tempfile.TemporaryDirectory() as td:
                fx = Fx(td)
                fx.register(GA, captured=[PA])
                fx.toc(GA, [PA])
                fx.capture(1, "111", GA, PA)
                fx.page(GA, PA, status=status, text=text)
                i = pid.resolve_identity(card(1, GA, PA), fx.ctx())
                self.assertFalse(i.local_page_available, (status, text))
                self.assertEqual(i.resolution_status, "identified_not_local")
                rec = [e for e in i.evidence if e["kind"] == "local_page_record"][0]
                self.assertFalse(rec["counted"])

    def test_good_local_record_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GA, captured=[PA])
            fx.toc(GA, [PA])
            fx.capture(1, "111", GA, PA)
            fx.page(GA, PA)
            i = pid.resolve_identity(card(1, GA, PA), fx.ctx())
            self.assertEqual(i.resolution_status, "resolved_local_page")
            self.assertTrue(i.local_page_available)
            self.assertTrue(i.local_page_path.endswith(f"{GA}/{PA}.json"))

    def test_local_record_under_card_ids_without_effective_identity_is_listed_but_not_counted(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.page(GA, PA)              # guide GA is not registered at all
            i = pid.resolve_identity(card(1, GA, PA), fx.ctx())
            self.assertEqual(i.resolution_status, "card_identity_only")
            self.assertFalse(i.local_page_available)
            rec = [e for e in i.evidence if e["kind"] == "local_page_record"][0]
            self.assertFalse(rec["counted"])


# ---------------------------------------------------------------------------------------------- conflict handling
class ConflictTests(unittest.TestCase):
    def test_real_conflict_is_visible_and_nothing_is_chosen(self):
        confl = [i for i in real_ids().values() if i.resolution_status == "conflicting_identity"]
        self.assertEqual([i.source_id for i in confl], ["M2C-18"])
        for i in confl:
            self.assertIsNone(i.effective_guide_id)
            self.assertTrue([e for e in i.evidence if e["kind"] == "conflict"])

    def test_correction_with_unverified_target_is_not_honoured(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GB, verification="unresolved: nothing")
            fx.toc(GB, [PA])
            fx.capture(1, "111", GB, PA)
            fx.correct(1, GA, PA, GB, saved=f"captured_responses/1_111_{PA}.json")
            i = pid.resolve_identity(card(1, GA, PA), fx.ctx())
            self.assertEqual(i.resolution_status, "conflicting_identity")
            self.assertIsNone(i.effective_guide_id)
            why = [e for e in i.evidence if e["kind"] == "conflict"][0]["reasons"]
            self.assertIn("CORRECTED_GUIDE_NOT_VERIFIED", why)

    def test_correction_whose_page_is_not_in_the_corrected_toc_is_not_honoured(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GB, captured=[PB])
            fx.toc(GB, [PB])
            fx.capture(1, "111", GB, PB)
            fx.capture(2, "111", GB, PA)
            fx.correct(1, GA, PA, GB, saved=f"captured_responses/2_111_{PA}.json")
            i = pid.resolve_identity(card(1, GA, PA), fx.ctx())
            self.assertEqual(i.resolution_status, "conflicting_identity")
            self.assertIn("PAGE_NOT_IN_CORRECTED_GUIDE_TOC", [e for e in i.evidence if e["kind"] == "conflict"][0]["reasons"])

    def test_correction_without_confirming_saved_response_or_for_other_ids_is_not_honoured(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GB, captured=[PA])
            fx.toc(GB, [PA])
            fx.capture(1, "111", GB, PA)
            fx.correct(1, GA, PA, GB, saved="captured_responses/missing.json")          # file does not exist
            fx.correct(2, GA, PB, GB, saved=f"captured_responses/1_111_{PA}.json")      # other card page than the card has
            ctx = fx.ctx()
            i1 = pid.resolve_identity(card(1, GA, PA), ctx)
            self.assertEqual(i1.resolution_status, "conflicting_identity")
            self.assertIn("CORRECTION_SAVED_RESPONSE_NOT_CONFIRMED", [e for e in i1.evidence if e["kind"] == "conflict"][0]["reasons"])
            i2 = pid.resolve_identity(card(2, GA, PA), ctx)            # card 2's URL has page PA but its correction names PB
            self.assertEqual(i2.resolution_status, "conflicting_identity")
            self.assertIn("CORRECTION_DOES_NOT_MATCH_CARD", [e for e in i2.evidence if e["kind"] == "conflict"][0]["reasons"])

    def test_verified_guide_page_not_in_toc_with_other_evidence_is_conflicting_and_other_guide_not_promoted(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GA, captured=[PB])
            fx.toc(GA, [PB])
            fx.capture(1, "111", GA, PB)
            fx.capture(2, "222", GB, PA)                # probe: PA lives in some other deliverable
            i = pid.resolve_identity(card(1, GA, PA), fx.ctx())
            self.assertEqual(i.resolution_status, "conflicting_identity")
            self.assertIsNone(i.effective_guide_id)
            self.assertEqual(i.card_guide_id, GA)
            probe = [e for e in i.evidence if e["kind"] == "captured_response"][0]
            self.assertEqual((probe["response_loio"], probe["authority"], probe["used_as_effective_guide"]), (GB, "probe_evidence_only", False))

    def test_verified_guide_page_not_in_toc_and_nothing_else_is_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GA, captured=[PB])
            fx.toc(GA, [PB])
            fx.capture(1, "111", GA, PB)
            i = pid.resolve_identity(card(1, GA, PA), fx.ctx())
            self.assertEqual(i.resolution_status, "unresolved")
            self.assertEqual(i.resolution_basis, pid.B_PAGE_NOT_IN_TOC)
            self.assertIsNone(i.effective_guide_id)

    def test_unverified_guide_with_probe_and_no_correction_is_conflicting(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.capture(1, "111", GB, PA)
            i = pid.resolve_identity(card(1, GA, PA), fx.ctx())
            self.assertEqual(i.resolution_status, "conflicting_identity")
            self.assertIsNone(i.effective_guide_id)

    def test_page_in_another_toc_is_a_hint_not_an_identity(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GB, captured=[PA])
            fx.toc(GB, [PA])
            fx.capture(1, "111", GB, PA)
            ctx = fx.ctx()
            # card names unverified guide GA + page PA; GB's TOC contains PA and a response agrees.
            # With a correction absent, the capture makes it a conflict; the identity is still not chosen.
            i = pid.resolve_identity(card(1, GA, PA), ctx)
            self.assertIsNone(i.effective_guide_id)
            self.assertNotEqual(i.resolution_status, "corrected_identity")
            hint = [e for e in i.evidence if e["kind"] == "page_also_in_other_saved_toc"][0]
            self.assertEqual(hint["authority"], "non_authoritative_hint")

    def test_registration_without_matching_saved_response_is_not_verified(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GA, captured=[PA])       # declares verification, but no saved response backs it
            fx.toc(GA, [PA])
            ctx = fx.ctx()
            self.assertFalse(ctx.guide_status(GA)["verified"])
            i = pid.resolve_identity(card(1, GA, PA), ctx)
            self.assertEqual(i.resolution_status, "card_identity_only")

    def test_toc_loio_mismatch_is_not_verified(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fx(td)
            fx.register(GA, captured=[PA])
            fx.capture(1, "111", GA, PA)
            p = Path(td) / "data" / "toc" / f"{GA}.json"
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps(toc_json(GB, [PA])), encoding="utf-8")       # file claims a different loio
            self.assertFalse(fx.ctx().guide_status(GA)["verified"])

    def test_unusable_cards_are_unresolved(self):
        ctx = real_ctx()
        for c in (None, {}, card(1, url=""), card(1, url="https://example.com/docs/x"),
                  card(1, url="https://help.sap.com/docs/P/40374657/" + PA + ".html")):        # a numeric id is not a guide id
            i = pid.resolve_identity(c, ctx)
            self.assertEqual(i.resolution_status, "unresolved")
            self.assertIsNone(i.effective_guide_id)
            self.assertFalse(i.local_page_available)

    def test_source_disagreements_are_listed_not_reconciled(self):
        ctx = real_ctx()
        c = dict(pid.load_cards(ROOT)[0])
        c["source_url"] = c["source_url"].replace("0a6ace53", "0a6ace54")
        i = pid.resolve_identity(c, ctx)
        self.assertTrue(i.disagreements)
        self.assertEqual(i.card_url, c["source_url"])          # the card as given wins the card_url slot; the other source is shown
        fields = {d["field"] for d in i.disagreements}
        self.assertIn("card_url", fields)
        self.assertIn("card_page_id", fields)


# ---------------------------------------------------------------------------------------------- orchestration
def meta_of(unit):
    return {k: unit[k] for k in ("source_id", "title", "category", "source_url", "source_status", "source_url_status",
                                 "has_source_correction", "citation", "retrieval_unit_id", "source_number")}


class FakeBackend:
    distance_metric = "cosine"

    def __init__(self, units):
        self.units = units
        self.calls = []

    def query(self, query, n_results):
        self.calls.append((query, n_results))
        rows = self.units[:n_results]
        return {"ids": [[u["source_id"] for u in rows]], "metadatas": [[meta_of(u) for u in rows]],
                "distances": [[0.1 + 0.05 * k for k in range(len(rows))]]}


def units_first(sid):
    us = pid.load_cards(ROOT)
    first = [u for u in us if u["source_id"] == sid]
    return first + [u for u in us if u["source_id"] != sid]


class OrchestrationTests(unittest.TestCase):
    def route(self, sid, query="q"):
        return pid.route_to_identity(query, FakeBackend(units_first(sid)), real_ctx())

    def test_m2c_17_path_is_resolved_with_local_page(self):
        r = self.route("M2C-17")
        self.assertEqual(r.route_state, "resolved_local_page")
        self.assertEqual(r.selected_source_id, "M2C-17")
        self.assertTrue(r.page_content_available)
        self.assertEqual(r.local_page_path, f"data/sap_help/pages/{G_17}/{P17}.json")
        self.assertIsNone(r.fallback_reason)
        self.assertEqual(r.join_state_7a, "resolved_page")
        self.assertEqual(r.warnings, ())

    def test_other_cards_are_identified_not_local_or_url_only_and_join_agrees(self):
        r = self.route("M2C-07")
        self.assertEqual((r.route_state, r.page_content_available, r.local_page_path), ("identified_not_local", False, None))
        self.assertEqual(r.join_state_7a, "url_only")
        self.assertEqual(r.fallback_reason, pid.B_TOC_ONLY)
        r = self.route("M2C-01")
        self.assertEqual((r.route_state, r.page_content_available), ("card_identity_only", False))
        self.assertEqual(r.identity.card_guide_id, G_A)
        r = self.route("M2C-05")
        self.assertEqual((r.route_state, r.page_content_available), ("corrected_identity", False))
        self.assertEqual(r.identity.effective_guide_id, G_C)

    def test_conflicting_path_is_visible(self):
        r = self.route("M2C-18")
        self.assertEqual(r.route_state, "conflicting_identity")
        self.assertFalse(r.page_content_available)
        self.assertIsNone(r.identity.effective_guide_id)
        self.assertTrue(any("conflicting" in w for w in r.warnings))
        self.assertTrue(any("needs_review" in w for w in r.warnings))

    def test_unresolved_path_and_no_candidate_path(self):
        bad = dict(pid.load_cards(ROOT)[0], source_url="not a url")
        r = pid.route_to_identity("q", FakeBackend([bad]), real_ctx())
        self.assertEqual((r.route_state, r.page_content_available), ("unresolved", False))
        r = pid.route_to_identity("", FakeBackend([]), real_ctx())
        self.assertEqual((r.route_state, r.selected_source_id, r.identity), ("no_card_candidate", None, None))
        self.assertFalse(r.page_content_available)
        self.assertEqual(r.fallback_reason, "EMPTY_QUERY")
        r = pid.route_to_identity("q", FakeBackend(units_first("M2C-07")), real_ctx(), selector=lambda cands: None)
        self.assertEqual(r.route_state, "no_card_candidate")
        self.assertEqual(r.fallback_reason, "SELECTOR_REJECTED_ALL_CANDIDATES")

    def test_route_carries_no_page_text_and_serialises(self):
        r = self.route("M2C-17")
        d = r.to_dict()
        s = json.dumps(d)
        self.assertNotIn('"text"', s)
        page_text = json.loads((ROOT / r.local_page_path).read_text(encoding="utf-8"))["text"]
        self.assertNotIn(page_text[:60], s)
        self.assertLess(len(s), 20000)

    def test_join_and_orchestrator_modules_are_unchanged(self):
        for f in ("scripts/m2c_page_join.py", "scripts/m2c_orchestrator.py", "scripts/m2c_router.py"):
            self.assertEqual(sha(ROOT / f), PINNED[f], f)

    def test_no_llm_network_or_legacy_retriever_is_used(self):
        code = r"""
import json, socket, sys
def _blocked(*a, **k): raise AssertionError("network attempt")
socket.socket.connect = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
sys.path.insert(0, %r)
import m2c_page_identity as p
ctx = p.IdentityContext.from_root(p.ROOT)
cards = p.load_cards(p.ROOT)
class B:
    distance_metric = "cosine"
    def query(self, q, n):
        u = [c for c in cards if c["source_id"] == "M2C-17"][0]
        m = {k: u[k] for k in ("source_id","title","category","source_url","source_status","source_url_status","has_source_correction","citation")}
        return {"ids": [["M2C-17"]], "metadatas": [[m]], "distances": [[0.4]]}
r = p.route_to_identity("q", B(), ctx)
assert r.route_state == "resolved_local_page", r.route_state
p.build_audit(ctx)
bad = sorted(m for m in ("ollama", "rag_core", "rag_chat", "retrieve", "evaluate_retrieval", "create_embeddings", "chromadb",
                         "sentence_transformers", "torch", "numpy", "requests", "sap_resolver", "openai", "anthropic") if m in sys.modules)
print(json.dumps(bad))
""" % (str(SCRIPTS),)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), [])

    def test_identity_module_imports_no_network_llm_or_legacy_code(self):
        banned = {"ollama", "requests", "urllib3", "httpx", "aiohttp", "socket", "rag_core", "rag_chat", "retrieve", "evaluate_retrieval",
                  "create_embeddings", "sap_resolver", "openai", "anthropic", "chromadb", "sentence_transformers", "torch", "numpy"}
        tree = ast.parse((SCRIPTS / "m2c_page_identity.py").read_text(encoding="utf-8"))
        names = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                names.append(n.module or "")
        for name in names:
            self.assertNotIn(name.split(".")[0], banned, name)
            self.assertNotIn(name, {"urllib.request", "urllib.error", "http.client"})


# ---------------------------------------------------------------------------------------------- determinism + artefacts
class DeterminismTests(unittest.TestCase):
    def test_two_resolver_runs_are_byte_identical(self):
        a = pid.render_json(pid.build_audit(pid.IdentityContext.from_root(ROOT)))
        b = pid.render_json(pid.build_audit(pid.IdentityContext.from_root(ROOT)))
        self.assertEqual(a, b)
        self.assertEqual(pid.render_report(json.loads(a)), pid.render_report(json.loads(b)))

    def test_main_twice_writes_identical_files_and_committed_artefacts_match(self):
        with tempfile.TemporaryDirectory() as td:
            outs = []
            for k in (1, 2):
                j, m = Path(td) / f"{k}.json", Path(td) / f"{k}.md"
                self.assertEqual(pid.main(["--out", str(j), "--report", str(m)]), 0)
                outs.append((j.read_bytes(), m.read_bytes()))
            self.assertEqual(outs[0], outs[1])
            self.assertEqual(outs[0][0], (ROOT / "data" / "m2c_page_identity.json").read_bytes())
            self.assertEqual(outs[0][1], (ROOT / "data" / "m2c_page_identity_report.md").read_bytes())

    def test_output_has_no_timestamps_and_no_absolute_paths(self):
        s = (ROOT / "data" / "m2c_page_identity.json").read_text(encoding="utf-8")
        self.assertNotIn("/home/", s)
        self.assertNotIn("/tmp/", s)
        self.assertIsNone(re.search(r"20\d\d-\d\d-\d\dT", s))

    def test_report_lists_all_cards_and_every_problem_card(self):
        t = (ROOT / "data" / "m2c_page_identity_report.md").read_text(encoding="utf-8")
        self.assertIn("| Source | Card title | Card guide | Card page | Effective guide | Effective page | Status | Local content |", t)
        for n in range(1, 30):
            self.assertIn(f"| M2C-{n:02d} |", t)
        for sec in ("## 3. Corrected identities", "## 4. Conflicting identities", "## 5. Unresolved", "## 6. URL-only", "## 7. Locally resolved"):
            self.assertIn(sec, t)
        for sid in ("M2C-05", "M2C-18", "M2C-01", "M2C-13", "M2C-16", "M2C-17"):
            self.assertGreaterEqual(t.count(f"**{sid}**"), 1, sid)

    def test_protected_inputs_are_unchanged(self):
        for f, h in PINNED.items():
            self.assertEqual(sha(ROOT / f), h, f)

    def test_the_resolver_writes_nothing_outside_its_explicit_outputs(self):
        before = {p: sha(p) for p in (ROOT / "data").rglob("*.json") if "m2c_page_identity" not in p.name and "phase7" not in p.name.lower()}
        pid.build_audit(pid.IdentityContext.from_root(ROOT))
        pid.resolve_all(pid.IdentityContext.from_root(ROOT))
        after = {p: sha(p) for p in (ROOT / "data").rglob("*.json") if "m2c_page_identity" not in p.name and "phase7" not in p.name.lower()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
