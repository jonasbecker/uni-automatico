import re
import requests
from pathlib import Path

MAX_TEXT_CHARS = 12000  # keep prompts manageable for local models


class FlashcardGenerator:
    def __init__(self, model: str = "llama3.2", ollama_url: str = "http://localhost:11434"):
        self.model = model
        self.ollama_url = ollama_url.rstrip('/')

    # ── Text extraction ────────────────────────────────────────────────────

    def extract_text(self, filepath: Path) -> str:
        suffix = filepath.suffix.lower()
        if suffix == '.pdf':
            return self._extract_pdf(filepath)
        if suffix in ('.txt', '.md'):
            return filepath.read_text(encoding='utf-8', errors='ignore')[:MAX_TEXT_CHARS]
        return ""

    def _extract_pdf(self, filepath: Path) -> str:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise Exception("PyMuPDF nicht installiert – bitte 'pip install PyMuPDF' ausführen.")
        doc = fitz.open(str(filepath))
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return text[:MAX_TEXT_CHARS]

    # ── Card generation ───────────────────────────────────────────────────

    def generate_cards(self, text: str, prompt_template: str) -> list[dict]:
        prompt = prompt_template.replace('{text}', text)
        try:
            resp = requests.post(f"{self.ollama_url}/api/generate", json={
                "model": self.model,
                "prompt": prompt,
                "stream": False
            }, timeout=300)
        except requests.exceptions.ConnectionError:
            raise Exception(
                f"Ollama nicht erreichbar unter {self.ollama_url}. "
                "Stelle sicher, dass 'ollama serve' läuft."
            )
        if resp.status_code != 200:
            raise Exception(f"Ollama Fehler {resp.status_code}: {resp.text[:300]}")
        response_text = resp.json().get('response', '')
        return self._parse_cards(response_text)

    def _parse_cards(self, text: str) -> list[dict]:
        cards = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '\t' in line:
                front, back = line.split('\t', 1)
                cards.append({'front': front.strip(), 'back': back.strip()})
            elif '::' in line:
                front, back = line.split('::', 1)
                cards.append({'front': front.strip(), 'back': back.strip()})
        return cards

    # ── File categorization ────────────────────────────────────────────────

    CATEGORIES = ("Vorlesungen", "Übungen", "Sonstige Dateien")

    def classify_files(self, filenames: list[str]) -> dict[str, str]:
        """Sort filenames into the three folder categories using the LLM.

        Returns a dict {filename: category}. Only filenames the model
        classified confidently are included — the caller falls back to
        keyword matching for any that are missing.
        """
        if not filenames:
            return {}

        listing = "\n".join(f"{i + 1}. {fn}" for i, fn in enumerate(filenames))
        prompt = (
            "Du sortierst Dateien einer Universitäts-Lehrveranstaltung in genau "
            "drei Kategorien:\n"
            "- Vorlesungen: Folien, Skripte, Vorlesungsmaterial, Handouts\n"
            "- Übungen: Übungsblätter, Aufgaben, Lösungen, Tutorien, Klausuren, "
            "Probeklausuren\n"
            "- Sonstige Dateien: alles andere (Organisatorisches, Literatur, "
            "Formulare …)\n\n"
            "Ordne jede Datei genau einer Kategorie zu. Antworte mit einer Zeile "
            "pro Datei im Format:\n"
            "Nummer<TAB>Kategorie\n"
            "Gib nur diese Zeilen aus, keine Erklärungen.\n\n"
            f"Dateien:\n{listing}"
        )

        try:
            resp = requests.post(f"{self.ollama_url}/api/generate", json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
            }, timeout=120)
            if resp.status_code != 200:
                return {}
            text = resp.json().get('response', '')
        except Exception:
            return {}

        return self._parse_classification(text, filenames)

    def _parse_classification(self, text: str, filenames: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            num_match = re.match(r'(\d+)', line)
            if not num_match:
                continue
            idx = int(num_match.group(1)) - 1
            if not (0 <= idx < len(filenames)):
                continue
            # Find which category name appears in the line
            for cat in self.CATEGORIES:
                if cat.lower() in line.lower():
                    result[filenames[idx]] = cat
                    break
        return result

    # ── Export ────────────────────────────────────────────────────────────

    def export_anki_txt(self, cards: list[dict], output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("#separator:tab\n#html:false\n")
            for card in cards:
                front = card['front'].replace('\t', ' ').replace('\n', ' ')
                back = card['back'].replace('\t', ' ').replace('\n', ' ')
                if front and back:
                    f.write(f"{front}\t{back}\n")
