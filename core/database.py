"""
SQLite база для хранения истории анонимизации.
Файл titan_cleaner.db рядом с .exe / main.py.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.utils import get_app_dir


def _db_path() -> Path:
    return get_app_dir() / "titan_cleaner.db"


def get_connection() -> sqlite3.Connection:
    """Возвращает соединение с БД, создаёт таблицы если нет."""
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            total_replacements INTEGER DEFAULT 0,
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS file_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            source_filename TEXT NOT NULL,
            output_filename TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            total_replacements INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_mapping_id INTEGER NOT NULL,
            original TEXT NOT NULL,
            pseudonym TEXT NOT NULL,
            entity_type TEXT DEFAULT '',
            FOREIGN KEY (file_mapping_id) REFERENCES file_mappings(id)
        );

        CREATE INDEX IF NOT EXISTS idx_mappings_file ON mappings(file_mapping_id);
        CREATE INDEX IF NOT EXISTS idx_file_mappings_session ON file_mappings(session_id);

        CREATE TABLE IF NOT EXISTS user_dictionary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL COLLATE NOCASE,
            dict_type TEXT NOT NULL CHECK(dict_type IN ('exclusion', 'inclusion')),
            entity_type TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(word, dict_type)
        );
        CREATE INDEX IF NOT EXISTS idx_user_dict_type ON user_dictionary(dict_type);
    """)
    conn.commit()


class SessionDB:
    """Работа с сессиями анонимизации."""

    def __init__(self):
        self.conn = get_connection()
        self.session_id: Optional[int] = None

    def start_session(self) -> int:
        """Создаёт новую сессию, возвращает ID."""
        cur = self.conn.execute(
            "INSERT INTO sessions (total_replacements) VALUES (0)"
        )
        self.conn.commit()
        self.session_id = cur.lastrowid
        return self.session_id

    def save_file_mappings(
        self,
        source_filename: str,
        output_filename: str,
        mappings: list[dict],
    ) -> int:
        """
        Сохраняет маппинг для одного файла.
        mappings: [{"original": ..., "pseudonym": ..., "entity_type": ...}, ...]
        Возвращает file_mapping_id.
        """
        if self.session_id is None:
            self.start_session()

        cur = self.conn.execute(
            "INSERT INTO file_mappings (session_id, source_filename, output_filename, total_replacements) "
            "VALUES (?, ?, ?, ?)",
            (self.session_id, source_filename, output_filename, len(mappings)),
        )
        file_mapping_id = cur.lastrowid

        if mappings:
            self.conn.executemany(
                "INSERT INTO mappings (file_mapping_id, original, pseudonym, entity_type) "
                "VALUES (?, ?, ?, ?)",
                [
                    (file_mapping_id, m["original"], m["pseudonym"], m.get("entity_type", ""))
                    for m in mappings
                ],
            )

        # Обновляем общий счётчик сессии
        self.conn.execute(
            "UPDATE sessions SET total_replacements = "
            "(SELECT COALESCE(SUM(total_replacements), 0) FROM file_mappings WHERE session_id = ?) "
            "WHERE id = ?",
            (self.session_id, self.session_id),
        )
        self.conn.commit()
        return file_mapping_id

    def close(self):
        if self.conn:
            self.conn.close()

    # ── Запросы для деанонимизации ──

    @staticmethod
    def search_files(query: str = "", limit: int = 50) -> list[dict]:
        """Поиск файлов в истории. Возвращает список для выпадающего списка."""
        conn = get_connection()
        try:
            if query.strip():
                rows = conn.execute(
                    "SELECT fm.id, fm.session_id, fm.source_filename, fm.output_filename, "
                    "fm.created_at, fm.total_replacements "
                    "FROM file_mappings fm "
                    "WHERE fm.source_filename LIKE ? OR fm.output_filename LIKE ? "
                    "ORDER BY fm.created_at DESC LIMIT ?",
                    (f"%{query}%", f"%{query}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT fm.id, fm.session_id, fm.source_filename, fm.output_filename, "
                    "fm.created_at, fm.total_replacements "
                    "FROM file_mappings fm "
                    "ORDER BY fm.created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_file_mappings(file_mapping_id: int) -> list[dict]:
        """Возвращает все маппинги для файла."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT original, pseudonym, entity_type FROM mappings "
                "WHERE file_mapping_id = ? ORDER BY id",
                (file_mapping_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_reverse_rules(file_mapping_id: int) -> list[dict]:
        """Строит правила обратной замены из БД для деанонимизации."""
        import re
        mappings = SessionDB.get_file_mappings(file_mapping_id)
        rules = []
        seen = set()
        for m in mappings:
            pseudonym = m["pseudonym"]
            original = m["original"]
            if pseudonym in seen:
                continue
            seen.add(pseudonym)
            pattern = re.compile(re.escape(pseudonym), re.IGNORECASE)
            rules.append({
                "patterns": [pattern],
                "replacement": original,
                "type": "deanonymize",
            })
        rules.sort(key=lambda r: len(r["patterns"][0].pattern), reverse=True)
        return rules

    @staticmethod
    def get_all_sessions(limit: int = 100) -> list[dict]:
        """Все сессии для истории."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT s.id, s.created_at, s.total_replacements, "
                "GROUP_CONCAT(fm.source_filename, ', ') as files "
                "FROM sessions s "
                "LEFT JOIN file_mappings fm ON fm.session_id = s.id "
                "GROUP BY s.id "
                "ORDER BY s.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


class UserDictionary:
    """Словарь исключений и включений для автопоиска."""

    @staticmethod
    def add(word: str, dict_type: str, entity_type: str = "") -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO user_dictionary (word, dict_type, entity_type) VALUES (?, ?, ?)",
                (word.strip(), dict_type, entity_type))
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    @staticmethod
    def remove(word: str, dict_type: str) -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "DELETE FROM user_dictionary WHERE word = ? COLLATE NOCASE AND dict_type = ?",
                (word.strip(), dict_type))
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    @staticmethod
    def get_exclusions() -> set[str]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT word FROM user_dictionary WHERE dict_type = 'exclusion'").fetchall()
            return {row["word"].lower() for row in rows}
        finally:
            conn.close()

    @staticmethod
    def get_inclusions() -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT word, entity_type FROM user_dictionary WHERE dict_type = 'inclusion'").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
