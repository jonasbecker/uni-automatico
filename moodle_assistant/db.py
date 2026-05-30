"""db.py — SQLite layer: schema, upserts, queries, and state.json migration."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from moodle_assistant.appconfig import DB_PATH, STATE_PATH, load_state

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    moodle_course_id  INTEGER UNIQUE,
    name              TEXT NOT NULL,
    priority          INTEGER DEFAULT 3
);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER NOT NULL REFERENCES courses(id),
    type        TEXT NOT NULL,
    cmid        INTEGER,
    title       TEXT NOT NULL,
    path        TEXT,
    url         TEXT,
    due_date    TEXT,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new',
    UNIQUE(type, cmid)
);

CREATE TABLE IF NOT EXISTS exams (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id  INTEGER REFERENCES courses(id),
    name       TEXT NOT NULL,
    date       TEXT
);

CREATE TABLE IF NOT EXISTS plan_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at  TEXT NOT NULL,
    plan_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_due    ON items(due_date);
CREATE INDEX IF NOT EXISTS idx_items_course ON items(course_id);
"""


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _now_local_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def epoch_to_utc_iso(ts: int) -> str:
    """Convert a unix epoch to a fixed-format ISO-8601 UTC string (sorts correctly)."""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Connection & schema                                                           #
# --------------------------------------------------------------------------- #

def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    migrate_state_if_needed(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    conn.commit()


# --------------------------------------------------------------------------- #
# Meta                                                                          #
# --------------------------------------------------------------------------- #

def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# --------------------------------------------------------------------------- #
# Courses                                                                       #
# --------------------------------------------------------------------------- #

def upsert_course(
    conn: sqlite3.Connection,
    moodle_course_id: int,
    name: str,
    priority: int = 3,
) -> int:
    """Insert/refresh a course by moodle_course_id. Adopts a name-matched
    placeholder (from migration) if its moodle_course_id is still NULL."""
    row = conn.execute(
        "SELECT id FROM courses WHERE moodle_course_id = ?", (moodle_course_id,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE courses SET name = ? WHERE id = ?", (name, row["id"])
        )
        return row["id"]

    # Adopt a placeholder created by migration (same name, no moodle id yet).
    placeholder = conn.execute(
        "SELECT id FROM courses WHERE moodle_course_id IS NULL AND name = ?",
        (name,),
    ).fetchone()
    if placeholder:
        conn.execute(
            "UPDATE courses SET moodle_course_id = ?, priority = ? WHERE id = ?",
            (moodle_course_id, priority, placeholder["id"]),
        )
        return placeholder["id"]

    cur = conn.execute(
        "INSERT INTO courses(moodle_course_id, name, priority) VALUES(?, ?, ?)",
        (moodle_course_id, name, priority),
    )
    return cur.lastrowid


def upsert_course_by_name(conn: sqlite3.Connection, name: str) -> int:
    """Return id of a course matched by name; create a NULL-moodle-id placeholder."""
    row = conn.execute(
        "SELECT id FROM courses WHERE name = ? ORDER BY id LIMIT 1", (name,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO courses(moodle_course_id, name) VALUES(NULL, ?)", (name,)
    )
    return cur.lastrowid


# --------------------------------------------------------------------------- #
# Items                                                                         #
# --------------------------------------------------------------------------- #

def upsert_item(
    conn: sqlite3.Connection,
    *,
    course_id: int,
    type: str,
    cmid: int,
    title: str,
    url: Optional[str] = None,
    path: Optional[str] = None,
    due_date: Optional[str] = None,
    status_if_new: str = "new",
) -> tuple[int, bool]:
    """Insert-or-update keyed on (type, cmid).

    New row → status=status_if_new, created_at=now, returns (id, True).
    Existing → refresh title/url/path/due_date, PRESERVE status/created_at,
    returns (id, False).
    """
    row = conn.execute(
        "SELECT id FROM items WHERE type = ? AND cmid = ?", (type, cmid)
    ).fetchone()
    if row:
        item_id = row["id"]
        conn.execute(
            "UPDATE items SET title = ?, "
            "url = COALESCE(?, url), "
            "path = COALESCE(?, path), "
            "due_date = COALESCE(?, due_date), "
            "course_id = ? "
            "WHERE id = ?",
            (title, url, path, due_date, course_id, item_id),
        )
        return item_id, False

    cur = conn.execute(
        "INSERT INTO items(course_id, type, cmid, title, url, path, due_date, "
        "created_at, status) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (course_id, type, cmid, title, url, path, due_date,
         _now_local_iso(), status_if_new),
    )
    return cur.lastrowid, True


def set_item_path(conn: sqlite3.Connection, item_id: int, path: str) -> None:
    conn.execute("UPDATE items SET path = ? WHERE id = ?", (path, item_id))


def mark_status(conn: sqlite3.Connection, item_id: int, status: str) -> None:
    conn.execute("UPDATE items SET status = ? WHERE id = ?", (status, item_id))


def mark_seen_all_new(conn: sqlite3.Connection) -> int:
    cur = conn.execute("UPDATE items SET status = 'seen' WHERE status = 'new'")
    conn.commit()
    return cur.rowcount


def count_new(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE status = 'new'"
    ).fetchone()
    return row["n"]


# --------------------------------------------------------------------------- #
# Exams                                                                         #
# --------------------------------------------------------------------------- #

def add_exam(
    conn: sqlite3.Connection,
    course_name: str,
    name: str,
    date: str,
) -> int:
    course_id = upsert_course_by_name(conn, course_name)
    cur = conn.execute(
        "INSERT INTO exams(course_id, name, date) VALUES(?, ?, ?)",
        (course_id, name, date),
    )
    conn.commit()
    return cur.lastrowid


def replace_exams(conn: sqlite3.Connection, exams: list[dict]) -> None:
    """Rebuild the exams table from a config list of {course, name, date}."""
    conn.execute("DELETE FROM exams")
    for e in exams:
        course_id = upsert_course_by_name(conn, e.get("course", "Unbekannt"))
        conn.execute(
            "INSERT INTO exams(course_id, name, date) VALUES(?, ?, ?)",
            (course_id, e.get("name", "Klausur"), e.get("date")),
        )
    conn.commit()


# --------------------------------------------------------------------------- #
# Queries for `today`                                                           #
# --------------------------------------------------------------------------- #

def get_new_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT i.*, c.name AS course_name FROM items i "
        "JOIN courses c ON c.id = i.course_id "
        "WHERE i.status = 'new' "
        "ORDER BY i.created_at DESC"
    ).fetchall()


def get_upcoming_deadlines(
    conn: sqlite3.Connection,
    within_days: int = 14,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Merge assignment due dates + exam dates within the window, sorted ascending.

    Returns dicts with keys: kind ('assignment'|'exam'), title, course_name,
    due (ISO-8601 UTC string), url.
    """
    now = now or datetime.now(tz=timezone.utc)
    lo = now.isoformat(timespec="seconds")
    hi = datetime.fromtimestamp(
        now.timestamp() + within_days * 86400, tz=timezone.utc
    ).isoformat(timespec="seconds")

    results: list[dict] = []

    for r in conn.execute(
        "SELECT i.title, i.due_date, i.url, c.name AS course_name FROM items i "
        "JOIN courses c ON c.id = i.course_id "
        "WHERE i.type = 'assignment' AND i.due_date IS NOT NULL "
        "AND i.status != 'done' AND i.due_date BETWEEN ? AND ? "
        "ORDER BY i.due_date ASC",
        (lo, hi),
    ).fetchall():
        results.append({
            "kind": "assignment",
            "title": r["title"],
            "course_name": r["course_name"],
            "due": r["due_date"],
            "url": r["url"],
        })

    # Exams stored as plain YYYY-MM-DD → treat as noon-UTC for windowing/sort.
    for r in conn.execute(
        "SELECT e.name, e.date, c.name AS course_name FROM exams e "
        "LEFT JOIN courses c ON c.id = e.course_id "
        "WHERE e.date IS NOT NULL"
    ).fetchall():
        try:
            due = datetime.fromisoformat(r["date"]).replace(
                hour=12, tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            continue
        due_iso = due.isoformat(timespec="seconds")
        if lo <= due_iso <= hi:
            results.append({
                "kind": "exam",
                "title": r["name"],
                "course_name": r["course_name"] or "",
                "due": due_iso,
                "url": None,
            })

    results.sort(key=lambda d: d["due"])
    return results


# --------------------------------------------------------------------------- #
# Migration: state.json -> DB                                                   #
# --------------------------------------------------------------------------- #

def migrate_state_if_needed(conn: sqlite3.Connection) -> int:
    """Import legacy state.json seen_resources as status='seen' items, once."""
    if get_meta(conn, "state_migrated") == "1":
        return 0
    if not STATE_PATH.exists():
        set_meta(conn, "state_migrated", "1")
        conn.commit()
        return 0

    state = load_state()
    n = 0
    for key, rec in state.get("seen_resources", {}).items():
        m = re.match(r"resource_(\d+)", key)
        if not m:
            continue
        cmid = int(m.group(1))
        course_id = upsert_course_by_name(conn, rec.get("course", "Unbekannt"))
        # Insert directly so we can preserve seen_at as created_at.
        existing = conn.execute(
            "SELECT id FROM items WHERE type = 'file' AND cmid = ?", (cmid,)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO items(course_id, type, cmid, title, path, created_at, status) "
            "VALUES(?, 'file', ?, ?, ?, ?, 'seen')",
            (course_id, cmid, rec.get("title", f"file_{cmid}"),
             rec.get("path"), rec.get("seen_at") or _now_local_iso()),
        )
        n += 1

    set_meta(conn, "state_migrated", "1")
    conn.commit()
    return n
