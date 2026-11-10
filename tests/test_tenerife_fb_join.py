"""Facebook /tenerife/join/ waitlist: validation, honeypot, attribution, storage, CRM contract."""
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
import artemis_sync_event_fields  # noqa: E402
import funnel_store as fstore  # noqa: E402
import tenerife_join  # noqa: E402
import tenerife_join_crm  # noqa: E402


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
        self.funnel = patch.dict(
            os.environ,
            ARTEMIS_FUNNEL_ENABLED="0",
            ARTEMIS_NEWSLETTER_SECRET="",
            ARTEMIS_JOIN_TYPED_CRM="1",
        )
        self.funnel.start()
        self.client = app.app.test_client()

    def tearDown(self):
        self.funnel.stop()
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
        self.assertNotIn("Referrer-Policy", r.headers)
        self.assertNotIn(b"yield", r.data.lower())

    def test_lang_preselects_language_field(self):
        r = self.get_form("?lang=de")
        self.assertIn(b'value="de" selected', r.data)

    def test_src_ref_hidden_fields(self):
        r = self.get_form("?src=fb-page&ref=post-123")
        h = Hidden(r.data).hidden
        self.assertEqual(h["fb_src"], "fb-page")
        self.assertEqual(h["fb_ref"], "post-123")

    def test_validation_aria_invalid(self):
        r = self.get_form()
        sid = Hidden(r.data).hidden["submission_id"]
        r = self.post(submission_id=sid, name="", facebook="@valid.user", interest="buyer", language="en", consent="1")
        self.assertEqual(r.status_code, 400)
        self.assertIn(b'aria-invalid="true"', r.data)
        self.assertIn(b'id="join-errors"', r.data)

    def test_facebook_display_name_unicode(self):
        self.assertEqual(tenerife_join.resolve_facebook_contact("Иван Петров"), "Иван Петров")
        self.assertEqual(tenerife_join.resolve_facebook_contact("José Muñoz"), "José Muñoz")

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
        self.mock_notify.assert_not_called()

    def test_success_stores_waitlist_and_crm_contract(self):
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
        self.assertIn("facebook.com", wl[0][1])
        self.assertIn("optional@example.invalid", wl[0][1])
        event = json.loads(self.rows("SELECT payload FROM artemis_events")[0][0])
        artemis_sync_event_fields.assert_artemis_sync_event(event)
        self.assertEqual(event["source_id"], "FB")
        self.assertEqual(event["capture_origin"], "website")
        self.assertEqual(event["utm_source"], "fb-group")
        self.assertNotIn("consent_at", event)
        self.assertNotIn("optional_email", event)

    def test_duplicate_submission_no_double_notify(self):
        r = self.get_form()
        sid = Hidden(r.data).hidden["submission_id"]
        base = dict(
            submission_id=sid,
            name="TEST",
            facebook="@test.person",
            interest="buyer",
            language="en",
            consent="1",
        )
        self.assertEqual(self.post(**base).status_code, 303)
        self.assertEqual(self.post(**base).status_code, 303)
        self.assertEqual(len(self.rows("SELECT * FROM tenerife_waitlist")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM artemis_events")), 1)
        self.mock_notify.assert_called_once()

    def test_submission_id_conflict_409(self):
        r = self.get_form()
        sid = Hidden(r.data).hidden["submission_id"]
        base = dict(
            submission_id=sid,
            name="TEST",
            facebook="@test.person",
            interest="buyer",
            language="en",
            consent="1",
        )
        self.assertEqual(self.post(**base).status_code, 303)
        self.assertEqual(self.post(**dict(base, name="OTHER")).status_code, 409)

    def test_join_typed_off_uses_legacy_when_crm_capture(self):
        with patch.dict(
            os.environ,
            ARTEMIS_JOIN_TYPED_CRM="0",
            ARTEMIS_CRM_CAPTURE_ENABLED="1",
        ):
            r = self.get_form()
            sid = Hidden(r.data).hidden["submission_id"]
            self.assertEqual(
                self.post(
                    submission_id=sid,
                    name="LEG",
                    facebook="@leg.user",
                    interest="partner",
                    language="en",
                    consent="1",
                ).status_code,
                303,
            )
        event = json.loads(self.rows("SELECT payload FROM artemis_events")[0][0])
        self.assertTrue(event["source_event_id"].startswith("artemis:legacy:"))
        self.assertEqual(event.get("source_id"), "unknown")
        self.assertNotEqual(event.get("contact_type"), "facebook")

    def test_prod_flags_join_typed_without_global_funnel(self):
        """Prod: funnel off, CRM_CAPTURE on — JOIN_TYPED_CRM must emit FB typed events."""
        with patch.dict(
            os.environ,
            ARTEMIS_FUNNEL_ENABLED="0",
            ARTEMIS_NEWSLETTER_SECRET="",
            ARTEMIS_JOIN_TYPED_CRM="1",
            ARTEMIS_CRM_CAPTURE_ENABLED="1",
        ):
            r = self.get_form("?src=fb-page&ref=r1")
            h = Hidden(r.data).hidden
            self.assertEqual(
                self.post(
                    submission_id=h["submission_id"],
                    fb_src=h["fb_src"],
                    fb_ref=h["fb_ref"],
                    name="PROD",
                    facebook="@prod.user",
                    interest="investor",
                    language="en",
                    consent="1",
                ).status_code,
                303,
            )
        event = json.loads(self.rows("SELECT payload FROM artemis_events")[0][0])
        self.assertEqual(event["source_id"], "FB")
        self.assertEqual(event["contact_type"], "facebook")
        self.assertEqual(event["intent"], "investor")
        self.assertEqual(event["utm_source"], "fb-page")

    def test_strip_bidi_from_name(self):
        r = self.get_form()
        sid = Hidden(r.data).hidden["submission_id"]
        self.assertEqual(
            self.post(
                submission_id=sid,
                name="A\u200bB",
                facebook="@x.user",
                interest="buyer",
                language="en",
                consent="1",
            ).status_code,
            303,
        )
        self.assertEqual(self.rows("SELECT name FROM tenerife_waitlist")[0][0], "AB")

    def test_thanks_hides_group_without_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARTEMIS_FB_PRIVATE_GROUP_URL", None)
            r = self.client.get("/tenerife/join/gracias/?lang=en")
        self.assertNotIn(b"btn-primary", r.data)

    def test_main_funnel_unchanged_by_join_flag(self):
        """ARTEMIS_JOIN_TYPED_CRM must not change /api/tenerife/waitlist typed capture."""
        d = dict(
            submission_id="main-funnel-flag-check-01",
            intent="investor",
            name="TEST",
            contact_type="email",
            contact="test@example.invalid",
            language="en",
            consent=True,
            newsletter_opt_in=False,
            page="/tenerife/inversores/",
        )
        env_on = dict(
            ARTEMIS_FUNNEL_ENABLED="1",
            ARTEMIS_NEWSLETTER_SECRET="isolated-test-secret-at-least-32-chars",
            ARTEMIS_JOIN_TYPED_CRM="0",
        )
        env_flag = dict(env_on, ARTEMIS_JOIN_TYPED_CRM="1")
        payloads = []
        for env in (env_on, env_flag):
            db = os.path.join(self.tmp.name, f"funnel-{env['ARTEMIS_JOIN_TYPED_CRM']}.db")
            with patch.dict(os.environ, env, clear=False):
                with patch.object(app, "DB", db):
                    with patch("tenerife.notify_lead"):
                        client = app.app.test_client()
                        r = client.post("/api/tenerife/waitlist", json=d)
                        self.assertEqual(r.status_code, 200)
                        with sqlite3.connect(db) as c:
                            fstore.migrate(c)
                            payloads.append(json.loads(c.execute("SELECT payload FROM artemis_events").fetchone()[0]))
        for key in ("created_at", "newsletter_requested_at"):
            payloads[0].pop(key, None)
            payloads[1].pop(key, None)
        self.assertEqual(payloads[0], payloads[1])

    def test_join_crm_builder_matches_normalize_byte_identity(self):
        """Existing typed funnel events must stay byte-identical (funnel_store.normalize unchanged)."""
        import datetime

        now = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
        data = dict(
            submission_id="byte-identity-check-01",
            intent="investor",
            name="TEST",
            contact_type="email",
            contact="test@example.invalid",
            language="de",
            consent=True,
            newsletter_opt_in=False,
            page="/tenerife/inversores/",
        )
        event = fstore.normalize(data, now)
        self.assertNotIn("consent_at", event)
        self.assertNotIn("optional_email", event)

    def test_existing_index_unchanged(self):
        with patch.dict(os.environ, ARTEMIS_FUNNEL_ENABLED="0", ARTEMIS_NEWSLETTER_SECRET=""):
            before = self.client.get("/tenerife/").data
            self.get_form()
            self.assertEqual(before, self.client.get("/tenerife/").data)


class JoinContractTest(unittest.TestCase):
    def test_build_join_event_passes_artemis_sync(self):
        import datetime

        now = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        event = tenerife_join_crm.build_join_event(
            "contract-test-submission-01", "N", "https://www.facebook.com/x", "buyer", "en", "fb-page", "p1", now
        )
        artemis_sync_event_fields.assert_artemis_sync_event(event)


if __name__ == "__main__":
    unittest.main()
