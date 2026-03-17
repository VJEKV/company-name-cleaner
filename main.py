"""
Titan Cleaner v4.0 — портативное GUI-приложение.
Анонимизация и деанонимизация документов (.docx, .pdf, .xlsx).
Двухпанельный интерфейс: управление слева, предпросмотр текста справа.
Маппинг хранится в SQLite базе.
"""

import csv
import json
import logging
import os
import re
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

# Логирование ошибок запуска
def _log_startup_error(msg):
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
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Ошибка", f"Не удалось загрузить CustomTkinter:\n{e}")
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
from core.database import SessionDB
from core.docx_cleaner import clean_docx, preview_docx
from core.pdf_cleaner import clean_pdf_text_mode, clean_pdf_stamp_mode, preview_pdf
from core.xlsx_cleaner import clean_xlsx, preview_xlsx, extract_text_xlsx, is_openpyxl_available
from core.utils import (
    setup_logging, load_config, save_config, get_assets_dir,
    is_valid_file, ensure_output_dir, format_file_size,
)
from core.auto_detect import (
    auto_detect_in_file, DetectedEntity, ENTITY_TYPE_NAMES,
    get_type_name, _reset_counters, _replacement_cache,
)

APP_TITLE = "Titan Cleaner v4.0"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 820

# Цвета
C = {
    "bg":         "#111827",
    "surface":    "#1f2937",
    "card":       "#374151",
    "input":      "#1e293b",
    "border":     "#4b5563",
    "accent":     "#ef4444",   # красный — основное действие
    "accent_h":   "#dc2626",
    "blue":       "#3b82f6",   # синий — поиск/инфо
    "blue_h":     "#2563eb",
    "green":      "#10b981",   # зелёный — деанонимизация
    "green_h":    "#059669",
    "gray":       "#6b7280",   # серый — второстепенное
    "gray_h":     "#4b5563",
    "text":       "#f3f4f6",
    "text2":      "#9ca3af",
    "text3":      "#6b7280",
    # Маркеры по типам
    "m_surname":  "#fbbf24",   # жёлтый
    "m_org":      "#f97316",   # оранжевый
    "m_city":     "#34d399",   # зелёный
    "m_req":      "#60a5fa",   # голубой
    "m_contact":  "#c084fc",   # сиреневый
    "m_address":  "#fb923c",   # оранж-светлый
    "m_doc":      "#f87171",   # красноватый
}

MARKER_COLORS = {
    "surname":      C["m_surname"],
    "organization": C["m_org"],
    "city":         C["m_city"],
    "inn":          C["m_req"],
    "ogrn":         C["m_req"],
    "kpp":          C["m_req"],
    "bik":          C["m_req"],
    "account":      C["m_req"],
    "snils":        C["m_doc"],
    "passport":     C["m_doc"],
    "phone":        C["m_contact"],
    "email":        C["m_contact"],
    "url":          C["m_contact"],
    "address":      C["m_address"],
}

LEGEND = [
    ("ФИО", C["m_surname"]),
    ("Орг", C["m_org"]),
    ("Город", C["m_city"]),
    ("Рекв", C["m_req"]),
    ("Конт", C["m_contact"]),
    ("Док", C["m_doc"]),
]

FIELD_TYPES = {
    "Организация": {
        "hint_search": "ЛУКОЙЛ",
        "hint_replace": "Northgate Industries Ltd",
        "options_func": get_company_replacement_options,
        "multiline": False,
    },
    "Город": {
        "hint_search": "Москва",
        "hint_replace": "London",
        "options_func": get_city_replacement_options,
        "multiline": False,
    },
    "ФИО подписант": {
        "hint_search": "Петров А.В.",
        "hint_replace": "J.A. Smith",
        "options_func": get_signatory_replacement_options,
        "multiline": False,
    },
    "ФИО участники": {
        "hint_search": "Сидоров\nКозлова",
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

ENGLISH_OPTIONS = {
    "Организация": ["Northgate Industries Ltd", "Meridian Solutions Corp",
                     "Ashford & Partners Inc", "Sterling Dynamics Ltd"],
    "Город": ["London", "Manchester", "Bristol", "Cambridge", "Oxford"],
    "ФИО подписант": ["J.A. Smith", "R.M. Johnson", "D.K. Williams"],
    "ФИО участники": ["Employee #{n}", "Staff Member #{n}"],
}

logger = setup_logging()
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ══════════════════════════════════════════════════════════════
#  FieldRow — один ряд замены
# ══════════════════════════════════════════════════════════════

class FieldRow:
    def __init__(self, parent, field_type, on_delete=None):
        self.field_type = field_type
        self.on_delete = on_delete
        cfg = FIELD_TYPES.get(field_type, FIELD_TYPES["Своё поле"])

        self.frame = ctk.CTkFrame(parent, corner_radius=6, fg_color=C["card"])
        self.frame.pack(fill="x", padx=4, pady=2)

        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=4)

        ctk.CTkLabel(row, text=field_type, width=100, anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MARKER_COLORS.get(
                         {"Организация": "organization", "Город": "city",
                          "ФИО подписант": "surname", "ФИО участники": "surname",
                          "Своё поле": "address"}.get(field_type, "surname"),
                         C["text"])).pack(side="left")

        if cfg["multiline"]:
            self.search_widget = ctk.CTkTextbox(
                self.frame, height=45, corner_radius=4,
                fg_color=C["input"], text_color=C["text"],
                font=ctk.CTkFont(size=11))
            self.search_widget.pack(fill="x", padx=6, pady=(0, 2))
        else:
            self.search_var = ctk.StringVar()
            self.search_widget = ctk.CTkEntry(
                row, textvariable=self.search_var, width=160,
                placeholder_text=cfg["hint_search"],
                fg_color=C["input"], border_color=C["border"],
                text_color=C["text"], font=ctk.CTkFont(size=11))
            self.search_widget.pack(side="left", padx=4, fill="x", expand=True)

        if on_delete:
            ctk.CTkButton(row, text="✕", width=24, height=24,
                          fg_color=C["gray"], hover_color=C["accent"],
                          font=ctk.CTkFont(size=10),
                          command=self._delete).pack(side="right")

        row2 = ctk.CTkFrame(self.frame, fg_color="transparent")
        row2.pack(fill="x", padx=6, pady=(0, 4))

        ctk.CTkLabel(row2, text="→", width=20).pack(side="left")

        self.replace_var = ctk.StringVar(value=cfg["hint_replace"])
        opts = []
        for cat, items in cfg["options_func"]().items():
            opts.extend(items)
        for item in ENGLISH_OPTIONS.get(field_type, []):
            if item not in opts:
                opts.append(item)

        self.replace_combo = ctk.CTkComboBox(
            row2, variable=self.replace_var, values=list(dict.fromkeys(opts)),
            width=200, fg_color=C["input"], border_color=C["border"],
            button_color=C["blue"], button_hover_color=C["blue_h"],
            dropdown_fg_color=C["surface"], dropdown_hover_color=C["card"],
            text_color=C["text"], font=ctk.CTkFont(size=11))
        self.replace_combo.pack(side="left", padx=4, fill="x", expand=True)

    def _delete(self):
        self.frame.destroy()
        if self.on_delete:
            self.on_delete(self)

    def get_search(self):
        cfg = FIELD_TYPES.get(self.field_type, FIELD_TYPES["Своё поле"])
        if cfg["multiline"]:
            return self.search_widget.get("1.0", "end").strip()
        return self.search_var.get().strip()

    def get_replace(self):
        return self.replace_var.get().strip()

    def set_search(self, text):
        cfg = FIELD_TYPES.get(self.field_type, FIELD_TYPES["Своё поле"])
        if cfg["multiline"]:
            self.search_widget.delete("1.0", "end")
            self.search_widget.insert("1.0", text)
        else:
            self.search_var.set(text)

    def set_replace(self, text):
        self.replace_var.set(text)

    def to_dict(self):
        return {"type": self.field_type, "search": self.get_search(), "replace": self.get_replace()}

    def is_empty(self):
        return not self.get_search()


# ══════════════════════════════════════════════════════════════
#  App
# ══════════════════════════════════════════════════════════════

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(1000, 650)

        self.files: list[str] = []
        self.processing = False
        self.cancel_flag = False
        self.all_mappers: list = []
        self.field_rows: list[FieldRow] = []
        self._last_detect_results: list[dict] = []
        self._current_file_entities: list = []

        self._load_saved_config()
        self._build_ui()
        self._bind_hotkeys()
        self._restore_fields()

    # ── Config ──

    def _load_saved_config(self):
        cfg = load_config()
        self._saved_output = cfg.get("output_dir", "")
        self._saved_fields = cfg.get("fields", [])
        if not self._saved_fields:
            old_c = cfg.get("company_name", "")
            old_s = cfg.get("surnames", "")
            if old_c:
                self._saved_fields.append({"type": "Организация", "search": old_c, "replace": cfg.get("company_replacement", "Northgate Industries Ltd")})
            if old_s:
                self._saved_fields.append({"type": "ФИО участники", "search": old_s, "replace": cfg.get("surname_replacement", "Employee #{n}")})

    def _save_current_config(self):
        fields_data = [fr.to_dict() for fr in self.field_rows if not fr.is_empty()]
        save_config({"output_dir": self.output_var.get(), "fields": fields_data})

    def _restore_fields(self):
        if self._saved_fields:
            for fd in self._saved_fields:
                row = self._add_field_row(fd.get("type", "Своё поле"))
                row.set_search(fd.get("search", ""))
                row.set_replace(fd.get("replace", ""))
        else:
            self._add_field_row("Организация")
            self._add_field_row("ФИО участники")

    # ── UI ──

    def _build_ui(self):
        # Верхняя панель — заголовок
        top = ctk.CTkFrame(self, fg_color=C["surface"], height=40, corner_radius=0)
        top.pack(fill="x")
        top.pack_propagate(False)

        ctk.CTkLabel(top, text="TITAN CLEANER",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C["accent"]).pack(side="left", padx=12)
        ctk.CTkLabel(top, text="v4.0",
                     font=ctk.CTkFont(size=11),
                     text_color=C["text3"]).pack(side="left")

        # Легенда цветов
        for name, color in LEGEND:
            ctk.CTkLabel(top, text=f"  {name}", font=ctk.CTkFont(size=10),
                         text_color=color).pack(side="right", padx=2)
        ctk.CTkLabel(top, text="Маркеры:", font=ctk.CTkFont(size=10),
                     text_color=C["text3"]).pack(side="right", padx=(8, 0))

        # Основное тело: две панели
        body = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=0, minsize=320)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ═══ ЛЕВАЯ ПАНЕЛЬ ═══
        left = ctk.CTkScrollableFrame(body, width=310, fg_color=C["bg"], corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")

        # -- Файлы --
        self._section(left, "ФАЙЛЫ")
        files_frame = ctk.CTkFrame(left, fg_color=C["surface"], corner_radius=6)
        files_frame.pack(fill="x", padx=6, pady=(0, 4))

        self.file_list = ctk.CTkTextbox(files_frame, height=70, corner_radius=4,
                                         fg_color=C["input"], text_color=C["text"],
                                         font=ctk.CTkFont(size=10))
        self.file_list.pack(fill="x", padx=6, pady=(6, 2))
        self.file_list.configure(state="disabled")

        fb = ctk.CTkFrame(files_frame, fg_color="transparent")
        fb.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkButton(fb, text="+ Файлы", width=80, height=26,
                      fg_color=C["blue"], hover_color=C["blue_h"],
                      font=ctk.CTkFont(size=11),
                      command=self._add_files).pack(side="left", padx=(0, 4))
        ctk.CTkButton(fb, text="+ Папка", width=80, height=26,
                      fg_color=C["blue"], hover_color=C["blue_h"],
                      font=ctk.CTkFont(size=11),
                      command=self._add_folder).pack(side="left", padx=(0, 4))
        ctk.CTkButton(fb, text="Очистить", width=70, height=26,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      font=ctk.CTkFont(size=11),
                      command=self._clear_files).pack(side="right")

        # -- Замены (сводка) --
        self._section(left, "ЗАМЕНЫ")
        self.summary_frame = ctk.CTkFrame(left, fg_color=C["surface"], corner_radius=6)
        self.summary_frame.pack(fill="x", padx=6, pady=(0, 4))
        self.summary_label = ctk.CTkLabel(self.summary_frame, text="Добавьте файлы для анализа",
                                           font=ctk.CTkFont(size=11),
                                           text_color=C["text2"], wraplength=280, anchor="w")
        self.summary_label.pack(padx=8, pady=6, anchor="w")

        # -- Правила замены --
        self._section(left, "ПРАВИЛА ЗАМЕНЫ")
        self.fields_container = ctk.CTkFrame(left, fg_color="transparent")
        self.fields_container.pack(fill="x", padx=6, pady=(0, 2))

        add_btns = ctk.CTkFrame(left, fg_color="transparent")
        add_btns.pack(fill="x", padx=6, pady=(0, 4))

        btn_cfg = [
            ("+ Орг", "Организация", C["m_org"]),
            ("+ Город", "Город", C["m_city"]),
            ("+ ФИО подп.", "ФИО подписант", C["m_surname"]),
            ("+ ФИО уч.", "ФИО участники", C["m_surname"]),
            ("+ Своё", "Своё поле", C["gray"]),
        ]
        for text, ft, color in btn_cfg:
            ctk.CTkButton(add_btns, text=text, width=58, height=24,
                          fg_color=color, hover_color=C["gray_h"],
                          text_color="#000000" if color in (C["m_surname"], C["m_city"]) else C["text"],
                          font=ctk.CTkFont(size=10),
                          command=lambda n=ft: self._add_field_row(n)
                          ).pack(side="left", padx=1)

        # -- Выделенное (ручное добавление) --
        self._section(left, "ВЫДЕЛЕННОЕ")
        sel_frame = ctk.CTkFrame(left, fg_color=C["surface"], corner_radius=6)
        sel_frame.pack(fill="x", padx=6, pady=(0, 4))

        self.sel_text_label = ctk.CTkLabel(
            sel_frame, text="Выделите текст в предпросмотре\nи нажмите «Добавить»",
            font=ctk.CTkFont(size=11), text_color=C["text3"],
            wraplength=280, justify="left")
        self.sel_text_label.pack(padx=8, pady=(6, 2), anchor="w")

        sel_row = ctk.CTkFrame(sel_frame, fg_color="transparent")
        sel_row.pack(fill="x", padx=8, pady=(2, 2))

        self.sel_type_var = ctk.StringVar(value="Организация")
        ctk.CTkComboBox(sel_row, variable=self.sel_type_var,
                        values=list(FIELD_TYPES.keys()), width=130,
                        fg_color=C["input"], border_color=C["border"],
                        button_color=C["blue"], dropdown_fg_color=C["surface"],
                        text_color=C["text"], font=ctk.CTkFont(size=11)
                        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(sel_row, text="Добавить", width=80, height=26,
                      fg_color=C["blue"], hover_color=C["blue_h"],
                      font=ctk.CTkFont(size=11),
                      command=self._add_selected_text).pack(side="left")

        # -- PDF --
        self._section(left, "PDF")
        pdf_frame = ctk.CTkFrame(left, fg_color=C["surface"], corner_radius=6)
        pdf_frame.pack(fill="x", padx=6, pady=(0, 4))
        pdf_inner = ctk.CTkFrame(pdf_frame, fg_color="transparent")
        pdf_inner.pack(fill="x", padx=8, pady=6)

        self.pdf_mode = ctk.StringVar(value="text")
        ctk.CTkRadioButton(pdf_inner, text="Текст", variable=self.pdf_mode, value="text",
                           fg_color=C["accent"], font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkRadioButton(pdf_inner, text="Штамп", variable=self.pdf_mode, value="stamp",
                           fg_color=C["accent"], font=ctk.CTkFont(size=11)).pack(side="left", padx=8)

        self.stamp_var = ctk.StringVar(value="чёрная плашка")
        ctk.CTkComboBox(pdf_inner, variable=self.stamp_var,
                        values=["чёрная плашка", "ромашка", "замок", "конфиденциально"],
                        width=130, fg_color=C["input"], border_color=C["border"],
                        button_color=C["gray"], dropdown_fg_color=C["surface"],
                        text_color=C["text"], font=ctk.CTkFont(size=10)).pack(side="left")

        ocr_row = ctk.CTkFrame(pdf_frame, fg_color="transparent")
        ocr_row.pack(fill="x", padx=8, pady=(0, 6))
        self.ocr_enabled = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(ocr_row, text="OCR", variable=self.ocr_enabled,
                        fg_color=C["blue"], font=ctk.CTkFont(size=11)).pack(side="left")

        # -- Результат --
        self._section(left, "РЕЗУЛЬТАТ")
        out_frame = ctk.CTkFrame(left, fg_color=C["surface"], corner_radius=6)
        out_frame.pack(fill="x", padx=6, pady=(0, 4))
        out_inner = ctk.CTkFrame(out_frame, fg_color="transparent")
        out_inner.pack(fill="x", padx=6, pady=6)
        self.output_var = ctk.StringVar(value=self._saved_output or "./cleaned")
        ctk.CTkEntry(out_inner, textvariable=self.output_var,
                     fg_color=C["input"], border_color=C["border"],
                     text_color=C["text"], font=ctk.CTkFont(size=11)).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(out_inner, text="...", width=30, height=26,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      command=self._browse_output).pack(side="right")

        # -- Лог --
        self._section(left, "ЛОГ")
        self.log_text = ctk.CTkTextbox(left, height=80, corner_radius=4,
                                        fg_color=C["input"], text_color=C["text"],
                                        font=ctk.CTkFont(family="Consolas", size=10))
        self.log_text.pack(fill="x", padx=6, pady=(0, 4))
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("success", foreground=C["green"])
        self.log_text.tag_config("warning", foreground=C["m_surname"])
        self.log_text.tag_config("error", foreground=C["accent"])
        self.log_text.tag_config("info", foreground=C["blue"])

        # -- Прогресс --
        self.progress = ctk.CTkProgressBar(left, progress_color=C["accent"],
                                            fg_color=C["border"], height=8)
        self.progress.pack(fill="x", padx=6, pady=(0, 2))
        self.progress.set(0)
        self.progress_label = ctk.CTkLabel(left, text="", font=ctk.CTkFont(size=10),
                                            text_color=C["text3"])
        self.progress_label.pack(anchor="w", padx=8)

        # ═══ ПРАВАЯ ПАНЕЛЬ — ПРЕДПРОСМОТР ═══
        right = ctk.CTkFrame(body, fg_color=C["surface"], corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew", padx=(2, 0))

        # Заголовок
        preview_header = ctk.CTkFrame(right, fg_color="transparent", height=36)
        preview_header.pack(fill="x", padx=8, pady=(6, 0))
        preview_header.pack_propagate(False)

        ctk.CTkLabel(preview_header, text="ПРЕДПРОСМОТР",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack(side="left")

        self.found_label = ctk.CTkLabel(preview_header, text="",
                                         font=ctk.CTkFont(size=11),
                                         text_color=C["text2"])
        self.found_label.pack(side="right", padx=4)

        # Выбор файла
        self.preview_file_var = ctk.StringVar(value="")
        self.preview_file_combo = ctk.CTkComboBox(
            preview_header, variable=self.preview_file_var, values=[""],
            width=250, fg_color=C["input"], border_color=C["border"],
            button_color=C["blue"], dropdown_fg_color=C["surface"],
            dropdown_hover_color=C["card"], text_color=C["text"],
            font=ctk.CTkFont(size=11),
            command=self._on_preview_file_changed)
        self.preview_file_combo.pack(side="right", padx=4)

        # Текст документа
        self.preview_text = ctk.CTkTextbox(
            right, corner_radius=4,
            fg_color=C["input"], text_color=C["text"],
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word")
        self.preview_text.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        # Настраиваем теги маркеров
        for etype, color in MARKER_COLORS.items():
            self.preview_text.tag_config(f"m_{etype}", foreground="#000000", background=color)
        self.preview_text.tag_config("page_sep", foreground=C["text3"])
        self.preview_text.tag_config("sel_highlight", background=C["blue"], foreground="#ffffff")

        # Привязка выделения текста
        self.preview_text.bind("<<Selection>>", self._on_text_selected)
        self.preview_text.bind("<ButtonRelease-1>", self._on_text_selected)

        # ═══ НИЖНЯЯ ПАНЕЛЬ — КНОПКИ ═══
        bottom = ctk.CTkFrame(self, fg_color=C["surface"], height=80, corner_radius=0)
        bottom.pack(fill="x")
        bottom.pack_propagate(False)

        btn_row = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_row.pack(pady=8)

        # Главные кнопки — одинакового размера
        btn_w, btn_h = 160, 38
        self.btn_detect = ctk.CTkButton(
            btn_row, text="АВТОПОИСК", width=btn_w, height=btn_h,
            fg_color=C["blue"], hover_color=C["blue_h"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._auto_detect_start)
        self.btn_detect.pack(side="left", padx=6)

        self.btn_process = ctk.CTkButton(
            btn_row, text="ОБРАБОТАТЬ", width=btn_w, height=btn_h,
            fg_color=C["accent"], hover_color=C["accent_h"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_processing)
        self.btn_process.pack(side="left", padx=6)

        self.btn_deanon = ctk.CTkButton(
            btn_row, text="ДЕАНОНИМИЗАЦИЯ", width=btn_w, height=btn_h,
            fg_color=C["green"], hover_color=C["green_h"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._deanon_panel)
        self.btn_deanon.pack(side="left", padx=6)

        # Второстепенные
        btn_row2 = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_row2.pack()

        ctk.CTkButton(btn_row2, text="История замен", width=110, height=26,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      font=ctk.CTkFont(size=11),
                      command=self._show_history).pack(side="left", padx=4)
        ctk.CTkButton(btn_row2, text="Карта замен", width=100, height=26,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      font=ctk.CTkFont(size=11),
                      command=self._show_replacement_map).pack(side="left", padx=4)
        self.btn_cancel = ctk.CTkButton(
            btn_row2, text="Отмена", width=80, height=26,
            fg_color=C["gray"], hover_color=C["accent"],
            font=ctk.CTkFont(size=11), state="disabled",
            command=self._cancel)
        self.btn_cancel.pack(side="left", padx=4)

        # ═══ СТАТУС-БАР ═══
        status = ctk.CTkFrame(self, fg_color=C["card"], height=24, corner_radius=0)
        status.pack(fill="x")
        status.pack_propagate(False)
        self.status_var = ctk.StringVar(value="Готов к работе")
        ctk.CTkLabel(status, textvariable=self.status_var,
                     font=ctk.CTkFont(size=10), text_color=C["text2"]).pack(side="left", padx=8)

    def _section(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["text2"], anchor="w").pack(fill="x", padx=8, pady=(8, 2))

    # ── Field rows ──

    def _add_field_row(self, field_type):
        row = FieldRow(self.fields_container, field_type, on_delete=self._remove_field_row)
        self.field_rows.append(row)
        return row

    def _remove_field_row(self, row):
        if row in self.field_rows:
            self.field_rows.remove(row)

    # ── Hotkeys ──

    def _bind_hotkeys(self):
        self.bind_all("<Control-o>", lambda e: self._add_files())
        self.bind_all("<Control-Return>", lambda e: self._start_processing())
        self.bind_all("<Escape>", lambda e: self._cancel())

    # ── Files ──

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Выберите файлы",
            filetypes=[("Документы", "*.docx *.pdf *.xlsx *.xls"), ("Все", "*.*")])
        added = False
        for p in paths:
            if is_valid_file(p) and p not in self.files:
                self.files.append(p)
                added = True
        if added:
            self._refresh_file_list()
            self._update_status()
            self._auto_detect_start()  # автопоиск при добавлении

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку")
        if not folder:
            return
        added = False
        for root, dirs, fns in os.walk(folder):
            for fn in fns:
                fp = os.path.join(root, fn)
                if is_valid_file(fp) and fp not in self.files:
                    self.files.append(fp)
                    added = True
        if added:
            self._refresh_file_list()
            self._update_status()
            self._auto_detect_start()

    def _refresh_file_list(self):
        self.file_list.configure(state="normal")
        self.file_list.delete("1.0", "end")
        for f in self.files:
            self.file_list.insert("end", Path(f).name + "\n")
        self.file_list.configure(state="disabled")

    def _clear_files(self):
        self.files.clear()
        self._last_detect_results.clear()
        self._refresh_file_list()
        self._update_status()
        self._clear_preview()

    def _browse_output(self):
        f = filedialog.askdirectory(title="Папка результатов")
        if f:
            self.output_var.set(f)

    def _update_status(self):
        n = len(self.files)
        dc = sum(1 for f in self.files if f.lower().endswith('.docx'))
        pc = sum(1 for f in self.files if f.lower().endswith('.pdf'))
        xc = sum(1 for f in self.files if f.lower().endswith(('.xlsx', '.xls')))
        self.status_var.set(f"Файлов: {n}  (DOCX:{dc}  PDF:{pc}  Excel:{xc})")

    # ── Logging ──

    def _log(self, msg, tag="info"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        logger.info(msg)

    # ── Preview ──

    def _clear_preview(self):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.configure(state="disabled")
        self.found_label.configure(text="")
        self.preview_file_combo.configure(values=[""])
        self.preview_file_var.set("")

    def _show_preview(self, all_results):
        """Показывает текст первого файла с подсветкой."""
        self._last_detect_results = all_results
        file_names = [Path(r["filepath"]).name for r in all_results]
        self.preview_file_combo.configure(values=file_names)
        if file_names:
            self.preview_file_var.set(file_names[0])
            self._render_file_preview(all_results[0])

        # Обновляем сводку замен
        total = 0
        type_counts = {}
        for res in all_results:
            for e in res.get("entities", []):
                total += 1
                type_counts[e.entity_type] = type_counts.get(e.entity_type, 0) + 1

        parts = [f"Всего: {total}"]
        for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            parts.append(f"{get_type_name(etype)}: {count}")
        self.summary_label.configure(text="  |  ".join(parts))
        self.found_label.configure(text=f"Найдено: {total}")

    def _on_preview_file_changed(self, choice=None):
        fname = self.preview_file_var.get()
        for r in self._last_detect_results:
            if Path(r["filepath"]).name == fname:
                self._render_file_preview(r)
                return

    def _render_file_preview(self, result):
        """Рендерит текст документа с подсветкой маркеров."""
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")

        pages = result.get("pages", {})
        entities = result.get("entities", [])
        full_text = result.get("text", "")
        self._current_file_entities = entities

        if not pages and full_text:
            pages = {1: full_text}

        if not pages:
            self.preview_text.insert("end", "(нет текста)")
            self.preview_text.configure(state="disabled")
            return

        text_offset = 0
        for page_num in sorted(pages.keys()):
            page_text = pages[page_num]
            if not page_text.strip():
                text_offset += len(page_text)
                continue

            if page_num > 1 or len(pages) > 1:
                self.preview_text.insert("end", f"\n── стр. {page_num} ──\n", "page_sep")

            page_start = text_offset
            page_end = text_offset + len(page_text)
            page_entities = sorted(
                [e for e in entities if e.start >= page_start and e.end <= page_end],
                key=lambda e: e.start)

            pos = 0
            for e in page_entities:
                local_start = e.start - page_start
                local_end = e.end - page_start
                if local_start < pos:
                    continue
                if local_start > pos:
                    self.preview_text.insert("end", page_text[pos:local_start])
                tag = f"m_{e.entity_type}"
                self.preview_text.insert("end", page_text[local_start:local_end], tag)
                pos = local_end

            if pos < len(page_text):
                self.preview_text.insert("end", page_text[pos:])

            text_offset += len(page_text)

        self.preview_text.configure(state="disabled")

    def _on_text_selected(self, event=None):
        """Обработка выделения текста в предпросмотре."""
        try:
            sel = self.preview_text.selection_get()
            sel = sel.strip()
            if sel and len(sel) > 1:
                self.sel_text_label.configure(
                    text=f"«{sel[:60]}{'...' if len(sel) > 60 else ''}»",
                    text_color=C["text"])
                self._pending_selection = sel
            else:
                self._pending_selection = None
        except (tk.TclError, Exception):
            self._pending_selection = None

    def _add_selected_text(self):
        """Добавляет выделенный текст как правило замены."""
        sel = getattr(self, '_pending_selection', None)
        if not sel:
            messagebox.showinfo("Выделение", "Выделите текст в предпросмотре мышкой.")
            return
        ft = self.sel_type_var.get()
        row = self._add_field_row(ft)
        row.set_search(sel)
        self.sel_text_label.configure(text=f"Добавлено: «{sel[:40]}»", text_color=C["green"])
        self._pending_selection = None

    # ── Auto-detect ──

    def _auto_detect_start(self):
        if not self.files:
            return
        self._log("Автопоиск...", "info")
        self.status_var.set("Автопоиск...")
        self.btn_detect.configure(state="disabled")
        thread = threading.Thread(target=self._auto_detect_worker, daemon=True)
        thread.start()

    def _auto_detect_worker(self):
        _reset_counters()
        _replacement_cache.clear()
        results = []
        for fp in self.files:
            r = auto_detect_in_file(fp)
            results.append(r)
            n = len(r.get("entities", []))
            fname = Path(fp).name
            if r.get("error"):
                self.after(0, lambda m=f"X {fname}: {r['error']}": self._log(m, "error"))
            else:
                self.after(0, lambda m=f"  {fname}: {n} сущностей": self._log(m, "info"))

        self.after(0, lambda: self._show_preview(results))
        self.after(0, lambda: self.status_var.set("Автопоиск завершён"))
        self.after(0, lambda: self.btn_detect.configure(state="normal"))

    # ── Build rules ──

    def _build_replacement_rules(self):
        rules = []
        self.all_mappers = []
        for row in self.field_rows:
            if row.is_empty():
                continue
            search, replace, ft = row.get_search(), row.get_replace(), row.field_type
            if ft == "Организация":
                rules.append({"patterns": build_company_patterns(search), "replacement": replace, "type": "company"})
            elif ft == "Город":
                rules.append({"patterns": build_city_patterns(search), "replacement": replace, "type": "city"})
            elif ft == "ФИО подписант":
                sp = SurnamePattern(search, search_with_initials=True, search_feminine=True)
                rules.append({"patterns": sp.get_all_patterns_sorted(), "replacement": replace, "type": "signatory"})
            elif ft == "ФИО участники":
                mapper = ReplacementMapper(replace)
                self.all_mappers.append(mapper)
                pats = []
                for line in search.split('\n'):
                    for s in line.strip().split(','):
                        s = s.strip()
                        if s:
                            sp = SurnamePattern(s, search_with_initials=True, search_feminine=True)
                            pats.extend(sp.get_all_patterns_sorted())
                if pats:
                    rules.append({"patterns": pats, "mapper": mapper, "type": "surnames"})
            elif ft == "Своё поле":
                rules.append({"patterns": build_custom_patterns(search), "replacement": replace, "type": "custom"})
        return rules

    def _collect_mapping_list(self, rules):
        """Собирает список маппингов из правил для сохранения в БД."""
        result = []
        for rule in rules:
            if "mapper" in rule:
                for orig, repl in rule["mapper"].get_map().items():
                    result.append({"original": orig, "pseudonym": repl, "entity_type": rule.get("type", "")})
            elif "replacement" in rule:
                for pat in rule["patterns"]:
                    result.append({"original": pat.pattern, "pseudonym": rule["replacement"], "entity_type": rule.get("type", "")})
        # Для автозамены — из entities
        for res in self._last_detect_results:
            for e in res.get("entities", []):
                result.append({"original": e.text, "pseudonym": e.replacement, "entity_type": e.entity_type})
        # Убираем дубли
        seen = set()
        unique = []
        for m in result:
            key = (m["original"].lower(), m["pseudonym"])
            if key not in seen:
                seen.add(key)
                unique.append(m)
        return unique

    def _get_stamp_path(self):
        stamp_name = self.stamp_var.get()
        if stamp_name == "чёрная плашка":
            return None
        assets_dir = get_assets_dir()
        stamp_map = {"ромашка": "daisy.png", "замок": "lock.png", "конфиденциально": "confidential.png"}
        fn = stamp_map.get(stamp_name)
        if fn:
            p = assets_dir / "stamps" / fn
            if p.exists():
                return str(p)
        return None

    # ── Processing ──

    def _validate(self):
        has_rules = any(not r.is_empty() for r in self.field_rows)
        has_auto = bool(self._last_detect_results and any(r.get("entities") for r in self._last_detect_results))
        if not has_rules and not has_auto:
            messagebox.showwarning("Внимание", "Нет правил замены.\nЗапустите автопоиск или добавьте правила вручную.")
            return False
        if not self.files:
            messagebox.showwarning("Внимание", "Добавьте файлы.")
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

        # Определяем режим: ручные правила или автозамена
        has_rules = any(not r.is_empty() for r in self.field_rows)
        if has_rules:
            thread = threading.Thread(target=self._process_manual, daemon=True)
        else:
            thread = threading.Thread(target=self._process_auto, daemon=True)
        thread.start()

    def _cancel(self):
        if self.processing:
            self.cancel_flag = True
            self._log("Отмена...", "warning")

    def _process_manual(self):
        """Обработка с ручными правилами."""
        rules = self._build_replacement_rules()
        output_dir = self.output_var.get()
        try:
            ensure_output_dir(output_dir)
        except Exception as e:
            self.after(0, lambda: self._log(f"Ошибка папки: {e}", "error"))
            self._finish()
            return

        db = SessionDB()
        db.start_session()
        total_matches = {}
        n = len(self.files)

        for i, fp in enumerate(self.files):
            if self.cancel_flag:
                break
            fn = Path(fp).name
            ext = Path(fp).suffix.lower()
            out = str(Path(output_dir) / fn)
            if os.path.abspath(fp) == os.path.abspath(out):
                out = str(Path(output_dir) / f"{Path(fp).stem}_cleaned{ext}")

            self.after(0, lambda f=fn: self.progress_label.configure(text=f))
            try:
                if ext == '.docx':
                    res = clean_docx(fp, out, rules)
                elif ext == '.pdf':
                    if self.pdf_mode.get() == "text":
                        res = clean_pdf_text_mode(fp, out, rules, ocr_enabled=self.ocr_enabled.get())
                    else:
                        res = clean_pdf_stamp_mode(fp, out, rules, stamp_path=self._get_stamp_path(),
                                                    stamp_type=self.stamp_var.get(), ocr_enabled=self.ocr_enabled.get())
                elif ext in ('.xlsx', '.xls'):
                    res = clean_xlsx(fp, out, rules)
                else:
                    continue

                matches = res.get("matches", {})
                for k, v in matches.items():
                    total_matches[k] = total_matches.get(k, 0) + v
                total_file = sum(matches.values()) if matches else 0

                # Сохраняем маппинг в БД для этого файла
                mapping_list = self._collect_mapping_list(rules)
                db.save_file_mappings(fn, Path(out).name, mapping_list)

                if res.get("status") == "success" and total_file > 0:
                    d = ", ".join(f"{k}:{v}" for k, v in matches.items())
                    self.after(0, lambda m=f"OK {fn} — {d}": self._log(m, "success"))
                else:
                    self.after(0, lambda f=fn: self._log(f"! {f} — 0 замен", "warning"))
            except Exception as e:
                self.after(0, lambda m=f"X {fn}: {e}": self._log(m, "error"))

            self.after(0, lambda v=(i+1)/n: self.progress.set(v))

        db.close()
        summary = ", ".join(f"{k}:{v}" for k, v in total_matches.items()) if total_matches else "замен нет"
        self.after(0, lambda: self._log(f"Готово. {summary}", "info"))
        self.after(0, lambda: self.progress_label.configure(text=f"Готово. {summary}"))
        self._finish()

    def _process_auto(self):
        """Обработка с автодетекцией."""
        output_dir = self.output_var.get()
        try:
            ensure_output_dir(output_dir)
        except Exception as e:
            self.after(0, lambda: self._log(f"Ошибка папки: {e}", "error"))
            self._finish()
            return

        db = SessionDB()
        db.start_session()
        total_matches = {}
        results = self._last_detect_results if self._last_detect_results else []

        # Если автопоиск не был запущен — запускаем
        if not results:
            for fp in self.files:
                results.append(auto_detect_in_file(fp))

        n = len(results)
        for i, result in enumerate(results):
            if self.cancel_flag:
                break
            fp = result["filepath"]
            fn = Path(fp).name
            ext = Path(fp).suffix.lower()
            out = str(Path(output_dir) / fn)
            if os.path.abspath(fp) == os.path.abspath(out):
                out = str(Path(output_dir) / f"{Path(fp).stem}_cleaned{ext}")

            entities = result.get("entities", [])
            if not entities:
                self.after(0, lambda f=fn: self._log(f"! {f} — 0 сущностей", "warning"))
                self.after(0, lambda v=(i+1)/n: self.progress.set(v))
                continue

            self.after(0, lambda f=fn: self.progress_label.configure(text=f))
            rules = self._entities_to_rules(entities)

            try:
                if ext == '.docx':
                    res = clean_docx(fp, out, rules)
                elif ext == '.pdf':
                    res = clean_pdf_text_mode(fp, out, rules)
                elif ext in ('.xlsx', '.xls'):
                    res = clean_xlsx(fp, out, rules)
                else:
                    continue

                matches = res.get("matches", {})
                for k, v in matches.items():
                    total_matches[k] = total_matches.get(k, 0) + v
                total_file = sum(matches.values()) if matches else 0

                # Маппинг в БД — для каждого файла отдельно
                mapping_list = [{"original": e.text, "pseudonym": e.replacement, "entity_type": e.entity_type} for e in entities]
                db.save_file_mappings(fn, Path(out).name, mapping_list)

                if res.get("status") == "success" and total_file > 0:
                    d = ", ".join(f"{k}:{v}" for k, v in matches.items())
                    self.after(0, lambda m=f"OK {fn} — {d}": self._log(m, "success"))
                else:
                    self.after(0, lambda f=fn: self._log(f"! {f} — 0 замен", "warning"))
            except Exception as e:
                self.after(0, lambda m=f"X {fn}: {e}": self._log(m, "error"))

            self.after(0, lambda v=(i+1)/n: self.progress.set(v))

        db.close()
        summary = ", ".join(f"{k}:{v}" for k, v in total_matches.items()) if total_matches else "замен нет"
        self.after(0, lambda: self._log(f"Готово. {summary}", "info"))
        self.after(0, lambda: self.progress_label.configure(text=f"Готово. {summary}"))
        self._finish()

    @staticmethod
    def _entities_to_rules(entities):
        rules = []
        seen = set()
        for e in entities:
            escaped = re.escape(e.text)
            key = (escaped, e.replacement)
            if key in seen:
                continue
            seen.add(key)
            rules.append({"patterns": [re.compile(escaped, re.IGNORECASE)],
                          "replacement": e.replacement, "type": e.entity_type})
        rules.sort(key=lambda r: len(r["patterns"][0].pattern), reverse=True)
        return rules

    def _finish(self):
        self.processing = False
        self.after(0, lambda: self.btn_process.configure(state="normal"))
        self.after(0, lambda: self.btn_cancel.configure(state="disabled"))

    # ── Deanonymization panel ──

    def _deanon_panel(self):
        win = ctk.CTkToplevel(self)
        win.title("Деанонимизация")
        win.geometry("750x550")
        win.transient(self)

        ctk.CTkLabel(win, text="ДЕАНОНИМИЗАЦИЯ",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C["green"]).pack(padx=16, pady=(12, 4))

        # Поиск в базе
        search_frame = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=8)
        search_frame.pack(fill="x", padx=16, pady=4)

        sf_inner = ctk.CTkFrame(search_frame, fg_color="transparent")
        sf_inner.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(sf_inner, text="Поиск в базе:", width=100, anchor="w").pack(side="left")
        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(sf_inner, textvariable=search_var, width=300,
                                     placeholder_text="имя файла...",
                                     fg_color=C["input"], border_color=C["border"],
                                     text_color=C["text"])
        search_entry.pack(side="left", padx=4, fill="x", expand=True)

        # Список файлов из БД
        list_frame = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=8)
        list_frame.pack(fill="both", expand=True, padx=16, pady=4)

        file_list_text = ctk.CTkTextbox(list_frame, corner_radius=4,
                                         fg_color=C["input"], text_color=C["text"],
                                         font=ctk.CTkFont(family="Consolas", size=11))
        file_list_text.pack(fill="both", expand=True, padx=8, pady=8)
        file_list_text.tag_config("header", foreground=C["blue"])
        file_list_text.tag_config("item", foreground=C["text"])
        file_list_text.tag_config("selected_item", foreground=C["green"])

        selected_fm_id = [None]  # mutable container

        def refresh_list(*args):
            q = search_var.get().strip()
            files = SessionDB.search_files(q)
            file_list_text.configure(state="normal")
            file_list_text.delete("1.0", "end")
            file_list_text.insert("end",
                f"{'#':>4}  {'Файл':<30} {'Дата':<20} {'Замен':>6}\n", "header")
            file_list_text.insert("end", "─" * 70 + "\n", "header")
            for f in files:
                line = f"#{f['id']:>3}  {f['source_filename']:<30} {f['created_at']:<20} {f['total_replacements']:>6}\n"
                file_list_text.insert("end", line, "item")
            file_list_text.configure(state="disabled")
            if files:
                selected_fm_id[0] = files[0]["id"]
            else:
                selected_fm_id[0] = None

        search_var.trace_add("write", refresh_list)
        refresh_list()

        # Клик по строке для выбора
        def on_click(event):
            try:
                index = file_list_text.index(f"@{event.x},{event.y}")
                line_num = int(index.split(".")[0])
                if line_num <= 2:  # заголовок
                    return
                q = search_var.get().strip()
                files = SessionDB.search_files(q)
                idx = line_num - 3
                if 0 <= idx < len(files):
                    selected_fm_id[0] = files[idx]["id"]
                    # Подсветка
                    file_list_text.configure(state="normal")
                    file_list_text.tag_remove("selected_item", "1.0", "end")
                    file_list_text.tag_add("selected_item", f"{line_num}.0", f"{line_num}.end")
                    file_list_text.configure(state="disabled")
                    # Показать маппинг
                    show_mappings(files[idx]["id"])
            except Exception:
                pass

        file_list_text.bind("<Button-1>", on_click)

        # Маппинг выбранного файла
        map_frame = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=8)
        map_frame.pack(fill="x", padx=16, pady=4)

        map_text = ctk.CTkTextbox(map_frame, height=100, corner_radius=4,
                                   fg_color=C["input"], text_color=C["text"],
                                   font=ctk.CTkFont(family="Consolas", size=10))
        map_text.pack(fill="x", padx=8, pady=8)
        map_text.tag_config("pseudo", foreground=C["m_org"])
        map_text.tag_config("arrow", foreground=C["text3"])
        map_text.tag_config("orig", foreground=C["green"])

        def show_mappings(fm_id):
            mappings = SessionDB.get_file_mappings(fm_id)
            map_text.configure(state="normal")
            map_text.delete("1.0", "end")
            for m in mappings[:20]:
                map_text.insert("end", m["pseudonym"], "pseudo")
                map_text.insert("end", "  ←  ", "arrow")
                map_text.insert("end", m["original"] + "\n", "orig")
            if len(mappings) > 20:
                map_text.insert("end", f"...ещё {len(mappings) - 20}\n", "arrow")
            map_text.configure(state="disabled")

        # Файл для деанонимизации
        doc_frame = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=8)
        doc_frame.pack(fill="x", padx=16, pady=4)
        doc_inner = ctk.CTkFrame(doc_frame, fg_color="transparent")
        doc_inner.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(doc_inner, text="Документ:", width=80, anchor="w").pack(side="left")
        doc_var = ctk.StringVar()
        ctk.CTkEntry(doc_inner, textvariable=doc_var, fg_color=C["input"],
                     border_color=C["border"], text_color=C["text"]).pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkButton(doc_inner, text="...", width=30, height=26,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      command=lambda: doc_var.set(
                          filedialog.askopenfilename(title="Документ",
                              filetypes=[("Документы", "*.docx *.pdf *.xlsx"), ("Все", "*.*")]) or doc_var.get()
                      )).pack(side="right")

        # Результат
        result_label = ctk.CTkLabel(win, text="", font=ctk.CTkFont(size=12), text_color=C["text2"])
        result_label.pack(padx=16, pady=2)

        def run_deanon():
            fm_id = selected_fm_id[0]
            doc_path = doc_var.get().strip()
            if not fm_id:
                messagebox.showwarning("Внимание", "Выберите файл из базы.")
                return
            if not doc_path or not Path(doc_path).exists():
                messagebox.showwarning("Внимание", "Укажите документ для деанонимизации.")
                return

            result_label.configure(text="Деанонимизация...", text_color=C["blue"])
            win.update()

            try:
                reverse_rules = SessionDB.get_reverse_rules(fm_id)
                ext = Path(doc_path).suffix.lower()
                out_path = str(Path(doc_path).parent / f"{Path(doc_path).stem}_restored{ext}")

                if ext == ".docx":
                    res = clean_docx(doc_path, out_path, reverse_rules)
                elif ext == ".pdf":
                    res = clean_pdf_text_mode(doc_path, out_path, reverse_rules)
                elif ext in (".xlsx", ".xls"):
                    res = clean_xlsx(doc_path, out_path, reverse_rules)
                else:
                    result_label.configure(text=f"Формат {ext} не поддерживается", text_color=C["accent"])
                    return

                total = sum(res.get("matches", {}).values()) if res.get("matches") else 0
                result_label.configure(text=f"Готово! Восстановлено: {total} замен → {out_path}",
                                        text_color=C["green"])
                self._log(f"Деанонимизация: {Path(doc_path).name} → {total} замен", "success")
            except Exception as e:
                result_label.configure(text=f"Ошибка: {e}", text_color=C["accent"])

        ctk.CTkButton(win, text="ДЕАНОНИМИЗИРОВАТЬ", width=200, height=38,
                      fg_color=C["green"], hover_color=C["green_h"],
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=run_deanon).pack(pady=(4, 12))

    # ── History ──

    def _show_history(self):
        win = ctk.CTkToplevel(self)
        win.title("История замен")
        win.geometry("700x450")
        win.transient(self)

        text = ctk.CTkTextbox(win, corner_radius=6, fg_color=C["input"],
                               text_color=C["text"],
                               font=ctk.CTkFont(family="Consolas", size=11))
        text.pack(fill="both", expand=True, padx=12, pady=12)
        text.tag_config("header", foreground=C["blue"])

        sessions = SessionDB.get_all_sessions()
        text.insert("end", f"{'#':>4}  {'Дата':<20}  {'Замен':>6}  {'Файлы'}\n", "header")
        text.insert("end", "─" * 80 + "\n", "header")
        for s in sessions:
            files_str = s.get("files") or "(нет файлов)"
            text.insert("end", f"#{s['id']:>3}  {s['created_at']:<20}  {s['total_replacements']:>6}  {files_str}\n")
        text.configure(state="disabled")

    # ── Replacement map ──

    def _show_replacement_map(self):
        all_mappings = {}
        for mapper in self.all_mappers:
            all_mappings.update(mapper.get_map())
        for res in self._last_detect_results:
            for e in res.get("entities", []):
                all_mappings[e.text] = e.replacement

        if not all_mappings:
            messagebox.showinfo("Карта замен", "Нет данных. Запустите автопоиск или обработку.")
            return

        win = ctk.CTkToplevel(self)
        win.title("Карта замен (текущий сеанс)")
        win.geometry("600x400")
        win.transient(self)

        text = ctk.CTkTextbox(win, corner_radius=6, fg_color=C["input"],
                               text_color=C["text"],
                               font=ctk.CTkFont(family="Consolas", size=11))
        text.pack(fill="both", expand=True, padx=12, pady=12)
        text.tag_config("orig", foreground=C["accent"])
        text.tag_config("arrow", foreground=C["text3"])
        text.tag_config("repl", foreground=C["green"])

        for orig, repl in all_mappings.items():
            text.insert("end", orig, "orig")
            text.insert("end", "  →  ", "arrow")
            text.insert("end", repl + "\n", "repl")
        text.configure(state="disabled")

        def export_csv():
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
            if path:
                with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(["Оригинал", "Замена"])
                    for o, r in all_mappings.items():
                        w.writerow([o, r])
                messagebox.showinfo("Экспорт", f"Сохранено: {path}")

        ctk.CTkButton(win, text="Экспорт CSV", width=120, height=28,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      command=export_csv).pack(pady=(0, 12))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
