@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalar OCR para el lector de runas

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

echo ============================================================
echo  Diagnostico de Python
echo ============================================================
%PY% --version
%PY% -c "import sys;print('Ejecutable:',sys.executable)"
echo.

echo [1/4] Actualizando pip...
%PY% -m pip install --upgrade pip

echo.
echo [2/4] Instalando Pillow (lector de imagenes)...
%PY% -m pip install pillow

echo.
echo [3/4] Intentando winsdk (OCR nativo, opcion simple)...
%PY% -m pip install winsdk
%PY% -c "import winsdk.windows.media.ocr; print('OK winsdk')" 2>nul
if %errorlevel%==0 (
  echo.
  echo  ====================================================
  echo   LISTO: OCR instalado via winsdk. Abre run_windows.bat
  echo  ====================================================
  pause
  exit /b 0
)

echo.
echo  winsdk no funciono con tu Python. Probando el paquete moderno winrt...
echo.
echo [4/4] Instalando winrt (OCR nativo, soporta Python 3.12/3.13)...
%PY% -m pip install winrt-runtime winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Globalization winrt-Windows.Graphics.Imaging winrt-Windows.Media.Ocr winrt-Windows.Storage winrt-Windows.Storage.Streams
%PY% -c "import winrt.windows.media.ocr; print('OK winrt')" 2>nul
if %errorlevel%==0 (
  echo.
  echo  ====================================================
  echo   LISTO: OCR instalado via winrt. Abre run_windows.bat
  echo  ====================================================
) else (
  echo.
  echo  No se pudo instalar el OCR nativo automaticamente.
  echo  Copia los mensajes de error de arriba y mandalos para ayudarte.
  echo  (Alternativa: instalar Tesseract y luego  %PY% -m pip install pytesseract)
)
pause
