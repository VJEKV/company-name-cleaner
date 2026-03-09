# ТЗ для Claude Code: Portable-приложение «Company Name Cleaner»

## Задача

Создай портативное GUI-приложение на Python, которое **заменяет** (НЕ удаляет!) название компании и фамилии сотрудников на заглушки в файлах .docx и .pdf. Приложение должно работать с флешки как единый .exe без установки Python на целевой машине.

**ВАЖНО: Текст никогда не удаляется — только заменяется.** Удаление текста ломает структуру документов, сбивает форматирование и нарушает целостность таблиц.

---

## Архитектура

### Стек технологий
- **Python 3.11+**
- **GUI**: tkinter (встроен в Python, не требует доп. зависимостей)
- **DOCX**: python-docx
- **PDF**: PyMuPDF (fitz)
- **Сборка**: PyInstaller (один .exe, флаг `--onefile`)
- **Regex**: модуль `re` для вариаций названий и фамилий

### Структура проекта
```
company_cleaner/
├── main.py              # Точка входа + GUI
├── core/
│   ├── __init__.py
│   ├── docx_cleaner.py  # Обработка .docx
│   ├── pdf_cleaner.py   # Обработка .pdf
│   ├── patterns.py      # Regex-паттерны и словарь вариаций
│   ├── replacements.py  # Генератор вариантов замены (заглушки)
│   ├── surnames.py      # Обработка фамилий (ФИО, инициалы)
│   └── utils.py         # Вспомогательные функции
├── assets/
│   └── stamps/          # Встроенные штампы-заглушки (PNG, для PDF)
├── build.spec           # Конфиг PyInstaller
├── requirements.txt
└── README.md
```

---

## Два режима замены

### Режим 1: Текстовая заглушка (DOCX + PDF)
Название компании и фамилии заменяются на текстовую строку-заглушку.

### Режим 2: Графический штамп (только PDF)
Поверх области с текстом ставится непрозрачное изображение-штамп (например, ромашка, логотип, плашка). Текст под штампом закрашивается белым прямоугольником, поверх — штамп.

Пользователь выбирает режим в интерфейсе. Для DOCX доступен только текстовый режим. Для PDF — оба.

---

## Модуль replacements.py — Генератор вариантов замены

```python
"""
При запуске приложение ПРЕДЛАГАЕТ пользователю варианты замены.
Пользователь может выбрать из предложенных или ввести свой.

Логика: заглушка должна быть той же "природы", что и оригинал,
чтобы документ выглядел естественно и не ломалась структура.
"""

# === ВАРИАНТЫ ЗАМЕНЫ НАЗВАНИЯ КОМПАНИИ ===

COMPANY_REPLACEMENTS = {
    "Нейтральные": [
        "ООО «Ромашка»",
        "ПАО «Компания»", 
        "АО «Предприятие»",
        "ООО «Организация»",
    ],
    "Цветочные": [
        "ООО «Ромашка»",
        "ПАО «Василёк»",
        "АО «Подсолнух»",
        "ООО «Одуванчик»",
    ],
    "Абстрактные": [
        "ООО «Альфа»",
        "ПАО «Дельта»",
        "АО «Омега»",
        "ООО «Сигма»",
    ],
    "Очевидные заглушки": [
        "[КОМПАНИЯ]",
        "[НАИМЕНОВАНИЕ]",
        "███████",          # визуальная редакция
        "ХХХХХХ",
    ],
}

# === ВАРИАНТЫ ЗАМЕНЫ ФАМИЛИЙ ===

SURNAME_REPLACEMENTS = {
    "Стандартные ФИО": [
        "Иванов И.И.",
        "Петров П.П.",
        "Сидоров С.С.",
        "Кузнецов К.К.",
    ],
    "Нейтральные": [
        "Сотрудник №{n}",      # автонумерация: Сотрудник №1, №2...
        "Специалист №{n}",
        "Работник №{n}",
    ],
    "Очевидные заглушки": [
        "[ФИО]",
        "[СОТРУДНИК]",
        "███████",
        "ХХХХХХ",
    ],
    "Последовательные буквенные": [
        "Сотрудник А.",         # каждая новая фамилия = следующая буква
        "Сотрудник Б.",
        "Сотрудник В.",
        # ... автоматически
    ],
}

def get_company_replacement_options() -> dict[str, list[str]]:
    """Возвращает словарь категорий → список вариантов замены для компании."""
    return COMPANY_REPLACEMENTS

def get_surname_replacement_options() -> dict[str, list[str]]:
    """Возвращает словарь категорий → список вариантов замены для фамилий."""
    return SURNAME_REPLACEMENTS

def generate_sequential_replacement(template: str, index: int) -> str:
    """
    Для шаблонов с {n} — подставляет порядковый номер.
    Для буквенных — подставляет букву алфавита.
    
    Важно: одна и та же фамилия ВСЕГДА заменяется на одну и ту же заглушку
    в рамках одного сеанса обработки (consistency map).
    """
    pass

class ReplacementMapper:
    """
    Отвечает за консистентность замен в рамках сеанса.
    
    Если "Петров" заменён на "Сотрудник №3" в первом файле,
    то во всех остальных файлах "Петров" тоже будет "Сотрудник №3".
    
    Хранит маппинг: оригинал → заглушка
    """
    def __init__(self, template: str):
        self.template = template
        self.mapping: dict[str, str] = {}
        self.counter = 1
    
    def get_replacement(self, original: str) -> str:
        """Возвращает заглушку. Если этот оригинал уже встречался — ту же самую."""
        normalized = original.strip().lower()
        if normalized not in self.mapping:
            self.mapping[normalized] = generate_sequential_replacement(self.template, self.counter)
            self.counter += 1
        return self.mapping[normalized]
```

---

## Модуль surnames.py — Обработка фамилий и ФИО

```python
"""
Фамилии в документах встречаются в разных форматах:
- "Иванов Иван Иванович" (полное ФИО)
- "Иванов И.И." (фамилия + инициалы)
- "И.И. Иванов" (инициалы + фамилия)
- "Иванов" (только фамилия)
- "Иванова" (женская форма)
- "Иванову И.И." (падежная форма + инициалы)

Также фамилии могут быть в таблицах, подписях, колонтитулах.
"""

import re

# Русские падежные окончания для фамилий
# Муж.: -ов, -ев, -ин, -ский, -цкий, -ый, -ой
# Жен.: -ова, -ева, -ина, -ская, -цкая, -ая, -яя

SURNAME_CASE_SUFFIXES = {
    # Для фамилий на -ов/-ев
    "masculine_ov": ["", "а", "у", "ым", "е", "ых"],
    # Для фамилий на -ова/-ева  
    "feminine_ova": ["", "ой", "у", "ой", "е", "ых"],
    # Для фамилий на -ский/-цкий
    "masculine_sky": ["", "ого", "ому", "им", "ом", "их"],
    # Для фамилий на -ская/-цкая
    "feminine_skaya": ["", "ой", "ую", "ой", "ой", "их"],
}

class SurnamePattern:
    """
    Пользователь вводит список фамилий (по одной на строку или через запятую).
    Для каждой фамилии генерируется набор regex-паттернов.
    """
    
    def __init__(self, surname: str):
        self.surname = surname.strip()
        self.base = self._extract_base()
    
    def _extract_base(self) -> str:
        """Извлекает основу фамилии для склонения."""
        pass
    
    def build_patterns(self) -> list[re.Pattern]:
        """
        Генерирует паттерны для всех вариаций:
        
        1. "Иванов" → Иванов, Иванова, Иванову, Ивановым, Иванове
        2. "Иванов И.И." → с пробелами, без пробелов между инициалами
        3. "И.И. Иванов" → инициалы перед фамилией
        4. "Иванов Иван Иванович" → полное ФИО (если указано)
        5. Женские формы (если указан флаг или авто-определение)
        
        Паттерны сортируются от длинного к короткому.
        """
        patterns = []
        
        # Полное ФИО с инициалами: "Иванов И.И." и "И.И. Иванов"
        # Допускаем: пробел/нет между инициалами, точка/нет после каждой буквы
        initial_pattern = r'[А-ЯЁ]\.?\s*[А-ЯЁ]\.?'
        
        # Фамилия + инициалы
        patterns.append(
            re.compile(
                rf'{self.surname}\s+{initial_pattern}',
                re.IGNORECASE
            )
        )
        
        # Инициалы + фамилия
        patterns.append(
            re.compile(
                rf'{initial_pattern}\s+{self.surname}',
                re.IGNORECASE
            )
        )
        
        # Просто фамилия (с падежными вариациями)
        # ... добавить вариации
        
        return patterns
```

---

## Модуль patterns.py — Словарь вариаций названия компании

```python
"""
Генерирует regex-паттерны для всех вариаций названия компании.

Пример: для "ЛУКОЙЛ" генерирует:
- ЛУКОЙЛ, Лукойл, лукойл
- ПАО "ЛУКОЙЛ", ПАО «ЛУКОЙЛ», ПАО 'ЛУКОЙЛ'
- ООО "ЛУКОЙЛ", АО "ЛУКОЙЛ" и т.д.
- ЛУКОЙЛа, ЛУКОЙЛу, ЛУКОЙЛом, ЛУКОЙЛе (падежные окончания)
- С пробелами и без между организационно-правовой формой и названием
"""

import re

def build_patterns(company_name: str, 
                   include_cases: bool = True,
                   include_quotes: bool = True,
                   include_org_forms: bool = True,
                   case_insensitive: bool = True) -> list[re.Pattern]:
    """
    Возвращает список скомпилированных regex-паттернов,
    отсортированных от самого длинного к самому короткому
    (чтобы сначала заменить "ПАО «ЛУКОЙЛ»", потом "ЛУКОЙЛ").
    """
    
    ORG_FORMS = ["ПАО", "ООО", "АО", "ЗАО", "ОАО", "НАО"]
    
    QUOTE_PAIRS = [
        ('«', '»'),
        ('"', '"'),
        ('\u201c', '\u201d'),
        ("'", "'"),
    ]
    
    CASE_SUFFIXES = ["а", "у", "ом", "е", "ы", "ов", "ам", "ами", "ах"]
    
    pass  # Реализовать
```

---

## Модуль docx_cleaner.py — Обработка DOCX

```python
"""
Стратегия: посимвольная склейка runs в каждом параграфе,
поиск вхождений в склеенном тексте, ЗАМЕНА на заглушку.

ВАЖНО: НЕ удаляем текст — заменяем. Это сохраняет структуру документа.

Обрабатываемые области документа:
1. Основной текст (параграфы)
2. Таблицы (ячейки → параграфы)
3. Колонтитулы (headers/footers)
4. Текстовые поля (shapes/textboxes) — если доступны
5. Сноски и примечания

Важно: сохранять исходное форматирование (bold, italic, font, size).
"""

from docx import Document
import re

def clean_docx(filepath: str, 
               output_path: str,
               company_patterns: list[re.Pattern],
               surname_patterns: list[re.Pattern],
               company_replacement: str,
               surname_mapper: 'ReplacementMapper') -> dict:
    """
    Заменяет вхождения названия компании и фамилий на заглушки.
    
    Возвращает:
    {
        "status": "success" | "error",
        "company_matches": int,
        "surname_matches": int,
        "total_replacements": int,
        "error_message": str | None
    }
    """
    
    doc = Document(filepath)
    stats = {"company": 0, "surname": 0}
    
    # 1. Обработка параграфов
    for paragraph in doc.paragraphs:
        stats = _process_paragraph(paragraph, company_patterns, surname_patterns,
                                   company_replacement, surname_mapper, stats)
    
    # 2. Обработка таблиц
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    stats = _process_paragraph(paragraph, company_patterns, surname_patterns,
                                               company_replacement, surname_mapper, stats)
    
    # 3. Обработка колонтитулов
    for section in doc.sections:
        for header in [section.header, section.first_page_header, section.even_page_header]:
            if header and header.is_linked_to_previous is False:
                for paragraph in header.paragraphs:
                    stats = _process_paragraph(paragraph, company_patterns, surname_patterns,
                                               company_replacement, surname_mapper, stats)
        for footer in [section.footer, section.first_page_footer, section.even_page_footer]:
            if footer and footer.is_linked_to_previous is False:
                for paragraph in footer.paragraphs:
                    stats = _process_paragraph(paragraph, company_patterns, surname_patterns,
                                               company_replacement, surname_mapper, stats)
    
    doc.save(output_path)
    return {
        "status": "success",
        "company_matches": stats["company"],
        "surname_matches": stats["surname"],
        "total_replacements": stats["company"] + stats["surname"]
    }


def _process_paragraph(paragraph, company_patterns, surname_patterns,
                       company_replacement, surname_mapper, stats):
    """
    Ключевой алгоритм:
    1. Склеиваем текст всех runs: "ЛУК" + "ОЙЛ" → "ЛУКОЙЛ"
    2. Строим карту символ → (run_index, char_index_in_run)
    3. Ищем паттерны в склеенном тексте
    4. ЗАМЕНЯЕМ найденное на заглушку (не удаляем!)
    5. Модифицируем runs, сохраняя форматирование первого затронутого run
    
    Порядок замены:
    - Сначала длинные паттерны (ПАО «ЛУКОЙЛ»), потом короткие (ЛУКОЙЛ)
    - Сначала компания, потом фамилии (чтобы не зацепить фамилию внутри названия)
    """
    pass  # Реализовать
```

---

## Модуль pdf_cleaner.py — Обработка PDF

```python
"""
Два режима:

РЕЖИМ 1 — Текстовая заглушка:
Находим текст → закрашиваем белым прямоугольником → поверх пишем текст заглушки.
Используем redact с параметром text= для вставки замены.

РЕЖИМ 2 — Графический штамп:
Находим текст → закрашиваем белым прямоугольником → поверх вставляем PNG-штамп.
Штамп масштабируется под размер области.

В обоих случаях оригинальный текст физически удаляется из потока (через redaction),
но ВИЗУАЛЬНО на его месте появляется замена — документ не «рваный».
"""

import fitz  # PyMuPDF
import re
from pathlib import Path

# Встроенные штампы
BUILTIN_STAMPS = {
    "ромашка": "assets/stamps/daisy.png",
    "звёздочка": "assets/stamps/star.png",
    "замок": "assets/stamps/lock.png",
    "конфиденциально": "assets/stamps/confidential.png",
    "чёрная плашка": None,  # Генерируется программно — чёрный прямоугольник
}

def clean_pdf_text_mode(filepath: str,
                        output_path: str,
                        company_patterns: list[re.Pattern],
                        surname_patterns: list[re.Pattern],
                        company_replacement: str,
                        surname_mapper: 'ReplacementMapper') -> dict:
    """
    Режим 1: Заменяем текст на текстовую заглушку.
    
    Используем page.add_redact_annot() с параметром text= 
    для вставки текста замены на место оригинала.
    """
    doc = fitz.open(filepath)
    stats = {"company": 0, "surname": 0, "pages_affected": []}
    
    for page_num, page in enumerate(doc):
        page_changed = False
        
        # Замена названия компании
        for pattern in company_patterns:
            text = page.get_text()
            for match in pattern.finditer(text):
                rects = page.search_for(match.group())
                for rect in rects:
                    page.add_redact_annot(
                        rect,
                        text=company_replacement,
                        fill=(1, 1, 1),        # белый фон
                        text_color=(0, 0, 0),  # чёрный текст замены
                        fontsize=0,            # автоподбор
                        cross_out=False,
                    )
                    stats["company"] += 1
                    page_changed = True
        
        # Замена фамилий
        for pattern in surname_patterns:
            text = page.get_text()
            for match in pattern.finditer(text):
                replacement = surname_mapper.get_replacement(match.group())
                rects = page.search_for(match.group())
                for rect in rects:
                    page.add_redact_annot(
                        rect,
                        text=replacement,
                        fill=(1, 1, 1),
                        text_color=(0, 0, 0),
                        fontsize=0,
                        cross_out=False,
                    )
                    stats["surname"] += 1
                    page_changed = True
        
        if page_changed:
            page.apply_redactions()
            stats["pages_affected"].append(page_num + 1)
    
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return stats


def clean_pdf_stamp_mode(filepath: str,
                         output_path: str,
                         company_patterns: list[re.Pattern],
                         surname_patterns: list[re.Pattern],
                         stamp_path: str | None = None,
                         stamp_type: str = "чёрная плашка") -> dict:
    """
    Режим 2: Закрашиваем область и ставим штамп поверх.
    
    Алгоритм:
    1. Находим все вхождения текста на странице
    2. Для каждого вхождения: redact (закрасить белым)
    3. Apply redactions
    4. Поверх каждой области вставляем изображение штампа
       (масштабированное под размер rect)
    
    Для "чёрной плашки" — просто рисуем чёрный прямоугольник (без PNG).
    """
    doc = fitz.open(filepath)
    stats = {"company": 0, "surname": 0, "pages_affected": []}
    
    # Загружаем штамп если указан
    stamp_image = None
    if stamp_path and Path(stamp_path).exists():
        stamp_image = open(stamp_path, "rb").read()
    
    for page_num, page in enumerate(doc):
        rects_to_stamp = []  # Сохраняем позиции для штампов
        page_changed = False
        
        # Собираем все области для замены
        all_patterns = company_patterns + surname_patterns
        for pattern in all_patterns:
            text = page.get_text()
            for match in pattern.finditer(text):
                found_rects = page.search_for(match.group())
                for rect in found_rects:
                    # Белый redact (убираем текст)
                    page.add_redact_annot(rect, text="", fill=(1, 1, 1))
                    rects_to_stamp.append(rect)
                    page_changed = True
                    stats["company" if pattern in company_patterns else "surname"] += 1
        
        if page_changed:
            page.apply_redactions()  # Сначала убираем оригинальный текст
            
            # Теперь ставим штампы поверх
            for rect in rects_to_stamp:
                if stamp_type == "чёрная плашка" or stamp_image is None:
                    # Рисуем чёрный прямоугольник
                    shape = page.new_shape()
                    shape.draw_rect(rect)
                    shape.finish(color=(0, 0, 0), fill=(0, 0, 0))
                    shape.commit()
                else:
                    # Вставляем PNG штамп, масштабированный под rect
                    page.insert_image(rect, stream=stamp_image, keep_proportion=True)
            
            stats["pages_affected"].append(page_num + 1)
    
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return stats
```

---

## GUI — главное окно (tkinter)

### Макет окна (примерно 850x750)

```
┌──────────────────────────────────────────────────────┐
│  Company Name Cleaner v1.0                           │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ── Название компании ───────────────────────────    │
│  Искать: [____________________]                      │
│  Заменить на: [▼ Выбрать вариант / свой ________]    │
│    Предложения: ○ ООО «Ромашка»  ○ [КОМПАНИЯ]       │
│                 ○ ПАО «Альфа»    ○ ██████            │
│                                                      │
│  ☑ Учитывать падежи          ☑ Учитывать кавычки     │
│  ☑ Орг. формы (ПАО, ООО)    ☑ Регистронезависимо    │
│                                                      │
│  ── Фамилии сотрудников ────────────────────────     │
│  ┌────────────────────────────────────────────┐      │
│  │ Петров                                     │      │
│  │ Сидоров                                    │      │
│  │ Козлова                                    │      │
│  └────────────────────────────────────────────┘      │
│  [+ Добавить]  [Из файла .txt]  [Очистить]           │
│  Заменять на: [▼ Выбрать шаблон / свой _______]      │
│    Предложения: ○ Сотрудник №N   ○ Иванов И.И.      │
│                 ○ [ФИО]          ○ Буквенные (А,Б,В) │
│  ☑ Искать с инициалами  ☑ Женские формы              │
│                                                      │
│  ── Режим замены в PDF ─────────────────────────     │
│  ○ Текстовая заглушка (как в DOCX)                   │
│  ○ Графический штамп:                                │
│    [▼ Ромашка 🌼] [Чёрная плашка ■] [Замок 🔒]      │
│    [Свой PNG...]                                     │
│                                                      │
│  ── Файлы ──────────────────────────────────────     │
│  [Добавить файлы]  [Добавить папку]  [Очистить]      │
│  ┌────────────────────────────────────────────┐      │
│  │ 📄 contract.docx                           │      │
│  │ 📄 report_2024.pdf                         │      │
│  │ 📄 order_153.docx                          │      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  Папка результатов: [________________] [Обзор]       │
│                                                      │
│  [═══════════════════════ 45% ═══════════════]       │
│                                                      │
│  ── Лог ────────────────────────────────────────     │
│  ┌────────────────────────────────────────────┐      │
│  │ ✓ contract.docx — компания: 8, фамилии: 3 │      │
│  │ ✓ report_2024.pdf — компания: 2, штамп: 5  │      │
│  │ ⚠ order_153.docx — 0 вхождений             │      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│     [▶ ОБРАБОТАТЬ]  [Предпросмотр]  [Карта замен]    │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Требования к GUI
- Drag & drop файлов в список (через `tkinterdnd2` или кнопки)
- Фильтр файлов: только .docx и .pdf
- По умолчанию папка результатов = `./cleaned/` рядом с исходниками
- **Оригиналы НИКОГДА не перезаписываются**
- Лог в реальном времени с цветовой индикацией
- Обработка в отдельном потоке (threading), чтобы GUI не зависал
- Прогресс-бар обновляется пофайлово
- Комбо-бокс с предложениями замены, выпадающий по клику
- Список фамилий — редактируемый текстовый блок (по одной на строку)
- Загрузка фамилий из .txt файла (по одной на строку)

---

## Кнопка «Карта замен»

После обработки доступна **карта замен** — таблица соответствий:

```
┌────────────────────────────────────────────────┐
│           Карта замен (сеанс)                  │
├──────────────────┬─────────────────────────────┤
│ Оригинал         │ Заменено на                 │
├──────────────────┼─────────────────────────────┤
│ ПАО «ЛУКОЙЛ»    │ ООО «Ромашка»              │
│ ЛУКОЙЛ           │ Ромашка                     │
│ ЛУКОЙЛа          │ Ромашки                     │
│ Петров А.В.      │ Сотрудник №1               │
│ А.В. Петров      │ Сотрудник №1               │
│ Козлова Е.Н.     │ Сотрудник №2               │
└──────────────────┴─────────────────────────────┘
│        [Экспорт в CSV]  [Закрыть]              │
```

Эта карта нужна для:
- Проверки корректности замен
- Обратного восстановления (если понадобится)
- Документирования процесса обезличивания

---

## Режим предпросмотра

Кнопка «Предпросмотр» — сканирует файлы БЕЗ изменений и показывает:
- Количество вхождений в каждом файле (отдельно компания / фамилии)
- Контекст каждого вхождения (±30 символов вокруг найденного текста)
- Что будет заменено и на что
- Отдельное окно с результатами предпросмотра

---

## Встроенные штампы для PDF

Приложение включает несколько встроенных PNG-штампов (небольшие, ~5-10 КБ каждый):

1. **Ромашка** 🌼 — цветок ромашки на белом фоне
2. **Чёрная плашка** ■ — генерируется программно, сплошной чёрный прямоугольник
3. **Замок** 🔒 — иконка замка (конфиденциально)
4. **Плашка «КОНФИДЕНЦИАЛЬНО»** — красная плашка с белым текстом
5. **Свой PNG** — пользователь может загрузить свой файл

Штампы хранятся в `assets/stamps/` и включаются в .exe при сборке PyInstaller (`--add-data`).

Штампы можно сгенерировать программно через Pillow при первом запуске, если не хотим тащить файлы — нарисовать простую ромашку, замок и плашку средствами PIL.

---

## Сборка в .exe

### requirements.txt
```
python-docx==1.1.2
PyMuPDF==1.24.14
Pillow==11.0.0
pyinstaller==6.11.1
```

### Команда сборки
```bash
pip install -r requirements.txt
pyinstaller --onefile \
    --windowed \
    --name "CompanyCleaner" \
    --icon=icon.ico \
    --add-data "assets/stamps:assets/stamps" \
    --add-data "README.md:." \
    main.py
```

Результат: `dist/CompanyCleaner.exe` — один файл ~45-55 МБ, работает с флешки.

---

## Обработка ошибок

- **Защищённые PDF** (пароль) → сообщение в лог, пропуск файла
- **Битые файлы** → try/except, сообщение в лог, продолжение обработки
- **Файлы только для чтения** → копирование во временную папку
- **Очень большие файлы (>100 МБ)** → предупреждение, обработка с увеличенным таймаутом
- **Русские символы в путях** → корректная работа с Path и encoding
- **Отсутствие прав на запись** → сообщение пользователю
- **Текст не найден в PDF** (сканы без OCR-слоя) → предупреждение: «Файл может быть сканом. Текстовый слой не обнаружен.»

---

## Дополнительные требования

1. **Логирование**: все операции пишутся в `cleaner.log` рядом с .exe
2. **Настройки сохраняются**: название компании, список фамилий, путь, выбранные заглушки → `config.json` рядом с .exe
3. **Горячие клавиши**: Ctrl+O — добавить файлы, Ctrl+Enter — обработка, Escape — отмена
4. **Статус-бар**: общее число файлов, вхождений компании, вхождений фамилий
5. **Консистентность замен**: одна фамилия = одна заглушка во всех файлах сеанса
6. **Платформа**: Windows 10/11 (основная), Linux (опционально)
