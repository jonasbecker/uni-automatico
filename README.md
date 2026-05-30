# uni-automatico — Moodle Study Assistant

Automatically syncs Moodle course materials, tracks deadlines, and uses the Claude AI API to generate a prioritised study plan.

## Architecture

| Phase | Module | Description |
|-------|--------|-------------|
| 0 | — | Auth test: `moodle-dl` token + course list |
| 1 | `sync.py` | Periodic sync via `moodle-dl` |
| 2 | `ingest.py` | Deadlines + new items → SQLite |
| 3 | `planner.py` | Claude API → JSON study plan |
| 4 | `notify.py` | macOS notifications + optional `.ics` |

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
mkdir -p Configs
moodle-dl --init --path ./Configs
```

Copy `config/config.yaml.template` to `config/config.yaml` and fill in your courses and exam dates.
