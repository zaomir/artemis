from flask import Flask, request, abort
import os
import subprocess

app = Flask(__name__)
SECRET = os.environ.get("HOOK_SECRET", "rovlex-artemis-2025")
ARTEMIS_DIR = "/var/www/artemis"

COMMANDS = [
    ["/usr/bin/sudo", "-n", "/usr/bin/git", "-C", ARTEMIS_DIR, "pull", "origin", "main"],
    ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "restart", "artemis"],
]


@app.route("/deploy-hook", methods=["POST"])
def hook():
    sig = request.headers.get("X-Hook-Secret", "")
    if sig != SECRET:
        abort(403)
    result = []
    for cmd in COMMANDS:
        r = subprocess.run(cmd, capture_output=True, text=True)
        result.append(" ".join(cmd) + "\n" + (r.stdout or "") + (r.stderr or ""))
        if r.returncode != 0:
            return "\n".join(result), 500
    return "\n".join(result), 200
