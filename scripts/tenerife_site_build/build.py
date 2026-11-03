#!/usr/bin/env python3
"""Build Artemis Tenerife RU prod pages (/tenerife/) from the author's static
source (grainee-v2 docs/projects/artemis/tenerife/site-ru/) into zaomir/artemis.

usage: python3 scripts/tenerife_site_build/build.py SRC_DIR . [--allow-missing]
  SRC_DIR = checkout of grainee-v2 docs/projects/artemis/tenerife/site-ru
"""
import hashlib, json, os, re, shutil, sys, urllib.request
from pathlib import Path

PAGES = ["index", "norte", "producto", "construccion", "proceso", "faq"]
SRC, REPO = Path(sys.argv[1]), Path(sys.argv[2])
ALLOW_MISSING = "--allow-missing" in sys.argv
OUT_PAGES = REPO / "app/tenerife_site" / "ru"   # RU живёт под /tenerife/ru/ (EN — корень каталога)
OUT_STATIC = REPO / "app/static/tenerife/site"
FONTS = Path(__file__).resolve().parent  # fonts.css lives here; woff2 files are already in app/static/tenerife/site/fonts
URL = lambda p: "/tenerife/" if p == "index" else f"/tenerife/{p}/"
# SEO (task 4, 31.10): meta description + Open Graph per page. Pages without an entry get a flag.
OG_IMG = "https://artemisresort.com/static/tenerife/site/img/og-tenerife-1200x630.jpg"
DESC = {'index': '20 резиденций на севере Тенерифе, район La Quinta / Santa Úrsula: состав комплекса, архитектура, сроки и бесплатная запись в очередь.', 'norte': 'Север Тенерифе: La Quinta / Santa Úrsula рядом с Puerto de la Cruz — характер района и предложения соседних новостроек на октябрь 2026.'}

def meta_block(p, title):
    d = DESC.get(p)
    if not d:
        report["flags"].append(f"{p}: нет meta description в DESC (build.py)")
        return ""
    u = "https://artemisresort.com" + URL(p)
    return (f'<meta name="description" content="{d}">\n<meta property="og:type" content="website">\n'
            f'<meta property="og:site_name" content="Artemis Tenerife">\n<meta property="og:locale" content="ru_RU">\n'
            f'<meta property="og:title" content="{title}">\n<meta property="og:description" content="{d}">\n'
            f'<meta property="og:url" content="{u}">\n<meta property="og:image" content="{OG_IMG}">\n'
            f'<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n')
report = {"fixes": [], "images": [], "missing": [], "flags": []}

present = [p for p in PAGES if (SRC / f"{p}.html").exists()]
report["missing"] = [p for p in PAGES if p not in present]

# --- text fixes: internal notes / editorial instructions leaking to the public page
FIXES = [
    # founder 31.10 01:44 UTC: no disclaimers, no «Визуализация»/AI captions (same cleaning as the author's index.html @eb77aa1)
    (r"Визуализация, не фото построенного\. ", "", "убрано «Визуализация, не фото построенного.» из подписей (решение 01:44, как в очищенном index)"),
    (r'\s*<p class="note">[^<]*</p>', "", "убран note-блок с дисклеймерами (решение 01:44, как в очищенном index)"),
    (r"\s*Без выдуманных биографий\. Фото Simon — из папок проекта, когда будут доступны\. Лица не генерируем\.", "",
     "убрана внутренняя пометка «Без выдуманных биографий… Лица не генерируем»"),
    (r"<p>\s*</p>", "", None),
    (r" Не пишем адрес, высоту и минуты до аэропорта как факт\.", "",
     "убрана внутренняя пометка «Не пишем адрес, высоту и минуты до аэропорта как факт»"),
    (r" Мы не пишем, сколько минут до аэропорта, и не называем высоту\.", "",
     "убрана внутренняя пометка «Мы не пишем, сколько минут до аэропорта…»"),
    (r" Писать «скидка раннего входа» нельзя: 2 900–3 200 €/м² на старте — уровень соседних офферов, не дисконт\.", "",
     "убрана редакторская инструкция «Писать «скидка раннего входа» нельзя: 2 900–3 200 €/м² на старте…»"),
    (r" Цифр загрузки и комиссии оператора в наших файлах нет\.", "",
     "убрана внутренняя фраза «…в наших файлах нет»"),
    (r"\s*<p>Отдельной аналитики аренды с доходностью на сайте нет\.</p>", "",
     "убрана мета-фраза «Отдельной аналитики аренды с доходностью на сайте нет»"),
    (r"ориентиры брифа и чужих офферов", "предварительные ориентиры и данные чужих предложений",
     "«ориентиры брифа и чужих офферов» → «предварительные ориентиры и данные чужих предложений»"),
    (r"вилка брифа", "предварительная вилка", "«вилка брифа» → «предварительная вилка»"),
    # founder 31.10 (task «оговорки»): no «Участок не зафиксирован» / «не наш прайс» / «не выбираем одну цифру» on live pages
    (r"\s*<figcaption>Участок не зафиксирован\.</figcaption>", "", "убраны подписи «Участок не зафиксирован.»"),
    (r"<figcaption>([^<.]+)\. Участок не зафиксирован\.</figcaption>", r"<figcaption>\1</figcaption>", "из подписей убрано «Участок не зафиксирован.»"),
    (r"Участок ещё не зафиксирован\. Разрешения на строительство нет\. Поэтому сейчас — только", "Сейчас —", "убрано «Участок ещё не зафиксирован…»"),
    (r" Класс энергии появится, когда его посчитает проектировщик\. Сейчас это концепция, не сданный объём\.", "", "убрана оговорка про класс энергии"),
    (r" Это состав, не прайс-лист\. Цен по юнитам нет, пока нет участка и проекта\. Площади — предварительная вилка, не обмер после проекта\.", "", "убрана оговорка «не прайс-лист»"),
    (r" Точную точку не называем\.", "", "убрано «Точную точку не называем»"),
    (r" Это не обязательство и не дата в договоре\.", "", "убрано «Это не обязательство…»"),
    (r"<h2>Чужие офферы как ориентир</h2>", "<h2>Соседние новостройки</h2>", "«Чужие офферы как ориентир» → «Соседние новостройки»"),
    (r"<p>Рынок рядом, как тексты чужих офферов на октябрь 2026, не наш прайс:</p>", "<p>Предложения рядом, октябрь 2026:</p>", "убрано «не наш прайс»"),
    (r"Средняя по Santa Úrsula в разных сводках не сходится:", "Средняя цена по Santa Úrsula:", None),
    (r" На сайте не выбираем одну цифру как «рынок»\.", "", "убрано «На сайте не выбираем одну цифру»"),
]

def links(html):
    def rep(m):
        page, frag = m.group(2), m.group(3) or ""
        if page not in PAGES:
            report["flags"].append(f"ссылка на неизвестную страницу {page}.html")
            return m.group(0)
        return f'{m.group(1)}"{URL(page)}{frag}"'
    return re.sub(r'(href=)"(?:\./)?([a-z_-]+)\.html(#[^"]*)?"', rep, html)

def img_local(url_or_rel):
    if url_or_rel.startswith("https://cdn.leonardo.ai/"):
        base = url_or_rel.rsplit("/", 1)[1]
        m = re.search(r"photorealistic_(.+?)_\d+\.jpg$", base)
        slug = (m.group(1) if m else base).replace("_", "-").lower() + "-" + hashlib.sha1(url_or_rel.encode()).hexdigest()[:6] + ".jpg"
        dst = OUT_STATIC / "img" / slug
        if not dst.exists():
            try:
                req = urllib.request.Request(url_or_rel, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    code, data = r.status, r.read()
                if not data[:3] == b"\xff\xd8\xff":
                    raise ValueError("not a jpeg")
                dst.write_bytes(data)
                report["images"].append({"src": url_or_rel, "local": slug, "code": code, "bytes": len(data)})
            except Exception as e:  # noqa
                code = getattr(e, "code", str(e))
                report["images"].append({"src": url_or_rel, "local": None, "code": code})
                return None
        return f"/static/tenerife/site/img/{slug}"
    if re.match(r"^(https?:)?//", url_or_rel):
        report["flags"].append(f"внешняя картинка не Leonardo: {url_or_rel}")
        return None
    srcf = (SRC / url_or_rel).resolve()
    if not srcf.exists():
        report["flags"].append(f"нет файла картинки {url_or_rel}")
        return None
    rel = srcf.relative_to(SRC.resolve()).as_posix()
    dst = OUT_STATIC / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(srcf, dst)
    report["images"].append({"src": url_or_rel, "local": rel, "code": "repo"})
    return f"/static/tenerife/site/{rel}"

def images(html):
    def rep(m):
        new = img_local(m.group(2))
        if new is None:
            return m.group(0)
        return f'{m.group(1)}"{new}"'
    html = re.sub(r'(<img[^>]*?\ssrc=)"([^"]+)"', rep, html)
    return html

sys.path.insert(0, str(Path(__file__).resolve().parent))
from responsive import responsive  # noqa: E402
from email_off import EmailOffError, unprotected, wrap as email_off  # noqa: E402  (Cloudflare Email Obfuscation, see email_off.py)

FOOTER = Path(__file__).with_name("_footer.html").read_text(encoding="utf-8")
FORM = Path(__file__).with_name("_waitlist.html").read_text(encoding="utf-8")

OUT_PAGES.mkdir(parents=True, exist_ok=True); (OUT_STATIC / "img").mkdir(parents=True, exist_ok=True)
(OUT_STATIC / "fonts").mkdir(exist_ok=True)
for w in FONTS.glob("*.woff2"):  # optional: drop new woff2 next to this script
    shutil.copy2(w, OUT_STATIC / "fonts" / w.name)

css = (SRC / "style.css").read_text(encoding="utf-8")
extra = Path(__file__).with_name("extra.css").read_text(encoding="utf-8")
(OUT_STATIC / "style.css").write_text((FONTS / "fonts.css").read_text() + "\n" + css + "\n" + extra, encoding="utf-8")

for p in present:
    h = (SRC / f"{p}.html").read_text(encoding="utf-8")
    if re.search(r"\{\{|\{%", h):
        report["flags"].append(f"{p}: jinja-like syntax")
    for rx, sub, desc in FIXES:
        h2 = re.sub(rx, sub, h)
        if h2 != h and desc:
            report["fixes"].append(f"{p}.html: {desc}")
        h = h2
    # fonts: self-hosted, no Google requests
    if "fonts.googleapis" in h:
        report["fixes"].append(f"{p}.html: Google Fonts → свои шрифты (без запросов к Google)")
    h = re.sub(r'\s*<link[^>]*fonts\.(googleapis|gstatic)\.com[^>]*>', "", h)
    h = re.sub(r'<link rel="stylesheet" href="(?:\./)?style\.css">', '<link rel="stylesheet" href="/static/tenerife/site/style.css">', h)
    _title = (re.search(r"<title>(.*?)</title>", h, re.S) or [None, ""])[1]
    h = h.replace("</title>", '</title>\n<link rel="canonical" href="https://artemisresort.com' + URL(p) + '">\n' + meta_block(p, _title) + '<link rel="icon" href="/static/favicon-32x32.png">', 1)
    h = links(h)
    h = images(h)
    h = responsive(h, OUT_STATIC)  # webp srcset, width/height, lazy, hero preload
    # existing external forms → our handler
    if re.search(r"<form", h):
        if re.search(r'action="(mailto:|https?://)', h):
            report["fixes"].append(f"{p}.html: внешний action формы → наш обработчик")
        h = re.sub(r"<form.*?</form>", "{{WAITLIST_FORM}}", h, flags=re.S)
        report["fixes"].append(f"{p}.html: форма заменена на нашу (waitlist /api/tenerife/waitlist)")
    FORM_HOST = "proceso" if "proceso" in present else "index"
    if p == FORM_HOST and "{{WAITLIST_FORM}}" not in h:
        h = h.replace("</main>", "{{WAITLIST_FORM}}\n</main>", 1)
        report["fixes"].append(f"{p}.html: добавлена форма листа ожидания")
    h = h.replace("{{WAITLIST_FORM}}", FORM.replace("__PAGE__", URL(p)))
    # waitlist CTAs point to the form anchor
    form_url = URL(FORM_HOST) + "#waitlist"
    h = h.replace('href="/tenerife/proceso/"', f'href="{form_url}"') if "proceso" in present else re.sub(
        r'(<a class="cta" href=)"/tenerife/proceso/"', rf'\1"{form_url}"', h)
    # pages not shipped yet: drop their nav items (no broken links)
    for miss in report["missing"]:
        h2 = re.sub(r'\n\s*<a href="%s">[^<]*</a>' % re.escape(URL(miss)), "", h)
        if h2 != h:
            report["fixes"].append(f"{p}.html: пункт меню на ещё не готовую страницу {miss} убран (вернётся при пересборке)")
        h = h2
    if re.search(r"<footer>.*?</footer>", h, flags=re.S):
        old = re.search(r"<footer>.*?</footer>", h, flags=re.S).group(0)
        if "не для деплоя" in old:
            report["fixes"].append(f"{p}.html: футер «… не для деплоя» заменён на футер со ссылками на Impressum и privacy и реквизитами оператора")
        h = h.replace(old, FOOTER, 1)
    else:
        h = h.replace("</body>", FOOTER + "\n</body>", 1)
    # last step, nothing may rewrite the page after it: e-mails stay readable without JS behind Cloudflare
    try:
        h2 = email_off(h)
    except EmailOffError as e:  # a marker would land inside a tag/attribute: never write such a page
        sys.exit(f"FAIL {p}.html: {e}")
    if h2 != h:
        report["fixes"].append(f"{p}.html: e-mail / mailto обёрнуты в <!--email_off--> (Cloudflare Email Obfuscation)")
    h = h2
    leaks = unprotected(h)  # computed once, reused
    if leaks:  # Cloudflare would obfuscate these (404 without JS): fail the build, do not just flag
        sys.exit(f"FAIL {p}.html: e-mail / mailto вне <!--email_off-->: {leaks}")
    (OUT_PAGES / f"{p}.html").write_text(h, encoding="utf-8")

# links to pages not present must not ship
for p in present:
    h = (OUT_PAGES / f"{p}.html").read_text(encoding="utf-8")
    for m in re.findall(r'href="(/tenerife/[a-z]*/?)', h):
        tgt = m.strip("/").split("/")[-1] or "index"
        tgt = "index" if tgt == "tenerife" else tgt
        if tgt not in present and tgt not in ("index", "impressum", "privacy"):  # legal pages: app/tenerife.py
            report["flags"].append(f"BROKEN {p} -> {m}")
print(json.dumps(report, ensure_ascii=False, indent=1))
if report["missing"] and not ALLOW_MISSING:
    sys.exit(3)
