@echo off
REM ===================================================================
REM Script para generar el perfil interactivo HTML de la etapa
REM Uso:
REM   generar_perfil.bat
REM   generar_perfil.bat 2026-08-26
REM   generar_perfil.bat 2026-08-26 --titulo "Etapa 1"
REM ===================================================================

cd /d "%~dp0"

set FECHA=%1
if "%FECHA%"=="" (
    for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set datetime=%%I
    if defined datetime (
        set FECHA=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%
    ) else (
        set FECHA=2026-08-26
    )
)

echo =======================================================
echo 🚴 GENERANDO PERFIL INTERACTIVO DE ETAPA
echo 📅 Fecha objetivo: %FECHA%
echo =======================================================

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" cli.py interactive-profile --fecha %FECHA% %2 %3 %4 %5
) else (
    python cli.py interactive-profile --fecha %FECHA% %2 %3 %4 %5
)

if exist "output\etapa_%FECHA%.pdf" (
    echo 📄 Informe PDF disponible en: "output\etapa_%FECHA%.pdf"
)

if exist "output\etapa_%FECHA%.html" (
    echo.
    echo 🌐 Abriendo reporte HTML en el navegador...
    start "" "output\etapa_%FECHA%.html"
)

pause
