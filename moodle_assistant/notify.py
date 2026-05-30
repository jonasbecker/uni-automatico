"""notify.py — macOS notifications via osascript (no extra install needed)."""
from __future__ import annotations

import subprocess


def send(title: str, message: str) -> None:
    """Send a macOS notification. Silent no-op on non-macOS."""
    try:
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
