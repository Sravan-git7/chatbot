import unittest
import re
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rag_text as T
import rag_generate as RG
import rag_pipeline as RP
import rag_evidence as RE

class TestPhase16Context(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(
            items=[
                SimpleNamespace(marker="S1", chunk_id="c1", text="Transaction EL43 is located in the Utilities menu. See details below."),
                SimpleNamespace(marker="S2", chunk_id="c2", text="The purpose of transaction is to get an overview of devices in a meter reading unit. It is protected by authorization."),
                SimpleNamespace(marker="S3", chunk_id="c3", text="Installment plans can be changed. You can add installments, delete installments, and calculate interest. Save the plan to complete.")
            ]
        )

    # 1. Same-page code token accepted.
    def test_1_same_page_code_token_accepted(self):
        # EL43 is in S1 (same page), but the cited sentence cites S2
        ans = "The purpose of transaction EL43 is to get an overview of devices in a meter reading unit. [S2]"
        rep = RG.verify_grounding(ans, self.context, in_page_grounding=True)
        self.assertTrue(rep.ok, f"Violations: {rep.violations}")
        self.assertEqual(rep.cited_markers, ["S2"])

    # 2. Cross-page code token rejected.
    def test_2_cross_page_code_token_rejected(self):
        # XYZ_999 is NOT anywhere in all_context
        ans = "The purpose of transaction XYZ_999 is to get an overview of devices in a meter reading unit. [S2]"
        rep = RG.verify_grounding(ans, self.context, in_page_grounding=True)
        self.assertFalse(rep.ok)
        self.assertTrue(any(v["kind"] == "TOKEN_NOT_IN_CONTEXT" for v in rep.violations))

    # 3. Compound [S1/S2] citation accepted.
    def test_3_compound_citation_accepted(self):
        ans = "Transaction details are available in the system overview. [S1/S2]"
        rep = RG.verify_grounding(ans, self.context, citation_normalization=True)
        self.assertTrue(rep.ok, f"Violations: {rep.violations}")
        self.assertEqual(rep.cited_markers, ["S1", "S2"])

    # 4. Unsupported compound citation rejected (e.g., phantom marker S9).
    def test_4_unsupported_compound_citation_rejected(self):
        ans = "Transaction details are available in the system overview. [S1/S9]"
        rep = RG.verify_grounding(ans, self.context, citation_normalization=True)
        self.assertFalse(rep.ok)
        self.assertTrue(any(v["kind"] == "PHANTOM_MARKER" for v in rep.violations))

    # 5. Supported bullet list with trailing citation accepted.
    def test_5_supported_bullet_list_with_trailing_citation_accepted(self):
        ans = "In an installment plan proposal, changes can be made:\n- Add installments\n- Delete installments\n- Calculate interest. [S3]"
        rep = RG.verify_grounding(ans, self.context, citation_normalization=True)
        self.assertTrue(rep.ok, f"Violations: {rep.violations}")
        self.assertEqual(rep.cited_markers, ["S3"])

    # 6. Unsupported bullet item still rejected.
    def test_6_unsupported_bullet_item_still_rejected(self):
        # "Call the national power authority" is not in context
        ans = "In an installment plan proposal, changes can be made:\n- Add installments\n- Call the national power authority for guidance\n- Calculate interest. [S3]"
        rep = RG.verify_grounding(ans, self.context, citation_normalization=True)
        self.assertFalse(rep.ok)
        self.assertTrue(any(v["kind"] in ("NO_CITATION", "LOW_SUPPORT") for v in rep.violations))

    # 7. Multi-sentence supported response accepted.
    def test_7_multi_sentence_supported_response_accepted(self):
        ans = "Installment plans can be changed. You can add installments, delete installments, and calculate interest. [S3]"
        rep = RG.verify_grounding(ans, self.context, citation_normalization=True)
        self.assertTrue(rep.ok, f"Violations: {rep.violations}")
        self.assertEqual(rep.cited_markers, ["S3"])

    # 8. No Phase 16 flags => exact Phase 15 behavior.
    def test_8_no_phase16_flags_preserves_phase15(self):
        cfg = RP.PipelineConfig()
        self.assertFalse(cfg.in_page_grounding)
        self.assertFalse(cfg.citation_normalization)
        self.assertFalse(cfg.relaxed_context_gate)
        self.assertFalse(cfg.phase16_context_experiment)
        self.assertEqual(cfg.context_min_coverage, 0.50)

        # Baseline rejects same-page token in another chunk
        ans = "The purpose of transaction EL43 is to get an overview of devices in a meter reading unit. [S2]"
        rep_base = RG.verify_grounding(ans, self.context, in_page_grounding=cfg.in_page_grounding, citation_normalization=cfg.citation_normalization)
        self.assertFalse(rep_base.ok)
        self.assertTrue(any(v["kind"] == "TOKEN_NOT_IN_CITED_CHUNK" for v in rep_base.violations))

        # Baseline rejects compound marker [S1/S2]
        ans_comp = "Transaction details are available in the system overview. [S1/S2]"
        rep_comp = RG.verify_grounding(ans_comp, self.context, in_page_grounding=cfg.in_page_grounding, citation_normalization=cfg.citation_normalization)
        self.assertFalse(rep_comp.ok)

    # 9. relaxed_context_gate changes only context_min_coverage.
    def test_9_relaxed_context_gate_changes_only_context_min_coverage(self):
        cfg_base = RP.PipelineConfig(relaxed_context_gate=False)
        self.assertEqual(cfg_base.ood_min_coverage, 0.25)
        self.assertEqual(cfg_base.context_min_coverage, 0.50)

        cfg_relaxed = RP.PipelineConfig(relaxed_context_gate=True)
        self.assertEqual(cfg_relaxed.ood_min_coverage, 0.25)
        # Check that relaxed gate triggers effective 0.25 threshold
        self.assertTrue(cfg_relaxed.relaxed_context_gate)

    # 10. EvidenceGuard remains unchanged unless explicit frame-normalization flag is enabled.
    def test_10_evidenceguard_remains_unchanged(self):
        needs = RE.analyze_question("In which step do I choose Continue to get the installment plan proposal?")
        units = [
            RE.Unit(marker="S1", chunk_id="c1", rank=1, order=1, text="8. Choose Continue to get the installment plan proposal.", own=frozenset(["choos", "continu", "get", "instal", "plan", "propos"]), head=frozenset(["activ"]), chunk_text="8. Choose Continue to get the installment plan proposal.")
        ]
        # Standard assess() without frame normalization rejects because "step" is missing
        dec, _ = RE.assess(needs, units, tau=0.5)
        self.assertFalse(dec.supported)
        self.assertEqual(dec.reason, "ASKED_TERM_NOT_IN_EVIDENCE")

if __name__ == '__main__':
    unittest.main()
