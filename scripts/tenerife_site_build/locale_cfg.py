"""Настройки локалей сайта Тенерифе (2026-11-02).

Русский мастер остаётся эталоном вёрстки. Для остальных языков сборка берёт перевод из copy_<loc>/,
а компоненты находит по карте заголовков, которую строит build_v3 (RU-заголовок ↔ перевод по порядку).
Здесь лежат только те якоря, которые в тексте не заголовки: шапки таблицы ступеней и порядок страниц.
"""
LOCALES = ("en", "es", "de", "fr")

# порядок страниц в подвале/меню — тот же, что в русском мастере
# порядок строк в подвале (= порядок меню); INVESTORS не построен и скрывается
PAGE_ORDER = ("index", "producto", "inversores", "norte", "construccion", "equipo", "calculadora",
              "alquiler", "energia", "proceso", "faq", "mercado", "simon", "boris")

NAV_UI = {
    "ru": {"main": "Основное меню", "calculation": "Получить расчёт", "project": "Проект",
           "participation": "Участие", "team": "Команда", "documents": "Документы"},
    "en": {"main": "Main menu", "calculation": "Get a calculation", "project": "Project",
           "participation": "Participation", "team": "Team", "documents": "Documents"},
    "es": {"main": "Menú principal", "calculation": "Recibir cálculo", "project": "Proyecto",
           "participation": "Participación", "team": "Equipo", "documents": "Documentos"},
    "de": {"main": "Hauptmenü", "calculation": "Berechnung erhalten", "project": "Projekt",
           "participation": "Beteiligung", "team": "Team", "documents": "Dokumente"},
    "fr": {"main": "Menu principal", "calculation": "Obtenir un calcul", "project": "Projet",
           "participation": "Participation", "team": "Équipe", "documents": "Documents"},
}

NOT_FOUND = {
    "ru": ("Страница не найдена", "Проверьте адрес или вернитесь к проекту Artemis de la Cruz.", "На главную"),
    "en": ("Page not found", "Check the address or return to the Artemis de la Cruz project.", "Back to the project"),
    "es": ("Página no encontrada", "Compruebe la dirección o vuelva al proyecto Artemis de la Cruz.", "Volver al proyecto"),
    "de": ("Seite nicht gefunden", "Prüfen Sie die Adresse oder kehren Sie zum Projekt Artemis de la Cruz zurück.", "Zurück zum Projekt"),
    "fr": ("Page introuvable", "Vérifiez l’adresse ou revenez au projet Artemis de la Cruz.", "Revenir au projet"),
}

# шапка таблицы ступеней: первая колонка и сравнение с ценой ввода
LADDER_HEAD = {
    "ru": ("Ступень", "Ниже"),
    "en": ("Step", "Below"),
    "es": ("Tramo", "Menos"),
    "de": ("Stufe", "Unter"),
    "fr": ("Palier", "Sous"),
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
           "plinth": "Ключевые цифры", "now": "сейчас", "lang_ru": "RU"},
    "en": {"skip": "Skip to content", "menu": "Menu", "menu_aria": "Menu", "lang_aria": "Language",
           "pages": "Pages.", "contacts": "Contacts.", "company": "Company.", "docs": "Documents.",
           "plinth": "Key figures", "now": "now", "lang_ru": "RU"},
    "es": {"skip": "Ir al contenido", "menu": "Menú", "menu_aria": "Menú", "lang_aria": "Idioma",
           "pages": "Páginas.", "contacts": "Contacto.", "company": "Empresa.", "docs": "Documentos.",
           "plinth": "Cifras clave", "now": "ahora", "lang_ru": "RU"},
    "de": {"skip": "Zum Inhalt", "menu": "Menü", "menu_aria": "Menü", "lang_aria": "Sprache",
           "pages": "Seiten.", "contacts": "Kontakt.", "company": "Unternehmen.", "docs": "Dokumente.",
           "plinth": "Kennzahlen", "now": "jetzt", "lang_ru": "RU"},
    "fr": {"skip": "Aller au contenu", "menu": "Menu", "menu_aria": "Menu", "lang_aria": "Langue",
           "pages": "Pages.", "contacts": "Contact.", "company": "Société.", "docs": "Documents.",
           "plinth": "Chiffres clés", "now": "maintenant", "lang_ru": "RU"},
}

# Названия ступеней цены для мини-лестницы (C8 mini) — те же слова, что в первой колонке таблицы copy_<loc>/04
STAGE_NAMES = {
    "ru": ("Ранний вход", "Разрешение", "Фундамент", "Коробка и кровля", "Отделка", "Ввод"),
    "en": ("Early entry", "Permit", "Foundation", "Shell and roof", "Finishing", "Handover"),
    "es": ("Entrada inicial", "Licencia", "Cimentación", "Estructura y cubierta", "Acabados", "Entrega"),
    "de": ("Früher Einstieg", "Baugenehmigung", "Fundament", "Rohbau und Dach", "Ausbau", "Fertigstellung"),
    "fr": ("Entrée initiale", "Permis", "Fondations", "Gros œuvre et toiture", "Finitions", "Livraison"),
}
