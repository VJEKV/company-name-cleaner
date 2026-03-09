@echo off
chcp 65001 >nul 2>&1
title Build TitanCleaner.exe

echo ============================================
echo   Build TitanCleaner.exe
echo ============================================
echo.

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo Run ZAPUSTIT.bat first to install dependencies
    pause
    exit /b 1
)

pip install pyinstaller -q

python generate_stamps.py

echo.
echo Building EXE...
echo.

set ADDDATA=assets\stamps;assets\stamps
pyinstaller --onefile --windowed --name TitanCleaner --add-data %ADDDATA% main.py

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo   DONE! File: dist\TitanCleaner.exe
    echo ============================================
    echo.
    explorer dist
) else (
    echo.
    echo BUILD FAILED
)

pause
