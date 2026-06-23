"""
text_match.py — Matching de texto robusto para PoE2 Valuator
------------------------------------------------------------

Utilidades compartidas para emparejar texto (nombres de items copiados o
leidos por OCR) contra el catalogo del mercado de forma fiable.

Aporta tres piezas:

  1. `bounded_edit_distance(a, b, max_distance)`
     Distancia de edicion de Levenshtein con terminacion temprana (devuelve -1
     si supera `max_distance`). Portada de la idea de `StrComp.cs` del proyecto
     de referencia RuneshapePriceChecker: rapida y predecible para erratas OCR.

  2. `normalize_ocr(s)`
     Normaliza un texto colapsando confusiones tipicas de OCR (0<->o, 1<->l<->i,
     rn->m, etc.) para que "Divlne 0rb" y "Divine Orb" comparen igual.

  3. `best_match(query, candidates, ...)`
     Elige el mejor candidato combinando: coincidencia exacta -> contencion por
     palabra completa -> distancia de edicion con umbral *escalado por longitud*
     (mas estricto en nombres cortos, mas laxo en largos) -> ratio de difflib.
     Devuelve `(candidato, score 0..1, motivo)` o `(None, 0.0, "")`.

Sin dependencias externas: solo stdlib. Testeable de forma aislada.
"""
from __future__ import annotations

import difflib
import re
from typing import Iterable, Optional


# Confusiones de OCR mas comunes (mapeamos a una forma canonica).
# Se aplican tras pasar a minusculas. El objetivo no es "leer bien" sino que
# dos textos con las mismas erratas tipicas colapsen al mismo valor.
_OCR_CHAR_MAP = {
    "0": "o",
    "1": "l",
    "|": "l",
    "!": "l",
    "5": "s",
    "8": "b",
    "2": "z",
    "@": "a",
    "$": "s",
    "`": "",
    "'": "",
    "’": "",  # apostrofe tipografico
    "´": "",
    "“": "",
    "”": "",
}

# Secuencias multi-caracter (orden importa: se aplican antes que las de 1 char).
_OCR_SEQ = (
    ("rn", "m"),   # "rn" suele leerse como "m"
    ("vv", "w"),
    ("cl", "d"),
)


def normalize_ocr(s: str) -> str:
    """Normaliza texto para comparacion tolerante a OCR.

    minusculas -> quita apostrofes -> colapsa confusiones de caracteres ->
    deja solo [a-z0-9 ] ya canonizado -> colapsa espacios.
    """
    if not s:
        return ""
    s = s.lower()
    # quitar acentos latinos comunes
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    # secuencias multi-caracter primero
    for a, b in _OCR_SEQ:
        s = s.replace(a, b)
    # caracteres sueltos
    out = []
    for ch in s:
        out.append(_OCR_CHAR_MAP.get(ch, ch))
    s = "".join(out)
    # dejar solo letras/numeros/espacio
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def bounded_edit_distance(a: str, b: str, max_distance: int) -> int:
    """Distancia de Levenshtein con corte temprano.

    Devuelve la distancia si es <= max_distance; si no, -1.
    Implementacion O(n*m) con dos filas y poda por mejor valor de fila.
    """
    if max_distance < 0:
        return -1
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_distance:
        return -1
    if la == 0:
        return lb if lb <= max_distance else -1
    if lb == 0:
        return la if la <= max_distance else -1
    # `a` el mas corto para usar menos memoria
    if la > lb:
        a, b = b, a
        la, lb = lb, la

    prev = list(range(la + 1))
    curr = [0] * (la + 1)
    for i in range(1, lb + 1):
        curr[0] = i
        best = curr[0]
        bi = b[i - 1]
        for j in range(1, la + 1):
            cost = 0 if a[j - 1] == bi else 1
            v = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            curr[j] = v
            if v < best:
                best = v
        if best > max_distance:
            return -1
        prev, curr = curr, prev
    d = prev[la]
    return d if d <= max_distance else -1


def _max_distance_for(length: int) -> int:
    """Umbral de erratas tolerado segun longitud del texto normalizado.

    Mas estricto en nombres cortos (donde una errata cambia el sentido) y mas
    laxo en nombres largos (donde el OCR mete mas ruido pero el match sigue claro).
    """
    if length <= 4:
        return 0
    if length <= 7:
        return 1
    if length <= 14:
        return 2
    return 1 + length // 8  # 15->2, 24->4, 40->6 ...


def _word_set(s: str) -> set:
    return {w for w in s.split(" ") if len(w) >= 3}


def best_match(
    query: str,
    candidates: Iterable[str],
    *,
    min_len: int = 4,
    ratio_floor: float = 0.78,
) -> tuple:
    """Devuelve (mejor_candidato, score 0..1, motivo) o (None, 0.0, "").

    `candidates` son strings *ya legibles* (se normalizan aqui internamente).
    Estrategia en cascada, de mayor a menor confianza:
      1. exacto (tras normalizar)            -> score 1.0
      2. contencion por palabra completa     -> score 0.9
      3. distancia de edicion <= umbral(len) -> score 0.80..0.97 segun cercania
      4. ratio difflib >= ratio_floor        -> score = ratio
    """
    qn = normalize_ocr(query)
    if len(qn) < min_len:
        return None, 0.0, ""

    cand_list = list(candidates)
    norm_pairs = [(c, normalize_ocr(c)) for c in cand_list]

    # 1. exacto
    for c, cn in norm_pairs:
        if cn and cn == qn:
            return c, 1.0, "exacto"

    # 2. contencion por palabra completa (evita falsos positivos de substring suelto)
    q_words = _word_set(qn)
    best_contain = None
    best_contain_len = 0
    for c, cn in norm_pairs:
        if not cn:
            continue
        # el nombre del catalogo aparece entero dentro del query, o viceversa,
        # exigiendo limite de palabra para no casar "ire" dentro de "fire".
        if re.search(r"(?:^| )" + re.escape(cn) + r"(?: |$)", qn) or \
           re.search(r"(?:^| )" + re.escape(qn) + r"(?: |$)", cn):
            if len(cn) > best_contain_len:
                best_contain = c
                best_contain_len = len(cn)
    if best_contain is not None:
        return best_contain, 0.9, "contencion por palabra"

    # 3. distancia de edicion con umbral escalado por longitud
    md = _max_distance_for(len(qn))
    best_c = None
    best_d = md + 1
    for c, cn in norm_pairs:
        if not cn or abs(len(cn) - len(qn)) > md:
            continue
        d = bounded_edit_distance(qn, cn, md)
        if d >= 0 and d < best_d:
            best_d = d
            best_c = c
            if d == 0:
                break
    if best_c is not None:
        # score: 0.97 si d=1, bajando suavemente
        score = max(0.80, 0.97 - 0.05 * (best_d - 1))
        return best_c, score, f"edicion d={best_d}"

    # 4. ratio difflib como ultimo recurso
    norms = [cn for _, cn in norm_pairs if cn]
    cand = difflib.get_close_matches(qn, norms, n=1, cutoff=ratio_floor)
    if cand:
        ratio = difflib.SequenceMatcher(None, qn, cand[0]).ratio()
        for c, cn in norm_pairs:
            if cn == cand[0]:
                return c, ratio, f"ratio={ratio:.2f}"
    return None, 0.0, ""
