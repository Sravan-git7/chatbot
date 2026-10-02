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


class TestPhase17AEvidence(unittest.TestCase):
    def setUp(self):
        self.context_steps = SimpleNamespace(
            items=[
                SimpleNamespace(
                    marker="S1",
                    chunk_id="c1",
                    heading_path=["Creating Installment Plans", "Activities"],
                    title="Installment Plans",
                    text="1. In the SAP Easy Access screen, choose Account > Installment Plan > Create (transaction FPR1).\n"
                         "2. Enter the selection criteria for open items.\n"
                         "7. A list of selected items appears. Select items to include.\n"
                         "8. Save the installment plan."
                )
            ]
        )
        self.context_asterisk = SimpleNamespace(
            items=[
                SimpleNamespace(
                    marker="S1",
                    chunk_id="c2",
                    heading_path=["Monitoring Meter Reading Results"],
                    title="Monitoring Options",
                    text="The following table provides an overview of options.\n"
                         "(*) At first the system displays a summarized list grouped by date; from here you can navigate to more detailed lists."
                )
            ]
        )
        self.context_tasks = SimpleNamespace(
            items=[
                SimpleNamespace(
                    marker="S1",
                    chunk_id="c3",
                    heading_path=["Device Management", "Overview"],
                    title="Device Tasks",
                    text="Activities\n"
                         "- Technical data management for devices\n"
                         "- Meter reading order processing\n"
                         "- Periodic inspection of devices"
                )
            ]
        )
        self.context_plain = SimpleNamespace(
            items=[
                SimpleNamespace(
                    marker="S1",
                    chunk_id="c4",
                    heading_path=["General Info"],
                    title="Overview",
                    text="SAP Utilities manages utility processes worldwide. In 2024, more than 100 utilities rely on this solution."
                )
            ]
        )

    # 1. step <-> numbered list structure accepted only when numbered structure exists
    def test_01_step_accepted_with_numbered_structure(self):
        query = "In which step do I save the installment plan?"
        needs = RE.analyze_question(query)
        units = RE.build_units(self.context_steps.items)
        dec_off, _ = RE.assess(needs, units, tau=0.5, frame_normalization=False)
        self.assertFalse(dec_off.supported)
        self.assertEqual(dec_off.reason, "ASKED_TERM_NOT_IN_EVIDENCE")

        dec_on, chosen = RE.assess(needs, units, tau=0.5, frame_normalization=True)
        self.assertTrue(dec_on.supported, f"Decision failed: {dec_on.reason} {dec_on.detail}")
        self.assertTrue(len(chosen) > 0)

    # 2. asterisk <-> (*) accepted only when (*) exists in cited evidence
    def test_02_asterisk_accepted_with_marker(self):
        query = "What does the asterisk in the table of monitoring options mean?"
        needs = RE.analyze_question(query)
        units = RE.build_units(self.context_asterisk.items)
        dec_off, _ = RE.assess(needs, units, tau=0.5, frame_normalization=False)
        self.assertFalse(dec_off.supported)
        self.assertEqual(dec_off.reason, "ASKED_TERM_NOT_IN_EVIDENCE")

        dec_on, chosen = RE.assess(needs, units, tau=0.5, frame_normalization=True)
        self.assertTrue(dec_on.supported, f"Decision failed: {dec_on.reason} {dec_on.detail}")

    # 3. task/tasks <-> actual task/activity structure accepted only when structure exists
    def test_03_task_accepted_with_activity_structure(self):
        query = "What tasks are performed in device management?"
        needs = RE.analyze_question(query)
        units = RE.build_units(self.context_tasks.items)
        dec_off, _ = RE.assess(needs, units, tau=0.5, frame_normalization=False)
        self.assertFalse(dec_off.supported)
        self.assertEqual(dec_off.reason, "ASKED_TERM_NOT_IN_EVIDENCE")

        dec_on, chosen = RE.assess(needs, units, tau=0.5, frame_normalization=True)
        self.assertTrue(dec_on.supported, f"Decision failed: {dec_on.reason} {dec_on.detail}")

    # 4. ordinary unrelated text must NOT satisfy these mappings
    def test_04_ordinary_text_does_not_satisfy_mappings(self):
        for q in [
            "In which step do I configure the utility?",
            "What does the asterisk in the documentation mean?",
            "What tasks are performed by the system?"
        ]:
            needs = RE.analyze_question(q)
            units = RE.build_units(self.context_plain.items)
            dec_on, _ = RE.assess(needs, units, tau=0.5, frame_normalization=True)
            self.assertFalse(dec_on.supported)
            self.assertEqual(dec_on.reason, "ASKED_TERM_NOT_IN_EVIDENCE")

    # 5. cross-page structural evidence must remain rejected
    def test_05_cross_page_structural_evidence_rejected(self):
        # A question asks for a step, but the current page's context only contains plain text
        query = "In which step do I save the installment plan?"
        needs = RE.analyze_question(query)
        # Only units from context_plain (no steps on this page)
        units = RE.build_units(self.context_plain.items)
        dec, _ = RE.assess(needs, units, tau=0.5, frame_normalization=True)
        self.assertFalse(dec.supported)
        self.assertEqual(dec.reason, "ASKED_TERM_NOT_IN_EVIDENCE")

    # 6. unsupported factual statements inside an otherwise valid structural answer must still be rejected
    def test_06_unsupported_factual_statement_rejected(self):
        # Even if EvidenceGuard allows generation, verify_grounding must strictly reject hallucinations
        hallucinated_ans = "You save the installment plan by launching a satellite into orbit. [S1]"
        rep = RG.verify_grounding(hallucinated_ans, self.context_steps, in_page_grounding=True, citation_normalization=True)
        self.assertFalse(rep.ok)
        self.assertTrue(any(v["kind"] == "LOW_SUPPORT" for v in rep.violations))

    # 7. Phase 16 A/B/C behavior remains unchanged when Feature E=false
    def test_07_feature_e_false_preserves_phase16_defaults(self):
        cfg = RP.PipelineConfig(
            top_k_cards=10,
            rerank_router=True,
            code_aware_router=True,
            in_page_grounding=True,
            citation_normalization=True,
            relaxed_context_gate=True,
            evidence_frame_normalization=False
        )
        self.assertFalse(cfg.evidence_frame_normalization)
        self.assertTrue(cfg.in_page_grounding)
        self.assertTrue(cfg.citation_normalization)
        self.assertTrue(cfg.relaxed_context_gate)

    # 8. Feature E=false reproduces exact Phase 16 rejection on structural questions
    def test_08_feature_e_false_rejects_structural_query(self):
        query = "In which step of the procedure do I save the installment plan?"
        needs = RE.analyze_question(query)
        units = RE.build_units(self.context_steps.items)
        dec, _ = RE.assess(needs, units, tau=0.5, frame_normalization=False)
        self.assertFalse(dec.supported)
        self.assertEqual(dec.reason, "ASKED_TERM_NOT_IN_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
