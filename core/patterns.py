"""
Генерация regex-паттернов для всех вариаций названия компании.

Для "ЛУКОЙЛ" генерирует:
- ЛУКОЙЛ, Лукойл, лукойл
- ПАО "ЛУКОЙЛ", ПАО «ЛУКОЙЛ», ПАО 'ЛУКОЙЛ'
- ООО "ЛУКОЙЛ", АО "ЛУКОЙЛ" и т.д.
- ЛУКОЙЛа, ЛУКОЙЛу, ЛУКОЙЛом, ЛУКОЙЛе (падежные окончания)
"""

import re

ORG_FORMS = ['ПАО', 'ООО', 'АО', 'ЗАО', 'ОАО', 'НАО',
             'ИП', 'ФГУП', 'МУП', 'ГУП', 'НКО', 'АНО']

QUOTE_PAIRS = [
    ('«', '»'),
    ('"', '"'),
    ('\u201c', '\u201d'),  # "…"
    ('\u201e', '\u201c'),  # „…"
    ("'", "'"),
    ('`', '`'),
]

# Падежные окончания для названий
CASE_SUFFIXES = ['', 'а', 'у', 'ом', 'е', 'ы', 'ов', 'ам', 'ами', 'ах']


def build_company_patterns(
    company_name: str,
    include_cases: bool = True,
    include_quotes: bool = True,
    include_org_forms: bool = True,
    case_insensitive: bool = True,
) -> list[re.Pattern]:
    """
    Возвращает список скомпилированных regex-паттернов,
    отсортированных от самого длинного к самому короткому.
    """
    flags = re.IGNORECASE if case_insensitive else 0
    raw_patterns: list[str] = []
    name = company_name.strip()
    name_escaped = re.escape(name)

    # --- 1. Орг. форма + кавычки + название ---
    if include_org_forms:
        org_alt = '|'.join(re.escape(f) for f in ORG_FORMS)
        if include_quotes:
            for open_q, close_q in QUOTE_PAIRS:
                oq = re.escape(open_q)
                cq = re.escape(close_q)
                # С падежами
                if include_cases:
                    for suffix in CASE_SUFFIXES:
                        s = re.escape(suffix)
                        raw_patterns.append(
                            rf'(?:{org_alt})\s*{oq}{name_escaped}{s}{cq}'
                        )
                else:
                    raw_patterns.append(
                        rf'(?:{org_alt})\s*{oq}{name_escaped}{cq}'
                    )
        # Орг. форма без кавычек
        if include_cases:
            for suffix in CASE_SUFFIXES:
                s = re.escape(suffix)
                raw_patterns.append(
                    rf'(?:{org_alt})\s+{name_escaped}{s}\b'
                )
        else:
            raw_patterns.append(
                rf'(?:{org_alt})\s+{name_escaped}\b'
            )

    # --- 2. Только в кавычках (без орг. формы) ---
    if include_quotes:
        for open_q, close_q in QUOTE_PAIRS:
            oq = re.escape(open_q)
            cq = re.escape(close_q)
            if include_cases:
                for suffix in CASE_SUFFIXES:
                    s = re.escape(suffix)
                    raw_patterns.append(rf'{oq}{name_escaped}{s}{cq}')
            else:
                raw_patterns.append(rf'{oq}{name_escaped}{cq}')

    # --- 3. Просто название с падежами ---
    if include_cases:
        for suffix in CASE_SUFFIXES:
            s = re.escape(suffix)
            raw_patterns.append(rf'\b{name_escaped}{s}\b')
    else:
        raw_patterns.append(rf'\b{name_escaped}\b')

    # Убираем дубликаты, сохраняя порядок
    seen = set()
    unique: list[str] = []
    for p in raw_patterns:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    # Сортируем от длинных к коротким
    unique.sort(key=len, reverse=True)

    return [re.compile(p, flags) for p in unique]


def build_city_patterns(
    city_name: str,
    case_insensitive: bool = True,
) -> list[re.Pattern]:
    """
    Генерирует regex-паттерны для названия города с падежами и префиксами.

    Для "Москва" генерирует:
    - г. Москва, г.Москва, город Москва
    - Москвы, Москве, Москвой, Москву (падежи)
    """
    flags = re.IGNORECASE if case_insensitive else 0
    raw_patterns: list[str] = []
    name = city_name.strip()
    name_escaped = re.escape(name)

    # Падежные окончания для городов
    city_suffixes = _get_city_case_forms(name)

    # Все формы названия
    all_forms = [re.escape(f) for f in city_suffixes]
    forms_alt = '|'.join(sorted(all_forms, key=len, reverse=True))

    # С префиксом "г." / "г. " / "город "
    raw_patterns.append(rf'(?:г\.\s*|город\s+)(?:{forms_alt})')

    # Просто название с падежами
    raw_patterns.append(rf'\b(?:{forms_alt})\b')

    # Убираем дубликаты
    seen = set()
    unique: list[str] = []
    for p in raw_patterns:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    unique.sort(key=len, reverse=True)
    return [re.compile(p, flags) for p in unique]


def _get_city_case_forms(city_name: str) -> list[str]:
    """
    Возвращает падежные формы города.
    Поддерживает типичные окончания: -а, -о, -ск, -ий, согласная.
    """
    forms = {city_name}
    lower = city_name.lower()

    if lower.endswith('а'):
        base = city_name[:-1]
        forms.update([
            base + 'а', base + 'ы', base + 'е',
            base + 'у', base + 'ой', base + 'ою',
        ])
    elif lower.endswith('я'):
        base = city_name[:-1]
        forms.update([
            base + 'я', base + 'и', base + 'е',
            base + 'ю', base + 'ей', base + 'ею',
        ])
    elif lower.endswith('о') or lower.endswith('е'):
        base = city_name[:-1]
        suffix = city_name[-1]
        forms.update([
            base + suffix, base + 'а', base + 'у',
            base + 'ом', base + 'е',
        ])
    elif lower.endswith('ий') or lower.endswith('ый'):
        base = city_name[:-2]
        forms.update([
            base + 'ий', base + 'ый', base + 'ого',
            base + 'ому', base + 'им', base + 'ом',
        ])
    else:
        # Согласная: Саратов, Иркутск и т.д.
        forms.update([
            city_name, city_name + 'а', city_name + 'у',
            city_name + 'ом', city_name + 'е',
        ])

    return list(forms)


def build_custom_patterns(
    search_text: str,
    case_insensitive: bool = True,
) -> list[re.Pattern]:
    """
    Простой текстовый поиск — для произвольных полей (ИНН, адрес и т.п.).
    """
    flags = re.IGNORECASE if case_insensitive else 0
    escaped = re.escape(search_text.strip())
    return [re.compile(escaped, flags)]


def build_replacement_for_company(
    original_match: str,
    company_replacement: str,
) -> str:
    """
    Генерирует текст замены, подстраиваясь под формат оригинала.

    Если оригинал: 'ПАО «ЛУКОЙЛ»' → замена: 'ООО «Ромашка»'
    Если оригинал: 'ЛУКОЙЛ' → замена: 'Ромашка'
    Если оригинал: 'ЛУКОЙЛа' → замена: 'Ромашки'
    """
    # Если замена — это шаблон типа [КОМПАНИЯ], возвращаем как есть
    if company_replacement.startswith('[') or company_replacement.startswith('█'):
        return company_replacement

    return company_replacement
