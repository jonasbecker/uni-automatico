"""cli.py — entry point for the moodle-assistant CLI."""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from moodle_assistant.appconfig import CONFIG_PATH, load_config


def _require_config() -> dict:
    config = load_config()
    if not config.get("moodle_url") or not config.get("username"):
        print("Keine Konfiguration gefunden.")
        print(f"Starte 'moodle-assistant-app' und richte die Einstellungen ein,")
        print(f"oder lege {CONFIG_PATH} manuell an.")
        sys.exit(1)
    return config


def _make_client(config: dict):
    from moodle_assistant.sync import MoodleClient
    base_url = config.get("moodle_url", "").rstrip("/")
    username = config.get("username") or os.environ.get("MOODLE_USER") or input("Moodle username: ")
    password = os.environ.get("MOODLE_PASS") or getpass.getpass("Moodle password: ")
    return MoodleClient(base_url, username, password)


def cmd_list_courses(args: argparse.Namespace) -> None:
    config = _require_config()
    client = _make_client(config)
    print(f"Logging in to {config['moodle_url'].rstrip('/')} ...")
    try:
        client.login()
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)
    print("Login successful.\n")
    courses = client.get_courses()
    if not courses:
        print("No courses found.")
        return
    print(f"Found {len(courses)} course(s):")
    for c in courses:
        print(f"  [{c.id:6}]  {c.name}")


def cmd_sync(args: argparse.Namespace) -> None:
    from moodle_assistant import db, ingest, notify

    config = _require_config()
    client = _make_client(config)
    print(f"Logging in to {config['moodle_url'].rstrip('/')} ...")
    try:
        client.login()
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)
    print("Login successful.")

    conn = db.connect()
    new_items = ingest.sync_to_db(client, conn, on_progress=lambda s: print(s))

    files = [i for i in new_items if i["type"] == "file"]
    assigns = [i for i in new_items if i["type"] == "assignment"]
    for i in files:
        print(f"  ↓  [{i['course_name']}]  {i['title']}")

    if new_items:
        parts = []
        if files:
            parts.append(f"{len(files)} neue Datei(en)")
        if assigns:
            parts.append(f"{len(assigns)} neue Abgabe(n)")
        summary = ", ".join(parts) or f"{len(new_items)} neue Items"
        print(f"\n{summary}")
        notify.send("Moodle: Neue Materialien", summary)
    else:
        print("Keine neuen Dateien oder Fristen.")


def cmd_today(args: argparse.Namespace) -> None:
    from moodle_assistant import db
    from moodle_assistant.views import format_today

    conn = db.connect()
    deadlines = db.get_upcoming_deadlines(conn, within_days=14)
    new_items = db.get_new_items(conn)
    print(format_today(deadlines, new_items, plain=True))

    if getattr(args, "seen", False):
        n = db.mark_seen_all_new(conn)
        print(f"\n({n} Item(s) als gesehen markiert.)")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="moodle-assistant",
        description="Moodle Study Assistant",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list-courses", help="Login and list enrolled courses")
    sub.add_parser("sync", help="Download new course files and notify")
    today_p = sub.add_parser("today", help="Show new items and deadlines")
    today_p.add_argument(
        "--seen", action="store_true",
        help="Mark all new items as seen after displaying",
    )
    sub.add_parser("plan", help="Generate AI study plan (Phase 3)")

    args = parser.parse_args()

    if args.command == "list-courses":
        cmd_list_courses(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "today":
        cmd_today(args)
    elif args.command is None:
        parser.print_help()
    else:
        print(f"[stub] '{args.command}' not yet implemented")


if __name__ == "__main__":
    main()
