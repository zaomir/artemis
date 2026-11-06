# English copy (draft)

Translation of `copy_v3` (Russian master), produced 2026-11-02. Structure, figures, `[КАДР Fxx]` markers,
links and META keys are identical to the master; only prose is translated.

Not wired into the build yet: `build_v3.py` recognises components by Russian section titles and footer labels
(`Страницы.` / `Контакты.` / `Компания.` / `Документы.`), and `NAV` is keyed by the Russian names. A locale
layer (per-locale NAV, footer labels, COMPANY_RX, section-title map, ladder headers) is required before
`TENERIFE_LOCALE=en` can render. Legal pages 15–17 are not translated yet.
