"""Offline repair of malformed captured pagecontent responses (bare quotes inside data.body)."""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sap_resolver.repair import RepairError, repair_pagecontent_text  # noqa: E402

PAGE = "8990d0533f8e4308e10000000a174cb4"
BODY = '<!DOCTYPE html>\n<html lang="en-us"><body><p class="x">He said "hi" \\ back\\slash \u00e9 & <b>x</b></p></body></html>'


def _good(body=BODY):
    return {"status": "OK", "data": {"fallback": False,
            "deliverable": {"title": "T", "loio": "0" * 31 + "1", "fullToc": [{"t": "Root", "u": PAGE + ".html", "c": []}]},
            "currentPage": {"id": 1, "t": "Device Management", "u": PAGE + ".html", "loio": PAGE},
            "body": body, "isMachineTranslated": 0, "githubLink": ""}}


def _chrome_style(resp):
    """What the browser copy looks like: the body JSON-escaped EXCEPT the double quotes."""
    txt = json.dumps(resp, ensure_ascii=False, separators=(",", ":"))
    body_json = json.dumps(resp["data"]["body"], ensure_ascii=False)
    assert body_json in txt
    return txt.replace(body_json, '"' + body_json[1:-1].replace('\\"', '"') + '"')


class RepairTests(unittest.TestCase):
    def test_bare_quotes_body_is_preserved_exactly(self):
        bad = _chrome_style(_good())
        with self.assertRaises(ValueError):
            json.loads(bad)
        resp, rep = repair_pagecontent_text(bad)
        self.assertEqual(resp, _good())
        self.assertEqual(resp["data"]["body"], BODY)
        self.assertEqual(list(resp["data"]), list(_good()["data"]))            # member order kept
        self.assertGreater(rep["bare_quotes_escaped"], 0)

    def test_raw_newlines_and_bom_and_already_escaped_quotes(self):
        bad = "\ufeff" + _chrome_style(_good()).replace("\\n", "\n")          # literal newline in the string
        resp, _ = repair_pagecontent_text(bad)
        self.assertEqual(resp["data"]["body"], BODY)
        raw = ('{"status":"OK","data":{"fallback":false,"currentPage":{"loio":"' + PAGE + '"},'
               '"body":"a "b" \\"c\\" \\u00e9 \\n d","isMachineTranslated":0,"githubLink":""}}')
        resp, _ = repair_pagecontent_text(raw)
        self.assertEqual(resp["data"]["body"], 'a "b" "c" \u00e9 \n d')           # valid escapes decode, bare quotes are kept

    def test_refuses_unexpected_structure(self):
        for bad in ['{"status":"OK","data":{"deliverable":{"loio":"x"}}}',          # no body
                    '{"status":"OK","data":{"body":"<a b="c">"',                    # head ok, no tail
                    _chrome_style(_good()).replace('"currentPage":', '"currentPage" ')]:   # head broken
            with self.assertRaises(RepairError, msg=bad[:60]):
                repair_pagecontent_text(bad)
        with self.assertRaises(RepairError):                                       # invalid escape inside the body
            repair_pagecontent_text('{"status":"OK","data":{"body":"x \\q y","isMachineTranslated":0}}')

    def test_real_saved_responses_roundtrip_after_simulated_corruption(self):
        folder = ROOT / "captured_responses"
        files = [p for p in sorted(folder.glob("[0-9]*_*.json"))] if folder.is_dir() else []
        if not files:
            self.skipTest("no captured responses")
        for f in files:
            orig = json.loads(f.read_text(encoding="utf-8-sig"))
            resp, rep = repair_pagecontent_text(_chrome_style(orig))
            self.assertEqual(resp, orig, f.name)
            self.assertEqual(resp["data"]["body"], orig["data"]["body"])

    def test_cli_repairs_in_place_keeps_original_and_is_idempotent(self):
        spec = importlib.util.spec_from_file_location("repair_cli", ROOT / "scripts" / "repair_captured_response.py")
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        tmp = Path(tempfile.mkdtemp())
        try:
            name = f"1_40374657_{PAGE}.json"
            bad = _chrome_style(_good())
            (tmp / name).write_text(bad, encoding="utf-8")
            (tmp / "summary.json").write_text("[]", encoding="utf-8")
            self.assertEqual(cli.main(["--dir", str(tmp)]), 0)
            self.assertEqual(json.load(open(tmp / name, encoding="utf-8")), _good())
            self.assertEqual((tmp / "_malformed_originals" / name).read_text(encoding="utf-8"), bad)
            self.assertTrue((tmp / "_malformed_originals" / (name + ".repair.json")).is_file())
            self.assertEqual(cli.main(["--dir", str(tmp)]), 0)                      # now valid: untouched
            # page mismatch with the file name -> refused, nothing written
            other = tmp / f"2_1_{'a' * 32}.json"
            other.write_text(bad, encoding="utf-8")
            self.assertEqual(cli.main(["--dir", str(tmp), str(other)]), 1)
            self.assertEqual(other.read_text(encoding="utf-8"), bad)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class PrettyPrintedCopyTests(unittest.TestCase):
    def test_pretty_printed_browser_copy_with_spaced_members(self):
        """The real Chrome copy is pretty-printed (`"body": "..."`, members on their own lines)."""
        resp = _good()
        txt = json.dumps(resp, ensure_ascii=False, indent=1)
        bj = json.dumps(BODY, ensure_ascii=False)
        bad = txt.replace(bj, '"' + bj[1:-1].replace('\\"', '"') + '"')
        with self.assertRaises(ValueError):
            json.loads(bad)
        out, rep = repair_pagecontent_text(bad)
        self.assertEqual(out, resp)
        self.assertEqual(out["data"]["body"], BODY)
