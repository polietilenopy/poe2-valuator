# PoE2 Item Valuator — Contexto técnico del proyecto (v0.5)

Documento de traspaso para retomar/modificar el proyecto en otra PC o con otro asistente.
Refleja el estado **actual** tras la evolución desde el MVP 0.1 (sucede a `CONTEXTO_PROYECTO_v0.4.md`).

- **App:** overlay local para Path of Exile 2 que valora ítems por portapapeles y aconseja según tu build.
- **Versión:** `0.5`
- **Liga objetivo:** `Runes of Aldur` (se autodetecta la liga activa).
- **Plataforma:** Windows. **Lenguaje:** Python 3. **UI:** CustomTkinter (con fallback a Tkinter clásico).

---

## 0. Cambios de v0.4 → v0.5 (resumen rápido)

1. **Reward Picker robusto (`rune_reward.py`).** El emparejado de recompensas ya no exige el formato `Nx <Nombre>` ni tolera solo erratas de dígitos:
   - **Cantidad opcional:** `10x Divine Orb`, `1x Aldur's Legacy` o `Aldur's Legacy` a secas (asume 1).
   - **Normalización tolerante a apóstrofes:** `_norm_kn` ahora *elimina* el apóstrofe (no lo cambia por espacio), así `Aldur's Legacy` y un OCR que lo pierde (`Aldurs Legacy`) emparejan igual. **Este era el bug por el que Aldur's Legacy salía "sin precio".**
   - **Matcher en cascada (`_match_catalog_item`):** exacto → nombre del catálogo contenido en el texto → texto contenido en el nombre → difuso (`difflib`). Cotiza por nombre **y cantidad** cualquier tipo: currency, gemas, runas con nombre, sagas, ítems únicos, abyssal bones, fragments, uncut gems, etc. Tolera erratas de OCR (`l`↔`1`, `I`↔`l`, apóstrofes).
   - Líneas con cantidad pero sin precio → `USAR`. Líneas sin cantidad y sin match → se ignoran (evita ruido del OCR).
2. **Miniatura del ítem copiado, también para rares.** Antes el icono solo salía con match directo de poe2scout (uniques/currency/gemas/runas). Ahora:
   - `TradeClient.comparables()` captura el `icon` del primer listing comparable (misma base = mismo arte) y lo expone en el resultado, así los **rares** muestran miniatura.
   - `_fetch_icon(result, item)` tiene fallback: si no hay `IconUrl`, busca por nombre/base en poe2scout.
   - Miniatura más grande: **64×64** (antes 44×44).
3. **Fix detección de arma equipada (`build_to_filter.py`).** `weapon_from_inventory` ya no mira solo la 1ª línea del slot (que en un rare es el *nombre*, p. ej. "Twister"); escanea todo el bloque para leer la **base** ("Hunting Spear"). Evita que el arma realmente equipada se pierda.
4. **Comparativa vs-equipado confirmada para Mobalytics y poe.ninja** (ver §7).

---

## 1. Qué hace hoy

1. Lees un ítem con `Ctrl+C` dentro de PoE2 → el overlay lee el portapapeles y lo parsea, y muestra una **miniatura** del ítem copiado (confirmación visual).
2. Da **precio real en vivo** (Exalted + Divine) para currency, runas, esencias, uniques y gemas (vía poe2scout).
3. Para **rares** da heurística local y, opcionalmente, **comparables reales del trade oficial** (con miniatura del comparable).
4. Si cargas tu **`.build`** (poe.ninja o Mobalytics), dice si el ítem **sirve para tu build** (afinidad por mods) y, si el export trae el equipado, lo **compara contra tu pieza** (MEJOR/SIMILAR/PEOR).
5. Genera un **loot filter `.filter`** de bases acorde a tu build.
6. **Reward Picker (OCR):** lee una captura de un panel de recompensas y cotiza cada fila (VENDER/USAR), con TOP-3 y "⭐ ELEGIR".
7. Guarda historial en `history.jsonl`.

### Principios de seguridad (se mantienen)
- No lee memoria del juego, no inyecta DLLs, no automatiza teclado/mouse, no escanea la pantalla en segundo plano.
- El **OCR es opt-in**: solo corre sobre una imagen que TÚ subes o un área que TÚ seleccionas (botón/atajo). No hay captura automática.
- Red usada: APIs de **poe2scout** (precios) y **trade oficial de PoE2** (comparables), solo cuando corresponde. El trade se consulta **una vez por clic/ítem**, con throttle y manejo de rate limit.

---

## 2. Archivos del proyecto

```text
poe2_item_valuator_mvp/
├─ poe2_valuator_overlay.py   # App principal (parser, mercado, trade, advisor, 2 UIs)
├─ build_to_filter.py         # Perfil de build + generador de loot filter (.filter)
├─ rune_reward.py             # Lector de recompensas por OCR (Reward Picker)
├─ config.json                # Configuración (liga, monedas, trade, build, etc.)
├─ run_windows.bat            # Lanzador (instala customtkinter la 1a vez)
├─ CREAR_EXE.bat / CREAR_EXE_CARPETA.bat / build_exe_windows.ps1 / Poe2Valuator.spec
├─ INSTALAR_OCR.bat           # Instala el OCR (winsdk→winrt fallback)
├─ sample_items.txt           # Ítems de prueba para copiar sin abrir el juego
├─ tests_parser.py            # Smoke test del parser/valuator (offline)
├─ README.md / COMO_EJECUTAR.md
└─ CONTEXTO_PROYECTO_v0.5.md  # Este documento
```

Generados en runtime (junto al script o al `.exe`): `history.jsonl`, `poe2scout_items_cache.json`, y los `.filter` que crees.

---

## 3. Estructura del código `poe2_valuator_overlay.py`

| Componente | Rol |
|---|---|
| `load_config` / `save_config` | Carga/persiste `config.json` (merge con `DEFAULT_CONFIG`). |
| `looks_like_poe_item`, `parse_item_text` | Detecta y parsea el texto del ítem → `ParsedItem` (regex; inglés y parte de español). |
| `infer_category` / `item_slot` | Clasifica y mapea slot: weapon/boots/armour/accessory/jewel/currency/gem/waystone. |
| `ParsedItem` / `ValuationResult` (dataclasses) | Ítem parseado y resultado (precios, confianza, fuente, razones, warnings, campos de build). |
| `MarketClient` | Cliente de **poe2scout**: liga current + divine price + dump de ítems + caché + conversión de monedas. `find_market_item` (match por nombre/base; trae `IconUrl`). |
| `HeuristicValuator` | Decide el precio: mercado (uniques/currency/gem) / comparables (rares con trade) / heurística (rares). Formatea ex+div. |
| `TradeClient` | Trade oficial (search+fetch), min/mediana en exalted, throttle + caché + 429. **Captura `icon` del comparable.** |
| `BuildAdvisor` | Carga el `.build`, deriva perfil (vía `build_to_filter.build_profile`), puntúa afinidad y **compara contra el equipado** (`_parse_equipped` + `compare`). |
| `RuneAdvisorMixin` | Reward Picker (OCR) en ambas UIs. |
| `OverlayApp` / `OverlayAppModern` | UI clásica Tkinter (fallback) / UI moderna CustomTkinter (con miniatura del ítem). |
| `main` | Elige UI moderna si `HAS_CTK`, si no la clásica. |

`BASE_DIR` es consciente de PyInstaller: en modo `.exe` apunta a la carpeta del ejecutable.

---

## 4. Reward Picker — `rune_reward.py` (actualizado v0.5)

Pipeline: `analyze_image()` → OCR → `analyze_text()`.

- **OCR:** motor nativo de Windows vía `winrt`/`winsdk`; fallback a `pytesseract`. `ocr_available()` / `_winrt_modules()` detectan lo instalado.
- **Runas de augment** ("X Rune of Y"): `extract_rune_names()` + `match_rune()` (tier-proxy Archaic→Ancient, verdict `USAR` con precio de referencia).
- **Catálogo completo** (cualquier ítem con precio): `build_full_index()` + `extract_catalog_rewards()` + `_match_catalog_item()`:
  - `_norm_kn(s)` — normaliza **conservando números** y **eliminando apóstrofes** (clave para nombres como `Aldur's Legacy`).
  - `extract_catalog_rewards(text, full_index)` — acepta filas con o sin cantidad (`_REWARD_LINE_RE`, cantidad opcional; `_QTY_TRANS` corrige dígitos OCR). Devuelve `(matched, unmatched)`.
  - `_match_catalog_item(body, full_index, names_sorted)` — cascada exacto/substring/difuso (`difflib`, cutoff 0.84).
- **Salida:** `Analysis` con `RuneResult` (`verdict` VENDER/USAR). Helpers `summary_line()`, `best_to_sell()`, `top_to_sell(n)`, `format_report()`.

**Límites honestos (no son del matcher, son de los datos):** solo cotiza lo que poe2scout tenga **con precio > 0**. En la caché hay categorías sin precio (p. ej. `waystones`, `talismans` = 0) e ítems sueltos en 0.0; saldrán `USAR · sin precio`. El gear **raro con mods aleatorios** no se puede preciar por nombre (cada uno vale distinto). Y hay que tener la **caché fresca** para ver ítems nuevos.

---

## 5. Fuentes de datos (APIs reales verificadas)

### poe2scout (precios) — base `https://poe2scout.com/api`
- `GET /{realm}/Leagues` → ligas; `IsCurrent` (liga activa) y `DivinePrice` (exalted por 1 divine).
- `GET /{realm}/Leagues/{league}/Items` → **dump completo** (~1300 ítems) con `CurrentPrice` (exalted), `Text/Name/Type/ApiId/CategoryApiId` y **`IconUrl`** (usado para la miniatura).
- `MarketClient` cachea el dump en `poe2scout_items_cache.json` (validado por realm+liga, frescura configurable).

### Trade oficial PoE2 — base `https://www.pathofexile.com/api/trade2`
- `POST /search/poe2/{league}` → `{id, result:[hashes]}`; `GET /fetch/{hashes}?query={id}&realm=poe2` → listings con `listing.price.{amount,currency}` **y `item.icon`** (capturado en v0.5 para la miniatura de rares).
- `GET /data/stats` y `/data/filters` para los filtros. **Rate limits** (~12 req/4s): respeta `trade_min_interval_s`, maneja 429 con cooldown.

---

## 6. Valoración (`HeuristicValuator`) + miniatura

Orden de decisión en `value(item)`:
1. **Unique/Currency/Gem** o categoría currency → mercado poe2scout (`_try_market_value`). `raw_market_match` = ítem del mercado (con `IconUrl`).
2. **Rare/Magic** con `auto_trade_comparables` ON y trade disponible → `TradeClient.comparables` (precio real: min + mediana). `raw_market_match` = `{"comparables": comp, "IconUrl": comp["icon"]}`.
3. **Rare/Magic** → heurística local (`_value_weapon` / `_value_rare_defensive_or_accessory`).

**Miniatura (UI moderna):** `_worker_check` llama `_fetch_icon(result, item)` y la pinta con `_set_icon` (64×64). Fuentes del icono, en orden: `IconUrl` del match → `icon` del comparable → fallback `find_market_item`. Para un rare puramente heurístico (sin trade) puede no haber icono; es esperado.

---

## 7. Build advisor + loot filter

### `build_to_filter.py`
- `build_profile(data)` → perfil desde un `.build`: `weapon` (clase de arma), `attrs` (dex/int/str), `defenses`, `themes`.
  - Prioridad de arma: **(a) arma equipada en `inventory_slots`** (`weapon_from_inventory`, v0.5 escanea todo el bloque) → (b) nodos de pasivas → (c) ascendencia (Huntress=Spears, etc.) → (d) nombres de skills (último recurso).
- `generate_filter(profile)` → texto del `.filter` (resalta arma de la build, bases por atributo, rares de slots, currency chase, runas, waystones; atenúa lo off-build).
- CLI: `python build_to_filter.py "mi.build" -o salida.filter`.

### En el overlay — `BuildAdvisor`
- `advise(item)` → afinidad 0–100 (vida, resistencias, MS en botas, spirit, atributo correcto, +gemas, attack speed/crit/elem según `themes`; penaliza spell/cast en build de ataque y arma de otra clase). Veredicto ≥55 SIRVE, 30–55 POSIBLE, <30 NO APORTA.
- `compare(item)` → comparación **vs tu equipado**: mapea el slot, compara contra la pieza más débil de ese slot (útil para 2 anillos), reporta gana/pierde y MEJOR/SIMILAR/PEOR (peso por `_CMP_STATS`).

### Formatos de build soportados (verificado v0.5)
- **Mobalytics:** el export trae `inventory_slots` con `additional_text` (nombre + mods numerados) → **la comparativa vs-equipado funciona** (probado con build real: detecta guantes y 2 anillos, compara un rare copiado y da MEJOR/PEOR con net correcto).
- **poe.ninja:** si el export incluye `inventory_slots`, la comparativa funciona igual (el parseo es agnóstico del origen). Si el `.build` es solo **árbol de pasivas + skills** (sin equipado), `compare()` devuelve `None` de forma segura (no crashea): se muestran **afinidad + filtro**, pero no la comparación pieza a pieza.
- En ambos casos el **perfil** (arma/atributos/temas) y el **filtro** se derivan de pasivas/skills/ascendencia, así que funcionan haya o no equipado.

**Limitación clave (sin cambios):** un loot filter de suelo NO lee mods de rares (solo base/rareza/ilvl). El filtro resalta **bases**; el overlay (Ctrl+C) juzga **mods**. Se complementan.

---

## 8. UI

- **OverlayAppModern** (CustomTkinter): tema PoE2 oscuro dorado. Cabecera arrastrable (pin/compacto/cerrar), hero de precio (ex/div) **con miniatura 64×64 del ítem**, badge de build con color, chips (rápida/justo/ambicioso), toolbar (Leer, Mercado, Trade, Build, Filtro, Runas, Historial) + switch Auto-precio, barra de estado. Modo compacto.
- **OverlayApp** (Tkinter clásico): fallback automático.
- Paleta (constantes `C_*`): `C_BG=#14110b`, `C_PANEL=#1d1810`, `C_GOLD=#d8b25a`, `C_GREEN/_YELLOW/_RED` para el badge.

---

## 9. Ejecutar / distribuir

- **Desarrollo:** `run_windows.bat` o `python poe2_valuator_overlay.py`. **Test parser:** `python tests_parser.py`.
- **OCR:** `INSTALAR_OCR.bat` (winsdk→winrt). El Reward Picker funciona sin Tesseract.
- **.exe repartible:** `CREAR_EXE.bat` / `build_exe_windows.ps1` → `dist\Poe2Valuator.exe` autocontenido. Compilar **en Windows** (PyInstaller no cross-compila desde Linux). Incluir `rune_reward.py`, Pillow y `winrt`.

---

## 10. Ideas / próximos pasos

- Avisar en el reporte de recompensas cuando una categoría no cotiza en el mercado (distinguir de fallo de lectura).
- Refresco automático y visible de la caché de poe2scout (para no perder ítems nuevos).
- Recordar modo compacto y posición de ventana entre sesiones.
- Mejorar comparables de armas (crit, attack speed, +gemas) y jewels.
- Afinidad de uniques por nombre (mapear uniques meta a la build).
- Instalador firmado (menos avisos de SmartScreen/antivirus).

---

## 11. Notas de mantenimiento

- Si poe2scout cambia endpoint/formato: ver `MarketClient.ensure_loaded` y `_build_index`.
- Si el trade cambia query/IDs de stats: ver `build_trade2_query` y `_STAT_TO_TRADE2` (regenerar desde `/api/trade2/data/stats`).
- Reward Picker: ampliar el catálogo es automático (usa el dump de poe2scout). Para nuevos tipos de fila, ajustar `_REWARD_LINE_RE` / `_match_catalog_item` en `rune_reward.py`.
- El parser de ítems es regex-based (`parse_item_text`); ampliar patrones de mods ahí.
- Editar `poe2_valuator_overlay.py` con cuidado (archivo grande): valida con `python -m py_compile` tras cada cambio.
