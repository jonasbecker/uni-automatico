# uni-automatico — Moodle Study Assistant

Automatically syncs Moodle course materials, tracks deadlines, and uses the Claude AI API to generate a prioritised study plan.

## Architecture

| Phase | Module | Description |
|-------|--------|-------------|
| 0 | `sync.py` | Auth test: web login + course list |
| 1 | `sync.py` | Sync course files via web scraping |
| 2 | `ingest.py` | Deadlines + new items → SQLite |
| 3 | `planner.py` | Claude API → JSON study plan |
| 4 | `notify.py` | macOS notifications + optional `.ics` |

> **Note:** Uni-Due Moodle has the Web Services API disabled, so we use
> direct web login + scraping (`requests` + `BeautifulSoup`) instead of `moodle-dl`.

## Phase 0 — Local setup (run on your Mac)

```bash
# 1. Clone the repo and check out the dev branch
git clone https://github.com/jonasbecker/uni-automatico
cd uni-automatico
git checkout claude/elegant-noether-2GDHH

# 2. Set up the virtual environment
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e .

# 3. Create your config (never committed — gitignored)
cp config/config.yaml.template config/config.yaml
# Edit config/config.yaml: set your username

# 4. Verify login and list your courses
moodle-assistant list-courses
# Prompts for password (or set MOODLE_PASS env var)
```

## Usage

```bash
source .venv/bin/activate          # activate venv if not already active
moodle-assistant list-courses      # Phase 0: verify login + list courses
moodle-assistant sync              # Phase 1: download new files (coming soon)
moodle-assistant today             # Phase 2: show deadlines (coming soon)
moodle-assistant plan              # Phase 3: AI study plan (coming soon)
```

## Notes

- `config/config.yaml` is gitignored — credentials never leave your machine.
- Password: prompted at runtime, or set `export MOODLE_PASS=yourpassword` in your shell.
- For Phase 3 (AI planner): set `export ANTHROPIC_API_KEY=sk-ant-...` in your shell.
