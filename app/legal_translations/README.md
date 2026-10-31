# Legal text translations (drop-in)

TODO(A-06, QA fa39ad0): the main privacy / terms text on /ru/, /es/, /fr/ is still the English
original. Until a reviewed translation is dropped in here, those pages show the English body
(marked `lang="en"`) under a localized note (`legal_body_pending`), so they keep working.

How to publish a translation:

1. Take the English source with markers (`artemis-privacy-en.md` from the web-dev hand-off;
   same format as below) and translate the text under each marker. Keep the markers.
2. Save as `app/legal_translations/privacy.<lang>.md` (`ru`, `es`, `fr`); terms → `terms.<lang>.md`.
3. Run `python -m pytest -q tests/test_legal_i18n.py tests/test_crete_privacy.py` and deploy as usual.

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
