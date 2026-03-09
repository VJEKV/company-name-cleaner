@echo off
chcp 65001 >nul 2>&1
title Titan Cleaner v3.0

echo ============================================
echo   Titan Cleaner v3.0
echo ============================================
echo.

:: Clean old cache to avoid stale bytecode
if exist "__pycache__" rmdir /s /q __pycache__
if exist "core\__pycache__" rmdir /s /q core\__pycache__

:: Force reinstall if upgrading from old version
if exist ".venv\installed.flag" (
    findstr /c:"v3" ".venv\installed.flag" >nul 2>&1
    if %errorlevel% neq 0 (
        echo Upgrading from old version, reinstalling...
        del ".venv\installed.flag"
    )
)

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo.
    echo Download Python 3.11+ from https://www.python.org/downloads/
    echo Check "Add Python to PATH" during install
    echo.
    pause
    exit /b 1
)

:: Create venv if not exists
if not exist ".venv" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create venv
        pause
        exit /b 1
    )
)

:: Activate venv
call .venv\Scripts\activate.bat

:: Install dependencies
if not exist ".venv\installed.flag" (
    echo [2/4] Installing dependencies...
    pip install -r requirements.txt -q
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo v3 > .venv\installed.flag
) else (
    echo [2/4] Dependencies OK
)

:: Generate stamps
if not exist "assets\stamps\daisy.png" (
    echo [3/4] Generating stamps...
    python generate_stamps.py
) else (
    echo [3/4] Stamps OK
)

echo [4/4] Starting Titan Cleaner v3.0...
echo.
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] App crashed. Details above.
    pause
)
