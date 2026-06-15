@echo off
cd /d "%~dp0"
title PoE2 Item Valuator
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

REM Instala customtkinter (UI moderna) si falta. Si no hay internet, la app usa la UI clasica.
%PY% -c "import customtkinter" >nul 2>nul
if errorlevel 1 (
  echo Instalando dependencia de la interfaz moderna ^(customtkinter^)...
  %PY% -m pip install customtkinter >nul 2>nul
)

REM Pillow: necesario para leer imagenes y capturar pantalla (lector de runas).
%PY% -c "import PIL" >nul 2>nul
if errorlevel 1 (
  echo Instalando Pillow ^(lector de imagenes^)...
  %PY% -m pip install pillow >nul 2>nul
)

REM OCR nativo de Windows para leer las recompensas de runa (sin Tesseract).
REM Acepta winsdk (Python <=3.11) o winrt (Python 3.12/3.13).
%PY% -c "import winsdk.windows.media.ocr" >nul 2>nul
if errorlevel 1 (
  %PY% -c "import winrt.windows.media.ocr" >nul 2>nul
  if errorlevel 1 (
    echo Instalando motor OCR de Windows ^(winsdk^)...
    %PY% -m pip install winsdk >nul 2>nul
    %PY% -c "import winsdk.windows.media.ocr" >nul 2>nul
    if errorlevel 1 (
      echo.
      echo  [AVISO] No pude instalar el OCR automaticamente con tu version de Python.
      echo  Para activar el lector de runas, cierra esto y ejecuta:  INSTALAR_OCR.bat
      echo.
    )
  )
)

%PY% poe2_valuator_overlay.py
if errorlevel 1 (
  echo.
  echo Hubo un error al ejecutar la app. Revisa que Python 3 este instalado.
  pause
)
