"""StorageBackend Protocol + LocalStorageBackend — invoice image storage abstraction.

Citations:
- D-07: StorageBackend interface: save(data, filename) -> relative_path
- D-08: Storage root from settings.storage_path (STORAGE_PATH env var, default /data/invoices)
- D-09: Caller constructs the full relative path: '{invoice_uuid}/{original_basename}'
- T-02-01: Path-traversal mitigation — per-component split/filter of '.' and '..' segments,
           plus defense-in-depth realpath check.

Contract (FINAL per 02-01-PLAN.md interfaces section):
  - The caller (ExtractionService) constructs the full relative path:
    "{invoice_uuid}/{basename_of_filename}"
  - save() splits on '/', drops empty components and any '.' or '..' segments,
    reassembles, and writes to os.path.join(root, relative_path).
  - Defense-in-depth: os.path.commonpath([realpath(full_path), realpath(root)]) must equal
    realpath(root); ValueError raised otherwise.
  - Parent directories are auto-created via os.makedirs(..., exist_ok=True).
  - Returns the sanitized relative_path string.

Why Protocol over ABC (RESEARCH.md Pattern 2):
  - No forced inheritance — LocalStorageBackend satisfies Protocol structurally.
  - @runtime_checkable allows isinstance(backend, StorageBackend) in tests.
  - Matches established Python service-layer pattern.
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Interface for invoice image storage. Phase 2: save only. delete() is Phase 4."""

    def save(self, data: bytes, filename: str) -> str:
        """Save data to storage. Returns relative path."""
        ...


class LocalStorageBackend:
    """Filesystem implementation of StorageBackend.

    Storage root is constructed from settings.storage_path (STORAGE_PATH env var,
    default /data/invoices). The UUID prefix is the CALLER's responsibility.

    Path-traversal sanitization (T-02-01):
      Per-component split and filter — '.' and '..' segments are dropped entirely.
      No directory-part reconstruction (avoids review HIGH #1 bug from prior plan version).
      Defense-in-depth: realpath commonpath check raises ValueError on any escape.
    """

    def __init__(self, root: str) -> None:
        self._root = root

    def save(self, data: bytes, filename: str) -> str:
        """Save bytes to '{root}/{sanitized_relative_path}'. Returns relative path.

        Sanitization algorithm (FINAL contract):
        1. Normalize backslashes to forward slashes.
        2. Split into components on '/'.
        3. Drop empty strings, '.' and '..' segments.
        4. If no safe parts remain, raise ValueError.
        5. Join safe parts back into a relative_path string.
        6. Compute full_path = os.path.join(self._root, relative_path).
        7. Defense-in-depth: assert full_path does not escape self._root via realpath.
        8. Auto-create parent directories.
        9. Write bytes; return relative_path.
        """
        # Step 1-2: normalize and split
        normalized = filename.replace("\\", "/")
        parts = normalized.split("/")

        # Step 3: reject traversal tokens immediately; drop empty strings and "."
        safe_parts = []
        for p in parts:
            if p == "..":
                raise ValueError(
                    f"filename {filename!r} contains path traversal component '..'"
                )
            if p and p != ".":
                safe_parts.append(p)

        # Step 4: nothing left after sanitization
        if not safe_parts:
            raise ValueError(
                f"filename {filename!r} has no valid component after sanitization"
            )

        # Step 5: reassemble
        relative_path = "/".join(safe_parts)

        # Step 6: absolute target path
        full_path = os.path.join(self._root, relative_path)

        # Step 7: defense-in-depth — reject any path that escapes the storage root
        real_root = os.path.realpath(self._root)
        real_full = os.path.realpath(full_path)
        try:
            common = os.path.commonpath([real_full, real_root])
        except ValueError:
            # On Windows, commonpath raises ValueError for paths on different drives
            raise ValueError(
                f"path escapes storage root: {full_path!r} not under {self._root!r}"
            )
        if common != real_root:
            raise ValueError(
                f"path escapes storage root: {full_path!r} not under {self._root!r}"
            )

        # Step 8: auto-create parent directories
        parent = os.path.dirname(full_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        # Step 9: write and return
        with open(full_path, "wb") as fh:
            fh.write(data)

        return relative_path
