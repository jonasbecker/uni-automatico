"""ingest.py — central sync loop: Moodle -> SQLite (files, pages, deadlines)."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Optional

from moodle_assistant import db
from moodle_assistant.appconfig import FILES_DIR, load_config


def _course_priority(config: dict, moodle_course_id: int) -> int:
    for c in config.get("courses", []) or []:
        if c.get("id") == moodle_course_id:
            return int(c.get("priority", 3))
    return 3


def sync_to_db(
    client,
    conn: sqlite3.Connection,
    files_dir: Path = FILES_DIR,
    on_progress: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """Sync courses, files and deadlines into the DB.

    Caller must have called client.login() first.
    Returns a list of new-item dicts: {type, title, course_name, due_date, path}.
    """
    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    config = load_config()
    new_items: list[dict] = []

    # Keep exams table in sync with config.yaml (source of truth).
    exams = config.get("exams")
    if exams is not None:
        db.replace_exams(conn, exams)

    progress("🔄 Lade Kurse...")
    courses = client.get_courses()

    # moodle_course_id -> local course id / name
    local_id: dict[int, int] = {}
    course_name: dict[int, str] = {}
    for course in courses:
        cid = db.upsert_course(
            conn, course.id, course.name,
            priority=_course_priority(config, course.id),
        )
        local_id[course.id] = cid
        course_name[course.id] = course.name

    # --- Files & pages -----------------------------------------------------
    for course in courses:
        progress(f"📂 {course.name}")
        resources = client.get_course_resources(course)
        for r in resources:
            if r.type == "file":
                item_id, is_new = db.upsert_item(
                    conn, course_id=local_id[course.id], type="file",
                    cmid=r.id, title=r.title, url=r.url,
                )
                if is_new:
                    path = client.download_resource(r, files_dir)
                    if path:
                        db.set_item_path(conn, item_id, str(path))
                        new_items.append({
                            "type": "file", "title": r.title,
                            "course_name": r.course_name,
                            "due_date": None, "path": str(path),
                        })
                    else:
                        # HTML/error page — don't keep flagging or notifying.
                        db.mark_status(conn, item_id, "seen")
            elif r.type == "page":
                _, is_new = db.upsert_item(
                    conn, course_id=local_id[course.id], type="page",
                    cmid=r.id, title=r.title, url=r.url,
                )
                if is_new:
                    new_items.append({
                        "type": "page", "title": r.title,
                        "course_name": r.course_name,
                        "due_date": None, "path": None,
                    })

    # --- Deadlines ---------------------------------------------------------
    progress("⏰ Lade Fristen...")
    for d in client.get_deadlines():
        cid = local_id.get(d.course_id)
        if cid is None:
            cid = db.upsert_course(
                conn, d.course_id,
                course_name.get(d.course_id, f"Kurs {d.course_id}"),
            )
            local_id[d.course_id] = cid
        due_iso = db.epoch_to_utc_iso(d.due_ts)
        _, is_new = db.upsert_item(
            conn, course_id=cid, type="assignment", cmid=d.cmid,
            title=d.title, url=d.url, due_date=due_iso,
        )
        if is_new:
            new_items.append({
                "type": "assignment", "title": d.title,
                "course_name": course_name.get(d.course_id, ""),
                "due_date": due_iso, "path": None,
            })

    conn.commit()
    return new_items
