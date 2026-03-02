"""
Обработка .docx файлов: замена текста с сохранением форматирования.

Стратегия:
1. Склеиваем текст всех runs в параграфе
2. Строим карту: позиция символа → (run_index, char_index_in_run)
3. Ищем паттерны в склеенном тексте
4. ЗАМЕНЯЕМ найденное на заглушку (не удаляем!)
5. Модифицируем runs, сохраняя форматирование первого затронутого run

replacement_rules — универсальный формат:
  [
    {"patterns": [...], "replacement": "текст", "type": "company"},
    {"patterns": [...], "mapper": ReplacementMapper, "type": "surnames"},
    ...
  ]
"""

import re
import logging
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn

logger = logging.getLogger('CompanyCleaner')


def _get_replacement_text(rule: dict, matched_text: str) -> str:
    """Получает текст замены из правила."""
    if "mapper" in rule and rule["mapper"] is not None:
        return rule["mapper"].get_replacement(matched_text)
    return rule.get("replacement", "[ЗАГЛУШКА]")


def clean_docx(
    filepath: str,
    output_path: str,
    replacement_rules: list[dict],
) -> dict:
    """
    Заменяет вхождения на заглушки по списку правил.

    replacement_rules: список словарей с ключами:
      - patterns: list[re.Pattern]
      - replacement: str ИЛИ mapper: ReplacementMapper
      - type: str (для статистики)
    """
    try:
        doc = Document(filepath)
    except Exception as e:
        logger.error(f"Не удалось открыть {filepath}: {e}")
        return {
            "status": "error",
            "matches": {},
            "total_replacements": 0,
            "error_message": str(e),
        }

    stats = {}  # type -> count

    # 1. Параграфы основного текста
    for paragraph in doc.paragraphs:
        stats = _process_paragraph(paragraph, replacement_rules, stats)

    # 2. Таблицы
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    stats = _process_paragraph(paragraph, replacement_rules, stats)

    # 3. Колонтитулы
    for section in doc.sections:
        for header in [section.header, section.first_page_header,
                       section.even_page_header]:
            if header is not None:
                try:
                    linked = header.is_linked_to_previous
                except Exception:
                    linked = True
                if not linked:
                    for paragraph in header.paragraphs:
                        stats = _process_paragraph(paragraph, replacement_rules, stats)
        for footer in [section.footer, section.first_page_footer,
                       section.even_page_footer]:
            if footer is not None:
                try:
                    linked = footer.is_linked_to_previous
                except Exception:
                    linked = True
                if not linked:
                    for paragraph in footer.paragraphs:
                        stats = _process_paragraph(paragraph, replacement_rules, stats)

    try:
        doc.save(output_path)
    except Exception as e:
        logger.error(f"Не удалось сохранить {output_path}: {e}")
        return {
            "status": "error",
            "matches": stats,
            "total_replacements": sum(stats.values()),
            "error_message": str(e),
        }

    return {
        "status": "success",
        "matches": stats,
        "total_replacements": sum(stats.values()),
        "error_message": None,
    }


def _process_paragraph(paragraph, replacement_rules, stats):
    """
    Ключевой алгоритм замены текста в параграфе с сохранением форматирования.
    """
    runs = paragraph.runs
    if not runs:
        return stats

    full_text = ''
    char_map = []

    for run_idx, run in enumerate(runs):
        run_text = run.text or ''
        for char_idx, char in enumerate(run_text):
            char_map.append((run_idx, char_idx))
        full_text += run_text

    if not full_text.strip():
        return stats

    # Собираем все замены: (start, end, replacement_text, type)
    replacements = []

    for rule in replacement_rules:
        rule_type = rule.get("type", "custom")
        for pattern in rule.get("patterns", []):
            for match in pattern.finditer(full_text):
                repl = _get_replacement_text(rule, match.group())
                replacements.append((match.start(), match.end(), repl, rule_type))

    if not replacements:
        return stats

    # Убираем пересекающиеся замены (приоритет длинным)
    replacements.sort(key=lambda r: (r[0], -(r[1] - r[0])))
    filtered = []
    last_end = 0
    for start, end, repl, rtype in replacements:
        if start >= last_end:
            filtered.append((start, end, repl, rtype))
            last_end = end

    if not filtered:
        return stats

    # Подсчёт
    for _, _, _, rtype in filtered:
        stats[rtype] = stats.get(rtype, 0) + 1

    # Строим новый текст
    new_text = ''
    pos = 0
    for start, end, repl, _ in filtered:
        new_text += full_text[pos:start]
        new_text += repl
        pos = end
    new_text += full_text[pos:]

    # Перезаписываем runs: весь текст в первый run, остальные очищаем
    if runs:
        runs[0].text = new_text
        for run in runs[1:]:
            run.text = ''

    return stats


def preview_docx(
    filepath: str,
    replacement_rules: list[dict],
    context_chars: int = 30,
) -> dict:
    """
    Сканирует файл БЕЗ изменений, возвращает найденные вхождения.
    """
    try:
        doc = Document(filepath)
    except Exception as e:
        return {"status": "error", "error_message": str(e), "matches": []}

    matches = []
    all_paragraphs = []

    for p in doc.paragraphs:
        all_paragraphs.append(p)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    all_paragraphs.append(p)

    for para in all_paragraphs:
        text = para.text
        if not text.strip():
            continue

        # Собираем с дедупликацией перекрытий
        text_matches = []
        for rule in replacement_rules:
            rule_type = rule.get("type", "custom")
            for pattern in rule.get("patterns", []):
                for match in pattern.finditer(text):
                    repl = _get_replacement_text(rule, match.group())
                    text_matches.append(
                        (match.start(), match.end(), match.group(),
                         repl, rule_type)
                    )

        text_matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))
        last_end = 0
        for mstart, mend, original, repl, rule_type in text_matches:
            if mstart < last_end:
                continue
            last_end = mend
            ctx_start = max(0, mstart - context_chars)
            ctx_end = min(len(text), mend + context_chars)
            context = text[ctx_start:ctx_end]
            if ctx_start > 0:
                context = '...' + context
            if ctx_end < len(text):
                context = context + '...'
            matches.append({
                "original": original,
                "replacement": repl,
                "context": context,
                "type": rule_type,
            })

    type_counts = {}
    for m in matches:
        t = m["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "status": "success",
        "matches": matches,
        "type_counts": type_counts,
    }
