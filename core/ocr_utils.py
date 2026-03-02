"""
OCR-утилиты для обработки отсканированных PDF-страниц.
Использует pytesseract (Tesseract OCR) для извлечения текста с координатами.

Tesseract — внешняя зависимость. При отсутствии модуль gracefully деградирует:
is_tesseract_available() вернёт False, остальные функции не вызываются.
"""

import os
import logging
import shutil
from io import BytesIO

import fitz  # PyMuPDF

logger = logging.getLogger('CompanyCleaner')

_pytesseract = None
_tesseract_available = None


def is_tesseract_available() -> bool:
    """Проверяет доступность pytesseract и бинарника Tesseract."""
    global _pytesseract, _tesseract_available
    if _tesseract_available is not None:
        return _tesseract_available

    try:
        import pytesseract as pt
        _pytesseract = pt
    except ImportError:
        _tesseract_available = False
        return False

    # Проверяем бинарник в PATH
    if shutil.which("tesseract"):
        _tesseract_available = True
        return True

    # Windows fallback
    win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(win_path):
        pt.pytesseract.tesseract_cmd = win_path
        _tesseract_available = True
        return True

    _tesseract_available = False
    return False


def is_page_scanned(page, min_chars: int = 10) -> bool:
    """
    Определяет, является ли страница сканом (нет текстового слоя).
    Страница считается сканом если get_text() даёт менее min_chars символов.
    """
    text = page.get_text()
    return len(text.strip()) < min_chars


def page_to_pil_image(page, dpi: int = 300):
    """
    Рендерит fitz.Page в PIL Image с заданным DPI.
    300 DPI — оптимальный баланс качества и скорости для OCR.
    """
    from PIL import Image

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix)
    img = Image.open(BytesIO(pixmap.tobytes("png")))
    return img


def ocr_page(page, dpi: int = 300, lang: str = "rus+eng") -> list[dict]:
    """
    Запускает OCR на странице PDF и возвращает слова с координатами в PDF-пространстве.

    Возвращает список:
        [{"text": str, "bbox": fitz.Rect, "conf": int}, ...]
    """
    if not is_tesseract_available():
        raise RuntimeError("Tesseract OCR недоступен")

    img = page_to_pil_image(page, dpi=dpi)

    data = _pytesseract.image_to_data(
        img, lang=lang, output_type=_pytesseract.Output.DICT
    )

    zoom = dpi / 72.0
    words = []

    n = len(data['text'])
    for i in range(n):
        text = data['text'][i].strip()
        conf = int(data['conf'][i]) if str(data['conf'][i]) != '-1' else 0
        if not text or conf < 20:
            continue

        # Координаты в пикселях изображения
        left = data['left'][i]
        top = data['top'][i]
        width = data['width'][i]
        height = data['height'][i]

        # Пересчёт в координаты PDF (точки, 1/72 дюйма)
        pdf_x0 = left / zoom
        pdf_y0 = top / zoom
        pdf_x1 = (left + width) / zoom
        pdf_y1 = (top + height) / zoom

        words.append({
            "text": text,
            "bbox": fitz.Rect(pdf_x0, pdf_y0, pdf_x1, pdf_y1),
            "conf": conf,
        })

    return words


def _group_words_by_line(ocr_words: list[dict]) -> list[list[dict]]:
    """
    Группирует OCR-слова по строкам (близкий Y) и сортирует внутри строки по X.
    Возвращает список строк, каждая строка — список слов отсортированных по X.
    """
    if not ocr_words:
        return []

    # Сортируем по Y для группировки
    sorted_by_y = sorted(ocr_words, key=lambda w: w["bbox"].y0)

    lines = []
    current_line = [sorted_by_y[0]]
    current_y = sorted_by_y[0]["bbox"].y0
    line_height = max(sorted_by_y[0]["bbox"].height, 1)

    for w in sorted_by_y[1:]:
        if abs(w["bbox"].y0 - current_y) > line_height * 0.6:
            # Сортируем слова в строке по X
            current_line.sort(key=lambda w: w["bbox"].x0)
            lines.append(current_line)
            current_line = [w]
            current_y = w["bbox"].y0
            line_height = max(w["bbox"].height, 1)
        else:
            current_line.append(w)

    if current_line:
        current_line.sort(key=lambda w: w["bbox"].x0)
        lines.append(current_line)

    return lines


def reconstruct_text_from_ocr(ocr_words: list[dict]) -> str:
    """
    Собирает текст из OCR-слов с сохранением строк.
    Слова на одной строке объединяются пробелами, строки — переносами.
    """
    if not ocr_words:
        return ""

    lines = _group_words_by_line(ocr_words)
    return "\n".join(
        " ".join(w["text"] for w in line) for line in lines
    )


def find_ocr_word_rects(
    ocr_words: list[dict], matched_text: str
) -> list[fitz.Rect]:
    """
    Находит прямоугольники OCR-слов, покрывающие matched_text.
    Группирует слова по строкам, ищет sliding window внутри каждой строки.
    Для многострочных совпадений ищет через соседние строки.
    Возвращает список fitz.Rect.
    """
    if not ocr_words or not matched_text:
        return []

    lines = _group_words_by_line(ocr_words)
    target = matched_text.strip().lower()
    target_nospace = target.replace(" ", "")
    results = []

    # Собираем все слова в порядке чтения (строка за строкой, слева направо)
    ordered_words = []
    for line in lines:
        ordered_words.extend(line)

    for start_idx in range(len(ordered_words)):
        accumulated = ""
        rects = []

        for end_idx in range(start_idx, min(start_idx + 15, len(ordered_words))):
            word = ordered_words[end_idx]

            if accumulated:
                accumulated += " "
            accumulated += word["text"]
            rects.append(word["bbox"])

            acc_lower = accumulated.lower()
            acc_nospace = accumulated.replace(" ", "").lower()

            if acc_lower == target or acc_nospace == target_nospace:
                # Точное совпадение — лучший вариант
                x0 = min(r.x0 for r in rects)
                y0 = min(r.y0 for r in rects)
                x1 = max(r.x1 for r in rects)
                y1 = max(r.y1 for r in rects)
                results.append(fitz.Rect(x0, y0, x1, y1))
                break

            if acc_lower.startswith(target) or acc_nospace.startswith(target_nospace):
                # Совпадение в начале — тоже берём
                x0 = min(r.x0 for r in rects)
                y0 = min(r.y0 for r in rects)
                x1 = max(r.x1 for r in rects)
                y1 = max(r.y1 for r in rects)
                results.append(fitz.Rect(x0, y0, x1, y1))
                break

            if len(accumulated) > len(target) * 3:
                break

    return results
