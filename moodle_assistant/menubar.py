"""menubar.py — macOS menu bar app for Moodle Assistant."""
from __future__ import annotations

import getpass
import json
import os
import threading
from datetime import datetime
from pathlib import Path

import rumps
import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
STATE_PATH_DEFAULT = Path(__file__).parent.parent / "data" / "state.json"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        with open(state_path) as f:
            return json.load(f)
    return {"seen_resources": {}}


def _save_state(state: dict, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


class MoodleApp(rumps.App):
    def __init__(self):
        super().__init__("🎓", quit_button=None)
        self.config = _load_config()
        self._password: str | None = os.environ.get("MOODLE_PASS")
        self._syncing = False

        data_dir = Path(self.config.get("data_dir", "data"))
        self._state_path = data_dir / "state.json"
        self._files_dir = data_dir / "files"

        self.menu = [
            rumps.MenuItem("Sync jetzt", callback=self.sync_now),
            rumps.MenuItem("Dateien öffnen", callback=self.open_files),
            None,  # separator
            rumps.MenuItem("Status", callback=None),
            None,
            rumps.MenuItem("Beenden", callback=rumps.quit_application),
        ]
        self._update_status("Bereit")

    def _update_status(self, text: str) -> None:
        self.menu["Status"].title = text

    def _get_password(self) -> str | None:
        if self._password:
            return self._password
        # Ask via a rumps dialog
        resp = rumps.Window(
            message="Moodle Passwort eingeben:",
            title="Moodle Assistant",
            secure=True,
            ok="OK",
            cancel="Abbrechen",
            dimensions=(300, 20),
        ).run()
        if resp.clicked:
            self._password = resp.text
            return self._password
        return None

    @rumps.clicked("Sync jetzt")
    def sync_now(self, _):
        if self._syncing:
            return
        threading.Thread(target=self._do_sync, daemon=True).start()

    def _do_sync(self) -> None:
        from moodle_assistant.sync import MoodleClient

        self._syncing = True
        self._update_status("⏳ Verbinde...")
        self.title = "⏳"

        base_url = self.config.get("moodle_url", "").rstrip("/")
        username = self.config.get("username", "")
        password = self._get_password()

        if not password:
            self._update_status("❌ Kein Passwort")
            self.title = "🎓"
            self._syncing = False
            return

        try:
            client = MoodleClient(base_url, username, password)
            client.login()
        except Exception as e:
            self._update_status(f"❌ Login fehlgeschlagen")
            self.title = "🎓"
            self._syncing = False
            return

        self._update_status("🔄 Prüfe Kurse...")
        state = _load_state(self._state_path)
        new_items = []

        try:
            courses = client.get_courses()
            for course in courses:
                resources = client.get_course_resources(course)
                for resource in [r for r in resources if r.type == "file"]:
                    key = f"resource_{resource.id}"
                    if key in state["seen_resources"]:
                        continue
                    state["seen_resources"][key] = {
                        "title": resource.title,
                        "course": resource.course_name,
                        "seen_at": datetime.now().isoformat(),
                    }
                    path = client.download_resource(resource, self._files_dir)
                    if path:
                        state["seen_resources"][key]["path"] = str(path)
                        new_items.append(resource)

            _save_state(state, self._state_path)
        except Exception as e:
            self._update_status(f"❌ Fehler: {e}")
            self.title = "🎓"
            self._syncing = False
            return

        now = datetime.now().strftime("%H:%M")
        if new_items:
            courses_set = {r.course_name for r in new_items}
            summary = f"{len(new_items)} neue Datei(en)"
            self._update_status(f"✅ {summary} — {now}")
            self.title = f"🎓 {len(new_items)} neu"
            rumps.notification(
                title="Moodle: Neue Materialien",
                subtitle=None,
                message=f"{summary} in {len(courses_set)} Kurs(en)",
            )
        else:
            self._update_status(f"✅ Nichts Neues — {now}")
            self.title = "🎓"

        self._syncing = False

    @rumps.clicked("Dateien öffnen")
    def open_files(self, _):
        import subprocess
        files_dir = self._files_dir
        files_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(files_dir)])


def main() -> None:
    MoodleApp().run()


if __name__ == "__main__":
    main()
