# PLAN: Artemis favicon (v33)

**Дата:** 2026-05-27  
**Репо:** `zaomir/artemis` · **SHA:** `badeb01`

## Цель

Иконка Artemis во вкладке браузера на https://artemisresort.com/

## Изменения

| Файл | Действие |
|------|----------|
| `app/static/favicon.ico` | 32×32 PNG (браузерный fallback) |
| `app/static/favicon-32x32.png` | 32×32 |
| `app/static/favicon-192x192.png` | 192×192 |
| `app/static/apple-touch-icon.png` | 180×180 |
| `app/templates/index.html` | 4× `<link rel="icon|apple-touch-icon">` после charset |
| `DECISIONS.md` | v33, запись о favicon |

Flask: `url_for('static', …)` → `/static/…` (nginx alias).

## Smoke (prod)

- `GET /` → 200, 4 link-тега в HTML
- `GET /static/favicon.ico` → 200
- `GET /static/favicon-32x32.png` → 200
- `GET /static/favicon-192x192.png` → 200
- `GET /static/apple-touch-icon.png` → 200

## Deploy-hook fix

`webhook.py`: `git pull` через `sudo` + `safe.directory` (www-data не имел прав на git).

## MONYA REVIEW

N/A — автономный zavod-цикл.
