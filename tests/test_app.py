"""Proxy behaviour tests. Run from the project folder:

    python -m unittest discover tests

No network or credentials needed: upstream calls are mocked.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.pop("DATABASE_URL", None)
os.environ.pop("APP_PASSWORD", None)

import requests  # noqa: E402

import app as appmod  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nfake"


def upstream(status=200, content=PNG, ctype="image/png", text=""):
    response = mock.Mock(status_code=status, content=content, text=text)
    response.headers = {"Content-Type": ctype}
    return response


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.client = appmod.app.test_client()

    def test_good_tile_is_cached(self):
        with mock.patch.object(appmod.http, "get", return_value=upstream()):
            r = self.client.get("/api/overlay/lineament?bbox=0,0,1,1")
        self.assertEqual(r.status_code, 200)
        self.assertIn("max-age", r.headers["Cache-Control"])

    def test_upstream_error_is_not_cached(self):
        xml = upstream(content=b"<ServiceExceptionReport/>", ctype="application/vnd.ogc.se_xml")
        with mock.patch.object(appmod.http, "get", return_value=xml):
            r = self.client.get("/api/overlay/lineament?bbox=0,0,1,1")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_upstream_timeout_is_not_cached(self):
        with mock.patch.object(appmod.http, "get", side_effect=requests.Timeout()):
            r = self.client.get("/api/overlay/structure?bbox=0,0,1,1")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_unknown_overlay_rejected(self):
        self.assertEqual(self.client.get("/api/overlay/evil").status_code, 404)


class TokenTests(unittest.TestCase):
    def test_concurrent_requests_fetch_one_token(self):
        calls = []

        def slow_post(*args, **kwargs):
            calls.append(1)
            time.sleep(0.2)
            return mock.Mock(raise_for_status=lambda: None,
                             json=lambda: {"access_token": "t", "expires_in": 3600})

        with mock.patch.object(appmod, "access_token", None), \
                mock.patch.object(appmod, "CLIENT_ID", "id"), \
                mock.patch.object(appmod, "CLIENT_SECRET", "secret"), \
                mock.patch.object(appmod.http, "post", side_effect=slow_post):
            threads = [threading.Thread(target=appmod.get_access_token) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(len(calls), 1)


class LbandTests(unittest.TestCase):
    def setUp(self):
        appmod._lband_searches.clear()
        self.client = appmod.app.test_client()

    def test_expired_search_is_reregistered_once(self):
        registers = []

        def post(*args, **kwargs):
            registers.append(1)
            return mock.Mock(raise_for_status=lambda: None,
                             json=lambda: {"searchid": f"id{len(registers)}"})

        def get(url, **kwargs):
            if "/id1/" in url:  # first id expired upstream
                return upstream(status=404, text="search not found")
            return upstream()

        with mock.patch.object(appmod.http, "post", side_effect=post), \
                mock.patch.object(appmod.http, "get", side_effect=get):
            first = self.client.get("/api/lband/9/380/218.png")
            second = self.client.get("/api/lband/9/381/218.png")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(registers), 2)

    def test_upstream_error_is_not_cached(self):
        post = mock.Mock(return_value=mock.Mock(raise_for_status=lambda: None,
                                                json=lambda: {"searchid": "x"}))
        with mock.patch.object(appmod.http, "post", post), \
                mock.patch.object(appmod.http, "get", return_value=upstream(status=429, text="Too Many")):
            r = self.client.get("/api/lband/9/380/218.png")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
