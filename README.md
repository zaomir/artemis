# Artemis Resort & Spa — project + investment site

**Live:** https://artemisresort.com  
**Source:** `zaomir/artemis` · **Mirror:** `site-artemis/` in grainee-v2  
**Canon:** `docs/audits/artemis/04_SAFE_PUBLIC_COPY.md` · DEC-ARTEMIS-INVESTMENT-RESTORE-2026-10-30

## Stack

- Flask (`app/app.py`) on `127.0.0.1:8082`
- Templates: `app/templates/`
- i18n: `app/translations/{en,ru,es,fr}.json`
- Static: `app/static/` (nginx alias)

## Public architecture

Hero → At a glance → Location → Concept → Investment → Accommodation → Status → Governance → Enquiry → Privacy/Terms

Disclaimer / fraud-warning pages **removed**. Investment content **allowed**.

## Compliance

```bash
bash scripts/artemis-compliance-scan.sh   # no-op PASS (hard-block disabled)
```

## Deploy

No GitHub Actions and no webhook (the old `/deploy-hook` / `artemis-hook.service`
is **disabled**, see `webhook.py`). Deploy = merge to `main`, then on the server:

```bash
ssh vps2402 sudo /usr/local/sbin/artemis-deploy.sh          # fetch + tests + ff-only + HUP reload + smoke, auto-rollback
ssh vps2402 sudo /usr/local/sbin/artemis-deploy.sh --check  # smoke only
```

Source of the script: `deploy/artemis-deploy.sh` (re-install after changing it:
`install -m 750 deploy/artemis-deploy.sh /usr/local/sbin/artemis-deploy.sh`).
Log: `/var/log/artemis-deploy.log`.
The script runs the unit tests (`python -m unittest discover -s tests`, app venv) on the new commit
in a temp dir **before** switching prod; a failure aborts the deploy and leaves prod untouched.

nginx (not deployed by the script; copy by hand, `nginx -t`, `systemctl reload nginx`, backup first):
`deploy/nginx-artemisresort.com.origin.conf` → `/etc/nginx/sites-enabled/artemisresort.com.origin.conf`,
`deploy/nginx-artemis-security-map.conf` → `/etc/nginx/conf.d/artemis-security-map.conf`,
`deploy/nginx-artemis-security-headers.conf` → `/etc/nginx/snippets/artemis-security-headers.conf`.

Lead relay (`deploy/artemis-lead-relay.py` → `/usr/local/sbin/artemis-lead-relay.py`, timer every minute):
`--status`, `--requeue [--channel email|telegram]`. The relay identifies a lead by `tbl:id:created_at`
(side tables `sent_key` / `attempt_key` in `/var/lib/artemis-lead-relay/state.db`), so deleting leads from
`leads.db` no longer needs a state clean-up: a new lead that gets a deleted lead's id (existing tables have
no AUTOINCREMENT; new databases do) is still e-mailed. Legacy `sent` rows without a key count only for a
lead created no later than the row's `at`. Checkout: `/var/www/artemis` (branch `main`, never edit in place).
Leads from `/tenerife/calculadora/` carry validated calculator fields (`calc_*` columns of `tenerife_waitlist`,
added by the app on first write; `app/tenerife_calc.py`); the app's Telegram message shows them (the relay does not).

## Runtime config

`artemis.service` reads `EnvironmentFile=/etc/artemis/artemis.env` (root:root 600):

| Var | Purpose |
|---|---|
| `ARTEMIS_ADMIN_TOKEN` | `/admin/leads` token. Missing → admin always 403 (fail-closed) |
| `ARTEMIS_TG_BOT_TOKEN` | Telegram bot used for lead notifications |
| `ARTEMIS_TG_CHAT_ID` | Telegram group «Artemis». Missing → lead saved to DB + warning in journal only. A lead whose name (Crete: or message) contains `TEST` is still sent, with «[TEST] » before the first line |
| `RATE_LIMIT_SALT` | Secret HMAC key for the per-client rate-limit hash (`/api/enquiry`, Tenerife waitlist; `app/ratelimit.py`); any long random string, e.g. `openssl rand -hex 32`. Unset or empty → `ARTEMIS_ADMIN_TOKEN` is used. **Neither set → the app refuses to start** (`refusing to start: rate limit: …` in the journal); there is no built-in default. Changing it only resets the rate-limit counters |
| `TENERIFE_WHATSAPP` | WhatsApp number of the `/tenerife/` footer, E.164 with `+` (e.g. `+440000000000`): «WhatsApp: » + `https://wa.me/<digits>`. Unset/invalid → contact hidden + one warning without the value. Never commit it. Details: `app/tenerife_site/README.md` |
| `TENERIFE_INDEXING` | `1` → `/tenerife/` indexable and in `sitemap.xml`. Unset → `noindex, nofollow` meta + `X-Robots-Tag` on every `/tenerife/` page (impressum/privacy included), none in the sitemap (until the founder approves numbers and prices). Crete unaffected |
| `TENERIFE_SHOW_FIGURES` | **Build time only** (`scripts/tenerife_site_build/build_v3.py`, not the app). Unset → the committed `/tenerife/` pages carry no prices, ladder, payments, dividend or yield figures and no calculator; `1` → rebuilt with them, as before r4.1. Details: `app/tenerife_site/README.md` |

Notifications contain only: name, contact, language, page — plus the planned investment amount
for Crete enquiries when the visitor filled it in (Telegram from `app/notify.py`, e-mail copy from
`deploy/artemis-lead-relay.py`). Never the message body; Tenerife waitlist has no amount.

## Admin

`/admin/leads?t=<ARTEMIS_ADMIN_TOKEN>` — enquiries including planned amount.
