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

## Phase 0 — Local setup (run on your Mac)

```bash
# 1. Clone and set up the virtual environment
git clone https://github.com/jonasbecker/uni-automatico
cd uni-automatico
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip   # required on macOS with older pip (< 22)
pip install -e .

# 2. Create the Configs directory (moodle-dl stores its token here)
mkdir -p Configs

# 3. Pre-seed the Moodle URL (skips having to type it in the wizard)
echo '{"moodle_domain":"lehre.moodle.uni-due.de","moodle_path":"/"}' > Configs/config.json
chmod 600 Configs/config.json

# 4. Get an auth token (no notifications wizard, automated with -u/-pw)
moodle-dl --new-token -u YOUR_USERNAME --path ./Configs
# The -pw flag is optional; omitting it prompts for hidden password input

# 5. Verify: list all visible courses
moodle-dl --add-all-visible-courses --path ./Configs

# 6. Copy and fill in the config template
cp config/config.yaml.template config/config.yaml
# Edit config/config.yaml — add your course IDs and exam dates
```

## Notes

- `Configs/` and `config/config.yaml` are gitignored — credentials never leave your machine.
- For Phase 3 (AI planner): set `export ANTHROPIC_API_KEY=sk-ant-...` in your shell.
- On macOS, `keyring` uses the system Keychain automatically.
