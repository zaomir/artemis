"""DISABLED (2026-10-31) — legacy deploy webhook, kept for history only.

Deploy is done on the server with deploy/artemis-deploy.sh
(installed as /usr/local/sbin/artemis-deploy.sh). The systemd unit
artemis-hook.service is disabled and nginx /deploy-hook has no backend.
Do not re-enable: there is no GitHub Actions / webhook deploy channel
(see grainee-v2 docs/ssot/NO_GITHUB_ACTIONS.md).

If ever started by mistake it is fail-closed: every request -> 410.
"""
from flask import Flask, abort

app = Flask(__name__)


@app.route("/deploy-hook", methods=["GET", "POST"])
def hook():
    abort(410)
