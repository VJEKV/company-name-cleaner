@echo off
chcp 65001 >nul 2>&1
title Сборка CompanyCleaner.exe

echo ============================================
echo   Сборка CompanyCleaner.exe
echo ============================================
echo.

:: Активируем venv
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo Сначала запустите ЗАПУСТИТЬ.bat для установки зависимостей
    pause
    exit /b 1
)

:: Устанавливаем PyInstaller
pip install pyinstaller -q

:: Генерируем штампы
python generate_stamps.py

echo.
echo Сборка .exe (это займёт 1-3 минуты)...
echo.

pyinstaller --onefile --windowed --name "CompanyCleaner" --add-data "assets\stamps;assets\stamps" main.py

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo   ГОТОВО! Файл: dist\CompanyCleaner.exe
    echo ============================================
    echo.
    explorer dist
) else (
    echo.
    echo [ОШИБКА] Сборка не удалась
)

pause
