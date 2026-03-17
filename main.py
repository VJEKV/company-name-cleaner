"""
Titan Cleaner v4.0 — портативное GUI-приложение.
Анонимизация и деанонимизация документов (.docx, .pdf, .xlsx).
Замена названия компании, фамилий, городов и произвольных полей
на английские псевдонимы с возможностью обратной замены.
UI на CustomTkinter (тёмная тема).
"""

import csv
import json
import logging
import os
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

# Логирование ошибок запуска в файл (для --windowed .exe)
def _log_startup_error(msg):
    """Записывает ошибку запуска в файл рядом с .exe."""
    try:
        if getattr(sys, 'frozen', False):
            log_path = Path(sys.executable).parent / 'titan_error.log'
        else:
            log_path = Path(__file__).parent / 'titan_error.log'
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"{msg}\n")
    except Exception:
        pass

try:
    import customtkinter as ctk
except ImportError as e:
    _log_startup_error(f"CustomTkinter import error: {e}\n{traceback.format_exc()}")
    # Показываем ошибку через базовый tkinter
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Ошибка запуска",
            f"Не удалось загрузить CustomTkinter:\n{e}\n\n"
            "Проверьте файл titan_error.log"
        )
    except Exception:
        pass
    sys.exit(1)

from core.patterns import build_company_patterns, build_city_patterns, build_custom_patterns
from core.surnames import SurnamePattern
from core.replacements import (
    get_company_replacement_options,
    get_surname_replacement_options,
    get_city_replacement_options,
    get_signatory_replacement_options,
    get_generic_replacement_options,
    ReplacementMapper,
)
from core.english_pseudonyms import EnglishPseudonymGenerator
from core.deanonymizer import AnonymizationMap, deanonymize_file
from core.docx_cleaner import clean_docx, preview_docx
from core.pdf_cleaner import (
    clean_pdf_text_mode,
    clean_pdf_stamp_mode,
    preview_pdf,
)
from core.xlsx_cleaner import (
    clean_xlsx,
    preview_xlsx,
    extract_text_xlsx,
    is_openpyxl_available,
)
from core.utils import (
    setup_logging,
    load_config,
    save_config,
    get_assets_dir,
    is_valid_file,
    ensure_output_dir,
    format_file_size,
)
from core.auto_detect import (
    auto_detect_all,
    auto_detect_in_file,
    DetectedEntity,
    ENTITY_TYPE_NAMES,
    get_type_name,
    _reset_counters,
    _replacement_cache,
)

APP_TITLE = "Titan Cleaner v4.0"
WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 900

# Цветовая палитра
COLORS = {
    "bg": "#1a1a2e",
    "surface": "#16213e",
    "card": "#0f3460",
    "accent": "#e94560",
    "accent_hover": "#c73852",
    "success": "#00b894",
    "warning": "#fdcb6e",
    "error": "#d63031",
    "info": "#74b9ff",
    "text": "#eaf0f6",
    "text_secondary": "#a4b0be",
    "border": "#2d3748",
    "input_bg": "#1e2d45",
    "button_primary": "#e94560",
    "button_secondary": "#0f3460",
    "button_success": "#00b894",
    "button_danger": "#d63031",
}

logger = setup_logging()

# Настройка CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Типы полей для замены
FIELD_TYPES = {
    "Город": {
        "hint_search": "Москва",
        "hint_replace": "London",
        "options_func": get_city_replacement_options,
        "multiline": False,
    },
    "Организация": {
        "hint_search": "ЛУКОЙЛ",
        "hint_replace": "Northgate Industries Ltd",
        "options_func": get_company_replacement_options,
        "multiline": False,
    },
    "ФИО подписант": {
        "hint_search": "Петров А.В.",
        "hint_replace": "J.A. Smith",
        "options_func": get_signatory_replacement_options,
        "multiline": False,
    },
    "ФИО участники": {
        "hint_search": "Сидоров\nКозлова\nМорозов",
        "hint_replace": "Employee #{n}",
        "options_func": get_surname_replacement_options,
        "multiline": True,
    },
    "Своё поле": {
        "hint_search": "ИНН 7707083893",
        "hint_replace": "TIN XXXXXXXXXX",
        "options_func": get_generic_replacement_options,
        "multiline": False,
    },
}

# Английские опции замены (добавляются к русским)
ENGLISH_REPLACEMENT_OPTIONS = {
    "Город": {
        "English cities": [
            "London", "Manchester", "Bristol", "Cambridge", "Oxford",
            "Liverpool", "Birmingham", "Edinburgh", "Glasgow", "Leeds",
        ],
    },
    "Организация": {
        "English companies": [
            "Northgate Industries Ltd",
            "Meridian Solutions Corp",
            "Ashford & Partners Inc",
            "Sterling Dynamics Ltd",
            "Blackwood Engineering Co",
        ],
    },
    "ФИО подписант": {
        "English names": [
            "J.A. Smith", "R.M. Johnson", "D.K. Williams",
            "M.T. Brown", "S.L. Davis",
        ],
    },
    "ФИО участники": {
        "English sequential": [
            "Employee #{n}",
            "Staff Member #{n}",
            "Specialist #{n}",
        ],
    },
}


class FieldRow:
    """Один ряд параметров замены в GUI (CustomTkinter)."""

    def __init__(self, parent_frame, field_type: str, on_delete=None, idx: int = 0):
        self.field_type = field_type
        self.on_delete = on_delete
        self.idx = idx
        config = FIELD_TYPES.get(field_type, FIELD_TYPES["Своё поле"])

        self.frame = ctk.CTkFrame(parent_frame, corner_radius=8)
        self.frame.pack(fill="x", padx=5, pady=4)

        # Заголовок типа поля
        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(6, 2))

        ctk.CTkLabel(
            header, text=field_type,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(side="left")

        if on_delete:
            ctk.CTkButton(
                header, text="✕", width=30, height=26,
                fg_color=COLORS["button_danger"],
                hover_color="#b02727",
                font=ctk.CTkFont(size=12),
                command=self._delete,
            ).pack(side="right")

        # Строка: Искать
        search_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        search_row.pack(fill="x", padx=8, pady=2)

        ctk.CTkLabel(search_row, text="Искать:", width=70, anchor="w").pack(side="left")

        if config["multiline"]:
            self.search_widget = ctk.CTkTextbox(
                self.frame, height=65, corner_radius=6,
                fg_color=COLORS["input_bg"],
                text_color=COLORS["text"],
            )
            self.search_widget.pack(fill="x", padx=8, pady=(0, 2))
        else:
            self.search_var = ctk.StringVar()
            self.search_widget = ctk.CTkEntry(
                search_row, textvariable=self.search_var,
                placeholder_text=config["hint_search"],
                fg_color=COLORS["input_bg"],
                border_color=COLORS["border"],
                text_color=COLORS["text"],
            )
            self.search_widget.pack(side="left", padx=(5, 0), fill="x", expand=True)

        # Строка: Замена
        replace_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        replace_row.pack(fill="x", padx=8, pady=(2, 6))

        ctk.CTkLabel(replace_row, text="Замена:", width=70, anchor="w").pack(side="left")

        self.replace_var = ctk.StringVar(value=config["hint_replace"])

        # Собираем все опции (русские + английские)
        options = []
        for cat, opts in config["options_func"]().items():
            options.extend(opts)
        eng_opts = ENGLISH_REPLACEMENT_OPTIONS.get(field_type, {})
        for cat, opts in eng_opts.items():
            options.extend(opts)

        self.replace_combo = ctk.CTkComboBox(
            replace_row, variable=self.replace_var,
            values=list(dict.fromkeys(options)),
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["card"],
            text_color=COLORS["text"],
            width=300,
        )
        self.replace_combo.pack(side="left", padx=(5, 0), fill="x", expand=True)

        # Кнопка загрузки для multiline
        if config["multiline"]:
            btn_row = ctk.CTkFrame(self.frame, fg_color="transparent")
            btn_row.pack(fill="x", padx=8, pady=(0, 4))
            ctk.CTkButton(
                btn_row, text="Из файла .txt", width=120,
                height=28, font=ctk.CTkFont(size=11),
                fg_color=COLORS["button_secondary"],
                hover_color=COLORS["card"],
                command=self._load_from_file,
            ).pack(side="left")

    def _delete(self):
        self.frame.destroy()
        if self.on_delete:
            self.on_delete(self)

    def _load_from_file(self):
        path = filedialog.askopenfilename(
            title="Файл со списком",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
        )
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.search_widget.delete("1.0", "end")
                self.search_widget.insert("1.0", content)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{e}")

    def get_search_text(self) -> str:
        config = FIELD_TYPES.get(self.field_type, FIELD_TYPES["Своё поле"])
        if config["multiline"]:
            return self.search_widget.get("1.0", "end").strip()
        return self.search_var.get().strip()

    def get_replace_text(self) -> str:
        return self.replace_var.get().strip()

    def set_search_text(self, text: str):
        config = FIELD_TYPES.get(self.field_type, FIELD_TYPES["Своё поле"])
        if config["multiline"]:
            self.search_widget.delete("1.0", "end")
            self.search_widget.insert("1.0", text)
        else:
            self.search_var.set(text)

    def set_replace_text(self, text: str):
        self.replace_var.set(text)

    def to_dict(self) -> dict:
        return {
            "type": self.field_type,
            "search": self.get_search_text(),
            "replace": self.get_replace_text(),
        }

    def is_empty(self) -> bool:
        return not self.get_search_text()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(800, 700)

        self.files: list[str] = []
        self.processing = False
        self.cancel_flag = False
        self.all_mappers: list = []
        self.anon_map: AnonymizationMap | None = None

        self.field_rows: list[FieldRow] = []

        self._load_saved_config()
        self._build_ui()
        self._bind_hotkeys()
        self._restore_fields()

    # ── Config ──────────────────────────────────────────────

    def _load_saved_config(self):
        cfg = load_config()
        self._saved_output = cfg.get("output_dir", "")
        self._saved_fields = cfg.get("fields", [])
        if not self._saved_fields:
            old_company = cfg.get("company_name", "")
            old_surnames = cfg.get("surnames", "")
            old_comp_repl = cfg.get("company_replacement", "Northgate Industries Ltd")
            old_sur_repl = cfg.get("surname_replacement", "Employee #{n}")
            if old_company:
                self._saved_fields.append({
                    "type": "Организация",
                    "search": old_company,
                    "replace": old_comp_repl,
                })
            if old_surnames:
                self._saved_fields.append({
                    "type": "ФИО участники",
                    "search": old_surnames,
                    "replace": old_sur_repl,
                })

    def _save_current_config(self):
        fields_data = [fr.to_dict() for fr in self.field_rows if not fr.is_empty()]
        save_config({
            "output_dir": self.output_var.get(),
            "fields": fields_data,
        })

    def _restore_fields(self):
        if self._saved_fields:
            for fd in self._saved_fields:
                ft = fd.get("type", "Своё поле")
                row = self._add_field_row(ft)
                row.set_search_text(fd.get("search", ""))
                row.set_replace_text(fd.get("replace", ""))
        else:
            self._add_field_row("Организация")
            self._add_field_row("ФИО участники")

    # ── UI Build ────────────────────────────────────────────

    def _build_ui(self):
        # Основной скроллируемый фрейм
        self.main_frame = ctk.CTkScrollableFrame(
            self, corner_radius=0,
            fg_color=COLORS["bg"],
        )
        self.main_frame.pack(fill="both", expand=True)

        # ── Заголовок ──
        header_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["surface"], corner_radius=10)
        header_frame.pack(fill="x", padx=12, pady=(12, 6))

        title_row = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_row.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(
            title_row, text="TITAN CLEANER",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(side="left")

        ctk.CTkLabel(
            title_row, text="v4.0",
            font=ctk.CTkFont(size=14),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            title_row,
            text="Анонимизация и деанонимизация документов",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        ).pack(side="right")

        # ── Секция: АВТОМАТИЧЕСКИЙ РЕЖИМ ──
        self._section_card("АВТОМАТИЧЕСКИЙ РЕЖИМ", self.main_frame, icon="")
        auto_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["surface"], corner_radius=8)
        auto_frame.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            auto_frame,
            text="Автоматический поиск всех ФИО, организаций, реквизитов, адресов, телефонов, email",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            wraplength=900,
        ).pack(anchor="w", padx=12, pady=(8, 4))

        auto_btns = ctk.CTkFrame(auto_frame, fg_color="transparent")
        auto_btns.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(
            auto_btns, text="АВТОПОИСК", width=140,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._auto_detect_start,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            auto_btns, text="АВТО-ЗАМЕНА", width=140,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._auto_replace_start,
        ).pack(side="left")

        # ── Секция: Ручной режим ──
        self._section_card("РУЧНОЙ РЕЖИМ", self.main_frame)

        self.fields_container = ctk.CTkFrame(
            self.main_frame, fg_color="transparent",
        )
        self.fields_container.pack(fill="x", padx=12, pady=(0, 4))

        # Кнопки добавления полей
        add_row = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        add_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(
            add_row, text="Добавить:",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 8))

        field_colors = {
            "Город": "#2ecc71",
            "Организация": "#3498db",
            "ФИО подписант": "#9b59b6",
            "ФИО участники": "#e67e22",
            "Своё поле": "#7f8c8d",
        }
        for ft_name in FIELD_TYPES:
            ctk.CTkButton(
                add_row, text=f"+ {ft_name}",
                width=120, height=28,
                font=ctk.CTkFont(size=11),
                fg_color=field_colors.get(ft_name, COLORS["card"]),
                hover_color=COLORS["accent_hover"],
                command=lambda n=ft_name: self._add_field_row(n),
            ).pack(side="left", padx=2)

        # ── Секция: Режим PDF ──
        self._section_card("РЕЖИМ ЗАМЕНЫ В PDF", self.main_frame)
        pdf_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["surface"], corner_radius=8)
        pdf_frame.pack(fill="x", padx=12, pady=(0, 6))

        pdf_inner = ctk.CTkFrame(pdf_frame, fg_color="transparent")
        pdf_inner.pack(fill="x", padx=12, pady=8)

        self.pdf_mode = ctk.StringVar(value="text")
        ctk.CTkRadioButton(
            pdf_inner, text="Текстовая заглушка",
            variable=self.pdf_mode, value="text",
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
        ).pack(anchor="w")

        stamp_row = ctk.CTkFrame(pdf_inner, fg_color="transparent")
        stamp_row.pack(anchor="w", pady=(4, 0))
        ctk.CTkRadioButton(
            stamp_row, text="Графический штамп:",
            variable=self.pdf_mode, value="stamp",
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
        ).pack(side="left")

        self.stamp_var = ctk.StringVar(value="чёрная плашка")
        stamp_opts = ["чёрная плашка", "ромашка", "замок",
                      "конфиденциально", "свой PNG..."]
        self.stamp_combo = ctk.CTkComboBox(
            stamp_row, variable=self.stamp_var,
            values=stamp_opts, width=180,
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["card"],
            command=self._on_stamp_selected,
        )
        self.stamp_combo.pack(side="left", padx=8)
        self.custom_stamp_path = None

        # OCR
        ocr_row = ctk.CTkFrame(pdf_inner, fg_color="transparent")
        ocr_row.pack(anchor="w", pady=(6, 0))
        self.ocr_enabled = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            ocr_row, text="OCR для сканов (Tesseract)",
            variable=self.ocr_enabled,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=self._on_ocr_toggled,
        ).pack(side="left")
        self.ocr_status_label = ctk.CTkLabel(
            ocr_row, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
        )
        self.ocr_status_label.pack(side="left", padx=12)
        self._check_tesseract()

        # ── Секция: Файлы ──
        self._section_card("ФАЙЛЫ", self.main_frame)

        file_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["surface"], corner_radius=8)
        file_frame.pack(fill="x", padx=12, pady=(0, 6))

        file_btns = ctk.CTkFrame(file_frame, fg_color="transparent")
        file_btns.pack(fill="x", padx=12, pady=(8, 4))

        ctk.CTkButton(
            file_btns, text="Добавить файлы", width=130,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=self._add_files,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            file_btns, text="Добавить папку", width=130,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=self._add_folder,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            file_btns, text="Очистить", width=100,
            fg_color=COLORS["button_danger"], hover_color="#b02727",
            command=self._clear_files,
        ).pack(side="left")

        # Список файлов (используем CTkTextbox как список)
        self.file_listbox = ctk.CTkTextbox(
            file_frame, height=90, corner_radius=6,
            fg_color=COLORS["input_bg"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=11),
        )
        self.file_listbox.pack(fill="x", padx=12, pady=(0, 4))
        self.file_listbox.configure(state="disabled")

        # Выходная папка
        out_row = ctk.CTkFrame(file_frame, fg_color="transparent")
        out_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(out_row, text="Результат:", width=80, anchor="w").pack(side="left")
        self.output_var = ctk.StringVar(
            value=self._saved_output or "./cleaned"
        )
        ctk.CTkEntry(
            out_row, textvariable=self.output_var,
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        ).pack(side="left", padx=5, fill="x", expand=True)
        ctk.CTkButton(
            out_row, text="Обзор", width=80,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=self._browse_output,
        ).pack(side="left", padx=(4, 0))

        # ── Прогресс ──
        self.progress = ctk.CTkProgressBar(
            self.main_frame, progress_color=COLORS["accent"],
            fg_color=COLORS["border"], corner_radius=4,
        )
        self.progress.pack(fill="x", padx=12, pady=(8, 2))
        self.progress.set(0)

        self.progress_label = ctk.CTkLabel(
            self.main_frame, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
        )
        self.progress_label.pack(anchor="w", padx=12)

        # ── Лог ──
        log_header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            log_header, text="Лог",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"],
        ).pack(side="left")

        ctk.CTkButton(
            log_header, text="Очистить", width=80, height=26,
            font=ctk.CTkFont(size=11),
            fg_color=COLORS["button_secondary"],
            hover_color=COLORS["card"],
            command=self._clear_log,
        ).pack(side="right", padx=2)
        ctk.CTkButton(
            log_header, text="Удалить файл лога", width=130, height=26,
            font=ctk.CTkFont(size=11),
            fg_color=COLORS["button_secondary"],
            hover_color=COLORS["card"],
            command=self._delete_log_file,
        ).pack(side="right", padx=2)

        self.log_text = ctk.CTkTextbox(
            self.main_frame, height=140, corner_radius=6,
            fg_color=COLORS["input_bg"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.log_text.pack(fill="x", padx=12, pady=(0, 6))
        self.log_text.configure(state="disabled")
        # Теги для цветного текста
        self.log_text.tag_config("success", foreground=COLORS["success"])
        self.log_text.tag_config("warning", foreground=COLORS["warning"])
        self.log_text.tag_config("error", foreground=COLORS["error"])
        self.log_text.tag_config("info", foreground=COLORS["info"])

        # ── Кнопки действий ──
        action_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["surface"], corner_radius=8)
        action_frame.pack(fill="x", padx=12, pady=(4, 6))

        action_inner = ctk.CTkFrame(action_frame, fg_color="transparent")
        action_inner.pack(padx=12, pady=10)

        self.btn_process = ctk.CTkButton(
            action_inner, text="ОБРАБОТАТЬ", width=150, height=40,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_processing,
        )
        self.btn_process.pack(side="left", padx=6)

        ctk.CTkButton(
            action_inner, text="Предпросмотр", width=130, height=40,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            font=ctk.CTkFont(size=13),
            command=self._preview,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            action_inner, text="Карта замен", width=120, height=40,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            font=ctk.CTkFont(size=13),
            command=self._show_replacement_map,
        ).pack(side="left", padx=6)

        self.btn_deanon = ctk.CTkButton(
            action_inner, text="ДЕАНОНИМИЗАЦИЯ", width=170, height=40,
            fg_color=COLORS["button_success"], hover_color="#009975",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._deanonymize_start,
        )
        self.btn_deanon.pack(side="left", padx=6)

        self.btn_cancel = ctk.CTkButton(
            action_inner, text="Отмена", width=100, height=40,
            fg_color=COLORS["button_danger"], hover_color="#b02727",
            font=ctk.CTkFont(size=13),
            state="disabled",
            command=self._cancel,
        )
        self.btn_cancel.pack(side="left", padx=6)

        # ── Статус-бар ──
        self.status_var = ctk.StringVar(value="Готов к работе")
        status_bar = ctk.CTkLabel(
            self.main_frame, textvariable=self.status_var,
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        status_bar.pack(fill="x", padx=12, pady=(0, 8))

    def _section_card(self, text: str, parent, icon: str = ""):
        """Заголовок секции."""
        lbl = ctk.CTkLabel(
            parent, text=f"{icon}  {text}" if icon else text,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["info"],
            anchor="w",
        )
        lbl.pack(fill="x", padx=16, pady=(10, 2))

    def _check_tesseract(self):
        try:
            from core.ocr_utils import is_tesseract_available
            if is_tesseract_available():
                self.ocr_status_label.configure(
                    text="Tesseract найден", text_color=COLORS["success"]
                )
            else:
                self.ocr_status_label.configure(
                    text="Tesseract не установлен", text_color=COLORS["error"]
                )
        except Exception:
            self.ocr_status_label.configure(
                text="pytesseract не установлен", text_color=COLORS["error"]
            )

    def _on_ocr_toggled(self):
        if self.ocr_enabled.get():
            try:
                from core.ocr_utils import is_tesseract_available
                if not is_tesseract_available():
                    messagebox.showwarning(
                        "Tesseract не найден",
                        "Для OCR необходимо установить Tesseract OCR.\n\n"
                        "Windows: скачайте с github.com/UB-Mannheim/tesseract\n"
                        "и установите с добавлением в PATH.\n\n"
                        "Linux: sudo apt install tesseract-ocr tesseract-ocr-rus"
                    )
                    self.ocr_enabled.set(False)
            except ImportError:
                messagebox.showwarning(
                    "pytesseract не установлен",
                    "Установите pytesseract:\n  pip install pytesseract"
                )
                self.ocr_enabled.set(False)

    def _add_field_row(self, field_type: str) -> FieldRow:
        idx = len(self.field_rows)
        row = FieldRow(
            self.fields_container, field_type,
            on_delete=self._remove_field_row, idx=idx
        )
        self.field_rows.append(row)
        return row

    def _remove_field_row(self, row: FieldRow):
        if row in self.field_rows:
            self.field_rows.remove(row)

    # ── Hotkeys ─────────────────────────────────────────────

    def _bind_hotkeys(self):
        self.bind_all("<Control-o>", lambda e: self._add_files())
        self.bind_all("<Control-Return>", lambda e: self._start_processing())
        self.bind_all("<Escape>", lambda e: self._cancel())

    # ── File operations ─────────────────────────────────────

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Выберите файлы",
            filetypes=[
                ("Документы", "*.docx *.pdf *.xlsx *.xls"),
                ("Word", "*.docx"),
                ("PDF", "*.pdf"),
                ("Excel", "*.xlsx *.xls"),
                ("Все файлы", "*.*"),
            ],
        )
        for p in paths:
            if is_valid_file(p) and p not in self.files:
                self.files.append(p)
        self._refresh_file_list()
        self._update_status()

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку")
        if not folder:
            return
        for root, dirs, filenames in os.walk(folder):
            for fn in filenames:
                fp = os.path.join(root, fn)
                if is_valid_file(fp) and fp not in self.files:
                    self.files.append(fp)
        self._refresh_file_list()
        self._update_status()

    def _refresh_file_list(self):
        self.file_listbox.configure(state="normal")
        self.file_listbox.delete("1.0", "end")
        for f in self.files:
            self.file_listbox.insert("end", Path(f).name + "\n")
        self.file_listbox.configure(state="disabled")

    def _clear_files(self):
        self.files.clear()
        self._refresh_file_list()
        self._update_status()

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Папка для результатов")
        if folder:
            self.output_var.set(folder)

    def _on_stamp_selected(self, choice=None):
        if self.stamp_var.get() == "свой PNG...":
            path = filedialog.askopenfilename(
                title="Выберите PNG-штамп",
                filetypes=[("PNG", "*.png"), ("Все файлы", "*.*")],
            )
            if path:
                self.custom_stamp_path = path
                self.stamp_var.set(f"Свой: {Path(path).name}")
            else:
                self.stamp_var.set("чёрная плашка")

    # ── Logging ─────────────────────────────────────────────

    def _log(self, message: str, tag: str = "info"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        logger.info(message)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _delete_log_file(self):
        from core.utils import get_app_dir
        log_path = get_app_dir() / 'cleaner.log'
        if not log_path.exists():
            messagebox.showinfo("Лог", "Файл лога не найден.")
            return
        if not messagebox.askyesno(
            "Удалить лог",
            f"Удалить файл лога?\n{log_path}"
        ):
            return
        try:
            for handler in logger.handlers[:]:
                if isinstance(handler, logging.FileHandler):
                    handler.close()
                    logger.removeHandler(handler)
            log_path.unlink()
            self._clear_log()
            fh = logging.FileHandler(str(log_path), encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter(
                '%(asctime)s [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S'
            ))
            logger.addHandler(fh)
            self._log("Файл лога удалён и пересоздан.", "info")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось удалить лог:\n{e}")

    def _update_status(self):
        n = len(self.files)
        docx_count = sum(1 for f in self.files if f.lower().endswith('.docx'))
        pdf_count = sum(1 for f in self.files if f.lower().endswith('.pdf'))
        xlsx_count = sum(1 for f in self.files if f.lower().endswith(('.xlsx', '.xls')))
        parts = f"Файлов: {n} (DOCX: {docx_count}, PDF: {pdf_count}"
        if xlsx_count:
            parts += f", Excel: {xlsx_count}"
        parts += ")"
        self.status_var.set(parts)

    # ── Build replacement rules ─────────────────────────────

    def _build_replacement_rules(self) -> list[dict]:
        rules = []
        self.all_mappers = []
        self.anon_map = AnonymizationMap()

        for row in self.field_rows:
            if row.is_empty():
                continue

            search = row.get_search_text()
            replace = row.get_replace_text()
            ft = row.field_type

            if ft == "Организация":
                patterns = build_company_patterns(search)
                rules.append({
                    "patterns": patterns,
                    "replacement": replace,
                    "type": "company",
                })
                self.anon_map.add(search, replace)

            elif ft == "Город":
                patterns = build_city_patterns(search)
                rules.append({
                    "patterns": patterns,
                    "replacement": replace,
                    "type": "city",
                })
                self.anon_map.add(search, replace)

            elif ft == "ФИО подписант":
                sp = SurnamePattern(search, search_with_initials=True,
                                    search_feminine=True)
                patterns = sp.get_all_patterns_sorted()
                rules.append({
                    "patterns": patterns,
                    "replacement": replace,
                    "type": "signatory",
                })
                self.anon_map.add(search, replace)

            elif ft == "ФИО участники":
                mapper = ReplacementMapper(replace)
                self.all_mappers.append(mapper)
                surname_patterns = []
                for line in search.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    for surname in line.split(','):
                        surname = surname.strip()
                        if surname:
                            sp = SurnamePattern(
                                surname,
                                search_with_initials=True,
                                search_feminine=True,
                            )
                            surname_patterns.extend(
                                sp.get_all_patterns_sorted()
                            )
                if surname_patterns:
                    rules.append({
                        "patterns": surname_patterns,
                        "mapper": mapper,
                        "type": "surnames",
                    })

            elif ft == "Своё поле":
                patterns = build_custom_patterns(search)
                rules.append({
                    "patterns": patterns,
                    "replacement": replace,
                    "type": "custom",
                })
                self.anon_map.add(search, replace)

        return rules

    def _get_stamp_path(self) -> str | None:
        if self.custom_stamp_path:
            return self.custom_stamp_path
        stamp_name = self.stamp_var.get()
        if stamp_name in ("чёрная плашка", "") or stamp_name.startswith("Свой:"):
            if stamp_name.startswith("Свой:"):
                return self.custom_stamp_path
            return None
        assets_dir = get_assets_dir()
        stamp_map = {
            "ромашка": "daisy.png",
            "замок": "lock.png",
            "конфиденциально": "confidential.png",
        }
        fn = stamp_map.get(stamp_name)
        if fn:
            p = assets_dir / "stamps" / fn
            if p.exists():
                return str(p)
        return None

    # ── Processing ──────────────────────────────────────────

    def _validate(self) -> bool:
        has_data = any(not row.is_empty() for row in self.field_rows)
        if not has_data:
            messagebox.showwarning(
                "Внимание",
                "Добавьте хотя бы одно поле для замены и заполните его."
            )
            return False
        if not self.files:
            messagebox.showwarning(
                "Внимание", "Добавьте файлы для обработки."
            )
            return False
        return True

    def _start_processing(self):
        if self.processing:
            return
        if not self._validate():
            return

        self._save_current_config()
        self.processing = True
        self.cancel_flag = False
        self.btn_process.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress.set(0)

        thread = threading.Thread(target=self._process_files, daemon=True)
        thread.start()

    def _cancel(self):
        if self.processing:
            self.cancel_flag = True
            self._log("Отмена обработки...", "warning")

    def _process_files(self):
        replacement_rules = self._build_replacement_rules()
        output_dir = self.output_var.get()

        try:
            ensure_output_dir(output_dir)
        except Exception as e:
            self.after(0, lambda: self._log(
                f"Ошибка создания папки: {e}", "error"
            ))
            self._finish_processing()
            return

        total_matches = {}
        file_count = len(self.files)

        for i, filepath in enumerate(self.files):
            if self.cancel_flag:
                self.after(0, lambda: self._log(
                    "Обработка отменена.", "warning"
                ))
                break

            filename = Path(filepath).name
            ext = Path(filepath).suffix.lower()
            output_path = str(Path(output_dir) / filename)

            if os.path.abspath(filepath) == os.path.abspath(output_path):
                stem = Path(filepath).stem
                output_path = str(
                    Path(output_dir) / f"{stem}_cleaned{ext}"
                )

            self.after(0, lambda fn=filename: self.progress_label.configure(
                text=f"Обработка: {fn}"
            ))

            try:
                file_size = os.path.getsize(filepath)
                if file_size > 100 * 1024 * 1024:
                    self.after(0, lambda fn=filename: self._log(
                        f"! {fn} — большой файл ({format_file_size(file_size)})",
                        "warning"
                    ))

                if ext == '.docx':
                    result = clean_docx(
                        filepath, output_path, replacement_rules
                    )
                elif ext == '.pdf':
                    ocr_on = self.ocr_enabled.get()
                    if self.pdf_mode.get() == "text":
                        result = clean_pdf_text_mode(
                            filepath, output_path, replacement_rules,
                            ocr_enabled=ocr_on,
                        )
                    else:
                        stamp_path = self._get_stamp_path()
                        result = clean_pdf_stamp_mode(
                            filepath, output_path, replacement_rules,
                            stamp_path=stamp_path,
                            stamp_type=self.stamp_var.get(),
                            ocr_enabled=ocr_on,
                        )
                elif ext in ('.xlsx', '.xls'):
                    result = clean_xlsx(
                        filepath, output_path, replacement_rules
                    )
                else:
                    continue

                status = result.get("status", "error")
                matches = result.get("matches", {})
                err = result.get("error_message")

                for k, v in matches.items():
                    total_matches[k] = total_matches.get(k, 0) + v

                total_file = sum(matches.values()) if isinstance(matches, dict) else 0

                ocr_pgs = result.get("ocr_pages", [])
                ocr_info = ""
                if ocr_pgs:
                    ocr_info = f" (OCR: стр. {', '.join(map(str, ocr_pgs))})"

                if status == "success":
                    if total_file > 0:
                        details = ", ".join(
                            f"{k}: {v}" for k, v in matches.items()
                        )
                        msg = f"OK {filename} — {details}{ocr_info}"
                        self.after(0, lambda m=msg: self._log(m, "success"))
                    else:
                        msg = f"! {filename} — 0 вхождений"
                        self.after(0, lambda m=msg: self._log(m, "warning"))
                elif status == "warning":
                    msg = f"! {filename} — {err}"
                    self.after(0, lambda m=msg: self._log(m, "warning"))
                else:
                    msg = f"X {filename} — ошибка: {err}"
                    self.after(0, lambda m=msg: self._log(m, "error"))

            except Exception as e:
                msg = f"X {filename} — исключение: {e}"
                self.after(0, lambda m=msg: self._log(m, "error"))
                logger.exception(f"Error processing {filepath}")

            progress_val = (i + 1) / file_count if file_count else 1
            self.after(0, lambda v=progress_val: self.progress.set(v))

        # Сохраняем маппинг замен для mappers (ФИО участники)
        if self.all_mappers and self.anon_map:
            for mapper in self.all_mappers:
                for orig, repl in mapper.get_map().items():
                    self.anon_map.add(orig, repl)

        # Сохраняем маппинг в файл
        if self.anon_map and self.anon_map.mappings and output_dir:
            try:
                map_path = str(Path(output_dir) / "anonymization_map.titan_map.json")
                p = Path(output_dir)
                data = {
                    "version": 1,
                    "mappings": [
                        {
                            "original": self.anon_map.originals[k],
                            "pseudonym": self.anon_map.mappings[k],
                        }
                        for k in self.anon_map.mappings
                    ],
                }
                with open(map_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self.after(0, lambda mp=map_path: self._log(
                    f"Карта замен сохранена: {mp}", "info"
                ))
            except Exception as e:
                self.after(0, lambda: self._log(
                    f"Ошибка сохранения карты замен: {e}", "warning"
                ))

        # Итог
        if total_matches:
            details = ", ".join(f"{k}: {v}" for k, v in total_matches.items())
            summary = f"Готово. {details}"
        else:
            summary = "Готово. Замен не найдено."
        self.after(0, lambda: self._log(summary, "info"))
        self.after(0, lambda: self.progress_label.configure(text=summary))
        self._finish_processing()

    def _finish_processing(self):
        self.processing = False
        self.after(0, lambda: self.btn_process.configure(state="normal"))
        self.after(0, lambda: self.btn_cancel.configure(state="disabled"))

    # ── Preview ─────────────────────────────────────────────

    def _preview(self):
        if not self._validate():
            return

        replacement_rules = self._build_replacement_rules()

        win = ctk.CTkToplevel(self)
        win.title("Предпросмотр вхождений")
        win.geometry("750x550")
        win.transient(self)

        text = ctk.CTkTextbox(
            win, corner_radius=6,
            fg_color=COLORS["input_bg"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        text.pack(fill="both", expand=True, padx=12, pady=12)
        text.tag_config("header", foreground=COLORS["info"])
        text.tag_config("match", foreground=COLORS["error"])
        text.tag_config("repl", foreground=COLORS["success"])

        for filepath in self.files:
            filename = Path(filepath).name
            ext = Path(filepath).suffix.lower()

            text.insert("end", f"\n{'='*50}\n", "header")
            text.insert("end", f"{filename}\n", "header")

            try:
                if ext == '.docx':
                    result = preview_docx(filepath, replacement_rules)
                elif ext == '.pdf':
                    result = preview_pdf(
                        filepath, replacement_rules,
                        ocr_enabled=self.ocr_enabled.get(),
                    )
                elif ext in ('.xlsx', '.xls'):
                    result = preview_xlsx(filepath, replacement_rules)
                else:
                    continue

                matches = result.get("matches", [])
                if not matches:
                    text.insert("end", "  Вхождений не найдено\n")
                    continue

                type_counts = result.get("type_counts", {})
                counts_str = ", ".join(
                    f"{k}: {v}" for k, v in type_counts.items()
                )
                text.insert("end", f"  {counts_str}\n\n")

                for m in matches:
                    page_info = (
                        f" (стр. {m['page']})" if 'page' in m else ""
                    )
                    ocr_tag = " [OCR]" if m.get('ocr') else ""
                    text.insert(
                        "end",
                        f"  [{m['type']}]{page_info}{ocr_tag} "
                    )
                    text.insert("end", m['original'], "match")
                    text.insert("end", " -> ")
                    text.insert("end", m['replacement'], "repl")
                    text.insert(
                        "end", f"\n  Контекст: {m['context']}\n\n"
                    )

            except Exception as e:
                text.insert("end", f"  Ошибка: {e}\n")

        text.configure(state="disabled")

    # ── Auto-detect ─────────────────────────────────────────

    def _auto_detect_start(self):
        if not self.files:
            messagebox.showwarning("Внимание", "Добавьте файлы для анализа.")
            return
        self._log("Автопоиск запущен...", "info")
        self.status_var.set("Автопоиск...")
        thread = threading.Thread(target=self._auto_detect_worker, daemon=True)
        thread.start()

    def _auto_detect_worker(self):
        all_results = []
        for filepath in self.files:
            result = auto_detect_in_file(filepath)
            all_results.append(result)
            n = len(result.get("entities", []))
            fname = Path(filepath).name
            ocr_tag = " [OCR]" if result.get("used_ocr") else ""
            if result.get("error"):
                self.after(0, lambda m=f"X {fname}: {result['error']}":
                           self._log(m, "error"))
            else:
                self.after(0, lambda m=f"  {fname}: найдено {n} сущностей{ocr_tag}":
                           self._log(m, "info"))

        self.after(0, lambda: self._show_auto_detect_preview(all_results))
        self.after(0, lambda: self.status_var.set("Автопоиск завершён"))

    def _show_auto_detect_preview(self, all_results: list[dict]):
        win = ctk.CTkToplevel(self)
        win.title("Автопоиск — результаты")
        win.geometry("1000x750")
        win.minsize(750, 550)
        win.transient(self)

        self._last_auto_results = all_results

        # Сводка
        summary_frame = ctk.CTkFrame(win, fg_color=COLORS["surface"], corner_radius=8)
        summary_frame.pack(fill="x", padx=12, pady=(12, 6))

        global_counts = {}
        total = 0
        for res in all_results:
            for e in res.get("entities", []):
                global_counts[e.entity_type] = global_counts.get(e.entity_type, 0) + 1
                total += 1

        summary_text = f"Всего найдено: {total}   |   "
        parts = []
        for etype, count in sorted(global_counts.items(), key=lambda x: -x[1]):
            parts.append(f"{get_type_name(etype)}: {count}")
        summary_text += "  |  ".join(parts)
        ctk.CTkLabel(
            summary_frame, text=summary_text,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text"],
            wraplength=950,
        ).pack(padx=12, pady=8)

        # Двухпанельный вид
        content = ctk.CTkFrame(win, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=6)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        # Левая панель
        left_frame = ctk.CTkFrame(content, fg_color=COLORS["surface"], corner_radius=8)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ctk.CTkLabel(
            left_frame, text="Найденные сущности",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["info"],
        ).pack(anchor="w", padx=10, pady=(8, 4))

        list_text = ctk.CTkTextbox(
            left_frame, corner_radius=6,
            fg_color=COLORS["input_bg"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=11),
        )
        list_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        list_text.tag_config("header", foreground=COLORS["info"])
        list_text.tag_config("item", foreground=COLORS["text_secondary"])

        for etype in sorted(global_counts.keys(),
                            key=lambda t: global_counts.get(t, 0), reverse=True):
            type_name = get_type_name(etype)
            count = global_counts[etype]
            list_text.insert("end", f"\n{type_name} ({count}):\n", "header")

            seen = set()
            for res in all_results:
                for e in res.get("entities", []):
                    if e.entity_type == etype:
                        key = e.text.strip()
                        if key not in seen:
                            seen.add(key)
                            list_text.insert(
                                "end",
                                f"  {key}  ->  {e.replacement}\n",
                                "item",
                            )
        list_text.configure(state="disabled")

        # Правая панель
        right_frame = ctk.CTkFrame(content, fg_color=COLORS["surface"], corner_radius=8)
        right_frame.grid(row=0, column=1, sticky="nsew")

        file_select = ctk.CTkFrame(right_frame, fg_color="transparent")
        file_select.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(file_select, text="Файл:").pack(side="left")
        file_names = [Path(r["filepath"]).name for r in all_results]
        file_var = ctk.StringVar(value=file_names[0] if file_names else "")
        file_combo = ctk.CTkComboBox(
            file_select, variable=file_var,
            values=file_names, width=300,
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
            button_color=COLORS["accent"],
            dropdown_fg_color=COLORS["surface"],
            command=lambda v: show_file_preview(),
        )
        file_combo.pack(side="left", padx=8)

        ctk.CTkLabel(
            right_frame, text="Текст документа (маркер = найденное)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["info"],
        ).pack(anchor="w", padx=10)

        doc_text = ctk.CTkTextbox(
            right_frame, corner_radius=6,
            fg_color=COLORS["input_bg"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family="Consolas", size=10),
        )
        doc_text.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        # Теги маркеров
        doc_text.tag_config("marker_surname", foreground="#FFD700", underline=True)
        doc_text.tag_config("marker_org", foreground="#FF8C00", underline=True)
        doc_text.tag_config("marker_city", foreground="#00FF7F", underline=True)
        doc_text.tag_config("marker_requisite", foreground="#87CEEB", underline=True)
        doc_text.tag_config("marker_contact", foreground="#DDA0DD", underline=True)
        doc_text.tag_config("marker_address", foreground="#F0E68C", underline=True)
        doc_text.tag_config("marker_passport", foreground="#FFA07A", underline=True)
        doc_text.tag_config("marker", foreground="#FFFF00", underline=True)
        doc_text.tag_config("page_header", foreground=COLORS["accent"])

        MARKER_TAGS = {
            "surname": "marker_surname",
            "organization": "marker_org",
            "city": "marker_city",
            "inn": "marker_requisite",
            "ogrn": "marker_requisite",
            "kpp": "marker_requisite",
            "bik": "marker_requisite",
            "account": "marker_requisite",
            "snils": "marker_passport",
            "passport": "marker_passport",
            "phone": "marker_contact",
            "email": "marker_contact",
            "url": "marker_contact",
            "address": "marker_address",
        }

        def show_file_preview(event=None):
            doc_text.configure(state="normal")
            doc_text.delete("1.0", "end")

            fname = file_var.get()
            result = None
            for r in all_results:
                if Path(r["filepath"]).name == fname:
                    result = r
                    break
            if not result:
                doc_text.configure(state="disabled")
                return

            pages = result.get("pages", {})
            entities = result.get("entities", [])
            full_text = result.get("text", "")

            if not pages:
                doc_text.insert("end", full_text or "(нет текста)")
                doc_text.configure(state="disabled")
                return

            max_pages = 3
            shown = 0
            text_offset = 0

            for page_num in sorted(pages.keys()):
                if shown >= max_pages:
                    doc_text.insert(
                        "end",
                        f"\n... ещё {len(pages) - max_pages} стр. ...\n",
                        "page_header",
                    )
                    break

                page_text = pages[page_num]
                if not page_text.strip():
                    text_offset += len(page_text)
                    continue

                doc_text.insert(
                    "end",
                    f"\n── Страница {page_num} ──\n",
                    "page_header",
                )

                page_start = text_offset
                page_end = text_offset + len(page_text)
                page_entities = [
                    e for e in entities
                    if e.start >= page_start and e.end <= page_end
                ]

                pos = 0
                for e in sorted(page_entities, key=lambda x: x.start):
                    local_start = e.start - page_start
                    local_end = e.end - page_start

                    if local_start < pos:
                        continue

                    if local_start > pos:
                        doc_text.insert("end", page_text[pos:local_start])

                    tag = MARKER_TAGS.get(e.entity_type, "marker")
                    doc_text.insert("end", page_text[local_start:local_end], tag)
                    pos = local_end

                if pos < len(page_text):
                    doc_text.insert("end", page_text[pos:])

                text_offset += len(page_text)
                shown += 1

            doc_text.configure(state="disabled")

        if all_results:
            show_file_preview()

        # Легенда
        legend_frame = ctk.CTkFrame(win, fg_color="transparent")
        legend_frame.pack(fill="x", padx=12, pady=2)
        legends = [
            ("ФИО", "#FFD700"), ("Организации", "#FF8C00"),
            ("Города", "#00FF7F"), ("Реквизиты", "#87CEEB"),
            ("Контакты", "#DDA0DD"), ("Адреса", "#F0E68C"),
            ("Документы", "#FFA07A"),
        ]
        for name, color in legends:
            ctk.CTkLabel(
                legend_frame, text=f" {name} ",
                font=ctk.CTkFont(size=10),
                text_color=color,
            ).pack(side="left", padx=4)

        # Кнопки
        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(4, 12))

        def do_auto_replace():
            win.destroy()
            self._auto_replace_from_results(all_results)

        ctk.CTkButton(
            btn_frame, text="АВТО-ЗАМЕНА (заменить всё)",
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=do_auto_replace,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_frame, text="Закрыть",
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=win.destroy,
        ).pack(side="right", padx=6)

    def _auto_replace_start(self):
        if not self.files:
            messagebox.showwarning("Внимание", "Добавьте файлы для обработки.")
            return

        if not messagebox.askyesno(
            "Авто-замена",
            "Программа автоматически найдёт и заменит все персональные данные "
            "и реквизиты во всех файлах.\n\n"
            "Оригиналы НЕ будут изменены — результаты сохраняются в папку результатов.\n\n"
            "Продолжить?"
        ):
            return

        self._log("Авто-замена: сканирование...", "info")
        self.status_var.set("Авто-замена...")
        thread = threading.Thread(target=self._auto_replace_worker, daemon=True)
        thread.start()

    def _auto_replace_worker(self):
        all_results = []
        for filepath in self.files:
            result = auto_detect_in_file(filepath)
            all_results.append(result)

        self.after(0, lambda: self._auto_replace_from_results(all_results))

    def _auto_replace_from_results(self, all_results: list[dict]):
        output_dir = self.output_var.get()
        try:
            ensure_output_dir(output_dir)
        except Exception as e:
            self._log(f"Ошибка создания папки: {e}", "error")
            return

        self._save_current_config()
        self.processing = True
        self.cancel_flag = False
        self.btn_process.configure(state="disabled")
        self.progress.set(0)

        # Создаём маппинг для авто-замены
        self.anon_map = AnonymizationMap()

        thread = threading.Thread(
            target=self._auto_replace_process,
            args=(all_results, output_dir),
            daemon=True,
        )
        thread.start()

    def _auto_replace_process(self, all_results: list[dict], output_dir: str):
        from core.patterns import build_custom_patterns

        total_matches = {}
        result_count = len(all_results)

        for i, result in enumerate(all_results):
            if self.cancel_flag:
                self.after(0, lambda: self._log("Отменено.", "warning"))
                break

            filepath = result["filepath"]
            filename = Path(filepath).name
            ext = Path(filepath).suffix.lower()
            output_path = str(Path(output_dir) / filename)

            if os.path.abspath(filepath) == os.path.abspath(output_path):
                stem = Path(filepath).stem
                output_path = str(Path(output_dir) / f"{stem}_cleaned{ext}")

            entities = result.get("entities", [])
            if not entities:
                self.after(0, lambda fn=filename: self._log(
                    f"! {fn} — 0 сущностей", "warning"
                ))
                progress_val = (i + 1) / result_count if result_count else 1
                self.after(0, lambda v=progress_val: self.progress.set(v))
                continue

            self.after(0, lambda fn=filename: self.progress_label.configure(
                text=f"Авто-замена: {fn}"
            ))

            # Сохраняем маппинги в anon_map
            for e in entities:
                if self.anon_map:
                    self.anon_map.add(e.text, e.replacement)

            replacement_rules = self._entities_to_rules(entities)

            try:
                if ext == '.docx':
                    res = clean_docx(filepath, output_path, replacement_rules)
                elif ext == '.pdf':
                    res = clean_pdf_text_mode(filepath, output_path, replacement_rules)
                elif ext in ('.xlsx', '.xls'):
                    res = clean_xlsx(filepath, output_path, replacement_rules)
                else:
                    continue

                status = res.get("status", "error")
                matches = res.get("matches", {})
                err = res.get("error_message")

                for k, v in matches.items():
                    total_matches[k] = total_matches.get(k, 0) + v
                total_file = sum(matches.values()) if isinstance(matches, dict) else 0

                if status == "success":
                    if total_file > 0:
                        details = ", ".join(f"{k}: {v}" for k, v in matches.items())
                        msg = f"OK {filename} — {details}"
                        self.after(0, lambda m=msg: self._log(m, "success"))
                    else:
                        msg = f"! {filename} — 0 замен"
                        self.after(0, lambda m=msg: self._log(m, "warning"))
                else:
                    msg = f"X {filename} — {err}"
                    self.after(0, lambda m=msg: self._log(m, "error"))

            except Exception as e:
                msg = f"X {filename} — исключение: {e}"
                self.after(0, lambda m=msg: self._log(m, "error"))
                logger.exception(f"Auto-replace error: {filepath}")

            progress_val = (i + 1) / result_count if result_count else 1
            self.after(0, lambda v=progress_val: self.progress.set(v))

        # Сохраняем карту замен
        if self.anon_map and self.anon_map.mappings:
            try:
                map_path = str(Path(output_dir) / "anonymization_map.titan_map.json")
                data = {
                    "version": 1,
                    "mappings": [
                        {
                            "original": self.anon_map.originals[k],
                            "pseudonym": self.anon_map.mappings[k],
                        }
                        for k in self.anon_map.mappings
                    ],
                }
                with open(map_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self.after(0, lambda mp=map_path: self._log(
                    f"Карта замен сохранена: {mp}", "info"
                ))
            except Exception as e:
                self.after(0, lambda: self._log(
                    f"Ошибка сохранения карты замен: {e}", "warning"
                ))

        if total_matches:
            details = ", ".join(f"{k}: {v}" for k, v in total_matches.items())
            summary = f"Авто-замена завершена. {details}"
        else:
            summary = "Авто-замена завершена. Замен не выполнено."
        self.after(0, lambda: self._log(summary, "info"))
        self.after(0, lambda: self.progress_label.configure(text=summary))
        self._finish_processing()

    @staticmethod
    def _entities_to_rules(entities: list) -> list[dict]:
        import re as _re
        rules = []
        seen = set()

        for e in entities:
            text_escaped = _re.escape(e.text)
            key = (text_escaped, e.replacement)
            if key in seen:
                continue
            seen.add(key)

            pattern = _re.compile(text_escaped, _re.IGNORECASE)
            rules.append({
                "patterns": [pattern],
                "replacement": e.replacement,
                "type": e.entity_type,
            })

        rules.sort(key=lambda r: len(r["patterns"][0].pattern), reverse=True)
        return rules

    # ── Deanonymization ─────────────────────────────────────

    def _deanonymize_start(self):
        """Диалог деанонимизации: выбрать файл + карту замен → обратная замена."""
        win = ctk.CTkToplevel(self)
        win.title("Деанонимизация")
        win.geometry("650x400")
        win.transient(self)

        ctk.CTkLabel(
            win, text="ДЕАНОНИМИЗАЦИЯ ДОКУМЕНТА",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(padx=16, pady=(16, 4))

        ctk.CTkLabel(
            win,
            text="Загрузите анонимизированный (или изменённый ИИ) документ\n"
                 "и карту замен (.titan_map.json) для обратной замены.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
            justify="center",
        ).pack(padx=16, pady=(0, 12))

        # Файл документа
        doc_frame = ctk.CTkFrame(win, fg_color=COLORS["surface"], corner_radius=8)
        doc_frame.pack(fill="x", padx=16, pady=4)

        doc_inner = ctk.CTkFrame(doc_frame, fg_color="transparent")
        doc_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(doc_inner, text="Документ:", width=100, anchor="w").pack(side="left")
        doc_var = ctk.StringVar()
        doc_entry = ctk.CTkEntry(
            doc_inner, textvariable=doc_var,
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        )
        doc_entry.pack(side="left", fill="x", expand=True, padx=5)

        def browse_doc():
            path = filedialog.askopenfilename(
                title="Выберите документ для деанонимизации",
                filetypes=[
                    ("Документы", "*.docx *.pdf *.xlsx *.xls"),
                    ("Все файлы", "*.*"),
                ],
            )
            if path:
                doc_var.set(path)
                # Автоподбор карты замен
                p = Path(path)
                auto_map = p.parent / "anonymization_map.titan_map.json"
                if auto_map.exists() and not map_var.get():
                    map_var.set(str(auto_map))
                else:
                    per_file_map = p.parent / f"{p.stem}.titan_map.json"
                    if per_file_map.exists() and not map_var.get():
                        map_var.set(str(per_file_map))

        ctk.CTkButton(
            doc_inner, text="Обзор", width=80,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=browse_doc,
        ).pack(side="left")

        # Карта замен
        map_frame = ctk.CTkFrame(win, fg_color=COLORS["surface"], corner_radius=8)
        map_frame.pack(fill="x", padx=16, pady=4)

        map_inner = ctk.CTkFrame(map_frame, fg_color="transparent")
        map_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(map_inner, text="Карта замен:", width=100, anchor="w").pack(side="left")
        map_var = ctk.StringVar()
        ctk.CTkEntry(
            map_inner, textvariable=map_var,
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        ).pack(side="left", fill="x", expand=True, padx=5)

        def browse_map():
            path = filedialog.askopenfilename(
                title="Выберите карту замен",
                filetypes=[
                    ("Titan Map", "*.titan_map.json"),
                    ("JSON", "*.json"),
                    ("Все файлы", "*.*"),
                ],
            )
            if path:
                map_var.set(path)

        ctk.CTkButton(
            map_inner, text="Обзор", width=80,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=browse_map,
        ).pack(side="left")

        # Выходной файл
        out_frame = ctk.CTkFrame(win, fg_color=COLORS["surface"], corner_radius=8)
        out_frame.pack(fill="x", padx=16, pady=4)

        out_inner = ctk.CTkFrame(out_frame, fg_color="transparent")
        out_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(out_inner, text="Результат:", width=100, anchor="w").pack(side="left")
        out_var = ctk.StringVar()
        ctk.CTkEntry(
            out_inner, textvariable=out_var,
            placeholder_text="(авто: рядом с документом, _restored)",
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        ).pack(side="left", fill="x", expand=True, padx=5)

        def browse_out():
            path = filedialog.asksaveasfilename(
                title="Сохранить деанонимизированный документ",
            )
            if path:
                out_var.set(path)

        ctk.CTkButton(
            out_inner, text="Обзор", width=80,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=browse_out,
        ).pack(side="left")

        # Результат
        result_label = ctk.CTkLabel(
            win, text="",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        )
        result_label.pack(padx=16, pady=4)

        # Кнопка запуска
        def run_deanon():
            doc_path = doc_var.get().strip()
            map_path = map_var.get().strip()
            output_path = out_var.get().strip() or None

            if not doc_path:
                messagebox.showwarning("Внимание", "Выберите документ.")
                return
            if not map_path:
                messagebox.showwarning("Внимание", "Выберите карту замен.")
                return
            if not Path(doc_path).exists():
                messagebox.showerror("Ошибка", f"Файл не найден:\n{doc_path}")
                return
            if not Path(map_path).exists():
                messagebox.showerror("Ошибка", f"Карта замен не найдена:\n{map_path}")
                return

            result_label.configure(text="Деанонимизация...", text_color=COLORS["info"])
            win.update()

            try:
                result = deanonymize_file(doc_path, map_path, output_path)
                status = result.get("status", "error")
                out_file = result.get("output_path", "")
                matches = result.get("matches", {})
                err = result.get("error_message", "")

                if status == "success":
                    total_repl = sum(matches.values()) if matches else 0
                    result_label.configure(
                        text=f"Готово! Восстановлено замен: {total_repl}\nФайл: {out_file}",
                        text_color=COLORS["success"],
                    )
                    self._log(f"Деанонимизация: {Path(doc_path).name} -> {out_file} ({total_repl} замен)", "success")
                elif status == "warning":
                    result_label.configure(text=err, text_color=COLORS["warning"])
                    self._log(f"Деанонимизация: {err}", "warning")
                else:
                    result_label.configure(text=f"Ошибка: {err}", text_color=COLORS["error"])
                    self._log(f"Деанонимизация ошибка: {err}", "error")

            except Exception as e:
                result_label.configure(text=f"Ошибка: {e}", text_color=COLORS["error"])
                self._log(f"Деанонимизация исключение: {e}", "error")
                logger.exception("Deanonymization error")

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(8, 16))

        ctk.CTkButton(
            btn_frame, text="ДЕАНОНИМИЗИРОВАТЬ", width=200, height=40,
            fg_color=COLORS["button_success"], hover_color="#009975",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=run_deanon,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_frame, text="Закрыть",
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=win.destroy,
        ).pack(side="right", padx=6)

    # ── Replacement Map ─────────────────────────────────────

    def _show_replacement_map(self):
        # Собираем все маппинги (из mappers + anon_map)
        all_mappings = {}
        for mapper in self.all_mappers:
            all_mappings.update(mapper.get_map())

        if self.anon_map:
            for k in self.anon_map.mappings:
                orig = self.anon_map.originals[k]
                repl = self.anon_map.mappings[k]
                all_mappings[orig] = repl

        if not all_mappings:
            messagebox.showinfo(
                "Карта замен",
                "Сначала выполните обработку файлов."
            )
            return

        win = ctk.CTkToplevel(self)
        win.title("Карта замен (сеанс)")
        win.geometry("650x450")
        win.transient(self)

        # Используем текстовое поле вместо Treeview
        text = ctk.CTkTextbox(
            win, corner_radius=6,
            fg_color=COLORS["input_bg"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        text.pack(fill="both", expand=True, padx=12, pady=12)

        text.tag_config("header", foreground=COLORS["info"])
        text.tag_config("original", foreground=COLORS["error"])
        text.tag_config("arrow", foreground=COLORS["text_secondary"])
        text.tag_config("replacement", foreground=COLORS["success"])

        text.insert("end", f"{'Оригинал':<35} {'':>3} {'Замена'}\n", "header")
        text.insert("end", "─" * 70 + "\n", "header")

        for orig, repl in all_mappings.items():
            text.insert("end", f"{orig:<35}", "original")
            text.insert("end", " -> ", "arrow")
            text.insert("end", f"{repl}\n", "replacement")

        text.configure(state="disabled")

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 12))

        def export_csv():
            path = filedialog.asksaveasfilename(
                title="Экспорт карты замен",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")],
            )
            if path:
                try:
                    with open(path, 'w', encoding='utf-8-sig',
                              newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(["Оригинал", "Заменено на"])
                        for orig, repl in all_mappings.items():
                            writer.writerow([orig, repl])
                    messagebox.showinfo(
                        "Экспорт",
                        f"Карта замен сохранена:\n{path}"
                    )
                except Exception as e:
                    messagebox.showerror("Ошибка", str(e))

        ctk.CTkButton(
            btn_row, text="Экспорт в CSV", width=130,
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=export_csv,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row, text="Закрыть",
            fg_color=COLORS["card"], hover_color="#1a4a8a",
            command=win.destroy,
        ).pack(side="right", padx=4)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
