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
