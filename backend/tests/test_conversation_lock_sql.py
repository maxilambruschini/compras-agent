"""Compiled-SQL assertion that pins the FOR NO KEY UPDATE lock-strength contract.

This test is entirely offline — no DB engine, no session, no network.
It compiles select(Conversation).with_for_update(key_share=True) against
the PostgreSQL dialect and asserts the emitted SQL ends with the exact
string 'FOR NO KEY UPDATE'.

Why this test exists
--------------------
SQLAlchemy 2.0.x mapping of with_for_update() kwargs to Postgres lock modes:

    key_share=False (default)                → FOR UPDATE
    key_share=True                           → FOR NO KEY UPDATE   ← this project
    read=True, key_share=False               → FOR SHARE
    read=True, key_share=True                → FOR KEY SHARE

The project requires FOR NO KEY UPDATE (not FOR UPDATE) because it must not
block concurrent FK-referencing child table inserts (CONV-03 / RESEARCH Pattern 5).

This test FAILS LOUDLY if a SQLAlchemy upgrade silently changes the emitted lock
mode, because SQLite-based unit tests silently ignore row locks and would not catch
such a regression.

Plan reference: 01-04 Task 0, success criterion 3, Lock-strength contract section.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.models import Conversation


def test_with_for_update_key_share_emits_for_no_key_update() -> None:
    """select(Conversation).with_for_update(key_share=True) compiles to FOR NO KEY UPDATE.

    SQLAlchemy 2.0.x kwargs → Postgres lock mode mapping (empirically verified):
      key_share=True   → FOR NO KEY UPDATE   (this project's chosen lock)
      key_share=False  → FOR UPDATE          (stronger; blocks child-table inserts)
      read=True, key_share=True → FOR KEY SHARE  (weaker shared lock)
      read=True        → FOR SHARE
    """
    stmt = select(Conversation).with_for_update(key_share=True)
    compiled_sql = str(stmt.compile(dialect=postgresql.dialect()))

    # Primary assertion: correct lock mode is present
    assert "FOR NO KEY UPDATE" in compiled_sql, (
        f"Expected 'FOR NO KEY UPDATE' in compiled SQL, got:\n{compiled_sql}\n\n"
        "This means SQLAlchemy changed the key_share=True mapping. "
        "Audit the lock mode before deploying — the project requires FOR NO KEY UPDATE."
    )

    # Guard: must NOT contain FOR KEY SHARE (which would be read=True, key_share=True)
    assert "FOR KEY SHARE" not in compiled_sql, (
        f"Found 'FOR KEY SHARE' in compiled SQL — that is the read=True,key_share=True "
        f"mapping (a shared lock), not the FOR NO KEY UPDATE exclusive lock this project requires."
    )

    # Guard: the SQL must NOT end with bare 'FOR UPDATE' (key_share=False mapping).
    # Use regex to avoid matching the 'FOR UPDATE' substring inside 'FOR NO KEY UPDATE'.
    assert not re.search(r"\bFOR UPDATE\s*$", compiled_sql), (
        f"Found bare 'FOR UPDATE' at end of compiled SQL — that is the key_share=False "
        f"(stronger) lock. The project requires the weaker 'FOR NO KEY UPDATE'."
    )
