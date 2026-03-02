"""
Company Name Cleaner — портативное GUI-приложение.
Замена названия компании и фамилий сотрудников на заглушки в .docx и .pdf.
"""

import csv
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

from core.patterns import build_company_patterns
from core.surnames import SurnamePattern
from core.replacements import (
    get_company_replacement_options,
    get_surname_replacement_options,
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

APP_TITLE = "Titan Cleaner v1.0"
WINDOW_WIDTH = 880
WINDOW_HEIGHT = 800

logger = setup_logging()


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
        self.replacement_mapper = None
        self.company_mapper_log: list[tuple[str, str]] = []

        self._load_saved_config()
        self._build_ui()
        self._bind_hotkeys()

    # ── Config ──────────────────────────────────────────────

    def _load_saved_config(self):
        cfg = load_config()
        self._saved_company = cfg.get("company_name", "")
        self._saved_surnames = cfg.get("surnames", "")
        self._saved_output = cfg.get("output_dir", "")
        self._saved_company_repl = cfg.get("company_replacement", "")
        self._saved_surname_repl = cfg.get("surname_replacement", "")

    def _save_current_config(self):
        save_config({
            "company_name": self.company_entry.get(),
            "surnames": self.surnames_text.get("1.0", tk.END).strip(),
            "output_dir": self.output_var.get(),
            "company_replacement": self.company_repl_var.get(),
            "surname_replacement": self.surname_repl_var.get(),
        })

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

        # ── Секция: Название компании ──
        self._section_label("Название компании")
        row = ttk.Frame(self.main_frame)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Искать:").pack(side="left")
        self.company_entry = ttk.Entry(row, width=40)
        self.company_entry.pack(side="left", padx=5, fill="x", expand=True)
        self.company_entry.insert(0, self._saved_company)

        # Замена компании
        row2 = ttk.Frame(self.main_frame)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="Заменить на:").pack(side="left")
        self.company_repl_var = tk.StringVar(value=self._saved_company_repl or 'ООО «Ромашка»')
        company_options = []
        for cat, opts in get_company_replacement_options().items():
            company_options.extend(opts)
        self.company_repl_combo = ttk.Combobox(
            row2, textvariable=self.company_repl_var,
            values=list(dict.fromkeys(company_options)),
            width=35,
        )
        self.company_repl_combo.pack(side="left", padx=5, fill="x", expand=True)

        # Чекбоксы
        checks = ttk.Frame(self.main_frame)
        checks.pack(fill="x", **pad)
        self.chk_cases = tk.BooleanVar(value=True)
        self.chk_quotes = tk.BooleanVar(value=True)
        self.chk_orgforms = tk.BooleanVar(value=True)
        self.chk_caseins = tk.BooleanVar(value=True)

        ttk.Checkbutton(checks, text="Падежи", variable=self.chk_cases).pack(side="left", padx=5)
        ttk.Checkbutton(checks, text="Кавычки", variable=self.chk_quotes).pack(side="left", padx=5)
        ttk.Checkbutton(checks, text="Орг. формы", variable=self.chk_orgforms).pack(side="left", padx=5)
        ttk.Checkbutton(checks, text="Без учёта регистра", variable=self.chk_caseins).pack(side="left", padx=5)

        # ── Секция: Фамилии ──
        self._section_label("Фамилии сотрудников")
        ttk.Label(self.main_frame, text="По одной на строку:").pack(anchor="w", **pad)

        self.surnames_text = scrolledtext.ScrolledText(
            self.main_frame, height=5, width=50, wrap="word"
        )
        self.surnames_text.pack(fill="x", **pad)
        if self._saved_surnames:
            self.surnames_text.insert("1.0", self._saved_surnames)

        btn_row = ttk.Frame(self.main_frame)
        btn_row.pack(fill="x", **pad)
        ttk.Button(btn_row, text="Из файла .txt", command=self._load_surnames_file).pack(side="left", padx=3)
        ttk.Button(btn_row, text="Очистить", command=lambda: self.surnames_text.delete("1.0", tk.END)).pack(side="left", padx=3)

        # Замена фамилий
        row3 = ttk.Frame(self.main_frame)
        row3.pack(fill="x", **pad)
        ttk.Label(row3, text="Заменять на:").pack(side="left")
        self.surname_repl_var = tk.StringVar(value=self._saved_surname_repl or 'Сотрудник №{n}')
        surname_options = []
        for cat, opts in get_surname_replacement_options().items():
            surname_options.extend(opts)
        self.surname_repl_combo = ttk.Combobox(
            row3, textvariable=self.surname_repl_var,
            values=list(dict.fromkeys(surname_options)),
            width=35,
        )
        self.surname_repl_combo.pack(side="left", padx=5, fill="x", expand=True)

        chk2 = ttk.Frame(self.main_frame)
        chk2.pack(fill="x", **pad)
        self.chk_initials = tk.BooleanVar(value=True)
        self.chk_feminine = tk.BooleanVar(value=True)
        ttk.Checkbutton(chk2, text="С инициалами", variable=self.chk_initials).pack(side="left", padx=5)
        ttk.Checkbutton(chk2, text="Женские формы", variable=self.chk_feminine).pack(side="left", padx=5)

        # ── Секция: Режим PDF ──
        self._section_label("Режим замены в PDF")
        pdf_frame = ttk.Frame(self.main_frame)
        pdf_frame.pack(fill="x", **pad)
        self.pdf_mode = tk.StringVar(value="text")
        ttk.Radiobutton(pdf_frame, text="Текстовая заглушка", variable=self.pdf_mode, value="text").pack(anchor="w")
        stamp_row = ttk.Frame(pdf_frame)
        stamp_row.pack(anchor="w")
        ttk.Radiobutton(stamp_row, text="Графический штамп:", variable=self.pdf_mode, value="stamp").pack(side="left")
        self.stamp_var = tk.StringVar(value="чёрная плашка")
        stamp_opts = ["чёрная плашка", "ромашка", "замок", "конфиденциально", "свой PNG..."]
        self.stamp_combo = ttk.Combobox(stamp_row, textvariable=self.stamp_var, values=stamp_opts, width=20, state="readonly")
        self.stamp_combo.pack(side="left", padx=5)
        self.stamp_combo.bind("<<ComboboxSelected>>", self._on_stamp_selected)
        self.custom_stamp_path = None

        # ── Секция: Файлы ──
        self._section_label("Файлы")
        file_btns = ttk.Frame(self.main_frame)
        file_btns.pack(fill="x", **pad)
        ttk.Button(file_btns, text="Добавить файлы", command=self._add_files).pack(side="left", padx=3)
        ttk.Button(file_btns, text="Добавить папку", command=self._add_folder).pack(side="left", padx=3)
        ttk.Button(file_btns, text="Очистить", command=self._clear_files).pack(side="left", padx=3)

        self.file_listbox = tk.Listbox(self.main_frame, height=5, selectmode="extended")
        self.file_listbox.pack(fill="x", **pad)

        # Выходная папка
        out_row = ttk.Frame(self.main_frame)
        out_row.pack(fill="x", **pad)
        ttk.Label(out_row, text="Папка результатов:").pack(side="left")
        self.output_var = tk.StringVar(value=self._saved_output or "./cleaned")
        ttk.Entry(out_row, textvariable=self.output_var, width=35).pack(side="left", padx=5, fill="x", expand=True)
        ttk.Button(out_row, text="Обзор", command=self._browse_output).pack(side="left", padx=3)

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
        self.btn_process = ttk.Button(action_row, text="▶ ОБРАБОТАТЬ", command=self._start_processing)
        self.btn_process.pack(side="left", padx=5)
        ttk.Button(action_row, text="Предпросмотр", command=self._preview).pack(side="left", padx=5)
        ttk.Button(action_row, text="Карта замен", command=self._show_replacement_map).pack(side="left", padx=5)
        self.btn_cancel = ttk.Button(action_row, text="Отмена", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=5)

        # ── Статус-бар ──
        self.status_var = tk.StringVar(value="Готов к работе")
        status_bar = ttk.Label(self.main_frame, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(fill="x", side="bottom", padx=10, pady=5)

    def _section_label(self, text: str):
        sep = ttk.Separator(self.main_frame, orient="horizontal")
        sep.pack(fill="x", padx=10, pady=(10, 2))
        lbl = ttk.Label(self.main_frame, text=text, font=("", 10, "bold"))
        lbl.pack(anchor="w", padx=10)

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

    def _load_surnames_file(self):
        path = filedialog.askopenfilename(
            title="Файл со списком фамилий",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
        )
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.surnames_text.delete("1.0", tk.END)
                self.surnames_text.insert("1.0", content)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{e}")

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
        self.status_var.set(f"Файлов: {n} (DOCX: {docx_count}, PDF: {pdf_count})")

    # ── Build patterns ──────────────────────────────────────

    def _build_patterns(self):
        """Собирает паттерны из текущих настроек."""
        company_name = self.company_entry.get().strip()
        company_patterns = []
        if company_name:
            company_patterns = build_company_patterns(
                company_name,
                include_cases=self.chk_cases.get(),
                include_quotes=self.chk_quotes.get(),
                include_org_forms=self.chk_orgforms.get(),
                case_insensitive=self.chk_caseins.get(),
            )

        surnames_raw = self.surnames_text.get("1.0", tk.END).strip()
        surname_patterns = []
        if surnames_raw:
            for line in surnames_raw.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Поддержка перечисления через запятую
                for surname in line.split(','):
                    surname = surname.strip()
                    if surname:
                        sp = SurnamePattern(
                            surname,
                            search_with_initials=self.chk_initials.get(),
                            search_feminine=self.chk_feminine.get(),
                        )
                        surname_patterns.extend(sp.get_all_patterns_sorted())

        return company_patterns, surname_patterns

    def _get_stamp_path(self) -> str | None:
        if self.custom_stamp_path:
            return self.custom_stamp_path
        stamp_name = self.stamp_var.get()
        if stamp_name in ("чёрная плашка", "") or stamp_name.startswith("Свой:"):
            if stamp_name.startswith("Свой:"):
                return self.custom_stamp_path
            return None
        # Встроенные штампы
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
        if not self.company_entry.get().strip() and not self.surnames_text.get("1.0", tk.END).strip():
            messagebox.showwarning("Внимание", "Укажите название компании или фамилии для замены.")
            return False
        if not self.files:
            messagebox.showwarning("Внимание", "Добавьте файлы для обработки.")
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

        self.company_mapper_log = []
        self.replacement_mapper = ReplacementMapper(self.surname_repl_var.get())

        thread = threading.Thread(target=self._process_files, daemon=True)
        thread.start()

    def _cancel(self):
        if self.processing:
            self.cancel_flag = True
            self._log("Отмена обработки...", "warning")

    def _process_files(self):
        company_patterns, surname_patterns = self._build_patterns()
        company_replacement = self.company_repl_var.get()
        output_dir = self.output_var.get()

        try:
            ensure_output_dir(output_dir)
        except Exception as e:
            self.after(0, lambda: self._log(f"Ошибка создания папки: {e}", "error"))
            self._finish_processing()
            return

        total_company = 0
        total_surname = 0

        for i, filepath in enumerate(self.files):
            if self.cancel_flag:
                self.after(0, lambda: self._log("Обработка отменена.", "warning"))
                break

            filename = Path(filepath).name
            ext = Path(filepath).suffix.lower()
            output_path = str(Path(output_dir) / filename)

            # Не перезаписываем оригинал
            if os.path.abspath(filepath) == os.path.abspath(output_path):
                stem = Path(filepath).stem
                output_path = str(Path(output_dir) / f"{stem}_cleaned{ext}")

            self.after(0, lambda fn=filename: self.progress_label.configure(
                text=f"Обработка: {fn}"
            ))

            try:
                file_size = os.path.getsize(filepath)
                if file_size > 100 * 1024 * 1024:
                    self.after(0, lambda fn=filename: self._log(
                        f"⚠ {fn} — большой файл ({format_file_size(file_size)})", "warning"
                    ))

                if ext == '.docx':
                    result = clean_docx(
                        filepath, output_path,
                        company_patterns, surname_patterns,
                        company_replacement, self.replacement_mapper,
                    )
                elif ext == '.pdf':
                    if self.pdf_mode.get() == "text":
                        result = clean_pdf_text_mode(
                            filepath, output_path,
                            company_patterns, surname_patterns,
                            company_replacement, self.replacement_mapper,
                        )
                    else:
                        stamp_path = self._get_stamp_path()
                        result = clean_pdf_stamp_mode(
                            filepath, output_path,
                            company_patterns, surname_patterns,
                            stamp_path=stamp_path,
                            stamp_type=self.stamp_var.get(),
                        )
                else:
                    continue

                status = result.get("status", "error")
                c = result.get("company_matches", 0)
                s = result.get("surname_matches", 0)
                total_company += c
                total_surname += s
                err = result.get("error_message")

                if status == "success":
                    total = c + s
                    if total > 0:
                        msg = f"✓ {filename} — компания: {c}, фамилии: {s}"
                        self.after(0, lambda m=msg: self._log(m, "success"))
                    else:
                        msg = f"⚠ {filename} — 0 вхождений"
                        self.after(0, lambda m=msg: self._log(m, "warning"))
                elif status == "warning":
                    msg = f"⚠ {filename} — {err}"
                    self.after(0, lambda m=msg: self._log(m, "warning"))
                else:
                    msg = f"✗ {filename} — ошибка: {err}"
                    self.after(0, lambda m=msg: self._log(m, "error"))

            except Exception as e:
                msg = f"✗ {filename} — исключение: {e}"
                self.after(0, lambda m=msg: self._log(m, "error"))
                logger.exception(f"Error processing {filepath}")

            self.after(0, lambda v=i + 1: self.progress.configure(value=v))

        summary = f"Готово. Компания: {total_company}, фамилии: {total_surname}"
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

        company_patterns, surname_patterns = self._build_patterns()
        preview_mapper = ReplacementMapper(self.surname_repl_var.get())

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
            text.insert(tk.END, f"📄 {filename}\n", "header")

            try:
                if ext == '.docx':
                    result = preview_docx(
                        filepath, company_patterns, surname_patterns,
                        preview_mapper,
                    )
                elif ext == '.pdf':
                    result = preview_pdf(
                        filepath, company_patterns, surname_patterns,
                        preview_mapper,
                    )
                else:
                    continue

                matches = result.get("matches", [])
                if not matches:
                    text.insert(tk.END, "  Вхождений не найдено\n")
                    continue

                text.insert(tk.END,
                            f"  Компания: {result.get('company_count', 0)}, "
                            f"Фамилии: {result.get('surname_count', 0)}\n\n")

                for m in matches:
                    page_info = f" (стр. {m['page']})" if 'page' in m else ""
                    text.insert(tk.END, f"  [{m['type']}]{page_info} ")
                    text.insert(tk.END, m['original'], "match")
                    text.insert(tk.END, " → ")
                    text.insert(tk.END, m['replacement'], "repl")
                    text.insert(tk.END, f"\n  Контекст: {m['context']}\n\n")

            except Exception as e:
                text.insert(tk.END, f"  Ошибка: {e}\n")

        text.configure(state="disabled")

    # ── Replacement Map ─────────────────────────────────────

    def _show_replacement_map(self):
        if not self.replacement_mapper:
            messagebox.showinfo("Карта замен", "Сначала выполните обработку файлов.")
            return

        mapping = self.replacement_mapper.get_map()
        if not mapping:
            messagebox.showinfo("Карта замен", "Замен не найдено.")
            return

        win = tk.Toplevel(self)
        win.title("Карта замен (сеанс)")
        win.geometry("600x400")

        # Таблица
        tree = ttk.Treeview(win, columns=("original", "replacement"), show="headings")
        tree.heading("original", text="Оригинал")
        tree.heading("replacement", text="Заменено на")
        tree.column("original", width=250)
        tree.column("replacement", width=250)

        for orig, repl in mapping.items():
            tree.insert("", tk.END, values=(orig, repl))

        tree.pack(fill="both", expand=True, padx=10, pady=10)

        # Кнопки
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
                    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(["Оригинал", "Заменено на"])
                        for orig, repl in mapping.items():
                            writer.writerow([orig, repl])
                    messagebox.showinfo("Экспорт", f"Карта замен сохранена:\n{path}")
                except Exception as e:
                    messagebox.showerror("Ошибка", str(e))

        ttk.Button(btn_row, text="Экспорт в CSV", command=export_csv).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Закрыть", command=win.destroy).pack(side="right", padx=5)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
