"""Portability regressions; native Windows certification still requires Windows."""
import builtins
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import chroma_temp
import platform_metrics
from build_chunk_candidates_portable import LFPath
from diagnose_windows_verification import compare_page_snapshot


def test_missing_resource_reports_unsupported_not_zero():
    original = builtins.__import__
    def no_resource(name, *args, **kwargs):
        if name == "resource":
            raise ImportError("Windows")
        return original(name, *args, **kwargs)
    with patch("builtins.__import__", side_effect=no_resource):
        assert platform_metrics.peak_rss_mb() is None
        sys.modules.pop("evaluate_phase9", None)
        assert importlib.import_module("evaluate_phase9")


@pytest.mark.parametrize("platform,value,expected", [("linux", 2048, 2.0), ("darwin", 2097152, 2.0)])
def test_rss_units_are_platform_correct(platform, value, expected):
    resource = types.SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: types.SimpleNamespace(ru_maxrss=value))
    with patch.dict(sys.modules, resource=resource), patch.object(sys, "platform", platform):
        assert platform_metrics.peak_rss_mb() == expected


def test_lf_writer_bypasses_text_mode(tmp_path):
    p = LFPath(tmp_path / "unicode.json")
    with patch.object(Path, "write_text", side_effect=AssertionError("native text writer forbidden")):
        assert p.write_text("é\nline\n", encoding="utf-8") == 7
    assert p.read_bytes() == "é\nline\n".encode()
    with pytest.raises(ValueError):
        p.write_text("x", newline="\r\n")


def test_portable_producer_matches_frozen_json_bytes(tmp_path):
    out = tmp_path / "new"
    subprocess.run([sys.executable, str(ROOT / "scripts/build_chunk_candidates_portable.py"), "--out-dir", str(out)], check=True)
    for p in (ROOT / "data/chunk_candidates").glob("*.json"):
        assert hashlib.sha256((out / p.name).read_bytes()).hexdigest() == hashlib.sha256(p.read_bytes()).hexdigest(), p.name
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/build_chunk_candidates_portable.py"), "--out-dir", str(out)], capture_output=True)
    assert proc.returncode != 0  # refuses overwriting even scratch output


def test_chroma_cleanup_only_stops_owned_persistent_systems(tmp_path):
    events = []
    def system(path, persistent=True):
        return types.SimpleNamespace(settings=types.SimpleNamespace(is_persistent=persistent, persist_directory=str(path)), stop=lambda: events.append(str(path)))
    inside = tmp_path / "temp/store"
    outside = tmp_path / "permanent"
    cache = {"owned": system(inside), "outside": system(outside), "ephemeral": system(inside, False)}
    module = types.SimpleNamespace(SharedSystemClient=types.SimpleNamespace(_identifier_to_system=cache))
    with patch.dict(sys.modules, {"chromadb.api.shared_system_client": module}):
        assert chroma_temp.close_systems_under(tmp_path / "temp") == 1
        assert events == [str(inside)]
        assert set(cache) == {"outside", "ephemeral"}


def test_cleanup_precedes_directory_removal():
    events = []
    with patch.object(chroma_temp, "close_systems_under", side_effect=lambda _: events.append("stop")):
        td = chroma_temp.ChromaTemporaryDirectory()
        path = Path(td.name)
        td.cleanup()
        assert events == ["stop"]
        assert not path.exists()


def test_real_chroma_temp_store_releases_and_reopens(tmp_path):
    import chromadb
    from chromadb.config import Settings
    from chromadb.api.shared_system_client import SharedSystemClient
    permanent = chromadb.PersistentClient(path=str(tmp_path / "permanent"), settings=Settings(anonymized_telemetry=False))
    keep = permanent.get_or_create_collection("permanent")
    keep.add(ids=["kept"], embeddings=[[1., 0.]])
    with chroma_temp.ChromaTemporaryDirectory() as td:
        client = chromadb.PersistentClient(path=td, settings=Settings(anonymized_telemetry=False))
        col = client.create_collection("temporary")
        col.add(ids=["real"], embeddings=[[1., 0.]])
        assert col.count() == 1
        assert any(Path(s.settings.persist_directory).resolve() == Path(td).resolve()
                   for s in SharedSystemClient._identifier_to_system.values() if s.settings.is_persistent)
    assert not Path(td).exists()
    assert all(Path(s.settings.persist_directory).resolve() != Path(td).resolve()
               for s in SharedSystemClient._identifier_to_system.values() if s.settings.is_persistent)
    assert keep.count() == 1  # unrelated real store remains usable
    chroma_temp.close_systems_under(tmp_path)


def page_fixture():
    import build_page_collection as BP
    chunk = {"chunk_id": "expected", "text": "actual evidence", "content_hash": "hash", "embedding_text": "embed"}
    fp = BP.chunks_fingerprint([chunk])
    manifest = {"vector_count": 1, "corpus_sha256": "corpus", "chunks_fingerprint": fp,
                "embedding_model": "all-MiniLM-L6-v2", "embedding_dimensions": 384,
                "chunk_strategy": "B_heading_200", "collection_name": "sap_pages_v1"}
    md = dict(manifest)
    snapshot = {"ids": ["expected"], "documents": ["actual evidence"],
                "metadatas": [{"content_hash": "hash", "embedding_text_sha256": hashlib.sha256(b"embed").hexdigest()}],
                "collection_metadata": md, "collection_name": "sap_pages_v1"}
    return [chunk], manifest, {"corpus_sha256": "corpus"}, snapshot


def test_diagnostic_correct_store_and_wrong_ids_same_count():
    args = page_fixture()
    assert compare_page_snapshot(*args)["all_pass"]
    args[-1]["ids"] = ["wrong"]
    result = compare_page_snapshot(*args)
    assert result["checks"]["count_equals_manifest"]
    assert not result["all_pass"]
    assert result["missing_ids"] == ["expected"]
    assert result["extra_ids"] == ["wrong"]


def test_diagnostic_115_vs_113_not_repaired_or_hidden():
    args = page_fixture()
    args[-1]["ids"].extend(["extra1", "extra2"])
    args[-1]["documents"].extend(["x", "y"])
    args[-1]["metadatas"].extend([{}, {}])
    result = compare_page_snapshot(*args)
    assert result["actual_count"] == 3 and result["expected_count"] == 1
    assert result["extra_ids"] == ["extra1", "extra2"]
    assert not result["all_pass"]
    assert args[-1]["ids"] == ["expected", "extra1", "extra2"]


@pytest.mark.parametrize("key,value", [("corpus_sha256", "old"), ("chunks_fingerprint", "old"), ("embedding_model", "other"), ("embedding_dimensions", 12), ("chunk_strategy", "other")])
def test_diagnostic_rejects_metadata_drift(key, value):
    args = page_fixture()
    args[-1]["collection_metadata"][key] = value
    assert not compare_page_snapshot(*args)["all_pass"]


def test_diagnostic_requires_explicit_quiescence(tmp_path):
    out = tmp_path / "result.json"
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_windows_verification.py"), "--out", str(out)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "Stop SURA/Chroma" in proc.stderr
    assert not out.exists()


def test_real_diagnostic_uses_child_copy_and_preserves_wrong_store(tmp_path):
    import chromadb
    from chromadb.config import Settings
    from diagnose_windows_verification import hashes, investigate
    source = tmp_path / "original"
    client = chromadb.PersistentClient(path=str(source), settings=Settings(anonymized_telemetry=False))
    col = client.create_collection("sap_pages_v1", metadata={"embedding_model": "other-model"})
    col.add(ids=["wrong-extra"], documents=["wrong evidence"], embeddings=[[1., 0.]])
    chroma_temp.close_systems_under(source)
    before = hashes(source)
    result = investigate(source, "page")
    assert result["worker_exit"] == 0
    assert result["actual_count"] == 1
    assert result["expected_count"] == 113
    assert result["extra_ids"] == ["wrong-extra"]
    assert not result["all_pass"]
    assert result["original_store_unchanged"]
    assert hashes(source) == before


@pytest.mark.parametrize("name,outputs", [
    ("build_phase8_queries", {"OUT": "data/evaluation/phase8_queries.json"}),
    ("build_phase9_queries", {"OUT": "data/evaluation/phase9_queries.json", "FREEZE": "data/evaluation/phase9_queries_freeze.json"}),
    ("phase9_corpus_audit", {"OUT_JSON": "data/phase9/corpus_status.json", "OUT_MD": "data/phase9/corpus_status.md"}),
])
def test_unsealed_generators_match_frozen_bytes_without_text_mode(name, outputs, tmp_path):
    module = importlib.import_module(name)
    targets = {key: tmp_path / Path(original).name for key, original in outputs.items()}
    # Copy the immutable inputs; no symlinks or writes into the source checkout.
    import shutil
    shutil.copytree(ROOT / "data", tmp_path / "data", ignore=shutil.ignore_patterns("vector_store"))
    shutil.copytree(ROOT / "captured_responses", tmp_path / "captured_responses")
    shutil.copy2(ROOT / "master_data.json", tmp_path / "master_data.json")
    shutil.copytree(ROOT / "sap_pages", tmp_path / "sap_pages")
    with patch.multiple(module, **targets), patch.object(module, "ROOT", tmp_path), patch.object(Path, "write_text", side_effect=AssertionError("native text mode forbidden")):
        assert module.main() == 0
    for key, original in outputs.items():
        assert targets[key].read_bytes() == (ROOT / original).read_bytes()


def test_page_corpus_lf_outputs_match_frozen_records(tmp_path):
    import page_corpus as PC
    payload = {"records": {r["doc_id"]: r for r in PC.load_records()},
               "manifest": json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8")),
               "fetch_plan": json.loads((PC.CORPUS_DIR / "fetch_plan.json").read_text(encoding="utf-8"))}
    with patch.object(Path, "write_text", side_effect=AssertionError("native text mode forbidden")):
        PC.write_corpus(payload, tmp_path)
    for path in (PC.CORPUS_DIR / "pages").glob("*/*.json"):
        assert (tmp_path / path.relative_to(PC.CORPUS_DIR)).read_bytes() == path.read_bytes()
    for name in ("manifest.json", "fetch_plan.json"):
        assert (tmp_path / name).read_bytes() == (PC.CORPUS_DIR / name).read_bytes()


def test_temp_finalizer_also_closes_real_chroma():
    import gc
    import chromadb
    from chromadb.config import Settings
    from chromadb.api.shared_system_client import SharedSystemClient
    td = chroma_temp.ChromaTemporaryDirectory()
    path = Path(td.name)
    client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
    client.create_collection("finalizer_store")
    del td
    gc.collect()
    assert not path.exists()
    assert all(Path(s.settings.persist_directory).resolve() != path.resolve()
               for s in SharedSystemClient._identifier_to_system.values() if s.settings.is_persistent)


# Stdlib-only unit cases can also run without importing the optional Chroma/
# evaluation dependencies; native integration cases below still require Chroma.
import unittest


class ChromaCleanupUnitTests(unittest.TestCase):
    class Clock:
        def __init__(self):
            self.now = 0.0
            self.waits = []

        def wait(self, duration):
            self.waits.append(duration)
            self.now += duration

    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.database = self.root / "chroma.sqlite3"
        self.database.write_bytes(b"owned unit fixture, not a real database")

    @staticmethod
    def windows_error(code):
        exc = OSError("simulated Win32 error")
        exc.winerror = code
        return exc

    def wait_for_release(self, probe, clock=None):
        clock = clock or self.Clock()
        with patch.object(chroma_temp, "_IS_WINDOWS", True), \
             patch.object(chroma_temp, "_windows_file_probe", return_value=probe), \
             patch.object(chroma_temp, "monotonic", side_effect=lambda: clock.now), \
             patch.object(chroma_temp, "Event", return_value=clock), \
             patch.object(chroma_temp, "_SQLITE_RELEASE_TIMEOUT", 0.025):
            chroma_temp._wait_for_sqlite_release(self.root)
        return clock

    def test_non_windows_never_loads_win32(self):
        with patch.object(chroma_temp, "_IS_WINDOWS", False), \
             patch.object(chroma_temp, "_windows_file_probe") as factory:
            chroma_temp._wait_for_sqlite_release(self.root)
        factory.assert_not_called()

    def test_released_file_has_no_unconditional_delay(self):
        calls = []
        clock = self.wait_for_release(lambda p: calls.append(p))
        self.assertEqual(calls, [self.database])
        self.assertEqual(clock.waits, [])

    def test_sharing_violation_waits_then_rechecks_resource(self):
        calls = []
        def probe(path):
            calls.append(path)
            if len(calls) < 3:
                raise self.windows_error(32)
        clock = self.wait_for_release(probe)
        self.assertEqual(calls, [self.database] * 3)
        self.assertEqual(clock.waits, [0.01, 0.01])

    def test_timeout_is_bounded_visible_and_preserves_file(self):
        clock = self.Clock()
        def locked(path):
            raise self.windows_error(32)
        with self.assertRaises(TimeoutError) as caught:
            self.wait_for_release(locked, clock)
        self.assertEqual(caught.exception.__cause__.winerror, 32)
        self.assertAlmostEqual(sum(clock.waits), 0.025)
        self.assertTrue(all(0 < d <= 0.01 for d in clock.waits))
        self.assertTrue(self.database.exists())

    def test_nonsharing_error_is_not_retried(self):
        clock = self.Clock()
        error = self.windows_error(5)
        def denied(path):
            raise error
        with self.assertRaises(OSError) as caught:
            self.wait_for_release(denied, clock)
        self.assertIs(caught.exception, error)
        self.assertEqual(clock.waits, [])

    def test_database_paths_share_one_deadline(self):
        child = self.root / "nested"; child.mkdir()
        (child / "chroma.sqlite3").write_bytes(b"second unit fixture")
        clock = self.Clock()
        calls = []
        def probe(path):
            calls.append(path)
            if path == self.database and calls.count(path) > 2:
                return
            raise self.windows_error(32)
        with self.assertRaises(TimeoutError):
            self.wait_for_release(probe, clock)
        self.assertIn(child / "chroma.sqlite3", calls)
        self.assertAlmostEqual(sum(clock.waits), 0.025)

    def test_probe_does_not_follow_paths_outside_owned_root(self):
        calls = []
        with patch.object(Path, "rglob", return_value=iter([self.root.parent / "chroma.sqlite3"])):
            self.wait_for_release(lambda p: calls.append(p))
        self.assertEqual(calls, [])

    def test_win32_signatures_exclusive_read_and_handle_close(self):
        import ctypes
        from ctypes import wintypes
        from unittest.mock import Mock
        kernel = types.SimpleNamespace(CreateFileW=Mock(return_value=123), CloseHandle=Mock(return_value=1))
        with patch.object(ctypes, "WinDLL", create=True, return_value=kernel) as load:
            probe = chroma_temp._windows_file_probe()
            probe(self.database)
        load.assert_called_once_with("kernel32", use_last_error=True)
        self.assertEqual(kernel.CreateFileW.argtypes,
                         [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE])
        self.assertIs(kernel.CreateFileW.restype, wintypes.HANDLE)
        self.assertEqual(kernel.CloseHandle.argtypes, [wintypes.HANDLE])
        self.assertIs(kernel.CloseHandle.restype, wintypes.BOOL)
        kernel.CreateFileW.assert_called_once_with(str(self.database), 0x80000000, 0, None, 3, 0x80, None)
        kernel.CloseHandle.assert_called_once_with(123)

    def test_invalid_win32_handle_uses_last_error_without_close(self):
        import ctypes
        from unittest.mock import Mock
        for code in (2, 3, 5, 32):
            with self.subTest(code=code):
                kernel = types.SimpleNamespace(CreateFileW=Mock(return_value=ctypes.c_void_p(-1).value),
                                               CloseHandle=Mock())
                with patch.object(ctypes, "WinDLL", create=True, return_value=kernel), \
                     patch.object(ctypes, "get_last_error", create=True, return_value=code), \
                     patch.object(ctypes, "WinError", create=True, side_effect=self.windows_error):
                    probe = chroma_temp._windows_file_probe()
                    if code in (2, 3):
                        probe(self.database)
                    else:
                        with self.assertRaises(OSError) as caught:
                            probe(self.database)
                        self.assertEqual(caught.exception.winerror, code)
                kernel.CloseHandle.assert_not_called()

    def test_win32_close_error_remains_visible(self):
        import ctypes
        from unittest.mock import Mock
        kernel = types.SimpleNamespace(CreateFileW=Mock(return_value=123), CloseHandle=Mock(return_value=0))
        with patch.object(ctypes, "WinDLL", create=True, return_value=kernel), \
             patch.object(ctypes, "get_last_error", create=True, return_value=6), \
             patch.object(ctypes, "WinError", create=True, side_effect=self.windows_error):
            with self.assertRaises(OSError) as caught:
                chroma_temp._windows_file_probe()(self.database)
        self.assertEqual(caught.exception.winerror, 6)
        kernel.CloseHandle.assert_called_once_with(123)

    def fake_cache(self, stop):
        owned = types.SimpleNamespace(settings=types.SimpleNamespace(is_persistent=True, persist_directory=str(self.root)), stop=stop)
        outside = types.SimpleNamespace(settings=types.SimpleNamespace(is_persistent=True, persist_directory=str(self.root.parent / "unrelated")))
        self.addCleanup(lambda: chroma_temp._FAILED_SHUTDOWNS.pop(id(owned), None))  # synthetic state only
        cache = {"owned": owned, "outside": outside}
        counts = {"owned": 2, "outside": 2}
        shared = types.SimpleNamespace(_identifier_to_system=cache, _identifier_to_refcount=counts)
        return types.SimpleNamespace(SharedSystemClient=shared), cache, counts

    def test_scoped_eviction_preserves_refcounts_and_other_system(self):
        events = []
        module, cache, counts = self.fake_cache(lambda: events.append("stop"))
        outside = cache["outside"]
        with patch.dict(sys.modules, {"chromadb.api.shared_system_client": module}), \
             patch.object(chroma_temp, "_wait_for_sqlite_release", side_effect=lambda p: events.append(p)):
            self.assertEqual(chroma_temp.close_systems_under(self.root), 1)
        self.assertEqual(events, ["stop", self.root])
        self.assertEqual(cache, {"outside": outside})
        self.assertEqual(counts, {"owned": 2, "outside": 2})

    def test_stop_error_does_not_evict_or_claim_file_release(self):
        def stop():
            raise RuntimeError("native stop failed")
        module, cache, _ = self.fake_cache(stop)
        with patch.dict(sys.modules, {"chromadb.api.shared_system_client": module}), \
             patch.object(chroma_temp, "_wait_for_sqlite_release") as wait:
            with self.assertRaisesRegex(RuntimeError, "native stop failed"):
                chroma_temp.close_systems_under(self.root)
        self.assertIn("owned", cache)
        wait.assert_not_called()

    def test_partial_stop_is_terminal_and_never_retried(self):
        calls = []
        def partial_stop():
            calls.append("bindings_deleted")
            raise RuntimeError("later component failed")
        module, cache, counts = self.fake_cache(partial_stop)
        failed = cache["owned"]
        with patch.dict(sys.modules, {"chromadb.api.shared_system_client": module}), \
             patch.object(chroma_temp, "_wait_for_sqlite_release") as wait:
            with self.assertRaisesRegex(RuntimeError, "later component failed"):
                chroma_temp.close_systems_under(self.root)
            for target in (self.root, self.root / "nested", self.root.parent):
                with self.assertRaisesRegex(RuntimeError, "restart the process"):
                    chroma_temp.close_systems_under(target)
        self.assertEqual(calls, ["bindings_deleted"])
        self.assertIs(cache["owned"], failed)
        self.assertEqual(counts, {"owned": 2, "outside": 2})
        self.assertTrue(self.database.exists())
        wait.assert_not_called()

    def test_failed_shutdown_does_not_block_unrelated_tree(self):
        def partial_stop():
            raise RuntimeError("partial stop")
        module, cache, _ = self.fake_cache(partial_stop)
        with patch.dict(sys.modules, {"chromadb.api.shared_system_client": module}), \
             patch.object(chroma_temp, "_wait_for_sqlite_release"):
            with self.assertRaises(RuntimeError):
                chroma_temp.close_systems_under(self.root)
            # Replace only the synthetic unrelated stop method, never real clients.
            events = []
            cache["outside"].stop = lambda: events.append("outside")
            self.assertEqual(chroma_temp.close_systems_under(self.root.parent / "unrelated"), 1)
            self.assertEqual(events, ["outside"])
            self.assertIn("owned", cache)

    def test_timeout_retry_rechecks_files_without_stopping_native_twice(self):
        events = []
        module, cache, _ = self.fake_cache(lambda: events.append("stop"))
        with patch.dict(sys.modules, {"chromadb.api.shared_system_client": module}), \
             patch.object(chroma_temp, "_wait_for_sqlite_release", side_effect=[TimeoutError("locked"), None]) as wait:
            with self.assertRaises(TimeoutError):
                chroma_temp.close_systems_under(self.root)
            self.assertEqual(chroma_temp.close_systems_under(self.root), 0)
        self.assertNotIn("owned", cache)
        self.assertEqual(events, ["stop"])
        self.assertEqual(wait.call_count, 2)

    def test_replaced_cache_entry_is_not_evicted(self):
        replacement = object()
        def stop():
            cache["owned"] = replacement
        module, cache, _ = self.fake_cache(stop)
        with patch.dict(sys.modules, {"chromadb.api.shared_system_client": module}):
            with self.assertRaisesRegex(RuntimeError, "cache changed"):
                chroma_temp.close_systems_under(self.root)
        self.assertIs(cache["owned"], replacement)

    def test_explicit_cleanup_failure_keeps_finalizer_and_is_retryable(self):
        td = chroma_temp.ChromaTemporaryDirectory(dir=self.root)
        self.addCleanup(td.cleanup)
        with patch.object(chroma_temp, "close_systems_under", side_effect=TimeoutError("locked")):
            with self.assertRaises(TimeoutError):
                td.cleanup()
            self.assertTrue(td._finalizer.alive)
            self.assertTrue(Path(td.name).exists())
        td.cleanup()
        self.assertFalse(Path(td.name).exists())
        self.assertFalse(td._finalizer.alive)

    def test_completed_cleanup_does_not_touch_reused_path(self):
        td = chroma_temp.ChromaTemporaryDirectory(dir=self.root)
        path = Path(td.name)
        td.cleanup()
        path.mkdir()
        with patch.object(chroma_temp, "close_systems_under") as stop:
            td.cleanup()
        stop.assert_not_called()
        self.assertTrue(path.exists())

    def test_weakref_finalizer_calls_scoped_shutdown(self):
        import gc
        import warnings
        td = chroma_temp.ChromaTemporaryDirectory(dir=self.root)
        path = Path(td.name)
        with patch.object(chroma_temp, "close_systems_under") as stop, warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            del td
            gc.collect()
        stop.assert_called_once_with(str(path))
        self.assertFalse(path.exists())

    def test_weakref_timeout_is_unraisable_not_false_success(self):
        import gc
        td = chroma_temp.ChromaTemporaryDirectory(dir=self.root)
        path = Path(td.name)
        errors = []
        with patch.object(chroma_temp, "close_systems_under", side_effect=TimeoutError("locked")), \
             patch.object(sys, "unraisablehook", side_effect=lambda args: errors.append(args.exc_value)):
            del td
            gc.collect()
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], TimeoutError)
        self.assertTrue(path.exists())


@pytest.mark.parametrize("mode", ["explicit", "finalizer"])
def test_real_owned_cleanup_retains_clients_and_isolates_other_store(tmp_path, mode):
    import gc
    import chromadb
    from chromadb.config import Settings
    from chromadb.api.shared_system_client import SharedSystemClient
    settings = Settings(anonymized_telemetry=False)
    permanent = chromadb.PersistentClient(path=str(tmp_path / "unrelated"), settings=settings)
    keep = permanent.create_collection("keep_alive", embedding_function=None)
    keep.add(ids=["kept"], embeddings=[[1., 0.]])
    td = chroma_temp.ChromaTemporaryDirectory(dir=tmp_path)
    path = Path(td.name)
    client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
    col = client.create_collection("owned_alive", embedding_function=None)
    col.add(ids=["owned"], embeddings=[[0., 1.]])
    outside_system = SharedSystemClient._identifier_to_system[permanent._identifier]
    try:
        if mode == "explicit":
            td.cleanup()
        else:
            del td
            gc.collect()
        assert not path.exists()
        assert client is not None and col is not None  # Strong references deliberately retained.
        assert keep.count() == 1
        assert SharedSystemClient._identifier_to_system[permanent._identifier] is outside_system
    finally:
        chroma_temp.close_systems_under(tmp_path)


@pytest.mark.parametrize("old_first", [True, False])
def test_real_same_path_reuse_old_close_does_not_stop_new_client(tmp_path, old_first):
    import chromadb
    from chromadb.config import Settings
    from chromadb.api.shared_system_client import SharedSystemClient
    store = tmp_path / "reusable"
    old = chromadb.PersistentClient(path=str(store), settings=Settings(anonymized_telemetry=False))
    old_collection = old.create_collection("reused_collection", embedding_function=None)
    old_collection.add(ids=["kept"], embeddings=[[1., 0.]])
    try:
        chroma_temp.close_systems_under(store)
        new = chromadb.PersistentClient(path=str(store), settings=Settings(anonymized_telemetry=False))
        new_system = SharedSystemClient._identifier_to_system[new._identifier]
        if old_first:
            old.close()
            old.close()  # Idempotent; must not decrement the new generation's count.
            assert new.get_collection("reused_collection", embedding_function=None).count() == 1
            assert SharedSystemClient._identifier_to_system[new._identifier] is new_system
            new.close()
        else:
            new.close()
            assert SharedSystemClient._identifier_to_system[new._identifier] is new_system
            old.close()
        assert new._identifier not in SharedSystemClient._identifier_to_system
        last = chromadb.PersistentClient(path=str(store), settings=Settings(anonymized_telemetry=False))
        old.close()
        new.close()
        assert last.get_collection("reused_collection", embedding_function=None).count() == 1
        last.close()
        assert last._identifier not in SharedSystemClient._identifier_to_system
        chroma_temp._wait_for_sqlite_release(store)
    finally:
        chroma_temp.close_systems_under(tmp_path)


@pytest.mark.skipif(sys.platform != "win32", reason="requires actual Windows sharing semantics")
def test_windows_sqlite_probe_observes_real_handle_release(tmp_path):
    import ctypes
    from ctypes import wintypes
    path = tmp_path / "chroma.sqlite3"
    path.write_bytes(b"owned handle fixture")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    probe = chroma_temp._windows_file_probe()
    try:
        with pytest.raises(OSError) as caught:
            probe(path)
        assert caught.value.winerror == 32
        with patch.object(chroma_temp, "_SQLITE_RELEASE_TIMEOUT", 0.025):
            with pytest.raises(TimeoutError):
                chroma_temp._wait_for_sqlite_release(tmp_path)
        assert path.exists()
    finally:
        assert close(handle)
    probe(path)  # Immediate success after the actual handle is closed.

    # A real handle stays open until the barrier actually observes contention.
    # This exercises release *during* the wait without a scheduler-dependent sleep.
    from threading import Event, Thread
    release = Event()
    errors = []
    handle = create(str(path), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    def worker():
        try:
            if not release.wait(5):
                errors.append(TimeoutError("probe never observed the held handle"))
        finally:
            if not close(handle):
                errors.append(ctypes.WinError(ctypes.get_last_error()))
    def observed_probe(target):
        try:
            probe(target)
        except OSError as exc:
            if exc.winerror == 32:
                release.set()
            raise
    thread = Thread(target=worker)
    thread.start()
    try:
        with patch.object(chroma_temp, "_windows_file_probe", return_value=observed_probe):
            chroma_temp._wait_for_sqlite_release(tmp_path)
        assert release.is_set()
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert errors == []
    path.unlink()
    assert not path.exists()
