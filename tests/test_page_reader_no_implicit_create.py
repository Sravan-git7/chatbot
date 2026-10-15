"""Every supported page reader must reject absent databases before constructing a client."""

from unittest.mock import Mock, patch

import owned_retrieval as OWN
import page_retriever as PR
import pytest


@pytest.mark.parametrize("reader", [PR.PageRetriever, OWN.OwnedPageRetriever])
@pytest.mark.parametrize("existing_empty_directory", [False, True])
def test_page_reader_does_not_create_database_in_missing_or_empty_path(
    tmp_path, reader, existing_empty_directory
):
    path = tmp_path / "page-store"
    if existing_empty_directory:
        path.mkdir()
    client = Mock(
        side_effect=AssertionError("must reject before SDK database construction")
    )
    with patch("chromadb.PersistentClient", client):
        with pytest.raises(
            FileNotFoundError, match="implicit database creation is forbidden"
        ):
            reader.from_store(path, embed=Mock())
    client.assert_not_called()
    assert path.exists() is existing_empty_directory
    assert list(tmp_path.rglob("chroma.sqlite3")) == []
    if path.exists():
        assert list(path.iterdir()) == []
