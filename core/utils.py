"""Вспомогательные функции."""

import json
import logging
import os
import sys
from pathlib import Path

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def get_app_dir() -> Path:
    """Возвращает директорию рядом с .exe (или скриптом)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def get_assets_dir() -> Path:
    """Возвращает путь к директории assets."""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent
    return base / 'assets'


def setup_logging() -> logging.Logger:
    """Настраивает логирование в файл рядом с приложением."""
    log_path = get_app_dir() / 'cleaner.log'
    logger = logging.getLogger('CompanyCleaner')
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        fh = logging.FileHandler(str(log_path), encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
        logger.addHandler(fh)

    return logger


def load_config() -> dict:
    """Загружает настройки из config.json."""
    config_path = get_app_dir() / 'config.json'
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(config: dict) -> None:
    """Сохраняет настройки в config.json."""
    config_path = get_app_dir() / 'config.json'
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def format_file_size(size_bytes: int) -> str:
    """Форматирует размер файла."""
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} ТБ"


def is_valid_file(filepath: str) -> bool:
    """Проверяет, что файл — .docx, .pdf или .xlsx."""
    ext = Path(filepath).suffix.lower()
    return ext in ('.docx', '.pdf', '.xlsx', '.xls')


def ensure_output_dir(output_dir: str) -> Path:
    """Создаёт директорию для результатов если не существует."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path
