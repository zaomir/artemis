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

```bash
git push origin main
curl -sS -X POST https://artemisresort.com/deploy-hook \
  -H "X-Hook-Secret: <secret>" --max-time 60
```

## Admin

`/admin/leads?t=<ARTEMIS_ADMIN_TOKEN>` — enquiries including planned amount.
