@echo off
chcp 65001 >nul
REM ============================================================
REM  Crea Poe2Valuator.exe (autocontenido) con doble clic.
REM  Incluye: precios poe2scout, lector de runas (OCR winrt),
REM  captura de area y ventana de recompensas.
REM ============================================================
cd /d "%~dp0"
title Crear Poe2Valuator.exe

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

%PY% --version >nul 2>nul
if errorlevel 1 (
  echo No encontre Python 3. Instalalo desde https://www.python.org/downloads/
  echo  ^(marca "Add Python to PATH"^) y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)

echo.
echo [1/3] Instalando herramientas y dependencias...
%PY% -m pip install --upgrade pyinstaller customtkinter pillow

echo.
echo [2/3] Instalando OCR nativo de Windows (winrt)...
%PY% -m pip install winrt-runtime winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Globalization winrt-Windows.Graphics.Imaging winrt-Windows.Media.Ocr winrt-Windows.Storage winrt-Windows.Storage.Streams

echo.
echo [3/3] Compilando el .exe ^(puede tardar 1-3 minutos^)...
%PY% -m PyInstaller --noconfirm --onefile --windowed --name Poe2Valuator ^
  --noupx ^
  --version-file version_info.txt ^
  --collect-all customtkinter ^
  --collect-all winrt ^
  --collect-submodules winrt ^
  --hidden-import build_to_filter ^
  --hidden-import rune_reward ^
  --hidden-import PIL.ImageGrab ^
  --hidden-import PIL.ImageTk ^
  --hidden-import winrt.runtime ^
  --hidden-import winrt.windows.media.ocr ^
  --hidden-import winrt.windows.globalization ^
  --hidden-import winrt.windows.graphics.imaging ^
  --hidden-import winrt.windows.storage.streams ^
  --hidden-import winrt.windows.foundation ^
  --hidden-import winrt.windows.foundation.collections ^
  --hidden-import winrt.windows.storage ^
  --add-data "build_to_filter.py;." ^
  --add-data "rune_reward.py;." ^
  poe2_valuator_overlay.py

echo.
if exist "dist\Poe2Valuator.exe" (
  echo ============================================================
  echo  LISTO!  Tu ejecutable esta en:  dist\Poe2Valuator.exe
  echo ============================================================
  explorer dist
) else (
  echo Hubo un problema al compilar. Revisa los mensajes de arriba.
)
pause
