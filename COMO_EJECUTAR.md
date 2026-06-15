# Cómo ejecutar / compilar / compartir

Tienes dos formas. La **A** es la más fácil para una PC sin nada instalado.

---

## Opción A — Crear un .exe (recomendada, no necesita Python en la otra PC)

En **tu** PC (donde ya funciona), una sola vez:

1. Doble clic a **`CREAR_EXE.bat`** (lo más fácil). Instala lo necesario y compila solo.
   - Alternativa PowerShell: `powershell -ExecutionPolicy Bypass -File .\build_exe_windows.ps1`
2. Espera 1-3 minutos. Se crea **`dist\Poe2Valuator.exe`** (trae Python + todo adentro,
   incluido el OCR `winrt`, Pillow y `rune_reward.py`).
3. Ese `.exe` corre en **cualquier Windows** (con el paquete de idioma Inglés para el OCR).

### Para repartir a testers (menos alertas de antivirus): `CREAR_EXE_CARPETA.bat`
- Compila en **modo carpeta** (`--onedir`, sin UPX) y genera **`Poe2Valuator_compartir.zip`**.
- Dispara bastantes menos falsos positivos que el `.exe` suelto.
- Instrucción para el tester: descomprimir el zip y abrir `Poe2Valuator.exe` **sin sacarlo
  de la carpeta**.

> Importante: cada vez que cambie el código, **hay que recompilar** para que el `.exe` tenga
> lo último. `run_windows.bat` siempre usa el código actual sin recompilar.

---

## Opción B — Copiar la carpeta y usar Python

En la otra PC:

1. Instala **Python 3** desde https://www.python.org/downloads/
   (marca **"Add Python to PATH"** durante la instalación).
2. Copia toda la carpeta `poe2_item_valuator_mvp`.
3. Doble clic a **`run_windows.bat`**.
   - La primera vez instala `customtkinter`, `pillow` y el OCR (`winsdk`/`winrt`) si faltan.
   - Si el OCR no quedó instalado (p. ej. Python 3.14 no soporta `winsdk`), ejecuta
     **`INSTALAR_OCR.bat`**: prueba `winsdk` y, si no, instala `winrt`.

---

## Qué archivos hacen falta (Opción B)

Imprescindibles:
- `poe2_valuator_overlay.py`  (la app)
- `rune_reward.py`            (lector de recompensas de runa por OCR)
- `build_to_filter.py`        (advisor de build + generador de filtro)
- `run_windows.bat`           (lanzador)

Útiles para compilar/instalar:
- `CREAR_EXE.bat`, `CREAR_EXE_CARPETA.bat`, `build_exe_windows.ps1`, `Poe2Valuator.spec`
- `version_info.txt`          (metadatos del .exe; reduce falsos positivos)
- `INSTALAR_OCR.bat`          (instala el OCR nativo de Windows)

Opcionales:
- `config.json` (se crea solo), `sample_items.txt`, `README.md`

Se generan solos al usar la app: `config.json`, `history.jsonl`,
`poe2scout_items_cache.json`, y los `.filter` que crees.

---

## OCR (lector de recompensas de runa)

- Usa el **motor OCR nativo de Windows** vía pip: `winsdk` (Python ≤ 3.11) o `winrt`
  (Python 3.12/3.13/3.14). No requiere Tesseract.
- Necesita el **paquete de idioma Inglés** en Windows
  (Configuración → Hora e idioma → Idioma → Funciones de idioma).
- Si el lector dice "OCR no disponible", corre `INSTALAR_OCR.bat`.

---

## Requisitos comunes

- **Windows** (overlay + atajos + OCR nativo). El precio en vivo necesita **internet**.
- En PoE2 usa **Windowed** o **Borderless Windowed** para ver el overlay encima.
- Pon tu liga en `config.json` o deja `auto_detect_league: true`.

## Antivirus / SmartScreen marca el .exe
Es un **falso positivo** típico de PyInstaller (ejecutable nuevo, sin firmar). Mitigaciones
ya aplicadas en el build: **sin UPX** y con **metadatos de producto** (`version_info.txt`).
Además:
- Reparte el **zip** de `CREAR_EXE_CARPETA.bat` (modo carpeta = menos alertas).
- Subir el `.exe` a **VirusTotal** y compartir el enlace da confianza.
- Reportarlo a Microsoft como falso positivo lo limpia con el tiempo.
- En SmartScreen: **Más información → Ejecutar de todas formas**.
- Lo único que **elimina** el aviso del todo es un **certificado de firma de código**
  (de pago; el EV da confianza casi instantánea).

## Si el .exe no abre
- Permite el archivo en el antivirus (falso positivo).
- Para ver el error, compila con consola quitando `--windowed` del script de build.
