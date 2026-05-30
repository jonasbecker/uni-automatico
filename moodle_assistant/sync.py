"""sync.py — logs into Moodle via web form and downloads course materials."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
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
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    def login(self) -> None:
        """Authenticate via the Moodle web login form."""
        login_url = f"{self.base_url}/login/index.php"

        # Fetch login page to get the CSRF logintoken
        resp = self.session.get(login_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        token_input = soup.find("input", {"name": "logintoken"})
        login_token = token_input["value"] if token_input else ""

        # POST credentials
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

        # Moodle redirects away from /login/index.php on success
        if "login/index.php" in resp.url:
            raise ValueError("Login failed — check username and password.")

    def get_courses(self) -> List[Course]:
        """Return the list of enrolled courses by scraping multiple Moodle pages."""
        courses: List[Course] = []
        seen: set = set()

        # Moodle shows enrolled courses across different pages depending on version/theme
        pages = [
            "/my/",
            "/my/courses.php",
            "/course/index.php",
        ]

        for page in pages:
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
