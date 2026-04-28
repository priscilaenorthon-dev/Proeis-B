@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   PROEIS - Verificador e Instalador de Dependencias
echo ============================================================
echo.

set PYTHON_CMD=python

%PYTHON_CMD% --version >nul 2>&1
if not errorlevel 1 goto python_ok

set PYTHON_CMD=py
py --version >nul 2>&1
if not errorlevel 1 goto python_ok

echo [!] Python nao encontrado no sistema.
echo     Baixando Python 3.12.3. Isso pode levar alguns minutos...
echo.

curl -L --progress-bar -o "%TEMP%\python_setup.exe" "https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe"

if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao baixar Python automaticamente.
    echo        Instale manualmente em https://www.python.org/downloads/
    echo        Depois execute este arquivo novamente.
    pause
    exit /b 1
)

echo.
echo [!] Instalando Python 3.12.3...
"%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
del "%TEMP%\python_setup.exe" >nul 2>&1

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
        echo [OK] Python instalado.
        echo [!] Feche esta janela e abra o instalar.bat novamente para continuar.
        pause
        exit /b 0
    )
)

:python_ok
for /f "tokens=*" %%v in ('%PYTHON_CMD% --version 2^>^&1') do echo [OK] %%v encontrado.

echo.
echo [..] Verificando pip...
%PYTHON_CMD% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [!] Instalando pip...
    %PYTHON_CMD% -m ensurepip --upgrade
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar pip.
        pause
        exit /b 1
    )
)

echo.
echo [..] Atualizando pip...
%PYTHON_CMD% -m pip install --upgrade pip --quiet

echo.
echo [..] Instalando dependencias do requirements.txt...
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [!] Falha usando o PyPI padrao. Tentando espelho alternativo...
    %PYTHON_CMD% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
    if errorlevel 1 (
        echo.
        echo [ERRO] Nao foi possivel instalar as dependencias.
        echo        Verifique sua conexao, proxy ou permissao de rede.
        pause
        exit /b 1
    )
)

echo.
echo [..] Validando instalacao...
%PYTHON_CMD% -c "import requests, bs4, truststore; print('Dependencias OK')"
if errorlevel 1 (
    echo.
    echo [ERRO] Dependencias instaladas, mas a validacao falhou.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Tudo instalado e pronto!
echo   Abrindo o painel PROEIS em 3 segundos...
echo ============================================================
echo.
timeout /t 3 /nobreak >nul
call "%~dp0abrir_painel.bat"
