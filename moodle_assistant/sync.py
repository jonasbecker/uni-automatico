"""sync.py — Moodle web login, course listing, and file download."""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup


@dataclass
class Course:
    id: int
    name: str
    url: str


@dataclass
class Resource:
    id: int
    course_id: int
    course_name: str
    title: str
    url: str
    type: str  # file | assign | page | folder | url


def _safe_name(name: str) -> str:
    """Strip characters that are problematic in file/directory names."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip()


def _filename_from_response(resp: requests.Response, fallback: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename[^;=\n]*=(?:([\'"])(.+?)\1|([^\s;]+))', cd)
    if m:
        name = (m.group(2) or m.group(3) or "").strip()
        if name:
            return urllib.parse.unquote(name)
    # Try the final URL path
    url_path = resp.url.split("?")[0]
    url_name = urllib.parse.unquote(url_path.split("/")[-1])
    if "." in url_name:
        return url_name
    return _safe_name(fallback) + ".bin"


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

        m = re.search(r'"sesskey"\s*:\s*"([^"]+)"', resp.text)
        if m:
            self.sesskey = m.group(1)

    def get_courses(self) -> List[Course]:
        """Return enrolled courses via Moodle's internal AJAX endpoint."""
        courses = self._get_courses_via_ajax()
        if courses:
            return courses
        return self._get_courses_via_scraping()

    def _get_courses_via_ajax(self) -> List[Course]:
        if not self.sesskey:
            resp = self.session.get(f"{self.base_url}/my/", timeout=15)
            m = re.search(r'"sesskey"\s*:\s*"([^"]+)"', resp.text)
            if m:
                self.sesskey = m.group(1)
        if not self.sesskey:
            return []

        payload = [{
            "index": 0,
            "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
            "args": {
                "offset": 0, "limit": 0, "classification": "all",
                "customfieldname": "", "customfieldvalue": "", "searchvalue": "",
            },
        }]
        resp = self.session.post(
            f"{self.base_url}/lib/ajax/service.php"
            f"?sesskey={self.sesskey}&info=core_course_get_enrolled_courses_by_timeline_classification",
            json=payload, timeout=15,
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
        courses: List[Course] = []
        seen: set = set()
        for page in ["/my/", "/my/courses.php", "/course/index.php"]:
            resp = self.session.get(f"{self.base_url}{page}", timeout=15)
            if not resp.ok:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=re.compile(r"/course/view\.php\?id=\d+")):
                m = re.search(r"id=(\d+)", a["href"])
                if not m:
                    continue
                course_id = int(m.group(1))
                if course_id in seen:
                    continue
                seen.add(course_id)
                name = a.get_text(strip=True)
                if not name:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                courses.append(Course(id=course_id, name=name, url=full_url))
        return courses

    def get_course_resources(self, course: Course) -> List[Resource]:
        """Scrape a course page for all downloadable resources."""
        resp = self.session.get(course.url, timeout=15)
        if not resp.ok:
            return []
        soup = BeautifulSoup(resp.text, "lxml")

        type_patterns = {
            "file":   r"/mod/resource/view\.php\?id=(\d+)",
            "assign": r"/mod/assign/view\.php\?id=(\d+)",
            "page":   r"/mod/page/view\.php\?id=(\d+)",
            "folder": r"/mod/folder/view\.php\?id=(\d+)",
            "url":    r"/mod/url/view\.php\?id=(\d+)",
        }

        resources: List[Resource] = []
        seen: set = set()
        for rtype, pattern in type_patterns.items():
            for a in soup.find_all("a", href=re.compile(pattern)):
                m = re.search(r"id=(\d+)", a["href"])
                if not m:
                    continue
                rid = int(m.group(1))
                if rid in seen:
                    continue
                seen.add(rid)
                title = a.get_text(strip=True) or f"{rtype}_{rid}"
                href = a["href"]
                url = href if href.startswith("http") else f"{self.base_url}{href}"
                resources.append(Resource(
                    id=rid,
                    course_id=course.id,
                    course_name=course.name,
                    title=title,
                    url=url,
                    type=rtype,
                ))
        return resources

    def download_resource(self, resource: Resource, dest_dir: Path) -> Optional[Path]:
        """Download a file resource; return saved path or None if skipped/failed."""
        if resource.type != "file":
            return None

        resp = self.session.get(
            resource.url, timeout=30, allow_redirects=True, stream=True
        )
        if not resp.ok:
            return None

        # Skip HTML pages (Moodle error pages, not actual files)
        ct = resp.headers.get("Content-Type", "")
        if "text/html" in ct:
            return None

        filename = _filename_from_response(resp, resource.title)
        course_dir = dest_dir / _safe_name(resource.course_name)
        course_dir.mkdir(parents=True, exist_ok=True)
        dest_path = course_dir / filename

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)

        return dest_path
