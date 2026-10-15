"""Release Chroma systems owned by an ephemeral directory before OS cleanup.

PersistentClient systems are cached process-wide, beyond Python client lifetime.
This adapter targets Chroma's SharedSystemClient cache (1.5.9 lifecycle).
It never resets/deletes collections and never closes systems outside the given
owned temporary tree. Cleanup errors propagate; ignore_cleanup_errors is not used.
The caller must exclusively own the tree: no concurrent client creation or use
inside it during shutdown. Chroma's private cache is not a shutdown lock.
"""
from pathlib import Path
import sys
import tempfile
from threading import Event
from time import monotonic


_IS_WINDOWS = sys.platform == "win32"
_SQLITE_RELEASE_TIMEOUT = 5.0
_SQLITE_POLL_INTERVAL = 0.01
# Failed stop() is terminal: components may already be stopped and Rust stop()
# is not idempotent. Keep strong diagnostic state, never silently resume/delete.
_FAILED_SHUTDOWNS = {}


def _reject_failed_shutdown(root):
    owners = sys.modules.get("owned_retrieval")
    if owners is not None:
        owners.assert_path_reusable(root)
    for path, system in _FAILED_SHUTDOWNS.values():
        if path == root or root in path.parents or path in root.parents:
            raise RuntimeError("Previous owned Chroma shutdown failed; preserve the tree and restart the process before reuse")


def _windows_file_probe():
    """Build a read-only exclusive-open probe, with pointer-sized Win32 handles."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                           wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    invalid_handle = ctypes.c_void_p(-1).value

    def probe(path):
        # GENERIC_READ, no sharing, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL.
        # Never creates/truncates/writes the database or closes another handle.
        handle = create_file(str(path), 0x80000000, 0, None, 3, 0x80, None)
        if handle == invalid_handle:
            error = ctypes.get_last_error()
            if error in (2, 3):  # Already absent: no file needs removal.
                return
            raise ctypes.WinError(error)
        if not close_handle(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    return probe


def _wait_for_sqlite_release(directory):
    """Wait only for owned SQLite sharing violations, under one finite deadline.

    RustBindingsAPI.stop() drops its bindings; it does not explicitly await SQLx
    SQLite worker termination. Event.wait bounds each polling interval without
    busy spinning. This is a resource check, not an unconditional cleanup delay.
    Other errors and a timed-out sharing violation remain visible to the caller.
    """
    if not _IS_WINDOWS:
        return
    root = Path(directory).resolve()
    deadline = monotonic() + _SQLITE_RELEASE_TIMEOUT
    probe = _windows_file_probe()
    pause = Event()
    # Also check on a retry after cache eviction: a prior timeout must not make
    # the next cleanup falsely assume that the stopped system released its file.
    for path in root.rglob("chroma.sqlite3"):
        if path.is_symlink() or root not in path.resolve().parents:
            continue  # Do not probe a symlink/junction target outside our tree.
        while True:
            try:
                probe(path)
                break
            except OSError as exc:
                if getattr(exc, "winerror", None) != 32:
                    raise
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for owned SQLite file release: {path}") from exc
                pause.wait(min(_SQLITE_POLL_INTERVAL, remaining))


def close_systems_under(directory):
    """Force-stop exclusively owned temporary systems, not arbitrary clients.

    Retained clients become unusable after shutdown. Keep Chroma 1.5.9's client
    refcounts intact: old Client.close() calls still decrement them. Removing
    those counts could let an old client stop a newly opened same-path system.
    Sequential reuse requires eventually closing retained clients. Abandoning
    them without close() can leave SDK refcounts behind; resetting those counts
    here would be unsafe. Concurrent reuse is not supported by Chroma's cache
    lifecycle and must not be attempted. A component-stop failure is terminal:
    keep the cached failed system for diagnosis, block further cleanup of that
    tree, and require process restart. Do not call Client.close()/PersistentClient
    on that failed path: the SDK itself has no safe partial-stop recovery API.
    """
    root = Path(directory).resolve()
    _reject_failed_shutdown(root)
    module = sys.modules.get("chromadb.api.shared_system_client")
    if module is None:
        return 0
    cache = module.SharedSystemClient._identifier_to_system
    owned = []
    for identifier, system in list(cache.items()):
        # Only persistent systems have a filesystem path; ephemeral/http IDs
        # must not be interpreted as directories.
        settings = system.settings
        if not settings.is_persistent:
            continue
        path = Path(settings.persist_directory).resolve()
        if path == root or root in path.parents:
            owned.append((identifier, system))
    for identifier, system in owned:
        if cache.get(identifier) is not system:
            raise RuntimeError("Chroma cache changed during owned temporary shutdown")
        try:
            system.stop()
        except BaseException:
            _FAILED_SHUTDOWNS[id(system)] = (Path(system.settings.persist_directory).resolve(), system)
            raise
        if module.SharedSystemClient._identifier_to_system is not cache or cache.get(identifier) is not system:
            _FAILED_SHUTDOWNS[id(system)] = (Path(system.settings.persist_directory).resolve(), system)
            raise RuntimeError("Chroma cache changed during owned temporary shutdown")
        del cache[identifier]
    _wait_for_sqlite_release(root)
    return len(owned)


class ChromaTemporaryDirectory(tempfile.TemporaryDirectory):
    """Use for ephemeral stores only; persistent production clients are untouched."""
    def cleanup(self):
        if getattr(self, "_chroma_cleanup_complete", False):
            return  # A repeated cleanup must not close a later same-path system.
        close_systems_under(self.name)
        super().cleanup()
        self._chroma_cleanup_complete = True

    @classmethod
    def _cleanup(cls, name, *args, **kwargs):
        # weakref finalizer/GC follows a separate path in Python's tempfile.
        # Forward version-specific options unchanged (Python 3.10 and later).
        close_systems_under(name)
        super()._cleanup(name, *args, **kwargs)
