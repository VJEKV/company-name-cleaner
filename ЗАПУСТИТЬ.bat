@echo off
chcp 65001 >nul 2>&1
title Titan Cleaner v3.0

echo ============================================
echo   Titan Cleaner v3.0
echo ============================================
echo.

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

:: Check Python version
python --version 2>&1 | findstr /R "3\.\(1[1-9]\|[2-9][0-9]\)" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Python 3.11+ recommended
    echo Current version:
    python --version
    echo.
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
    echo done > .venv\installed.flag
) else (
    echo [2/4] Dependencies already installed
)

:: Generate stamps
if not exist "assets\stamps\daisy.png" (
    echo [3/4] Generating stamps...
    python generate_stamps.py
) else (
    echo [3/4] Stamps ready
)

echo [4/4] Starting app...
echo.
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] App crashed
    pause
)
