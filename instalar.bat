@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   PROEIS - Verificador e Instalador de Dependencias
echo ============================================================
echo.

:: ── 1. Verifica Python ──────────────────────────────────────
set PYTHON_CMD=python

%PYTHON_CMD% --version >nul 2>&1
if not errorlevel 1 goto python_ok

set PYTHON_CMD=py
py --version >nul 2>&1
if not errorlevel 1 goto python_ok

echo [!] Python nao encontrado no sistema.
echo     Baixando Python 3.12 (pode levar alguns minutos)...
echo.

curl -L --progress-bar -o "%TEMP%\python_setup.exe" "https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe"

if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao baixar Python automaticamente.
    echo        Acesse https://www.python.org/downloads/ e instale manualmente.
    echo        Depois execute este arquivo novamente.
    pause
    exit /b 1
)

echo.
echo [!] Instalando Python 3.12...
"%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
del "%TEMP%\python_setup.exe" >nul 2>&1

:: Tenta atualizar PATH da sessao atual via registro
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do (
    set "PATH=%%b;!PATH!"
)

set PYTHON_CMD=python
python --version >nul 2>&1
if errorlevel 1 (
    set PYTHON_CMD=py
    py --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [OK] Python instalado com sucesso!
        echo [!] Feche esta janela e abra o instalar.bat novamente para continuar.
        pause
        exit /b 0
    )
)

:python_ok
for /f "tokens=*" %%v in ('%PYTHON_CMD% --version 2^>^&1') do echo [OK] %%v encontrado.

:: ── 2. Garante pip atualizado ───────────────────────────────
echo.
echo [..] Verificando pip...
%PYTHON_CMD% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [!] Instalando pip...
    %PYTHON_CMD% -m ensurepip --upgrade >nul 2>&1
)
%PYTHON_CMD% -m pip install --upgrade pip --quiet
echo [OK] pip atualizado.

:: ── 3. Verifica e instala requests ─────────────────────────
echo.
%PYTHON_CMD% -c "import requests" >nul 2>&1
if errorlevel 1 (
    echo [!] Instalando requests...
    %PYTHON_CMD% -m pip install requests
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar requests. Verifique sua conexao.
        pause
        exit /b 1
    )
    echo [OK] requests instalado.
) else (
    echo [OK] requests ja esta instalado.
)

:: ── 4. Verifica e instala beautifulsoup4 ───────────────────
%PYTHON_CMD% -c "import bs4" >nul 2>&1
if errorlevel 1 (
    echo [!] Instalando beautifulsoup4...
    %PYTHON_CMD% -m pip install beautifulsoup4
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar beautifulsoup4. Verifique sua conexao.
        pause
        exit /b 1
    )
    echo [OK] beautifulsoup4 instalado.
) else (
    echo [OK] beautifulsoup4 ja esta instalado.
)

:: ── 5. Verificacao final ────────────────────────────────────
echo.
echo ============================================================
echo   Tudo instalado e pronto!
echo   Abrindo o painel PROEIS em 3 segundos...
echo ============================================================
echo.
timeout /t 3 /nobreak >nul
call "%~dp0abrir_painel.bat"
