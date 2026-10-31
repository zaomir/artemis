# Legal text translations (drop-in)

A-06 (QA fa39ad0): reviewed translations of the privacy / terms text ship here as
`privacy.<lang>.md` / `terms.<lang>.md` (ru, es, fr; copy-writer files `artemis-<page>-<lang>.md`,
31.10.2026). A language/page without a file falls back to the English original (marked `lang="en"`)
under a localized note (`legal_body_pending`), so the page keeps working. Do not edit the legal
wording here without the reviewer; addresses in these texts are wrapped in `<!--email_off-->` on render (A-13).

How to publish a translation:

1. Take the English source with markers (`artemis-privacy-en.md` from the web-dev hand-off;
   same format as below) and translate the text under each marker. Keep the markers.
2. Save as `app/legal_translations/privacy.<lang>.md` (`ru`, `es`, `fr`); terms → `terms.<lang>.md`.
3. Run `python -m pytest -q tests/test_crete_qa.py tests/test_crete_privacy.py tests/test_crete_email_off.py` and deploy as usual.

Format (`app/legal_i18n.py`):

```
<!-- @title -->
Политика конфиденциальности          (optional; else t.privacy_title)
<!-- @body -->
Paragraph one…

Paragraph two…                        (blank line = new paragraph; plain text, escaped)
<!-- @recipients -->
Получатель и обработчик копий заявок — …   (optional; else t.privacy_recipients;
                                            keep the prefix checked by tests/test_crete_privacy.py)
```

`<page>.en.md` is ignored: English always comes from `app/translations/en.json`.
