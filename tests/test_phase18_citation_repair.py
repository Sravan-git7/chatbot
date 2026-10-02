#!/usr/bin/env python3
"""Phase 18 unit tests for E2 (deterministic in-page citation repair).

Pure-function tests: fakes stand in for ContextBlock items. The repair must never change answer
content, never cite a chunk that was not supplied, and must be a no-op when attribution is already correct.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_citation_repair as CRC  # noqa: E402


def ctx(*pairs):
    """pairs: (marker, chunk text)"""
    return SimpleNamespace(items=[SimpleNamespace(marker=m, text=t) for m, t in pairs])


class TestNoOpCases(unittest.TestCase):
    def test_verbatim_in_cited_chunk_is_untouched(self):
        c = ctx(("S1", "Equipment records are created automatically during goods receipt."))
        answer = "Equipment records are created automatically during goods receipt. [S1]"
        text, log = CRC.repair_citations(answer, c)
        self.assertEqual(text, answer)
        self.assertFalse(log["changed"])

    def test_empty_answer(self):
        c = ctx(("S1", "some text here"))
        text, log = CRC.repair_citations("", c)
        self.assertEqual(text, "")
        self.assertFalse(log["changed"])

    def test_line_without_valid_marker_untouched(self):
        c = ctx(("S1", "some text here"))
        answer = "A sentence with no marker at all."
        text, log = CRC.repair_citations(answer, c)
        self.assertEqual(text, answer)
        self.assertFalse(log["changed"])

    def test_marker_only_line_untouched(self):
        c = ctx(("S1", "some text here"))
        answer = "[S1]"
        text, log = CRC.repair_citations(answer, c)
        self.assertEqual(text, answer)
        self.assertFalse(log["changed"])

    def test_ambiguous_verbatim_location_is_not_repointed(self):
        t = "The device is identified by a unique material and serial number combination."
        c = ctx(("S1", "unrelated first chunk"), ("S2", t), ("S3", "duplicate " + t))
        answer = f"{t} [S1]"
        text, log = CRC.repair_citations(answer, c)
        # Rule A must NOT replace the citation (two candidate locations) - the original citation is
        # never dropped. Rule B may still ADD one supporting chunk (S2, first in document order).
        self.assertEqual(text, f"{t} [S1/S2]")
        self.assertEqual(log["lines"][0]["rule"], "B_support")
        self.assertEqual(log["lines"][0]["from"], ["S1"])
        self.assertEqual(log["lines"][0]["to"], ["S1", "S2"])

    def test_rule_b_requires_strict_improvement(self):
        # best uncited chunk supports the sentence but by less than +0.10 over the cited support
        c = ctx(("S1", "The clearing of original items uses a priority setting for payments."),
                ("S2", "A priority setting for payments applies to the clearing of original items."))
        answer = "The clearing of original items uses a priority setting for payments. [S1]"
        # cited S1 already fully supports the sentence -> no improvement possible
        text, log = CRC.repair_citations(answer, c)
        self.assertEqual(text, answer)
        self.assertFalse(log["changed"])


class TestRuleA(unittest.TestCase):
    def test_verbatim_repoint_to_unique_chunk(self):
        t = "Equipment records are created automatically during goods receipt."
        c = ctx(("S1", "Device Management covers technical data and installations."),
                ("S2", "The device flow lists functions: Procurement, Delivery, Outward Movement."),
                ("S3", "Equipment records are created automatically during goods receipt . Therefore, functions from the PM application component are used."))
        answer = f"{t} [S1]"
        text, log = CRC.repair_citations(answer, c)
        self.assertEqual(text, f"{t} [S3]")
        self.assertTrue(log["changed"])
        self.assertEqual(log["lines"][0]["rule"], "A_verbatim")
        self.assertEqual(log["lines"][0]["from"], ["S1"])
        self.assertEqual(log["lines"][0]["to"], ["S3"])

    def test_punctuation_space_before_period_does_not_defeat_match(self):
        # page text has 'receipt .' (space before the period), the answer writes 'receipt.'
        t = "Equipment records are created automatically during goods receipt."
        c = ctx(("S1", "other chunk"), ("S2", "Intro line. Equipment records are created automatically during goods receipt . End."))
        answer = f"{t} [S1]"
        text, log = CRC.repair_citations(answer, c)
        self.assertEqual(text, f"{t} [S2]")

    def test_multiple_lines_repaired_independently(self):
        t1 = "First fact stated in the third chunk."
        t2 = "Second fact stated in the third chunk."
        c = ctx(("S1", "alpha beta gamma"), ("S2", "delta epsilon"), ("S3", t1 + " " + t2))
        answer = f"{t1} [S1]\n{t2} [S2]"
        text, log = CRC.repair_citations(answer, c)
        self.assertEqual(text, f"{t1} [S3]\n{t2} [S3]")
        self.assertEqual(len(log["lines"]), 2)


class TestRuleB(unittest.TestCase):
    def test_support_improving_marker_added(self):
        # sentence is NOT verbatim in any chunk; S2 supports it strongly, S1 weakly
        c = ctx(("S1", "The monitoring lists show meter reading results with various options and dates."),
                ("S2", "You can use the pushbutton to carry out quantity determination in the monitoring lists."))
        answer = "You can carry out quantity determination using the pushbutton in the monitoring lists. [S1]"
        text, log = CRC.repair_citations(answer, c)
        self.assertIn("[S1/S2]", text)
        self.assertTrue(log["changed"])
        self.assertEqual(log["lines"][0]["rule"], "B_support")
        self.assertEqual(log["lines"][0]["from"], ["S1"])
        self.assertEqual(log["lines"][0]["to"], ["S1", "S2"])

    def test_rule_b_respects_minimum_support(self):
        # no uncited chunk reaches 0.6 support -> no change
        c = ctx(("S1", "completely different vocabulary one"),
                ("S2", "completely different vocabulary two"))
        answer = "The installment plan proposal allows changes before saving. [S1]"
        text, log = CRC.repair_citations(answer, c)
        self.assertEqual(text, answer)
        self.assertFalse(log["changed"])


class TestCompoundMarkers(unittest.TestCase):
    def test_compound_citation_parsed_and_extended(self):
        t = "A sentence grounded in the second chunk."
        c = ctx(("S1", "first chunk words unrelated"),
                ("S2", t + " more second chunk words."),
                ("S3", "third chunk: " + t))
        answer = f"{t} [S1/S3]"
        # S3 already contains it verbatim -> attributed correctly, no change
        text, log = CRC.repair_citations(answer, c, citation_normalization=True)
        self.assertEqual(text, answer)
        self.assertFalse(log["changed"])

    def test_compound_citation_repointed_when_wrong(self):
        t = "A sentence that lives only in the first chunk."
        c = ctx(("S1", "lead-in. " + t), ("S2", "unrelated second"), ("S3", "unrelated third"))
        answer = f"{t} [S2/S3]"
        text, log = CRC.repair_citations(answer, c, citation_normalization=True)
        self.assertEqual(text, f"{t} [S1]")
        self.assertEqual(log["lines"][0]["to"], ["S1"])


class TestDeterminismAndSafety(unittest.TestCase):
    def test_deterministic(self):
        t = "The system posts the bill automatically after creation."
        c = ctx(("S1", "x"), ("S2", "y"), ("S3", t))
        a = CRC.repair_citations(f"{t} [S1]", c)
        b = CRC.repair_citations(f"{t} [S1]", c)
        self.assertEqual(a, b)

    def test_never_cites_undersupplied_or_external_chunk(self):
        # marker that is not a supplied chunk must not appear
        c = ctx(("S1", "some text"))
        answer = "Some sentence about other things entirely. [S1]"
        text, _ = CRC.repair_citations(answer, c)
        self.assertNotIn("[S2]", text)
        self.assertNotIn("[S9]", text)


if __name__ == "__main__":
    unittest.main()
