@echo off
cd /d "%~dp0"
python --version >nul 2>&1
if not errorlevel 1 (
    python proeis_gui.py
    exit /b %errorlevel%
)

py --version >nul 2>&1
if not errorlevel 1 (
    py proeis_gui.py
    exit /b %errorlevel%
)

echo Python nao encontrado. Execute instalar.bat ou instale o Python marcando "Add python.exe to PATH".
pause
exit /b 1
