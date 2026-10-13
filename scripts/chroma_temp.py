"""Release Chroma systems owned by an ephemeral directory before OS cleanup.

PersistentClient systems are cached process-wide, beyond Python client lifetime.
This adapter targets Chroma's SharedSystemClient cache (tested with 1.5.9).
It never resets/deletes collections and never closes systems outside the given
owned temporary tree. Cleanup errors propagate; ignore_cleanup_errors is not used.
"""
from pathlib import Path
import sys
import tempfile


def close_systems_under(directory):
    module = sys.modules.get("chromadb.api.shared_system_client")
    if module is None:
        return 0
    cache = module.SharedSystemClient._identifier_to_system
    root = Path(directory).resolve()
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
        system.stop()
        if cache.get(identifier) is system:
            del cache[identifier]
    return len(owned)


class ChromaTemporaryDirectory(tempfile.TemporaryDirectory):
    """Use for ephemeral stores only; persistent production clients are untouched."""
    def cleanup(self):
        close_systems_under(self.name)
        super().cleanup()

    @classmethod
    def _cleanup(cls, name, *args, **kwargs):
        # weakref finalizer/GC follows a separate path in Python's tempfile.
        # Forward version-specific options unchanged (Python 3.10 and later).
        close_systems_under(name)
        super()._cleanup(name, *args, **kwargs)
