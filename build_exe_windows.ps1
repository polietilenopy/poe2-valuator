# Crea un .exe independiente con PyInstaller (no requiere Python en la otra PC).
#   powershell -ExecutionPolicy Bypass -File .\build_exe_windows.ps1

py -3 -m pip install --upgrade pyinstaller customtkinter pillow
py -3 -m pip install winrt-runtime winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Globalization winrt-Windows.Graphics.Imaging winrt-Windows.Media.Ocr winrt-Windows.Storage winrt-Windows.Storage.Streams

py -3 -m PyInstaller --noconfirm --onefile --windowed --name Poe2Valuator `
  --noupx `
  --version-file version_info.txt `
  --collect-all customtkinter `
  --collect-all winrt `
  --collect-submodules winrt `
  --hidden-import build_to_filter `
  --hidden-import rune_reward `
  --hidden-import PIL.ImageGrab `
  --hidden-import PIL.ImageTk `
  --hidden-import winrt.runtime `
  --hidden-import winrt.windows.media.ocr `
  --hidden-import winrt.windows.globalization `
  --hidden-import winrt.windows.graphics.imaging `
  --hidden-import winrt.windows.storage.streams `
  --hidden-import winrt.windows.foundation `
  --hidden-import winrt.windows.foundation.collections `
  --hidden-import winrt.windows.storage `
  --add-data "build_to_filter.py;." `
  --add-data "rune_reward.py;." `
  poe2_valuator_overlay.py

Write-Host ""
Write-Host "EXE creado en .\dist\Poe2Valuator.exe"
