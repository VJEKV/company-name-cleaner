"""
Модуль деанонимизации.
Сохраняет маппинг замен при анонимизации и выполняет обратную замену.
Маппинг сохраняется в .titan_map.json рядом с анонимизированным файлом.
"""

import json
import re
from pathlib import Path
from typing import Optional

from core.docx_cleaner import clean_docx
from core.pdf_cleaner import clean_pdf_text_mode
from core.xlsx_cleaner import clean_xlsx


class AnonymizationMap:
    """Карта анонимизации — хранит все замены original → pseudonym."""

    def __init__(self):
        self.mappings: dict[str, str] = {}  # original_lower → pseudonym
        self.originals: dict[str, str] = {}  # original_lower → original (с регистром)

    def add(self, original: str, pseudonym: str):
        """Добавляет пару замены."""
        key = original.strip().lower()
        if key and pseudonym:
            self.mappings[key] = pseudonym
            self.originals[key] = original.strip()

    def save(self, output_path: str):
        """Сохраняет маппинг в .titan_map.json рядом с выходным файлом."""
        p = Path(output_path)
        map_path = p.parent / f"{p.stem}.titan_map.json"
        data = {
            "version": 1,
            "source_file": p.name,
            "mappings": [
                {
                    "original": self.originals[k],
                    "pseudonym": self.mappings[k],
                }
                for k in self.mappings
            ],
        }
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(map_path)

    @classmethod
    def load(cls, map_path: str) -> "AnonymizationMap":
        """Загружает маппинг из .titan_map.json."""
        with open(map_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        amap = cls()
        for item in data.get("mappings", []):
            amap.add(item["original"], item["pseudonym"])
        return amap

    def get_reverse_rules(self) -> list[dict]:
        """Строит правила обратной замены (pseudonym → original).
        Сортирует от длинных к коротким для корректной замены."""
        rules = []
        seen = set()
        for key in self.mappings:
            pseudonym = self.mappings[key]
            original = self.originals[key]
            if pseudonym in seen:
                continue
            seen.add(pseudonym)
            # Экранируем спецсимволы regex
            pattern = re.compile(re.escape(pseudonym), re.IGNORECASE)
            rules.append({
                "patterns": [pattern],
                "replacement": original,
                "type": "deanonymize",
            })
        # Длинные замены первыми
        rules.sort(key=lambda r: len(r["patterns"][0].pattern), reverse=True)
        return rules


def deanonymize_file(
    filepath: str,
    map_path: str,
    output_path: Optional[str] = None,
) -> dict:
    """
    Деанонимизирует файл, используя маппинг из .titan_map.json.

    Args:
        filepath: путь к анонимизированному (или изменённому ИИ) файлу
        map_path: путь к .titan_map.json
        output_path: путь для результата (если None — рядом с оригиналом)

    Returns:
        dict с результатом: {"status", "matches", "output_path", "error_message"}
    """
    amap = AnonymizationMap.load(map_path)
    reverse_rules = amap.get_reverse_rules()

    if not reverse_rules:
        return {
            "status": "warning",
            "matches": {},
            "output_path": "",
            "error_message": "Маппинг пуст — нечего деанонимизировать.",
        }

    ext = Path(filepath).suffix.lower()

    if output_path is None:
        p = Path(filepath)
        output_path = str(p.parent / f"{p.stem}_restored{ext}")

    try:
        if ext == ".docx":
            result = clean_docx(filepath, output_path, reverse_rules)
        elif ext == ".pdf":
            result = clean_pdf_text_mode(filepath, output_path, reverse_rules)
        elif ext in (".xlsx", ".xls"):
            result = clean_xlsx(filepath, output_path, reverse_rules)
        else:
            return {
                "status": "error",
                "matches": {},
                "output_path": "",
                "error_message": f"Неподдерживаемый формат: {ext}",
            }

        result["output_path"] = output_path
        return result

    except Exception as e:
        return {
            "status": "error",
            "matches": {},
            "output_path": "",
            "error_message": str(e),
        }
