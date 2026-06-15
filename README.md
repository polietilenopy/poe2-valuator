# PoE2 Item Valuator — v0.5  ·  by Polietileno

Overlay local y seguro para valorar ítems de Path of Exile 2 por portapapeles, con
**precios reales en vivo** de la liga actual.

Liga por defecto: **Runes of Aldur** (se autodetecta la liga `IsCurrent`).


## ⬇️ Descargar y probar (jugadores — sin instalar nada)

1. Entra a la pestaña **Releases** (columna derecha de esta página de GitHub).
2. Descarga **`Poe2Valuator.exe`** de la última versión.
3. Doble clic para abrirlo. No instala nada en tu sistema; podés borrarlo cuando quieras.
4. En PoE2 jugá en modo **Windowed** o **Borderless Windowed**.
5. Pasá el mouse sobre un ítem y pulsá **Ctrl+C**: el overlay te muestra el precio al instante.

¿No querés el .exe? También podés correrlo desde el código (ver *"Cómo probarlo ingame"* más abajo).


## 🛡️ ¿Es seguro? ¿Por qué Windows o el antivirus me avisan?

**Es un falso positivo, no un virus.** Al abrirlo puede que veas *"Windows protegió tu PC"* (SmartScreen) o que tu antivirus lo marque. Pasa con **casi todos** los programas hechos con **PyInstaller** (empaqueta Python + librerías dentro de un solo `.exe`, y los antivirus desconfían de ese empaquetado, no del contenido). El ejecutable **no está firmado** con un certificado de pago, por eso Windows no lo reconoce todavía.

Para abrirlo igual: en el aviso de SmartScreen hacé clic en **"Más información" → "Ejecutar de todas formas"**.

**Por qué podés confiar (y verificarlo vos mismo):**

- **El código es 100% abierto** y está en este repo: podés leer exactamente qué hace.
- **Qué hace:** solo lee el **portapapeles** (lo que copiás con Ctrl+C) y consulta dos APIs públicas para los precios: **poe2scout** y el **trade oficial de PoE2**.
- **Qué NO hace:** no lee la memoria del juego, no inyecta DLLs, no automatiza teclado ni mouse, no escanea tu pantalla en segundo plano y no toca tu cuenta ni tus contraseñas.
- **Si seguís con dudas:** podés **compilar tu propio .exe** desde el código con `CREAR_EXE.bat`, o subir el `.exe` a [VirusTotal](https://www.virustotal.com) para analizarlo. Los falsos positivos de PyInstaller son conocidos y documentados.

> Nota: solo trabaja sobre el texto del portapapeles; no interactúa con el cliente del juego (sin lectura de memoria, inyección ni automatización), que es el enfoque que usan las herramientas de este tipo.


## Interfaz (v0.3)
UI moderna con **CustomTkinter**, tema **PoE2 oscuro dorado**:
- Cabecera arrastrable con **pin** (siempre encima), **compacto/expandido** y cerrar.
- Hero con nombre del ítem, **precio grande** (ex/div) y chips de venta rápida/justo/ambicioso.
- **Badge de build** con color: verde = sirve, amarillo = posible, rojo = vender.
- Barra de herramientas: Leer, Mercado, Trade, Build, Filtro, Historial + switch Auto-precio.
- Barra de estado con liga, tasa div↔ex y build cargada.
- **Modo compacto**: solo precio + veredicto, para no tapar el juego.

Si `customtkinter` no está instalado, la app usa automáticamente la UI clásica.
`run_windows.bat` instala la dependencia la primera vez.

## Novedades v0.5 — Lector de recompensas de runa (Reward Picker)
Nuevo asesor que **lee una captura del panel de recompensas** (p. ej. "Runeshape
Combinations" / Ezomyte Remnant) y te dice **cuál fila conviene elegir** según el
precio real de mercado (poe2scout).

Cómo se usa (dos botones nuevos en la barra):
- **🪙 Runas: ¿cuál vender? (imagen)** — eliges/subes un archivo de imagen.
- **✂ Capturar área (F8)** — oscurece la pantalla, arrastras un rectángulo sobre el
  panel y analiza solo esa zona. (F8 funciona con el overlay enfocado.)

Qué muestra la ventana de resultados (estilo "reward picker"):
- **Miniatura** de la captura (clic para volver a capturar).
- **Resumen**: "Leí N recompensas — X para vender — Y para usar/craftear".
- Banner **⭐ ELEGIR esta fila** + **TOP 3** con el precio de cada una.
- **Tarjetas con veredicto**: `VENDER` (dorado, con precio) vs `USAR` (azul, craft/sin
  venta directa), con la **cuenta por cantidad** explícita (p. ej. `10 × 123.51 ex = 1235 ex`).

Detalles técnicos del lector:
- **OCR nativo de Windows** vía el paquete pip `winrt` (o `winsdk`). No necesita Tesseract.
  Si falta, `INSTALAR_OCR.bat` lo instala (prueba winsdk y, si tu Python no lo soporta —
  p. ej. 3.14 — instala `winrt`). Requiere el **paquete de idioma Inglés** de Windows.
- Empareja cada fila `Nx <Nombre>` contra **todo el catálogo** de poe2scout (currency,
  gemas, runas con nombre propio como *Aldur's Legacy*, sagas, crests, etc.).
- Tolera erratas de OCR (incluida la cantidad: lee `1OX` como `10x`).
- Captura **consciente del DPI** (escala 125%/150%): recorta el área correcta.
- Runas de augment "Archaic Rune of X": muestra precio del tier rastreado (Ancient) como
  **referencia** y las marca "no se vende directo · usar/craftear".
- Implementado en `rune_reward.py` (módulo independiente, sin GUI, testeable aparte).

## Confirmación visual del ítem copiado (v0.5)
Al copiar con Ctrl+C, la UI moderna limpia el panel al instante (no ves el resultado
viejo), muestra **el nombre + la hora de copiado** y el **icono real del ítem** (desde
poe2scout) cuando existe (uniques, currency, runas, gemas, bases).

## Novedades v0.2
- Mercado en vivo vía la API real de **poe2scout** (`poe2scout.com/api`): currency,
  runes, essences, uniques y gems con su precio actual de mercado.
- Precios mostrados **en Exalted y Divine a la vez**, con la tasa div↔ex en vivo.
- Autodetección de la liga activa + caché fresco (20 min) y botón **↻ Mercado**.
- Botón **Trade oficial**:
  - En **rares/magic**: arma automáticamente una búsqueda de **comparables por stats**
    (vida total, resistencias, movement speed, spirit, atributos, % phys, etc.) y abre el
    trade oficial **ya pre-cargado** con listings reales. Tú solo revisas/ajustas. Una sola
    llamada por clic (sin polling, respeta los límites de la API).
  - En **uniques/currency**: abre el buscador de tu liga y copia el nombre para pegarlo.
- Botón **Auto-precio: ON/OFF** (apagado por defecto): si lo activas, al leer un **rare**
  el overlay consulta el trade oficial y trae el **precio real** (mínimo y mediana de
  listings, convertidos a exalted) sin abrir el navegador. Throttle + caché + manejo de
  rate limit (429) para no bloquearte. Si lo dejas apagado, los rares usan heurística local.
- Historial enriquecido (precio en ex, match de mercado, divine) para calibrar después.

## Qué hace
- Lee el texto de un ítem copiado con `Ctrl+C` dentro del juego (solo portapapeles).
- Parsea rareza, nombre, base, ilvl, vida, resistencias, movement speed, spirit,
  atributos, rarity, DPS básico de armas y mods premium.
- Da precios orientativos: venta rápida, precio justo y precio ambicioso.
- Para uniques/currency/gems: precio real de mercado (poe2scout).
- Para rares: heurística local + botón para ver comparables reales en el trade oficial.

## Qué NO hace
- No lee memoria del juego. No inyecta nada. No escanea pantalla.
- No automatiza clicks ni teclas. No lista ítems automáticamente.
- No hace polling del trade: solo una consulta cuando tú pulsas el botón.

## Cómo probarlo ingame
1. Instala Python 3 en Windows.
2. Ejecuta `run_windows.bat`.
3. En PoE2 usa `Windowed` o `Borderless Windowed`.
4. Hover sobre un ítem y pulsa `Ctrl+C`. El overlay se actualiza solo.
5. Pulsa **Trade oficial** para ver el precio real / comparables.

## Probar sin abrir el juego
Abre `sample_items.txt`, copia un bloque completo y pulsa **Leer portapapeles**.

## Configuración (`config.json`)
- `league`: liga; con `auto_detect_league: true` se usa la liga activa.
- `enable_market_lookup`: `false` para modo 100% offline.
- `show_both_currencies`: muestra ex + div.
- `market_cache_minutes`: frescura de la caché de precios.
- `build_file`: ruta a tu `.build` para el advisor de build (o usa el botón).
- `auto_trade_comparables`: `true`/`false` para el modo Auto-precio (también con el botón).
- `trade_min_interval_s`: segundos mínimos entre consultas al trade (rate limit).
- `user_agent`: pon tu contacto si vas a usar la API con frecuencia.




## Calidad de rolls (¿es lo mejor de lo mejor?) (v0.4)
Al leer un ítem, el overlay muestra **cada mod vs su tope** y un **% de calidad**
(p. ej. `vida 116/90 (100% casi perfecto); MS 30/35 (86% alto)`) más una **calidad media**.
Así sabes no solo si te sirve, sino qué tan cerca está del **roll perfecto**.
Los topes están en una tabla editable (`MAX_ROLLS`, `PERSLOT_LIFE`, `PERSLOT_ES`) dentro de
`poe2_valuator_overlay.py` — afinables con referencias como pathofcrafting.net y
craftofexile.com (modo PoE2).

## Comparar con tu equipado (v0.4)
Si tu `.build` incluye el gear equipado (exports de **mobalytics.gg** traen
`inventory_slots`), al leer un ítem el overlay te dice **MEJOR / SIMILAR / PEOR**
que el que ya tienes en ese slot, con lo que **gana** y lo que **pierde**
(p. ej. "vs tu botas: MEJOR · gana +116 vida, +86 resist. · pierde -21 ES").
Para anillos compara contra el más débil (el que reemplazarías).
Funciona con cualquier clase: detecta el arma por el gear equipado, las pasivas
y la ascendencia (Huntress/Monk/Warrior/Mercenary/Witch...), no por las gemas.

## Combinar con tu build (advisor)
- Botón **Cargar build**: selecciona tu `.build` (el diálogo abre por defecto en la
  carpeta de PoE2 / Path of Building / Descargas). Se **recuerda** para la próxima vez.
- Botón **Generar filtro**: crea el `.filter` directamente desde la build cargada.
- A partir de ahí, al leer un item el overlay te dice **si sirve para tu build**
  (afinidad 0-100 por mods: arma de tu clase, vida, resistencias, MS, atributos,
  crit/ataque/elemental según tus pasivas) y una **recomendación**: quédatelo,
  compáralo, o **véndelo** (con el precio de venta rápida).
- Genera además un loot filter de bases con `build_to_filter.py` (resalta en el
  suelo las bases acordes a la build). Filtro = bases; overlay = mods + precio.

## Fuentes de precio
- Currency/uniques/gems: `https://poe2scout.com/api` (liga current, CurrentPrice en exalted).
- Comparables de rares: API del trade oficial `pathofexile.com/api/trade2`.
