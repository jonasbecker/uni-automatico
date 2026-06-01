import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import threading
import json
import re
import queue
from pathlib import Path

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CONFIG_PATH = Path.home() / ".uni-automatico" / "config.json"

DEFAULT_PROMPT = """\
Du bist ein Lernassistent für Universitätsstudierende. Analysiere den folgenden Vorlesungstext \
und erstelle präzise Anki-Karteikarten auf Deutsch.

Ausgabeformat – eine Karte pro Zeile, Frage und Antwort durch einen TAB getrennt:
Frage[TAB]Antwort

Regeln:
- Jede Zeile enthält genau eine Karte im Format: Frage<TAB>Antwort
- Fragen sollen das Kernwissen gezielt abfragen
- Antworten kurz und präzise (1–3 Sätze)
- Keine Nummerierung, keine Erklärungen außerhalb des Formats
- 10–20 Karten pro Text
- Nur das Ausgabeformat, sonst nichts

Text:
{text}"""


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {
        "moodle_url": "",
        "username": "",
        "password": "",
        "download_path": str(Path.home() / "Uni-Materialien"),
        "ollama_url": "http://localhost:11434",
        "ollama_model": "llama3.2",
        "prompt": DEFAULT_PROMPT,
        "selected_courses": [],
    }


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


VIDEO_EXTENSIONS = {
    '.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v',
    '.flv', '.wmv', '.ts', '.3gp', '.ogv', '.mpeg', '.mpg',
}

_VORL_RE = re.compile(
    r'(vorlesung|lecture|folien?|slides?|kapitel|chapter|skript|script|'
    r'handout|pr[äa]sentation|presentation|\bvl[-_ ]|\bvl\d)',
    re.IGNORECASE,
)
_UEBUNG_RE = re.compile(
    r'([üu]bung|uebung|aufgabe|blatt|exercise|tutorium|tutorial|'
    r'l[öo]sung|solution|praktikum|hausaufgabe|abgabe|klausur|\bue[-_ ]|\bue\d)',
    re.IGNORECASE,
)


def classify_file(fname: str) -> str:
    if _VORL_RE.search(fname):
        return "Vorlesungen"
    if _UEBUNG_RE.search(fname):
        return "Übungen"
    return "Sonstige Dateien"



# ── App ───────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Uni-Automatico")
        self.geometry("1100x740")
        self.minsize(900, 600)

        self.cfg = load_config()
        self.log_q: queue.Queue = queue.Queue()
        self.running = False
        self.course_vars: dict[int, tk.BooleanVar] = {}
        self.courses: list[dict] = []

        self._build_ui()
        self._poll_log()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Sidebar
        sb = ctk.CTkFrame(self, width=210, corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        ctk.CTkLabel(sb, text="Uni\nAutomatico",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(28, 2))
        ctk.CTkLabel(sb, text="Lernassistent",
                     text_color="gray60", font=ctk.CTkFont(size=11)).pack()

        ctk.CTkFrame(sb, height=1, fg_color="gray35").pack(fill="x", padx=15, pady=14)

        self._nav_btns: dict[str, ctk.CTkButton] = {}
        for key, label in [("dashboard", "Dashboard"),
                            ("einstellungen", "Einstellungen"),
                            ("kurse", "Kurse")]:
            btn = ctk.CTkButton(sb, text=label, anchor="w",
                                fg_color="transparent",
                                text_color=("gray10", "gray90"),
                                hover_color=("gray75", "gray30"),
                                command=lambda k=key: self._show(k))
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_btns[key] = btn

        # Spacer
        ctk.CTkFrame(sb, fg_color="transparent").pack(fill="both", expand=True)

        self._sync_btn = ctk.CTkButton(
            sb, text="⟳  Alles aktualisieren",
            height=52, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1c7c42", hover_color="#155e32",
            command=self._sync_all,
        )
        self._sync_btn.pack(fill="x", padx=14, pady=18)

        # Content
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(side="right", fill="both", expand=True)

        self._pages: dict[str, ctk.CTkFrame | ctk.CTkScrollableFrame] = {}
        self._build_dashboard()
        self._build_settings()
        self._build_courses()
        self._show("dashboard")

    # ── Dashboard ─────────────────────────────────────────────────────────

    def _build_dashboard(self):
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        self._pages["dashboard"] = page

        ctk.CTkLabel(page, text="Dashboard",
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=22, pady=(20, 2))
        ctk.CTkLabel(page, text="Materialien herunterladen & Karteikarten erstellen",
                     text_color="gray60").pack(anchor="w", padx=22)

        # Status row
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=14)
        self._status_lbl: dict[str, ctk.CTkLabel] = {}
        for key, icon, title in [
            ("download", "↓", "Download"),
            ("sort",     "⊞", "Sortierung"),
            ("cards",    "▣", "Karteikarten"),
            ("export",   "✓", "Export"),
        ]:
            card = ctk.CTkFrame(row)
            card.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=20)).pack(pady=(12, 0))
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(weight="bold")).pack()
            lbl = ctk.CTkLabel(card, text="Bereit", text_color="gray60",
                               font=ctk.CTkFont(size=11))
            lbl.pack(pady=(0, 12))
            self._status_lbl[key] = lbl

        # Progress
        prog = ctk.CTkFrame(page)
        prog.pack(fill="x", padx=22, pady=4)
        self._prog_lbl = ctk.CTkLabel(prog, text="Bereit zum Starten", anchor="w")
        self._prog_lbl.pack(anchor="w", padx=12, pady=(10, 2))
        self._prog_bar = ctk.CTkProgressBar(prog)
        self._prog_bar.pack(fill="x", padx=12, pady=(0, 10))
        self._prog_bar.set(0)

        # Log
        ctk.CTkLabel(page, text="Protokoll",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=22, pady=(10, 0))
        self._log_box = ctk.CTkTextbox(page, state="disabled", font=ctk.CTkFont(size=12))
        self._log_box.pack(fill="both", expand=True, padx=22, pady=(4, 18))

    # ── Settings ──────────────────────────────────────────────────────────

    def _build_settings(self):
        page = ctk.CTkScrollableFrame(self._content, fg_color="transparent")
        self._pages["einstellungen"] = page

        ctk.CTkLabel(page, text="Einstellungen",
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=22, pady=(20, 14))

        # Moodle
        self._section(page, "Moodle")
        self._moodle_url = self._field(page, "Moodle URL",
                                       self.cfg.get("moodle_url", ""),
                                       "https://moodle.uni-example.de")
        self._username   = self._field(page, "Benutzername",
                                       self.cfg.get("username", ""), "max.mustermann")
        self._password   = self._field(page, "Passwort",
                                       self.cfg.get("password", ""), "••••••••", show="*")

        # Files
        self._section(page, "Dateien")
        path_row = ctk.CTkFrame(page, fg_color="transparent")
        path_row.pack(fill="x", padx=22, pady=6)
        ctk.CTkLabel(path_row, text="Download-Ordner", width=170, anchor="w").pack(side="left")
        self._dl_path_var = tk.StringVar(value=self.cfg.get("download_path", ""))
        ctk.CTkEntry(path_row, textvariable=self._dl_path_var, width=320).pack(side="left", padx=6)
        ctk.CTkButton(path_row, text="…", width=36, command=self._pick_folder).pack(side="left")

        # Ollama
        self._section(page, "Ollama (lokale KI)")
        self._ollama_url   = self._field(page, "Ollama URL",
                                         self.cfg.get("ollama_url", "http://localhost:11434"),
                                         "http://localhost:11434")
        self._ollama_model = self._field(page, "Modell",
                                         self.cfg.get("ollama_model", "llama3.2"),
                                         "llama3.2")

        # Prompt
        self._section(page, "Karteikarten-Prompt")
        ctk.CTkLabel(page, text="Nutze {text} als Platzhalter für den Vorlesungstext.",
                     text_color="gray60").pack(anchor="w", padx=22)
        self._prompt_box = ctk.CTkTextbox(page, height=210, font=ctk.CTkFont(size=12))
        self._prompt_box.pack(fill="x", padx=22, pady=6)
        self._prompt_box.insert("1.0", self.cfg.get("prompt", DEFAULT_PROMPT))

        ctk.CTkButton(page, text="Einstellungen speichern", height=42,
                      command=self._save_settings).pack(fill="x", padx=22, pady=18)

    # ── Courses ───────────────────────────────────────────────────────────

    def _build_courses(self):
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        self._pages["kurse"] = page

        ctk.CTkLabel(page, text="Kurse",
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=22, pady=(20, 2))
        ctk.CTkLabel(page, text="Wähle die Kurse aus, die synchronisiert werden sollen.",
                     text_color="gray60").pack(anchor="w", padx=22)

        btn_row = ctk.CTkFrame(page, fg_color="transparent")
        btn_row.pack(fill="x", padx=22, pady=10)
        ctk.CTkButton(btn_row, text="Kurse laden",
                      command=self._load_courses).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Alle auswählen",
                      command=lambda: self._toggle_all(True)).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Alle abwählen",
                      command=lambda: self._toggle_all(False)).pack(side="left", padx=4)

        self._courses_scroll = ctk.CTkScrollableFrame(page)
        self._courses_scroll.pack(fill="both", expand=True, padx=22, pady=4)

        self._courses_status = ctk.CTkLabel(
            page, text="Klicke 'Kurse laden', um verfügbare Kurse anzuzeigen.",
            text_color="gray60")
        self._courses_status.pack(pady=8)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _section(self, parent, title: str):
        ctk.CTkLabel(parent, text=title,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=22, pady=(16, 2))
        ctk.CTkFrame(parent, height=1, fg_color="gray35").pack(fill="x", padx=22, pady=(0, 6))

    def _field(self, parent, label: str, value: str, placeholder="", show="") -> tk.StringVar:
        var = tk.StringVar(value=value)
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=5)
        ctk.CTkLabel(row, text=label, width=170, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=var, placeholder_text=placeholder,
                     width=360, show=show).pack(side="left")
        return var

    def _show(self, name: str):
        for p in self._pages.values():
            p.pack_forget()
        self._pages[name].pack(fill="both", expand=True)
        for k, btn in self._nav_btns.items():
            btn.configure(fg_color=("gray72", "gray28") if k == name else "transparent")

    def _pick_folder(self):
        path = filedialog.askdirectory()
        if path:
            self._dl_path_var.set(path)

    # ── Config actions ────────────────────────────────────────────────────

    def _save_settings(self):
        self.cfg.update({
            "moodle_url":   self._moodle_url.get().strip(),
            "username":     self._username.get().strip(),
            "password":     self._password.get(),
            "download_path": self._dl_path_var.get().strip(),
            "ollama_url":   self._ollama_url.get().strip(),
            "ollama_model": self._ollama_model.get().strip(),
            "prompt":       self._prompt_box.get("1.0", "end-1c"),
        })
        save_config(self.cfg)
        self._log("✓ Einstellungen gespeichert")
        messagebox.showinfo("Gespeichert", "Einstellungen wurden gespeichert.")

    # ── Courses loading ───────────────────────────────────────────────────

    def _load_courses(self):
        if not self.cfg.get("moodle_url") or not self.cfg.get("username"):
            messagebox.showerror("Fehler", "Bitte zuerst Moodle-Einstellungen speichern.")
            self._show("einstellungen")
            return
        self._courses_status.configure(text="Lade Kurse …")
        threading.Thread(target=self._load_courses_thread, daemon=True).start()

    def _load_courses_thread(self):
        try:
            from moodle_client import MoodleClient
            client = MoodleClient(self.cfg["moodle_url"],
                                  self.cfg["username"],
                                  self.cfg["password"])
            info = client.get_user_info()
            courses = client.get_courses(info["userid"])
            self.courses = courses
            self.after(0, self._populate_courses, courses)
        except Exception as e:
            self.after(0, self._courses_status.configure,
                       {"text": f"Fehler: {e}"})

    def _populate_courses(self, courses: list[dict]):
        for w in self._courses_scroll.winfo_children():
            w.destroy()
        self.course_vars = {}
        selected = set(self.cfg.get("selected_courses", []))
        for c in courses:
            var = tk.BooleanVar(value=(c["id"] in selected))
            cb = ctk.CTkCheckBox(self._courses_scroll,
                                 text=c["fullname"], variable=var,
                                 command=self._save_course_selection)
            cb.pack(anchor="w", pady=3)
            self.course_vars[c["id"]] = var
        self._courses_status.configure(text=f"{len(courses)} Kurs(e) gefunden.")

    def _save_course_selection(self):
        self.cfg["selected_courses"] = [cid for cid, v in self.course_vars.items() if v.get()]
        save_config(self.cfg)

    def _toggle_all(self, state: bool):
        for v in self.course_vars.values():
            v.set(state)
        self._save_course_selection()

    # ── Log ───────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        self.log_q.put(msg)

    def _poll_log(self):
        try:
            while True:
                msg = self.log_q.get_nowait()
                self._log_box.configure(state="normal")
                self._log_box.insert("end", msg + "\n")
                self._log_box.see("end")
                self._log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _set_prog(self, value: float, label: str):
        self._prog_bar.set(value)
        self._prog_lbl.configure(text=label)

    def _set_status(self, key: str, text: str, color: str = "gray60"):
        self._status_lbl[key].configure(text=text, text_color=color)

    # ── Main sync ─────────────────────────────────────────────────────────

    def _sync_all(self):
        if self.running:
            return
        if not self.cfg.get("moodle_url") or not self.cfg.get("username"):
            messagebox.showerror(
                "Keine Einstellungen",
                "Bitte zuerst Moodle URL, Benutzername und Passwort unter Einstellungen eingeben."
            )
            self._show("einstellungen")
            return

        self._show("dashboard")
        self.running = True
        self._sync_btn.configure(state="disabled", text="Läuft …")
        for key in self._status_lbl:
            self._set_status(key, "Warten …", "gray60")
        self._prog_bar.set(0)

        threading.Thread(target=self._sync_thread, daemon=True).start()

    def _sync_thread(self):
        try:
            from moodle_client import MoodleClient
            from flashcard_generator import FlashcardGenerator

            self._ui(self._log, "═══ Synchronisierung gestartet ═══")

            # ── 1. Login ──────────────────────────────────────────────
            self._ui(self._set_prog, 0.03, "Verbinde mit Moodle …")
            self._ui(self._set_status, "download", "Verbinden …", "orange")
            self._ui(self._log, "Verbinde mit Moodle …")

            client = MoodleClient(self.cfg["moodle_url"],
                                  self.cfg["username"],
                                  self.cfg["password"])
            info = client.get_user_info()
            userid = info["userid"]
            self._ui(self._log, f"✓ Eingeloggt als {info.get('fullname', userid)}")

            # ── 2. Courses ────────────────────────────────────────────
            all_courses = client.get_courses(userid)
            sel_ids = set(self.cfg.get("selected_courses", []))
            courses = [c for c in all_courses if c["id"] in sel_ids] if sel_ids else all_courses
            self._ui(self._log, f"Synchronisiere {len(courses)} Kurs(e) …")

            # ── 3. Download ───────────────────────────────────────────
            dl_root = Path(self.cfg.get("download_path", str(Path.home() / "Uni-Materialien")))
            new_files: list[tuple[str, Path]] = []

            for i, course in enumerate(courses):
                cname = course["fullname"]
                self._ui(self._log, f"  Kurs: {cname}")
                contents = client.get_course_contents(course["id"])

                for section in contents:
                    for module in section.get("modules", []):
                        for item in module.get("contents", []):
                            if item.get("type") != "file":
                                continue
                            fname = item["filename"]

                            # Skip video files
                            if Path(fname).suffix.lower() in VIDEO_EXTENSIONS:
                                self._ui(self._log, f"    ⏭ {fname} (Video)")
                                continue

                            category = classify_file(fname)
                            dest = dl_root / sanitize(cname) / category / sanitize(fname)
                            if dest.exists():
                                continue
                            self._ui(self._log, f"    ↓ [{category}] {fname}")
                            try:
                                if client.download_file(item["fileurl"], dest):
                                    new_files.append((cname, dest))
                            except Exception as e:
                                self._ui(self._log, f"    ✗ {fname}: {e}")

                pct = 0.05 + 0.45 * ((i + 1) / len(courses))
                self._ui(self._set_prog, pct, f"Lade: {cname}")

            new_count = len(new_files)
            self._ui(self._set_status, "download", f"✓ {new_count} neu", "green")
            self._ui(self._set_status, "sort", "✓ Sortiert", "green")
            self._ui(self._log, f"✓ {new_count} neue Datei(en) heruntergeladen")
            self._ui(self._set_prog, 0.5, "Download abgeschlossen")

            # ── 4. Flashcards ─────────────────────────────────────────
            if new_files:
                self._ui(self._set_status, "cards", "Erstelle …", "orange")
                self._ui(self._log, "Erstelle Karteikarten mit Ollama …")

                gen = FlashcardGenerator(
                    model=self.cfg.get("ollama_model", "llama3.2"),
                    ollama_url=self.cfg.get("ollama_url", "http://localhost:11434"),
                )
                prompt = self.cfg.get("prompt", DEFAULT_PROMPT)
                all_cards: dict[str, list[dict]] = {}
                processable = [f for f in new_files
                                if f[1].suffix.lower() in ('.pdf', '.txt', '.md')]

                for j, (cname, fpath) in enumerate(processable):
                    self._ui(self._log, f"  Verarbeite: {fpath.name}")
                    try:
                        text = gen.extract_text(fpath)
                        if not text.strip():
                            continue
                        cards = gen.generate_cards(text, prompt)
                        if cards:
                            all_cards.setdefault(cname, []).extend(cards)
                        self._ui(self._log, f"  ✓ {len(cards)} Karten aus {fpath.name}")
                    except Exception as e:
                        self._ui(self._log, f"  ✗ {fpath.name}: {e}")

                    pct = 0.5 + 0.4 * ((j + 1) / max(len(processable), 1))
                    self._ui(self._set_prog, pct, f"KI: {fpath.name}")

                total_cards = sum(len(v) for v in all_cards.values())
                self._ui(self._set_status, "cards", f"✓ {total_cards} Karten", "green")
                self._ui(self._log, f"✓ {total_cards} Karteikarten erstellt")

                # ── 5. Export ─────────────────────────────────────────
                self._ui(self._set_prog, 0.92, "Exportiere …")
                self._ui(self._set_status, "export", "Exportiere …", "orange")

                for cname, cards in all_cards.items():
                    export_path = dl_root / sanitize(cname) / "karteikarten_anki.txt"
                    gen.export_anki_txt(cards, export_path)
                    self._ui(self._log, f"  → {export_path}")

                self._ui(self._set_status, "export",
                         f"✓ {len(all_cards)} Dateien", "green")
            else:
                self._ui(self._log, "Keine neuen Dateien – überspringe Karteikarten-Erstellung.")
                for key in ("cards", "export"):
                    self._ui(self._set_status, key, "—", "gray60")

            self._ui(self._set_prog, 1.0, "Fertig!")
            self._ui(self._log, "═══ Fertig! ═══")

        except Exception as e:
            self._ui(self._log, f"✗ Fehler: {e}")
            self._ui(messagebox.showerror, "Fehler", str(e))
        finally:
            self._ui(self._sync_done)

    def _sync_done(self):
        self.running = False
        self._sync_btn.configure(state="normal", text="⟳  Alles aktualisieren")

    def _ui(self, fn, *args, **kwargs):
        """Schedule a UI call on the main thread."""
        self.after(0, lambda: fn(*args, **kwargs))


if __name__ == "__main__":
    app = App()
    app.mainloop()
