"""
rune_reward.py — Asesor de recompensas de runas para PoE2 Valuator
------------------------------------------------------------------

Lee una captura (archivo de imagen o captura de pantalla) de un panel de
recompensas de runas (p. ej. "Runeshape Combinations") y dice cual conviene
mas segun su valor de mercado real (poe2scout, liga actual).

Pipeline: imagen -> OCR (motor nativo de Windows, sin binarios extra) ->
nombres de runa -> emparejado difuso contra el mercado -> precio ex/div ->
ranking (la mas cara primero = la mejor para vender).

Notas:
  * OCR sin instalar Tesseract: usa Windows.Media.Ocr via el paquete pip
    `winsdk` (se autoinstala como customtkinter). Si no esta, intenta
    `pytesseract`; si tampoco, devuelve un error claro.
  * Tiers: en el juego estas runas aparecen como "Archaic Rune of X"; el
    mercado (poe2scout) rastrea el tier "Ancient Rune of X" de la misma
    familia. Emparejamos por la familia y avisamos cuando el precio es el
    del tier rastreado (aproximado).

Este modulo NO depende de la GUI: se puede importar y probar por separado.
"""
from __future__ import annotations

import difflib
import io
import re
from dataclasses import dataclass, field
from typing import Optional


# Delata que una linea OCR contiene la palabra "rune" (tolera erratas OCR).
_RUNE_HINT = re.compile(r"r[uv]n[ce]", re.IGNORECASE)

# "(Cualquier prefijo) Rune of (modificador)" -> captura el modificador.
_RUNE_OF_RE = re.compile(r"r[uv]n[ce]\s+of\s+(.+)$", re.IGNORECASE)

# Nombre de runa valido:
#   (a) "<algo> Rune of <modificador>"  (augment: Archaic/Ancient...)
#   (b) "Rune of <modificador>"         (por si el OCR pierde el tier)
#   (c) "<adjetivo> Rune"               (engastables: Perfect Ward Rune)
# Descarta texto de tooltip como "Rune Limited to: 1".
_RUNE_NAME_RE = re.compile(
    r"(r[uv]n[ce]\s+of\s+[A-Za-z' ]+"
    r"|[A-Za-z'][A-Za-z' ]*?r[uv]n[ce]\s+of\s+[A-Za-z' ]+"
    r"|[A-Za-z'][A-Za-z' ]*?\br[uv]n[ce]\b)",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("0", "o").replace("|", "l")
    s = re.sub(r"[^a-z ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _modifier_key(name: str) -> Optional[str]:
    m = _RUNE_OF_RE.search(name or "")
    if not m:
        return None
    return _norm(m.group(1))


def _looks_like_rune_name(cand: str) -> bool:
    cl = _norm(cand)
    if re.search(r"r[uv]n[ce]\s+of\s+[a-z]", cl):
        return True
    if re.search(r"[a-z]\s+r[uv]n[ce]\b", cl):
        return True
    return False


@dataclass
class RuneResult:
    detected_text: str
    matched_name: str
    price_ex: float
    price_div: float
    tier_note: str = ""
    confidence: str = "alta"
    found: bool = True
    verdict: str = "VENDER"   # VENDER (se vende) | USAR (craft/usar, sin venta directa)

    @property
    def price_text(self) -> str:
        if not self.found:
            return "sin precio"
        if self.price_div >= 0.1:
            return f"{self.price_ex:.2f} ex  (~{self.price_div:.2f} div)"
        return f"{self.price_ex:.2f} ex"


@dataclass
class Analysis:
    results: list = field(default_factory=list)
    league: str = ""
    divine_price: float = 0.0
    ocr_text: str = ""
    error: str = ""

    @property
    def best(self) -> Optional[RuneResult]:
        priced = [r for r in self.results if r.found]
        if not priced:
            return None
        return max(priced, key=lambda r: r.price_ex)


def build_rune_index(market_items: list) -> dict:
    names: list = []
    by_norm: dict = {}
    by_mod: dict = {}
    for it in market_items or []:
        cat = str(it.get("CategoryApiId") or "")
        text = it.get("Text") or it.get("Name") or ""
        if not text:
            continue
        is_rune = (cat == "runes") or _RUNE_HINT.search(text)
        if not is_rune:
            continue
        names.append(text)
        by_norm[_norm(text)] = it
        mod = _modifier_key(text)
        if mod:
            prev = by_mod.get(mod)
            if prev is None or float(it.get("CurrentPrice") or 0) > float(prev.get("CurrentPrice") or 0):
                by_mod[mod] = it
    return {"names": names, "by_norm": by_norm, "by_mod": by_mod}


def match_rune(detected: str, index: dict) -> tuple:
    norm = _norm(detected)
    if not norm:
        return None, "", "baja"
    if norm in index["by_norm"]:
        return index["by_norm"][norm], "", "alta"
    mod = _modifier_key(detected)
    if mod and mod in index["by_mod"]:
        item = index["by_mod"][mod]
        note = ""
        det_tier = norm.split(" rune of")[0].strip()
        off_name = (item.get("Text") or "").lower()
        off_tier = off_name.split(" rune of")[0].strip()
        if det_tier and off_tier and det_tier != off_tier:
            note = f"precio del tier rastreado «{item.get('Text')}» (aprox. para «{detected}»)"
        return item, note, "media" if note else "alta"
    cand = difflib.get_close_matches(norm, [_norm(n) for n in index["names"]], n=1, cutoff=0.72)
    if cand:
        item = index["by_norm"].get(cand[0])
        if item:
            return item, f"emparejado por similitud a «{item.get('Text')}»", "media"
    if mod and index["by_mod"]:
        cand = difflib.get_close_matches(mod, list(index["by_mod"].keys()), n=1, cutoff=0.7)
        if cand:
            item = index["by_mod"][cand[0]]
            return item, f"precio del tier rastreado «{item.get('Text')}» (aprox.)", "baja"
    return None, "", "baja"


def extract_rune_names(ocr_text: str) -> list:
    out: list = []
    seen = set()
    for raw in (ocr_text or "").splitlines():
        line = raw.strip(" \t•·-—|")
        if not line or not _RUNE_HINT.search(line):
            continue
        line = re.sub(r"^\s*\d+\s*[xX]\s*", "", line).strip()
        m = _RUNE_NAME_RE.search(line)
        if not m:
            continue
        cand = m.group(1).strip()
        if not _looks_like_rune_name(cand):
            continue
        key = _norm(cand)
        if key and key not in seen and len(key) >= 4:
            seen.add(key)
            out.append(cand)
    return out


def _winrt_modules():
    """Devuelve los modulos OCR de winsdk o winrt (lo que este instalado)."""
    import importlib
    for top in ("winsdk", "winrt"):
        try:
            return (
                importlib.import_module(top + ".windows.media.ocr"),
                importlib.import_module(top + ".windows.globalization"),
                importlib.import_module(top + ".windows.graphics.imaging"),
                importlib.import_module(top + ".windows.storage.streams"),
            )
        except Exception:
            continue
    return None


def ocr_available() -> tuple:
    if _winrt_modules() is not None:
        return True, "OCR nativo de Windows"
    try:
        import pytesseract  # noqa: F401
        return True, "pytesseract (Tesseract)"
    except Exception:
        pass
    return False, "ninguno"


def _ocr_winrt(pil_image) -> str:
    import asyncio
    mods = _winrt_modules()
    if mods is None:
        raise RuntimeError("winsdk/winrt no disponible")
    ocr_mod, glob_mod, imaging_mod, streams_mod = mods
    OcrEngine = ocr_mod.OcrEngine
    Language = glob_mod.Language
    BitmapDecoder = imaging_mod.BitmapDecoder
    InMemoryRandomAccessStream = streams_mod.InMemoryRandomAccessStream
    DataWriter = streams_mod.DataWriter

    buf = io.BytesIO()
    pil_image.convert("RGB").save(buf, format="PNG")
    data = buf.getvalue()

    async def run() -> str:
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        try:
            writer.write_bytes(data)          # winrt espera bytes
        except TypeError:
            writer.write_bytes(list(data))    # winsdk antiguo espera lista de ints
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            try:
                engine = OcrEngine.try_create_from_language(Language("en-US"))
            except Exception:
                engine = None
        if engine is None:
            raise RuntimeError(
                "No hay paquete de idioma OCR en Windows. Anade Ingles en "
                "Configuracion > Hora e idioma > Idioma > Funciones de idioma."
            )
        result = await engine.recognize_async(bitmap)
        lines = [" ".join(w.text for w in ln.words) for ln in result.lines]
        return "\n".join(lines) if lines else (result.text or "")

    return asyncio.run(run())


def _ocr_tesseract(pil_image) -> str:
    import pytesseract
    return pytesseract.image_to_string(pil_image)


def ocr_pil_image(pil_image) -> str:
    if _winrt_modules() is not None:
        return _ocr_winrt(pil_image)
    return _ocr_tesseract(pil_image)


def load_image(path: str):
    from PIL import Image
    return Image.open(path)


def capture_screen():
    from PIL import ImageGrab
    return ImageGrab.grab()


def capture_region(bbox):
    """Captura solo el area (x1, y1, x2, y2) en coordenadas de pantalla."""
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=bbox)


def _price_of(item: dict, divine_price: float) -> tuple:
    ex = float(item.get("CurrentPrice") or 0.0)
    div = (ex / divine_price) if divine_price else 0.0
    return ex, div


def analyze_market(detected_names: list, market) -> Analysis:
    try:
        market.ensure_loaded()
    except Exception:
        pass
    items = getattr(market, "_items", None) or []
    divine = float(getattr(market, "divine_price", 0.0) or 0.0)
    league = str(getattr(market, "resolved_league", "") or "")
    index = build_rune_index(items)
    results: list = []
    for name in detected_names:
        item, note, conf = match_rune(name, index)
        if item is None:
            results.append(RuneResult(name, name, 0.0, 0.0, "no encontrada en el mercado",
                                      "baja", found=False))
            continue
        ex, div = _price_of(item, divine)
        results.append(RuneResult(
            detected_text=name,
            matched_name=str(item.get("Text") or item.get("Name") or name),
            price_ex=ex, price_div=div, tier_note=note, confidence=conf, found=True,
        ))
    results.sort(key=lambda r: (r.found, r.price_ex), reverse=True)
    return Analysis(results=results, league=league, divine_price=divine)


def _norm_kn(s: str) -> str:
    """Normaliza pero CONSERVA numeros (para distinguir 'Skill Gem (Level 5)' de '(Level 20)').

    Importante: ELIMINA apostrofes (no los convierte en espacio) para que
    "Aldur's Legacy" y un OCR que pierde el apostrofe ("Aldurs Legacy")
    normalicen ambos a "aldurs legacy" y emparejen igual.
    """
    s = (s or "").lower()
    s = s.replace("'", "").replace("’", "").replace("`", "").replace("´", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Linea de recompensa: "<cantidad>x <Nombre>"  (p. ej. "10x Divine Orb", "1x Aldur's Legacy")
_QTY_LINE_RE = re.compile(r"^\s*(\d+)\s*[xX\u00d7]?\s*(.+?)\s*$")


def build_full_index(market_items: list) -> dict:
    """Indice de TODOS los items del mercado por nombre (conserva numeros).

    Asi podemos preciar cualquier recompensa: currency, gemas, runas con nombre
    propio (Aldur's Legacy), sagas, crests, etc. Guarda el de mayor precio por nombre.
    """
    idx: dict = {}
    for it in market_items or []:
        price = float(it.get("CurrentPrice") or 0)
        for nm in (it.get("Text"), it.get("Name")):
            kn = _norm_kn(nm or "")
            if len(kn) >= 6:
                prev = idx.get(kn)
                if prev is None or price > float(prev.get("CurrentPrice") or 0):
                    idx[kn] = it
    return idx


_QTY_TRANS = str.maketrans("OolIiZzSsBb", "00111225586")  # errores OCR de digitos
# Cantidad OPCIONAL: "10x Nombre", "1 Nombre" o simplemente "Nombre".
_REWARD_LINE_RE = re.compile(r"^\s*(?:([0-9OolIiZzSsBb]+)\s*[xX\u00d7]?\s+)?(.+?)\s*$")


def _match_catalog_item(body: str, full_index: dict, names_sorted: Optional[list] = None):
    """Empareja un texto de recompensa con un item del mercado (con precio > 0).

    Estrategia en cascada, tolerante a erratas de OCR:
      1. Coincidencia exacta del nombre normalizado.
      2. Un nombre del catalogo aparece dentro del texto (OCR con palabras de mas).
      3. El texto aparece dentro de un nombre del catalogo (OCR con palabras de menos).
      4. Coincidencia difusa (difflib) para erratas sueltas.
    """
    kn = _norm_kn(body)
    if len(kn) < 4:
        return None
    if names_sorted is None:
        names_sorted = sorted(full_index.keys(), key=len, reverse=True)

    def _priced(it) -> bool:
        return it is not None and float(it.get("CurrentPrice") or 0) > 0

    # 1. exacto
    it = full_index.get(kn)
    if _priced(it):
        return it
    # 2. nombre del catalogo contenido en el texto (mas largo primero)
    for nm in names_sorted:
        if len(nm) >= 6 and nm in kn and _priced(full_index[nm]):
            return full_index[nm]
    # 3. texto contenido en un nombre del catalogo (solo si el texto es sustancioso)
    if len(kn) >= 6:
        for nm in names_sorted:
            if kn in nm and _priced(full_index[nm]):
                return full_index[nm]
    # 4. difuso (tolera errores de OCR como letras cambiadas)
    cand = difflib.get_close_matches(kn, names_sorted, n=1, cutoff=0.84)
    if cand and _priced(full_index[cand[0]]):
        return full_index[cand[0]]
    return None


def extract_catalog_rewards(ocr_text: str, full_index: dict) -> tuple:
    """En cada linea de recompensa busca el item del catalogo con precio.

    Acepta filas con o sin cantidad: "10x Divine Orb", "1x Aldur's Legacy" o
    incluso "Aldur's Legacy" (cantidad asumida = 1). Cotiza cualquier tipo de
    item (currency, gemas, runas con nombre propio, items unicos, etc.).

    Devuelve (matched, unmatched):
      matched   = lista de (item, cantidad, texto)
      unmatched = lista de (texto_recompensa, cantidad) sin precio en el mercado
    """
    names = sorted(full_index.keys(), key=len, reverse=True)  # mas largos primero
    matched = []
    unmatched = []
    seen = set()
    for raw in (ocr_text or "").splitlines():
        m = _REWARD_LINE_RE.match(raw.strip())
        if not m:
            continue
        qraw = m.group(1)
        if qraw:
            try:
                qty = int(qraw.translate(_QTY_TRANS))
            except ValueError:
                qty = 1
            if qty <= 0 or qty > 9999:
                qty = 1
            has_qty = True
        else:
            qty = 1
            has_qty = False
        body = m.group(2).strip()
        if len(body) < 3:
            continue
        # las runas de augment "X Rune of Y" las maneja el matcher de runas
        if _looks_like_rune_name(body):
            continue
        hit = _match_catalog_item(body, full_index, names)
        if hit is not None:
            key = (_norm_kn(hit.get("Text") or hit.get("Name") or ""), qty)
            if key in seen:
                continue
            seen.add(key)
            matched.append((hit, qty, body))
        elif has_qty:
            # tenia cantidad explicita pero no cotiza: recompensa para usar/craftear
            unmatched.append((body, qty))
        # sin cantidad y sin match -> linea ignorada (evita ruido de OCR)
    return matched, unmatched


def analyze_image(image_or_path, market) -> Analysis:
    try:
        img = load_image(image_or_path) if isinstance(image_or_path, str) else image_or_path
    except Exception as exc:
        return Analysis(error=f"No pude abrir la imagen: {exc}")
    try:
        text = ocr_pil_image(img)
    except Exception as exc:
        import traceback as _tb
        return Analysis(error="OCR fallo: " + repr(exc) + "\n\nDetalle:\n" + _tb.format_exc())
    return analyze_text(text, market)


def analyze_text(text: str, market) -> Analysis:
    """Combina nombres de runa + recompensas de currency, con veredicto VENDER/USAR."""
    try:
        market.ensure_loaded()
    except Exception:
        pass
    items = getattr(market, "_items", None) or []
    divine = float(getattr(market, "divine_price", 0.0) or 0.0)
    league = str(getattr(market, "resolved_league", "") or "")
    rune_index = build_rune_index(items)
    full_index = build_full_index(items)

    results: list = []

    # (a) Nombres de runa (texto)
    for name in extract_rune_names(text):
        item, note, conf = match_rune(name, rune_index)
        if item is None:
            results.append(RuneResult(
                detected_text=name, matched_name=name,
                price_ex=0.0, price_div=0.0,
                tier_note="sin precio de venta · usar/craftear",
                confidence="baja", found=False, verdict="USAR"))
            continue
        ex, div = _price_of(item, divine)
        is_proxy = ("tier rastreado" in note) or ("aprox" in note) or ("similitud" in note)
        if is_proxy:
            verdict = "USAR"
            note = "no se vende directo · referencia (" + note + ")"
        else:
            verdict = "VENDER"
        results.append(RuneResult(
            detected_text=name,
            matched_name=str(item.get("Text") or item.get("Name") or name),
            price_ex=ex, price_div=div, tier_note=note, confidence=conf,
            found=True, verdict=verdict))

    # (b) Recompensas del catalogo (cualquier item con precio), p. ej.
    #     "10x Divine Orb", "1x Aldur's Legacy"  -> VENDER
    matched, unmatched = extract_catalog_rewards(text, full_index)
    for item, qty, raw in matched:
        unit_ex, unit_div = _price_of(item, divine)
        name = str(item.get("Text") or item.get("Name") or raw)
        label = f"{qty}x {name}" if qty != 1 else name
        if qty != 1:
            note = f"{qty} \u00d7 {unit_ex:.2f} ex c/u  =  {unit_ex * qty:.2f} ex"
        else:
            note = "recompensa vendible"
        results.append(RuneResult(
            detected_text=raw, matched_name=label,
            price_ex=unit_ex * qty, price_div=unit_div * qty,
            tier_note=note, confidence="alta", found=True, verdict="VENDER"))

    # (c) Filas de recompensa sin precio en el mercado (p. ej. "Medved's Boon")
    for body, qty in unmatched:
        label = f"{qty}x {body}" if qty != 1 else body
        results.append(RuneResult(
            detected_text=body, matched_name=label,
            price_ex=0.0, price_div=0.0,
            tier_note="sin precio en el mercado · usar/craftear",
            confidence="baja", found=False, verdict="USAR"))

    if not results:
        leido = (text or "").strip()
        if leido:
            diag = "\n\nTexto que leyo el OCR (para diagnostico):\n" + leido[:600]
        else:
            diag = ("\n\nEl OCR no leyo NADA: el area capturada quedo vacia o muy chica. "
                    "Selecciona el area de las recompensas un poco mas grande.")
        return Analysis(ocr_text=text,
                        error="No detecte runas ni recompensas en la imagen.\n\n"
                              "Captura el panel SIN pasar el mouse sobre una recompensa "
                              "(el tooltip tapa los nombres) y abarca las filas con su texto."
                              + diag)

    # de-duplicar por etiqueta, quedando el de mayor valor
    best_by_name: dict = {}
    for r in results:
        k = r.matched_name.strip().lower()
        if k not in best_by_name or r.price_ex > best_by_name[k].price_ex:
            best_by_name[k] = r
    final = list(best_by_name.values())
    # ordenar: VENDER con precio primero (mayor a menor), luego USAR, luego sin precio
    final.sort(key=lambda r: (r.verdict == "VENDER" and r.found, r.found, r.price_ex), reverse=True)
    return Analysis(results=final, league=league, divine_price=divine, ocr_text=text)


def summary_line(a: Analysis) -> str:
    total = len(a.results)
    vend = sum(1 for r in a.results if r.verdict == "VENDER" and r.found)
    usar = total - vend
    partes = [f"Lei {total} recompensa" + ("s" if total != 1 else "")]
    if vend:
        partes.append(f"{vend} para vender")
    if usar:
        partes.append(f"{usar} para usar/craftear")
    return " \u2014 ".join(partes)


def top_to_sell(a: Analysis, n: int = 3) -> list:
    """Top-N recompensas vendibles (verdict VENDER) por valor."""
    vend = [r for r in a.results if r.verdict == "VENDER" and r.found]
    vend.sort(key=lambda r: r.price_ex, reverse=True)
    return vend[:n]


def best_to_sell(a: Analysis):
    """La mejor recompensa que se vende de verdad (verdict VENDER)."""
    vend = [r for r in a.results if r.verdict == "VENDER" and r.found]
    if vend:
        return max(vend, key=lambda r: r.price_ex)
    # si nada se vende directo, devolver la de mayor precio de referencia
    found = [r for r in a.results if r.found]
    return max(found, key=lambda r: r.price_ex) if found else None


def format_report(a: Analysis) -> str:
    if a.error and not a.results:
        return "\u26a0 " + a.error
    lines: list = []
    best = best_to_sell(a)
    lines.append(summary_line(a))
    lines.append("")
    if best and best.verdict == "VENDER" and best.found:
        lines.append(f"\u2b50 MEJOR PARA VENDER: {best.matched_name}  ({best.price_text})")
        lines.append("")
    for i, r in enumerate(a.results, 1):
        tag = "VENDER" if (r.verdict == "VENDER" and r.found) else "USAR"
        crown = " \u2b50" if (best is not None and r is best and tag == "VENDER") else ""
        if r.found:
            lines.append(f"[{tag}]{crown} {r.matched_name}: {r.price_text}")
        else:
            lines.append(f"[{tag}] {r.matched_name}: sin precio de venta \u00b7 usar/craftear")
        if r.tier_note:
            lines.append(f"        \u00b7 {r.tier_note}")
    lines.append("")
    meta = []
    if a.league:
        meta.append(f"Liga: {a.league}")
    if a.divine_price:
        meta.append(f"1 div \u2248 {a.divine_price:g} ex")
    meta.append("Fuente: poe2scout (mercado en vivo)")
    lines.append(" | ".join(meta))
    return "\n".join(lines)
