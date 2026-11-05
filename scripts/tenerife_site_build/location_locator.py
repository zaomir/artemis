"""Mobile coordinate locator, using the same sourced points as the desktop SVG.

No raster tiles, parcels, roads or project location are inferred. Regenerate with
python3 scripts/tenerife_site_build/location_locator.py. Evidence: docs/visual/
evidence/F23_LA_QUINTA_LOCATION_SOURCES_2026-11-05.md.
"""
from pathlib import Path

POINTS = {
    "la_quinta": (28.43187, -16.49517),
    "puerto": (28.41552846, -16.55000025),
    "titsa": (28.4271, -16.493),
}


def project(lat, lon):
    return 120 + (lon + 16.566) / .083 * 440, 130 + (28.443 - lat) / .039 * 380


def mobile_svg():
    parts = ['''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="660" viewBox="0 0 640 660" role="img" aria-labelledby="title desc">
<title id="title">La Quinta · Santa Úrsula</title>
<desc id="desc">Coordinate locator: La Quinta neighbourhood, Puerto de la Cruz municipality and TITSA stop 4004. No selected parcel, roads or route. Sources: OpenStreetMap, AEMET, TITSA.</desc>
<style>text{font-family:Georgia,serif;fill:#4a3525}.grid{stroke:#9ba6a5;stroke-dasharray:3 8;opacity:.5}.tick{font-size:24px;fill:#7a5c43}.place{font-size:28px}.leader{fill:none;stroke:#7a5c43;stroke-width:2}</style>
<rect width="640" height="660" fill="#f5efe0"/>
<text x="40" y="58" font-size="36">La Quinta · Santa Úrsula</text>
<text x="40" y="97" font-size="26">Tenerife</text>''']
    for lat in (28.41, 28.42, 28.43, 28.44):
        _, y = project(lat, -16.566)
        parts.append(f'<path d="M120 {y:.2f} H560" class="grid"/><text x="14" y="{y+8:.2f}" class="tick">{lat:.2f}°N</text>')
    for lon in (-16.56, -16.53, -16.50):
        x, _ = project(28.443, lon)
        parts.append(f'<path d="M{x:.2f} 130 V510" class="grid"/><text x="{x:.2f}" y="550" text-anchor="middle" class="tick">{-lon:.2f}°W</text>')
    for key, (lat, lon) in POINTS.items():
        x, y = project(lat, lon)
        colour = {"la_quinta": "#444743", "puerto": "#819da8", "titsa": "#967b5a"}[key]
        parts.append(f'<circle id="{key}" cx="{x:.2f}" cy="{y:.2f}" r="10" fill="{colour}" stroke="#f5efe0" stroke-width="3"/>')
    qx, qy = project(*POINTS["la_quinta"])
    px, py = project(*POINTS["puerto"])
    tx, ty = project(*POINTS["titsa"])
    parts += [f'<path d="M{qx-10:.2f} {qy-8:.2f} L440 195 H315" class="leader"/>',
              '<text x="315" y="177" class="place" font-weight="bold">La Quinta</text>',
              f'<path d="M{px+7:.2f} {py+8:.2f} L230 435" class="leader"/>',
              '<text x="168" y="479" class="place">Puerto de la Cruz</text>',
              f'<path d="M{tx+10:.2f} {ty+3:.2f} L550 323 H405" class="leader"/>',
              '<text x="405" y="364" class="place">TITSA 4004</text>',
              '<path d="M592 162 V122 L584 138 M592 122 L600 138" class="leader"/><text x="592" y="110" text-anchor="middle" font-size="26">N</text>',
              '<path d="M40 584 H600" stroke="#7a5c43" opacity=".4"/>',
              '<text x="40" y="618" class="tick">© OpenStreetMap contributors</text>',
              '<text x="40" y="650" class="tick">AEMET · TITSA</text></svg>']
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[2] / "app/static/tenerife/site/img/la-quinta-context-locator-mobile-20261105.svg"
    target.write_text(mobile_svg(), encoding="utf-8")
