"""Phase 8C - chunk strategies: legacy reproduction, heading awareness, token limits, metadata, determinism."""
from __future__ import annotations

import json
import re
import unittest

from tests.phase8_support import HAVE_BS4, ROOT, corpus_records, regex_count

import page_chunker as PK  # noqa: E402

REQUIRED = ("chunk_id", "guide_id", "page_id", "source_url", "title", "heading_path", "section_title", "chunk_index", "text", "content_hash")


def synth(blocks, title="Page", guide="g" * 32, page="p" * 32):
    bl = [dict(b, block_index=i) for i, b in enumerate(blocks)]
    return {"guide_id": guide, "page_id": page, "doc_id": f"{guide}/{page}", "source_ids": ["M2C-99"], "source_url": "https://example/x", "title": title,
            "text": "\n".join(b["text"] for b in bl), "blocks": bl}


def para(text, *path):
    return {"kind": "paragraph", "text": text, "heading_path": ["Page", *path]}


class LegacyStrategyTests(unittest.TestCase):
    def test_legacy_reproduction_matches_committed_chunks_json(self):
        pages = json.loads((ROOT / "cleaned_pages.json").read_text(encoding="utf-8"))
        old = json.loads((ROOT / "chunks.json").read_text(encoding="utf-8"))
        new = [t for p in pages for t in PK.legacy_chunk_texts(p["text"])]
        self.assertEqual(new, [c["text"] for c in old])

    def test_legacy_max_chars_respected(self):
        for c in PK.legacy_chunk_texts(("Sentence number one is here. " * 200), 1000):
            self.assertLessEqual(len(c), 1000)


class HeadingStrategyTests(unittest.TestCase):
    cfg = PK.STRATEGIES["B_heading_200"]

    def test_metadata_fields_and_ids(self):
        rec = synth([para("A short sentence about meters and readings in the system.", "Use")])
        ch = PK.chunk_page(rec, self.cfg, regex_count)
        self.assertEqual(len(ch), 1)
        for k in REQUIRED:
            self.assertIn(k, ch[0])
        self.assertEqual(ch[0]["chunk_id"], f"{'g' * 32}/{'p' * 32}/000")
        self.assertEqual(ch[0]["heading_path"], ["Page", "Use"])
        self.assertEqual(ch[0]["section_title"], "Use")
        self.assertEqual(ch[0]["embedding_text"], "Page > Use\n" + ch[0]["text"])
        self.assertEqual(len(ch[0]["content_hash"]), 64)

    def test_deterministic(self):
        rec = synth([para("Alpha beta gamma. " * 80, "Use"), para("Delta epsilon. " * 60, "Features")])
        self.assertEqual(PK.chunk_page(rec, self.cfg, regex_count), PK.chunk_page(rec, self.cfg, regex_count))

    def test_does_not_cross_headings_unless_tiny(self):
        rec = synth([para("Long enough paragraph about billing. " * 12, "Use"), para("Another long paragraph about invoicing. " * 12, "Features")])
        ch = PK.chunk_page(rec, self.cfg, regex_count)
        paths = {tuple(c["heading_path"]) for c in ch}
        self.assertEqual(paths, {("Page", "Use"), ("Page", "Features")})
        for c in ch:
            self.assertEqual(c["merged_headings"], [])
            if c["heading_path"][-1] == "Use":
                self.assertNotIn("invoicing", c["text"])

    def test_tiny_section_merges_into_previous(self):
        rec = synth([para("Long enough paragraph about billing. " * 6, "Use"), para("Tiny.", "Notes")])
        ch = PK.chunk_page(rec, self.cfg, regex_count)
        self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0]["merged_headings"], ["Notes"])
        self.assertIn("Notes\nTiny.", ch[0]["text"])

    def test_chunks_never_exceed_token_cap_and_are_never_empty(self):
        rec = synth([para("This is sentence number %d about meter reading orders and billing. " % i, "Use") for i in range(120)])
        for name in ("B_heading_200", "C_heading_128"):
            for c in PK.chunk_page(rec, PK.STRATEGIES[name], regex_count):
                self.assertLessEqual(c["token_count"], PK.STRATEGIES[name].max_tokens)
                self.assertTrue(c["text"].strip())

    def test_overlap_only_when_one_paragraph_is_split(self):
        sent = " ".join(f"This is sentence number {i} about meter reading orders and billing." for i in range(60))
        ch = PK.chunk_page(synth([para(sent, "Use")]), self.cfg, regex_count)
        self.assertGreater(len(ch), 2)
        for a, b in zip(ch, ch[1:]):
            self.assertGreater(b["overlap_chars"], 0)
            self.assertIn(b["text"].split("\n")[0], a["text"])
        # separate paragraphs of one section are packed, not overlapped
        ch2 = PK.chunk_page(synth([para("Paragraph %d has its own distinct content about topic %d." % (i, i), "Use") for i in range(40)]), self.cfg, regex_count)
        self.assertTrue(all(c["overlap_chars"] == 0 for c in ch2))

    def test_lead_in_and_label_stay_with_what_follows(self):
        items = [{"kind": "list", "text": "\n".join(f"- item {i} " + "word " * 20 for i in range(30)), "heading_path": ["Page", "Use"]}]
        rec = synth([para("Filler sentence. " * 10, "Use"), para("The following functions are available:", "Use")] + items)
        ch = PK.chunk_page(rec, PK.STRATEGIES["C_heading_128"], regex_count)
        for i, c in enumerate(ch):
            self.assertFalse(c["text"].rstrip().endswith("available:"), c["text"][-60:])

    def test_long_single_sentence_is_split_not_truncated(self):
        long = " ".join(f"word{i}" for i in range(900))
        rec = synth([para(long, "Use")])
        ch = PK.chunk_page(rec, self.cfg, regex_count)
        self.assertGreater(len(ch), 1)
        rebuilt = " ".join(c["text"] for c in ch).split()
        self.assertTrue(set(long.split()) <= set(rebuilt))
        self.assertTrue(all(c["token_count"] <= self.cfg.max_tokens for c in ch))

    def test_table_rows_split_on_row_boundaries(self):
        rows = "\n".join(f"Name: row{i}; Value: {'x ' * 25}" for i in range(40))
        ch = PK.chunk_page(synth([{"kind": "table", "text": rows, "heading_path": ["Page", "Use"]}]), self.cfg, regex_count)
        for c in ch:
            for line in c["text"].split("\n"):
                self.assertTrue(line.startswith("Name: row"))

    def test_chunk_text_is_traceable_to_page_blocks(self):
        rec = synth([para("Alpha sentence one. Beta sentence two. " * 30, "Use"), para("Gamma.", "Features")])
        blob = " ".join(b["text"] for b in rec["blocks"]) + " Features"
        for c in PK.chunk_page(rec, self.cfg, regex_count):
            for line in c["text"].split("\n"):
                for sent in re.split(r"(?<=[.!?])\s+", line):
                    self.assertIn(sent, blob)


@unittest.skipUnless(HAVE_BS4, "bs4 missing")
class RealCorpusChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = corpus_records()

    def test_every_strategy_covers_every_page_and_every_text_char(self):
        for name, cfg in PK.STRATEGIES.items():
            ch = PK.chunk_corpus(self.records, cfg, regex_count)
            self.assertEqual({c["page_id"] for c in ch}, {r["page_id"] for r in self.records}, name)
            ids = [c["chunk_id"] for c in ch]
            self.assertEqual(len(ids), len(set(ids)))
            for r in self.records:
                joined = " ".join(c["text"] for c in ch if c["page_id"] == r["page_id"])
                missing = [b["text"][:50] for b in r["blocks"] if b["text"].split("\n")[0] not in joined and name != "A_legacy_1000c"]
                self.assertEqual(missing, [], (name, r["doc_id"]))

    def test_model_token_limit_with_real_tokenizer_if_available(self):
        count, info = PK.make_token_counter()
        if not info.get("exact"):
            self.skipTest("model tokenizer not available: " + str(info.get("reason")))
        for name, cfg in PK.STRATEGIES.items():
            stats = PK.chunk_stats(PK.chunk_corpus(self.records, cfg, count))
            self.assertEqual(stats["over_model_limit"], 0, name)

    def test_strategy_ids_and_default_are_declared(self):
        self.assertEqual(set(PK.STRATEGIES), {"A_legacy_1000c", "B_heading_200", "C_heading_128"})
        self.assertEqual(PK.DEFAULT_STRATEGY, "B_heading_200")

    def test_stats_shape(self):
        s = PK.chunk_stats(PK.chunk_corpus(self.records, PK.STRATEGIES["B_heading_200"], regex_count))
        for k in ("chunks", "pages", "tokens", "chars", "over_model_limit", "split_chunks"):
            self.assertIn(k, s)
        self.assertEqual(PK.chunk_stats([]), {"chunks": 0})


if __name__ == "__main__":
    unittest.main()
