"""Standalone Facebook waitlist: GET/POST /tenerife/join/ and thank-you page."""
from __future__ import annotations

import datetime
import os
import re
import sqlite3
import uuid
from urllib.parse import urlencode

from flask import make_response, redirect, render_template, request

import funnel_store as store
import funnel_http
import tenerife_join_copy as copy
import tenerife_join_crm as join_crm

from notify import notify_lead

JOIN_PATH = "/tenerife/join/"
THANKS_PATH = "/tenerife/join/gracias/"
INTERESTS = frozenset({"buyer", "investor", "partner"})
SRC_RX = re.compile(r"[A-Za-z0-9_.:-]{1,100}")
REF_RX = re.compile(r"[A-Za-z0-9_.:-]{1,100}")
NAME_MAX = 120
FB_MAX = 300
EMAIL_MAX = 254

FIELD_KEYS = ("name", "facebook", "interest", "language", "email", "consent")


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
    resp.headers.update({"Cache-Control": "no-store, max-age=0", "X-Robots-Tag": "noindex, nofollow"})
    return resp


def _group_url_configured() -> tuple[str | None, bool]:
    raw = os.environ.get("ARTEMIS_FB_PRIVATE_GROUP_URL", "").strip()
    if raw.startswith("https://"):
        return raw, True
    return None, False


def _consent_ok(value) -> bool:
    return str(value or "").lower() in {"1", "true", "on", "yes"}


def resolve_facebook_contact(raw: str) -> str:
    """Handle, HTTPS profile URL, or display name (Unicode / spaces)."""
    value = " ".join(str(raw or "").split())
    if not value or len(value) > FB_MAX:
        raise ValueError("facebook")
    try:
        return store.contact_value("facebook", value)
    except ValueError:
        pass
    if any(ord(c) < 32 for c in value):
        raise ValueError("facebook")
    if not any(c.isalpha() for c in value):
        raise ValueError("facebook")
    if not re.fullmatch(r"[\w .'\-]+", value, flags=re.UNICODE):
        raise ValueError("facebook")
    return value


def _validate_form(values: dict, labels: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    name = " ".join(str(values.get("name") or "").split())[:NAME_MAX]
    if len(str(values.get("name") or "")) > NAME_MAX:
        errors["name"] = labels["err_name"]
    elif not name:
        errors["name"] = labels["err_name"]

    raw_fb = str(values.get("facebook") or "").strip()
    if len(raw_fb) > FB_MAX:
        errors["facebook"] = labels["err_facebook"]
    else:
        try:
            resolve_facebook_contact(raw_fb)
        except ValueError:
            errors["facebook"] = labels["err_facebook"]

    interest = str(values.get("interest") or "").strip()
    if interest not in INTERESTS:
        errors["interest"] = labels["err_interest"]

    language = str(values.get("language") or "").strip().lower()
    if language not in store.LANGUAGES:
        errors["language"] = labels["err_language"]

    if not values.get("consent"):
        errors["consent"] = labels["err_consent"]

    email = str(values.get("email") or "").strip()[:EMAIL_MAX]
    if len(str(values.get("email") or "").strip()) > EMAIL_MAX:
        errors["email"] = labels["err_email"]
    elif email and not store.EMAIL.fullmatch(email):
        errors["email"] = labels["err_email"]

    return errors


def _render_form(ui, labels, submission_id, src, ref, values, field_errors, status=200, preselect_language=""):
    body = render_template(
        "tenerife/join_form.html",
        ui_lang=ui,
        labels=labels,
        lang_options=[(c, copy.LANG_LABELS[c]) for c in copy.JOIN_LANGS],
        submission_id=submission_id,
        fb_src=src,
        fb_ref=ref,
        values=values,
        field_errors=field_errors,
        preselect_language=preselect_language or (ui if ui in copy.JOIN_LANGS else ""),
    )
    return _headers(make_response(body, status))


def register(bp, db_path, client_hash, honeypot_field, rate_max, rate_window_min, init_waitlist_db):
    @bp.route(JOIN_PATH, methods=["GET", "POST"])
    def fb_join():
        ui = _ui_lang()
        labels = copy.COPY[ui]
        src, ref = _capture_attribution()
        default_language = ui if ui in copy.JOIN_LANGS else ""

        if request.method == "GET":
            values = {"language": default_language} if default_language else {}
            return _render_form(ui, labels, str(uuid.uuid4()), src, ref, values, {}, 200, default_language)

        if str(request.form.get(honeypot_field) or "").strip():
            return redirect(THANKS_PATH + "?" + urlencode({"lang": ui}), code=303)

        values = {k: request.form.get(k, "") for k in FIELD_KEYS if k != "consent"}
        values["consent"] = _consent_ok(request.form.get("consent"))
        submission_id = str(request.form.get("submission_id") or "")
        src, ref = _capture_attribution()

        if not store.ID.fullmatch(submission_id):
            return _render_form(ui, labels, str(uuid.uuid4()), src, ref, values, {"form": labels["err_server"]}, 400)

        field_errors = _validate_form(values, labels)
        if field_errors:
            return _render_form(ui, labels, submission_id, src, ref, values, field_errors, 400)

        name = " ".join(str(values["name"] or "").split())[:NAME_MAX]
        fb_contact = resolve_facebook_contact(values["facebook"])
        interest = str(values["interest"]).strip()
        language = str(values["language"]).strip().lower()
        email = str(values.get("email") or "").strip()[:EMAIL_MAX]

        now = datetime.datetime.now(datetime.timezone.utc)
        since = (now - datetime.timedelta(minutes=rate_window_min)).isoformat()
        client = client_hash()
        funnel_on = funnel_http.enabled()
        conn = None
        waitlist_contact = fb_contact
        if email:
            waitlist_contact = f"{fb_contact} | {email.casefold()}"

        try:
            conn = sqlite3.connect(db_path(), timeout=5)
            init_waitlist_db(conn)
            if funnel_on:
                store.migrate(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")

            event = None
            digest = None
            if funnel_on:
                event = join_crm.build_join_event(submission_id, name, fb_contact, interest, language, src, ref, now)
                digest = join_crm.event_digest(event)
                row = conn.execute(
                    "SELECT payload_hash FROM artemis_events WHERE submission_id=?", (submission_id,)
                ).fetchone()
                if row:
                    if row[0] == digest:
                        conn.rollback()
                        conn.close()
                        return redirect(THANKS_PATH + "?" + urlencode({"lang": ui}), code=303)
                    conn.rollback()
                    return _render_form(
                        ui,
                        labels,
                        submission_id,
                        src,
                        ref,
                        values,
                        {"form": labels["err_conflict"]},
                        409,
                    )

            recent_waitlist = conn.execute(
                "SELECT COUNT(*) FROM tenerife_waitlist WHERE client_hash=? AND created_at>=?",
                (client, since),
            ).fetchone()[0]
            recent_events = 0
            if funnel_on:
                recent_events = conn.execute(
                    "SELECT COUNT(*) FROM artemis_events WHERE client_hash=? AND created_at>=?",
                    (client, since),
                ).fetchone()[0]
            if max(recent_waitlist, recent_events) >= rate_max:
                conn.rollback()
                return _render_form(ui, labels, submission_id, src, ref, values, {"form": labels["err_rate"]}, 429)

            cursor = conn.execute(
                """INSERT INTO tenerife_waitlist(name,contact,language,page,consent,client_hash,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (name, waitlist_contact, language, JOIN_PATH, 1, client, now.isoformat()),
            )
            legacy = ("tenerife_waitlist", cursor.lastrowid, now.isoformat())

            if funnel_on:
                join_crm.capture_join(conn, event, legacy, client)
            elif os.environ.get("ARTEMIS_CRM_CAPTURE_ENABLED") == "1":
                from funnel_legacy import enqueue_row

                enqueue_row(conn, "tenerife_waitlist", cursor.lastrowid)

            conn.commit()
        except sqlite3.Error:
            if conn:
                conn.rollback()
            return _render_form(ui, labels, submission_id, src, ref, values, {"form": labels["err_server"]}, 503)
        except ValueError as exc:
            if conn:
                conn.rollback()
            if str(exc) == "submission_id_conflict":
                return _render_form(
                    ui, labels, submission_id, src, ref, values, {"form": labels["err_conflict"]}, 409
                )
            return _render_form(ui, labels, submission_id, src, ref, values, {"form": labels["err_server"]}, 503)
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
        return redirect(THANKS_PATH + "?" + urlencode({"lang": ui}), code=303)

    @bp.route(THANKS_PATH)
    def fb_join_thanks():
        ui = _ui_lang()
        labels = copy.COPY[ui]
        group_url, show_group = _group_url_configured()
        body = render_template(
            "tenerife/join_thanks.html",
            ui_lang=ui,
            labels=labels,
            group_url=group_url,
            show_group_button=show_group,
        )
        return _headers(make_response(body))
