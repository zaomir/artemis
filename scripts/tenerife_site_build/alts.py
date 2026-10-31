"""Alt texts of the RU v3 photos — review list for the editor (designer r2, item 4).

  python3 scripts/tenerife_site_build/alts.py export OUT.md   # table page | slot | file | alt (final, after the build)
  python3 scripts/tenerife_site_build/alts.py import IN.md    # apply an edited table to alts.json, then rebuild

Only the «alt» column is read back. A changed alt becomes a per-slot override in alts.json ('<page>/<Fxx>':
{file, alt}); an alt equal to the photo's default removes the override. No code change is needed; the build
fails if an override no longer matches the slot's photo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALTS = HERE / "alts.json"
sys.path.insert(0, str(HERE))
import build_v3  # noqa: E402

HEAD = "| Страница | URL | Слот | Файл | Alt |\n|---|---|---|---|---|\n"


def rows():
    _, report = build_v3.build(write=False)
    for _fname, name in build_v3.PAGES:
        r = report[name]
        for fid, stem in r["frames"].items():
            if stem:
                yield name, r["url"], fid, stem, r["alts"][fid]


def cell(t):
    return t.replace("|", "\\|")


def export(out):
    lines = [f"| {n} | {u} | {f} | {s}.jpg | {cell(a)} |" for n, u, f, s, a in rows()]
    Path(out).write_text(
        "# Artemis Tenerife RU v3 — alt-тексты фото (на ревью)\n\n"
        "Сгенерировано `scripts/tenerife_site_build/alts.py export` из `alts.json` после сборки: только слоты с фото "
        "(слоты без фото — текстовый блок с базальтовой полосой, без alt). Правьте только колонку «Alt»; "
        "применение: `alts.py import <этот файл>` и пересборка — без изменений кода.\n\n"
        f"Изображений всего: {len(lines)}.\n\n" + HEAD + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def parse(md):
    out = {}
    for line in Path(md).read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| Страница") or line.startswith("|---"):
            continue
        parts = [p.strip().replace("\\|", "|") for p in line.replace("\\|", "\x00").strip("|").split("|")]
        parts = [p.replace("\x00", "|") for p in parts]
        if len(parts) != 5:
            raise SystemExit(f"bad row: {line}")
        name, _url, fid, file, alt = parts
        out[(name, fid)] = (file.removesuffix(".jpg"), " ".join(alt.split()))
    return out


def import_md(md, alts_path=ALTS):
    alts = json.loads(Path(alts_path).read_text(encoding="utf-8"))
    current = {(n, f): (s, a) for n, _u, f, s, a in rows()}
    edited = parse(md)
    unknown = set(edited) - set(current)
    if unknown:
        raise SystemExit(f"rows not on the site: {sorted(unknown)}")
    changed = 0
    for key, (file, alt) in edited.items():
        if file != current[key][0]:
            raise SystemExit(f"{key}: file {file} != current photo {current[key][0]}")
        if not alt:
            raise SystemExit(f"{key}: empty alt")
        slot = f"{key[0]}/{key[1]}"
        if alt == alts["images"][file]:
            changed += alts["slots"].pop(slot, None) is not None
        elif alts["slots"].get(slot) != {"file": file, "alt": alt}:
            alts["slots"][slot] = {"file": file, "alt": alt}
            changed += 1
    Path(alts_path).write_text(json.dumps(alts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("export", "import"):
        raise SystemExit(__doc__)
    if sys.argv[1] == "export":
        print(f"{export(sys.argv[2])} alts -> {sys.argv[2]}")
    else:
        print(f"{import_md(sys.argv[2])} slot(s) changed in alts.json; rebuild: python3 {HERE / 'build_v3.py'}")
