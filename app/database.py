from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import settings


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    return conn.execute(sql, tuple(params))


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',
  persona_id TEXT,
  avatar_color TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS boards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  icon TEXT NOT NULL DEFAULT '',
  digest_level TEXT NOT NULL DEFAULT 'snippet',
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  board_id INTEGER NOT NULL REFERENCES boards(id),
  title TEXT NOT NULL,
  author_user_id INTEGER NOT NULL REFERENCES users(id),
  created_by_user_id INTEGER NOT NULL REFERENCES users(id),
  submitter_identity_id INTEGER REFERENCES users(id),
  source_channel TEXT,
  source_message_id TEXT,
  source_submission_id TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  is_pinned INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES threads(id),
  parent_post_id INTEGER REFERENCES posts(id),
  author_user_id INTEGER NOT NULL REFERENCES users(id),
  created_by_user_id INTEGER NOT NULL REFERENCES users(id),
  quoted_excerpt TEXT,
  body_markdown TEXT NOT NULL,
  body_html TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'visible',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_threads_board_updated ON threads(board_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_thread_created ON posts(thread_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_tokens_hash ON tokens(token_hash);

CREATE TABLE IF NOT EXISTS invites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code_hash TEXT NOT NULL UNIQUE,
  created_by_user_id INTEGER REFERENCES users(id),
  default_role TEXT NOT NULL DEFAULT 'guest',
  allowed_boards TEXT NOT NULL DEFAULT '[]',
  digest_scope TEXT,
  requires_approval INTEGER NOT NULL DEFAULT 1,
  max_uses INTEGER NOT NULL DEFAULT 1,
  used_count INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT,
  notes TEXT NOT NULL DEFAULT '',
  revoked_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    ensure_schema_migrations(conn)
    conn.commit()


def ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "password_hash" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if "password_changed_at" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN password_changed_at TEXT")
    if "avatar_emoji" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_emoji TEXT")

    board_columns = {row["name"] for row in conn.execute("PRAGMA table_info(boards)").fetchall()}
    if "digest_level" not in board_columns:
        conn.execute("ALTER TABLE boards ADD COLUMN digest_level TEXT NOT NULL DEFAULT 'snippet'")

    thread_columns = {row["name"] for row in conn.execute("PRAGMA table_info(threads)").fetchall()}
    if "submitter_identity_id" not in thread_columns:
        conn.execute("ALTER TABLE threads ADD COLUMN submitter_identity_id INTEGER REFERENCES users(id)")
    if "source_channel" not in thread_columns:
        conn.execute("ALTER TABLE threads ADD COLUMN source_channel TEXT")
    if "source_message_id" not in thread_columns:
        conn.execute("ALTER TABLE threads ADD COLUMN source_message_id TEXT")
    if "source_submission_id" not in thread_columns:
        conn.execute("ALTER TABLE threads ADD COLUMN source_submission_id TEXT")
    if "edited_at" not in thread_columns:
        conn.execute("ALTER TABLE threads ADD COLUMN edited_at TEXT")
    if "edited_by_user_id" not in thread_columns:
        conn.execute("ALTER TABLE threads ADD COLUMN edited_by_user_id INTEGER REFERENCES users(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_threads_submitter ON threads(submitter_identity_id, updated_at DESC)")

    post_columns = {row["name"] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    if "parent_post_id" not in post_columns:
        conn.execute("ALTER TABLE posts ADD COLUMN parent_post_id INTEGER REFERENCES posts(id)")
    if "quoted_excerpt" not in post_columns:
        conn.execute("ALTER TABLE posts ADD COLUMN quoted_excerpt TEXT")
    if "edited_at" not in post_columns:
        conn.execute("ALTER TABLE posts ADD COLUMN edited_at TEXT")
    if "edited_by_user_id" not in post_columns:
        conn.execute("ALTER TABLE posts ADD COLUMN edited_by_user_id INTEGER REFERENCES users(id)")
