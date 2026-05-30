"""appconfig.py — shared paths and config helpers for all entry points."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

APP_NAME = "MoodleAssistant"
APP_SUPPORT = Path.home() / "Library" / "Application Support" / APP_NAME
CONFIG_PATH = APP_SUPPORT / "config.yaml"
STATE_PATH = APP_SUPPORT / "state.json"
DB_PATH = APP_SUPPORT / "assistant.db"
FILES_DIR = APP_SUPPORT / "files"
LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / "com.moodleassistant.app.plist"
)

MOODLE_URL_DEFAULT = "https://lehre.moodle.uni-due.de"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(config: dict) -> None:
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"seen_resources": {}}


def save_state(state: dict) -> None:
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
