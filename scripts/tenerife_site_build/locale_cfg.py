"""Настройки локалей сайта Тенерифе (2026-11-02).

Русский мастер остаётся эталоном вёрстки. Для остальных языков сборка берёт перевод из copy_<loc>/,
а компоненты находит по карте заголовков, которую строит build_v3 (RU-заголовок ↔ перевод по порядку).
Здесь лежат только те якоря, которые в тексте не заголовки: шапки таблицы ступеней и порядок страниц.
"""
LOCALES = ("en", "es", "de", "fr")

# порядок страниц в подвале/меню — тот же, что в русском мастере
# порядок строк в подвале (= порядок меню); INVESTORS не построен и скрывается
PAGE_ORDER = ("index", "producto", "norte", "acciones", "calculadora", "alquiler", "energia",
              "construccion", "proceso", "investors", "faq", "mercado", "simon", "boris")

# шапка таблицы ступеней: первая колонка и колонка роста
LADDER_HEAD = {
    "ru": ("Ступень", "Рост"),
    "en": ("Step", "Rise"),
    "es": ("Tramo", "Subida"),
    "de": ("Stufe", "Anstieg"),
    "fr": ("Étape", "Hausse"),
}

# скрытая на главной секция «Команда и компания» (она же в подвале не нужна)
HIDDEN_TITLES = {
    "ru": "Команда и компания",
    "en": "Team and company",
    "es": "Equipo y sociedad",
    "de": "Team und Gesellschaft",
    "fr": "Équipe et société",
}

# Интерфейсные строки в разметке (не копирайт): шапка, подвал, служебные подписи. Тексты страниц берутся из copy_<loc>.
UI = {
    "ru": {"skip": "К содержанию", "menu": "Меню", "menu_aria": "Меню", "lang_aria": "Язык",
           "pages": "Страницы.", "contacts": "Контакты.", "company": "Компания.", "docs": "Документы.",
           "plinth": "Ключевые цифры", "now": "сейчас", "lang_ru": "Русский"},
    "en": {"skip": "Skip to content", "menu": "Menu", "menu_aria": "Menu", "lang_aria": "Language",
           "pages": "Pages.", "contacts": "Contacts.", "company": "Company.", "docs": "Documents.",
           "plinth": "Key figures", "now": "now", "lang_ru": "Русский"},
    "es": {"skip": "Ir al contenido", "menu": "Menú", "menu_aria": "Menú", "lang_aria": "Idioma",
           "pages": "Páginas.", "contacts": "Contacto.", "company": "Empresa.", "docs": "Documentos.",
           "plinth": "Cifras clave", "now": "ahora", "lang_ru": "Русский"},
    "de": {"skip": "Zum Inhalt", "menu": "Menü", "menu_aria": "Menü", "lang_aria": "Sprache",
           "pages": "Seiten.", "contacts": "Kontakt.", "company": "Unternehmen.", "docs": "Dokumente.",
           "plinth": "Kennzahlen", "now": "jetzt", "lang_ru": "Русский"},
    "fr": {"skip": "Aller au contenu", "menu": "Menu", "menu_aria": "Menu", "lang_aria": "Langue",
           "pages": "Pages.", "contacts": "Contact.", "company": "Société.", "docs": "Documents.",
           "plinth": "Chiffres clés", "now": "maintenant", "lang_ru": "Русский"},
}

# Названия ступеней цены для мини-лестницы (C8 mini) — те же слова, что в первой колонке таблицы copy_<loc>/04
STAGE_NAMES = {
    "ru": ("Очередь", "Разрешение", "Фундамент", "Коробка и кровля", "Отделка", "Ввод"),
    "en": ("Waiting list", "Permit", "Foundation", "Shell and roof", "Finishing", "Handover"),
    "es": ("Lista de espera", "Licencia", "Cimentación", "Estructura y cubierta", "Acabados", "Entrega"),
    "de": ("Warteliste", "Baugenehmigung", "Fundament", "Rohbau und Dach", "Ausbau", "Fertigstellung"),
    "fr": ("Liste d'attente", "Permis", "Fondations", "Gros œuvre et toiture", "Finitions", "Livraison"),
}
