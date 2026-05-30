"""menubar.py — macOS menu bar app for Moodle Assistant."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import keyring
import rumps

from moodle_assistant.appconfig import (
    APP_NAME,
    APP_SUPPORT,
    FILES_DIR,
    LAUNCH_AGENT_PATH,
    MOODLE_URL_DEFAULT,
    load_config,
    save_config,
)

AUTOSYNC_INTERVAL = 30 * 60  # seconds


class MoodleApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("🎓", quit_button=None)
        self._config = load_config()
        self._syncing = False
        self._autosync_timer: threading.Timer | None = None

        # Build menu items we need to reference later
        self._status_item = rumps.MenuItem("— Bereit —", callback=None)
        self._autosync_item = rumps.MenuItem(
            "🔁 Auto-Sync (30 min)", callback=self.toggle_autosync
        )
        self._autostart_item = rumps.MenuItem(
            "🚀 Beim Anmelden starten", callback=self.toggle_autostart
        )
        self._autostart_item.state = LAUNCH_AGENT_PATH.exists()

        self.menu = [
            rumps.MenuItem("▶  Sync jetzt", callback=self.sync_now),
            rumps.MenuItem("📅  Heute", callback=self.show_today),
            rumps.MenuItem("📁  Dateien öffnen", callback=self.open_files),
            None,
            self._autosync_item,
            None,
            rumps.MenuItem("⚙  Einstellungen", callback=self.open_settings),
            rumps.MenuItem("🔑  Passwort ändern", callback=self.change_password),
            rumps.MenuItem("📝  Klausur hinzufügen", callback=self.add_exam),
            None,
            self._status_item,
            None,
            self._autostart_item,
            None,
            rumps.MenuItem("Beenden", callback=rumps.quit_application),
        ]
        self._refresh_badge()

        # First-run wizard if not configured
        if not self._config.get("username") or not self._config.get("moodle_url"):
            threading.Timer(0.6, self._first_run).start()

    # ------------------------------------------------------------------ #
    # Status helper                                                        #
    # ------------------------------------------------------------------ #

    def _set_status(self, text: str) -> None:
        self._status_item.title = text

    # ------------------------------------------------------------------ #
    # First-run & settings                                                 #
    # ------------------------------------------------------------------ #

    def _first_run(self) -> None:
        rumps.alert(
            title="Moodle Assistant – Ersteinrichtung",
            message=(
                "Willkommen! Bitte gib deine Moodle-URL\n"
                "und deinen Benutzernamen ein."
            ),
            ok="Weiter",
        )
        self._run_settings_wizard()

    def _run_settings_wizard(self) -> None:
        url_resp = rumps.Window(
            title="Moodle Assistant – Einstellungen",
            message="Moodle-URL:",
            default_text=self._config.get("moodle_url", MOODLE_URL_DEFAULT),
            ok="Weiter",
            cancel="Abbrechen",
            dimensions=(340, 22),
        ).run()
        if not url_resp.clicked:
            return

        user_resp = rumps.Window(
            title="Moodle Assistant – Einstellungen",
            message="Benutzername (Uni-Account):",
            default_text=self._config.get("username", ""),
            ok="Speichern",
            cancel="Abbrechen",
            dimensions=(340, 22),
        ).run()
        if not user_resp.clicked:
            return

        self._config["moodle_url"] = url_resp.text.strip().rstrip("/")
        self._config["username"] = user_resp.text.strip()
        save_config(self._config)
        self._set_status("✅ Einstellungen gespeichert")

    @rumps.clicked("⚙  Einstellungen")
    def open_settings(self, _) -> None:
        self._run_settings_wizard()

    # ------------------------------------------------------------------ #
    # Password (macOS Keychain)                                            #
    # ------------------------------------------------------------------ #

    def _get_password(self) -> str | None:
        pw = os.environ.get("MOODLE_PASS")
        if pw:
            return pw
        username = self._config.get("username", "")
        pw = keyring.get_password(APP_NAME, username)
        if pw:
            return pw
        return self._ask_password()

    def _ask_password(self) -> str | None:
        username = self._config.get("username", "")
        resp = rumps.Window(
            title="Moodle Assistant",
            message=f"Passwort für {username}:",
            secure=True,
            ok="OK",
            cancel="Abbrechen",
            dimensions=(300, 22),
        ).run()
        return resp.text if resp.clicked else None

    @rumps.clicked("🔑  Passwort ändern")
    def change_password(self, _) -> None:
        pw = self._ask_password()
        if pw:
            username = self._config.get("username", "")
            keyring.set_password(APP_NAME, username, pw)
            self._set_status("✅ Passwort gespeichert")

    # ------------------------------------------------------------------ #
    # Auto-Sync timer                                                      #
    # ------------------------------------------------------------------ #

    @rumps.clicked("🔁 Auto-Sync (30 min)")
    def toggle_autosync(self, sender) -> None:
        if self._autosync_timer:
            self._autosync_timer.cancel()
            self._autosync_timer = None
            sender.state = 0
            self._set_status("⏸ Auto-Sync deaktiviert")
        else:
            self._schedule_autosync()
            sender.state = 1
            self._set_status("🔁 Auto-Sync aktiv (30 min)")

    def _schedule_autosync(self) -> None:
        self._autosync_timer = threading.Timer(AUTOSYNC_INTERVAL, self._autosync_fire)
        self._autosync_timer.daemon = True
        self._autosync_timer.start()

    def _autosync_fire(self) -> None:
        if not self._syncing:
            threading.Thread(target=self._do_sync, daemon=True).start()
        self._schedule_autosync()  # re-arm for next cycle

    # ------------------------------------------------------------------ #
    # Autostart (Launch Agent)                                             #
    # ------------------------------------------------------------------ #

    @rumps.clicked("🚀 Beim Anmelden starten")
    def toggle_autostart(self, sender) -> None:
        if LAUNCH_AGENT_PATH.exists():
            subprocess.run(
                ["launchctl", "unload", str(LAUNCH_AGENT_PATH)], capture_output=True
            )
            LAUNCH_AGENT_PATH.unlink()
            sender.state = 0
            self._set_status("⏸ Autostart deaktiviert")
        else:
            self._install_launch_agent()
            sender.state = 1
            self._set_status("🚀 Autostart aktiviert")

    def _install_launch_agent(self) -> None:
        # Prefer the installed script; fall back to python -m
        script = shutil.which("moodle-assistant-app")
        if script:
            args = [str(Path(script).resolve())]
        else:
            args = [sys.executable, "-m", "moodle_assistant.menubar"]

        args_xml = "\n".join(f"        <string>{a}</string>" for a in args)
        log = APP_SUPPORT / "app.log"
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.moodleassistant.app</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
</dict>
</plist>
"""
        LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_AGENT_PATH.write_text(plist)
        subprocess.run(
            ["launchctl", "load", str(LAUNCH_AGENT_PATH)], capture_output=True
        )

    # ------------------------------------------------------------------ #
    # Sync                                                                 #
    # ------------------------------------------------------------------ #

    @rumps.clicked("▶  Sync jetzt")
    def sync_now(self, _) -> None:
        if self._syncing:
            return
        threading.Thread(target=self._do_sync, daemon=True).start()

    def _do_sync(self) -> None:
        from moodle_assistant.sync import MoodleClient

        self._syncing = True
        self._set_status("⏳ Verbinde...")
        self.title = "⏳"

        url = self._config.get("moodle_url", "").rstrip("/")
        username = self._config.get("username", "")

        if not url or not username:
            self._set_status("❌ Einstellungen fehlen")
            self.title = "🎓"
            self._syncing = False
            threading.Timer(0.3, self._run_settings_wizard).start()
            return

        password = self._get_password()
        if not password:
            self._set_status("❌ Kein Passwort")
            self.title = "🎓"
            self._syncing = False
            return

        try:
            client = MoodleClient(url, username, password)
            client.login()
            # Save working password to Keychain for future sessions
            if not keyring.get_password(APP_NAME, username):
                keyring.set_password(APP_NAME, username, password)
        except Exception:
            # Clear potentially wrong cached password
            try:
                keyring.delete_password(APP_NAME, username)
            except Exception:
                pass
            self._set_status("❌ Login fehlgeschlagen")
            self.title = "🎓"
            self._syncing = False
            return

        self._set_status("🔄 Prüfe Kurse...")
        try:
            from moodle_assistant import db, ingest
            conn = db.connect()
            new_items = ingest.sync_to_db(client, conn, on_progress=self._set_status)
            n_unread = db.count_new(conn)
        except Exception as e:
            self._set_status(f"❌ {e}")
            self.title = "🎓"
            self._syncing = False
            return

        now = datetime.now().strftime("%H:%M")
        if new_items:
            self._set_status(f"✅ {len(new_items)} neu — {now}")
            rumps.notification(
                title="Moodle: Neue Materialien",
                subtitle=None,
                message=_summary(new_items),
            )
        else:
            self._set_status(f"✅ Nichts Neues — {now}")
        self.title = f"🎓 {n_unread}" if n_unread else "🎓"

        self._syncing = False

    def _refresh_badge(self) -> None:
        try:
            from moodle_assistant import db
            n = db.count_new(db.connect())
            self.title = f"🎓 {n}" if n else "🎓"
        except Exception:
            self.title = "🎓"

    # ------------------------------------------------------------------ #
    # "Heute" view                                                         #
    # ------------------------------------------------------------------ #

    @rumps.clicked("📅  Heute")
    def show_today(self, _) -> None:
        from moodle_assistant import db
        from moodle_assistant.views import format_today

        conn = db.connect()
        deadlines = db.get_upcoming_deadlines(conn, within_days=14)
        new_items = db.get_new_items(conn)
        msg = format_today(deadlines, new_items, plain=True)
        rumps.alert(title="📅 Heute", message=msg, ok="OK")
        db.mark_seen_all_new(conn)
        self.title = "🎓"

    # ------------------------------------------------------------------ #
    # Add exam                                                             #
    # ------------------------------------------------------------------ #

    @rumps.clicked("📝  Klausur hinzufügen")
    def add_exam(self, _) -> None:
        course = rumps.Window(
            title="Klausur – Kurs",
            message="Kursname:",
            ok="Weiter", cancel="Abbrechen",
            dimensions=(300, 22),
        ).run()
        if not course.clicked or not course.text.strip():
            return
        name = rumps.Window(
            title="Klausur – Bezeichnung",
            message="Name der Klausur:",
            default_text="Klausur",
            ok="Weiter", cancel="Abbrechen",
            dimensions=(300, 22),
        ).run()
        if not name.clicked or not name.text.strip():
            return
        date = rumps.Window(
            title="Klausur – Datum",
            message="Datum (JJJJ-MM-TT):",
            ok="Speichern", cancel="Abbrechen",
            dimensions=(300, 22),
        ).run()
        if not date.clicked:
            return
        date_str = date.text.strip()
        if not _valid_date(date_str):
            rumps.alert("Ungültiges Datum", "Bitte im Format JJJJ-MM-TT eingeben.")
            return

        from moodle_assistant import db
        conn = db.connect()
        db.add_exam(conn, course.text.strip(), name.text.strip(), date_str)

        # Persist to config.yaml so it survives and feeds Phase 3.
        exams = self._config.get("exams") or []
        exams.append({
            "course": course.text.strip(),
            "name": name.text.strip(),
            "date": date_str,
        })
        self._config["exams"] = exams
        save_config(self._config)
        self._set_status(f"✅ Klausur '{name.text.strip()}' gespeichert")

    # ------------------------------------------------------------------ #
    # Open files folder                                                    #
    # ------------------------------------------------------------------ #

    @rumps.clicked("📁  Dateien öffnen")
    def open_files(self, _) -> None:
        FILES_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(FILES_DIR)])


def _summary(new_items: list[dict]) -> str:
    files = sum(1 for i in new_items if i["type"] == "file")
    assigns = sum(1 for i in new_items if i["type"] == "assignment")
    parts = []
    if files:
        parts.append(f"{files} Datei(en)")
    if assigns:
        parts.append(f"{assigns} Abgabe(n)")
    return ", ".join(parts) or f"{len(new_items)} neue Items"


def _valid_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def main() -> None:
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    MoodleApp().run()


if __name__ == "__main__":
    main()
