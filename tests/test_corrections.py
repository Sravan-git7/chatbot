"""Per-topic card->guide corrections (sap_resolver/corrections.py)."""
import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sap_resolver.corrections import apply_corrections, load_corrections  # noqa: E402

CARD_G, RES_G, PAGE = "a" * 32, "b" * 32, "c" * 32


def _topic(tid=5):
    return {"topic_id": tid, "title": "T", "category": "C", "pdf_file": "x.pdf", "product": "SAP_S4HANA_ON-PREMISE",
            "guide_id": CARD_G, "page_id": PAGE, "url_as_given": f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{CARD_G}/{PAGE}.html",
            "canonical_url": f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{CARD_G}/{PAGE}.html"}


def _corr(**kw):
    c = {"topic_id": 5, "card_guide_id": CARD_G, "card_page_id": PAGE, "resolved_guide_id": RES_G, "reason": "r",
         "evidence": [{"kind": "user_reported_browser", "observation": "o"}]}
    c.update(kw)
    return c


class ApplyTests(unittest.TestCase):
    def test_applies_and_keeps_card_values(self):
        topics = [_topic(5), _topic(6)]
        orig = copy.deepcopy(topics)
        out, applied, rejected = apply_corrections(topics, [_corr()], ROOT)
        self.assertEqual(rejected, [])
        self.assertEqual(topics, orig)                                   # input untouched
        self.assertEqual(out[0]["guide_id"], RES_G)
        self.assertEqual(out[0]["card_guide_id"], CARD_G)
        self.assertEqual(out[0]["card_url"], orig[0]["url_as_given"])    # original card URL kept
        self.assertIn(f"/{RES_G}/{PAGE}.html", out[0]["canonical_url"])
        self.assertEqual(out[0]["page_id"], PAGE)
        self.assertEqual(out[1], orig[1])                                # other topics unchanged
        self.assertEqual(len(applied), 1)

    def test_rejections(self):
        bad = {
            "card guide differs": _corr(card_guide_id="d" * 32),
            "card page differs": _corr(card_page_id="d" * 32),
            "no evidence": _corr(evidence=[]),
            "unknown evidence kind": _corr(evidence=[{"kind": "hunch"}]),
            "same guide": _corr(resolved_guide_id=CARD_G),
            "not hex": _corr(resolved_guide_id="xyz"),
            "unknown topic": _corr(topic_id=99),
        }
        for why, c in bad.items():
            out, applied, rejected = apply_corrections([_topic()], [c], ROOT)
            self.assertEqual((applied, len(rejected)), ([], 1), why)
            self.assertEqual(out[0]["guide_id"], CARD_G, why)
        _, applied, rejected = apply_corrections([_topic()], [_corr(), _corr()], ROOT)
        self.assertEqual((len(applied), len(rejected)), (1, 1))            # duplicate for one topic

    def test_saved_response_evidence_is_machine_checked(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            def resp(loio, page):
                return {"data": {"deliverable": {"loio": loio}, "currentPage": {"loio": page}}}
            ev = {"kind": "saved_response", "file": "r.json"}
            (tmp / "r.json").write_text(json.dumps(resp(RES_G, PAGE)), encoding="utf-8")
            _, applied, rejected = apply_corrections([_topic()], [_corr(evidence=[ev])], tmp)
            self.assertEqual((len(applied), rejected), (1, []))
            (tmp / "r.json").write_text(json.dumps(resp(CARD_G, PAGE)), encoding="utf-8")       # response says card guide
            _, applied, rejected = apply_corrections([_topic()], [_corr(evidence=[ev])], tmp)
            self.assertEqual((applied, len(rejected)), ([], 1))
            (tmp / "r.json").write_text(json.dumps(resp(RES_G, "e" * 32)), encoding="utf-8")    # other page
            _, applied, rejected = apply_corrections([_topic()], [_corr(evidence=[ev])], tmp)
            self.assertEqual((applied, len(rejected)), ([], 1))
            (tmp / "r.json").unlink()                                                            # file absent: not a failure
            _, applied, _ = apply_corrections([_topic()], [_corr(evidence=[ev])], tmp)
            self.assertEqual(len(applied), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_repo_corrections_file_is_valid_and_only_topic_5(self):
        cs = load_corrections(ROOT / "data" / "topic_corrections.json")
        self.assertEqual([c["topic_id"] for c in cs], [5])
        c = cs[0]
        self.assertEqual((c["card_guide_id"][:8], c["resolved_guide_id"][:8]), ("021b182b", "2ac7fe29"))
        self.assertTrue(any(e["kind"] == "user_reported_browser" and e["machine_verified"] is False for e in c["evidence"]))


def _cli():
    spec = importlib.util.spec_from_file_location("build_corpus_cli2", ROOT / "scripts" / "build_corpus.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


@unittest.skipUnless((ROOT / "data" / "toc" / "2ac7fe29a0c94cdd88fb80c2cb9f7758.json").is_file(), "needs saved TOC of guide 2ac7fe29")
class RealCorrectionTests(unittest.TestCase):
    def _manifest(self, corrections_file=None):
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp, True)
        args = ["--offline", "--out-dir", str(tmp / "o")]
        if corrections_file:
            args += ["--corrections-file", str(corrections_file)]
        _cli().main(args)
        return json.loads((tmp / "o" / "final_corpus_manifest.json").read_text(encoding="utf-8"))

    def test_topic5_resolves_in_guide_c_with_evidence_and_guide_a_is_not_touched(self):
        m = self._manifest()
        t5 = next(t for t in m["topics"] if t["topic_id"] == 5)
        self.assertEqual((t5["resolution_status"], t5["guide_id"][:8], t5["card_guide_id"][:8]), ("RESOLVED", "2ac7fe29", "021b182b"))
        self.assertTrue(t5["correction"]["evidence"])
        self.assertEqual([c["topic_id"] for c in m["topic_corrections"]], [5])
        for tid in (1, 13, 16):                                          # nothing inferred for the other Guide A topics
            t = next(x for x in m["topics"] if x["topic_id"] == tid)
            self.assertEqual((t["resolution_status"], t["guide_id"][:8]), ("UNRESOLVED_GUIDE", "021b182b"))
        a = next(g for g in m["guides"] if g["guide_id"].startswith("021b182b"))
        self.assertEqual((a["status"], a["topic_ids"]), ("unresolved", [1, 13, 16]))

    def test_a_correction_cannot_force_resolution_when_page_not_in_target_toc(self):
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp, True)
        man = json.loads((ROOT / "data" / "topic_manifest.json").read_text(encoding="utf-8"))
        t18 = next(t for t in man["topics"] if t["topic_id"] == 18)
        f = tmp / "c.json"
        f.write_text(json.dumps({"corrections": [{
            "topic_id": 18, "card_guide_id": t18["guide_id"], "card_page_id": t18["page_id"],
            "resolved_guide_id": "2ac7fe29a0c94cdd88fb80c2cb9f7758", "reason": "test",
            "evidence": [{"kind": "user_reported_browser", "observation": "x"}]}]}), encoding="utf-8")
        m = self._manifest(f)
        t = next(t for t in m["topics"] if t["topic_id"] == 18)
        self.assertEqual((t["resolution_status"], t["resolution_reason"]), ("UNRESOLVED_PAGE", "PAGE_NOT_IN_TOC"))


if __name__ == "__main__":
    unittest.main()
