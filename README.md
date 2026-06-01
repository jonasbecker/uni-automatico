# uni-automatico

Automatischer Lernassistent – Materialien herunterladen, sortieren und Anki-Karteikarten erstellen.

## Voraussetzungen

- Python 3.10+
- [Ollama](https://ollama.com) lokal installiert und gestartet (`ollama serve`)
- Ein Sprachmodell in Ollama, z.B. `ollama pull llama3.2`
- Moodle-Zugang deiner Uni (Web-Services müssen aktiviert sein)

## Start

```bash
./start.sh
```

Oder manuell:

```bash
pip install -r requirements.txt
python main.py
```

## Erster Start

1. **Einstellungen** öffnen → Moodle URL, Benutzername, Passwort eintragen
2. **Kurse** laden und gewünschte Kurse auswählen
3. Auf **Alles aktualisieren** klicken

## Was passiert beim Klick

1. Login bei Moodle via Web Services API
2. Neue Dateien (PDF, TXT, MD) je Kurs herunterladen
3. Dateien nach Kursname sortieren
4. Jede neue Datei mit Ollama analysieren → Karteikarten erstellen
5. Export als `karteikarten_anki.txt` im Kursordner (Tab-getrennt, Anki-kompatibel)

## Anki-Import

In Anki: **Datei → Importieren** → `karteikarten_anki.txt` auswählen.  
Trennzeichen: Tab (wird automatisch erkannt).
