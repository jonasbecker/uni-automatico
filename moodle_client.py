import re
import requests
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False


def _find_all(html: str, pattern: str) -> list[str]:
    """Simple regex helper when BeautifulSoup is unavailable."""
    return re.findall(pattern, html)


class MoodleClient:
    def __init__(self, url: str, username: str, password: str):
        self.url = url.rstrip('/')
        self._session = requests.Session()
        self._session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; uni-automatico)'})
        self._token: str | None = None
        self._sesskey: str | None = None
        self._userid: int | None = None
        self._fullname: str = 'Nutzer'
        self._auth_mode: str = 'token'
        self._authenticate(username, password)

    # ── Authentication ─────────────────────────────────────────────────────

    def _authenticate(self, username: str, password: str):
        for service in ('moodle_mobile_app', 'moodle_mobile_app_nosso'):
            try:
                resp = self._session.post(f"{self.url}/login/token.php", data={
                    'username': username,
                    'password': password,
                    'service': service,
                }, timeout=30)
                data = resp.json()
                if 'token' in data:
                    self._token = data['token']
                    self._auth_mode = 'token'
                    return
            except Exception:
                continue

        # Fallback: cookie-session login
        self._login_session(username, password)

    def _login_session(self, username: str, password: str):
        # Fetch login page for CSRF token
        resp = self._session.get(f"{self.url}/login/index.php", timeout=30)
        resp.raise_for_status()

        logintoken = ''
        m = re.search(r'name="logintoken"\s+value="([^"]+)"', resp.text)
        if m:
            logintoken = m.group(1)

        resp = self._session.post(f"{self.url}/login/index.php", data={
            'username': username,
            'password': password,
            'logintoken': logintoken,
            'anchor': '',
        }, timeout=30, allow_redirects=True)
        resp.raise_for_status()

        # Detect login failure
        if re.search(r'(loginerrors|errormessage|invalidlogin)', resp.text, re.I):
            raise Exception("Login fehlgeschlagen: Benutzername oder Passwort falsch.")
        if '/login/' in resp.url:
            raise Exception("Login fehlgeschlagen: Moodle hat die Anmeldung abgelehnt.")

        # Extract JS config values
        m = re.search(r'"sesskey"\s*:\s*"([a-zA-Z0-9]+)"', resp.text)
        self._sesskey = m.group(1) if m else None

        m = re.search(r'"userid"\s*:\s*(\d+)', resp.text)
        self._userid = int(m.group(1)) if m else None

        m = re.search(r'"fullname"\s*:\s*"([^"]+)"', resp.text)
        self._fullname = m.group(1) if m else 'Nutzer'

        self._auth_mode = 'session'

    # ── Web Service (token mode) ───────────────────────────────────────────

    def _call(self, function: str, **params) -> dict | list:
        resp = self._session.post(f"{self.url}/webservice/rest/server.php", data={
            'wstoken': self._token,
            'wsfunction': function,
            'moodlewsrestformat': 'json',
            **{str(k): str(v) for k, v in params.items()},
        }, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, dict) and result.get('exception'):
            raise Exception(f"Moodle API Fehler: {result.get('message', str(result))}")
        return result

    # ── Public API ────────────────────────────────────────────────────────

    def get_user_info(self) -> dict:
        if self._auth_mode == 'token':
            return self._call('core_webservice_get_site_info')
        return {
            'userid': self._userid,
            'fullname': self._fullname,
            'sitename': self.url,
        }

    def get_courses(self, userid: int) -> list:
        if self._auth_mode == 'token':
            return self._call('core_enrol_get_users_courses', userid=userid)
        return self._scrape_courses()

    def get_course_contents(self, courseid: int) -> list:
        if self._auth_mode == 'token':
            return self._call('core_course_get_contents', courseid=courseid)
        return self._scrape_course_contents(courseid)

    def download_file(self, url: str, dest: Path) -> bool:
        if self._auth_mode == 'token':
            sep = '&' if '?' in url else '?'
            resp = self._session.get(f"{url}{sep}token={self._token}",
                                     stream=True, timeout=120)
        else:
            resp = self._session.get(url, stream=True, timeout=120, allow_redirects=True)

        resp.raise_for_status()
        content_type = resp.headers.get('content-type', '')
        if 'text/html' in content_type and dest.suffix.lower() != '.html':
            return False

        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True

    # ── Session-mode scraping ─────────────────────────────────────────────

    def _scrape_courses(self) -> list:
        resp = self._session.get(f"{self.url}/my/", timeout=30)
        courses, seen = [], set()

        for href, name in re.findall(
            r'href="([^"]*?/course/view\.php\?id=(\d+)[^"]*)"[^>]*>([^<]+)<',
            resp.text
        ):
            cid_match = re.search(r'id=(\d+)', href)
            if not cid_match:
                continue
            cid = int(cid_match.group(1))
            name = re.sub(r'\s+', ' ', name).strip()
            if cid not in seen and name:
                seen.add(cid)
                courses.append({'id': cid, 'fullname': name, 'shortname': str(cid)})

        if not courses:
            # Broader fallback: any course link on the page
            for m in re.finditer(r'/course/view\.php\?id=(\d+)', resp.text):
                cid = int(m.group(1))
                if cid not in seen:
                    seen.add(cid)
                    courses.append({'id': cid, 'fullname': f'Kurs {cid}', 'shortname': str(cid)})

        return courses

    def _scrape_course_contents(self, courseid: int) -> list:
        resp = self._session.get(f"{self.url}/course/view.php",
                                  params={'id': courseid}, timeout=30)

        modules = []
        seen_ids = set()

        # Match resource/folder/url module links
        pattern = re.compile(
            r'href="([^"]*?/mod/(?:resource|folder)/view\.php\?id=(\d+)[^"]*)"'
            r'[^>]*>.*?<span[^>]*>([^<]+)</span>',
            re.DOTALL
        )
        for m in pattern.finditer(resp.text):
            href, mid_str, name = m.group(1), m.group(2), m.group(3)
            mid = int(mid_str)
            if mid in seen_ids:
                continue
            seen_ids.add(mid)

            name = re.sub(r'\s+', ' ', name).strip()
            contents = self._resolve_resource(href)
            if contents:
                modules.append({
                    'id': mid,
                    'name': name,
                    'modname': 'resource',
                    'contents': contents,
                })

        # Fallback: find any mod/resource links
        if not modules:
            for m in re.finditer(r'href="([^"]*?/mod/resource/view\.php\?id=(\d+)[^"]*)"', resp.text):
                mid = int(m.group(2))
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                href = m.group(1)
                contents = self._resolve_resource(href)
                if contents:
                    modules.append({
                        'id': mid,
                        'name': f'Ressource {mid}',
                        'modname': 'resource',
                        'contents': contents,
                    })

        return [{'id': 0, 'name': 'Kursinhalt', 'modules': modules}]

    def _resolve_resource(self, module_url: str) -> list:
        """Follow a resource module URL to get the actual file URL and name."""
        try:
            # Use stream=True + close() to read headers only (no body transfer)
            resp = self._session.get(module_url, timeout=15,
                                     allow_redirects=True, stream=True)
            final_url = resp.url
            content_type = resp.headers.get('content-type', '')
            content_disp = resp.headers.get('content-disposition', '')
            resp.close()

            if 'text/html' in content_type and 'attachment' not in content_disp:
                # HTML page — try to find pluginfile link inside
                resp2 = self._session.get(module_url, timeout=15, allow_redirects=True)
                plug_m = re.search(r'href="([^"]*pluginfile\.php[^"]+)"', resp2.text)
                if plug_m:
                    file_url = plug_m.group(1).replace('&amp;', '&')
                    filename = file_url.split('/')[-1].split('?')[0]
                    return [{'type': 'file', 'filename': filename, 'fileurl': file_url}]
                return []

            # Get filename from content-disposition or URL
            m = re.search(r"filename\*?=['\"]?(?:UTF-\d'[^']*')?([^'\";\r\n]+)", content_disp)
            if m:
                filename = m.group(1).strip().strip('"\'')
            else:
                filename = final_url.split('/')[-1].split('?')[0]

            if not filename:
                return []

            return [{'type': 'file', 'filename': filename, 'fileurl': final_url}]

        except Exception:
            return []
