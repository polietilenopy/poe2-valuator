@echo off
chcp 65001 >nul
REM ============================================================
REM  Crea Poe2Valuator en modo CARPETA (--onedir) y la comprime
REM  en un .zip para compartir. Dispara MENOS alertas de antivirus
REM  que el .exe suelto (--onefile), porque no se descomprime en
REM  un temporal al abrir.
REM
REM  Resultado:
REM    dist\Poe2Valuator\Poe2Valuator.exe   (la app + sus archivos)
REM    Poe2Valuator_compartir.zip           (para repartir a testers)
REM ============================================================
cd /d "%~dp0"
title Crear Poe2Valuator (carpeta + zip)

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
echo [1/4] Instalando herramientas y dependencias...
%PY% -m pip install --upgrade pyinstaller customtkinter pillow

echo.
echo [2/4] Instalando OCR nativo de Windows (winrt)...
%PY% -m pip install winrt-runtime winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Globalization winrt-Windows.Graphics.Imaging winrt-Windows.Media.Ocr winrt-Windows.Storage winrt-Windows.Storage.Streams

echo.
echo [3/4] Compilando en modo carpeta ^(--onedir, --noupx^)...
%PY% -m PyInstaller --noconfirm --onedir --windowed --name Poe2Valuator ^
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

if not exist "dist\Poe2Valuator\Poe2Valuator.exe" (
  echo.
  echo Hubo un problema al compilar. Revisa los mensajes de arriba.
  pause
  exit /b 1
)

echo.
echo [4/4] Comprimiendo en Poe2Valuator_compartir.zip...
if exist "Poe2Valuator_compartir.zip" del "Poe2Valuator_compartir.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Poe2Valuator\*' -DestinationPath 'Poe2Valuator_compartir.zip' -Force"

echo.
echo ============================================================
echo  LISTO!
echo   App:  dist\Poe2Valuator\Poe2Valuator.exe
echo   Para compartir:  Poe2Valuator_compartir.zip
echo.
echo  Diles a tus testers: descomprimir el zip en una carpeta y
echo  abrir Poe2Valuator.exe (no sacar el .exe de la carpeta).
echo ============================================================
explorer "%~dp0"
pause
