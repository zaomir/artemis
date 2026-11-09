"""Facebook /tenerife/join/ waitlist: validation, honeypot, attribution, storage."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ.setdefault("RATE_LIMIT_SALT", "isolated-tests-only")

import app  # noqa: E402


class Hidden(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.hidden = {}
        self.feed(body.decode())

    def handle_starttag(self, tag, attrs):
        if tag != "input":
            return
        d = dict(attrs)
        if d.get("type") == "hidden" and d.get("name"):
            self.hidden[d["name"]] = d.get("value", "")


class FbJoinTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "leads.db")
        self.notify = patch("tenerife_join.notify_lead")
        self.mock_notify = self.notify.start()
        self.dbpatch = patch.object(app, "DB", self.db)
        self.dbpatch.start()
        self.client = app.app.test_client()

    def tearDown(self):
        self.dbpatch.stop()
        self.notify.stop()
        self.tmp.cleanup()

    def get_form(self, query=""):
        return self.client.get("/tenerife/join/" + query)

    def post(self, **fields):
        return self.client.post("/tenerife/join/", data=fields)

    def rows(self, sql):
        with sqlite3.connect(self.db) as c:
            return c.execute(sql).fetchall()

    def test_default_english_noindex(self):
        r = self.get_form()
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'lang="en"', r.data)
        self.assertEqual(r.headers.get("X-Robots-Tag"), "noindex, nofollow")
        self.assertNotIn(b"yield", r.data.lower())
        self.assertNotIn(b"\xe2\x82\xac", r.data)

    def test_lang_parameter(self):
        r = self.get_form("?lang=de")
        self.assertIn(b'lang="de"', r.data)
        self.assertIn("Warteliste".encode(), r.data)

    def test_src_ref_hidden_fields(self):
        r = self.get_form("?src=fb-page&ref=post-123")
        h = Hidden(r.data).hidden
        self.assertEqual(h["fb_src"], "fb-page")
        self.assertEqual(h["fb_ref"], "post-123")

    def test_validation_errors(self):
        r = self.get_form()
        sid = Hidden(r.data).hidden["submission_id"]
        r = self.post(submission_id=sid, name="", facebook="@valid.user", interest="buyer", language="en", consent="1")
        self.assertEqual(r.status_code, 400)
        r = self.post(
            submission_id=sid,
            name="TEST",
            facebook="not-a-facebook",
            interest="buyer",
            language="en",
            consent="1",
        )
        self.assertEqual(r.status_code, 400)
        with sqlite3.connect(self.db) as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='tenerife_waitlist'").fetchone():
                self.assertFalse(c.execute("SELECT * FROM tenerife_waitlist").fetchall())

    def test_honeypot_drops_without_storage(self):
        r = self.get_form()
        sid = Hidden(r.data).hidden["submission_id"]
        r = self.post(
            submission_id=sid,
            name="BOT",
            facebook="@bot.user",
            interest="buyer",
            language="en",
            consent="1",
            website="http://spam.example",
        )
        self.assertEqual(r.status_code, 303)
        self.assertIn("/tenerife/join/gracias/", r.headers["Location"])
        with sqlite3.connect(self.db) as c:
            self.assertFalse(
                c.execute("SELECT 1 FROM sqlite_master WHERE name='tenerife_waitlist'").fetchall()
                and c.execute("SELECT * FROM tenerife_waitlist").fetchall()
            )
        self.mock_notify.assert_not_called()

    def test_success_stores_waitlist_and_crm_outbox(self):
        r = self.get_form("?src=fb-group&ref=g1")
        h = Hidden(r.data).hidden
        r = self.post(
            submission_id=h["submission_id"],
            fb_src=h["fb_src"],
            fb_ref=h["fb_ref"],
            name="TEST FB",
            facebook="@test.person",
            interest="investor",
            language="es",
            email="optional@example.invalid",
            consent="1",
        )
        self.assertEqual(r.status_code, 303)
        wl = self.rows("SELECT name,contact,language,page FROM tenerife_waitlist")
        self.assertEqual(len(wl), 1)
        self.assertEqual(wl[0][0], "TEST FB")
        self.assertIn("facebook.com", wl[0][1])
        self.assertEqual(wl[0][2], "es")
        self.assertEqual(wl[0][3], "/tenerife/join/")
        self.assertEqual(len(self.rows("SELECT * FROM artemis_crm_outbox")), 1)
        event = json.loads(self.rows("SELECT payload FROM artemis_events")[0][0])
        self.assertEqual(event["source_id"], "FB")
        self.assertEqual(event["capture_origin"], "facebook")
        self.assertEqual(event["utm_source"], "fb-group")
        self.assertEqual(event["utm_campaign"], "g1")
        self.assertEqual(event["intent"], "investor")
        self.assertEqual(event["consent_at"][:10], event["created_at"][:10])
        self.assertEqual(event.get("optional_email"), "optional@example.invalid")
        self.mock_notify.assert_called_once()

    def test_thanks_page_messenger_line_and_disclaimer(self):
        r = self.client.get("/tenerife/join/gracias/?lang=ru")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Messenger".encode(), r.data)
        self.assertIn("\u043d\u0435 \u0431\u0440\u043e\u043d\u044c".encode(), r.data)

    def test_existing_index_unchanged(self):
        before = self.client.get("/tenerife/").data
        r = self.get_form()
        self.assertEqual(before, self.client.get("/tenerife/").data)
        self.assertNotEqual(before, r.data)


if __name__ == "__main__":
    unittest.main()
