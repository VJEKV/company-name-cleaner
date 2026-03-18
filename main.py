"""
Titan Cleaner v4.2 — портативное GUI-приложение.
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

APP_TITLE = "Titan Cleaner v4.2"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 860


def _make_readonly(textbox):
    """Делает CTkTextbox readonly, но с возможностью выделения мышью и Ctrl+C/Ctrl+A."""
    inner = textbox._textbox  # внутренний tk.Text виджет

    def _block_input(event):
        # Разрешаем: Ctrl+C, Ctrl+A
        if event.state & 0x4:  # Ctrl
            if event.keysym.lower() in ('c', 'a'):
                return
        # Разрешаем навигацию
        if event.keysym in ('Left', 'Right', 'Up', 'Down', 'Home', 'End',
                            'Prior', 'Next', 'Shift_L', 'Shift_R',
                            'Control_L', 'Control_R'):
            return
        return "break"

    inner.bind("<Key>", _block_input)
    inner.bind("<<Paste>>", lambda e: "break")
    inner.bind("<<Cut>>", lambda e: "break")

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
    ("Адрес", C["m_address"]),
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
    "Адрес": {
        "hint_search": "ул. Ленина, д.5",
        "hint_replace": "123 Baker Street",
        "options_func": get_generic_replacement_options,
        "multiline": False,
    },
    "Своё поле": {
        "hint_search": "ИНН 7707083893",
        "hint_replace": "TIN XXXXXXXXXX",
        "options_func": get_generic_replacement_options,
        "multiline": False,
    },
}

ENGLISH_OPTIONS = {
    "Организация": [
        "Northgate Industries Ltd", "Meridian Solutions Corp",
        "Ashford & Partners Inc", "Sterling Dynamics Ltd",
        "Blackwood Engineering Co", "Harrington Global Services",
        "Crossfield Manufacturing Ltd", "Whitmore Technical Group",
        "Oakridge Systems Inc", "Pemberton & Hayes Ltd",
        "Kingsford Logistics Co", "Silverdale Resources Ltd",
        "Thornhill Enterprises Inc", "Westbrook Capital Ltd",
        "Briarwood Solutions Group", "Fairmont Industrial Corp",
        "Eastgate Trading Ltd", "Hillcrest Energy Inc",
        "Lockwood & Associates", "Crestview Holdings Ltd",
        "Hartfield Services Corp", "Redstone Technologies Ltd",
        "Clearwater Industries Inc", "Alderton Group Ltd",
        "Foxwell Engineering Co", "Brookside Chemicals Ltd",
        "Glenmore Supply Chain Inc", "Whitehall Consulting Ltd",
        "Langford Construction Co", "Riverside Petroleum Ltd",
    ],
    "Город": [
        "London", "Manchester", "Bristol", "Cambridge", "Oxford",
        "Liverpool", "Birmingham", "Edinburgh", "Glasgow", "Leeds",
        "Sheffield", "Nottingham", "Brighton", "York", "Bath",
        "Canterbury", "Durham", "Chester", "Exeter", "Lancaster",
        "Winchester", "Plymouth", "Norwich", "Derby", "Coventry",
        "Bradford", "Leicester", "Aberdeen", "Dundee", "Inverness",
    ],
    "ФИО подписант": [
        "J.A. Smith", "R.M. Johnson", "D.K. Williams", "M.T. Brown",
        "S.L. Davis", "P.R. Anderson", "C.J. Taylor", "B.N. Thomas",
        "A.W. Moore", "G.E. Jackson", "H.F. Martin", "K.D. Lee",
        "W.P. Thompson", "N.C. White", "E.S. Harris", "T.B. Clark",
        "L.G. Lewis", "F.H. Robinson", "I.M. Walker", "O.R. Young",
    ],
    "ФИО участники": [
        "Employee #{n}", "Staff Member #{n}", "Specialist #{n}",
        "Worker #{n}", "Associate #{n}", "Team Member #{n}",
    ],
    "Адрес": [
        "123 Baker Street", "456 Oak Avenue", "789 Elm Road",
        "10 Downing Street", "[АДРЕС]", "███████",
    ],
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
                          "Адрес": "address", "Своё поле": "address"}.get(field_type, "surname"),
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
        # Сначала английские (основные), потом русские опции
        eng = ENGLISH_OPTIONS.get(field_type, [])
        rus = []
        for cat, items in cfg["options_func"]().items():
            rus.extend(items)
        # Собираем: английские первые, затем разделитель, затем русские
        opts = list(eng)
        if eng and rus:
            opts.append("── Русские ──")
        for item in rus:
            if item not in opts:
                opts.append(item)

        self._all_opts = list(dict.fromkeys(opts))
        self.replace_combo = ctk.CTkComboBox(
            row2, variable=self.replace_var, values=self._all_opts,
            width=200, fg_color=C["input"], border_color=C["border"],
            button_color=C["blue"], button_hover_color=C["blue_h"],
            dropdown_fg_color=C["surface"], dropdown_hover_color=C["card"],
            text_color=C["text"], font=ctk.CTkFont(size=11))
        self.replace_combo.pack(side="left", padx=4, fill="x", expand=True)

    def update_used_marks(self, used_replacements: set):
        """Обновляет выпадающий список: занятые отмечены ✓."""
        marked = []
        for opt in self._all_opts:
            if opt in used_replacements:
                marked.append(f"✓ {opt}")
            else:
                marked.append(f"  {opt}")
        self.replace_combo.configure(values=marked)

    def get_next_free(self, used_replacements: set) -> str | None:
        """Возвращает следующую свободную замену из пула."""
        for opt in self._all_opts:
            if opt.startswith("──"):
                continue
            if opt not in used_replacements:
                return opt
        return None

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
        val = self.replace_var.get().strip()
        # Убираем маркер занятости
        if val.startswith("✓ "):
            val = val[2:]
        return val

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
        self.minsize(1100, 700)

        self.files: list[str] = []
        self.processing = False
        self.cancel_flag = False
        self.all_mappers: list = []
        self.field_rows: list[FieldRow] = []
        self._last_detect_results: list[dict] = []
        self._current_file_entities: list = []
        self._page_marks: dict = {}

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
        # ═══ ВЕРХНЯЯ ПАНЕЛЬ — ЗАГОЛОВОК ═══
        top = ctk.CTkFrame(self, fg_color=C["surface"], height=40, corner_radius=0)
        top.pack(fill="x")
        top.pack_propagate(False)

        ctk.CTkLabel(top, text="TITAN CLEANER",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C["accent"]).pack(side="left", padx=12)
        ctk.CTkLabel(top, text="v4.2",
                     font=ctk.CTkFont(size=11),
                     text_color=C["text3"]).pack(side="left")

        # Легенда цветов
        legend_frame = ctk.CTkFrame(top, fg_color="transparent")
        legend_frame.pack(side="right", padx=(8, 12))
        ctk.CTkLabel(legend_frame, text="Маркеры:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text2"]).pack(side="left", padx=(0, 6))
        for name, color in LEGEND:
            ctk.CTkLabel(legend_frame, text=f"●{name}", font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=color).pack(side="left", padx=3)

        # ═══ ОСНОВНОЕ ТЕЛО: ТРИ КОЛОНКИ ═══
        body = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=0, minsize=250)
        body.grid_columnconfigure(1, weight=1, minsize=400)
        body.grid_columnconfigure(2, weight=0, minsize=280)
        body.grid_rowconfigure(0, weight=1)

        # ═══ ЛЕВАЯ КОЛОНКА — ФАЙЛЫ, НАСТРОЙКИ, ЛОГ ═══
        left = ctk.CTkScrollableFrame(body, width=240, fg_color=C["bg"], corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")

        # -- Файлы --
        self._section(left, "ФАЙЛЫ")
        files_frame = ctk.CTkFrame(left, fg_color=C["surface"], corner_radius=6)
        files_frame.pack(fill="x", padx=6, pady=(0, 4))

        self.file_list = ctk.CTkTextbox(files_frame, height=70, corner_radius=4,
                                         fg_color=C["input"], text_color=C["text"],
                                         font=ctk.CTkFont(size=10))
        self.file_list.pack(fill="x", padx=6, pady=(6, 2))
        _make_readonly(self.file_list)

        fb = ctk.CTkFrame(files_frame, fg_color="transparent")
        fb.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkButton(fb, text="+ Файлы", width=70, height=24,
                      fg_color=C["blue"], hover_color=C["blue_h"],
                      font=ctk.CTkFont(size=10),
                      command=self._add_files).pack(side="left", padx=(0, 2))
        ctk.CTkButton(fb, text="+ Папка", width=70, height=24,
                      fg_color=C["blue"], hover_color=C["blue_h"],
                      font=ctk.CTkFont(size=10),
                      command=self._add_folder).pack(side="left", padx=(0, 2))
        ctk.CTkButton(fb, text="Очист.", width=50, height=24,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      font=ctk.CTkFont(size=10),
                      command=self._clear_files).pack(side="right")

        # -- Папка результатов (сразу под файлами) --
        out_row = ctk.CTkFrame(files_frame, fg_color="transparent")
        out_row.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkLabel(out_row, text="Сохранять в:", font=ctk.CTkFont(size=10),
                     text_color=C["text2"]).pack(side="left")
        self.output_var = ctk.StringVar(value=self._saved_output or "./cleaned")
        ctk.CTkEntry(out_row, textvariable=self.output_var,
                     fg_color=C["input"], border_color=C["border"],
                     text_color=C["text"], font=ctk.CTkFont(size=10)).pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkButton(out_row, text="...", width=26, height=24,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      command=self._browse_output).pack(side="right")

        # -- Замены (сводка) --
        self._section(left, "СВОДКА")
        self.summary_frame = ctk.CTkFrame(left, fg_color=C["surface"], corner_radius=6)
        self.summary_frame.pack(fill="x", padx=6, pady=(0, 4))
        self.summary_label = ctk.CTkLabel(self.summary_frame, text="Добавьте файлы",
                                           font=ctk.CTkFont(size=10),
                                           text_color=C["text2"], wraplength=220, anchor="w")
        self.summary_label.pack(padx=6, pady=4, anchor="w")

        # -- PDF --
        self._section(left, "PDF")
        pdf_frame = ctk.CTkFrame(left, fg_color=C["surface"], corner_radius=6)
        pdf_frame.pack(fill="x", padx=6, pady=(0, 4))
        pdf_inner = ctk.CTkFrame(pdf_frame, fg_color="transparent")
        pdf_inner.pack(fill="x", padx=6, pady=4)

        self.pdf_mode = ctk.StringVar(value="text")
        ctk.CTkRadioButton(pdf_inner, text="Текст", variable=self.pdf_mode, value="text",
                           fg_color=C["accent"], font=ctk.CTkFont(size=10)).pack(side="left")
        ctk.CTkRadioButton(pdf_inner, text="Штамп", variable=self.pdf_mode, value="stamp",
                           fg_color=C["accent"], font=ctk.CTkFont(size=10)).pack(side="left", padx=4)

        self.stamp_var = ctk.StringVar(value="чёрная плашка")
        ctk.CTkComboBox(pdf_inner, variable=self.stamp_var,
                        values=["чёрная плашка", "ромашка", "замок", "конфиденциально"],
                        width=120, fg_color=C["input"], border_color=C["border"],
                        button_color=C["gray"], dropdown_fg_color=C["surface"],
                        text_color=C["text"], font=ctk.CTkFont(size=9)).pack(side="left", padx=2)

        ocr_row = ctk.CTkFrame(pdf_frame, fg_color="transparent")
        ocr_row.pack(fill="x", padx=6, pady=(0, 4))
        self.ocr_enabled = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(ocr_row, text="OCR", variable=self.ocr_enabled,
                        fg_color=C["blue"], font=ctk.CTkFont(size=10)).pack(side="left")

        # -- Лог --
        self._section(left, "ЛОГ")
        self.log_text = ctk.CTkTextbox(left, height=100, corner_radius=4,
                                        fg_color=C["input"], text_color=C["text"],
                                        font=ctk.CTkFont(family="Consolas", size=11))
        self.log_text.pack(fill="x", padx=6, pady=(0, 4))
        _make_readonly(self.log_text)
        self.log_text.tag_config("success", foreground=C["green"])
        self.log_text.tag_config("warning", foreground=C["m_surname"])
        self.log_text.tag_config("error", foreground=C["accent"])
        self.log_text.tag_config("info", foreground=C["blue"])

        # -- Карта замен (аккордеон по группам) --
        self._map_expanded = True
        map_header = ctk.CTkFrame(left, fg_color=C["card"], height=26, corner_radius=4)
        map_header.pack(fill="x", padx=6, pady=(6, 0))
        map_header.pack_propagate(False)

        self.map_toggle_btn = ctk.CTkButton(
            map_header, text="▾ КАРТА ЗАМЕН (0)", width=200, height=22,
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["text2"], anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_map)
        self.map_toggle_btn.pack(side="left", padx=4)

        self.map_frame = ctk.CTkFrame(left, fg_color=C["surface"], corner_radius=4)
        self.map_frame.pack(fill="x", padx=6, pady=(2, 0))

        # Контейнер для аккордеон-групп
        self._map_groups_container = ctk.CTkFrame(self.map_frame, fg_color="transparent")
        self._map_groups_container.pack(fill="x", padx=2, pady=2)
        self._map_group_widgets = {}   # group_key -> {header, body, expanded, btn}
        self._map_group_order = [      # порядок и конфиг групп
            ("organization", "Организации", C["m_org"]),
            ("surname",      "ФИО",         C["m_surname"]),
            ("city",         "Города",      C["m_city"]),
            ("address",      "Адреса",      C["m_address"]),
            ("req",          "Реквизиты",   C["m_req"]),
            ("contact",      "Контакты",    C["m_contact"]),
            ("doc",          "Документы",    C["m_doc"]),
        ]

        # -- Прогресс --
        self.progress = ctk.CTkProgressBar(left, progress_color=C["accent"],
                                            fg_color=C["border"], height=6)
        self.progress.pack(fill="x", padx=6, pady=(4, 2))
        self.progress.set(0)
        self.progress_label = ctk.CTkLabel(left, text="", font=ctk.CTkFont(size=9),
                                            text_color=C["text3"])
        self.progress_label.pack(anchor="w", padx=6)

        # ═══ ЦЕНТРАЛЬНАЯ КОЛОНКА — ЛИСТЫ ДОКУМЕНТА ═══
        center = ctk.CTkFrame(body, fg_color=C["bg"], corner_radius=0)
        center.grid(row=0, column=1, sticky="nsew", padx=2)

        # -- Заголовок предпросмотра --
        preview_header = ctk.CTkFrame(center, fg_color=C["surface"], height=36, corner_radius=6)
        preview_header.pack(fill="x", padx=4, pady=(4, 0))
        preview_header.pack_propagate(False)

        ctk.CTkLabel(preview_header, text="ПРЕДПРОСМОТР",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).pack(side="left", padx=8)

        self.found_label = ctk.CTkLabel(preview_header, text="",
                                         font=ctk.CTkFont(size=10),
                                         text_color=C["text2"])
        self.found_label.pack(side="right", padx=4)

        self.preview_file_var = ctk.StringVar(value="")
        self.preview_file_combo = ctk.CTkComboBox(
            preview_header, variable=self.preview_file_var, values=[""],
            width=200, fg_color=C["input"], border_color=C["border"],
            button_color=C["blue"], dropdown_fg_color=C["surface"],
            dropdown_hover_color=C["card"], text_color=C["text"],
            font=ctk.CTkFont(size=10),
            command=self._on_preview_file_changed)
        self.preview_file_combo.pack(side="right", padx=4)

        # -- Навигация по страницам --
        page_nav = ctk.CTkFrame(center, fg_color="transparent", height=28)
        page_nav.pack(fill="x", padx=4, pady=(4, 0))
        page_nav.pack_propagate(False)

        self.btn_prev_page = ctk.CTkButton(
            page_nav, text="← Пред.", width=70, height=22,
            fg_color=C["gray"], hover_color=C["gray_h"],
            font=ctk.CTkFont(size=10), command=self._prev_page)
        self.btn_prev_page.pack(side="left")

        self.page_label = ctk.CTkLabel(page_nav, text="",
                                        font=ctk.CTkFont(size=10), text_color=C["text2"])
        self.page_label.pack(side="left", padx=8)

        self.btn_next_page = ctk.CTkButton(
            page_nav, text="След. →", width=70, height=22,
            fg_color=C["gray"], hover_color=C["gray_h"],
            font=ctk.CTkFont(size=10), command=self._next_page)
        self.btn_next_page.pack(side="left")

        self._current_page = 0
        self._total_pages = 0

        # -- Превью документа: все страницы в скролле как "листы" --
        self.preview_text = ctk.CTkTextbox(
            center, corner_radius=4,
            fg_color="#ffffff", text_color="#1a1a1a",
            font=ctk.CTkFont(size=12),
            wrap="word")
        self.preview_text.pack(fill="both", expand=True, padx=4, pady=(4, 4))

        # Теги
        for etype, color in MARKER_COLORS.items():
            self.preview_text.tag_config(f"m_{etype}", foreground="#000000", background=color)
        self.preview_text.tag_config("page_header", foreground="#999999", background="#e8e8e8")
        self.preview_text.tag_config("page_gap", foreground="#cccccc", background="#cccccc")

        # Привязка выделения текста
        self.preview_text.bind("<<Selection>>", self._on_text_selected)
        self.preview_text.bind("<ButtonRelease-1>", self._on_text_selected)
        _make_readonly(self.preview_text)

        # ═══ ПРАВАЯ КОЛОНКА — ВЫДЕЛЕННОЕ + ПРАВИЛА ЗАМЕНЫ ═══
        right = ctk.CTkScrollableFrame(body, width=270, fg_color=C["bg"], corner_radius=0)
        right.grid(row=0, column=2, sticky="nsew")

        # -- Выделенное (ручное добавление) --
        self._section(right, "ВЫДЕЛЕННОЕ")
        sel_frame = ctk.CTkFrame(right, fg_color=C["surface"], corner_radius=6)
        sel_frame.pack(fill="x", padx=6, pady=(0, 4))

        self.sel_text_label = ctk.CTkLabel(
            sel_frame, text="Выделите текст в превью",
            font=ctk.CTkFont(size=10), text_color=C["text3"],
            wraplength=250, justify="left")
        self.sel_text_label.pack(padx=6, pady=(4, 2), anchor="w")

        sel_row = ctk.CTkFrame(sel_frame, fg_color="transparent")
        sel_row.pack(fill="x", padx=6, pady=(2, 2))

        self.sel_type_var = ctk.StringVar(value="Организация")
        ctk.CTkComboBox(sel_row, variable=self.sel_type_var,
                        values=list(FIELD_TYPES.keys()), width=120,
                        fg_color=C["input"], border_color=C["border"],
                        button_color=C["blue"], dropdown_fg_color=C["surface"],
                        text_color=C["text"], font=ctk.CTkFont(size=10)
                        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(sel_row, text="Добавить", width=70, height=24,
                      fg_color=C["blue"], hover_color=C["blue_h"],
                      font=ctk.CTkFont(size=10),
                      command=self._add_selected_text).pack(side="left")

        # -- Занятые замены (контекст маппинга) --
        self.sel_used_label = ctk.CTkLabel(
            sel_frame, text="", font=ctk.CTkFont(size=9),
            text_color=C["text3"], wraplength=250, justify="left")
        self.sel_used_label.pack(padx=6, pady=(0, 4), anchor="w")

        # -- Правила замены --
        self._section(right, "ПРАВИЛА ЗАМЕНЫ")
        self.fields_container = ctk.CTkFrame(right, fg_color="transparent")
        self.fields_container.pack(fill="x", padx=6, pady=(0, 2))

        add_btns = ctk.CTkFrame(right, fg_color="transparent")
        add_btns.pack(fill="x", padx=6, pady=(0, 4))

        btn_cfg = [
            ("+ Орг", "Организация", C["m_org"]),
            ("+ Город", "Город", C["m_city"]),
            ("+ Адрес", "Адрес", C["m_address"]),
            ("+ ФИО подп.", "ФИО подписант", C["m_surname"]),
            ("+ ФИО уч.", "ФИО участники", C["m_surname"]),
            ("+ Своё", "Своё поле", C["gray"]),
        ]
        for text, ft, color in btn_cfg:
            ctk.CTkButton(add_btns, text=text, width=50, height=22,
                          fg_color=color, hover_color=C["gray_h"],
                          text_color="#000000" if color in (C["m_surname"], C["m_city"], C["m_address"]) else C["text"],
                          font=ctk.CTkFont(size=10),
                          command=lambda n=ft: self._add_field_row(n)
                          ).pack(side="left", padx=1)

        # ═══ НИЖНЯЯ ПАНЕЛЬ — КНОПКИ ДЕЙСТВИЙ ═══
        bottom = ctk.CTkFrame(self, fg_color=C["surface"], height=70, corner_radius=0)
        bottom.pack(fill="x")
        bottom.pack_propagate(False)

        btn_row = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_row.pack(pady=6)

        btn_w, btn_h = 150, 34
        self.btn_detect = ctk.CTkButton(
            btn_row, text="АВТОПОИСК", width=btn_w, height=btn_h,
            fg_color=C["blue"], hover_color=C["blue_h"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._auto_detect_start)
        self.btn_detect.pack(side="left", padx=4)

        self.btn_process = ctk.CTkButton(
            btn_row, text="ОБРАБОТАТЬ", width=btn_w, height=btn_h,
            fg_color=C["accent"], hover_color=C["accent_h"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._start_processing)
        self.btn_process.pack(side="left", padx=4)

        self.btn_deanon = ctk.CTkButton(
            btn_row, text="ДЕАНОНИМИЗАЦИЯ", width=btn_w, height=btn_h,
            fg_color=C["green"], hover_color=C["green_h"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._deanon_panel)
        self.btn_deanon.pack(side="left", padx=4)

        ctk.CTkButton(btn_row, text="История", width=80, height=btn_h,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      font=ctk.CTkFont(size=10),
                      command=self._show_history).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Экспорт карты", width=100, height=btn_h,
                      fg_color=C["gray"], hover_color=C["gray_h"],
                      font=ctk.CTkFont(size=10),
                      command=self._show_replacement_map).pack(side="left", padx=4)
        self.btn_cancel = ctk.CTkButton(
            btn_row, text="Отмена", width=70, height=btn_h,
            fg_color=C["gray"], hover_color=C["accent"],
            font=ctk.CTkFont(size=10), state="disabled",
            command=self._cancel)
        self.btn_cancel.pack(side="left", padx=4)

        # ═══ СТАТУС-БАР ═══
        status = ctk.CTkFrame(self, fg_color=C["card"], height=22, corner_radius=0)
        status.pack(fill="x")
        status.pack_propagate(False)
        self.status_var = ctk.StringVar(value="Готов к работе")
        ctk.CTkLabel(status, textvariable=self.status_var,
                     font=ctk.CTkFont(size=9), text_color=C["text2"]).pack(side="left", padx=8)

    def _section(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["text2"], anchor="w").pack(fill="x", padx=6, pady=(6, 2))

    def _toggle_map(self):
        """Сворачивает/разворачивает карту замен."""
        if self._map_expanded:
            self.map_frame.pack_forget()
            self._map_expanded = False
            lbl = self.map_toggle_btn.cget("text").replace("▾", "▸")
            self.map_toggle_btn.configure(text=lbl)
        else:
            self.map_frame.pack(fill="x", padx=6, pady=(2, 0),
                                after=self.map_toggle_btn.master)
            self._map_expanded = True
            lbl = self.map_toggle_btn.cget("text").replace("▸", "▾")
            self.map_toggle_btn.configure(text=lbl)

    def _update_map_panel(self):
        """Обновляет карту замен с группировкой-аккордеоном."""
        # Маппинг entity_type -> группа аккордеона
        type_to_group = {
            "organization": "organization",
            "surname": "surname",
            "city": "city",
            "address": "address",
            "inn": "req", "ogrn": "req", "kpp": "req", "bik": "req", "account": "req",
            "phone": "contact", "email": "contact", "url": "contact",
            "snils": "doc", "passport": "doc",
        }
        type_label = {
            "organization": "Орг", "surname": "ФИО", "city": "Город",
            "inn": "ИНН", "ogrn": "ОГРН", "kpp": "КПП", "bik": "БИК",
            "account": "Счёт", "phone": "Тел", "email": "Email",
            "url": "URL", "address": "Адрес", "snils": "СНИЛС",
            "passport": "Пасп",
        }

        # Собираем данные по группам: group_key -> [(label, src_text, repl_text, source)]
        groups_data = {}
        seen = set()
        count = 0

        # Авто-замены
        for res in self._last_detect_results:
            for e in res.get("entities", []):
                key = e.text.lower()
                if key in seen:
                    continue
                seen.add(key)
                count += 1
                grp = type_to_group.get(e.entity_type, "organization")
                label = type_label.get(e.entity_type, "?")
                groups_data.setdefault(grp, []).append(
                    (label, e.text, e.replacement, "авто"))

        # Ручные правила
        for row in self.field_rows:
            if row.is_empty():
                continue
            search, replace = row.get_search(), row.get_replace()
            key = search.lower()
            if key in seen:
                continue
            seen.add(key)
            count += 1
            ft = row.field_type
            etype = {"Организация": "organization", "Город": "city",
                     "ФИО подписант": "surname", "ФИО участники": "surname",
                     "Адрес": "address", "Своё поле": "address"}.get(ft, "organization")
            grp = type_to_group.get(etype, "organization")
            label = type_label.get(etype, "?")
            groups_data.setdefault(grp, []).append(
                (label, search, replace, "ручн"))

        # Очищаем старые виджеты
        for w in self._map_groups_container.winfo_children():
            w.destroy()
        self._map_group_widgets.clear()

        # Строим аккордеон-группы
        for grp_key, grp_name, grp_color in self._map_group_order:
            items = groups_data.get(grp_key, [])
            if not items:
                continue

            # Заголовок группы (кнопка)
            hdr = ctk.CTkFrame(self._map_groups_container, fg_color=C["card"],
                               height=24, corner_radius=3)
            hdr.pack(fill="x", pady=(2, 0))
            hdr.pack_propagate(False)

            body = ctk.CTkFrame(self._map_groups_container, fg_color=C["input"],
                                corner_radius=3)
            body.pack(fill="x", pady=(0, 1))

            gw = {"body": body, "expanded": True}
            self._map_group_widgets[grp_key] = gw

            btn = ctk.CTkButton(
                hdr, text=f"▾ {grp_name} ({len(items)})", width=200, height=22,
                fg_color="transparent", hover_color=C["surface"],
                text_color=grp_color, anchor="w",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda k=grp_key: self._toggle_map_group(k))
            btn.pack(side="left", padx=4)
            gw["btn"] = btn

            # Элементы группы
            for label, src, repl, source in items:
                row_f = ctk.CTkFrame(body, fg_color="transparent")
                row_f.pack(fill="x", padx=4, pady=(1, 2))

                # Верхняя строка: исходный текст + [источник]
                top_row = ctk.CTkFrame(row_f, fg_color="transparent")
                top_row.pack(fill="x")
                src_color = C["blue"] if source == "авто" else C["m_surname"]
                ctk.CTkLabel(top_row, text=f"[{source}]", font=ctk.CTkFont(size=9),
                             text_color=src_color, width=36).pack(side="right")
                ctk.CTkLabel(top_row, text=src, font=ctk.CTkFont(family="Consolas", size=11),
                             text_color=grp_color, anchor="w", wraplength=220).pack(side="left", fill="x")

                # Нижняя строка: стрелка + замена
                bot_row = ctk.CTkFrame(row_f, fg_color="transparent")
                bot_row.pack(fill="x")
                ctk.CTkLabel(bot_row, text="  → ", font=ctk.CTkFont(size=10),
                             text_color=C["text3"]).pack(side="left")
                ctk.CTkLabel(bot_row, text=repl, font=ctk.CTkFont(family="Consolas", size=11),
                             text_color=C["green"], anchor="w", wraplength=220).pack(side="left", fill="x")

        arrow = "▾" if self._map_expanded else "▸"
        self.map_toggle_btn.configure(text=f"{arrow} КАРТА ЗАМЕН ({count})")

        # Обновляем галочки занятых замен
        for row in self.field_rows:
            row_etype = {"Организация": "organization", "Город": "city",
                         "ФИО подписант": "surname", "ФИО участники": "surname",
                         "Адрес": "address", "Своё поле": "address"}.get(row.field_type, "organization")
            used = self._get_used_replacements(row_etype)
            row.update_used_marks(used)

    def _toggle_map_group(self, grp_key):
        """Сворачивает/разворачивает группу аккордеона карты замен."""
        gw = self._map_group_widgets.get(grp_key)
        if not gw:
            return
        if gw["expanded"]:
            gw["body"].pack_forget()
            gw["expanded"] = False
            txt = gw["btn"].cget("text").replace("▾", "▸")
            gw["btn"].configure(text=txt)
        else:
            # Вставить body обратно после header
            gw["body"].pack(fill="x", pady=(0, 1), after=gw["btn"].master)
            gw["expanded"] = True
            txt = gw["btn"].cget("text").replace("▸", "▾")
            gw["btn"].configure(text=txt)

    def _update_used_replacements(self):
        """Обновляет список занятых замен в панели ВЫДЕЛЕННОЕ."""
        ft = self.sel_type_var.get()
        etype = {"Организация": "organization", "Город": "city",
                 "ФИО подписант": "surname", "ФИО участники": "surname",
                 "Адрес": "address", "Своё поле": "address"}.get(ft, "organization")

        used = []
        for res in self._last_detect_results:
            for e in res.get("entities", []):
                if e.entity_type == etype and e.replacement not in used:
                    used.append(e.replacement)
        for row in self.field_rows:
            if not row.is_empty():
                row_etype = {"Организация": "organization", "Город": "city",
                             "ФИО подписант": "surname", "ФИО участники": "surname",
                             "Адрес": "address", "Своё поле": "address"}.get(row.field_type, "organization")
                if row_etype == etype and row.get_replace() not in used:
                    used.append(row.get_replace())

        pool = ENGLISH_OPTIONS.get(ft, [])
        total = len(pool)
        n_used = len(used)

        if used:
            used_str = ", ".join(used[:5])
            if len(used) > 5:
                used_str += f" ...+{len(used)-5}"
            next_free = next((x for x in pool if x not in used), None)
            lines = [f"Занято: {n_used}/{total}"]
            lines.append(f"Исп.: {used_str}")
            if next_free:
                lines.append(f"След. свободное: {next_free}")
            self.sel_used_label.configure(text="\n".join(lines))
        else:
            self.sel_used_label.configure(text="")

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
        self.file_list.delete("1.0", "end")
        for f in self.files:
            self.file_list.insert("end", Path(f).name + "\n")

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
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")
        logger.info(msg)

    # ── Preview ──

    def _clear_preview(self):
        self.preview_text.delete("1.0", "end")
        self.found_label.configure(text="")
        self.preview_file_combo.configure(values=[""])
        self.preview_file_var.set("")
        for w in self._map_groups_container.winfo_children():
            w.destroy()
        self._map_group_widgets.clear()
        self.map_toggle_btn.configure(text="▾ КАРТА ЗАМЕН (0)")
        self.page_label.configure(text="")

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

        # Обновляем карту замен и занятые замены
        self._update_map_panel()
        self._update_used_replacements()

    def _on_preview_file_changed(self, choice=None):
        fname = self.preview_file_var.get()
        for r in self._last_detect_results:
            if Path(r["filepath"]).name == fname:
                self._render_file_preview(r)
                return

    def _render_file_preview(self, result):
        """Рендерит все страницы документа как отдельные «листы» в одном скролле."""
        pages = result.get("pages", {})
        entities = result.get("entities", [])
        full_text = result.get("text", "")
        self._current_file_entities = entities

        if not pages and full_text:
            pages = {1: full_text}

        self._preview_pages = pages
        self._preview_entities = entities
        self._page_keys = sorted(pages.keys()) if pages else []
        self._total_pages = len(self._page_keys)
        self._current_page = 0

        # Считаем text_offset для каждой страницы
        self._page_offsets = {}
        offset = 0
        for pk in self._page_keys:
            self._page_offsets[pk] = offset
            offset += len(pages[pk])

        # Запоминаем tk-метки начала каждой страницы для навигации
        self._page_marks = {}

        self._render_all_pages()

    def _render_all_pages(self):
        """Рендерит все страницы как визуальные «листы» с разделителями."""
        self.preview_text.delete("1.0", "end")

        if not self._page_keys:
            self.preview_text.insert("end", "(нет текста)")
            self.page_label.configure(text="")
            return

        for i, page_key in enumerate(self._page_keys):
            page_text = self._preview_pages[page_key]
            page_start = self._page_offsets[page_key]
            page_end = page_start + len(page_text)

            # Разделитель между листами
            if i > 0:
                self.preview_text.insert("end", "\n")
                self.preview_text.insert("end", "━" * 60 + "\n", "page_gap")

            # Заголовок страницы
            mark_name = f"page_{page_key}"
            self.preview_text.mark_set(mark_name, "end-1c")
            self._page_marks[i] = mark_name
            self.preview_text.insert("end", f"  ─── Страница {page_key} ───\n", "page_header")

            # Текст с подсветкой сущностей
            page_entities = sorted(
                [e for e in self._preview_entities
                 if e.start >= page_start and e.end <= page_end],
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

        self.preview_text.see("1.0")

        # Навигация
        self.page_label.configure(text=f"Стр. 1 / {self._total_pages}")
        self.btn_prev_page.configure(state="disabled")
        self.btn_next_page.configure(
            state="normal" if self._total_pages > 1 else "disabled")

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._scroll_to_page()

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._scroll_to_page()

    def _scroll_to_page(self):
        """Прокручивает превью к указанной странице."""
        mark = self._page_marks.get(self._current_page)
        if mark:
            self.preview_text._textbox.see(mark)
            # Дополнительно прокрутить метку в начало видимой области
            self.after(50, lambda: self.preview_text._textbox.yview(mark))
        self.page_label.configure(
            text=f"Стр. {self._current_page + 1} / {self._total_pages}")
        self.btn_prev_page.configure(
            state="normal" if self._current_page > 0 else "disabled")
        self.btn_next_page.configure(
            state="normal" if self._current_page < self._total_pages - 1 else "disabled")

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
                self._update_used_replacements()
            else:
                self._pending_selection = None
        except (tk.TclError, Exception):
            self._pending_selection = None

    def _get_used_replacements(self, entity_type):
        """Возвращает set занятых замен для данного типа."""
        used = set()
        for res in self._last_detect_results:
            for e in res.get("entities", []):
                if e.entity_type == entity_type:
                    used.add(e.replacement)
        for row in self.field_rows:
            if not row.is_empty():
                row_etype = {"Организация": "organization", "Город": "city",
                             "ФИО подписант": "surname", "ФИО участники": "surname",
                             "Адрес": "address", "Своё поле": "address"}.get(row.field_type, "organization")
                if row_etype == entity_type:
                    used.add(row.get_replace())
        return used

    def _add_selected_text(self):
        """Добавляет выделенный текст как правило замены и подсвечивает в превью."""
        sel = getattr(self, '_pending_selection', None)
        if not sel:
            messagebox.showinfo("Выделение", "Выделите текст в предпросмотре мышкой.")
            return
        ft = self.sel_type_var.get()
        etype = {"Организация": "organization", "Город": "city",
                 "ФИО подписант": "surname", "ФИО участники": "surname",
                 "Адрес": "address", "Своё поле": "address"}.get(ft, "organization")

        row = self._add_field_row(ft)
        row.set_search(sel)

        # Автовыбор следующей свободной замены
        used = self._get_used_replacements(etype)
        next_free = row.get_next_free(used)
        if next_free:
            row.set_replace(next_free)
        row.update_used_marks(used)

        self.sel_text_label.configure(text=f"Добавлено: «{sel[:40]}»", text_color=C["green"])
        self._pending_selection = None

        # Определяем entity_type для маркера
        type_map = {
            "Организация": "organization",
            "Город": "city",
            "Адрес": "address",
            "ФИО подписант": "surname",
            "ФИО участники": "surname",
            "Своё поле": "address",
        }
        etype = type_map.get(ft, "organization")

        # Добавляем как entity в авто-результаты текущего файла и подсвечиваем
        fname = self.preview_file_var.get()
        for r in self._last_detect_results:
            if Path(r["filepath"]).name == fname:
                full_text = r.get("text", "")
                # Находим все вхождения в тексте
                import re as _re
                for m in _re.finditer(_re.escape(sel), full_text, _re.IGNORECASE):
                    # Проверяем нет ли уже такой entity
                    already = any(
                        e.start == m.start() and e.end == m.end()
                        for e in r.get("entities", [])
                    )
                    if not already:
                        from core.auto_detect import DetectedEntity, _auto_replacement
                        new_e = DetectedEntity(
                            start=m.start(), end=m.end(),
                            text=m.group(), entity_type=etype,
                            replacement=_auto_replacement(etype, m.group()),
                            confidence=1.0,
                        )
                        r.setdefault("entities", []).append(new_e)

                # Перерисовываем превью с новыми маркерами
                self._render_file_preview(r)

                # Обновляем сводку и карту замен
                total = sum(len(res.get("entities", [])) for res in self._last_detect_results)
                self.found_label.configure(text=f"Найдено: {total}")
                self._update_map_panel()
                self._update_used_replacements()
                break

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
            elif ft == "Адрес":
                rules.append({"patterns": build_custom_patterns(search), "replacement": replace, "type": "address"})
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

        # Всегда объединяем ручные правила + автодетект
        thread = threading.Thread(target=self._process_combined, daemon=True)
        thread.start()

    def _cancel(self):
        if self.processing:
            self.cancel_flag = True
            self._log("Отмена...", "warning")

    def _process_combined(self):
        """Обработка: объединяет ручные правила + автодетект для каждого файла."""
        manual_rules = self._build_replacement_rules()
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

        # Индексируем авто-результаты по filepath
        auto_by_file = {}
        for r in self._last_detect_results:
            auto_by_file[r["filepath"]] = r

        for i, fp in enumerate(self.files):
            if self.cancel_flag:
                break
            fn = Path(fp).name
            ext = Path(fp).suffix.lower()
            out = str(Path(output_dir) / fn)
            if os.path.abspath(fp) == os.path.abspath(out):
                out = str(Path(output_dir) / f"{Path(fp).stem}_cleaned{ext}")

            self.after(0, lambda f=fn: self.progress_label.configure(text=f))

            # Объединяем правила: ручные + авто-entities для этого файла
            combined_rules = list(manual_rules)  # копия ручных правил
            auto_result = auto_by_file.get(fp)
            entities = auto_result.get("entities", []) if auto_result else []
            if entities:
                auto_rules = self._entities_to_rules(entities)
                # Добавляем авто-правила, которых нет в ручных
                manual_patterns = set()
                for r in manual_rules:
                    for p in r["patterns"]:
                        manual_patterns.add(p.pattern.lower())
                for ar in auto_rules:
                    pat = ar["patterns"][0].pattern.lower()
                    if pat not in manual_patterns:
                        combined_rules.append(ar)

            if not combined_rules:
                self.after(0, lambda f=fn: self._log(f"! {f} — нет правил", "warning"))
                self.after(0, lambda v=(i+1)/n: self.progress.set(v))
                continue

            try:
                if ext == '.docx':
                    res = clean_docx(fp, out, combined_rules)
                elif ext == '.pdf':
                    if self.pdf_mode.get() == "text":
                        res = clean_pdf_text_mode(fp, out, combined_rules, ocr_enabled=self.ocr_enabled.get())
                    else:
                        res = clean_pdf_stamp_mode(fp, out, combined_rules, stamp_path=self._get_stamp_path(),
                                                    stamp_type=self.stamp_var.get(), ocr_enabled=self.ocr_enabled.get())
                elif ext in ('.xlsx', '.xls'):
                    res = clean_xlsx(fp, out, combined_rules)
                else:
                    continue

                matches = res.get("matches", {})
                for k, v in matches.items():
                    total_matches[k] = total_matches.get(k, 0) + v
                total_file = sum(matches.values()) if matches else 0

                # Маппинг в БД — для каждого файла
                mapping_list = []
                # Из ручных правил
                for rule in manual_rules:
                    if "mapper" in rule:
                        for orig, repl in rule["mapper"].get_map().items():
                            mapping_list.append({"original": orig, "pseudonym": repl, "entity_type": rule.get("type", "")})
                    elif "replacement" in rule:
                        for pat in rule["patterns"]:
                            mapping_list.append({"original": pat.pattern.replace("\\", ""), "pseudonym": rule["replacement"], "entity_type": rule.get("type", "")})
                # Из авто-entities
                for e in entities:
                    mapping_list.append({"original": e.text, "pseudonym": e.replacement, "entity_type": e.entity_type})
                # Дедупликация
                seen = set()
                unique_mappings = []
                for m in mapping_list:
                    key = (m["original"].lower(), m["pseudonym"])
                    if key not in seen:
                        seen.add(key)
                        unique_mappings.append(m)
                db.save_file_mappings(fn, Path(out).name, unique_mappings)

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
        _make_readonly(file_list_text)

        selected_fm_id = [None]  # mutable container

        def refresh_list(*args):
            q = search_var.get().strip()
            files = SessionDB.search_files(q)
            file_list_text.delete("1.0", "end")
            file_list_text.insert("end",
                f"{'#':>4}  {'Файл':<30} {'Дата':<20} {'Замен':>6}\n", "header")
            file_list_text.insert("end", "─" * 70 + "\n", "header")
            for f in files:
                line = f"#{f['id']:>3}  {f['source_filename']:<30} {f['created_at']:<20} {f['total_replacements']:>6}\n"
                file_list_text.insert("end", line, "item")
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
                    file_list_text.tag_remove("selected_item", "1.0", "end")
                    file_list_text.tag_add("selected_item", f"{line_num}.0", f"{line_num}.end")
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
        _make_readonly(map_text)

        def show_mappings(fm_id):
            mappings = SessionDB.get_file_mappings(fm_id)
            map_text.delete("1.0", "end")
            for m in mappings[:20]:
                map_text.insert("end", m["pseudonym"], "pseudo")
                map_text.insert("end", "  ←  ", "arrow")
                map_text.insert("end", m["original"] + "\n", "orig")
            if len(mappings) > 20:
                map_text.insert("end", f"...ещё {len(mappings) - 20}\n", "arrow")

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
        _make_readonly(text)

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
        _make_readonly(text)

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
