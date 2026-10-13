"""Real-Chroma temporary store ownership for the sealed legacy tests.

The frozen tests cannot be edited without changing their SHA-256 pins. Supply a
resource-lifecycle fixture, NOT a fake store, skipped assertion, or changed result.
Only TemporaryDirectory instances created during this test session use the scoped
cleanup adapter; production stores outside those trees are never stopped.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from chroma_temp import ChromaTemporaryDirectory


@pytest.fixture(scope="session", autouse=True)
def chroma_temporary_store_lifecycle():
    original = tempfile.TemporaryDirectory
    tempfile.TemporaryDirectory = ChromaTemporaryDirectory
    try:
        yield
    finally:
        tempfile.TemporaryDirectory = original
