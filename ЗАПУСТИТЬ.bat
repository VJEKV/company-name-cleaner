@echo off
chcp 65001 >nul 2>&1
title Company Name Cleaner

echo ============================================
echo   Company Name Cleaner - Первый запуск
echo ============================================
echo.

:: Проверяем Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] Python не найден!
    echo.
    echo Скачайте Python 3.11+ с https://www.python.org/downloads/
    echo При установке обязательно отметьте "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

:: Проверяем версию Python
python --version 2>&1 | findstr /R "3\.\(1[1-9]\|[2-9][0-9]\)" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ВНИМАНИЕ] Рекомендуется Python 3.11+
    echo Текущая версия:
    python --version
    echo.
)

:: Создаём venv если нет
if not exist ".venv" (
    echo [1/4] Создание виртуального окружения...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось создать venv
        pause
        exit /b 1
    )
)

:: Активируем venv
call .venv\Scripts\activate.bat

:: Устанавливаем зависимости если нужно
if not exist ".venv\installed.flag" (
    echo [2/4] Установка зависимостей...
    pip install -r requirements.txt -q
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось установить зависимости
        pause
        exit /b 1
    )
    echo done > .venv\installed.flag
) else (
    echo [2/4] Зависимости уже установлены
)

:: Генерируем штампы если нет
if not exist "assets\stamps\daisy.png" (
    echo [3/4] Генерация штампов...
    python generate_stamps.py
) else (
    echo [3/4] Штампы уже созданы
)

echo [4/4] Запуск приложения...
echo.
python main.py

:: Если приложение закрылось с ошибкой
if %errorlevel% neq 0 (
    echo.
    echo [ОШИБКА] Приложение завершилось с ошибкой
    pause
)
