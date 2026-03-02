"""
Обработка .pdf файлов: два режима замены.

Режим 1 — Текстовая заглушка:
  Находим текст → blank redact → overlay текст с кириллическим шрифтом.

Режим 2 — Графический штамп:
  Находим текст → redact (закрашиваем) → поверх вставляем PNG-штамп.

OCR fallback: если страница не содержит текстового слоя и ocr_enabled=True,
  используется Tesseract OCR для распознавания текста и получения координат.

replacement_rules — универсальный формат:
  [
    {"patterns": [...], "replacement": "текст", "type": "company"},
    {"patterns": [...], "mapper": ReplacementMapper, "type": "surnames"},
    ...
  ]
"""

import os
import re
import unicodedata
import logging
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger('CompanyCleaner')

BUILTIN_STAMPS = {
    "ромашка": "assets/stamps/daisy.png",
    "звёздочка": "assets/stamps/star.png",
    "замок": "assets/stamps/lock.png",
    "конфиденциально": "assets/stamps/confidential.png",
    "чёрная плашка": None,
}

# Пути к кириллическим шрифтам (проверяются по порядку)
_CYRILLIC_FONT_PATHS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    'C:/Windows/Fonts/arial.ttf',
    'C:/Windows/Fonts/calibri.ttf',
]

_cached_font = None


def _get_cyrillic_font():
    """Возвращает fitz.Font с поддержкой кириллицы."""
    global _cached_font
    if _cached_font is not None:
        return _cached_font

    for path in _CYRILLIC_FONT_PATHS:
        if os.path.exists(path):
            try:
                font = fitz.Font(fontfile=path)
                if font.has_glyph(ord('А')):
                    _cached_font = font
                    return font
            except Exception:
                continue

    try:
        font = fitz.Font("china-s")
        _cached_font = font
        return font
    except Exception:
        pass

    _cached_font = fitz.Font("helv")
    return _cached_font


def _normalize_text(text: str) -> str:
    """Нормализует текст: убирает лишние пробелы, Unicode-нормализация."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _search_text_on_page(page, text: str) -> list:
    """
    Ищет текст на странице с fallback-стратегиями:
    1. Прямой поиск search_for()
    2. Поиск с нормализованным текстом
    3. Пословный поиск
    """
    rects = page.search_for(text)
    if rects:
        return rects

    normalized = _normalize_text(text)
    if normalized != text:
        rects = page.search_for(normalized)
        if rects:
            return rects

    words = normalized.split()
    if len(words) <= 1:
        return []

    word_rects = []
    for w in words:
        wr = page.search_for(w)
        if wr:
            word_rects.append(wr[0])
        else:
            return []

    if not word_rects:
        return []

    x0 = min(r.x0 for r in word_rects)
    y0 = min(r.y0 for r in word_rects)
    x1 = max(r.x1 for r in word_rects)
    y1 = max(r.y1 for r in word_rects)
    return [fitz.Rect(x0, y0, x1, y1)]


def _get_replacement_text(rule: dict, matched_text: str) -> str:
    """Получает текст замены из правила."""
    if "mapper" in rule and rule["mapper"] is not None:
        return rule["mapper"].get_replacement(matched_text)
    return rule.get("replacement", "[ЗАГЛУШКА]")


def _open_and_check(filepath: str) -> tuple:
    """Открывает PDF и проверяет на ошибки."""
    try:
        doc = fitz.open(filepath)
    except Exception as e:
        logger.error(f"Не удалось открыть PDF {filepath}: {e}")
        return None, {
            "status": "error",
            "matches": {},
            "pages_affected": [],
            "ocr_pages": [],
            "scanned_pages": [],
            "error_message": str(e),
        }

    if doc.is_encrypted:
        doc.close()
        return None, {
            "status": "error",
            "matches": {},
            "pages_affected": [],
            "ocr_pages": [],
            "scanned_pages": [],
            "error_message": "Файл защищён паролем",
        }

    return doc, None


def _is_page_scanned(page, min_chars: int = 10) -> bool:
    """Проверяет, является ли страница сканом."""
    text = page.get_text()
    return len(text.strip()) < min_chars


def _get_page_text_and_rects(page, replacement_rules, ocr_enabled, ocr_dpi, ocr_lang):
    """
    Извлекает текст страницы и определяет способ поиска прямоугольников.

    Возвращает (page_text, use_ocr, ocr_words):
      - page_text: текст для regex
      - use_ocr: True если нужны OCR-координаты
      - ocr_words: список OCR-слов (если use_ocr) или None
    """
    page_text = page.get_text()
    is_scan = len(page_text.strip()) < 10

    if not is_scan:
        return page_text, False, None

    if not ocr_enabled:
        return page_text, False, None

    # OCR fallback
    try:
        from core.ocr_utils import ocr_page, reconstruct_text_from_ocr
        ocr_words = ocr_page(page, dpi=ocr_dpi, lang=ocr_lang)
        page_text = reconstruct_text_from_ocr(ocr_words)
        return page_text, True, ocr_words
    except Exception as e:
        logger.warning(f"OCR ошибка: {e}")
        return "", False, None


def _find_matches_deduplicated(page_text, replacement_rules):
    """
    Находит все regex-совпадения в тексте с дедупликацией перекрытий.
    Возвращает [(matched_text, replacement, rule_type), ...]
    """
    text_matches = []
    for rule in replacement_rules:
        rule_type = rule.get("type", "custom")
        for pattern in rule.get("patterns", []):
            for match in pattern.finditer(page_text):
                replacement = _get_replacement_text(rule, match.group())
                text_matches.append(
                    (match.start(), match.end(), match.group(),
                     replacement, rule_type)
                )

    if not text_matches:
        return []

    text_matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))
    filtered = []
    last_end = 0
    for start, end, matched, repl, rtype in text_matches:
        if start >= last_end:
            filtered.append((matched, repl, rtype))
            last_end = end

    return filtered


def _find_rects_for_matches(page, filtered, use_ocr, ocr_words):
    """
    Находит прямоугольники для совпадений.
    Если use_ocr — через OCR-координаты, иначе через page.search_for().
    """
    redactions = []
    if use_ocr and ocr_words:
        from core.ocr_utils import find_ocr_word_rects
        for matched, repl, rtype in filtered:
            rects = find_ocr_word_rects(ocr_words, matched)
            for rect in rects:
                redactions.append((rect, repl, rtype))
    else:
        for matched, repl, rtype in filtered:
            rects = _search_text_on_page(page, matched)
            for rect in rects:
                redactions.append((rect, repl, rtype))

    return redactions


# ── Режим 1: Текстовая заглушка ────────────────────────────


def clean_pdf_text_mode(
    filepath: str,
    output_path: str,
    replacement_rules: list[dict],
    ocr_enabled: bool = False,
    ocr_dpi: int = 300,
    ocr_lang: str = "rus+eng",
) -> dict:
    """
    Режим 1: Blank redact + overlay текст кириллическим шрифтом.
    При ocr_enabled=True сканированные страницы обрабатываются через Tesseract.
    """
    doc, error = _open_and_check(filepath)
    if error:
        return error

    font = _get_cyrillic_font()
    stats = {}
    pages_affected = []
    ocr_pages = []
    scanned_pages = []
    has_text = False

    for page_num, page in enumerate(doc):
        page_text, use_ocr, ocr_words = _get_page_text_and_rects(
            page, replacement_rules, ocr_enabled, ocr_dpi, ocr_lang
        )

        if not page_text.strip():
            if _is_page_scanned(page):
                scanned_pages.append(page_num + 1)
            continue

        has_text = True
        if use_ocr:
            ocr_pages.append(page_num + 1)

        # Фаза 1: regex + дедупликация
        filtered = _find_matches_deduplicated(page_text, replacement_rules)
        if not filtered:
            continue

        # Фаза 2: прямоугольники
        redactions = _find_rects_for_matches(
            page, filtered, use_ocr, ocr_words
        )
        if not redactions:
            continue

        # Фаза 3: blank redact
        for rect, _, _ in redactions:
            page.add_redact_annot(rect, text="", fill=(1, 1, 1))

        page.apply_redactions()

        # Фаза 4: overlay кириллический текст
        for rect, replacement, rule_type in redactions:
            fontsize = rect.height * 0.72
            fontsize = max(6, min(20, fontsize))
            tw = fitz.TextWriter(page.rect)
            tw.append(
                (rect.x0, rect.y1 - rect.height * 0.2),
                replacement, font=font, fontsize=fontsize
            )
            tw.write_text(page)
            stats[rule_type] = stats.get(rule_type, 0) + 1

        pages_affected.append(page_num + 1)

    if not has_text and not ocr_pages:
        doc.close()
        msg = "Файл может быть сканом. Текстовый слой не обнаружен."
        if not ocr_enabled:
            msg += " Включите OCR для обработки сканов."
        return {
            "status": "warning",
            "matches": {},
            "pages_affected": [],
            "ocr_pages": [],
            "scanned_pages": scanned_pages,
            "error_message": msg,
        }

    try:
        doc.save(output_path, garbage=4, deflate=True)
    except Exception as e:
        logger.error(f"Не удалось сохранить PDF {output_path}: {e}")
        doc.close()
        return {
            "status": "error",
            "matches": stats,
            "pages_affected": pages_affected,
            "ocr_pages": ocr_pages,
            "scanned_pages": scanned_pages,
            "error_message": str(e),
        }

    doc.close()
    return {
        "status": "success",
        "matches": stats,
        "pages_affected": pages_affected,
        "ocr_pages": ocr_pages,
        "scanned_pages": scanned_pages,
        "error_message": None,
    }


# ── Режим 2: Графический штамп ─────────────────────────────


def clean_pdf_stamp_mode(
    filepath: str,
    output_path: str,
    replacement_rules: list[dict],
    stamp_path: str | None = None,
    stamp_type: str = "чёрная плашка",
    ocr_enabled: bool = False,
    ocr_dpi: int = 300,
    ocr_lang: str = "rus+eng",
) -> dict:
    """Режим 2: Закрашиваем область и ставим штамп поверх."""
    doc, error = _open_and_check(filepath)
    if error:
        return error

    stats = {}
    pages_affected = []
    ocr_pages = []
    scanned_pages = []

    stamp_image = None
    if stamp_path and Path(stamp_path).exists():
        stamp_image = open(stamp_path, "rb").read()

    for page_num, page in enumerate(doc):
        page_text, use_ocr, ocr_words = _get_page_text_and_rects(
            page, replacement_rules, ocr_enabled, ocr_dpi, ocr_lang
        )

        if not page_text.strip():
            if _is_page_scanned(page):
                scanned_pages.append(page_num + 1)
            continue

        if use_ocr:
            ocr_pages.append(page_num + 1)

        # Regex + дедупликация
        text_matches = []
        for rule in replacement_rules:
            rule_type = rule.get("type", "custom")
            for pattern in rule.get("patterns", []):
                for match in pattern.finditer(page_text):
                    text_matches.append(
                        (match.start(), match.end(), match.group(), rule_type)
                    )

        text_matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))
        filtered = []
        last_end = 0
        for start, end, matched, rtype in text_matches:
            if start >= last_end:
                filtered.append((matched, rtype))
                last_end = end

        # Прямоугольники
        rects_to_stamp = []
        page_changed = False

        if use_ocr and ocr_words:
            from core.ocr_utils import find_ocr_word_rects
            for matched, rtype in filtered:
                found_rects = find_ocr_word_rects(ocr_words, matched)
                for rect in found_rects:
                    page.add_redact_annot(rect, text="", fill=(1, 1, 1))
                    rects_to_stamp.append(rect)
                    page_changed = True
                    stats[rtype] = stats.get(rtype, 0) + 1
        else:
            for matched, rtype in filtered:
                found_rects = _search_text_on_page(page, matched)
                for rect in found_rects:
                    page.add_redact_annot(rect, text="", fill=(1, 1, 1))
                    rects_to_stamp.append(rect)
                    page_changed = True
                    stats[rtype] = stats.get(rtype, 0) + 1

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

            pages_affected.append(page_num + 1)

    try:
        doc.save(output_path, garbage=4, deflate=True)
    except Exception as e:
        doc.close()
        return {
            "status": "error",
            "matches": stats,
            "pages_affected": pages_affected,
            "ocr_pages": ocr_pages,
            "scanned_pages": scanned_pages,
            "error_message": str(e),
        }

    doc.close()
    return {
        "status": "success",
        "matches": stats,
        "pages_affected": pages_affected,
        "ocr_pages": ocr_pages,
        "scanned_pages": scanned_pages,
        "error_message": None,
    }


# ── Предпросмотр ───────────────────────────────────────────


def preview_pdf(
    filepath: str,
    replacement_rules: list[dict],
    context_chars: int = 30,
    ocr_enabled: bool = False,
    ocr_dpi: int = 300,
    ocr_lang: str = "rus+eng",
) -> dict:
    """Сканирует PDF без изменений, возвращает найденные вхождения."""
    try:
        doc = fitz.open(filepath)
    except Exception as e:
        return {"status": "error", "error_message": str(e), "matches": []}

    matches = []
    ocr_pages = []

    for page_num, page in enumerate(doc):
        text, use_ocr, ocr_words = _get_page_text_and_rects(
            page, replacement_rules, ocr_enabled, ocr_dpi, ocr_lang
        )

        if not text.strip():
            continue

        if use_ocr:
            ocr_pages.append(page_num + 1)

        # Дедупликация
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
            context = text[ctx_start:ctx_end].replace('\n', ' ')
            if ctx_start > 0:
                context = '...' + context
            if ctx_end < len(text):
                context = context + '...'

            ocr_tag = " [OCR]" if use_ocr else ""
            matches.append({
                "original": original,
                "replacement": repl,
                "context": context,
                "type": rule_type,
                "page": page_num + 1,
                "ocr": use_ocr,
            })

    doc.close()

    type_counts = {}
    for m in matches:
        t = m["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "status": "success",
        "matches": matches,
        "type_counts": type_counts,
        "ocr_pages": ocr_pages,
    }
