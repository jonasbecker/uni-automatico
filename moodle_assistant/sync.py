"""sync.py — logs into Moodle via web form and downloads course materials."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List

import requests
from bs4 import BeautifulSoup


@dataclass
class Course:
    id: int
    name: str
    url: str


class MoodleClient:
    """Authenticated Moodle session using the standard web login."""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.sesskey: str = ""
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    def login(self) -> None:
        """Authenticate via the Moodle web login form and extract sesskey."""
        login_url = f"{self.base_url}/login/index.php"

        resp = self.session.get(login_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        token_input = soup.find("input", {"name": "logintoken"})
        login_token = token_input["value"] if token_input else ""

        resp = self.session.post(
            login_url,
            data={
                "username": self.username,
                "password": self.password,
                "logintoken": login_token,
                "anchor": "",
            },
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()

        if "login/index.php" in resp.url:
            raise ValueError("Login failed — check username and password.")

        # Extract sesskey — needed for AJAX calls (embedded as M.cfg.sesskey)
        m = re.search(r'"sesskey"\s*:\s*"([^"]+)"', resp.text)
        if m:
            self.sesskey = m.group(1)

    def get_courses(self) -> List[Course]:
        """Return enrolled courses via Moodle's internal AJAX endpoint."""
        courses = self._get_courses_via_ajax()
        if courses:
            return courses
        # Fallback: scrape static HTML (only catches visible links)
        return self._get_courses_via_scraping()

    def _get_courses_via_ajax(self) -> List[Course]:
        """Call core_course_get_enrolled_courses_by_timeline_classification via AJAX."""
        if not self.sesskey:
            # Try to fetch sesskey from dashboard
            resp = self.session.get(f"{self.base_url}/my/", timeout=15)
            m = re.search(r'"sesskey"\s*:\s*"([^"]+)"', resp.text)
            if m:
                self.sesskey = m.group(1)
        if not self.sesskey:
            return []

        payload = [
            {
                "index": 0,
                "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
                "args": {
                    "offset": 0,
                    "limit": 0,
                    "classification": "all",
                    "customfieldname": "",
                    "customfieldvalue": "",
                    "searchvalue": "",
                },
            }
        ]

        resp = self.session.post(
            f"{self.base_url}/lib/ajax/service.php?sesskey={self.sesskey}&info=core_course_get_enrolled_courses_by_timeline_classification",
            json=payload,
            timeout=15,
        )
        if not resp.ok:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        if not data or data[0].get("error"):
            return []

        courses = []
        for c in data[0].get("data", {}).get("courses", []):
            course_id = c.get("id")
            name = c.get("fullname") or c.get("shortname") or f"Course {course_id}"
            url = c.get("viewurl") or f"{self.base_url}/course/view.php?id={course_id}"
            courses.append(Course(id=course_id, name=name, url=url))
        return courses

    def _get_courses_via_scraping(self) -> List[Course]:
        """Fallback: scrape course links from static HTML pages."""
        courses: List[Course] = []
        seen: set = set()
        for page in ["/my/", "/my/courses.php", "/course/index.php"]:
            resp = self.session.get(f"{self.base_url}{page}", timeout=15)
            if not resp.ok:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=re.compile(r"/course/view\.php\?id=\d+")):
                href = a["href"]
                m = re.search(r"id=(\d+)", href)
                if not m:
                    continue
                course_id = int(m.group(1))
                if course_id in seen:
                    continue
                seen.add(course_id)
                name = a.get_text(strip=True)
                if not name:
                    continue
                full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                courses.append(Course(id=course_id, name=name, url=full_url))
        return courses
