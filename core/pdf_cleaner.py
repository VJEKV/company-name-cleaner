"""
Обработка .pdf файлов: два режима замены.

Режим 1 — Текстовая заглушка:
  Находим текст → redact с текстом замены.

Режим 2 — Графический штамп:
  Находим текст → redact (закрашиваем) → поверх вставляем PNG-штамп.
"""

import re
import logging
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger('CompanyCleaner')

BUILTIN_STAMPS = {
    "ромашка": "assets/stamps/daisy.png",
    "звёздочка": "assets/stamps/star.png",
    "замок": "assets/stamps/lock.png",
    "конфиденциально": "assets/stamps/confidential.png",
    "чёрная плашка": None,  # Генерируется программно
}


def clean_pdf_text_mode(
    filepath: str,
    output_path: str,
    company_patterns: list[re.Pattern],
    surname_patterns: list[re.Pattern],
    company_replacement: str,
    surname_mapper,
) -> dict:
    """
    Режим 1: Заменяем текст на текстовую заглушку через redaction.
    """
    try:
        doc = fitz.open(filepath)
    except Exception as e:
        logger.error(f"Не удалось открыть PDF {filepath}: {e}")
        return {
            "status": "error",
            "company_matches": 0,
            "surname_matches": 0,
            "pages_affected": [],
            "error_message": str(e),
        }

    if doc.is_encrypted:
        doc.close()
        return {
            "status": "error",
            "company_matches": 0,
            "surname_matches": 0,
            "pages_affected": [],
            "error_message": "Файл защищён паролем",
        }

    stats = {"company": 0, "surname": 0, "pages_affected": []}
    has_text = False

    for page_num, page in enumerate(doc):
        page_text = page.get_text()
        if page_text.strip():
            has_text = True

        page_changed = False

        # Замена названия компании
        for pattern in company_patterns:
            for match in pattern.finditer(page_text):
                matched_text = match.group()
                rects = page.search_for(matched_text)
                for rect in rects:
                    page.add_redact_annot(
                        rect,
                        text=company_replacement,
                        fill=(1, 1, 1),
                        text_color=(0, 0, 0),
                        fontsize=0,
                        cross_out=False,
                    )
                    stats["company"] += 1
                    page_changed = True

        # Замена фамилий
        for pattern in surname_patterns:
            for match in pattern.finditer(page_text):
                matched_text = match.group()
                replacement = surname_mapper.get_replacement(matched_text)
                rects = page.search_for(matched_text)
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

    if not has_text:
        doc.close()
        return {
            "status": "warning",
            "company_matches": 0,
            "surname_matches": 0,
            "pages_affected": [],
            "error_message": "Файл может быть сканом. Текстовый слой не обнаружен.",
        }

    try:
        doc.save(output_path, garbage=4, deflate=True)
    except Exception as e:
        logger.error(f"Не удалось сохранить PDF {output_path}: {e}")
        doc.close()
        return {
            "status": "error",
            "company_matches": stats["company"],
            "surname_matches": stats["surname"],
            "pages_affected": stats["pages_affected"],
            "error_message": str(e),
        }

    doc.close()
    return {
        "status": "success",
        "company_matches": stats["company"],
        "surname_matches": stats["surname"],
        "pages_affected": stats["pages_affected"],
        "error_message": None,
    }


def clean_pdf_stamp_mode(
    filepath: str,
    output_path: str,
    company_patterns: list[re.Pattern],
    surname_patterns: list[re.Pattern],
    stamp_path: str | None = None,
    stamp_type: str = "чёрная плашка",
) -> dict:
    """
    Режим 2: Закрашиваем область и ставим штамп поверх.
    """
    try:
        doc = fitz.open(filepath)
    except Exception as e:
        logger.error(f"Не удалось открыть PDF {filepath}: {e}")
        return {
            "status": "error",
            "company_matches": 0,
            "surname_matches": 0,
            "pages_affected": [],
            "error_message": str(e),
        }

    if doc.is_encrypted:
        doc.close()
        return {
            "status": "error",
            "company_matches": 0,
            "surname_matches": 0,
            "pages_affected": [],
            "error_message": "Файл защищён паролем",
        }

    stats = {"company": 0, "surname": 0, "pages_affected": []}

    # Загружаем штамп
    stamp_image = None
    if stamp_path and Path(stamp_path).exists():
        stamp_image = open(stamp_path, "rb").read()

    for page_num, page in enumerate(doc):
        page_text = page.get_text()
        rects_to_stamp = []
        page_changed = False

        all_patterns = list(company_patterns) + list(surname_patterns)
        company_set = set(id(p) for p in company_patterns)

        for pattern in all_patterns:
            for match in pattern.finditer(page_text):
                matched_text = match.group()
                found_rects = page.search_for(matched_text)
                for rect in found_rects:
                    page.add_redact_annot(rect, text="", fill=(1, 1, 1))
                    rects_to_stamp.append(rect)
                    page_changed = True
                    if id(pattern) in company_set:
                        stats["company"] += 1
                    else:
                        stats["surname"] += 1

        if page_changed:
            page.apply_redactions()

            for rect in rects_to_stamp:
                if stamp_type == "чёрная плашка" or stamp_image is None:
                    shape = page.new_shape()
                    shape.draw_rect(rect)
                    shape.finish(color=(0, 0, 0), fill=(0, 0, 0))
                    shape.commit()
                else:
                    page.insert_image(
                        rect, stream=stamp_image, keep_proportion=True
                    )

            stats["pages_affected"].append(page_num + 1)

    try:
        doc.save(output_path, garbage=4, deflate=True)
    except Exception as e:
        doc.close()
        return {
            "status": "error",
            "company_matches": stats["company"],
            "surname_matches": stats["surname"],
            "pages_affected": stats["pages_affected"],
            "error_message": str(e),
        }

    doc.close()
    return {
        "status": "success",
        "company_matches": stats["company"],
        "surname_matches": stats["surname"],
        "pages_affected": stats["pages_affected"],
        "error_message": None,
    }


def preview_pdf(
    filepath: str,
    company_patterns: list[re.Pattern],
    surname_patterns: list[re.Pattern],
    surname_mapper=None,
    context_chars: int = 30,
) -> dict:
    """Сканирует PDF без изменений, возвращает найденные вхождения."""
    try:
        doc = fitz.open(filepath)
    except Exception as e:
        return {"status": "error", "error_message": str(e), "matches": []}

    matches = []

    for page_num, page in enumerate(doc):
        text = page.get_text()
        if not text.strip():
            continue

        for pattern in company_patterns:
            for match in pattern.finditer(text):
                start = max(0, match.start() - context_chars)
                end = min(len(text), match.end() + context_chars)
                context = text[start:end].replace('\n', ' ')
                if start > 0:
                    context = '...' + context
                if end < len(text):
                    context = context + '...'
                matches.append({
                    "original": match.group(),
                    "replacement": "[ЗАГЛУШКА]",
                    "context": context,
                    "type": "company",
                    "page": page_num + 1,
                })

        for pattern in surname_patterns:
            for match in pattern.finditer(text):
                start = max(0, match.start() - context_chars)
                end = min(len(text), match.end() + context_chars)
                context = text[start:end].replace('\n', ' ')
                if start > 0:
                    context = '...' + context
                if end < len(text):
                    context = context + '...'
                repl = surname_mapper.get_replacement(match.group()) \
                    if surname_mapper else '[ФИО]'
                matches.append({
                    "original": match.group(),
                    "replacement": repl,
                    "context": context,
                    "type": "surname",
                    "page": page_num + 1,
                })

    doc.close()
    return {
        "status": "success",
        "matches": matches,
        "company_count": sum(1 for m in matches if m["type"] == "company"),
        "surname_count": sum(1 for m in matches if m["type"] == "surname"),
    }
