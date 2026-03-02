"""
Обработка фамилий и ФИО: генерация regex-паттернов для всех вариаций.

Поддерживаемые форматы:
- "Иванов Иван Иванович" (полное ФИО)
- "Иванов И.И." (фамилия + инициалы)
- "И.И. Иванов" (инициалы + фамилия)
- "Иванов" (только фамилия)
- "Иванова" (женская форма)
- Падежные формы: Иванову, Ивановым, Иванове и т.д.
"""

import re

# Падежные окончания по типу фамилии
DECLENSION_SUFFIXES = {
    'ов': ['ов', 'ова', 'ову', 'овым', 'ове', 'овых'],
    'ев': ['ев', 'ева', 'еву', 'евым', 'еве', 'евых'],
    'ёв': ['ёв', 'ёва', 'ёву', 'ёвым', 'ёве', 'ёвых'],
    'ин': ['ин', 'ина', 'ину', 'иным', 'ине', 'иных'],
    'ын': ['ын', 'ына', 'ыну', 'ыным', 'ыне', 'ыных'],
    'ский': ['ский', 'ского', 'скому', 'ским', 'ском', 'ских'],
    'цкий': ['цкий', 'цкого', 'цкому', 'цким', 'цком', 'цких'],
    'ской': ['ской', 'ского', 'скому', 'ским', 'ском', 'ских'],
    # Женские
    'ова': ['ова', 'овой', 'ову', 'овой', 'овой', 'овых'],
    'ева': ['ева', 'евой', 'еву', 'евой', 'евой', 'евых'],
    'ёва': ['ёва', 'ёвой', 'ёву', 'ёвой', 'ёвой', 'ёвых'],
    'ина': ['ина', 'иной', 'ину', 'иной', 'иной', 'иных'],
    'ская': ['ская', 'ской', 'скую', 'ской', 'ской', 'ских'],
    'цкая': ['цкая', 'цкой', 'цкую', 'цкой', 'цкой', 'цких'],
}

# Суффиксы для определения типа фамилии (от длинных к коротким)
SUFFIX_ORDER = [
    'ский', 'цкий', 'ской', 'ская', 'цкая',
    'ова', 'ева', 'ёва', 'ина',
    'ов', 'ев', 'ёв', 'ин', 'ын',
]


class SurnamePattern:
    """Генерирует regex-паттерны для всех вариаций фамилии."""

    def __init__(self, surname: str, search_with_initials: bool = True,
                 search_feminine: bool = True):
        self.surname = surname.strip()
        self.search_with_initials = search_with_initials
        self.search_feminine = search_feminine
        self.base, self.suffix_type = self._extract_base()

    def _extract_base(self) -> tuple[str, str | None]:
        """Извлекает основу фамилии и определяет тип склонения."""
        lower = self.surname.lower()
        for suffix in SUFFIX_ORDER:
            if lower.endswith(suffix):
                base = self.surname[:-len(suffix)]
                return base, suffix
        return self.surname, None

    def _get_declined_forms(self) -> list[str]:
        """Возвращает все падежные формы фамилии."""
        if not self.suffix_type or self.suffix_type not in DECLENSION_SUFFIXES:
            return [self.surname]

        forms = set()
        suffixes = DECLENSION_SUFFIXES[self.suffix_type]
        for suffix in suffixes:
            # Сохраняем регистр первой буквы основы
            if self.base and self.base[0].isupper():
                form = self.base + suffix
            else:
                form = self.base + suffix
            forms.add(form)

        # Добавляем женские формы если нужно
        if self.search_feminine and self.suffix_type in ('ов', 'ев', 'ёв', 'ин', 'ын'):
            fem_suffix = self.suffix_type + 'а'
            if fem_suffix in DECLENSION_SUFFIXES:
                for suffix in DECLENSION_SUFFIXES[fem_suffix]:
                    forms.add(self.base + suffix)

        return list(forms)

    def build_patterns(self) -> list[re.Pattern]:
        """
        Генерирует паттерны для всех вариаций, отсортированные от длинного к короткому.
        """
        patterns = []
        declined_forms = self._get_declined_forms()

        # Создаём alternation для всех падежных форм
        forms_escaped = [re.escape(f) for f in declined_forms]
        forms_alt = '|'.join(sorted(forms_escaped, key=len, reverse=True))

        if self.search_with_initials:
            # Паттерн для инициалов: А.Б. или А. Б. или А Б
            initial_pattern = r'[А-ЯЁ]\.\s*[А-ЯЁ]\.?'

            # Фамилия + инициалы: "Иванов И.И.", "Иванову А.В."
            patterns.append(re.compile(
                rf'(?:{forms_alt})\s+{initial_pattern}',
                re.IGNORECASE
            ))

            # Инициалы + фамилия: "И.И. Иванов", "А.В. Иванову"
            patterns.append(re.compile(
                rf'{initial_pattern}\s+(?:{forms_alt})',
                re.IGNORECASE
            ))

        # Просто фамилия (все падежные формы)
        # Используем word boundary чтобы не зацепить часть другого слова
        patterns.append(re.compile(
            rf'\b(?:{forms_alt})\b',
            re.IGNORECASE
        ))

        return patterns

    def get_all_patterns_sorted(self) -> list[re.Pattern]:
        """Возвращает паттерны отсортированные от длинных к коротким."""
        patterns = self.build_patterns()
        # Сортируем по длине паттерна (приблизительно)
        patterns.sort(key=lambda p: len(p.pattern), reverse=True)
        return patterns
