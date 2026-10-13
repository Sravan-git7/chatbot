"""Optional process metrics; unsupported is None, never a fabricated zero."""
import sys


def peak_rss_mb():
    try:
        import resource
    except ImportError:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports KiB. Windows has no resource module.
    return round(value / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
