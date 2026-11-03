"""Build-time monotone cubic price chart. No browser library or financial-model mutation.

Hermite interpolation uses Steffen's shape-preserving tangent construction (1990),
also documented in d3-shape's curveMonotoneX implementation:
https://github.com/d3/d3-shape/blob/main/src/curve/monotone.js
"""
from decimal import Decimal, ROUND_HALF_UP
import math

Y_MIN, Y_MAX, GRID_STEP = 2900, 3900, 100

UI = {
    "ru": {"comparison": "Разница с ценой ввода", "title": "Цена акции по стадиям проекта", "axis": "Ось цены", "range": "от 2 900 до 3 900 евро за м²", "unit": "€/м²", "end": "Цена на вводе", "basis": "Ниже цены ввода", "key": "Стадии проекта"},
    "en": {"comparison": "Difference from handover price", "title": "Share price by project stage", "axis": "Price axis", "range": "2,900 to 3,900 euros per m²", "unit": "€/m²", "end": "Handover price", "basis": "Below handover price", "key": "Project stages"},
    "es": {"comparison": "Diferencia con el precio en la entrega", "title": "Precio de la acción por etapa", "axis": "Eje de precios", "range": "de 2.900 a 3.900 euros por m²", "unit": "€/m²", "end": "Precio en la entrega", "basis": "Menos que en la entrega", "key": "Etapas del proyecto"},
    "de": {"comparison": "Differenz zum Übergabepreis", "title": "Aktienpreis nach Projektstufe", "axis": "Preisachse", "range": "2.900 bis 3.900 Euro je m²", "unit": "€/m²", "end": "Preis bei Übergabe", "basis": "Unter dem Übergabepreis", "key": "Projektstufen"},
    "fr": {"comparison": "Écart avec le prix à la livraison", "title": "Prix de l’action par étape", "axis": "Axe des prix", "range": "de 2 900 à 3 900 euros par m²", "unit": "€/m²", "end": "Prix à la livraison", "basis": "Sous le prix à la livraison", "key": "Étapes du projet"},
}


def eur(value):
    return f"{int(value):,}".replace(",", "\u00a0") + "\u00a0€"


def reduction_percent(price, handover):
    return ((Decimal(str(handover)) - Decimal(str(price))) / Decimal(str(handover)) * 100).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP)


def percent(value, locale):
    text = format(value, ".1f")
    return (text if locale == "en" else text.replace(".", ",")) + "%"


def monotone_segments(points):
    """Cubic Bézier segments interpolating the input, preserving monotonicity between every pair."""
    if len(points) < 2:
        raise ValueError("A price curve needs at least two points")
    widths = [b[0] - a[0] for a, b in zip(points, points[1:])]
    if any(h <= 0 for h in widths):
        raise ValueError("Stage positions must increase")
    slopes = [(b[1] - a[1]) / h for a, b, h in zip(points, points[1:], widths)]
    inner = []
    for i in range(1, len(points) - 1):
        left, right = slopes[i - 1:i + 1]
        mean = (left * widths[i] + right * widths[i - 1]) / (widths[i - 1] + widths[i])
        sign_sum = (1 if left > 0 else -1 if left < 0 else 0) + (1 if right > 0 else -1 if right < 0 else 0)
        inner.append(sign_sum * min(abs(left), abs(right), abs(mean) / 2))
    tangents = ([(3 * slopes[0] - inner[0]) / 2] + inner + [(3 * slopes[-1] - inner[-1]) / 2]
                if inner else [slopes[0], slopes[0]])
    segments = []
    for i, (start, end) in enumerate(zip(points, points[1:])):
        third = widths[i] / 3
        segments.append((start, (start[0] + third, start[1] + third * tangents[i]),
                         (end[0] - third, end[1] - third * tangents[i + 1]), end))
    return segments


def _n(value):
    return format(value, ".3f").rstrip("0").rstrip(".")


def _name_lines(name):
    words = name.split()
    if len(words) < 2:
        return [name]
    if len(name) <= 12:
        return words
    middle = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return [" ".join(words[:middle]), " ".join(words[middle:])]


def build_curve(steps, labels, locale, *, with_table=True, key="ladder"):
    if len(steps) != 6 or len(labels) != 6:
        raise ValueError("The project has exactly six price stages")
    prices = [step["price_eur_m2"] for step in steps]
    if any(not math.isfinite(p) or p < Y_MIN or p > Y_MAX for p in prices):
        raise ValueError("A stage price lies outside the explicitly fixed 2900–3900 axis")
    if any(b < a for a, b in zip(prices, prices[1:])):
        raise ValueError("Project stage prices must not decrease")
    handover = prices[-1]
    items = [{"id": step["id"], "name": label, "price": eur(price), "value": price,
              "reduction": percent(reduction_percent(price, handover), locale)}
             for step, label, price in zip(steps, labels, prices)]
    variants = []
    for compact, size, left, right, top, bottom in ((False, 760, 88, 722, 132, 610), (True, 360, 68, 336, 96, 272)):
        points = [(left + i * (right - left) / 5,
                   bottom - (price - Y_MIN) / (Y_MAX - Y_MIN) * (bottom - top)) for i, price in enumerate(prices)]
        segments = monotone_segments(points)
        line = "M " + " ".join(_n(v) for v in points[0])
        for segment in segments:
            line += " C " + " ".join(_n(v) for point in segment[1:] for v in point)
        area = line + f" L {_n(right)} {bottom} L {left} {bottom} Z"
        marks = [dict(item, x=_n(x), y=_n(y), number=i + 1, lines=_name_lines(item["name"]),
                      anchor="start" if i == 0 else "end" if i == 5 else "middle",
                      value_y=_n(y - 18)) for i, (item, (x, y)) in enumerate(zip(items, points))]
        ticks = [{"value": value, "label": eur(value),
                  "y": _n(bottom - (value - Y_MIN) / (Y_MAX - Y_MIN) * (bottom - top))}
                 for value in range(Y_MIN, Y_MAX + 1, GRID_STEP)]
        variants.append({"compact": compact, "size": size, "id": key + ("-compact" if compact else "-full"),
                         "left": left, "right": right, "top": top, "bottom": bottom,
                         "line": line, "area": area, "marks": marks, "ticks": ticks,
                         "x_label_y": 292 if compact else 640,
                         "min_value_y": 342 if compact else 742,
                         "max_value_y": 49 if compact else 72, "max_label_y": 76 if compact else 103})
    ui = UI[locale]
    return {"id": key, "variants": variants, "steps": items, "ui": ui, "with_table": with_table,
            "min": Y_MIN, "max": Y_MAX, "grid_step": GRID_STEP,
            "first": items[0], "last": items[-1],
            "difference": "−" + eur(handover - prices[0]) + " / −" + items[0]["reduction"],
            "description": "; ".join(item["name"] + ": " + item["price"] for item in items)
                           + ". " + ui["axis"] + ": " + ui["range"] + "."}
