import requests
from pathlib import Path


class MoodleClient:
    def __init__(self, url: str, username: str, password: str):
        self.url = url.rstrip('/')
        self.token = self._authenticate(username, password)

    def _authenticate(self, username: str, password: str) -> str:
        resp = requests.post(f"{self.url}/login/token.php", data={
            'username': username,
            'password': password,
            'service': 'moodle_mobile_app'
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if 'token' not in data:
            raise Exception(
                f"Login fehlgeschlagen: {data.get('error', data.get('debuginfo', 'Unbekannter Fehler'))}"
            )
        return data['token']

    def _call(self, function: str, **params) -> dict | list:
        resp = requests.post(f"{self.url}/webservice/rest/server.php", data={
            'wstoken': self.token,
            'wsfunction': function,
            'moodlewsrestformat': 'json',
            **{str(k): str(v) for k, v in params.items()}
        }, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, dict) and result.get('exception'):
            raise Exception(f"Moodle API Fehler: {result.get('message', str(result))}")
        return result

    def get_user_info(self) -> dict:
        return self._call('core_webservice_get_site_info')

    def get_courses(self, userid: int) -> list:
        return self._call('core_enrol_get_users_courses', userid=userid)

    def get_course_contents(self, courseid: int) -> list:
        return self._call('core_course_get_contents', courseid=courseid)

    def download_file(self, url: str, dest: Path) -> bool:
        """Download a file. Returns True if downloaded, False if skipped."""
        sep = '&' if '?' in url else '?'
        full_url = f"{url}{sep}token={self.token}"
        resp = requests.get(full_url, stream=True, timeout=120)
        resp.raise_for_status()

        # Skip non-file responses (e.g. HTML error pages)
        content_type = resp.headers.get('content-type', '')
        if 'text/html' in content_type and dest.suffix.lower() != '.html':
            return False

        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
