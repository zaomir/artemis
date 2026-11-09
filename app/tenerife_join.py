"""Standalone Facebook waitlist: GET/POST /tenerife/join/ and thank-you page.

Does not modify committed static /tenerife/* HTML. Reuses waitlist DB, rate limits,
honeypot and artemis_events / CRM outbox (twenty-sync via existing lead relay).
"""
from __future__ import annotations

import datetime
import os
import re
import sqlite3
import uuid
from urllib.parse import urlencode

from flask import make_response, redirect, render_template, request

import funnel_store as store
import tenerife_join_copy as copy

from notify import notify_lead

JOIN_PATH = "/tenerife/join/"
THANKS_PATH = "/tenerife/join/gracias/"
INTERESTS = frozenset({"buyer", "investor", "partner"})
SRC_RX = re.compile(r"[A-Za-z0-9_.:-]{1,100}")
REF_RX = re.compile(r"[A-Za-z0-9_.:-]{1,200}")


def _ui_lang() -> str:
    raw = (request.args.get("lang") or request.form.get("ui_lang") or "en").strip().lower()[:5]
    return raw if raw in copy.JOIN_LANGS else "en"


def _capture_attribution() -> tuple[str, str]:
    src = (request.args.get("src") or request.form.get("fb_src") or "").strip()[:100]
    ref = (request.args.get("ref") or request.form.get("fb_ref") or "").strip()[:100]
    if src and not SRC_RX.fullmatch(src):
        src = ""
    if ref and not REF_RX.fullmatch(ref):
        ref = ""
    return src, ref


def _headers(resp):
    resp.headers.update(
        {
            "Cache-Control": "no-store, max-age=0",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
        }
    )
    return resp


def _group_url() -> tuple[str, bool]:
    raw = os.environ.get("ARTEMIS_FB_PRIVATE_GROUP_URL", "").strip()
    if raw.startswith("https://"):
        return raw, False
    return "https://www.facebook.com/", True


def _consent_ok(value) -> bool:
    return str(value or "").lower() in {"1", "true", "on", "yes"}


def _build_capture_payload(
    submission_id: str,
    name: str,
    facebook: str,
    interest: str,
    language: str,
    email: str,
    src: str,
    ref: str,
    now: datetime.datetime,
) -> dict:
    """Event fields for funnel_store.capture (CRM outbox + relay → twenty-sync)."""
    data = {
        "submission_id": submission_id,
        "intent": interest,
        "name": name,
        "contact_type": "facebook",
        "contact": facebook,
        "language": language,
        "consent": True,
        "newsletter_opt_in": False,
        "page": JOIN_PATH,
        "source_id": "FB",
        "form_id": "fb-join",
        "capture_origin": "facebook",
    }
    if src:
        data["utm_source"] = src
    if ref:
        data["utm_campaign"] = ref
    if email:
        data["optional_email"] = email
    return data


def register(bp, db_path, client_hash, honeypot_field, rate_max, rate_window_min, init_waitlist_db):
    """Attach routes to the Tenerife blueprint."""

    @bp.route(JOIN_PATH, methods=["GET", "POST"])
    def fb_join():
        ui = _ui_lang()
        labels = copy.COPY[ui]
        src, ref = _capture_attribution()

        if request.method == "GET":
            q = {}
            if request.args.get("lang"):
                q["lang"] = ui
            if src:
                q["src"] = src
            if ref:
                q["ref"] = ref
            body = render_template(
                "tenerife/join_form.html",
                ui_lang=ui,
                labels=labels,
                lang_options=[(c, copy.LANG_LABELS[c]) for c in copy.JOIN_LANGS],
                submission_id=str(uuid.uuid4()),
                fb_src=src,
                fb_ref=ref,
                values={},
                error="",
            )
            return _headers(make_response(body))

        # POST
        if str(request.form.get(honeypot_field) or "").strip():
            return redirect(THANKS_PATH + "?" + urlencode({"lang": ui}), code=303)

        values = {k: request.form.get(k, "") for k in ("name", "facebook", "interest", "language", "email")}
        values["consent"] = _consent_ok(request.form.get("consent"))
        submission_id = str(request.form.get("submission_id") or "")
        src, ref = _capture_attribution()

        def fail(msg: str, status: int = 400):
            body = render_template(
                "tenerife/join_form.html",
                ui_lang=ui,
                labels=labels,
                lang_options=[(c, copy.LANG_LABELS[c]) for c in copy.JOIN_LANGS],
                submission_id=submission_id if store.ID.fullmatch(submission_id) else str(uuid.uuid4()),
                fb_src=src,
                fb_ref=ref,
                values=values,
                error=msg,
            )
            return _headers(make_response(body, status))

        if not store.ID.fullmatch(submission_id):
            return fail(labels["err_server"], 400)

        name = " ".join(str(values["name"] or "").split())[:120]
        if not name:
            return fail(labels["err_name"])

        raw_fb = str(values["facebook"] or "").strip()
        try:
            fb_contact = store.contact_value("facebook", raw_fb)
        except ValueError:
            return fail(labels["err_facebook"])

        interest = str(values["interest"] or "").strip()
        if interest not in INTERESTS:
            return fail(labels["err_interest"])

        language = str(values["language"] or "").strip().lower()
        if language not in store.LANGUAGES:
            return fail(labels["err_language"])

        if not values["consent"]:
            return fail(labels["err_consent"])

        email = str(values["email"] or "").strip()
        if email and not store.EMAIL.fullmatch(email):
            return fail(labels["err_email"])

        now = datetime.datetime.now(datetime.timezone.utc)
        since = (now - datetime.timedelta(minutes=rate_window_min)).isoformat()
        client = client_hash()
        conn = None
        legacy = None
        try:
            conn = sqlite3.connect(db_path(), timeout=5)
            init_waitlist_db(conn)
            store.migrate(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")

            if conn.execute(
                "SELECT 1 FROM artemis_events WHERE submission_id=?", (submission_id,)
            ).fetchone():
                conn.rollback()
                conn.close()
                return redirect(THANKS_PATH + "?" + urlencode({"lang": ui}), code=303)

            recent_waitlist = conn.execute(
                "SELECT COUNT(*) FROM tenerife_waitlist WHERE client_hash=? AND created_at>=?",
                (client, since),
            ).fetchone()[0]
            recent_events = 0
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='artemis_events'"
            ).fetchone():
                recent_events = conn.execute(
                    "SELECT COUNT(*) FROM artemis_events WHERE client_hash=? AND created_at>=?",
                    (client, since),
                ).fetchone()[0]
            if max(recent_waitlist, recent_events) >= rate_max:
                conn.rollback()
                return fail(labels["err_rate"], 429)

            waitlist_contact = fb_contact
            if email:
                waitlist_contact = f"{fb_contact} | {email.casefold()}"

            cursor = conn.execute(
                """INSERT INTO tenerife_waitlist(name,contact,language,page,consent,client_hash,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (name, waitlist_contact, language, JOIN_PATH, 1, client, now.isoformat()),
            )
            legacy = ("tenerife_waitlist", cursor.lastrowid, now.isoformat())

            capture_data = _build_capture_payload(
                submission_id, name, fb_contact, interest, language, email, src, ref, now
            )
            store.capture(conn, capture_data, now=now, legacy=legacy, client_hash=client)
            conn.commit()
        except sqlite3.Error:
            if conn:
                conn.rollback()
            return fail(labels["err_server"], 503)
        except ValueError:
            if conn:
                conn.rollback()
            return fail(labels["err_server"], 409)
        finally:
            if conn:
                conn.close()

        notify_lead(
            "Tenerife FB waitlist",
            name,
            waitlist_contact,
            language,
            JOIN_PATH + (f"?src={src}" if src else ""),
        )
        q = {"lang": ui}
        if src:
            q["src"] = src
        return redirect(THANKS_PATH + "?" + urlencode(q), code=303)

    @bp.route(THANKS_PATH)
    def fb_join_thanks():
        ui = _ui_lang()
        labels = copy.COPY[ui]
        group_url, placeholder = _group_url()
        body = render_template(
            "tenerife/join_thanks.html",
            ui_lang=ui,
            labels=labels,
            group_url=group_url,
            group_placeholder=placeholder,
        )
        return _headers(make_response(body))
