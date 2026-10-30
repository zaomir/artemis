# site-artemis mirror

Public-safe mirror of `zaomir/artemis` for grainee-v2 tracking.

| Role | Path |
|------|------|
| Deployable production source | `/var/www/artemis` (`https://github.com/zaomir/artemis`) |
| Tracked mirror (this tree) | `/var/www/grainee-v2/site-artemis/` |

Do not deploy from this mirror alone without syncing `/var/www/artemis`.
Excluded: venv, leads.db, secrets, private_quarantine (benchmark hotel imagery), legacy templates.

Compliance: `bash scripts/artemis-compliance-scan.sh` from this directory (script expects `app/` sibling).
