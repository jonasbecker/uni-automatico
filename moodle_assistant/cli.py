"""cli.py — entry point for the moodle-assistant CLI."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        print("Copy config/config.yaml.template to config/config.yaml and fill it in.")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        with open(state_path) as f:
            return json.load(f)
    return {"seen_resources": {}}


def _save_state(state: dict, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _make_client(config: dict):
    from moodle_assistant.sync import MoodleClient
    base_url = config.get("moodle_url", "").rstrip("/")
    username = config.get("username") or os.environ.get("MOODLE_USER") or input("Moodle username: ")
    password = os.environ.get("MOODLE_PASS") or getpass.getpass("Moodle password: ")
    return MoodleClient(base_url, username, password)


def cmd_list_courses(args: argparse.Namespace) -> None:
    config = _load_config(Path(args.config))
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
    from moodle_assistant import notify

    config = _load_config(Path(args.config))
    data_dir = Path(config.get("data_dir", "data"))
    state_path = data_dir / "state.json"
    files_dir = data_dir / "files"

    client = _make_client(config)
    print(f"Logging in to {config['moodle_url'].rstrip('/')} ...")
    try:
        client.login()
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)
    print("Login successful.")

    courses = client.get_courses()
    print(f"Checking {len(courses)} course(s) for new files...\n")

    state = _load_state(state_path)
    new_items = []

    for course in courses:
        resources = client.get_course_resources(course)
        files = [r for r in resources if r.type == "file"]
        for resource in files:
            key = f"resource_{resource.id}"
            if key in state["seen_resources"]:
                continue
            # Mark as seen immediately (even if download fails, avoids re-checking)
            state["seen_resources"][key] = {
                "title": resource.title,
                "course": resource.course_name,
                "seen_at": datetime.now().isoformat(),
            }
            path = client.download_resource(resource, files_dir)
            if path:
                state["seen_resources"][key]["path"] = str(path)
                new_items.append((resource, path))
                print(f"  ↓  [{course.name}]  {resource.title}")

    _save_state(state, state_path)

    if new_items:
        courses_affected = {r.course_name for r, _ in new_items}
        summary = f"{len(new_items)} neue Datei(en) in {len(courses_affected)} Kurs(en)"
        print(f"\n{summary}")
        notify.send("Moodle: Neue Materialien", summary)
    else:
        print("Keine neuen Dateien.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="moodle-assistant",
        description="Moodle Study Assistant",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config.yaml (default: config/config.yaml)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list-courses", help="Login and list enrolled courses")
    sub.add_parser("sync", help="Download new course files and notify")
    sub.add_parser("today", help="Show new items and deadlines (Phase 2)")
    sub.add_parser("plan", help="Generate AI study plan (Phase 3)")

    args = parser.parse_args()

    if args.command == "list-courses":
        cmd_list_courses(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command is None:
        parser.print_help()
    else:
        print(f"[stub] '{args.command}' not implemented yet — see PLAN.md")


if __name__ == "__main__":
    main()
