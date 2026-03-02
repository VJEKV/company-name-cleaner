"""
Company Name Cleaner — портативное GUI-приложение.
Замена названия компании, фамилий, городов и произвольных полей
на заглушки в .docx и .pdf.
"""

import csv
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

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
from core.docx_cleaner import clean_docx, preview_docx
from core.pdf_cleaner import (
    clean_pdf_text_mode,
    clean_pdf_stamp_mode,
    preview_pdf,
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

APP_TITLE = "Titan Cleaner v2.0"
WINDOW_WIDTH = 920
WINDOW_HEIGHT = 850

logger = setup_logging()

# Типы полей для замены
FIELD_TYPES = {
    "Город": {
        "hint_search": "Москва",
        "hint_replace": "г. Ромашкино",
        "options_func": get_city_replacement_options,
        "multiline": False,
    },
    "Организация": {
        "hint_search": "ЛУКОЙЛ",
        "hint_replace": "ООО «Ромашка»",
        "options_func": get_company_replacement_options,
        "multiline": False,
    },
    "ФИО подписант": {
        "hint_search": "Петров А.В.",
        "hint_replace": "Иванов И.И.",
        "options_func": get_signatory_replacement_options,
        "multiline": False,
    },
    "ФИО участники": {
        "hint_search": "Сидоров\nКозлова\nМорозов",
        "hint_replace": "Сотрудник №{n}",
        "options_func": get_surname_replacement_options,
        "multiline": True,
    },
    "Своё поле": {
        "hint_search": "ИНН 7707083893",
        "hint_replace": "ИНН XXXXXXXXXX",
        "options_func": get_generic_replacement_options,
        "multiline": False,
    },
}


class FieldRow:
    """Один ряд параметров замены в GUI."""

    def __init__(self, parent_frame, field_type: str, on_delete=None, idx: int = 0):
        self.field_type = field_type
        self.on_delete = on_delete
        self.idx = idx
        config = FIELD_TYPES.get(field_type, FIELD_TYPES["Своё поле"])

        self.frame = ttk.LabelFrame(parent_frame, text=f"  {field_type}  ", padding=5)
        self.frame.pack(fill="x", padx=5, pady=3)

        # Верхняя строка: Искать + Удалить
        top = ttk.Frame(self.frame)
        top.pack(fill="x")

        ttk.Label(top, text="Искать:", width=8).pack(side="left")

        if config["multiline"]:
            self.search_widget = scrolledtext.ScrolledText(
                self.frame, height=3, width=40, wrap="word"
            )
            self.search_widget.pack(fill="x", pady=(0, 3))
        else:
            self.search_var = tk.StringVar()
            self.search_widget = ttk.Entry(top, textvariable=self.search_var, width=40)
            self.search_widget.pack(side="left", padx=5, fill="x", expand=True)

        if on_delete:
            ttk.Button(top, text="✕", width=3, command=self._delete).pack(side="right")

        # Нижняя строка: Замена
        bottom = ttk.Frame(self.frame)
        bottom.pack(fill="x")

        ttk.Label(bottom, text="Замена:", width=8).pack(side="left")

        self.replace_var = tk.StringVar(value=config["hint_replace"])
        options = []
        for cat, opts in config["options_func"]().items():
            options.extend(opts)
        self.replace_combo = ttk.Combobox(
            bottom, textvariable=self.replace_var,
            values=list(dict.fromkeys(options)),
            width=37,
        )
        self.replace_combo.pack(side="left", padx=5, fill="x", expand=True)

        # Для ФИО участники — кнопка загрузки из файла
        if config["multiline"]:
            btn_row = ttk.Frame(self.frame)
            btn_row.pack(fill="x")
            ttk.Button(btn_row, text="Из файла .txt",
                       command=self._load_from_file).pack(side="left", padx=3)

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
                self.search_widget.delete("1.0", tk.END)
                self.search_widget.insert("1.0", content)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{e}")

    def get_search_text(self) -> str:
        config = FIELD_TYPES.get(self.field_type, FIELD_TYPES["Своё поле"])
        if config["multiline"]:
            return self.search_widget.get("1.0", tk.END).strip()
        return self.search_var.get().strip()

    def get_replace_text(self) -> str:
        return self.replace_var.get().strip()

    def set_search_text(self, text: str):
        config = FIELD_TYPES.get(self.field_type, FIELD_TYPES["Своё поле"])
        if config["multiline"]:
            self.search_widget.delete("1.0", tk.END)
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(750, 650)
        self.configure(bg="#f5f5f5")

        self.files: list[str] = []
        self.processing = False
        self.cancel_flag = False
        self.all_mappers: list = []  # для карты замен

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
        # Обратная совместимость со старым форматом
        if not self._saved_fields:
            old_company = cfg.get("company_name", "")
            old_surnames = cfg.get("surnames", "")
            old_comp_repl = cfg.get("company_replacement", "ООО «Ромашка»")
            old_sur_repl = cfg.get("surname_replacement", "Сотрудник №{n}")
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
        """Восстанавливает поля из сохранённого конфига."""
        if self._saved_fields:
            for fd in self._saved_fields:
                ft = fd.get("type", "Своё поле")
                row = self._add_field_row(ft)
                row.set_search_text(fd.get("search", ""))
                row.set_replace_text(fd.get("replace", ""))
        else:
            # По умолчанию — организация и ФИО
            self._add_field_row("Организация")
            self._add_field_row("ФИО участники")

    # ── UI Build ────────────────────────────────────────────

    def _build_ui(self):
        # Основной скроллируемый фрейм
        canvas = tk.Canvas(self, bg="#f5f5f5", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.main_frame = ttk.Frame(canvas)

        self.main_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.main_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Прокрутка колесиком
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_mousewheel_linux(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel_linux)
        canvas.bind_all("<Button-5>", _on_mousewheel_linux)

        pad = {"padx": 10, "pady": 3}

        # ── Секция: Параметры для замены ──
        self._section_label("Параметры для замены")

        # Контейнер для динамических полей
        self.fields_container = ttk.Frame(self.main_frame)
        self.fields_container.pack(fill="x", **pad)

        # Кнопки добавления полей
        add_row = ttk.Frame(self.main_frame)
        add_row.pack(fill="x", **pad)

        ttk.Label(add_row, text="Добавить:").pack(side="left", padx=(0, 5))

        for ft_name in FIELD_TYPES:
            ttk.Button(
                add_row, text=f"+ {ft_name}",
                command=lambda n=ft_name: self._add_field_row(n),
            ).pack(side="left", padx=2)

        # ── Секция: Режим PDF ──
        self._section_label("Режим замены в PDF")
        pdf_frame = ttk.Frame(self.main_frame)
        pdf_frame.pack(fill="x", **pad)
        self.pdf_mode = tk.StringVar(value="text")
        ttk.Radiobutton(pdf_frame, text="Текстовая заглушка",
                        variable=self.pdf_mode, value="text").pack(anchor="w")
        stamp_row = ttk.Frame(pdf_frame)
        stamp_row.pack(anchor="w")
        ttk.Radiobutton(stamp_row, text="Графический штамп:",
                        variable=self.pdf_mode, value="stamp").pack(side="left")
        self.stamp_var = tk.StringVar(value="чёрная плашка")
        stamp_opts = ["чёрная плашка", "ромашка", "замок",
                      "конфиденциально", "свой PNG..."]
        self.stamp_combo = ttk.Combobox(
            stamp_row, textvariable=self.stamp_var,
            values=stamp_opts, width=20, state="readonly"
        )
        self.stamp_combo.pack(side="left", padx=5)
        self.stamp_combo.bind("<<ComboboxSelected>>", self._on_stamp_selected)
        self.custom_stamp_path = None

        # OCR для сканов
        ocr_frame = ttk.Frame(pdf_frame)
        ocr_frame.pack(anchor="w", pady=(5, 0))
        self.ocr_enabled = tk.BooleanVar(value=False)
        self.ocr_checkbox = ttk.Checkbutton(
            ocr_frame,
            text="OCR для сканов (Tesseract)",
            variable=self.ocr_enabled,
            command=self._on_ocr_toggled,
        )
        self.ocr_checkbox.pack(side="left")
        self.ocr_status_label = ttk.Label(
            ocr_frame, text="", foreground="gray"
        )
        self.ocr_status_label.pack(side="left", padx=10)
        self._check_tesseract()

        # ── Секция: Файлы ──
        self._section_label("Файлы")
        file_btns = ttk.Frame(self.main_frame)
        file_btns.pack(fill="x", **pad)
        ttk.Button(file_btns, text="Добавить файлы",
                   command=self._add_files).pack(side="left", padx=3)
        ttk.Button(file_btns, text="Добавить папку",
                   command=self._add_folder).pack(side="left", padx=3)
        ttk.Button(file_btns, text="Очистить",
                   command=self._clear_files).pack(side="left", padx=3)

        self.file_listbox = tk.Listbox(self.main_frame, height=5,
                                       selectmode="extended")
        self.file_listbox.pack(fill="x", **pad)

        # Выходная папка
        out_row = ttk.Frame(self.main_frame)
        out_row.pack(fill="x", **pad)
        ttk.Label(out_row, text="Папка результатов:").pack(side="left")
        self.output_var = tk.StringVar(
            value=self._saved_output or "./cleaned"
        )
        ttk.Entry(out_row, textvariable=self.output_var, width=35).pack(
            side="left", padx=5, fill="x", expand=True
        )
        ttk.Button(out_row, text="Обзор",
                   command=self._browse_output).pack(side="left", padx=3)

        # ── Прогресс ──
        self.progress = ttk.Progressbar(self.main_frame, mode="determinate")
        self.progress.pack(fill="x", **pad)
        self.progress_label = ttk.Label(self.main_frame, text="")
        self.progress_label.pack(anchor="w", padx=10)

        # ── Лог ──
        self._section_label("Лог")
        self.log_text = scrolledtext.ScrolledText(
            self.main_frame, height=8, width=80, state="disabled", wrap="word"
        )
        self.log_text.pack(fill="x", **pad)
        self.log_text.tag_configure("success", foreground="green")
        self.log_text.tag_configure("warning", foreground="orange")
        self.log_text.tag_configure("error", foreground="red")
        self.log_text.tag_configure("info", foreground="blue")

        # ── Кнопки действий ──
        action_row = ttk.Frame(self.main_frame)
        action_row.pack(fill="x", pady=10, padx=10)
        self.btn_process = ttk.Button(
            action_row, text="ОБРАБОТАТЬ", command=self._start_processing
        )
        self.btn_process.pack(side="left", padx=5)
        ttk.Button(action_row, text="Предпросмотр",
                   command=self._preview).pack(side="left", padx=5)
        ttk.Button(action_row, text="Карта замен",
                   command=self._show_replacement_map).pack(side="left", padx=5)
        self.btn_cancel = ttk.Button(
            action_row, text="Отмена", command=self._cancel, state="disabled"
        )
        self.btn_cancel.pack(side="left", padx=5)

        # ── Статус-бар ──
        self.status_var = tk.StringVar(value="Готов к работе")
        status_bar = ttk.Label(
            self.main_frame, textvariable=self.status_var,
            relief="sunken", anchor="w"
        )
        status_bar.pack(fill="x", side="bottom", padx=10, pady=5)

    def _section_label(self, text: str):
        sep = ttk.Separator(self.main_frame, orient="horizontal")
        sep.pack(fill="x", padx=10, pady=(10, 2))
        lbl = ttk.Label(self.main_frame, text=text, font=("", 10, "bold"))
        lbl.pack(anchor="w", padx=10)

    def _check_tesseract(self):
        """Проверяет доступность Tesseract OCR и обновляет UI."""
        try:
            from core.ocr_utils import is_tesseract_available
            if is_tesseract_available():
                self.ocr_status_label.configure(
                    text="Tesseract найден", foreground="green"
                )
            else:
                self.ocr_status_label.configure(
                    text="Tesseract не установлен", foreground="red"
                )
        except Exception:
            self.ocr_status_label.configure(
                text="pytesseract не установлен", foreground="red"
            )

    def _on_ocr_toggled(self):
        """Вызывается при переключении чекбокса OCR."""
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
        """Добавляет новый ряд параметров замены."""
        idx = len(self.field_rows)
        row = FieldRow(
            self.fields_container, field_type,
            on_delete=self._remove_field_row, idx=idx
        )
        self.field_rows.append(row)
        return row

    def _remove_field_row(self, row: FieldRow):
        """Удаляет ряд параметров."""
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
                ("Документы", "*.docx *.pdf"),
                ("Word", "*.docx"),
                ("PDF", "*.pdf"),
                ("Все файлы", "*.*"),
            ],
        )
        for p in paths:
            if is_valid_file(p) and p not in self.files:
                self.files.append(p)
                self.file_listbox.insert(tk.END, Path(p).name)
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
                    self.file_listbox.insert(tk.END, Path(fp).name)
        self._update_status()

    def _clear_files(self):
        self.files.clear()
        self.file_listbox.delete(0, tk.END)
        self._update_status()

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Папка для результатов")
        if folder:
            self.output_var.set(folder)

    def _on_stamp_selected(self, event=None):
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
        self.log_text.insert(tk.END, message + "\n", tag)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
        logger.info(message)

    def _update_status(self):
        n = len(self.files)
        docx_count = sum(1 for f in self.files if f.lower().endswith('.docx'))
        pdf_count = sum(1 for f in self.files if f.lower().endswith('.pdf'))
        self.status_var.set(
            f"Файлов: {n} (DOCX: {docx_count}, PDF: {pdf_count})"
        )

    # ── Build replacement rules ─────────────────────────────

    def _build_replacement_rules(self) -> list[dict]:
        """Собирает replacement_rules из всех полей GUI."""
        rules = []
        self.all_mappers = []

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

            elif ft == "Город":
                patterns = build_city_patterns(search)
                rules.append({
                    "patterns": patterns,
                    "replacement": replace,
                    "type": "city",
                })

            elif ft == "ФИО подписант":
                # Одна фамилия — используем SurnamePattern + фиксированную замену
                sp = SurnamePattern(search, search_with_initials=True,
                                    search_feminine=True)
                patterns = sp.get_all_patterns_sorted()
                rules.append({
                    "patterns": patterns,
                    "replacement": replace,
                    "type": "signatory",
                })

            elif ft == "ФИО участники":
                # Несколько фамилий — используем ReplacementMapper
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
        self.progress["value"] = 0
        self.progress["maximum"] = len(self.files)

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
                else:
                    continue

                status = result.get("status", "error")
                matches = result.get("matches", {})
                err = result.get("error_message")

                # Суммируем статистику
                for k, v in matches.items():
                    total_matches[k] = total_matches.get(k, 0) + v

                total_file = sum(matches.values()) if isinstance(matches, dict) else 0

                # OCR-информация
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

            self.after(0, lambda v=i + 1: self.progress.configure(value=v))

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

        win = tk.Toplevel(self)
        win.title("Предпросмотр вхождений")
        win.geometry("700x500")

        text = scrolledtext.ScrolledText(win, wrap="word")
        text.pack(fill="both", expand=True, padx=10, pady=10)
        text.tag_configure("header", font=("", 10, "bold"))
        text.tag_configure("match", foreground="red")
        text.tag_configure("repl", foreground="green")

        for filepath in self.files:
            filename = Path(filepath).name
            ext = Path(filepath).suffix.lower()

            text.insert(tk.END, f"\n{'='*50}\n", "header")
            text.insert(tk.END, f"{filename}\n", "header")

            try:
                if ext == '.docx':
                    result = preview_docx(filepath, replacement_rules)
                elif ext == '.pdf':
                    result = preview_pdf(
                        filepath, replacement_rules,
                        ocr_enabled=self.ocr_enabled.get(),
                    )
                else:
                    continue

                matches = result.get("matches", [])
                if not matches:
                    text.insert(tk.END, "  Вхождений не найдено\n")
                    continue

                type_counts = result.get("type_counts", {})
                counts_str = ", ".join(
                    f"{k}: {v}" for k, v in type_counts.items()
                )
                text.insert(tk.END, f"  {counts_str}\n\n")

                for m in matches:
                    page_info = (
                        f" (стр. {m['page']})" if 'page' in m else ""
                    )
                    ocr_tag = " [OCR]" if m.get('ocr') else ""
                    text.insert(
                        tk.END,
                        f"  [{m['type']}]{page_info}{ocr_tag} "
                    )
                    text.insert(tk.END, m['original'], "match")
                    text.insert(tk.END, " -> ")
                    text.insert(tk.END, m['replacement'], "repl")
                    text.insert(
                        tk.END, f"\n  Контекст: {m['context']}\n\n"
                    )

            except Exception as e:
                text.insert(tk.END, f"  Ошибка: {e}\n")

        text.configure(state="disabled")

    # ── Replacement Map ─────────────────────────────────────

    def _show_replacement_map(self):
        if not self.all_mappers:
            messagebox.showinfo(
                "Карта замен",
                "Сначала выполните обработку файлов."
            )
            return

        # Собираем все маппинги
        all_mappings = {}
        for mapper in self.all_mappers:
            all_mappings.update(mapper.get_map())

        if not all_mappings:
            messagebox.showinfo("Карта замен", "Замен не найдено.")
            return

        win = tk.Toplevel(self)
        win.title("Карта замен (сеанс)")
        win.geometry("600x400")

        tree = ttk.Treeview(
            win, columns=("original", "replacement"), show="headings"
        )
        tree.heading("original", text="Оригинал")
        tree.heading("replacement", text="Заменено на")
        tree.column("original", width=250)
        tree.column("replacement", width=250)

        for orig, repl in all_mappings.items():
            tree.insert("", tk.END, values=(orig, repl))

        tree.pack(fill="both", expand=True, padx=10, pady=10)

        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", padx=10, pady=5)

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

        ttk.Button(btn_row, text="Экспорт в CSV",
                   command=export_csv).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Закрыть",
                   command=win.destroy).pack(side="right", padx=5)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
