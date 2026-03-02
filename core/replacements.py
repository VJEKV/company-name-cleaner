"""
Генератор вариантов замены (заглушки) для названий компаний и фамилий.
Обеспечивает консистентность: одна фамилия = одна заглушка во всём сеансе.
"""

COMPANY_REPLACEMENTS = {
    "Нейтральные": [
        'ООО «Ромашка»',
        'ПАО «Компания»',
        'АО «Предприятие»',
        'ООО «Организация»',
    ],
    "Цветочные": [
        'ООО «Ромашка»',
        'ПАО «Василёк»',
        'АО «Подсолнух»',
        'ООО «Одуванчик»',
    ],
    "Абстрактные": [
        'ООО «Альфа»',
        'ПАО «Дельта»',
        'АО «Омега»',
        'ООО «Сигма»',
    ],
    "Очевидные заглушки": [
        '[КОМПАНИЯ]',
        '[НАИМЕНОВАНИЕ]',
        '███████',
        'ХХХХХХ',
    ],
}

SURNAME_REPLACEMENTS = {
    "Стандартные ФИО": [
        'Иванов И.И.',
        'Петров П.П.',
        'Сидоров С.С.',
        'Кузнецов К.К.',
    ],
    "Нейтральные": [
        'Сотрудник №{n}',
        'Специалист №{n}',
        'Работник №{n}',
    ],
    "Очевидные заглушки": [
        '[ФИО]',
        '[СОТРУДНИК]',
        '███████',
        'ХХХХХХ',
    ],
    "Последовательные буквенные": [
        'Сотрудник А.',
        'Сотрудник Б.',
        'Сотрудник В.',
    ],
}

CITY_REPLACEMENTS = {
    "Нейтральные": [
        'г. Ромашкино',
        'г. Цветочное',
        'г. Светлоград',
    ],
    "Очевидные заглушки": [
        '[ГОРОД]',
        '███████',
        'ХХХХХХ',
    ],
}

SIGNATORY_REPLACEMENTS = {
    "Стандартные": [
        'Иванов И.И.',
        'Петров П.П.',
    ],
    "Нейтральные": [
        'Подписант',
        'Руководитель',
    ],
    "Очевидные заглушки": [
        '[ПОДПИСАНТ]',
        '███████',
    ],
}

GENERIC_REPLACEMENTS = {
    "Очевидные заглушки": [
        '[ЗАГЛУШКА]',
        '███████',
        'ХХХХХХ',
    ],
}

RUSSIAN_ALPHABET = 'АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ'


def get_company_replacement_options() -> dict[str, list[str]]:
    return COMPANY_REPLACEMENTS


def get_surname_replacement_options() -> dict[str, list[str]]:
    return SURNAME_REPLACEMENTS


def get_city_replacement_options() -> dict[str, list[str]]:
    return CITY_REPLACEMENTS


def get_signatory_replacement_options() -> dict[str, list[str]]:
    return SIGNATORY_REPLACEMENTS


def get_generic_replacement_options() -> dict[str, list[str]]:
    return GENERIC_REPLACEMENTS


def generate_sequential_replacement(template: str, index: int) -> str:
    """
    Для шаблонов с {n} — подставляет порядковый номер.
    Для буквенных шаблонов — подставляет букву алфавита.
    """
    if '{n}' in template:
        return template.replace('{n}', str(index))

    # Буквенный шаблон: ищем одиночную букву после пробела перед точкой
    # Например "Сотрудник А." -> "Сотрудник Б.", "Сотрудник В." и т.д.
    letter_idx = (index - 1) % len(RUSSIAN_ALPHABET)
    letter = RUSSIAN_ALPHABET[letter_idx]

    # Находим букву в шаблоне и заменяем
    for ch in RUSSIAN_ALPHABET:
        if ch + '.' in template:
            return template.replace(ch + '.', letter + '.')

    # Если шаблон не содержит паттерна, просто добавляем номер
    return f"{template} №{index}"


class ReplacementMapper:
    """
    Консистентность замен в рамках сеанса.
    Если "Петров" заменён на "Сотрудник №3" в первом файле,
    то во всех файлах "Петров" тоже будет "Сотрудник №3".
    """

    def __init__(self, template: str):
        self.template = template
        self.mapping: dict[str, str] = {}
        self.counter = 1

    def get_replacement(self, original: str) -> str:
        normalized = original.strip().lower()
        if normalized not in self.mapping:
            self.mapping[normalized] = generate_sequential_replacement(
                self.template, self.counter
            )
            self.counter += 1
        return self.mapping[normalized]

    def get_map(self) -> dict[str, str]:
        return dict(self.mapping)
