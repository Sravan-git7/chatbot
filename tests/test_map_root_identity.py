"""Regression tests for map-root-to-landing-page identity resolution."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import m2c_page_identity as pid
from sap_resolver.corrections import apply_corrections

# Test constants
G_CARD = "021b182b0c47416c8fafed67ebfd78a9"  # unverified original card guide
P_MAP_ROOT = "0a6ace53118d4308e10000000a174cb4"  # map root LOIO
G_VERIFIED = "e52c8ee6197147ec97dfc2eb8c46a3ad"  # verified "Master Data" guide
P_LANDING = "e369ce53118d4308e10000000a174cb4"   # declared landing page in TOC


def _make_context(corrections_list, captures_list=()):
    """Build an IdentityContext using repo files but injecting synthetic corrections and captures."""
    ctx = pid.IdentityContext.from_root(ROOT)
    corrs = {int(c["topic_id"]): c for c in corrections_list}
    caps = list(ctx.captures)
    for c in captures_list:
        caps.append(pid.CaptureInfo(
            file=c["file"],
            numeric_deliverable_id=c.get("numeric_id", "40374631"),
            response_loio=c["response_loio"],
            current_page_id=c["current_page_id"],
            current_page_title="Page Title",
            deliverable_title="Master Data",
            toc_nodes_in_response=81,
        ))
    return pid.IdentityContext(
        root=ctx.root,
        topic_manifest=ctx.topic_manifest,
        source_manifest=ctx.source_manifest,
        corrections=corrs,
        registrations=ctx.registrations,
        registry=ctx.registry,
        tocs=ctx.tocs,
        captures=caps,
        page_index=ctx.page_index,
        input_files=ctx.input_files,
        stale_final_manifest=ctx.stale_final_manifest,
    )


class MapRootIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = {c["source_id"]: c for c in pid.load_cards(ROOT)}

    def test_valid_map_root_to_landing_page_mapping(self):
        """A verified map-root correction resolves to the guide and landing page."""
        corr = {
            "topic_id": 1,
            "card_guide_id": G_CARD,
            "card_page_id": P_MAP_ROOT,
            "card_url": f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G_CARD}/{P_MAP_ROOT}.html",
            "resolved_guide_id": G_VERIFIED,
            "resolved_page_id": P_LANDING,
            "reason": "SAP map-root resolves to landing page of Master Data guide",
            "evidence": [
                {
                    "kind": "saved_response",
                    "file": "captured_responses/m2c01_test.json",
                }
            ],
        }
        cap = {
            "file": "captured_responses/m2c01_test.json",
            "response_loio": G_VERIFIED,
            "current_page_id": P_LANDING,
        }
        ctx = _make_context([corr], [cap])
        card = self.cards["M2C-01"]
        ident = pid.resolve_identity(card, ctx)

        self.assertEqual(ident.resolution_status, pid.CORRECTED_IDENTITY)
        self.assertEqual(ident.resolution_basis, pid.B_CORRECTION)
        self.assertEqual(ident.card_guide_id, G_CARD)
        self.assertEqual(ident.card_page_id, P_MAP_ROOT)
        self.assertEqual(ident.effective_guide_id, G_VERIFIED)
        self.assertEqual(ident.effective_page_id, P_LANDING)

        corr_ev = next(e for e in ident.evidence if e["kind"] == "correction")
        self.assertTrue(corr_ev["card_page_is_map_root"])
        self.assertTrue(corr_ev["resolved_page_is_landing_page"])
        self.assertTrue(corr_ev["machine_checked_saved_response_passed"])

    def test_rejection_if_guide_not_verified(self):
        """A map-root correction targeting an unverified guide is rejected."""
        corr = {
            "topic_id": 1,
            "card_guide_id": G_CARD,
            "card_page_id": P_MAP_ROOT,
            "card_url": f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G_CARD}/{P_MAP_ROOT}.html",
            "resolved_guide_id": "11111111111111111111111111111111",  # unverified guide
            "resolved_page_id": P_LANDING,
            "reason": "Bad guide",
            "evidence": [{"kind": "saved_response", "file": "test.json"}],
        }
        cap = {"file": "test.json", "response_loio": "11111111111111111111111111111111", "current_page_id": P_LANDING}
        ctx = _make_context([corr], [cap])
        card = self.cards["M2C-01"]
        ident = pid.resolve_identity(card, ctx)

        self.assertEqual(ident.resolution_status, pid.CONFLICTING_IDENTITY)
        self.assertEqual(ident.resolution_basis, pid.B_CORRECTION_REJECTED)
        conflict = next(e for e in ident.evidence if e["kind"] == "conflict")
        self.assertIn("CORRECTED_GUIDE_NOT_VERIFIED", conflict["reasons"])

    def test_rejection_if_card_page_not_map_root(self):
        """A correction with resolved_page_id is rejected if card_page_id is not the guide's map root."""
        corr = {
            "topic_id": 1,
            "card_guide_id": G_CARD,
            "card_page_id": "99999999999999999999999999999999",  # not the map root
            "card_url": f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G_CARD}/99999999999999999999999999999999.html",
            "resolved_guide_id": G_VERIFIED,
            "resolved_page_id": P_LANDING,
            "reason": "Wrong card page",
            "evidence": [{"kind": "saved_response", "file": "test.json"}],
        }
        cap = {"file": "test.json", "response_loio": G_VERIFIED, "current_page_id": P_LANDING}
        ctx = _make_context([corr], [cap])
        # Card with mismatched page ID
        card = dict(self.cards["M2C-01"], source_url=f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G_CARD}/99999999999999999999999999999999.html")
        ident = pid.resolve_identity(card, ctx)

        self.assertEqual(ident.resolution_status, pid.CONFLICTING_IDENTITY)
        conflict = next(e for e in ident.evidence if e["kind"] == "conflict")
        self.assertIn("CARD_PAGE_NOT_MAP_ROOT_OF_CORRECTED_GUIDE", conflict["reasons"])

    def test_rejection_if_resolved_page_not_in_toc(self):
        """A correction is rejected if the landing page is not in the guide's TOC."""
        corr = {
            "topic_id": 1,
            "card_guide_id": G_CARD,
            "card_page_id": P_MAP_ROOT,
            "card_url": f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G_CARD}/{P_MAP_ROOT}.html",
            "resolved_guide_id": G_VERIFIED,
            "resolved_page_id": "88888888888888888888888888888888",  # not in TOC
            "reason": "Wrong landing page",
            "evidence": [{"kind": "saved_response", "file": "test.json"}],
        }
        cap = {"file": "test.json", "response_loio": G_VERIFIED, "current_page_id": "88888888888888888888888888888888"}
        ctx = _make_context([corr], [cap])
        card = self.cards["M2C-01"]
        ident = pid.resolve_identity(card, ctx)

        self.assertEqual(ident.resolution_status, pid.CONFLICTING_IDENTITY)
        conflict = next(e for e in ident.evidence if e["kind"] == "conflict")
        self.assertIn("PAGE_NOT_IN_CORRECTED_GUIDE_TOC", conflict["reasons"])

    def test_rejection_if_resolved_page_not_landing_page(self):
        """A correction is rejected if resolved_page_id is a TOC node but NOT the declared landing page."""
        # Page 0bfcc5536a51204be10000000a174cb4 is in master_data.json TOC (topic 17) but is not the landing page
        other_node = "0bfcc5536a51204be10000000a174cb4"
        corr = {
            "topic_id": 1,
            "card_guide_id": G_CARD,
            "card_page_id": P_MAP_ROOT,
            "card_url": f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G_CARD}/{P_MAP_ROOT}.html",
            "resolved_guide_id": G_VERIFIED,
            "resolved_page_id": other_node,
            "reason": "Not the landing page",
            "evidence": [{"kind": "saved_response", "file": "test.json"}],
        }
        cap = {"file": "test.json", "response_loio": G_VERIFIED, "current_page_id": other_node}
        ctx = _make_context([corr], [cap])
        card = self.cards["M2C-01"]
        ident = pid.resolve_identity(card, ctx)

        self.assertEqual(ident.resolution_status, pid.CONFLICTING_IDENTITY)
        conflict = next(e for e in ident.evidence if e["kind"] == "conflict")
        self.assertIn("RESOLVED_PAGE_NOT_LANDING_PAGE_OF_CORRECTED_GUIDE", conflict["reasons"])

    def test_m2c18_remains_protected_conflicting_identity(self):
        """M2C-18 remains conflicting_identity without authoritative evidence."""
        ctx = pid.IdentityContext.from_root(ROOT)
        card = self.cards["M2C-18"]
        ident = pid.resolve_identity(card, ctx)

        self.assertEqual(ident.resolution_status, pid.CONFLICTING_IDENTITY)
        self.assertIsNone(ident.effective_guide_id)
        self.assertIsNone(ident.effective_page_id)

    def test_m2c05_standard_correction_unaffected(self):
        """M2C-05 standard page-preserving correction continues to work without regression."""
        ctx = pid.IdentityContext.from_root(ROOT)
        card = self.cards["M2C-05"]
        ident = pid.resolve_identity(card, ctx)

        self.assertEqual(ident.resolution_status, pid.CORRECTED_IDENTITY)
        self.assertEqual(ident.effective_guide_id, "2ac7fe29a0c94cdd88fb80c2cb9f7758")
        self.assertEqual(ident.effective_page_id, "8990d0533f8e4308e10000000a174cb4")
        self.assertEqual(ident.card_guide_id, G_CARD)
        self.assertEqual(ident.card_page_id, "8990d0533f8e4308e10000000a174cb4")

    def test_apply_corrections_with_resolved_page_id(self):
        """sap_resolver apply_corrections correctly accepts resolved_page_id."""
        topics = [
            {
                "topic_id": 1,
                "title": "Utilities Master Data",
                "category": "Master Data",
                "pdf_file": "01_Utilities_Master_Data.pdf",
                "product": "SAP_S4HANA_ON-PREMISE",
                "guide_id": G_CARD,
                "page_id": P_MAP_ROOT,
                "url_as_given": f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G_CARD}/{P_MAP_ROOT}.html",
                "canonical_url": f"https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{G_CARD}/{P_MAP_ROOT}.html",
            }
        ]
        corr = {
            "topic_id": 1,
            "card_guide_id": G_CARD,
            "card_page_id": P_MAP_ROOT,
            "resolved_guide_id": G_VERIFIED,
            "resolved_page_id": P_LANDING,
            "reason": "Map root to landing page",
            "evidence": [{"kind": "user_reported_browser", "observation": "redirects to landing page"}],
        }
        out, applied, rejected = apply_corrections(topics, [corr], ROOT)
        self.assertEqual(rejected, [])
        self.assertEqual(len(applied), 1)
        self.assertEqual(out[0]["guide_id"], G_VERIFIED)
        self.assertEqual(out[0]["page_id"], P_LANDING)
        self.assertEqual(out[0]["card_guide_id"], G_CARD)
        self.assertIn(f"/{G_VERIFIED}/{P_LANDING}.html", out[0]["canonical_url"])


if __name__ == "__main__":
    unittest.main()
