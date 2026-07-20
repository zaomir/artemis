# Artemis Resort & Spa — public project-information site

**Live (after Final deploy):** https://artemisresort.com  
**Source:** this repository (`zaomir/artemis`)  
**Mirror in grainee-v2:** `site-artemis/` (public-safe source only)

## Stack

- Flask (`app/app.py`) on `127.0.0.1:8082`
- Templates: `app/templates/`
- i18n: `app/translations/{en,ru,es,fr}.json`
- Static: `app/static/` (nginx alias)
- Counsel draft disclaimer: `app/legal/DISCLAIMER_EN.txt`

## Public architecture

Hero → At a glance → Location → Concept → Accommodation → Status → Governance → Professional enquiry → Legal footer

Legal pages: `/<lang>/privacy/`, `/terms/`, `/disclaimer/`, `/fraud-warning/`

## Compliance

```bash
bash scripts/artemis-compliance-scan.sh
# or: python3 scripts/compliance_scan.py
```

## Deploy (Final only — Lane B does not deploy)

```bash
git push origin main
curl -sS -X POST https://artemisresort.com/deploy-hook \
  -H "X-Hook-Secret: <secret>" --max-time 60
```

Also apply `deploy/nginx-410-snippet.conf` before `/static/` alias, then `nginx -t` && reload.

## Admin

`/admin/leads?t=<ARTEMIS_ADMIN_TOKEN>` — professional enquiries (no planned amount).
