"""Unit tests for LocalStorageBackend.save() — path construction, directory creation,
and path-traversal sanitization (T-02-01).

These tests cover the FINAL contract from 02-01-PLAN.md:
- Per-component split/filter of "." and ".." segments
- Defense-in-depth realpath check
- Auto-creation of parent directories
- Returns relative path that was written

Run: cd backend && python -m pytest tests/test_storage.py -x -q
"""
import pathlib

import pytest

from app.services.storage import LocalStorageBackend  # RED: ImportError until Task 2


def test_save_writes_bytes_and_returns_relative_path(tmp_path):
    """save(bytes, 'abc-uuid/photo.jpg') writes the bytes and returns the relative path."""
    backend = LocalStorageBackend(root=str(tmp_path))
    result = backend.save(b"hello", "abc-uuid/photo.jpg")

    assert result == "abc-uuid/photo.jpg"
    written = tmp_path / "abc-uuid" / "photo.jpg"
    assert written.exists()
    assert written.read_bytes() == b"hello"


def test_save_creates_parent_directories(tmp_path):
    """save() auto-creates the directory '{tmp_path}/abc-uuid/' when it does not exist."""
    backend = LocalStorageBackend(root=str(tmp_path))
    backend.save(b"data", "abc-uuid/invoice.jpg")

    assert (tmp_path / "abc-uuid").is_dir()


def test_save_rejects_path_traversal(tmp_path):
    """save(b'x', '../../etc/passwd') raises ValueError on '..' component.

    CR-01: raise immediately on traversal rather than silently rewriting.
    T-02-01 mitigation.
    """
    backend = LocalStorageBackend(root=str(tmp_path))
    with pytest.raises(ValueError, match="path traversal"):
        backend.save(b"x", "../../etc/passwd")

    # Verify no file was written anywhere under tmp_path
    assert not list(pathlib.Path(tmp_path).rglob("*"))


def test_save_with_uuid_prefix_and_traversal_filename(tmp_path):
    """save(b'x', 'uuid-xxx/../../bad') raises ValueError on '..' component.

    CR-01: raise immediately when '..' is detected anywhere in the path.
    """
    backend = LocalStorageBackend(root=str(tmp_path))
    with pytest.raises(ValueError, match="path traversal"):
        backend.save(b"x", "uuid-xxx/../../bad")


def test_save_rejects_only_dot_segments(tmp_path):
    """save(b'x', '../..') raises ValueError on '..' traversal component."""
    backend = LocalStorageBackend(root=str(tmp_path))
    with pytest.raises(ValueError, match="path traversal"):
        backend.save(b"x", "../..")


def test_save_returns_correct_relative_path_for_uuid_prefix(tmp_path):
    """save(b'd', 'some-uuid-123/photo.jpg') returns 'some-uuid-123/photo.jpg'."""
    backend = LocalStorageBackend(root=str(tmp_path))
    result = backend.save(b"d", "some-uuid-123/photo.jpg")

    assert result == "some-uuid-123/photo.jpg"
    assert (tmp_path / "some-uuid-123" / "photo.jpg").read_bytes() == b"d"
