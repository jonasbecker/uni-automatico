"""cli.py — entry point for the moodle-assistant CLI."""
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="moodle-assistant",
        description="Moodle Study Assistant",
    )
    parser.add_argument(
        "command",
        choices=["sync", "today", "plan"],
        help="Action to run",
    )
    args = parser.parse_args()
    print(f"[stub] command='{args.command}' — not implemented yet (see PLAN.md)")


if __name__ == "__main__":
    main()
