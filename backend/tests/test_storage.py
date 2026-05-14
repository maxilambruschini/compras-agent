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


def test_save_sanitizes_path_traversal(tmp_path):
    """save(b'x', '../../etc/passwd') must NOT write any file above tmp_path.

    Per the FINAL contract: ".." segments are dropped. The result is
    '{tmp_path}/etc/passwd' — NOT any path escaping tmp_path.
    T-02-01 mitigation.
    """
    backend = LocalStorageBackend(root=str(tmp_path))
    result = backend.save(b"x", "../../etc/passwd")

    # Verify no file was written ABOVE tmp_path
    for entry in pathlib.Path(tmp_path).rglob("*"):
        assert entry.is_relative_to(tmp_path), (
            f"File was written outside tmp_path: {entry}"
        )

    # The ".." segments are dropped; remaining parts are "etc" and "passwd"
    # So the file lands at tmp_path/etc/passwd
    assert result == "etc/passwd"
    assert (tmp_path / "etc" / "passwd").exists()


def test_save_with_uuid_prefix_and_traversal_filename(tmp_path):
    """save(b'x', 'uuid-xxx/../../bad') drops both '..' segments.

    Result: 'uuid-xxx/bad' is written to '{tmp_path}/uuid-xxx/bad'.
    No file resolves above tmp_path.
    """
    backend = LocalStorageBackend(root=str(tmp_path))
    result = backend.save(b"x", "uuid-xxx/../../bad")

    # No file above tmp_path
    for entry in pathlib.Path(tmp_path).rglob("*"):
        assert entry.is_relative_to(tmp_path), (
            f"File was written outside tmp_path: {entry}"
        )

    # After dropping ".." segments from ["uuid-xxx", "..", "..", "bad"],
    # the safe_parts are ["uuid-xxx", "bad"] — both ".." are dropped.
    assert result == "uuid-xxx/bad"
    matches = list(pathlib.Path(tmp_path).rglob("bad"))
    assert len(matches) == 1
    assert matches[0].is_relative_to(tmp_path)


def test_save_rejects_only_dot_segments(tmp_path):
    """save(b'x', '../..') raises ValueError — no valid component after sanitization."""
    backend = LocalStorageBackend(root=str(tmp_path))
    with pytest.raises(ValueError, match="no valid component"):
        backend.save(b"x", "../..")


def test_save_returns_correct_relative_path_for_uuid_prefix(tmp_path):
    """save(b'd', 'some-uuid-123/photo.jpg') returns 'some-uuid-123/photo.jpg'."""
    backend = LocalStorageBackend(root=str(tmp_path))
    result = backend.save(b"d", "some-uuid-123/photo.jpg")

    assert result == "some-uuid-123/photo.jpg"
    assert (tmp_path / "some-uuid-123" / "photo.jpg").read_bytes() == b"d"
