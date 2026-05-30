"""cli.py — entry point for the moodle-assistant CLI."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import yaml


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        print("Copy config/config.yaml.template to config/config.yaml and fill it in.")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def cmd_list_courses(args: argparse.Namespace) -> None:
    from moodle_assistant.sync import MoodleClient

    config = _load_config(Path(args.config))
    base_url = config.get("moodle_url", "").rstrip("/")
    username = config.get("username") or os.environ.get("MOODLE_USER") or input("Moodle username: ")
    password = os.environ.get("MOODLE_PASS") or getpass.getpass("Moodle password: ")

    print(f"Logging in to {base_url} ...")
    client = MoodleClient(base_url, username, password)
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

    sub.add_parser("list-courses", help="Login and list enrolled courses (Phase 0 check)")
    sub.add_parser("sync", help="Sync course materials (Phase 1)")
    sub.add_parser("today", help="Show new items and upcoming deadlines (Phase 2)")
    sub.add_parser("plan", help="Generate AI study plan (Phase 3)")

    args = parser.parse_args()

    if args.command == "list-courses":
        cmd_list_courses(args)
    elif args.command is None:
        parser.print_help()
    else:
        print(f"[stub] '{args.command}' not implemented yet — see PLAN.md")


if __name__ == "__main__":
    main()
