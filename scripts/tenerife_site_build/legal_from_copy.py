"""copy_v3 15_impressum.md / 16_privacy.md -> {% block body %} of app/templates/tenerife/{impressum,privacy}.html
(QA T3-09, Kimi 31.10.2026). Text word for word; markup only: h1/h2/p/ul, **b**, [link](url) (rel nofollow noopener),
mailto + email_off around info@artemisresort.com, the old classes (intro line .muted, source line .muted src).
usage: legal_from_copy.py [--check]   (--check: exit 1 if a template differs from what the copy gives)"""
import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TPL = ROOT / "app" / "templates" / "tenerife"
FILES = {"impressum": "15_impressum.md", "privacy": "16_privacy.md"}
TITLES = {"impressum": "Правовая информация — Artemis de la Cruz", "privacy": "Конфиденциальность — Artemis de la Cruz"}
EMAIL = "info@artemisresort.com"
BACK = '  <p class="back"><a href="/tenerife/">← К сайту проекта</a></p>'


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\[([^\]]+)\]\((https://[^)\s]+)\)", r'<a href="\2" rel="nofollow noopener">\1</a>', t)
    return t.replace(EMAIL, f'<!--email_off--><a href="mailto:{EMAIL}">{EMAIL}</a><!--/email_off-->')


def body(md):
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    out, ul, first_p = [], False, True
    for line in md.splitlines():
        if ul and not line.startswith("- "):
            out.append("  </ul>")
            ul = False
        if not line.strip():
            continue
        if line.startswith("# "):
            out.append(f"  <h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"\n  <h2>{inline(line[3:])}</h2>")
        elif line.startswith("- "):
            if not ul:
                out.append("  <ul>")
                ul = True
            out.append(f"    <li>{inline(line[2:])}</li>")
        else:
            cls = ' class="muted"' if first_p else (' class="muted src"' if line.startswith("Источник:") else "")
            out.append(f"  <p{cls}>{inline(line)}</p>")
            first_p = False
    if ul:
        out.append("  </ul>")
    return "\n".join(out) + "\n\n" + BACK


def template(name):
    md = (HERE / "copy_v3" / FILES[name]).read_text(encoding="utf-8")
    return ('{% extends "tenerife/base.html" %}\n'
            f'{{% block title %}}{TITLES[name]}{{% if not canonical %}} (превью){{% endif %}}{{% endblock %}}\n'
            '{% block body %}\n<section class="legal"><div class="wrap">\n'
            + body(md) + "\n</div></section>\n{% endblock %}\n")


if __name__ == "__main__":
    bad = 0
    for n in FILES:
        p, want = TPL / f"{n}.html", template(n)
        if "--check" in sys.argv:
            bad += p.read_text(encoding="utf-8") != want
        else:
            p.write_text(want, encoding="utf-8")
    sys.exit(1 if bad else 0)
