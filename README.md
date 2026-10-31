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
ssh vps2402 sudo /usr/local/sbin/artemis-deploy.sh          # fetch + ff-only + restart + smoke, auto-rollback
ssh vps2402 sudo /usr/local/sbin/artemis-deploy.sh --check  # smoke only
```

Source of the script: `deploy/artemis-deploy.sh` (re-install after changing it:
`install -m 750 deploy/artemis-deploy.sh /usr/local/sbin/artemis-deploy.sh`).
Log: `/var/log/artemis-deploy.log`. Checkout: `/var/www/artemis` (branch `main`, never edit in place).

## Runtime config

`artemis.service` reads `EnvironmentFile=/etc/artemis/artemis.env` (root:root 600):

| Var | Purpose |
|---|---|
| `ARTEMIS_ADMIN_TOKEN` | `/admin/leads` token. Missing → admin always 403 (fail-closed) |
| `ARTEMIS_TG_BOT_TOKEN` | Telegram bot used for lead notifications |
| `ARTEMIS_TG_CHAT_ID` | Telegram group «Artemis». Missing → lead saved to DB + warning in journal only |

Notifications contain only: name, contact, language, page.

## Admin

`/admin/leads?t=<ARTEMIS_ADMIN_TOKEN>` — enquiries including planned amount.
