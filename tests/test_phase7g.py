"""Phase 7G - the legacy / route_only mode boundary (spec section 5, 7G; implementation: scripts/rag_modes.py).

Store-free tests use a deterministic stub backend; the store-gated tests run the real router and model and are skipped, with a
reason, when ``data/vector_store`` or the model are missing. Old Phase 7A-7F tests are pinned by hash so that any edit to them
(or to the protected legacy and 7A-7F files) fails here.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import socket
import subprocess
import sys
import types
import unittest
import zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import m2c_common as C  # noqa: E402

rm = importlib.import_module("rag_modes")
rt = importlib.import_module("m2c_router")
pid = importlib.import_module("m2c_page_identity")
cit = importlib.import_module("m2c_citations")
ev = importlib.import_module("evaluate_two_stage")

EVAL = ROOT / "data" / "evaluation"


def _have(mod):
    return importlib.util.find_spec(mod) is not None


def _model_available():
    try:
        C.resolve_model()
        return True
    except Exception:
        return False


LIVE = C.VECTOR_DIR.is_dir() and (C.VECTOR_DIR / "chroma.sqlite3").is_file() and _have("chromadb") and _have("sentence_transformers") and _model_available()
SKIP_MSG = "needs data/vector_store (build_card_collection.py), chromadb, sentence-transformers and the local all-MiniLM-L6-v2 files"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


UNITS = {u["source_id"]: u for u in load(C.UNITS_PATH)["units"]}
AUDIT = {c["source_id"]: c for c in load(ROOT / "data" / "m2c_citation_audit.json")["cards"]}
E7 = load(ROOT / "data" / "phase7E_evaluation.json")

# Hashes recorded at the start of 7G. Old tests, the legacy production files and the Phase 7 artefacts must not change.
PINNED = {
    "tests/test_phase7a.py": "58aa1bed1984d5918861e5f292652956941f01f4bb886700cc15ceb739997bda",
    "tests/test_phase7b.py": "2e46bfb2a946bd861d2676a420895172ed347990ed44b8bf6fca2d887fb33149",
    "tests/test_phase7c.py": "7b1c82361d9d527b05dffdc0bb357634fe1c2080a3eb9cd786e54e04233fd84f",
    "tests/test_phase7d.py": "89373f958d4fad736d306b868277b8b3e57dc5f9d6bcc5e07ee462e8785e0c2e",
    "tests/test_phase7e.py": "d7058929dfe41c733ac30d34845ebdf7f39f5b23bbf390490d96f3962b449271",
    "tests/test_phase7f.py": "de1b2bc939fe1f19064682529cfcb3c1a7e711619f9898ad8969546473379537",
    "tests/test_phase5.py": "5f1d9d7bc395cfee61656cd192688b3c55815a8b1c6c0481df6a16dd47664be7",
    "scripts/rag_chat.py": "e862ce38d06e2ef74f39e366a5a8b65948ba03f00dfab5baa0c61bc281673a15",
    "scripts/rag_core.py": "881316e4f9f2c164b2109f416b2a309f8ab829f185d231b09990274f56567b2c",
    "scripts/retrieve.py": "a7c878955709e5b1a1630d70b7f48993b2ee97602bdfdb899f5f70c986cda260",
    "scripts/evaluate_retrieval.py": "6275a670ab3d274ed862479f9b2a7ac6f2be88153f44440e59bc9b984b10621d",
    "scripts/create_embeddings.py": "2e00072b1a9863a848b13d3ff6f088b10837446521c12793c5c6d5eee2923144",
    "scripts/evaluate_two_stage.py": "5ced2dabc27edb9cb7e4db90d4133c683e7aa2a54e09c4f74e5b3b41333c6a47",
    "scripts/evaluate_ood.py": "584bb29e57fbe9b665a25d4e785bb441bd675ea9b403cde3150044845764b7ff",
    "scripts/build_card_collection.py": "39381b1ec959f1100e6d49404878d5f457c5fce74cc36b5ac558da40a9089233",
    "data/evaluation/phase7F_results.json": "40f8e536dfe9da667a152cd60e5c0aa3a8834323cffa83883653948cfa27bc6b",
    "data/evaluation/phase7F_ood_queries.json": "631c7a524edecb5f78205334dd86256638fe1473998e86e7926ec619801dbe14",
    "data/phase7_checkpoint.md": "9d5dc410e1f97c42c182453ebd707af7f2722b79a472a7cea84db774b75b568c",
    "data/m2c_page_identity.json": "fccb0bb87fc6309ac0fa9e1205387c68aeb6f93fff73d6aab457a2164587787c",
    "data/m2c_citation_audit.json": "009ede7a187d11850a1c7e3cd72f964090ef4f0d161daffab6ecd3206901ded6",
    "data/retrieval_units.json": "f5e9b908c9b7374ffab5adbc6f8afb9b5597de91cb50ec3fea8b9b3db2d3ff21",
    "data/phase7E_evaluation.json": "727236b9707eb783e173c6418e84f459ae17aba918f90cd34080f5bd3e22be28",
}
EXPECTED_IDENTITY = {**{f"M2C-{n:02d}": "identified_not_local" for n in range(1, 30)},
                     "M2C-17": "resolved_local_page", "M2C-05": "corrected_identity", "M2C-18": "conflicting_identity",
                     "M2C-01": "card_identity_only", "M2C-13": "card_identity_only", "M2C-16": "card_identity_only"}


class CardFirstBackend:
    """Stub backend: the requested card is rank 1 (cosine distance ``d1``); the other 28 follow in a fixed order."""
    distance_metric = "cosine"

    def __init__(self, first=None, d1=0.3):
        bcc = importlib.import_module("build_card_collection")
        self.meta = {s: bcc.metadata_for(u) for s, u in UNITS.items()}
        self.first, self.d1 = first, d1
        self.queries = []

    def query(self, query, n_results):
        self.queries.append(query)
        ids = sorted(self.meta, key=lambda i: (zlib.crc32((query + i).encode()), i))
        if self.first:
            ids = [self.first] + [i for i in ids if i != self.first]
        ids = ids[:n_results]
        return {"ids": [ids], "metadatas": [[self.meta[i] for i in ids]], "distances": [[self.d1 + 0.01 * k for k in range(len(ids))]]}


_CTX = None


def ctx():
    global _CTX
    if _CTX is None:
        _CTX = pid.IdentityContext.from_root(ROOT)
    return _CTX


def run_main(argv, backend=None, stdin_lines=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        if stdin_lines is not None:
            with mock.patch("builtins.input", side_effect=list(stdin_lines)):
                code = rm.main(argv, backend=backend, ctx=ctx())
        else:
            code = rm.main(argv, backend=backend, ctx=ctx())
    return code, out.getvalue(), err.getvalue()


def fake_rag_chat(calls):
    m = types.ModuleType("rag_chat")
    m.main = lambda: calls.append("legacy_main")
    return m


def routed(card_id, d1=0.3, question="any question"):
    return rm.route_only(question, CardFirstBackend(card_id, d1), ctx()).to_dict()


# ------------------------------------------------------------------------------------------------ 1-3 mode selection


class ModeSelectionTests(unittest.TestCase):
    def test_default_mode_is_legacy_and_flags_are_additive(self):
        self.assertEqual(rm.DEFAULT_MODE, "legacy")
        self.assertEqual(rm.build_parser().parse_args([]).mode, "legacy")
        self.assertEqual(rm.build_parser().parse_args(["--mode", "legacy"]).mode, "legacy")
        self.assertEqual(rm.IMPLEMENTED_MODES, ("legacy", "route_only"))

    def test_no_arguments_runs_the_existing_chatbot_unchanged(self):
        calls = []
        with mock.patch.dict(sys.modules, {"rag_chat": fake_rag_chat(calls)}):
            self.assertEqual(rm.main([]), 0)
            self.assertEqual(rm.main(["--mode", "legacy"]), 0)
        self.assertEqual(calls, ["legacy_main", "legacy_main"])     # rag_chat.main() called with no arguments, once per invocation

    def test_legacy_delegates_to_the_real_rag_chat_main_without_running_it(self):
        """Fresh process: the real rag_chat is importable and run_legacy calls exactly its main() (patched here so no chatbot starts)."""
        code = ("import sys; sys.path.insert(0, 'scripts'); import rag_modes as rm\n"
                "import rag_chat; calls = []; rag_chat.main = lambda: calls.append('main')\n"
                "rc = rm.main([]); print(rc, calls)")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "0 ['main']")

    def test_legacy_mode_does_not_touch_the_router_or_the_store(self):
        calls = []
        be = CardFirstBackend()
        with mock.patch.dict(sys.modules, {"rag_chat": fake_rag_chat(calls)}), mock.patch.object(rm, "route_only", side_effect=AssertionError("router used")):
            rm.main([], backend=be)
        self.assertEqual(be.queries, [])

    def test_explicit_route_only_runs_the_routing_path_and_not_legacy(self):
        calls = []
        be = CardFirstBackend("M2C-17")
        with mock.patch.dict(sys.modules, {"rag_chat": fake_rag_chat(calls)}):
            code, out, err = run_main(["--mode", "route_only", "--question", "How are payments assigned?"], backend=be)
        self.assertEqual((code, calls, err), (0, [], ""))
        self.assertEqual(be.queries, ["How are payments assigned?"])
        self.assertIn("route_only", out)
        self.assertIn("Closest topic card", out)

    def test_json_output_is_valid_and_structured(self):
        code, out, _ = run_main(["--mode", "route_only", "--question", "q", "--json", "--top-k", "3"], backend=CardFirstBackend("M2C-02"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual((d["mode"], d["selected"]["source_id"], len(d["candidates"])), ("route_only", "M2C-02", 3))

    def test_interactive_route_only_loop_stops_on_exit_and_skips_blank_lines(self):
        be = CardFirstBackend("M2C-02")
        code, out, _ = run_main(["--mode", "route_only"], backend=be, stdin_lines=["", "first question", "exit"])
        self.assertEqual(code, 0)
        self.assertEqual(be.queries, ["first question"])
        self.assertIn("Goodbye!", out)

    def test_invalid_modes_fail_clearly_and_exit_2(self):
        for bad in ("bogus", "Legacy", "ROUTE_ONLY", "route-only", "", " legacy", "legacy "):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                rm.main(["--mode", bad])
            self.assertEqual(cm.exception.code, 2, repr(bad))
            self.assertIn("unknown mode", err.getvalue(), repr(bad))
            self.assertIn("Valid modes: legacy, route_only", err.getvalue())

    def test_specified_but_unimplemented_modes_are_refused_not_aliased(self):
        for mode in ("shadow", "routed"):
            with self.assertRaises(rm.ModeError) as cm:
                rm.parse_mode(mode)
            self.assertIn("not implemented", str(cm.exception))
            self.assertIn("no page corpus", str(cm.exception))
            err = io.StringIO()
            calls = []
            with mock.patch.dict(sys.modules, {"rag_chat": fake_rag_chat(calls)}), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ex:
                rm.main(["--mode", mode, "--question", "q"], backend=CardFirstBackend())
            self.assertEqual((ex.exception.code, calls), (2, []))      # no silent fallback to legacy or to route_only
            self.assertIn("not implemented", err.getvalue())

    def test_route_only_options_with_legacy_mode_are_an_error(self):
        for argv in (["--question", "q"], ["--mode", "legacy", "--json"], ["--top-k", "3"]):
            calls = []
            err = io.StringIO()
            with mock.patch.dict(sys.modules, {"rag_chat": fake_rag_chat(calls)}), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                rm.main(argv)
            self.assertEqual((cm.exception.code, calls), (2, []))
            self.assertIn("only apply to --mode route_only", err.getvalue())

    def test_invalid_top_k_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            rm.main(["--mode", "route_only", "--question", "q", "--top-k", "0"], backend=CardFirstBackend())
        self.assertEqual(cm.exception.code, 2)

    def test_missing_store_is_a_defined_failure_never_a_legacy_fallback(self):
        calls = []
        with mock.patch.dict(sys.modules, {"rag_chat": fake_rag_chat(calls)}):
            code, out, err = run_main(["--mode", "route_only", "--question", "q", "--vector-dir", "/nonexistent/vector_store"])
        self.assertEqual((code, calls, out), (2, [], ""))
        self.assertIn("router_unavailable", err)

    def test_help_lists_only_implemented_modes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            rm.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("legacy, route_only", out.getvalue())
        self.assertNotIn("shadow", out.getvalue())


# ------------------------------------------------------------------------------------------------ 4-6 isolation


def module_level_imports(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def all_imports(path):
    out = []
    for n in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append(n.module or "")
    return out


class IsolationTests(unittest.TestCase):
    def test_legacy_pipeline_is_imported_only_inside_run_legacy(self):
        path = SCRIPTS / "rag_modes.py"
        for name in module_level_imports(path):
            self.assertNotIn(name.split(".")[0], {"rag_chat", "rag_core", "retrieve", "evaluate_retrieval", "create_embeddings", "ollama"}, name)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        holders = [f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
                   for n in ast.walk(f) if isinstance(n, ast.Import) and any(a.name == "rag_chat" for a in n.names)]
        self.assertEqual(holders, ["run_legacy"])
        for name in all_imports(path):
            self.assertNotIn(name.split(".")[0], {"rag_core", "retrieve", "evaluate_retrieval", "create_embeddings", "ollama"}, name)

    def test_no_llm_or_generation_vocabulary(self):
        text = (SCRIPTS / "rag_modes.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in text.splitlines())
        for tok in ("generate_answer", "build_prompt", "LLM_OPTIONS", "import ollama", "temperature", "openai", "anthropic", "llama"):
            self.assertNotIn(tok, code.replace("no LLM", ""), tok)

    def test_no_network_modules(self):
        banned = {"requests", "socket", "httpx", "aiohttp", "urllib3", "ollama", "openai", "anthropic"}
        for name in all_imports(SCRIPTS / "rag_modes.py"):
            self.assertNotIn(name.split(".")[0], banned, name)
            self.assertNotIn(name, ("urllib.request", "urllib.error", "http.client"), name)

    def test_collection_is_never_written(self):
        text = (SCRIPTS / "rag_modes.py").read_text(encoding="utf-8")
        for tok in (".add(", ".upsert(", "delete_collection", "create_collection", "get_or_create_collection", ".delete(", "sap_docs", "chroma_db"):
            self.assertNotIn(tok, text, tok)

    def test_route_only_makes_no_socket_connection_and_calls_no_llm_or_legacy(self):
        attempts = []

        def refuse(self, *a, **k):
            attempts.append(a)
            raise AssertionError("network attempt")
        calls = []
        legacy = fake_rag_chat(calls)
        with mock.patch.dict(sys.modules, {"rag_chat": legacy}), mock.patch.object(socket.socket, "connect", refuse), mock.patch.object(socket, "create_connection", refuse):
            for cid in ("M2C-17", "M2C-05", "M2C-18"):
                routed(cid)
        self.assertEqual((attempts, calls), ([], []))

    def test_subprocess_route_only_loads_no_llm_legacy_or_network_module(self):
        code = (
            "import sys, io, contextlib; sys.path.insert(0, 'scripts'); sys.path.insert(0, 'tests'); "
            "import rag_modes as rm, m2c_page_identity as pid, m2c_common as C; "
            "from test_phase7g import CardFirstBackend; "
            "buf = io.StringIO()\n"
            "with contextlib.redirect_stdout(buf):\n"
            "    rc = rm.main(['--mode','route_only','--question','q','--json'], backend=CardFirstBackend('M2C-17'), ctx=pid.IdentityContext.from_root(C.ROOT))\n"
            "bad = sorted(m for m in ('ollama','rag_core','rag_chat','retrieve','evaluate_retrieval','create_embeddings','requests','httpx','chromadb','sentence_transformers','torch') if m in sys.modules)\n"
            "print(rc, bad)")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "0 []")

    def test_payload_states_what_was_not_done(self):
        d = routed("M2C-17")
        self.assertEqual((d["answer_generated"], d["llm_called"], d["page_text_used"], d["network_used"]), (False, False, False, False))
        for forbidden in ("answer", "text", "content", "chunks", "prompt"):
            self.assertNotIn(forbidden, d)
            self.assertNotIn(forbidden, d["selected"])


# ------------------------------------------------------------------------------------------------ 7 no threshold


class NoThresholdTests(unittest.TestCase):
    def test_min_cosine_is_none_everywhere(self):
        self.assertIsNone(rm.MIN_COSINE)
        self.assertIsNone(routed("M2C-02")["min_cosine"])
        self.assertIsNone(load(EVAL / "phase7F_results.json")["verdict"]["min_cosine"])

    def test_no_threshold_parameter_or_option_exists(self):
        import inspect
        for fn in (rm.route_only, rm.main):
            self.assertNotIn("min_cosine", inspect.signature(fn).parameters)
            self.assertNotIn("threshold", inspect.signature(fn).parameters)
        opts = {o for a in rm.build_parser()._actions for o in a.option_strings}
        self.assertEqual(opts, {"-h", "--help", "--mode", "--question", "--top-k", "--json", "--vector-dir"})
        tree = ast.parse((SCRIPTS / "rag_modes.py").read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for tok in ("MAX_DISTANCE", "max_distance", "make_selector", "min_similarity", "select_on_dev"):
            self.assertNotIn(tok, names, tok)

    def test_a_very_distant_card_is_still_selected_and_flagged_as_rank_not_confidence(self):
        d = routed("M2C-08", d1=0.99, question="What is the weather today?")
        self.assertEqual(d["selected"]["source_id"], "M2C-08")
        self.assertEqual(d["candidates"][0]["cosine_distance"], 0.99)
        self.assertEqual(d["candidates"][0]["cosine_similarity"], 0.01)
        self.assertIn("Rank, not confidence", d["rank_is_not_confidence"])
        self.assertEqual(len(d["candidates"]), 5)

    def test_similarity_and_distance_are_separate_fields(self):
        for c in routed("M2C-02", d1=0.4)["candidates"]:
            self.assertAlmostEqual(c["cosine_similarity"], 1 - c["cosine_distance"], places=6)
            self.assertNotIn("distance", c)
            self.assertNotIn("score", c)

    def test_selection_is_rank_one_whatever_its_score(self):
        for d1 in (0.0, 0.5, 0.95, 1.4):
            self.assertEqual(routed("M2C-09", d1=d1)["selected"]["source_id"], "M2C-09")

    def test_empty_question_selects_nothing_and_says_so(self):
        d = rm.route_only("   ", CardFirstBackend(), ctx()).to_dict()
        self.assertEqual((d["status"], d["selected"], d["fallback_reason"]), ("no_card_candidate", None, "EMPTY_QUERY"))
        self.assertIn("No topic card was selected", d["message"])


# ------------------------------------------------------------------------------------------------ 8-10 URL, identity, citation semantics


class SemanticsTests(unittest.TestCase):
    def test_every_card_url_is_byte_identical_to_the_stored_value(self):
        for cid, u in UNITS.items():
            d = routed(cid)
            stored = u["source_url"]
            self.assertEqual(d["selected"]["url"], stored, cid)
            self.assertEqual(d["citations"]["sources"][0]["url"], stored, cid)
            self.assertEqual(AUDIT[cid]["url"], stored, cid)
            self.assertIn(f"(source: {stored})", d["message"], cid)

    def test_identity_statuses_are_unchanged_for_all_29_cards(self):
        got = {cid: routed(cid)["status"] for cid in UNITS}
        self.assertEqual(got, EXPECTED_IDENTITY)
        counts = {}
        for s in got.values():
            counts[s] = counts.get(s, 0) + 1
        self.assertEqual(counts, {"resolved_local_page": 1, "identified_not_local": 23, "corrected_identity": 1, "card_identity_only": 3, "conflicting_identity": 1})
        self.assertNotIn("unresolved", counts)

    def test_status_equals_the_identity_layer_and_the_7d_audit(self):
        for cid in UNITS:
            d = routed(cid)
            self.assertEqual(d["selected"]["identity_status"], AUDIT[cid]["identity"]["status"], cid)
            self.assertEqual(d["selected"]["review_flag"], AUDIT[cid]["review_flag"], cid)
            self.assertEqual(d["selected"]["review_reasons"], AUDIT[cid]["review_reasons"], cid)
            self.assertEqual(d["selected"]["citation"], AUDIT[cid]["citation"], cid)

    def test_review_flagged_cards_keep_their_flags_and_are_not_corrected(self):
        flagged = {cid for cid in UNITS if routed(cid)["selected"]["review_flag"]}
        self.assertEqual(flagged, {"M2C-14", "M2C-18", "M2C-23"})
        d14, d18, d23 = routed("M2C-14"), routed("M2C-18"), routed("M2C-23")
        for d in (d14, d18, d23):
            self.assertIn("flagged for review", d["message"])
        self.assertEqual(d18["status"], "conflicting_identity")
        self.assertIn("no effective page is chosen", d18["message"])
        self.assertEqual(d18["citations"]["sources"][0]["identity"]["effective_page_id"], None)
        self.assertEqual(routed("M2C-05")["status"], "corrected_identity")

    def test_card_route_is_a_pointer_never_answer_text(self):
        for cid in UNITS:
            d = routed(cid)
            src = d["citations"]["sources"]
            self.assertEqual(len(src), 1)
            self.assertEqual(src[0]["origin"], "card_route")
            self.assertIs(src[0]["used_as_answer_text"], False)
            self.assertIs(src[0]["provided_as_context"], False)
            self.assertIs(src[0]["verified_used"], False)
            self.assertIs(d["selected"]["used_as_answer_text"], False)
            self.assertEqual(d["citations"]["label"], cit.LABEL_ROUTE_ONLY)
            self.assertNotIn("page_chunk", {s["origin"] for s in src})

    def test_local_page_exists_is_distinguished_from_page_text_used(self):
        d17 = routed("M2C-17")
        self.assertEqual((d17["status"], d17["selected"]["page_content_available"], d17["page_text_used"]), ("resolved_local_page", True, False))
        self.assertIn("does not retrieve or use page text", d17["message"])
        self.assertNotIn("not available locally", d17["message"])
        for cid in UNITS:
            if cid != "M2C-17":
                d = routed(cid)
                self.assertFalse(d["selected"]["page_content_available"], cid)
                self.assertIn("page content is not available locally", d["message"], cid)
                self.assertIn("PAGE_" + d["status"].upper(), d["citations"]["sources"][0]["flags"], cid)

    def test_url_only_and_resolved_states_stay_distinguishable(self):
        self.assertEqual(routed("M2C-17")["selected"]["join_state"], "resolved_page")
        self.assertEqual(routed("M2C-02")["selected"]["join_state"], "url_only")

    def test_text_rendering_labels_card_routes_and_never_shows_page_text(self):
        code, out, _ = run_main(["--mode", "route_only", "--question", "q"], backend=CardFirstBackend("M2C-18"))
        self.assertIn("[card_route]", out)
        self.assertIn("[REVIEW]", out)
        self.assertIn("identity=conflicting_identity", out)
        self.assertIn("Rank, not confidence", out)
        self.assertIn("Sources (card route only: topic identification; no page text; no model involved):", out)
        self.assertNotIn("provided to the model", out)
        self.assertNotIn("[page_chunk]", out)


# ------------------------------------------------------------------------------------------------ 11-12 regression and frozen files


class RegressionTests(unittest.TestCase):
    def test_route_only_preserves_router_order_exactly(self):
        be = CardFirstBackend()
        d = rm.route_only("q", be, ctx(), top_k=29).to_dict()
        raw = be.query("q", 29)["ids"][0]
        self.assertEqual([c["source_id"] for c in d["candidates"]], raw)
        self.assertEqual(d["selected"]["source_id"], raw[0])

    def test_old_tests_legacy_files_and_phase7_artefacts_are_unchanged(self):
        for rel, h in PINNED.items():
            self.assertEqual(sha(rel), h, rel)

    def test_legacy_files_do_not_know_the_new_module_and_it_is_not_wired_in(self):
        for rel in ("scripts/rag_chat.py", "scripts/rag_core.py", "scripts/retrieve.py", "scripts/evaluate_retrieval.py", "scripts/create_embeddings.py"):
            self.assertNotIn("rag_modes", (ROOT / rel).read_text(encoding="utf-8"), rel)
        for p in SCRIPTS.glob("*.py"):
            if p.name != "rag_modes.py":
                self.assertNotIn("import rag_modes", p.read_text(encoding="utf-8"), p.name)

    def test_the_spec_named_module_is_not_created_and_no_page_pipeline_appeared(self):
        self.assertFalse((SCRIPTS / "rag_two_stage.py").exists())      # the 7F test asserts this; 7G does not use that name
        for rel in ("chroma_db", "data/page_vector_store"):
            self.assertFalse((ROOT / rel).exists(), rel)

    def test_router_orchestrator_and_collection_manifest_are_the_pinned_ones(self):
        self.assertEqual(sha("data/card_collection_manifest.json"), "5b3a5c30bc637c8b61573983a16cf252f7899d2c279eae3895e06476482d2731")
        self.assertEqual(sha("scripts/m2c_router.py"), "b846f18d098406c17859d053ae5b9c0ddb5b82e247e92ac709edeed1113ea8f4")
        self.assertEqual(sha("scripts/m2c_orchestrator.py"), "89bcfcc1c57669f492d92d12e2f720b2e9d9b36035c678737db4d081213782dd")


@unittest.skipUnless(LIVE, SKIP_MSG)
class LiveRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = rt.ChromaCardBackend(vector_dir=C.VECTOR_DIR)

    def test_phase4_top5_through_route_only_equals_the_recorded_rankings(self):
        p4 = load(EVAL / "card_retrieval_results.json")["per_question"]
        self.assertEqual(len(p4), 50)
        for r in p4:
            d = rm.route_only(r["question"], self.backend, ctx(), top_k=5).to_dict()
            self.assertEqual([c["source_id"] for c in d["candidates"]], [x["source_id"] for x in r["retrieved_top5"]], r["question_id"])
            self.assertAlmostEqual(d["candidates"][0]["cosine_similarity"], r["retrieved_top5"][0]["cosine_similarity"], delta=5.1e-5, msg=r["question_id"])
            self.assertEqual(d["selected"]["source_id"], r["retrieved_top5"][0]["source_id"])

    def test_phase5_top5_through_route_only_equals_the_phase7e_rankings(self):
        rows = ev.recorded_datasets()["phase5"]["rows"]
        e7 = {p["id"]: p for p in E7["per_query"]["phase5"]}
        self.assertEqual(len(rows), 54)
        for r in rows:
            d = rm.route_only(r["query"], self.backend, ctx(), top_k=5).to_dict()
            self.assertEqual([c["source_id"] for c in d["candidates"]], e7[r["id"]]["top5"], r["id"])

    def test_cli_route_only_end_to_end_on_the_real_store_in_a_fresh_process(self):
        code = ("import sys, socket\n"
                "def refuse(*a, **k): raise RuntimeError('network blocked')\n"
                "socket.socket.connect = refuse; socket.create_connection = refuse\n"
                "sys.path.insert(0, 'scripts'); import rag_modes as rm\n"
                "rc = rm.main(['--mode','route_only','--question','How are overdue items and dunning handled?','--json','--top-k','3'])\n"
                "bad = sorted(m for m in ('ollama','rag_core','rag_chat','retrieve','requests') if m in sys.modules)\n"
                "print('BAD', bad, rc)")
        env = dict(__import__("os").environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), env=env)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        out = r.stdout
        self.assertTrue(out.strip().endswith("BAD [] 0"), out[-300:])
        d = json.loads(out[:out.rindex("BAD")])
        self.assertEqual(d["mode"], "route_only")
        self.assertEqual(len(d["candidates"]), 3)
        self.assertIsNone(d["min_cosine"])
        self.assertFalse(d["llm_called"])

    def test_store_logical_content_is_unchanged_by_routing(self):
        before = ev.store_logical_snapshot(C.VECTOR_DIR)
        for r in load(EVAL / "card_retrieval_results.json")["per_question"][:5]:
            rm.route_only(r["question"], self.backend, ctx())
        self.assertEqual(before, ev.store_logical_snapshot(C.VECTOR_DIR))


if __name__ == "__main__":
    unittest.main()
