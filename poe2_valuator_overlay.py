"""
PoE2 Item Valuator MVP
----------------------
Overlay local y seguro para Path of Exile 2.

Uso: ejecuta este archivo, deja la ventana encima del juego, pon PoE2 en Borderless/Windowed,
haz hover sobre un item y pulsa Ctrl+C. El overlay lee SOLO el portapapeles.

No lee memoria, no inyecta DLLs, no automatiza clics ni teclas del juego.
"""
from __future__ import annotations

import json
import math
import os
import sys
import re
import threading
import time
import traceback
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
try:
    import rune_reward as _rune_reward
except Exception:
    _rune_reward = None
try:
    import text_match as _tm  # matching robusto (Levenshtein acotado + OCR) compartido
except Exception:
    _tm = None
try:
    from build_to_filter import build_profile as _derive_build_profile, generate_filter as _generate_filter
except Exception:
    _derive_build_profile = None
    _generate_filter = None
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import tkinter as tk
    from tkinter import messagebox, filedialog
except Exception:  # pragma: no cover - solo para ambientes sin GUI
    tk = None
    messagebox = None

try:
    import customtkinter as ctk
    HAS_CTK = True
except Exception:
    ctk = None
    HAS_CTK = False

APP_NAME = "PoE2 Valuator"
APP_VERSION = "0.5"
APP_AUTHOR = "Polietileno"
# Repo de GitHub para el chequeo de actualizaciones (owner/repo). Editable en config.json ("github_repo").
GITHUB_REPO = "polietilenopy/poe2-valuator"
# PoE2 Item Valuator — by Polietileno. Uso personal/educativo.
if getattr(sys, "frozen", False):
    # Empaquetado con PyInstaller: usar la carpeta del .exe para config/historial/filtros.
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
HISTORY_PATH = BASE_DIR / "history.jsonl"
CACHE_PATH = BASE_DIR / "poe2scout_items_cache.json"
SEPARATOR_RE = re.compile(r"^-{2,}\s*$")

DEFAULT_CONFIG = {
    "realm": "poe2",
    "league": "Runes of Aldur",
    "auto_detect_league": True,
    "poll_ms": 600,
    "window_alpha": 0.94,
    "always_on_top": True,
    "enable_market_lookup": True,
    "market_cache_minutes": 20,
    "api_base_urls": [
        "https://poe2scout.com/api",
        "https://api.poe2scout.com/api"
    ],
    "user_agent": "PoE2ItemValuatorMVP/0.2 contact: change-me@example.com",
    "currency_label": "ex",
    "divine_label": "div",
    "show_both_currencies": True,
    "auto_trade_comparables": False,
    "trade_min_interval_s": 2.5,
    "request_timeout": 8,
    "build_file": "",
    "window_geometry": "",
    "start_compact": False,
    # Decision vender-en-mercado vs convertir-en-oro: si el valor de mercado del
    # item es menor a este umbral (en exalted), conviene venderlo al mercader por oro.
    "convert_to_gold_below_ex": 1.0,
    # Fuente de respaldo de economia de currencies (poe.ninja). Off por defecto:
    # poe2scout ya cubre todos los currencies; activalo si quieres rellenar faltantes.
    "enable_poeninja_fallback": False,
    "poeninja_base_url": "https://poe.ninja/poe2/api",
}

RARITY_MAP = {
    "normal": "Normal",
    "magic": "Magic",
    "rare": "Rare",
    "unique": "Unique",
    "currency": "Currency",
    "gem": "Gem",
    "raro": "Rare",
    "único": "Unique",
    "unico": "Unique",
    "mágico": "Magic",
    "magico": "Magic",
    "moneda": "Currency",
    "gema": "Gem",
}

WEAPON_KEYWORDS = [
    "bow", "crossbow", "quarterstaff", "staff", "sword", "axe", "mace", "wand",
    "sceptre", "scepter", "dagger", "claw", "spear", "flail",
    "arco", "ballesta", "báculo", "baculo", "bastón", "baston", "espada",
    "hacha", "mazo", "vara", "cetro", "daga", "garra", "lanza", "mayal"
]

ARMOUR_KEYWORDS = [
    "helmet", "helm", "body armour", "body armor", "gloves", "boots", "shield", "focus",
    "casco", "armadura corporal", "guantes", "botas", "escudo", "foco"
]

ACCESSORY_KEYWORDS = [
    "ring", "amulet", "belt", "quiver", "charm",
    "anillo", "amuleto", "cinturón", "cinturon", "carcaj", "talismán", "talisman"
]


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
        return dict(DEFAULT_CONFIG)
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_config(config: dict[str, Any]) -> None:
    """Persiste config.json para recordar opciones (p. ej. la build elegida)."""
    try:
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def default_build_dir() -> str:
    """Mejor carpeta inicial donde el usuario suele tener su .build (PoE2 / Path of Building / Downloads)."""
    home = Path.home()
    candidates = [
        home / "Documents" / "My Games" / "Path of Exile 2",
        home / "OneDrive" / "Documents" / "My Games" / "Path of Exile 2",
        home / "Documents" / "Path of Building 2" / "Builds",
        home / "Documents" / "Path of Building Community (PoE2)" / "Builds",
        home / "OneDrive" / "Documents" / "Path of Building 2" / "Builds",
        home / "Downloads",
        home / "Documents",
    ]
    for c in candidates:
        try:
            if c.exists():
                return str(c)
        except Exception:
            pass
    return str(home)


def clean_line(line: str) -> str:
    return line.strip().replace("\u00a0", " ")


def looks_like_poe_item(text: str) -> bool:
    if not text or len(text) < 20:
        return False
    t = text.lower()
    has_rarity = "rarity:" in t or "rareza:" in t
    has_item_level = "item level:" in t or "nivel de objeto:" in t or "nivel del objeto:" in t
    has_separator = "--------" in text or "────────" in text
    return has_separator and (has_rarity or has_item_level)


def safe_float(value: str) -> float:
    try:
        return float(value.replace(",", "."))
    except Exception:
        return 0.0


def max_regex(lines: list[str], patterns: list[str], flags: int = re.I) -> float:
    best = 0.0
    for line in lines:
        for pat in patterns:
            for m in re.finditer(pat, line, flags):
                try:
                    best = max(best, safe_float(m.group(1)))
                except Exception:
                    pass
    return best


def sum_regex(lines: list[str], patterns: list[str], flags: int = re.I) -> float:
    total = 0.0
    for line in lines:
        for pat in patterns:
            for m in re.finditer(pat, line, flags):
                try:
                    total += safe_float(m.group(1))
                except Exception:
                    pass
    return total


@dataclass
class ParsedItem:
    raw_text: str
    item_class: str = ""
    rarity: str = "Unknown"
    name: str = ""
    base_type: str = ""
    item_level: int | None = None
    quality: int | None = None
    corrupted: bool = False
    unidentified: bool = False
    category: str = "unknown"
    stats: dict[str, float] = field(default_factory=dict)
    mod_lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        if self.rarity in {"Rare", "Magic", "Unique"} and self.name:
            return self.name
        return self.name or self.base_type or "Ítem detectado"

    @property
    def searchable_names(self) -> list[str]:
        candidates = [self.name, self.base_type]
        # Para uniques Poe2Scout suele usar name y type/base por separado.
        return [c.strip() for c in candidates if c and c.strip()]


@dataclass
class ValuationResult:
    title: str
    price_text: str
    quick_sell: str
    fair_price: str
    ambitious_price: str
    confidence: str
    source: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_market_match: dict[str, Any] | None = None
    build_fit: float | None = None
    build_verdict: str = ""
    build_reasons: list[str] = field(default_factory=list)
    build_irrelevant: list[str] = field(default_factory=list)
    compare_text: str = ""
    roll_quality_text: str = ""
    market_value_ex: float = 0.0   # valor numerico de mercado en exalted (para decidir oro vs mercado)
    gold_verdict: str = ""         # "MERCADO" | "ORO" | "" (se calcula al renderizar)
    gold_estimate: str = ""        # estimado aproximado de oro del mercader (sin fuente exacta)


def split_sections(lines: list[str]) -> list[list[str]]:
    sections: list[list[str]] = [[]]
    for line in lines:
        if SEPARATOR_RE.match(line):
            if sections[-1]:
                sections.append([])
            continue
        if line:
            sections[-1].append(line)
    return [s for s in sections if s]


def parse_item_text(text: str) -> ParsedItem:
    raw_lines = [clean_line(l) for l in text.replace("────────", "--------").splitlines()]
    lines = [l for l in raw_lines if l]
    item = ParsedItem(raw_text=text)
    if not lines:
        item.notes.append("No se detectaron líneas útiles.")
        return item

    # Campos base
    for line in lines:
        m = re.match(r"^(Item Class|Clase de objeto|Clase):\s*(.+)$", line, re.I)
        if m:
            item.item_class = m.group(2).strip()
        m = re.match(r"^(Rarity|Rareza):\s*(.+)$", line, re.I)
        if m:
            raw_rarity = m.group(2).strip().lower()
            item.rarity = RARITY_MAP.get(raw_rarity, m.group(2).strip())
        m = re.match(r"^(Item Level|Nivel de objeto|Nivel del objeto):\s*(\d+)", line, re.I)
        if m:
            item.item_level = int(m.group(2))
        m = re.match(r"^(Quality|Calidad):\s*\+?(\d+)%", line, re.I)
        if m:
            item.quality = int(m.group(2))

    t_low = "\n".join(lines).lower()
    item.corrupted = any(word in t_low for word in ["corrupted", "corrupto", "corrupta"])
    item.unidentified = any(word in t_low for word in ["unidentified", "sin identificar"])

    # Nombre/base: líneas entre rarity y primer separador.
    first_sep_index = next((i for i, l in enumerate(lines) if SEPARATOR_RE.match(l)), len(lines))
    rarity_index = next((i for i, l in enumerate(lines[:first_sep_index]) if re.match(r"^(Rarity|Rareza):", l, re.I)), None)
    header_candidates: list[str] = []
    if rarity_index is not None:
        for l in lines[rarity_index + 1:first_sep_index]:
            if re.match(r"^(Item Class|Clase de objeto|Rarity|Rareza):", l, re.I):
                continue
            header_candidates.append(l)

    if item.rarity in {"Rare", "Magic", "Unique"}:
        if len(header_candidates) >= 1:
            item.name = header_candidates[0]
        if len(header_candidates) >= 2:
            item.base_type = header_candidates[1]
    else:
        if header_candidates:
            item.name = header_candidates[0]
            item.base_type = header_candidates[0]

    sections = split_sections(lines)

    # Mod lines: líneas que no son properties conocidas.
    meta_prefixes = (
        "item class:", "clase de objeto:", "rarity:", "rareza:", "quality:", "calidad:",
        "requirements:", "requisitos:", "sockets:", "engastes:", "rune sockets:",
        "item level:", "nivel de objeto:", "level:", "nivel:", "str:", "dex:", "int:",
        "physical damage:", "daño físico:", "elemental damage:", "daño elemental:",
        "critical hit chance:", "probabilidad de golpe crítico:", "attacks per second:",
        "ataques por segundo:", "armour:", "armadura:", "evasion rating:", "evasión:",
        "energy shield:", "escudo de energía:", "requires", "requiere", "description:",
    )
    possible_mods: list[str] = []
    for sec in sections[1:]:
        for l in sec:
            low = l.lower()
            if low in {"corrupted", "corrupto", "corrupta", "unidentified", "sin identificar"}:
                continue
            if low.startswith(meta_prefixes):
                continue
            # Evitar textos largos de flavor/descrición sin números salvo mods especiales.
            if any(ch.isdigit() for ch in l) or "+" in l or "%" in l:
                possible_mods.append(l)
    item.mod_lines = possible_mods

    all_lines = lines
    stats: dict[str, float] = {}

    stats["life"] = max_regex(all_lines, [
        r"\+?(\d+)\s+to maximum Life",
        r"\+?(\d+)\s+(?:de|a la)\s+vida máxima",
        r"\+?(\d+)\s+vida máxima",
    ])
    stats["mana"] = max_regex(all_lines, [
        r"\+?(\d+)\s+to maximum Mana",
        r"\+?(\d+)\s+(?:de|al)\s+maná máximo",
        r"\+?(\d+)\s+maná máximo",
    ])
    stats["energy_shield_flat"] = max_regex(all_lines, [
        r"\+?(\d+)\s+to maximum Energy Shield",
        r"\+?(\d+)\s+(?:de|al)\s+escudo de energía máximo",
    ])

    fire = max_regex(all_lines, [r"\+?(\d+)%\s+to Fire Resistance", r"\+?(\d+)%\s+(?:de|a la)\s+resistencia al fuego"])
    cold = max_regex(all_lines, [r"\+?(\d+)%\s+to Cold Resistance", r"\+?(\d+)%\s+(?:de|a la)\s+resistencia al frío", r"\+?(\d+)%\s+(?:de|a la)\s+resistencia al frio"])
    lightning = max_regex(all_lines, [r"\+?(\d+)%\s+to Lightning Resistance", r"\+?(\d+)%\s+(?:de|a la)\s+resistencia al rayo"])
    chaos = max_regex(all_lines, [r"\+?(\d+)%\s+to Chaos Resistance", r"\+?(\d+)%\s+(?:de|a la)\s+resistencia al caos"])
    all_ele = max_regex(all_lines, [
        r"\+?(\d+)%\s+to all Elemental Resistances",
        r"\+?(\d+)%\s+(?:de|a todas las)\s+resistencias elementales",
    ])
    if all_ele:
        fire += all_ele
        cold += all_ele
        lightning += all_ele
    stats["fire_res"] = fire
    stats["cold_res"] = cold
    stats["lightning_res"] = lightning
    stats["chaos_res"] = chaos
    stats["elemental_res_total"] = fire + cold + lightning
    stats["total_res"] = fire + cold + lightning + chaos

    stats["movement_speed"] = max_regex(all_lines, [
        r"(\d+)%\s+increased Movement Speed",
        r"(\d+)%\s+de aumento de la velocidad de movimiento",
        r"(\d+)%\s+aumento de velocidad de movimiento",
    ])
    stats["item_rarity"] = max_regex(all_lines, [
        r"(\d+)%\s+increased Rarity of Items found",
        r"(\d+)%\s+increased Rarity",
        r"(\d+)%\s+de aumento de rareza de los objetos",
        r"(\d+)%\s+aumento de rareza",
    ])
    stats["spirit"] = max_regex(all_lines, [r"\+?(\d+)\s+to Spirit", r"\+?(\d+)\s+(?:de|al)\s+Espíritu", r"\+?(\d+)\s+(?:de|al)\s+Espiritu"])
    stats["strength"] = max_regex(all_lines, [r"\+?(\d+)\s+to Strength", r"\+?(\d+)\s+(?:de|a la)\s+Fuerza"])
    stats["dexterity"] = max_regex(all_lines, [r"\+?(\d+)\s+to Dexterity", r"\+?(\d+)\s+(?:de|a la)\s+Destreza"])
    stats["intelligence"] = max_regex(all_lines, [r"\+?(\d+)\s+to Intelligence", r"\+?(\d+)\s+(?:de|a la)\s+Inteligencia"])
    all_attr = max_regex(all_lines, [r"\+?(\d+)\s+to all Attributes", r"\+?(\d+)\s+(?:a todos los|de todos los)\s+atributos"])
    stats["all_attributes"] = all_attr
    stats["attributes_total"] = stats["strength"] + stats["dexterity"] + stats["intelligence"] + all_attr * 3

    stats["skill_gem_levels"] = max_regex(all_lines, [
        r"\+(\d+)\s+to Level of all .*Skill Gems",
        r"\+(\d+)\s+to Level of all .*Skills",
        r"\+(\d+)\s+al nivel de todas? .*gemas",
        r"\+(\d+)\s+al nivel de todas? .*habilidades",
    ])
    stats["attack_speed"] = max_regex(all_lines, [r"(\d+)%\s+increased Attack Speed", r"(\d+)%\s+de aumento de la velocidad de ataque"])
    stats["cast_speed"] = max_regex(all_lines, [r"(\d+)%\s+increased Cast Speed", r"(\d+)%\s+de aumento de la velocidad de lanzamiento"])
    stats["crit_chance_inc"] = max_regex(all_lines, [r"(\d+)%\s+increased Critical (?:Hit |Strike )?Chance", r"(\d+)%\s+de aumento.*probabilidad.*crític"])
    stats["spell_damage"] = max_regex(all_lines, [r"(\d+)%\s+increased Spell Damage", r"(\d+)%\s+de aumento.*daño de hechizos"])
    stats["physical_damage_inc"] = max_regex(all_lines, [r"(\d+)%\s+increased Physical Damage", r"(\d+)%\s+de aumento.*daño físico"])
    stats["elemental_damage_inc"] = max_regex(all_lines, [r"(\d+)%\s+increased Elemental Damage", r"(\d+)%\s+de aumento.*daño elemental"])

    # Properties de armas: Physical Damage: 123-456, Elemental Damage: 1-50, 10-100...
    pdps = 0.0
    edps = 0.0
    attacks_per_second = max_regex(all_lines, [r"Attacks per Second:\s*([\d.,]+)", r"Ataques por segundo:\s*([\d.,]+)"])
    phys_line = next((l for l in all_lines if re.search(r"^(Physical Damage|Daño físico):", l, re.I)), "")
    if phys_line:
        m = re.search(r"(\d+)\s*-\s*(\d+)", phys_line)
        if m:
            pdps = (safe_float(m.group(1)) + safe_float(m.group(2))) / 2.0 * (attacks_per_second or 1.0)
    elem_lines = [l for l in all_lines if re.search(r"^(Elemental Damage|Daño elemental):", l, re.I)]
    for elem_line in elem_lines:
        for m in re.finditer(r"(\d+)\s*-\s*(\d+)", elem_line):
            edps += (safe_float(m.group(1)) + safe_float(m.group(2))) / 2.0 * (attacks_per_second or 1.0)
    stats["attacks_per_second"] = attacks_per_second
    stats["pdps"] = round(pdps, 1) if pdps else 0.0
    stats["edps"] = round(edps, 1) if edps else 0.0
    stats["total_dps"] = round(pdps + edps, 1) if (pdps or edps) else 0.0

    rune_sockets = max_regex(all_lines, [r"Rune Sockets:\s*(\d+)", r"Engastes de runa:\s*(\d+)"])
    stats["rune_sockets"] = rune_sockets

    # --- Mods adicionales (added damage, ES/evasion/armour %, accuracy, leech, regen, crit dmg) ---
    def _adds(type_kw: str) -> float:
        tot = 0.0
        for l in all_lines:
            for m in re.finditer(rf"Adds\s+(\d+)\s+to\s+(\d+)\s+{type_kw}\s+[Dd]amage", l):
                tot += (safe_float(m.group(1)) + safe_float(m.group(2))) / 2.0
            for m in re.finditer(rf"Añade\s+(\d+)\s+a\s+(\d+)\s+de\s+daño\s+{type_kw}", l, re.I):
                tot += (safe_float(m.group(1)) + safe_float(m.group(2))) / 2.0
        return round(tot, 1)

    add_fire = _adds("Fire"); add_cold = _adds("Cold"); add_light = _adds("Lightning")
    stats["added_phys_damage"] = _adds("Physical")
    stats["added_elemental_damage"] = round(add_fire + add_cold + add_light, 1)
    stats["added_chaos_damage"] = _adds("Chaos")

    stats["increased_es_pct"] = max_regex(all_lines, [
        r"(\d+)%\s+increased (?:maximum )?Energy Shield",
        r"(\d+)%\s+de aumento.*escudo de energía",
    ])
    stats["increased_evasion_pct"] = max_regex(all_lines, [
        r"(\d+)%\s+increased Evasion Rating", r"(\d+)%\s+de aumento.*evasión",
    ])
    stats["increased_armour_pct"] = max_regex(all_lines, [
        r"(\d+)%\s+increased Armour", r"(\d+)%\s+de aumento.*armadura",
    ])
    stats["accuracy"] = max_regex(all_lines, [
        r"\+?(\d+)\s+to Accuracy Rating", r"\+?(\d+)\s+(?:de|a la)\s+precisión",
    ])
    stats["crit_damage_bonus"] = max_regex(all_lines, [
        r"(\d+)%\s+increased Critical Damage Bonus",
        r"(\d+)%\s+de aumento.*daño crítico",
    ])
    stats["attack_damage_inc"] = max_regex(all_lines, [
        r"(\d+)%\s+increased Attack Damage",
        r"(\d+)%\s+increased Damage with Attacks",
    ])
    stats["life_regen"] = max_regex(all_lines, [
        r"([\d.]+)\s+Life Regeneration per second",
        r"([\d.]+)\s+de regeneración de vida",
    ])
    stats["mana_leech"] = max_regex(all_lines, [r"Leech\s+([\d.]+)%\s+of .*as Mana"])
    stats["life_leech"] = max_regex(all_lines, [r"Leech\s+([\d.]+)%\s+of .*as Life"])
    # +niveles de tipos concretos de skills (melee/spell/proyectil/minion) -> alimenta skill_gem_levels
    specific_levels = max_regex(all_lines, [
        r"\+(\d+)\s+to Level of all (?:Melee|Spell|Projectile|Minion|Cold|Fire|Lightning|Chaos|Physical) Skills",
    ])
    if specific_levels > stats.get("skill_gem_levels", 0):
        stats["skill_gem_levels"] = specific_levels

    # Limpieza de ceros para visualización.
    item.stats = {k: v for k, v in stats.items() if v not in (None, 0, 0.0)}
    item.category = infer_category(item)
    return item


def infer_category(item: ParsedItem) -> str:
    text = " ".join([item.item_class, item.base_type, item.name]).lower()
    if item.rarity == "Currency" or "currency" in text or "moneda" in text:
        return "currency"
    if "waystone" in text or "piedra de camino" in text:
        return "waystone"
    if "jewel" in text or "joya" in text:
        return "jewel"
    if any(k in text for k in WEAPON_KEYWORDS):
        return "weapon"
    if "boot" in text or "botas" in text:
        return "boots"
    if any(k in text for k in ACCESSORY_KEYWORDS):
        return "accessory"
    if any(k in text for k in ARMOUR_KEYWORDS):
        return "armour"
    if item.rarity == "Gem":
        return "gem"
    return "unknown"


def build_item_from_ocr(text: str, market=None) -> ParsedItem:
    """Construye un ParsedItem desde texto OCR de una CAPTURA del tooltip de un item.

    Diferencia clave con el Ctrl+C: el texto copiado trae 'Item Class:' y 'Rarity:',
    pero una captura visual NO los tiene (solo nombre, base, propiedades y mods). Por
    eso parse_item_text por si solo deja rarity=Unknown. Aca adaptamos:

      1. Si el texto ya viene en formato copiado (tiene 'rarity:'/'rareza:'), se usa
         parse_item_text tal cual.
      2. Si es tooltip visual:
         a. Probamos SOLO las primeras lineas (el nombre) contra los nombres de
            UNIQUES del mercado (no contra bases) para no caer en falsos positivos
            del tipo 'Quarterstaff' -> unique con base 'Long Quarterstaff'.
         b. Si no es unique, lo tratamos como RARE e inferimos clase/base por
            palabras clave, para que value() use los comparables del trade.

    Las stats (vida, res, MS, DPS, mods) ya las extrae parse_item_text aunque no haya
    separadores, asi que se conservan.
    """
    item = parse_item_text(text)
    if item.rarity != "Unknown":
        return item  # formato copiado: ya esta bien

    if market is not None:
        try:
            market.ensure_loaded()
        except Exception:
            pass

    raw = [clean_line(l) for l in (text or "").splitlines()]
    lines = [l for l in raw if l]
    if not lines:
        return item
    low_all = "\n".join(lines).lower()

    # (a) ¿es un unique? match del NOMBRE (primeras 1-2 lineas) contra nombres de uniques
    items = list(getattr(market, "_items", None) or []) if market is not None else []
    uniq_names = [str(it.get("Name")) for it in items if it.get("Name")]
    name_to_item = {_norm(str(it.get("Name"))): it for it in items if it.get("Name")}
    for cand in lines[:2]:
        if len(_norm(cand)) < 5:
            continue
        if _tm is not None and uniq_names:
            mn, score, _why = _tm.best_match(cand, uniq_names)
            if mn and score >= 0.9:
                m = name_to_item.get(_norm(mn))
                if m:
                    item.rarity = "Unique"
                    item.name = str(m.get("Name") or cand)
                    item.base_type = str(m.get("Type") or item.base_type)
                    item.category = infer_category(item)
                    return item

    # (b) no es unique: inferir base/clase por palabra clave y tratar como Rare
    base_kw = next((kw for kw in (WEAPON_KEYWORDS + ARMOUR_KEYWORDS + ACCESSORY_KEYWORDS)
                    if kw in low_all), None)
    if base_kw:
        item.item_class = base_kw.title()
        if not item.base_type:
            item.base_type = base_kw.title()
        item.rarity = "Rare"
        if not item.name:
            item.name = lines[0]
        item.category = infer_category(item)
        item.notes.append("Valorado desde imagen (OCR): rareza/base inferidas; "
                          "el Ctrl+C es mas preciso.")
    return item


# ======================================================================================
# Calidad de rolls: compara cada mod contra su tope (T1) para decir que tan "perfecto" es.
# Valores de referencia editables (PoE2 0.5 endgame, aprox). Ajustalos a tu gusto.
# Fuentes utiles para afinar numeros: pathofcrafting.net y craftofexile.com (game=poe2).
# ======================================================================================
MAX_ROLLS = {
    "fire_res": 45, "cold_res": 45, "lightning_res": 45, "chaos_res": 35,
    "movement_speed": 35, "spirit": 100, "mana": 120,
    "strength": 35, "dexterity": 35, "intelligence": 35, "all_attributes": 18,
    "skill_gem_levels": 3, "attack_speed": 27, "cast_speed": 27,
    "crit_chance_inc": 38, "spell_damage": 90, "physical_damage_inc": 165,
    "elemental_damage_inc": 60, "crit_damage_bonus": 40, "attack_damage_inc": 35,
    "increased_es_pct": 150, "increased_evasion_pct": 150, "increased_armour_pct": 150,
    "accuracy": 400, "added_elemental_damage": 250, "added_phys_damage": 60,
}
# Vida / ES dependen del slot: tope aproximado por pieza.
PERSLOT_LIFE = {"body": 125, "helmet": 100, "gloves": 90, "boots": 90,
                "ring": 50, "amulet": 60, "belt": 120}
PERSLOT_ES = {"body": 200, "helmet": 120, "gloves": 90, "boots": 90,
              "ring": 50, "amulet": 80, "belt": 40}
# Etiquetas que mostramos (orden) y su nombre legible.
_QUALITY_LABELS = [
    ("life", "vida"), ("fire_res", "res.fuego"), ("cold_res", "res.frío"),
    ("lightning_res", "res.rayo"), ("chaos_res", "res.caos"), ("movement_speed", "MS"),
    ("spirit", "spirit"), ("energy_shield_flat", "ES"), ("all_attributes", "todos atrib."),
    ("strength", "fuerza"), ("dexterity", "destreza"), ("intelligence", "inteligencia"),
    ("skill_gem_levels", "+gemas"), ("attack_speed", "vel.ataque"),
    ("crit_chance_inc", "crit"), ("spell_damage", "%hechizo"),
    ("physical_damage_inc", "%phys"), ("elemental_damage_inc", "%elem"), ("mana", "maná"),
    ("crit_damage_bonus", "crit dmg"), ("accuracy", "precisión"),
    ("added_elemental_damage", "dmg elem"), ("increased_es_pct", "%ES"),
]


def item_slot(item: ParsedItem) -> str | None:
    ic = (item.item_class or "").lower()
    for kw, key in (("boot", "boots"), ("glove", "gloves"), ("helmet", "helmet"), ("helm", "helmet"),
                    ("body", "body"), ("amulet", "amulet"), ("ring", "ring"), ("belt", "belt")):
        if kw in ic:
            return key
    if item.category == "weapon":
        return "weapon"
    if item.category == "boots":
        return "boots"
    return None


def _max_for(stat: str, slot: str | None) -> float:
    if stat == "life":
        return float(PERSLOT_LIFE.get(slot, 90))
    if stat == "energy_shield_flat":
        return float(PERSLOT_ES.get(slot, 80))
    return float(MAX_ROLLS.get(stat, 0))


def roll_quality(item: ParsedItem):
    """Devuelve (lista_de_(label,val,max,pct), promedio_pct) para los mods con tope conocido."""
    slot = item_slot(item)
    rows = []
    for stat, label in _QUALITY_LABELS:
        val = float(item.stats.get(stat, 0))
        if val <= 0:
            continue
        mx = _max_for(stat, slot)
        if mx <= 0:
            continue
        pct = min(100, round(val / mx * 100))
        rows.append((label, val, mx, pct))
    avg = round(sum(r[3] for r in rows) / len(rows)) if rows else 0
    return rows, avg


def roll_quality_text(item: ParsedItem) -> str:
    rows, avg = roll_quality(item)
    if not rows:
        return ""
    def tag(p):
        return "casi perfecto" if p >= 90 else ("alto" if p >= 70 else ("medio" if p >= 45 else "bajo"))
    parts = [f"{lbl} {val:g}/{mx:g} ({pct}% {tag(pct)})" for lbl, val, mx, pct in rows]
    return f"Calidad media {avg}% — " + "; ".join(parts)


def _norm(text: str) -> str:
    """Normaliza para matching: minusculas, sin acentos, espacios colapsados."""
    if not text:
        return ""
    text = text.lower().strip()
    repl = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n"))
    for a, b in repl:
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text)


def gold_decision(market_value_ex: float, threshold_ex: float) -> str:
    """Decide si conviene VENDER EN MERCADO u ORO (mercader) segun el valor en ex.

    Si el valor de mercado es menor al umbral configurable, no vale la pena
    listarlo: mejor convertirlo en oro con el mercader.
    """
    try:
        v = float(market_value_ex or 0.0)
        thr = float(threshold_ex or 0.0)
    except Exception:
        return ""
    if v <= 0:
        return "ORO"
    return "ORO" if v < thr else "MERCADO"


# Valores BASE aproximados de oro por mercader segun rareza (PoE2). NO hay API ni
# formula publica: el oro real depende de rareza, ilvl, mods e identificacion, asi
# que esto es solo una ESTIMACION orientativa (rango), claramente etiquetada.
_GOLD_BASE_BY_RARITY = {"Normal": 30, "Magic": 120, "Rare": 1200, "Unique": 1200}


def estimate_vendor_gold(item: "ParsedItem") -> str:
    """Estimacion aproximada (rango) del oro que da el mercader. Orientativa.

    Escala el valor base por rareza con el item level. Devuelve un texto tipo
    "~2.0k-3.2k oro (aprox)" o "" si no hay datos suficientes.
    """
    base = _GOLD_BASE_BY_RARITY.get(item.rarity, 0)
    if base <= 0:
        return ""
    ilvl = item.item_level or 0
    factor = 1.0 + min(max(ilvl, 0), 86) / 86.0 * 1.6  # ilvl 0->1.0x, 86->2.6x
    mid = base * factor
    lo, hi = mid * 0.8, mid * 1.2

    def _k(n: float) -> str:
        return f"{n/1000:.1f}k" if n >= 1000 else f"{int(round(n))}"

    return f"~{_k(lo)}-{_k(hi)} oro (aprox.)"


class MarketClient:
    """Cliente del mercado contra la API real de poe2scout.com.

    Usa:
      - GET /{realm}/Leagues                          -> liga current + DivinePrice (ex por divine)
      - GET /{realm}/Leagues/{league}/Items           -> dump completo (~1300 items) con CurrentPrice en exalted

    CurrentPrice siempre viene en Exalted Orb (moneda base). Para mostrar divine se usa DivinePrice.
    """

    def __init__(self, config: dict[str, Any], status_cb: Optional[Callable[[str], None]] = None):
        self.config = config
        self.status_cb = status_cb
        self._items: list[dict[str, Any]] | None = None
        self._index: dict[str, dict[str, Any]] = {}
        self._last_error: str = ""
        self._divine_price: float = 0.0          # exalted por 1 divine
        self._resolved_league: str = ""
        self._fetched_at: str = ""
        self._currency_ex: dict[str, float] = {"exalted": 1.0}

    def status(self, text: str) -> None:
        if self.status_cb:
            try:
                self.status_cb(text)
            except Exception:
                pass

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def divine_price(self) -> float:
        return self._divine_price

    @property
    def resolved_league(self) -> str:
        return self._resolved_league or str(self.config.get("league", "Runes of Aldur"))

    @property
    def fetched_at(self) -> str:
        return self._fetched_at

    @property
    def item_count(self) -> int:
        return len(self._items or [])

    # ---------- HTTP ----------
    def _get_json(self, url: str) -> Any:
        user_agent = str(self.config.get("user_agent", DEFAULT_CONFIG["user_agent"]))
        timeout = float(self.config.get("request_timeout", 8))
        req = urllib.request.Request(
            url, headers={"User-Agent": user_agent, "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)

    # ---------- liga + divine ----------
    def _resolve_league_and_divine(self, base: str, realm: str) -> None:
        """Detecta la liga current y el precio del divine en exalted."""
        configured = str(self.config.get("league", "Runes of Aldur")).strip()
        auto = bool(self.config.get("auto_detect_league", True))
        try:
            leagues = self._get_json(f"{base}/{realm}/Leagues")
        except Exception as exc:
            self._last_error = f"Leagues: {exc}"
            self._resolved_league = configured
            return
        if not isinstance(leagues, list):
            self._resolved_league = configured
            return

        chosen = None
        # 1) coincidencia exacta con la liga configurada
        for lg in leagues:
            if _norm(str(lg.get("Value"))) == _norm(configured):
                chosen = lg
                break
        # 2) si no aparece o auto-detect, usar la primera marcada IsCurrent (no hardcore)
        if chosen is None or auto and not chosen.get("IsCurrent"):
            currents = [lg for lg in leagues if lg.get("IsCurrent")]
            soft = [lg for lg in currents if not str(lg.get("Value", "")).lower().startswith(("hc ", "hardcore"))]
            if soft:
                chosen = soft[0]
            elif currents:
                chosen = currents[0]
            elif chosen is None and leagues:
                chosen = leagues[0]
        if chosen:
            self._resolved_league = str(chosen.get("Value") or configured)
            try:
                self._divine_price = float(chosen.get("DivinePrice") or 0.0)
            except Exception:
                self._divine_price = 0.0

    # ---------- cache ----------
    def _cache_is_fresh(self) -> bool:
        if not CACHE_PATH.exists():
            return False
        max_age = float(self.config.get("market_cache_minutes", 20)) * 60
        return (time.time() - CACHE_PATH.stat().st_mtime) < max_age

    def _load_cache_file(self) -> bool:
        try:
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                return False
            cached_realm = _norm(str(payload.get("realm", "")))
            current_realm = _norm(str(self.config.get("realm", "poe2")))
            if cached_realm != current_realm:
                return False
            # Si la liga cacheada no coincide con la configurada, solo la aceptamos en auto-detect.
            cached_league = str(payload.get("league", ""))
            configured = str(self.config.get("league", "Runes of Aldur"))
            if not self.config.get("auto_detect_league", True) and _norm(cached_league) != _norm(configured):
                return False
            self._items = payload["items"]
            self._divine_price = float(payload.get("divine_price") or 0.0)
            self._resolved_league = cached_league or configured
            self._fetched_at = str(payload.get("fetched_at", ""))
            self._build_index()
            return True
        except Exception:
            return False

    def _write_cache_file(self) -> None:
        try:
            payload = {
                "fetched_at": self._fetched_at or now_iso(),
                "realm": self.config.get("realm"),
                "league": self._resolved_league,
                "divine_price": self._divine_price,
                "items": self._items or [],
            }
            CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # ---------- index ----------
    def _build_index(self) -> None:
        self._index.clear()
        self._currency_ex = {"exalted": 1.0}
        if not self._items:
            return
        for it in self._items:
            name = it.get("Name")
            type_ = it.get("Type")
            keys = [it.get("Text"), name, type_, it.get("ApiId")]
            if name and type_:
                keys.append(f"{name} {type_}")
            for key in keys:
                if isinstance(key, str) and key.strip():
                    k = _norm(key)
                    # no pisar entradas ya existentes con bases genericas (Type compartido por varios uniques)
                    self._index.setdefault(k, it)
            if it.get("CategoryApiId") == "currency":
                # Registramos CADA currency bajo varias claves normalizadas (ApiId,
                # Text, Name y variantes con/sin "orb" y con guiones<->espacios) para
                # que currency_to_ex resuelva CUALQUIER codigo de moneda del trade
                # (divine, chaos, regal, vaal, annul, alch...) y no solo exalted.
                try:
                    price = float(it.get("CurrentPrice") or 0)
                except Exception:
                    price = 0.0
                if price > 0:
                    raw_keys = [it.get("ApiId"), it.get("Text"), it.get("Name")]
                    for rk in raw_keys:
                        if not rk:
                            continue
                        base = _norm(str(rk))
                        for variant in {
                            base,
                            base.replace(" orb", "").strip(),
                            base.replace("-", " ").strip(),
                            base.replace(" ", "-").strip(),
                            base.replace("-", " ").replace(" orb", "").strip(),
                        }:
                            if variant and variant not in self._currency_ex:
                                self._currency_ex[variant] = price
            # el nombre del unique tiene prioridad de match
            if name:
                self._index[_norm(name)] = it

    # ---------- carga principal ----------
    def ensure_loaded(self) -> None:
        if not self.config.get("enable_market_lookup", True):
            return
        if self._items is not None:
            return
        if self._cache_is_fresh() and self._load_cache_file():
            self.status(f"Mercado (caché): {self.item_count} items | {self.resolved_league}")
            return

        realm = str(self.config.get("realm", "poe2")).strip() or "poe2"
        bases = self.config.get("api_base_urls") or DEFAULT_CONFIG["api_base_urls"]
        errors: list[str] = []
        for base in bases:
            base = str(base).rstrip("/")
            try:
                self.status("Consultando poe2scout…")
                self._resolve_league_and_divine(base, realm)
                league = self._resolved_league or "Runes of Aldur"
                quoted = urllib.parse.quote(league, safe="")
                data = self._get_json(f"{base}/{realm}/Leagues/{quoted}/Items")
                if isinstance(data, list) and data:
                    self._items = [x for x in data if isinstance(x, dict)]
                    self._fetched_at = now_iso()
                    self._build_index()
                    # Respaldo opcional: rellena currencies faltantes desde poe.ninja.
                    if self.config.get("enable_poeninja_fallback", False):
                        try:
                            self._augment_currency_from_poeninja(league)
                        except Exception:
                            pass
                    self._write_cache_file()
                    self._last_error = ""
                    dp = f" | 1 div ≈ {self._divine_price:g} ex" if self._divine_price else ""
                    self.status(f"Mercado: {self.item_count} items | {league}{dp}")
                    return
                errors.append(f"{base}: respuesta vacía o inválida")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
        self._last_error = " | ".join(errors[-2:]) if errors else "No se pudo consultar mercado."
        if self._load_cache_file():
            self.status("Usando caché local (red no disponible).")
            return
        self.status("Mercado no disponible; usando heurística local.")

    def currency_to_ex(self, currency_id: str) -> float:
        """Convierte una moneda del trade (exalted/divine/chaos/regal/...) a exalted.

        IMPORTANTE: el trade oficial cotiza la mayoria de los rares valiosos en
        *divine*. Antes solo conociamos 'exalted' y dependiamos de que el ApiId
        de poe2scout coincidiera con el codigo del trade (p. ej. 'divine' vs
        'divine-orb'); cuando no coincidia devolviamos 0 y se DESCARTABAN todos
        los listings en divine -> precios artificialmente bajos (0-2 ex). Ahora
        resolvemos exalted y divine de forma directa y robusta.
        """
        if not currency_id:
            return 0.0
        cid = _norm(str(currency_id))
        # Exalted es la moneda base.
        if cid in ("exalted", "exalted orb", "ex", "exalt", "exa"):
            return 1.0
        # Divine: usamos el precio en ex que ya trae la liga (DivinePrice).
        if cid in ("divine", "divine orb", "div", "divine-orb") and self._divine_price > 0:
            return float(self._divine_price)
        # Resto de monedas: buscar en el indice de poe2scout, probando variantes
        # de nombre (con/sin ' orb', guiones <-> espacios).
        variants = {
            cid,
            cid.replace(" orb", "").strip(),
            cid.replace("-", " ").strip(),
            cid.replace(" ", "-").strip(),
            cid.replace("-", " ").replace(" orb", "").strip(),
        }
        for v in variants:
            val = self._currency_ex.get(v)
            if val:
                return float(val)
        return 0.0

    def _augment_currency_from_poeninja(self, league: str) -> None:
        """Respaldo OPCIONAL: rellena currencies que falten usando poe.ninja.

        Endpoint (poe2): /economy/currencyexchange/overview?leagueName=..&overviewName=Currency
        Respuesta: { "items": [{id, name, icon, tradeId}], "lines": [{<idKey>, ...valores}] }

        Estrategia segura:
          * Solo AÑADE claves que poe2scout no tenga (nunca pisa precios reales).
          * Indexa por `tradeId` (== codigo de moneda del trade) y por `name`.
          * El valor se toma del campo numerico mas plausible de cada linea, en
            relacion a exalted (moneda base de poe2). Es un respaldo: poe2scout
            sigue siendo la fuente primaria.

        NOTA: el formato exacto de `lines` de poe.ninja puede variar; por eso esto
        va detras de `enable_poeninja_fallback` y nunca rompe la carga (todo en
        try/except). Conviene una validacion en vivo la primera vez que se active.
        """
        base = str(self.config.get("poeninja_base_url", "https://poe.ninja/poe2/api")).rstrip("/")
        url = (f"{base}/economy/currencyexchange/overview"
               f"?leagueName={urllib.parse.quote(league)}&overviewName=Currency")
        data = self._get_json(url)
        if not isinstance(data, dict):
            return
        items = data.get("items") or data.get("currencyDetails") or []
        lines = data.get("lines") or []
        # Mapa idKey -> metadatos (tradeId/name)
        meta: dict[str, dict] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            key = str(it.get("id") if it.get("id") is not None else it.get("currencyTypeName") or "")
            if key:
                meta[key] = it

        def _line_value_ex(ln: dict) -> float:
            # Buscamos el primer campo numerico positivo plausible (en ex).
            for fld in ("primaryValue", "value", "chaosEquivalent", "exaltedValue", "secondaryValue"):
                try:
                    v = float(ln.get(fld))
                    if v > 0:
                        return v
                except Exception:
                    continue
            return 0.0

        added = 0
        for ln in lines:
            if not isinstance(ln, dict):
                continue
            idkey = str(ln.get("currencyTypeName") if ln.get("currencyTypeName") is not None
                        else ln.get("id") if ln.get("id") is not None else ln.get("itemId") or "")
            info = meta.get(idkey, {})
            trade_id = info.get("tradeId") or ln.get("tradeId")
            name = info.get("name") or info.get("currencyTypeName") or ln.get("name")
            value = _line_value_ex(ln)
            if value <= 0:
                continue
            for raw in (trade_id, name):
                if not raw:
                    continue
                k = _norm(str(raw))
                if k and k not in self._currency_ex:   # nunca pisa poe2scout
                    self._currency_ex[k] = value
                    added += 1
        if added:
            self.status(f"poe.ninja: +{added} tasas de currency de respaldo.")

    # ---------- búsqueda ----------
    def find_market_item(self, item: ParsedItem) -> dict[str, Any] | None:
        self.ensure_loaded()
        if not self._index:
            return None
        # 1) match exacto por nombre/base
        for name in item.searchable_names:
            match = self._index.get(_norm(name))
            if match:
                return match
        # 2) match exacto por "Name Base" combinado (uniques)
        if item.name and item.base_type:
            match = self._index.get(_norm(f"{item.name} {item.base_type}"))
            if match:
                return match
        # 3) match flexible y SEGURO: contencion por palabra completa + similitud
        #    acotada. Antes esto recorria el dict y devolvia el PRIMER key donde
        #    "lname in key or key in lname" — eso casaba parciales equivocados
        #    (un nombre corto contenido en otro mas largo no relacionado) y el
        #    resultado dependia del orden del diccionario. Ahora elegimos el mejor.
        keys = list(self._index.keys())
        for name in item.searchable_names:
            lname = _norm(name)
            if len(lname) < 4:
                continue
            if _tm is not None:
                cand, score, _why = _tm.best_match(lname, keys, min_len=4)
                if cand and score >= 0.9:  # exacto o contencion por palabra completa
                    return self._index[cand]
            else:
                # Respaldo sin text_match: solo contencion por palabra completa.
                for key in keys:
                    if lname == key:
                        return self._index[key]
                    if re.search(r"(?:^| )" + re.escape(lname) + r"(?: |$)", key) or \
                       re.search(r"(?:^| )" + re.escape(key) + r"(?: |$)", lname):
                        return self._index[key]
        return None


class HeuristicValuator:
    def __init__(self, config: dict[str, Any], market: MarketClient | None = None):
        self.config = config
        self.market = market
        self.currency_label = str(config.get("currency_label", "ex"))
        self.divine_label = str(config.get("divine_label", "div"))
        self.show_both = bool(config.get("show_both_currencies", True))
        self.trade = None  # TradeClient opcional (modo automatico)

    # ---------- formato de moneda (ex + div en vivo) ----------
    def _divine_price(self) -> float:
        if self.market and self.market.divine_price > 0:
            return self.market.divine_price
        try:
            return float(self.config.get("fallback_divine_price", 0) or 0)
        except Exception:
            return 0.0

    def _num(self, v: float) -> str:
        if v >= 100:
            return f"{v:,.0f}".replace(",", " ")
        if v >= 10:
            return f"{v:.0f}"
        if v >= 1:
            return f"{v:.1f}".rstrip("0").rstrip(".")
        return f"{v:.2f}".rstrip("0").rstrip(".")

    def _fmt(self, ex: float) -> str:
        """Formatea un valor en exalted, agregando el equivalente en divine cuando aplica."""
        c = self.currency_label
        if ex <= 0:
            return f"0 {c}"
        base = f"{self._num(ex)} {c}"
        dp = self._divine_price()
        if self.show_both and dp > 0:
            div = ex / dp
            if div >= 0.1:  # solo mostramos divine cuando el numero es legible
                return f"{base} ≈ {self._num(div)} {self.divine_label}"
        return base

    def _fmt_range(self, lo: float, hi: float) -> str:
        c = self.currency_label
        dp = self._divine_price()
        ex_part = f"{self._num(lo)}–{self._num(hi)} {c}"
        if self.show_both and dp > 0 and hi / dp >= 0.1:
            return f"{ex_part} ({self._num(lo / dp)}–{self._num(hi / dp)} {self.divine_label})"
        return ex_part

    def value(self, item: ParsedItem) -> ValuationResult:
        # Mercado para uniques/currency/gems con nombre directo.
        if item.rarity in {"Unique", "Currency", "Gem"} or item.category == "currency":
            market_result = self._try_market_value(item)
            if market_result:
                return market_result

        if item.rarity in {"Rare", "Magic"} and item.category != "currency" \
                and self.config.get("auto_trade_comparables") and self.trade:
            try:
                comp = self.trade.comparables(item)
            except Exception:
                comp = None
            if comp and comp.get("count"):
                return self._comparables_result(item, comp)

        if item.rarity == "Rare" or item.rarity == "Magic":
            if item.category == "weapon":
                return self._value_weapon(item)
            return self._value_rare_defensive_or_accessory(item)

        return ValuationResult(
            title=item.display_name,
            price_text="Revisar manual",
            quick_sell="—",
            fair_price="—",
            ambitious_price="—",
            confidence="baja",
            source="Parser local",
            reasons=["El ítem se pudo leer, pero no hay reglas suficientes todavía para esta categoría."],
            warnings=["Copia el texto completo con Ctrl+C y, si es rare, prueba con bases de joyería/armadura/armas para mejor estimación."],
        )

    def _try_market_value(self, item: ParsedItem) -> ValuationResult | None:
        if not self.market or not self.config.get("enable_market_lookup", True):
            return None
        try:
            match = self.market.find_market_item(item)
        except Exception:
            match = None
        if not match:
            return None
        # API real: CurrentPrice (exalted), Text/Name/Type, CategoryApiId
        price = float(match.get("CurrentPrice") or match.get("current_price") or 0)
        if price <= 0:
            return None
        name = match.get("Text") or match.get("Name") or item.display_name
        category = str(match.get("CategoryApiId") or "")
        is_unique = bool(item.rarity == "Unique" or (match.get("Name") and match.get("Type")))

        reasons = [
            f"Precio de mercado en vivo (poe2scout, liga {self.market.resolved_league}).",
            "Mediana de listings recientes; CurrentPrice expresado en Exalted Orbs.",
        ]
        warnings: list[str] = []
        # Uniques: el precio base puede variar mucho segun roll/variante.
        if is_unique:
            warnings.append("Uniques: el precio cambia según el roll y la variante; este es el valor base de referencia.")
            dp_ref = self.market.divine_price or 1
            if price >= dp_ref * 50:
                reasons.append("Precio alto: coincide con listings reales del trade oficial; confírmalo en trade antes de comprar/vender.")
            quick_factor, amb_factor = 0.8, 1.4
        elif category in {"currency", "runes", "essences", "fragments"}:
            reasons.append("Currency/objeto de stack: precio bastante líquido y confiable.")
            quick_factor, amb_factor = 0.92, 1.1
        else:
            quick_factor, amb_factor = 0.85, 1.3
        if item.corrupted:
            warnings.append("Está corrupto: el implicit puede subir o bajar mucho el precio real.")

        dp = self.market.divine_price
        dp_note = f"  |  1 {self.divine_label} ≈ {self._num(dp)} {self.currency_label}" if dp else ""
        return ValuationResult(
            title=str(name),
            price_text=self._fmt(price) + dp_note,
            quick_sell=self._fmt(max(price * quick_factor, 0.01)),
            fair_price=self._fmt(price),
            ambitious_price=self._fmt(price * amb_factor),
            confidence="alta" if category in {"currency", "runes", "essences"} else ("media-alta" if is_unique else "media"),
            source="poe2scout (mercado en vivo)",
            reasons=reasons,
            warnings=warnings,
            raw_market_match=match,
            market_value_ex=price,
        )

    def _comparables_result(self, item: ParsedItem, comp: dict) -> ValuationResult:
        """Construye el resultado usando precios reales de listings del trade oficial."""
        mn = float(comp.get("min_ex") or 0)
        med = float(comp.get("median_ex") or 0)
        count = int(comp.get("count") or 0)
        reasons = [
            f"Precio real del trade oficial: {count} listings comparables (online).",
            "Filtros por stats del ítem (vida, resistencias, MS, spirit, atributos, % phys).",
            "Mínimo = competidor más barato; mediana = precio típico de venta.",
        ]
        warnings = []
        if count < 3:
            warnings.append("Pocos comparables: el precio puede ser poco fiable; revisa el trade.")
        if item.corrupted:
            warnings.append("Corrupto: filtra por corrupted en el trade para comparar mejor.")
        return ValuationResult(
            title=item.display_name,
            price_text=self._fmt(med if med else mn),
            quick_sell=self._fmt(mn),
            fair_price=self._fmt(med if med else mn),
            ambitious_price=self._fmt(max(comp.get("max_ex") or 0, (med if med else mn) * 1.3)) + " (techo del rango)",
            confidence="alta" if count >= 5 else "media",
            source="Trade oficial (comparables en vivo)",
            reasons=reasons,
            warnings=warnings,
            raw_market_match={"comparables": comp, "IconUrl": comp.get("icon")},
            market_value_ex=float(med if med else mn),
        )

    # Anclas de precio en EXALTED por banda de score (lo, hi, quick, ambicioso)
    _PRICE_BANDS = (
        (18, (0, 2, 1, 4)),
        (35, (2, 8, 3, 14)),
        (55, (8, 25, 10, 40)),
        (75, (25, 70, 30, 110)),
        (100, (70, 180, 80, 280)),
        (10 ** 9, (180, 500, 200, 900)),
    )

    def _score_to_prices(self, score: float) -> tuple[str, str, str, str]:
        lo = hi = quick = amb = 0.0
        for threshold, (lo, hi, quick, amb) in self._PRICE_BANDS:
            if score < threshold:
                break
        price_text = self._fmt_range(lo, hi)
        quick_text = self._fmt(quick)
        fair_text = self._fmt_range(quick, hi)
        amb_text = self._fmt(amb) + (" (si hay demanda)" if score >= 75 else "")
        return price_text, quick_text, fair_text, amb_text

    def _score_to_value_ex(self, score: float) -> float:
        """Valor numerico de venta rapida (en ex) segun la banda de score.

        Sirve para la decision vender-en-mercado vs oro cuando no hay precio real
        (rares con heuristica local)."""
        lo = hi = quick = amb = 0.0
        for threshold, (lo, hi, quick, amb) in self._PRICE_BANDS:
            if score < threshold:
                break
        return float(quick)

    def _confidence(self, item: ParsedItem, score: float) -> str:
        hits = len(item.stats)
        if item.category == "unknown" or hits < 2:
            return "baja"
        if hits >= 6 and score >= 35:
            return "media-alta"
        return "media"

    def _value_rare_defensive_or_accessory(self, item: ParsedItem) -> ValuationResult:
        s = item.stats
        reasons: list[str] = []
        warnings: list[str] = []
        score = 0.0

        ilvl = item.item_level or 0
        if ilvl >= 82:
            score += 8; reasons.append(f"ilvl {ilvl}: buena base para rolls altos.")
        elif ilvl >= 75:
            score += 4; reasons.append(f"ilvl {ilvl}: aceptable para endgame temprano.")

        life = s.get("life", 0)
        if life >= 120:
            score += 34; reasons.append(f"Vida muy alta: +{life:g}.")
        elif life >= 90:
            score += 26; reasons.append(f"Buen roll de vida: +{life:g}.")
        elif life >= 60:
            score += 16; reasons.append(f"Vida útil: +{life:g}.")
        elif item.category in {"armour", "boots", "accessory"}:
            warnings.append("No detecté vida alta; eso suele bajar bastante el valor de rares defensivos.")

        elem_res = s.get("elemental_res_total", 0)
        total_res = s.get("total_res", 0)
        chaos = s.get("chaos_res", 0)
        if elem_res >= 120:
            score += 34; reasons.append(f"Resistencias elementales muy altas: {elem_res:g}% total.")
        elif elem_res >= 90:
            score += 26; reasons.append(f"Triple res/elemental fuerte: {elem_res:g}% total.")
        elif elem_res >= 60:
            score += 16; reasons.append(f"Resistencias útiles: {elem_res:g}% total.")
        elif elem_res >= 30:
            score += 8; reasons.append(f"Algo de resistencias: {elem_res:g}% total.")
        if chaos >= 35:
            score += 18; reasons.append(f"Chaos resistance alta: {chaos:g}%.")
        elif chaos >= 20:
            score += 10; reasons.append(f"Chaos resistance útil: {chaos:g}%.")
        if total_res >= 150:
            score += 10; reasons.append(f"Total res muy competitivo: {total_res:g}% incluyendo chaos.")

        ms = s.get("movement_speed", 0)
        if item.category == "boots":
            if ms >= 35:
                score += 35; reasons.append(f"Botas con movement speed excelente: {ms:g}%.")
            elif ms >= 25:
                score += 25; reasons.append(f"Botas con buen movement speed: {ms:g}%.")
            elif ms >= 15:
                score += 12; reasons.append(f"Movement speed usable: {ms:g}%.")
            else:
                score -= 12; warnings.append("Botas sin movement speed detectado: difícil vender salvo mods muy buenos.")

        rarity = s.get("item_rarity", 0)
        if rarity >= 40:
            score += 20; reasons.append(f"Item rarity alta: {rarity:g}%.")
        elif rarity >= 20:
            score += 10; reasons.append(f"Item rarity vendible: {rarity:g}%.")

        spirit = s.get("spirit", 0)
        if spirit >= 40:
            score += 28; reasons.append(f"Spirit alto: +{spirit:g}; stat muy buscado en varias builds.")
        elif spirit >= 20:
            score += 16; reasons.append(f"Spirit útil: +{spirit:g}.")

        gem = s.get("skill_gem_levels", 0)
        if gem >= 3:
            score += 45; reasons.append(f"+{gem:g} niveles de skills/gemas: revisar manual, puede disparar precio.")
        elif gem >= 2:
            score += 32; reasons.append(f"+{gem:g} niveles de skills/gemas: mod premium.")
        elif gem >= 1:
            score += 18; reasons.append("+1 nivel de skills/gemas: mod relevante.")

        attrs = s.get("attributes_total", 0)
        if attrs >= 100:
            score += 18; reasons.append(f"Muchos atributos: {attrs:g} total aprox.")
        elif attrs >= 60:
            score += 10; reasons.append(f"Atributos útiles: {attrs:g} total aprox.")

        mana = s.get("mana", 0)
        if mana >= 120:
            score += 10; reasons.append(f"Maná alto: +{mana:g}, útil para builds concretas.")
        elif mana >= 70:
            score += 5; reasons.append(f"Maná útil: +{mana:g}.")

        if s.get("rune_sockets", 0) >= 2:
            score += 12; reasons.append("Tiene 2 rune sockets detectados.")
        elif s.get("rune_sockets", 0) == 1:
            score += 5; reasons.append("Tiene 1 rune socket detectado.")

        if item.corrupted:
            score -= 6; warnings.append("Corrupto: puede ser peor o mejor según implicit; revisar si el resultado es especial.")
        if item.unidentified:
            warnings.append("Sin identificar: no se puede valorar bien hasta identificarlo.")
            score = min(score, 10)

        if not reasons:
            reasons.append("No detecté mods premium claros en el texto copiado.")
        try:
            _rows, _avgq = roll_quality(item)
            if _avgq:
                score += (_avgq - 60) * 0.25
                reasons.append(f"Calidad de rolls: {_avgq}% del tope.")
        except Exception:
            pass
        score = max(score, 0)
        price_text, quick, fair, ambitious = self._score_to_prices(score)
        return ValuationResult(
            title=item.display_name,
            price_text=price_text,
            quick_sell=quick,
            fair_price=fair,
            ambitious_price=ambitious,
            confidence=self._confidence(item, score),
            source="Heurística local v0.1",
            score=round(score, 1),
            reasons=reasons[:8],
            warnings=warnings[:6],
            market_value_ex=self._score_to_value_ex(score),
        )

    def _value_weapon(self, item: ParsedItem) -> ValuationResult:
        s = item.stats
        reasons: list[str] = []
        warnings: list[str] = []
        score = 0.0

        total_dps = s.get("total_dps", 0)
        pdps = s.get("pdps", 0)
        edps = s.get("edps", 0)
        if total_dps >= 650:
            score += 90; reasons.append(f"DPS total muy alto detectado: {total_dps:g}.")
        elif total_dps >= 500:
            score += 68; reasons.append(f"DPS total alto: {total_dps:g}.")
        elif total_dps >= 350:
            score += 45; reasons.append(f"DPS total decente: {total_dps:g}.")
        elif total_dps >= 250:
            score += 25; reasons.append(f"DPS usable: {total_dps:g}.")
        elif total_dps:
            score += 10; reasons.append(f"DPS bajo/medio: {total_dps:g}.")

        if pdps:
            reasons.append(f"pDPS aprox: {pdps:g}.")
        if edps:
            reasons.append(f"eDPS aprox: {edps:g}.")

        inc_phys = s.get("physical_damage_inc", 0)
        if inc_phys >= 170:
            score += 30; reasons.append(f"% physical damage muy alto: {inc_phys:g}%.")
        elif inc_phys >= 100:
            score += 18; reasons.append(f"% physical damage bueno: {inc_phys:g}%.")

        atk = s.get("attack_speed", 0)
        if atk >= 25:
            score += 22; reasons.append(f"Attack speed alto: {atk:g}%.")
        elif atk >= 12:
            score += 12; reasons.append(f"Attack speed útil: {atk:g}%.")

        gem = s.get("skill_gem_levels", 0)
        if gem >= 2:
            score += 35; reasons.append(f"+{gem:g} niveles de skills/gemas: puede ser premium según base.")
        elif gem >= 1:
            score += 18; reasons.append("+1 nivel de skills/gemas: mod relevante.")

        spell = s.get("spell_damage", 0)
        if spell >= 90:
            score += 28; reasons.append(f"Spell damage alto: {spell:g}%.")
        elif spell >= 50:
            score += 14; reasons.append(f"Spell damage útil: {spell:g}%.")

        crit = s.get("crit_chance_inc", 0)
        if crit >= 80:
            score += 14; reasons.append(f"Critical chance aumentado alto: {crit:g}%.")
        elif crit >= 40:
            score += 7; reasons.append(f"Critical chance aumentado útil: {crit:g}%.")

        if item.item_level and item.item_level >= 82:
            score += 6; reasons.append(f"ilvl {item.item_level}: buena base de crafting.")
        if item.quality and item.quality >= 20:
            score += 4; reasons.append(f"Calidad {item.quality}%.")
        if item.corrupted:
            score -= 5; warnings.append("Corrupta: menos flexible para craft; revisar si el implicit compensa.")

        if not total_dps and not gem and not spell:
            warnings.append("No detecté DPS/skill levels/spell damage; la valoración de arma queda floja.")
        if not reasons:
            reasons.append("No detecté mods ofensivos premium claros.")

        try:
            _rows, _avgq = roll_quality(item)
            if _avgq:
                score += (_avgq - 60) * 0.25
                reasons.append(f"Calidad de rolls: {_avgq}% del tope.")
        except Exception:
            pass
        score = max(score, 0)
        price_text, quick, fair, ambitious = self._score_to_prices(score)
        return ValuationResult(
            title=item.display_name,
            price_text=price_text,
            quick_sell=quick,
            fair_price=fair,
            ambitious_price=ambitious,
            confidence=self._confidence(item, score),
            source="Heurística local v0.1 para armas",
            score=round(score, 1),
            reasons=reasons[:8],
            warnings=warnings[:6],
            market_value_ex=self._score_to_value_ex(score),
        )


def append_history(item: ParsedItem, valuation: ValuationResult) -> None:
    try:
        payload = {
            "time": now_iso(),
            "item": {
                "item_class": item.item_class,
                "rarity": item.rarity,
                "name": item.name,
                "base_type": item.base_type,
                "item_level": item.item_level,
                "category": item.category,
                "stats": item.stats,
                "corrupted": item.corrupted,
                "unidentified": item.unidentified,
            },
            "valuation": {
                "price_text": valuation.price_text,
                "quick_sell": valuation.quick_sell,
                "fair_price": valuation.fair_price,
                "ambitious_price": valuation.ambitious_price,
                "confidence": valuation.confidence,
                "score": valuation.score,
                "source": valuation.source,
                "reasons": valuation.reasons,
                "warnings": valuation.warnings,
            },
            "build": {
                "fit": valuation.build_fit,
                "verdict": valuation.build_verdict,
                "matched": valuation.build_reasons,
                "compare": valuation.compare_text,
            } if valuation.build_fit is not None else None,
            "market": {
                "matched_name": (valuation.raw_market_match or {}).get("Text"),
                "current_price_ex": (valuation.raw_market_match or {}).get("CurrentPrice"),
                "category_api_id": (valuation.raw_market_match or {}).get("CategoryApiId"),
            } if valuation.raw_market_match else None,
            # Campos manuales para calibración futura (rellenar a mano):
            "feedback": {"listed_price": None, "sold_price": None, "sold_after_hours": None, "notes": ""},
        }
        with HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass



# ===================== Trade oficial PoE2 (busqueda asistida) =====================
TRADE2_API = "https://www.pathofexile.com/api/trade2/search/poe2/"
TRADE2_WEB = "https://www.pathofexile.com/trade2/search/poe2/"
TRADE2_FETCH = "https://www.pathofexile.com/api/trade2/fetch/"

_WEAPON_CLASS_TO_CAT = {
    "crossbow": "weapon.crossbow", "bow": "weapon.bow", "wand": "weapon.wand",
    "sceptre": "weapon.sceptre", "scepter": "weapon.sceptre",
    "quarterstave": "weapon.warstaff", "quarterstaff": "weapon.warstaff",
    "spear": "weapon.spear", "flail": "weapon.flail",
    "one hand sword": "weapon.onesword", "two hand sword": "weapon.twosword",
    "one hand axe": "weapon.oneaxe", "two hand axe": "weapon.twoaxe",
    "one hand mace": "weapon.onemace", "two hand mace": "weapon.twomace",
    "dagger": "weapon.dagger", "claw": "weapon.claw",
    "stave": "weapon.staff", "staff": "weapon.staff",
}
_ARMOUR_CLASS_TO_CAT = {
    "helmet": "armour.helmet", "gloves": "armour.gloves", "boots": "armour.boots",
    "body armour": "armour.chest", "shield": "armour.shield", "focus": "armour.focus",
    "quiver": "armour.quiver", "buckler": "armour.buckler",
}
_ACCESSORY_CLASS_TO_CAT = {
    "ring": "accessory.ring", "amulet": "accessory.amulet", "belt": "accessory.belt",
}
# stat interno -> (id trade2, factor de relajacion del minimo para hallar comparables)
_STAT_TO_TRADE2 = {
    "life": ("pseudo.pseudo_total_life", 0.9),
    "elemental_res_total": ("pseudo.pseudo_total_elemental_resistance", 0.9),
    "chaos_res": ("explicit.stat_2923486259", 0.9),
    "movement_speed": ("explicit.stat_2250533757", 1.0),
    "spirit": ("explicit.stat_3981240776", 0.9),
    "attributes_total": ("pseudo.pseudo_total_all_attributes", 0.85),
    "physical_damage_inc": ("explicit.stat_1509134228", 0.9),
}


def trade2_category(item: "ParsedItem") -> str | None:
    cls = (item.item_class or "").lower()
    if item.category == "boots":
        return "armour.boots"
    for table in (_ARMOUR_CLASS_TO_CAT, _ACCESSORY_CLASS_TO_CAT, _WEAPON_CLASS_TO_CAT):
        for key, cat in table.items():
            if key in cls:
                return cat
    return {"weapon": "weapon", "armour": "armour", "accessory": "accessory",
            "boots": "armour.boots", "jewel": "jewel"}.get(item.category)


def build_trade2_query(item: "ParsedItem") -> dict | None:
    """Arma la query del trade2 oficial a partir de los stats detectados del rare."""
    stat_filters: list[dict] = []
    for stat, (sid, relax) in _STAT_TO_TRADE2.items():
        v = item.stats.get(stat, 0)
        if v and v > 0:
            stat_filters.append({"id": sid, "value": {"min": max(1, int(v * relax))}, "disabled": False})
    has_dps = bool(item.stats.get("pdps") or item.stats.get("edps") or item.stats.get("total_dps"))
    if not stat_filters and not has_dps:
        return None
    cat = trade2_category(item)
    type_filters: dict = {"filters": {"rarity": {"option": "nonunique"}}}
    if cat:
        type_filters["filters"]["category"] = {"option": cat}
    filters: dict = {"type_filters": type_filters}
    # Armas: filtra por DPS (equipment_filters) para hallar comparables relevantes.
    pdps = item.stats.get("pdps", 0)
    edps = item.stats.get("edps", 0)
    total_dps = item.stats.get("total_dps", 0)
    eq: dict = {}
    if pdps:
        eq["pdps"] = {"min": int(pdps * 0.85)}
    if edps:
        eq["edps"] = {"min": int(edps * 0.85)}
    if not eq and total_dps:
        eq["dps"] = {"min": int(total_dps * 0.85)}
    if eq:
        filters["equipment_filters"] = {"filters": eq}
    query: dict = {
        "query": {"status": {"option": "online"}, "filters": filters},
        "sort": {"price": "asc"},
    }
    if stat_filters:
        query["query"]["stats"] = [{"type": "and", "filters": stat_filters}]
    return query


class TradeClient:
    """Consulta el trade oficial de PoE2 para traer precios reales de comparables (modo automatico).
    Hace 2 llamadas por item (search + fetch), con throttle y cache para respetar los rate limits."""

    def __init__(self, config: dict, market: "MarketClient", status_cb=None):
        self.config = config
        self.market = market
        self.status_cb = status_cb
        self._last_call = 0.0
        self._cache: dict = {}
        self._cooldown_until = 0.0

    def _status(self, t: str) -> None:
        if self.status_cb:
            try:
                self.status_cb(t)
            except Exception:
                pass

    def _throttle(self) -> None:
        gap = float(self.config.get("trade_min_interval_s", 2.5))
        dt = time.time() - self._last_call
        if dt < gap:
            time.sleep(gap - dt)
        self._last_call = time.time()

    def _ua(self) -> str:
        return str(self.config.get("user_agent", DEFAULT_CONFIG["user_agent"]))

    def _post_json(self, url: str, body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={
            "User-Agent": self._ua(), "Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))

    def _get_json(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": self._ua(), "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))

    def comparables(self, item: ParsedItem, league: str | None = None) -> dict | None:
        league = league or self.market.resolved_league or str(self.config.get("league", "Runes of Aldur"))
        if time.time() < self._cooldown_until:
            self._status("Trade en cooldown por rate limit; usando heurística.")
            return None
        query = build_trade2_query(item)
        if not query:
            return None
        sig = (league, item.category, tuple(sorted((k, round(v)) for k, v in item.stats.items())))
        cached = self._cache.get(sig)
        if cached and (time.time() - cached[0]) < 600:
            return cached[1]
        ql = urllib.parse.quote(league)
        try:
            self._status("Consultando comparables en el trade oficial…")
            self._throttle()
            search = self._post_json(f"{TRADE2_API}{ql}", query)
            hashes = (search.get("result") or [])[:10]
            sid = search.get("id")
            if not hashes or not sid:
                res = {"count": 0}
                self._cache[sig] = (time.time(), res)
                return res
            self._throttle()
            fetched = self._get_json(f"{TRADE2_FETCH}{','.join(hashes)}?query={sid}&realm=poe2")
            prices_ex: list[float] = []
            icon_url = None
            for r in (fetched.get("result") or []):
                pr = ((r or {}).get("listing") or {}).get("price") or {}
                amt = pr.get("amount")
                cur = pr.get("currency")
                # Captura el icono de un comparable (misma base = mismo arte) para
                # mostrar miniatura tambien en rares, que no tienen match en poe2scout.
                if icon_url is None:
                    icon_url = ((r or {}).get("item") or {}).get("icon")
                if amt is None or not cur:
                    continue
                exv = self.market.currency_to_ex(cur)
                if exv > 0:
                    prices_ex.append(float(amt) * exv)
            if not prices_ex:
                res = {"count": 0}
                self._cache[sig] = (time.time(), res)
                return res
            prices_ex.sort()
            mid = len(prices_ex) // 2
            median = prices_ex[mid] if len(prices_ex) % 2 else (prices_ex[mid - 1] + prices_ex[mid]) / 2
            res = {"count": len(prices_ex), "min_ex": prices_ex[0], "median_ex": median,
                   "max_ex": prices_ex[-1], "total_listed": len(search.get("result") or []),
                   "icon": icon_url}
            self._cache[sig] = (time.time(), res)
            return res
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry = 30
                try:
                    retry = int(exc.headers.get("Retry-After", "30"))
                except Exception:
                    pass
                self._cooldown_until = time.time() + retry
                self._status(f"Trade oficial: rate limit (429). Reintenta en ~{retry}s.")
            else:
                self._status(f"Trade oficial error {exc.code}.")
            return None
        except Exception as exc:
            self._status(f"No pude consultar comparables ({exc}).")
            return None


class BuildAdvisor:
    """Lee un .build de poe.ninja y juzga si un item aporta a esa build (afinidad por mods)."""

    GEAR = {"weapon", "boots", "armour", "accessory", "jewel"}

    def __init__(self, config: dict, status_cb=None):
        self.config = config
        self.status_cb = status_cb
        self.profile: dict | None = None
        self.equipped: dict[str, list] = {}
        self.load(self.config.get("build_file", ""))

    def _status(self, t: str) -> None:
        if self.status_cb:
            try:
                self.status_cb(t)
            except Exception:
                pass

    def load(self, path: str) -> bool:
        self.profile = None
        if not path or not _derive_build_profile:
            return False
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.profile = _derive_build_profile(data)
            self.equipped = self._parse_equipped(data)
            self.config["build_file"] = path
            n = sum(len(v) for v in self.equipped.values())
            self._status(f"Build cargada: {self.profile['name']} ({self.profile['weapon'] or '—'}) · {n} items equipados")
            return True
        except Exception as exc:
            self._status(f"No pude leer la build: {exc}")
            return False

    def advise(self, item: ParsedItem) -> dict | None:
        p = self.profile
        if not p:
            return None
        if item.category in {"currency", "waystone", "gem"}:
            return None
        if item.category not in self.GEAR and item.rarity not in {"Rare", "Magic", "Unique"}:
            return None
        s = item.stats
        themes = set(p.get("themes", []))
        attrs = set(p.get("attrs", []))
        weapon = p.get("weapon")
        matched: list[str] = []
        irrelevant: list[str] = []
        score = 0.0
        atk_build = bool({"attack", "spear", "projectile"} & themes) or item.category == "weapon"

        life = s.get("life", 0)
        if life:
            score += min(life, 150) / 150 * 25; matched.append(f"Vida +{life:g}")
        res = s.get("total_res", 0)
        if res:
            score += min(res, 150) / 150 * 22; matched.append(f"Resistencias {res:g}%")
        ms = s.get("movement_speed", 0)
        if ms and item.category == "boots":
            score += 18; matched.append(f"Movement speed {ms:g}%")
        if s.get("spirit"):
            score += 12; matched.append(f"Spirit +{s['spirit']:g}")
        if s.get("all_attributes"):
            score += 8; matched.append("Todos los atributos")
        if s.get("dexterity") and "dex" in attrs:
            score += 8; matched.append("Destreza")
        if s.get("intelligence") and "int" in attrs:
            score += 8; matched.append("Inteligencia")
        if s.get("strength") and "str" in attrs:
            score += 8; matched.append("Fuerza")
        if s.get("skill_gem_levels"):
            score += 14; matched.append(f"+{s['skill_gem_levels']:g} niveles de gemas")
        if s.get("attack_speed") and (atk_build or "speed" in themes):
            score += 12; matched.append("Velocidad de ataque")
        if s.get("crit_chance_inc") and "crit" in themes:
            score += 12; matched.append("Probabilidad crítica")
        if s.get("physical_damage_inc") and atk_build:
            score += 8; matched.append("% daño físico")
        if s.get("elemental_damage_inc") and bool({"elemental", "cold", "lightning", "fire"} & themes):
            score += 8; matched.append("% daño elemental")
        if s.get("item_rarity"):
            score += 5; matched.append("Rareza de objetos")

        # Desajustes claros
        if s.get("spell_damage") and atk_build:
            irrelevant.append("Daño de hechizo (tu build es de ataque)")
        if s.get("cast_speed") and atk_build:
            irrelevant.append("Velocidad de lanzamiento (build de ataque)")
        if s.get("strength") and "str" not in attrs:
            irrelevant.append("Fuerza (no es tu atributo)")

        # Arma: clase correcta o no
        if item.category == "weapon":
            ic = (item.item_class or "").lower()
            if weapon and weapon.lower().rstrip("s") in ic:
                score += 30; matched.append(f"Arma de tu clase ({weapon})")
            elif weapon:
                score -= 25; irrelevant.append(f"Arma de otra clase: usas {weapon}")

        score = max(0.0, min(100.0, score))
        if score >= 55:
            verdict = "✓ SIRVE PARA TU BUILD"
        elif score >= 30:
            verdict = "~ POSIBLE: compara con lo que llevas"
        else:
            verdict = "✗ NO APORTA A TU BUILD"
        return {"fit": round(score, 1), "verdict": verdict, "matched": matched, "irrelevant": irrelevant}

    # ---------- comparacion vs equipado ----------
    _SLOT_LABEL = {"weapon": "arma", "helmet": "casco", "body": "pechera", "gloves": "guantes",
                   "boots": "botas", "amulet": "amuleto", "ring": "anillo", "belt": "cinturón"}
    # stat -> (etiqueta, peso). Peso aproximado de importancia para el veredicto global.
    _CMP_STATS = {
        "life": ("vida", 1.0), "total_res": ("resist.", 1.0), "chaos_res": ("res.caos", 1.2),
        "energy_shield_flat": ("ES", 0.6), "movement_speed": ("MS", 4.0), "spirit": ("spirit", 1.5),
        "attributes_total": ("atrib.", 0.3), "mana": ("maná", 0.25),
        "attack_speed": ("vel.ataque", 2.0), "crit_chance_inc": ("crit", 1.5),
        "skill_gem_levels": ("+gemas", 18.0), "physical_damage_inc": ("%phys", 0.5),
        "elemental_damage_inc": ("%elem", 0.5), "spell_damage": ("%hechizo", 0.5),
        "item_rarity": ("rareza", 0.4), "crit_damage_bonus": ("crit dmg", 0.6),
        "added_elemental_damage": ("dmg elem", 0.15), "added_phys_damage": ("dmg phys", 0.3),
        "accuracy": ("precisión", 0.05), "increased_es_pct": ("%ES", 0.4),
    }

    @staticmethod
    def _slot_from_invid(iid: str):
        s = (iid or "").lower()
        for pre, key in (("weapon", "weapon"), ("helm", "helmet"), ("bodyarmour", "body"),
                         ("body", "body"), ("glove", "gloves"), ("boot", "boots"),
                         ("amulet", "amulet"), ("ring", "ring"), ("belt", "belt")):
            if s.startswith(pre):
                return key
        return None

    @staticmethod
    def _slot_from_item(item: ParsedItem):
        ic = (item.item_class or "").lower()
        for kw, key in (("boot", "boots"), ("glove", "gloves"), ("helmet", "helmet"), ("helm", "helmet"),
                        ("body", "body"), ("amulet", "amulet"), ("ring", "ring"), ("belt", "belt")):
            if kw in ic:
                return key
        if item.category == "weapon":
            return "weapon"
        if item.category == "boots":
            return "boots"
        return None

    def _parse_equipped(self, data: dict) -> dict:
        out: dict[str, list] = {}
        for sslot in (data.get("inventory_slots") or []):
            txt = (sslot.get("additional_text", "") or "").strip()
            if not txt:
                continue
            slot = self._slot_from_invid(str(sslot.get("inventory_id", "")))
            if not slot:
                continue
            lines = txt.split("\n")
            name = lines[0].strip()
            mods = [re.sub(r"^\s*\d+\.\s*", "", l).strip() for l in lines[1:] if l.strip()]
            block = "Item Class: Equipped\nRarity: Rare\n{0}\n{0}\n--------\nItem Level: 80\n--------\n{1}".format(
                name, "\n".join(mods))
            try:
                parsed = parse_item_text(block)
                out.setdefault(slot, []).append({"name": name, "stats": parsed.stats})
            except Exception:
                pass
        return out

    def _score_stats(self, stats: dict) -> float:
        return sum(float(stats.get(k, 0)) * w for k, (_lbl, w) in self._CMP_STATS.items())

    def compare(self, item: ParsedItem):
        slot = self._slot_from_item(item)
        if not slot or slot not in self.equipped or not self.equipped[slot]:
            return None
        # Anillos/slots con 2 piezas: comparar contra la mas debil (la que reemplazarias).
        target = min(self.equipped[slot], key=lambda t: self._score_stats(t["stats"]))
        eq = target["stats"]
        gains, losses = [], []
        for k, (lbl, _w) in self._CMP_STATS.items():
            a = float(item.stats.get(k, 0)); b = float(eq.get(k, 0))
            d = a - b
            thr = 1 if k == "skill_gem_levels" else 4
            if abs(d) < thr:
                continue
            (gains if d > 0 else losses).append(f"{'+' if d > 0 else ''}{d:g} {lbl}")
        net = self._score_stats(item.stats) - self._score_stats(eq)
        verdict = "MEJOR" if net > 6 else ("SIMILAR" if net >= -6 else "PEOR")
        return {"slot": slot, "name": target["name"], "verdict": verdict,
                "gains": gains[:5], "losses": losses[:5], "net": round(net, 1)}

    def compare_text(self, item: ParsedItem) -> str:
        c = self.compare(item)
        if not c:
            return ""
        label = self._SLOT_LABEL.get(c["slot"], c["slot"])
        parts = [f"vs tu {label} ({c['name']}): {c['verdict']}"]
        if c["gains"]:
            parts.append("gana " + ", ".join(c["gains"]))
        if c["losses"]:
            parts.append("pierde " + ", ".join(c["losses"]))
        return "  ·  ".join(parts)

    def annotate(self, item: ParsedItem, result: ValuationResult) -> None:
        adv = self.advise(item)
        if not adv:
            return
        result.build_fit = adv["fit"]
        result.build_verdict = adv["verdict"]
        result.build_reasons = adv["matched"]
        result.build_irrelevant = adv["irrelevant"]
        try:
            result.compare_text = self.compare_text(item)
        except Exception:
            result.compare_text = ""



class RuneAdvisorMixin:
    """Anade el asesor de recompensas de runas a las dos UIs (clasica y moderna).

    Requiere que la clase tenga: self.root, self.market y un metodo de estado
    (set_status_threadsafe o set_status). Funciona con o sin customtkinter.
    """

    # ---- estado / utilidades ----
    def _rune_status(self, text):
        for name in ("set_status_threadsafe", "set_status"):
            fn = getattr(self, name, None)
            if callable(fn):
                try:
                    fn(text)
                    return
                except Exception:
                    pass

    def _rune_ready(self):
        if _rune_reward is None:
            self._rune_popup("No encuentro rune_reward.py junto a la app.\n"
                             "Copialo en la misma carpeta que el ejecutable.")
            return False
        ok, _eng = _rune_reward.ocr_available()
        if not ok:
            self._rune_popup(
                "OCR no disponible todavia.\n\n"
                "Esta funcion usa el OCR nativo de Windows (paquete pip 'winsdk').\n"
                "Cierra la app y ejecuta run_windows.bat otra vez para instalarlo,\n"
                "o instala manualmente:  pip install winsdk\n\n"
                "(Alternativa: instalar Tesseract + 'pip install pytesseract'.)"
            )
            return False
        return True

    # ---- acciones de los botones ----
    def read_rune_image(self):
        if not self._rune_ready():
            return
        try:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                title="Elige la captura de las recompensas de runa",
                filetypes=[("Imagenes", "*.png *.jpg *.jpeg *.bmp *.webp"), ("Todos", "*.*")],
            )
        except Exception:
            path = ""
        if not path:
            return
        self._rune_status("Leyendo imagen de runas...")
        threading.Thread(target=self._rune_worker, args=(path,), daemon=True).start()

    def capture_rune_screen(self):
        # F8 / boton Captura: abre un selector de area (recorte) y analiza esa zona.
        if not self._rune_ready():
            return
        self._capture_target = self._rune_worker
        try:
            self._start_region_select()
        except Exception as exc:
            self._rune_popup(f"No pude abrir el selector de area: {exc}")

    def _start_region_select(self):
        sel = tk.Toplevel(self.root)
        try:
            sel.attributes("-fullscreen", True)
        except Exception:
            sel.geometry(f"{sel.winfo_screenwidth()}x{sel.winfo_screenheight()}+0+0")
        try:
            sel.attributes("-alpha", 0.25)
            sel.attributes("-topmost", True)
        except Exception:
            pass
        sel.configure(bg="black")
        sel.config(cursor="crosshair")
        canvas = tk.Canvas(sel, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(sel.winfo_screenwidth() // 2, 40,
                           text="Arrastra para seleccionar el area · ESC para cancelar",
                           fill="#ffd36b", font=("Segoe UI", 16, "bold"))
        st = {"x": 0, "y": 0, "rect": None}

        def on_down(e):
            st["x"], st["y"] = e.x, e.y
            st["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#ffd36b", width=2)

        def on_move(e):
            if st["rect"] is not None:
                canvas.coords(st["rect"], st["x"], st["y"], e.x, e.y)

        def cancel(_=None):
            try:
                sel.destroy()
            except Exception:
                pass

        def on_up(e):
            x1, y1 = min(st["x"], e.x), min(st["y"], e.y)
            x2, y2 = max(st["x"], e.x), max(st["y"], e.y)
            try:
                sel.destroy()
            except Exception:
                pass
            if (x2 - x1) < 6 or (y2 - y1) < 6:
                self._rune_status("Seleccion muy pequena, cancelada.")
                return
            self._grab_region_and_run((x1, y1, x2, y2))

        canvas.bind("<ButtonPress-1>", on_down)
        canvas.bind("<B1-Motion>", on_move)
        canvas.bind("<ButtonRelease-1>", on_up)
        sel.bind("<Escape>", cancel)
        sel.focus_force()

    def _grab_region_and_run(self, bbox):
        # Oculta el overlay para que no salga en la captura, espera y captura el area.
        self._rune_status("Capturando area...")
        try:
            self.root.withdraw()
        except Exception:
            pass

        # Escala logica (Tk) -> fisica (pixeles reales), para pantallas con DPI 125/150%
        try:
            sw = max(1, self.root.winfo_screenwidth())
            sh = max(1, self.root.winfo_screenheight())
        except Exception:
            sw = sh = 0

        def work():
            try:
                from PIL import ImageGrab
                full = ImageGrab.grab()  # pantalla completa en pixeles fisicos
                fx = (full.width / sw) if sw else 1.0
                fy = (full.height / sh) if sh else 1.0
                x1, y1, x2, y2 = bbox
                box = (int(x1 * fx), int(y1 * fy), int(x2 * fx), int(y2 * fy))
                # recorte seguro dentro de los limites
                box = (max(0, box[0]), max(0, box[1]),
                       min(full.width, box[2]), min(full.height, box[3]))
                if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                    img = full  # seleccion rara: usa pantalla completa como respaldo
                else:
                    img = full.crop(box)
            except Exception as exc:
                self.root.after(0, lambda: (self._safe_deiconify(),
                                            self._rune_popup(f"No pude capturar el area: {exc}")))
                return
            self.root.after(0, self._safe_deiconify)
            getattr(self, "_capture_target", self._rune_worker)(img)

        self.root.after(220, lambda: threading.Thread(target=work, daemon=True).start())

    def _safe_deiconify(self):
        try:
            self.root.deiconify()
            self.root.lift()
        except Exception:
            pass

    # ---- nucleo ----
    def _rune_worker(self, image_or_path):
        try:
            analysis = _rune_reward.analyze_image(image_or_path, self.market)
        except Exception as exc:
            err = "Error analizando runas:\n" + "".join(
                traceback.format_exception_only(type(exc), exc))
            self.root.after(0, lambda: self._rune_popup(err))
            return
        self.root.after(0, lambda: self._rune_status("Recompensas analizadas."))
        self.root.after(0, lambda: self._show_rune_window(analysis, image_or_path))

    # ============================================================================
    # Valorar ITEM por captura (imagen). Reusa OCR + el mismo parser/valuador del Ctrl+C.
    # ============================================================================
    def value_item_image(self):
        """Boton: elegir una imagen del tooltip de un item y valorarlo."""
        if not self._rune_ready():   # mismo chequeo de OCR disponible
            return
        try:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                title="Elige la captura del item (tooltip)",
                filetypes=[("Imagenes", "*.png *.jpg *.jpeg *.bmp *.webp"), ("Todos", "*.*")],
            )
        except Exception:
            path = ""
        if not path:
            return
        self._rune_status("Leyendo imagen del item...")
        threading.Thread(target=self._item_image_worker, args=(path,), daemon=True).start()

    def capture_item_screen(self):
        """Boton: seleccionar un area de la pantalla (el tooltip) y valorar ese item."""
        if not self._rune_ready():
            return
        self._capture_target = self._item_image_worker
        try:
            self._start_region_select()
        except Exception as exc:
            self._rune_popup(f"No pude abrir el selector de area: {exc}")

    def _item_image_worker(self, image_or_path):
        """OCR de la imagen -> build_item_from_ocr -> valuador -> render_result."""
        try:
            img = (_rune_reward.load_image(image_or_path)
                   if isinstance(image_or_path, str) else image_or_path)
            text = _rune_reward.ocr_pil_image(img)
        except Exception as exc:
            err = "No pude leer el item de la imagen (OCR):\n" + "".join(
                traceback.format_exception_only(type(exc), exc))
            self.root.after(0, lambda: self._rune_popup(err))
            return
        if not (text or "").strip():
            self.root.after(0, lambda: self._rune_popup(
                "El OCR no leyo texto. Captura el tooltip del item mas grande y nitido, "
                "sin que el cursor lo tape."))
            return
        try:
            item = build_item_from_ocr(text, self.market)
            result = self.valuator.value(item)
            try:
                self.advisor.annotate(item, result)
            except Exception:
                pass
            try:
                result.roll_quality_text = roll_quality_text(item)
            except Exception:
                result.roll_quality_text = ""
            try:
                append_history(item, result)
            except Exception:
                pass
            import datetime
            self._copied_at = datetime.datetime.now().strftime("%H:%M:%S") + " (imagen)"
            icon = None
            try:
                icon = self._fetch_icon(result, item)
            except Exception:
                icon = None
            self.root.after(0, lambda: self._render_value_result(item, result, icon))
            self.root.after(0, lambda: self._rune_status("Item valorado desde imagen."))
        except Exception as exc:
            err = "Error valorando el item:\n" + "".join(
                traceback.format_exception_only(type(exc), exc))
            self.root.after(0, lambda: self._rune_popup(err))

    def _render_value_result(self, item, result, icon=None):
        """Llama a render_result de forma compatible con ambas UIs (con/sin icono)."""
        try:
            self.render_result(item, result, icon)   # UI moderna
        except TypeError:
            self.render_result(item, result)         # UI clasica

    # ---- ventana de resultados estilo "reward picker" (tk puro) ----
    def _show_rune_window(self, analysis, source=None):
        a = analysis
        try:
            win = tk.Toplevel(self.root)
        except Exception:
            return self._rune_popup(_rune_reward.format_report(a))
        win.title("Recompensas - cual conviene")
        win.configure(bg="#15151f")
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        win.geometry("540x640")

        tk.Label(win, text="\U0001fa99  Asesor de recompensas", fg="#ffd36b", bg="#15151f",
                 font=("Segoe UI", 14, "bold"), anchor="w").pack(fill="x", padx=14, pady=(12, 2))

        if a.error and not a.results:
            tk.Label(win, text=a.error, fg="#ffb3b3", bg="#15151f", wraplength=500,
                     justify="left", font=("Segoe UI", 10)).pack(fill="x", padx=14, pady=10)
            tk.Button(win, text="Volver a capturar", command=lambda: (win.destroy(), self.capture_rune_screen()),
                      bg="#2d365f", fg="#fff", bd=0, padx=12, pady=6).pack(pady=(4, 4))
            tk.Button(win, text="Subir imagen", command=lambda: (win.destroy(), self.read_rune_image()),
                      bg="#3a2a1f", fg="#fff", bd=0, padx=12, pady=6).pack(pady=(0, 12))
            return

        # Miniatura de la captura (clic para volver a capturar / reemplazar)
        try:
            from PIL import Image, ImageTk
            img = Image.open(source) if isinstance(source, str) else source
            thumb = img.copy()
            thumb.thumbnail((380, 150))
            ph = ImageTk.PhotoImage(thumb)
            win._thumb_ref = ph  # evita que el GC la borre
            tl = tk.Label(win, image=ph, bg="#15151f", cursor="hand2")
            tl.pack(padx=14, pady=(4, 0))
            tk.Label(win, text="clic en la imagen para volver a capturar", fg="#6f7290",
                     bg="#15151f", font=("Segoe UI", 8)).pack()
            tl.bind("<Button-1>", lambda e: (win.destroy(), self.capture_rune_screen()))
        except Exception:
            pass

        tk.Label(win, text=_rune_reward.summary_line(a), fg="#cfcfe0", bg="#15151f",
                 anchor="w", font=("Segoe UI", 10, "bold")).pack(fill="x", padx=14, pady=(8, 6))
        tops = _rune_reward.top_to_sell(a, 3)
        if tops:
            tbox = tk.Frame(win, bg="#221d0f", highlightbackground="#caa23a", highlightthickness=2)
            tbox.pack(fill="x", padx=12, pady=(0, 8))
            tk.Label(tbox, text="\u2b50 ELEGIR esta fila:", bg="#221d0f", fg="#ffd36b",
                     font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
            tk.Label(tbox, text=f"{tops[0].matched_name}   \u2014   {tops[0].price_text}",
                     bg="#221d0f", fg="#ffe9a8", font=("Segoe UI", 12, "bold"), anchor="w",
                     wraplength=470, justify="left").pack(fill="x", padx=10, pady=(0, 6))
            if len(tops) > 1:
                medals = ["1\u00ba", "2\u00ba", "3\u00ba"]
                for i, r in enumerate(tops):
                    tk.Label(tbox, text=f"   {medals[i]}  {r.matched_name}: {r.price_text}",
                             bg="#221d0f", fg="#d8c79a", font=("Segoe UI", 9), anchor="w",
                             wraplength=470, justify="left").pack(fill="x", padx=10)
            tk.Frame(tbox, bg="#221d0f", height=6).pack()

        # Area scrollable de tarjetas
        outer = tk.Frame(win, bg="#15151f")
        outer.pack(fill="both", expand=True, padx=10)
        canvas = tk.Canvas(outer, bg="#15151f", highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg="#15151f")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", width=496)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        best = _rune_reward.best_to_sell(a)
        for r in a.results:
            vend = (r.verdict == "VENDER" and r.found)
            is_best = (r is best and vend)
            badge_bg = "#caa23a" if vend else "#2f4a6b"
            badge_fg = "#14110b" if vend else "#dce8ff"
            badge_txt = ("\u2605 " if is_best else "") + ("VENDER" if vend else "USAR")
            border = "#ffd36b" if is_best else "#2a2a3a"
            card = tk.Frame(inner, bg="#1c1c28", highlightbackground=border,
                            highlightcolor=border, highlightthickness=2)
            card.pack(fill="x", pady=4, padx=2)
            top = tk.Frame(card, bg="#1c1c28")
            top.pack(fill="x", padx=10, pady=(8, 0))
            tk.Label(top, text=badge_txt, bg=badge_bg, fg=badge_fg,
                     font=("Segoe UI", 9, "bold"), padx=8, pady=1).pack(side="left")
            price = r.price_text if r.found else "sin precio de venta"
            tk.Label(top, text=price, bg="#1c1c28", fg="#ffd36b" if vend else "#9fb4d6",
                     font=("Segoe UI", 11, "bold")).pack(side="right")
            tk.Label(card, text=r.matched_name, bg="#1c1c28", fg="#ffffff",
                     font=("Segoe UI", 11, "bold"), anchor="w", justify="left",
                     wraplength=450).pack(fill="x", padx=10, pady=(3, 0))
            note = r.tier_note or ("usar / craftear (no se vende directo)" if not vend else "")
            if note:
                tk.Label(card, text=note, bg="#1c1c28", fg="#8a8aa0", font=("Segoe UI", 8),
                         anchor="w", justify="left", wraplength=450).pack(fill="x", padx=10, pady=(0, 8))
            else:
                tk.Frame(card, bg="#1c1c28", height=6).pack()

        foot = " | ".join([x for x in [
            f"Liga: {a.league}" if a.league else "",
            f"1 div \u2248 {a.divine_price:g} ex" if a.divine_price else "",
            "Fuente: poe2scout (en vivo)"] if x])
        tk.Label(win, text=foot, fg="#8588a3", bg="#15151f", font=("Segoe UI", 8),
                 anchor="w").pack(fill="x", padx=14, pady=(4, 2))
        bar = tk.Frame(win, bg="#15151f")
        bar.pack(fill="x", padx=14, pady=(0, 10))
        tk.Button(bar, text="\U0001f4f7 Volver a capturar", command=lambda: (win.destroy(), self.capture_rune_screen()),
                  bg="#2d365f", fg="#fff", bd=0, padx=10, pady=6).pack(side="left")
        tk.Button(bar, text="\U0001fa99 Subir imagen", command=lambda: (win.destroy(), self.read_rune_image()),
                  bg="#3a2a1f", fg="#fff", bd=0, padx=10, pady=6).pack(side="left", padx=6)
        tk.Button(bar, text="Cerrar", command=win.destroy,
                  bg="#262638", fg="#fff", bd=0, padx=10, pady=6).pack(side="right")

    # ---- ventana de resultados (tk puro, sirve para ambas UIs) ----
    def _rune_popup(self, text):
        try:
            win = tk.Toplevel(self.root)
            win.title("Runas - cual vender")
            win.configure(bg="#101018")
            try:
                win.attributes("-topmost", True)
            except Exception:
                pass
            tk.Label(win, text="Asesor de recompensas de runa", fg="#ffd36b", bg="#101018",
                     font=("Segoe UI", 13, "bold"), anchor="w").pack(fill="x", padx=12, pady=(12, 4))
            box = tk.Text(win, width=72, height=20, wrap="word", bg="#0b0b12", fg="#e4e4ec",
                          insertbackground="#ffffff", bd=0, padx=10, pady=10, font=("Consolas", 10))
            box.pack(fill="both", expand=True, padx=12, pady=(0, 8))
            box.insert("1.0", text)
            box.configure(state="disabled")
            tk.Button(win, text="Cerrar", command=win.destroy, bg="#2d365f", fg="#ffffff",
                      bd=0, padx=12, pady=6).pack(pady=(0, 12))
        except Exception:
            try:
                messagebox.showinfo("Runas - cual vender", text)
            except Exception:
                print(text)

    # ---- atajo de captura ----
    def _bind_rune_hotkey(self):
        # Atajo local (cuando el overlay tiene foco)
        try:
            self.root.bind("<F8>", lambda e: self.capture_rune_screen())
            self.root.bind("<KeyPress-F8>", lambda e: self.capture_rune_screen())
        except Exception:
            pass
        # Atajo global opcional (funciona con el juego en primer plano) si esta 'keyboard'
        try:
            import keyboard  # opcional
            keyboard.add_hotkey("f8", lambda: self.root.after(0, self.capture_rune_screen))
        except Exception:
            pass


class OverlayApp(RuneAdvisorMixin):
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = load_config()
        self.market = MarketClient(self.config, self.set_status_threadsafe)
        self.valuator = HeuristicValuator(self.config, self.market)
        self.trade = TradeClient(self.config, self.market, self.set_status_threadsafe)
        self.valuator.trade = self.trade
        self.advisor = BuildAdvisor(self.config, self.set_status_threadsafe)
        self.last_clipboard = ""
        self.last_item: ParsedItem | None = None
        self.last_result: ValuationResult | None = None
        self._busy = False
        self._drag_start: tuple[int, int] | None = None
        self._setup_ui()
        self.root.after(300, self.poll_clipboard)

    def _setup_ui(self) -> None:
        r = self.root
        r.title(APP_NAME)
        r.geometry("470x500+80+80")
        r.minsize(420, 380)
        r.configure(bg="#101018")
        try:
            r.attributes("-topmost", bool(self.config.get("always_on_top", True)))
            r.attributes("-alpha", float(self.config.get("window_alpha", 0.94)))
        except Exception:
            pass

        self.header = tk.Frame(r, bg="#1d1d2b", padx=10, pady=8)
        self.header.pack(fill="x")
        self.header.bind("<ButtonPress-1>", self.start_drag)
        self.header.bind("<B1-Motion>", self.do_drag)

        self.title_var = tk.StringVar(value=f"{APP_NAME}  v{APP_VERSION}  ·  by {APP_AUTHOR}")
        tk.Label(self.header, textvariable=self.title_var, fg="#f5f5f5", bg="#1d1d2b", font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Button(self.header, text="×", command=r.destroy, bg="#2c2c3a", fg="#fff", bd=0, width=3).pack(side="right")

        body = tk.Frame(r, bg="#101018", padx=12, pady=10)
        body.pack(fill="both", expand=True)

        self.name_var = tk.StringVar(value="Copia un ítem con Ctrl+C dentro de PoE2")
        tk.Label(body, textvariable=self.name_var, fg="#ffffff", bg="#101018", anchor="w", justify="left", wraplength=430, font=("Segoe UI", 12, "bold")).pack(fill="x")

        self.price_var = tk.StringVar(value="Esperando ítem…")
        tk.Label(body, textvariable=self.price_var, fg="#ffd36b", bg="#101018", anchor="w", font=("Segoe UI", 20, "bold")).pack(fill="x", pady=(8, 0))

        self.detail_var = tk.StringVar(value="Modo seguro: solo portapapeles. Recomendado: Borderless Windowed.")
        tk.Label(body, textvariable=self.detail_var, fg="#b8bacf", bg="#101018", anchor="w", justify="left", wraplength=430, font=("Segoe UI", 9)).pack(fill="x", pady=(4, 8))

        cards = tk.Frame(body, bg="#101018")
        cards.pack(fill="x", pady=(0, 8))
        self.quick_var = tk.StringVar(value="Venta rápida: —")
        self.fair_var = tk.StringVar(value="Precio justo: —")
        self.high_var = tk.StringVar(value="Alto: —")
        for var in [self.quick_var, self.fair_var, self.high_var]:
            tk.Label(cards, textvariable=var, fg="#e8e8ef", bg="#181825", anchor="w", padx=8, pady=4, font=("Segoe UI", 9)).pack(fill="x", pady=2)

        self.text = tk.Text(body, height=12, wrap="word", bg="#0b0b12", fg="#e4e4ec", insertbackground="#ffffff", bd=0, padx=8, pady=8, font=("Consolas", 9))
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", "Tips:\n- Hover sobre el ítem en inventario/alijo y pulsa Ctrl+C.\n- El overlay se actualizará solo.\n- Para probar sin juego, copia un bloque de sample_items.txt.\n")
        self.text.configure(state="disabled")

        controls = tk.Frame(body, bg="#101018")
        controls.pack(fill="x", pady=(8, 0))
        tk.Button(controls, text="Leer portapapeles", command=self.manual_check, bg="#2d365f", fg="#ffffff", bd=0, padx=10, pady=6).pack(side="left")
        tk.Button(controls, text="Siempre encima ON/OFF", command=self.toggle_topmost, bg="#262638", fg="#ffffff", bd=0, padx=10, pady=6).pack(side="left", padx=6)
        tk.Button(controls, text="Abrir historial", command=self.open_history_location, bg="#262638", fg="#ffffff", bd=0, padx=10, pady=6).pack(side="left")
        tk.Button(controls, text="↻ Mercado", command=self.refresh_market, bg="#1f4d3a", fg="#ffffff", bd=0, padx=10, pady=6).pack(side="left", padx=6)
        tk.Button(controls, text="Trade oficial", command=self.open_trade_search, bg="#4d3a1f", fg="#ffffff", bd=0, padx=10, pady=6).pack(side="left")
        self.auto_btn = tk.Button(controls, text="Auto-precio: OFF", command=self.toggle_auto_trade, bg="#3a2342", fg="#ffffff", bd=0, padx=10, pady=6)
        self.auto_btn.pack(side="left", padx=6)
        tk.Button(controls, text="Cargar build", command=self.load_build_file, bg="#23323a", fg="#ffffff", bd=0, padx=10, pady=6).pack(side="left")
        tk.Button(controls, text="Generar filtro", command=self.generate_filter_from_build, bg="#2a3a23", fg="#ffffff", bd=0, padx=10, pady=6).pack(side="left", padx=6)
        self._bind_rune_hotkey()
        controls2 = tk.Frame(body, bg="#101018")
        controls2.pack(fill="x", pady=(6, 0))
        tk.Button(controls2, text="🪙 Runas: ¿cuál vender? (imagen)", command=self.read_rune_image, bg="#5a4a1f", fg="#ffffff", bd=0, padx=12, pady=6).pack(side="left")
        tk.Button(controls2, text="✂ Capturar área (F8)", command=self.capture_rune_screen, bg="#1f2a3a", fg="#ffffff", bd=0, padx=12, pady=6).pack(side="left", padx=6)
        tk.Button(controls2, text="💰 Ítem por imagen", command=self.value_item_image, bg="#1f3a2a", fg="#ffffff", bd=0, padx=12, pady=6).pack(side="left")
        tk.Button(controls2, text="✂ Ítem (capturar área)", command=self.capture_item_screen, bg="#2a1f3a", fg="#ffffff", bd=0, padx=12, pady=6).pack(side="left", padx=6)

        self.status_var = tk.StringVar(value=f"Liga: {self.config.get('league')} | Realm: {self.config.get('realm')}")
        tk.Label(body, textvariable=self.status_var, fg="#8588a3", bg="#101018", anchor="w", font=("Segoe UI", 8)).pack(fill="x", pady=(8, 0))
        # Carga el mercado al iniciar (en segundo plano) para tener divine/exalted listos.
        threading.Thread(target=self._preload_market, daemon=True).start()

    def _preload_market(self) -> None:
        try:
            self.market.ensure_loaded()
        except Exception:
            pass

    def refresh_market(self) -> None:
        """Fuerza recarga del mercado borrando la caché local."""
        def _job() -> None:
            try:
                if CACHE_PATH.exists():
                    CACHE_PATH.unlink()
            except Exception:
                pass
            self.market._items = None
            self.set_status_threadsafe("Actualizando precios de mercado…")
            self.market.ensure_loaded()
        threading.Thread(target=_job, daemon=True).start()

    def start_drag(self, event: tk.Event) -> None:
        self._drag_start = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def do_drag(self, event: tk.Event) -> None:
        if self._drag_start:
            x_offset, y_offset = self._drag_start
            self.root.geometry(f"+{event.x_root - x_offset}+{event.y_root - y_offset}")

    def set_status_threadsafe(self, text: str) -> None:
        try:
            self.root.after(0, lambda: self.status_var.set(text))
        except Exception:
            pass

    def set_text(self, content: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.configure(state="disabled")

    def poll_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except Exception:
            text = ""
        if text and text != self.last_clipboard and looks_like_poe_item(text):
            self.last_clipboard = text
            self.check_text_async(text)
        self.root.after(int(self.config.get("poll_ms", 600)), self.poll_clipboard)

    def manual_check(self) -> None:
        try:
            text = self.root.clipboard_get()
        except Exception:
            text = ""
        if not looks_like_poe_item(text):
            self.status_var.set("El portapapeles no parece contener un ítem copiado de PoE2.")
            return
        self.last_clipboard = text
        self.check_text_async(text)

    def check_text_async(self, text: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.status_var.set("Analizando ítem…")
        t = threading.Thread(target=self._worker_check, args=(text,), daemon=True)
        t.start()

    def _worker_check(self, text: str) -> None:
        try:
            item = parse_item_text(text)
            result = self.valuator.value(item)
            self.advisor.annotate(item, result)
            try:
                result.roll_quality_text = roll_quality_text(item)
            except Exception:
                result.roll_quality_text = ""
            append_history(item, result)
            self.root.after(0, lambda: self.render_result(item, result))
        except Exception as exc:
            err = "Error analizando item:\n" + "".join(traceback.format_exception_only(type(exc), exc))
            self.root.after(0, lambda: self.set_text(err))
        finally:
            self.root.after(0, lambda: setattr(self, "_busy", False))

    def render_result(self, item: ParsedItem, result: ValuationResult) -> None:
        self.last_item = item
        self.last_result = result
        subtitle_parts = []
        if item.base_type:
            subtitle_parts.append(item.base_type)
        if item.item_level:
            subtitle_parts.append(f"ilvl {item.item_level}")
        if item.category:
            subtitle_parts.append(item.category)
        subtitle = " | ".join(subtitle_parts)

        self.name_var.set(f"{result.title}" + (f"  ({subtitle})" if subtitle else ""))
        self.price_var.set(result.price_text)
        detail = f"Confianza: {result.confidence} | Fuente: {result.source} | Score: {result.score:g}"
        if result.build_fit is not None:
            detail += f"  |  BUILD: {result.build_verdict}  (afinidad {result.build_fit:g}/100)"
        self.detail_var.set(detail)
        self.quick_var.set(f"Venta rápida: {result.quick_sell}")
        self.fair_var.set(f"Precio justo: {result.fair_price}")
        self.high_var.set(f"Precio ambicioso: {result.ambitious_price}")

        lines: list[str] = []
        verdict = gold_decision(result.market_value_ex, self.config.get("convert_to_gold_below_ex", 1.0))
        if verdict and (result.market_value_ex > 0 or item.rarity in {"Normal", "Magic", "Rare", "Unique"}):
            gold_est = estimate_vendor_gold(item)
            if verdict == "MERCADO":
                lines.append(f"DECISIÓN: ✅ VENDER EN MERCADO (~{result.market_value_ex:g} ex)")
            else:
                tip = f" · {gold_est}" if gold_est else ""
                lines.append(f"DECISIÓN: 🪙 CONVERTIR EN ORO con el mercader (mercado ~{result.market_value_ex:g} ex, por debajo del umbral){tip}")
            lines.append("")
        if result.build_fit is not None:
            lines.append("PARA TU BUILD")
            lines.append(f"  {result.build_verdict}  (afinidad {result.build_fit:g}/100)")
            if result.build_fit >= 55:
                lines.append("  → Recomendación: QUÉDATELO / pruébalo en tu personaje.")
            elif result.build_fit >= 30:
                lines.append("  → Recomendación: compáralo con lo que ya usas.")
            else:
                lines.append(f"  → Recomendación: NO te sirve, véndelo (venta rápida {result.quick_sell}).")
            if result.build_reasons:
                lines.append("  Aporta: " + ", ".join(result.build_reasons[:8]))
            if result.build_irrelevant:
                lines.append("  No aporta: " + ", ".join(result.build_irrelevant[:5]))
            lines.append("")
        if result.compare_text:
            lines.append("VS TU EQUIPADO")
            lines.append("  " + result.compare_text)
            lines.append("")
        if result.roll_quality_text:
            lines.append("CALIDAD DE ROLLS (vs tope)")
            lines.append("  " + result.roll_quality_text)
            lines.append("")
        lines.append("STATS DETECTADOS")
        if item.stats:
            for k, v in sorted(item.stats.items()):
                lines.append(f"  {k}: {v:g}")
        else:
            lines.append("  — sin stats clave detectados —")
        lines.append("")
        lines.append("POR QUÉ VALE ESTO")
        for r in result.reasons:
            lines.append(f"  + {r}")
        if result.warnings:
            lines.append("")
            lines.append("OJO")
            for w in result.warnings:
                lines.append(f"  ! {w}")
        if item.mod_lines:
            lines.append("")
            lines.append("MODS LEÍDOS")
            for m in item.mod_lines[:12]:
                lines.append(f"  - {m}")
        self.set_text("\n".join(lines))
        self.status_var.set(f"Último check: {datetime.now().strftime('%H:%M:%S')} | historial en history.jsonl")

    def toggle_topmost(self) -> None:
        try:
            current = bool(self.root.attributes("-topmost"))
            self.root.attributes("-topmost", not current)
            self.status_var.set(f"Siempre encima: {'ON' if not current else 'OFF'}")
        except Exception:
            pass

    def open_history_location(self) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(BASE_DIR))  # type: ignore[attr-defined]
            else:
                self.status_var.set(str(BASE_DIR))
        except Exception:
            self.status_var.set(str(BASE_DIR))

    def load_build_file(self) -> None:
        try:
            start = self.config.get("build_file") or default_build_dir()
            initial_dir = str(Path(start).parent) if Path(start).suffix else start
            path = filedialog.askopenfilename(
                title="Selecciona tu archivo .build (PoE2 / Path of Building / Downloads)",
                initialdir=initial_dir,
                filetypes=[("PoE build", "*.build *.json"), ("Todos", "*.*")])
        except Exception:
            path = ""
        if not path:
            return
        if self.advisor.load(path):
            p = self.advisor.profile
            save_config(self.config)  # recuerda la build para la próxima vez
            self.status_var.set(f"Build: {p['name']} | arma {p['weapon']} | {', '.join(a.upper() for a in p['attrs'])} (guardada)")
        else:
            self.status_var.set("No se pudo cargar la build (revisa el archivo).")

    def generate_filter_from_build(self) -> None:
        """Crea un loot filter .filter desde la build cargada y abre su carpeta."""
        if not self.advisor.profile:
            self.status_var.set("Primero carga tu build con 'Cargar build'.")
            return
        if not _generate_filter:
            self.status_var.set("No encuentro build_to_filter.py junto al overlay.")
            return
        try:
            prof = self.advisor.profile
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", prof.get("name", "build")).strip("_") or "build"
            out = BASE_DIR / f"{safe}.filter"
            out.write_text(_generate_filter(prof), encoding="utf-8")
            self.status_var.set(f"Filtro generado: {out.name} (en la carpeta del overlay)")
            try:
                if os.name == "nt":
                    os.startfile(str(BASE_DIR))  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception as exc:
            self.status_var.set(f"No pude generar el filtro: {exc}")

    def toggle_auto_trade(self) -> None:
        new = not bool(self.config.get("auto_trade_comparables"))
        self.config["auto_trade_comparables"] = new
        self.auto_btn.config(text=f"Auto-precio: {'ON' if new else 'OFF'}",
                             bg="#1f4d3a" if new else "#3a2342")
        if new:
            self.status_var.set("Auto-precio ON: los rares consultarán comparables reales del trade al leerlos.")
        else:
            self.status_var.set("Auto-precio OFF: los rares usan heurística local (sin consultas al trade).")

    def open_trade_search(self) -> None:
        """Boton Trade: para rares arma la busqueda por stats (asistida) y abre el trade
        ya pre-cargado; para uniques/currency abre por nombre. Una sola llamada por clic."""
        item = self.last_item
        league = self.market.resolved_league or str(self.config.get("league", "Runes of Aldur"))
        if item and item.rarity in {"Rare", "Magic"} and item.category != "currency":
            threading.Thread(target=self._assisted_trade, args=(item, league), daemon=True).start()
            return
        self._name_trade(item, league)

    def _name_trade(self, item, league: str) -> None:
        url = f"{TRADE2_WEB}{urllib.parse.quote(league)}"
        query = (item.name or item.base_type or "") if item else ""
        try:
            if query:
                self.root.clipboard_clear()
                self.root.clipboard_append(query)
            webbrowser.open(url)
            tip = f" | nombre copiado: «{query}» (pegalo en la busqueda)" if query else ""
            self.status_var.set(f"Trade abierto para {league}{tip}")
        except Exception as exc:
            self.status_var.set(f"No pude abrir el trade: {exc}")

    def _assisted_trade(self, item, league: str) -> None:
        query = build_trade2_query(item)
        if not query:
            self.set_status_threadsafe("Sin stats clave para filtrar; abriendo trade por base.")
            self.root.after(0, lambda: self._name_trade(item, league))
            return
        self.set_status_threadsafe("Armando busqueda de comparables en el trade oficial…")
        ua = str(self.config.get("user_agent", DEFAULT_CONFIG["user_agent"]))
        n_filters = len(query["query"]["stats"][0]["filters"])
        try:
            data = json.dumps(query).encode("utf-8")
            req = urllib.request.Request(
                f"{TRADE2_API}{urllib.parse.quote(league)}",
                data=data,
                headers={"User-Agent": ua, "Content-Type": "application/json", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            sid = payload.get("id")
            count = len(payload.get("result") or [])
            if sid:
                webbrowser.open(f"{TRADE2_WEB}{urllib.parse.quote(league)}/{sid}")
                self.set_status_threadsafe(f"Trade: comparables con {n_filters} filtros | {count} listings reales")
                return
            self.set_status_threadsafe("El trade no devolvio busqueda; abriendo por base.")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                self.set_status_threadsafe("Trade oficial: limite de consultas (429). Espera unos segundos y reintenta.")
                return
            self.set_status_threadsafe(f"Trade oficial error {exc.code}; abriendo por base.")
        except Exception as exc:
            self.set_status_threadsafe(f"No pude consultar el trade ({exc}); abriendo por base.")
        self.root.after(0, lambda: self._name_trade(item, league))


# ======================================================================================
# UI MODERNA (CustomTkinter) — tema PoE2 oscuro dorado, con modo compacto/expandido.
# Si customtkinter no está instalado, main() cae a la UI clásica (OverlayApp).
# ======================================================================================

# Paleta PoE2 oscuro dorado
C_BG = "#14110b"
C_PANEL = "#1d1810"
C_PANEL2 = "#262016"
C_BORDER = "#4a3d22"
C_GOLD = "#d8b25a"
C_GOLD_SOFT = "#b9974a"
C_TEXT = "#ece6d8"
C_SUB = "#9a9080"
C_GREEN = "#5fb96b"
C_YELLOW = "#d8b25a"
C_RED = "#d2664f"


class _Tooltip:
    """Tooltip simple para widgets Tk/CustomTkinter: aparece al pasar el mouse.

    Uso: _Tooltip(boton, "texto explicativo"). No depende de librerías extra.
    """

    def __init__(self, widget, text: str, delay: int = 450):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._cancel()
        try:
            self._after = self.widget.after(self.delay, self._show)
        except Exception:
            pass

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 14
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        try:
            self._tip = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            try:
                tw.attributes("-topmost", True)
            except Exception:
                pass
            border = tk.Frame(tw, background=C_GOLD_SOFT, bd=0)
            border.pack()
            tk.Label(border, text=self.text, justify="left", background=C_PANEL2,
                     foreground=C_TEXT, font=("Segoe UI", 9), padx=8, pady=5,
                     wraplength=270).pack(padx=1, pady=1)
            tw.wm_geometry(f"+{x}+{y}")
        except Exception:
            self._tip = None

    def _hide(self, _=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def _parse_version(s: str) -> tuple:
    """'v0.5.1' -> (0, 5, 1). Sirve para comparar versiones numéricamente."""
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def check_github_update(repo: str, current_version: str, timeout: int = 6) -> Optional[dict]:
    """Consulta la última *release* de GitHub.

    Devuelve {"tag", "url", "asset_url"} si hay una versión MÁS NUEVA que la actual;
    None si está al día o si falla la consulta (sin molestar al usuario).
    """
    if not repo or "/" not in repo:
        return None
    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(url, headers={
            "User-Agent": "poe2valuator-updater",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        tag = str(data.get("tag_name") or "").strip()
        if not tag or _parse_version(tag) <= _parse_version(current_version):
            return None
        html_url = data.get("html_url") or f"https://github.com/{repo}/releases/latest"
        asset_url = None
        for a in (data.get("assets") or []):
            if str(a.get("name") or "").lower().endswith(".exe"):
                asset_url = a.get("browser_download_url")
                break
        return {"tag": tag, "url": html_url, "asset_url": asset_url}
    except Exception:
        return None


class OverlayAppModern(RuneAdvisorMixin):
    def __init__(self, root: "ctk.CTk"):
        self.root = root
        self.config = load_config()
        self.market = MarketClient(self.config, self.set_status_threadsafe)
        self.valuator = HeuristicValuator(self.config, self.market)
        self.trade = TradeClient(self.config, self.market, self.set_status_threadsafe)
        self.valuator.trade = self.trade
        self.advisor = BuildAdvisor(self.config, self.set_status_threadsafe)
        self.last_clipboard = ""
        self.last_item = None
        self.last_result = None
        self._busy = False
        self._drag = None
        self.compact = False
        self._build_ui()
        self.root.after(300, self.poll_clipboard)
        threading.Thread(target=self._preload_market, daemon=True).start()
        self._refresh_meta()
        if self.config.get("start_compact"):
            self.root.after(200, self.toggle_compact)

    # ---------------- construcción de UI ----------------
    def _font(self, size, weight="normal"):
        return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)

    def _build_ui(self):
        r = self.root
        try:
            r.overrideredirect(True)
        except Exception:
            pass
        try:
            r.attributes("-topmost", bool(self.config.get("always_on_top", True)))
            r.attributes("-alpha", float(self.config.get("window_alpha", 0.96)))
        except Exception:
            pass
        self._expanded_geom = self.config.get("window_geometry") or "450x580+90+90"
        r.geometry(self._expanded_geom)
        r.configure(fg_color=C_BG)

        # --- Header / barra superior (drag) ---
        self.header = ctk.CTkFrame(r, fg_color=C_PANEL2, corner_radius=0, height=42)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)
        title = ctk.CTkLabel(self.header, text="⚔  PoE2 Valuator", text_color=C_GOLD,
                             font=self._font(16, "bold"))
        title.pack(side="left", padx=(12, 4))
        credit = ctk.CTkLabel(self.header, text=f"v{APP_VERSION} · by {APP_AUTHOR}",
                              text_color=C_SUB, font=self._font(10))
        credit.pack(side="left", padx=0)
        for w in (self.header, title, credit):
            w.bind("<ButtonPress-1>", self.start_drag)
            w.bind("<B1-Motion>", self.do_drag)

        # Botón de actualización (oculto hasta detectar una versión más nueva en GitHub).
        self._update_url = None
        self.update_btn = ctk.CTkButton(self.header, text="⬆ Actualizar", height=26, corner_radius=8,
                      fg_color=C_GREEN, hover_color=C_GOLD, text_color="#14110b",
                      font=self._font(11, "bold"), command=self._open_update)
        _Tooltip(self.update_btn, "Hay una versión nueva en GitHub. Clic para abrir la página de descarga del .exe actualizado.")

        close_btn = ctk.CTkButton(self.header, text="✕", width=30, height=28, corner_radius=8,
                      fg_color=C_PANEL, hover_color=C_RED, text_color=C_TEXT,
                      command=self._on_close)
        close_btn.pack(side="right", padx=(0, 8))
        _Tooltip(close_btn, "Cierra el overlay y guarda la posición/estado de la ventana.")
        self.compact_btn = ctk.CTkButton(self.header, text="▢", width=30, height=28, corner_radius=8,
                      fg_color=C_PANEL, hover_color=C_GOLD_SOFT, text_color=C_TEXT,
                      command=self.toggle_compact)
        self.compact_btn.pack(side="right", padx=4)
        _Tooltip(self.compact_btn, "Modo compacto: oculta el panel de detalle para ocupar menos espacio (el precio y los botones siguen visibles). Vuelve a pulsarlo para expandir.")
        self.pin_sw = ctk.CTkSwitch(self.header, text="📌", width=44, font=self._font(13),
                      progress_color=C_GOLD, command=self.toggle_topmost)
        if self.config.get("always_on_top", True):
            self.pin_sw.select()
        self.pin_sw.pack(side="right", padx=4)
        _Tooltip(self.pin_sw, "Fija la ventana siempre encima del juego (activado) o permite que otras ventanas la tapen (desactivado).")

        # --- Hero: nombre + precio + chips ---
        self.hero = ctk.CTkFrame(r, fg_color=C_PANEL, corner_radius=12, border_width=1, border_color=C_BORDER)
        self.hero.pack(fill="x", padx=10, pady=(10, 6))
        self.icon_lbl = ctk.CTkLabel(self.hero, text="", width=44, height=44)
        self.icon_lbl.place(relx=1.0, x=-12, y=12, anchor="ne")
        self._icon_imgref = None
        self._copied_at = ""
        self.name_lbl = ctk.CTkLabel(self.hero, text="Copia un ítem con Ctrl+C en PoE2",
                      text_color=C_TEXT, font=self._font(15, "bold"), anchor="w", justify="left", wraplength=410)
        self.name_lbl.pack(fill="x", padx=14, pady=(12, 0))
        self.sub_lbl = ctk.CTkLabel(self.hero, text="Modo seguro: solo portapapeles",
                      text_color=C_SUB, font=self._font(11), anchor="w")
        self.sub_lbl.pack(fill="x", padx=14, pady=(2, 4))
        self.price_lbl = ctk.CTkLabel(self.hero, text="—", text_color=C_GOLD,
                      font=self._font(26, "bold"), anchor="w", justify="left", wraplength=410)
        self.price_lbl.pack(fill="x", padx=14, pady=(0, 6))

        chips = ctk.CTkFrame(self.hero, fg_color="transparent")
        chips.pack(fill="x", padx=12, pady=(0, 12))
        self.chip_quick = self._chip(chips, "Venta rápida", "—")
        self.chip_fair = self._chip(chips, "Justo", "—")
        self.chip_amb = self._chip(chips, "Ambicioso", "—")

        # --- Badge de build ---
        self.badge = ctk.CTkLabel(r, text="", text_color="#14110b", font=self._font(13, "bold"),
                      corner_radius=10, anchor="w", justify="left", fg_color=C_PANEL)
        # se muestra solo cuando hay build cargada (pack on demand)

        # --- Detalle (scrollable textbox) ---
        self.detail_box = ctk.CTkTextbox(r, fg_color=C_PANEL, text_color=C_TEXT,
                      font=ctk.CTkFont(family="Consolas", size=12), corner_radius=12,
                      border_width=1, border_color=C_BORDER, wrap="word")
        self.detail_box.pack(fill="both", expand=True, padx=10, pady=6)
        self.detail_box.insert("0.0", "Tips:\n  • Pasa el mouse sobre un ítem y pulsa Ctrl+C.\n"
                               "  • Carga tu build para ver si un ítem te sirve.\n"
                               "  • Activa Auto-precio para comparables reales del trade.\n")
        self.detail_box.configure(state="disabled")

        # --- Toolbar ---
        self.toolbar = ctk.CTkFrame(r, fg_color="transparent")
        self.toolbar.pack(fill="x", padx=8, pady=(0, 6))
        self._tb_btn("📋 Leer", self.manual_check, C_PANEL2,
                     tooltip="Lee AHORA el portapapeles y valora el ítem que tengas copiado. Úsalo si copiaste algo (Ctrl+C) y la ventana no se actualizó sola.")
        self._tb_btn("🔄 Mercado", self.refresh_market, C_PANEL2,
                     tooltip="Vuelve a descargar los precios en vivo de poe2scout para la liga actual (borra la caché y la regenera). Úsalo si los precios se ven viejos.")
        self._tb_btn("🔎 Trade", self.open_trade_search, C_PANEL2,
                     tooltip="Abre el trade oficial de PoE2 en el navegador con la búsqueda del ítem ya cargada. En rares la arma por sus stats para ver listados reales comparables.")
        self._tb_btn("🧬 Build", self.load_build_file, C_PANEL2,
                     tooltip="Abre un explorador para elegir tu archivo .build (poe.ninja o Mobalytics). Una vez cargado, cada ítem se juzga según tu build.")
        self._tb_btn("⚙ Filtro", self.generate_filter_from_build, C_PANEL2,
                     tooltip="Crea un loot filter .filter a medida de la build cargada (resalta tu arma, bases por atributo y currency; atenúa lo que no usás) y abre la carpeta donde se guarda.")
        self._tb_btn("🕘", self.open_history_location, C_PANEL2, width=40,
                     tooltip="Abre la carpeta donde se guarda el historial de tus valoraciones (history.jsonl).")
        self._tb_btn("⚙", self.open_settings, C_PANEL2, width=40,
                     tooltip="Abre los ajustes: liga, etiquetas de monedas, intervalo del trade, transparencia de la ventana y más.")
        self._bind_rune_hotkey()

        rune_row = ctk.CTkFrame(r, fg_color="transparent")
        rune_row.pack(fill="x", padx=8, pady=(0, 6))
        rune_btn = ctk.CTkButton(rune_row, text="🪙 Runas: ¿cuál vender? (imagen)", command=self.read_rune_image,
                      fg_color=C_GOLD_SOFT, hover_color=C_GOLD, text_color="#14110b",
                      corner_radius=8, font=self._font(12, "bold"), height=32)
        rune_btn.pack(side="left", expand=True, fill="x", padx=2)
        _Tooltip(rune_btn, "Sube una imagen del panel de recompensas y calcula el valor de cada una para decirte cuál conviene vender (por nombre y cantidad).")
        capt_btn = ctk.CTkButton(rune_row, text="✂ Capturar área (F8)", command=self.capture_rune_screen,
                      fg_color=C_PANEL2, hover_color=C_GOLD_SOFT, text_color=C_TEXT,
                      corner_radius=8, font=self._font(12), height=32, width=130)
        capt_btn.pack(side="left", padx=2)
        _Tooltip(capt_btn, "Te deja dibujar un recuadro sobre la pantalla para leer ahí mismo el panel de recompensas y calcular su valor, sin subir archivos (atajo: F8).")

        # Fila para valorar un ITEM por captura (OCR -> mismo valuador del Ctrl+C)
        item_row = ctk.CTkFrame(r, fg_color="transparent")
        item_row.pack(fill="x", padx=8, pady=(0, 6))
        itimg_btn = ctk.CTkButton(item_row, text="💰 Valorar ítem (imagen)", command=self.value_item_image,
                      fg_color="#1f3a2a", hover_color="#2c5a40", text_color="#eafff2",
                      corner_radius=8, font=self._font(12, "bold"), height=32)
        itimg_btn.pack(side="left", expand=True, fill="x", padx=2)
        _Tooltip(itimg_btn, "Sube una imagen del tooltip de un ítem y lo valora con el mismo motor que el Ctrl+C (precio real de uniques/currency, y comparables del trade para rares). El Ctrl+C sigue siendo más preciso.")
        itcap_btn = ctk.CTkButton(item_row, text="✂ Ítem (área)", command=self.capture_item_screen,
                      fg_color=C_PANEL2, hover_color="#2c5a40", text_color=C_TEXT,
                      corner_radius=8, font=self._font(12), height=32, width=130)
        itcap_btn.pack(side="left", padx=2)
        _Tooltip(itcap_btn, "Dibuja un recuadro sobre el tooltip de un ítem en pantalla y lo valora directo, sin subir archivos.")
        tb2 = ctk.CTkFrame(r, fg_color="transparent")
        tb2.pack(fill="x", padx=10, pady=(0, 4))
        self.auto_sw = ctk.CTkSwitch(tb2, text="Auto-precio (trade en vivo)", font=self._font(12),
                      progress_color=C_GOLD, text_color=C_SUB, command=self.toggle_auto_trade)
        if self.config.get("auto_trade_comparables"):
            self.auto_sw.select()
        self.auto_sw.pack(side="left")
        _Tooltip(self.auto_sw, "Activado: los ítems rares consultan precios reales del trade oficial (con un límite de frecuencia para no saturar). Desactivado: usa solo la heurística local, más rápida pero aproximada.")

        # --- Status bar ---
        self.meta_lbl = ctk.CTkLabel(r, text="", text_color=C_SUB, font=self._font(10), anchor="w")
        self.meta_lbl.pack(fill="x", padx=12, pady=(0, 2))
        self.status_lbl = ctk.CTkLabel(r, text="Listo.", text_color=C_GOLD_SOFT, font=self._font(10), anchor="w")
        self.status_lbl.pack(fill="x", padx=12, pady=(0, 8))

        # Chequeo de actualización en segundo plano (no bloquea el arranque).
        self.root.after(1800, self._start_update_check)

    def _start_update_check(self):
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        repo = str(self.config.get("github_repo") or GITHUB_REPO)
        info = check_github_update(repo, APP_VERSION)
        if info:
            self.root.after(0, lambda: self._show_update(info))

    def _show_update(self, info):
        try:
            self._update_url = info.get("url")
            self.update_btn.configure(text=f"⬆ Actualizar a {info.get('tag')}")
            self.update_btn.pack(side="left", padx=8)
            self.set_status(f"Hay una versión nueva: {info.get('tag')} (la tuya es v{APP_VERSION}).")
        except Exception:
            pass

    def _open_update(self):
        try:
            webbrowser.open(self._update_url or f"https://github.com/{GITHUB_REPO}/releases/latest")
        except Exception:
            pass

    def _chip(self, parent, title, value):
        f = ctk.CTkFrame(parent, fg_color=C_PANEL2, corner_radius=8)
        f.pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkLabel(f, text=title, text_color=C_SUB, font=self._font(10)).pack(pady=(6, 0))
        lbl = ctk.CTkLabel(f, text=value, text_color=C_TEXT, font=self._font(13, "bold"))
        lbl.pack(pady=(0, 6))
        return lbl

    def _tb_btn(self, text, command, color, width=0, tooltip=""):
        b = ctk.CTkButton(self.toolbar, text=text, command=command, fg_color=color,
                          hover_color=C_GOLD_SOFT, text_color=C_TEXT, corner_radius=8,
                          font=self._font(12), height=30, width=width or 0)
        b.pack(side="left", expand=not width, fill="x", padx=2)
        if tooltip:
            _Tooltip(b, tooltip)
        return b

    # ---------------- drag / ventana ----------------
    def start_drag(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def do_drag(self, e):
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def toggle_topmost(self):
        try:
            on = bool(self.pin_sw.get())
            self.root.attributes("-topmost", on)
            self.set_status(f"Siempre encima: {'ON' if on else 'OFF'}")
        except Exception:
            pass

    def toggle_compact(self):
        self.compact = not self.compact
        if self.compact:
            self._expanded_geom = self.root.geometry()  # recordar tamaño/posición expandida
            # En compacto ocultamos solo el detalle grande; la toolbar de botones
            # se mantiene visible para tener las acciones a mano.
            self.detail_box.pack_forget()
            w = self._expanded_geom.split("+", 1)
            pos = "+" + w[1] if len(w) > 1 else ""
            # Altura = lo que realmente ocupan los controles visibles (no un valor fijo),
            # así nunca se cortan la toolbar, las runas, el auto-precio ni la barra de estado.
            self.root.update_idletasks()
            try:
                h = max(220, self.root.winfo_reqheight() + 6)
            except Exception:
                h = 360
            self.root.geometry(f"450x{h}" + pos)
            self.compact_btn.configure(text="▣")
        else:
            # Restaurar el detalle por encima de la toolbar (que nunca se ocultó).
            self.detail_box.pack(fill="both", expand=True, padx=10, pady=6, before=self.toolbar)
            self.root.geometry(self._expanded_geom or "450x580")
            self.compact_btn.configure(text="▢")
        self._save_window_state()

    def _save_window_state(self):
        try:
            geom = self._expanded_geom if self.compact else self.root.geometry()
            self.config["window_geometry"] = geom
            self.config["start_compact"] = bool(self.compact)
            save_config(self.config)
        except Exception:
            pass

    def _on_close(self):
        self._save_window_state()
        self.root.destroy()

    def open_settings(self):
        """Panel de ajustes in-app: liga y toggles, sin editar el JSON."""
        try:
            win = ctk.CTkToplevel(self.root)
            win.title("Ajustes")
            win.geometry("360x300")
            win.configure(fg_color=C_BG)
            try:
                win.attributes("-topmost", True)
            except Exception:
                pass
            ctk.CTkLabel(win, text="Ajustes", text_color=C_GOLD,
                         font=self._font(15, "bold")).pack(pady=(12, 6))
            ctk.CTkLabel(win, text="Liga", text_color=C_SUB, font=self._font(11)).pack(anchor="w", padx=16)
            league_var = ctk.StringVar(value=str(self.config.get("league", "")))
            ctk.CTkEntry(win, textvariable=league_var).pack(fill="x", padx=16, pady=(0, 8))

            sw_auto_league = ctk.CTkSwitch(win, text="Auto-detectar liga", progress_color=C_GOLD)
            sw_auto_league.pack(anchor="w", padx=16, pady=3)
            (sw_auto_league.select if self.config.get("auto_detect_league", True) else sw_auto_league.deselect)()
            sw_both = ctk.CTkSwitch(win, text="Mostrar ex + div", progress_color=C_GOLD)
            sw_both.pack(anchor="w", padx=16, pady=3)
            (sw_both.select if self.config.get("show_both_currencies", True) else sw_both.deselect)()
            sw_auto_trade = ctk.CTkSwitch(win, text="Auto-precio (trade en vivo)", progress_color=C_GOLD)
            sw_auto_trade.pack(anchor="w", padx=16, pady=3)
            (sw_auto_trade.select if self.config.get("auto_trade_comparables", False) else sw_auto_trade.deselect)()

            def _apply():
                self.config["league"] = league_var.get().strip() or self.config.get("league", "")
                self.config["auto_detect_league"] = bool(sw_auto_league.get())
                self.config["show_both_currencies"] = bool(sw_both.get())
                self.valuator.show_both = bool(sw_both.get())
                self.config["auto_trade_comparables"] = bool(sw_auto_trade.get())
                if hasattr(self, "auto_sw"):
                    (self.auto_sw.select if sw_auto_trade.get() else self.auto_sw.deselect)()
                save_config(self.config)
                self.set_status("Ajustes guardados. Actualiza el mercado para aplicar la liga.")
                win.destroy()

            ctk.CTkButton(win, text="Guardar", fg_color=C_PANEL2, hover_color=C_GOLD_SOFT,
                          text_color=C_TEXT, command=_apply).pack(pady=14)
        except Exception as exc:
            self.set_status(f"No pude abrir ajustes: {exc}")

    # ---------------- status ----------------
    def set_status(self, text):
        try:
            self.status_lbl.configure(text=text)
        except Exception:
            pass

    def set_status_threadsafe(self, text):
        try:
            self.root.after(0, lambda: self.set_status(text))
        except Exception:
            pass

    def _refresh_meta(self):
        league = self.market.resolved_league or self.config.get("league", "")
        dp = self.market.divine_price
        bp = self.advisor.profile
        parts = [f"Liga: {league}"]
        if dp:
            parts.append(f"1 div ≈ {dp:g} ex")
        parts.append(f"Build: {bp['name']} ({bp['weapon']})" if bp else "Build: —")
        parts.append(f"by {APP_AUTHOR}")
        try:
            self.meta_lbl.configure(text="   ·   ".join(parts))
        except Exception:
            pass

    def _preload_market(self):
        try:
            self.market.ensure_loaded()
            self.root.after(0, self._refresh_meta)
        except Exception:
            pass

    # ---------------- clipboard / valoración ----------------
    def poll_clipboard(self):
        try:
            text = self.root.clipboard_get()
        except Exception:
            text = ""
        if text and text != self.last_clipboard and looks_like_poe_item(text):
            self.last_clipboard = text
            self.check_text_async(text)
        self.root.after(int(self.config.get("poll_ms", 600)), self.poll_clipboard)

    def manual_check(self):
        try:
            text = self.root.clipboard_get()
        except Exception:
            text = ""
        if not looks_like_poe_item(text):
            self.set_status("El portapapeles no parece un ítem de PoE2.")
            return
        self.last_clipboard = text
        self.check_text_async(text)

    def check_text_async(self, text):
        if self._busy:
            return
        self._busy = True
        self._begin_item(text)
        self.set_status("Analizando ítem…")
        threading.Thread(target=self._worker_check, args=(text,), daemon=True).start()

    def _worker_check(self, text):
        try:
            item = parse_item_text(text)
            result = self.valuator.value(item)
            self.advisor.annotate(item, result)
            try:
                result.roll_quality_text = roll_quality_text(item)
            except Exception:
                result.roll_quality_text = ""
            append_history(item, result)
            icon = self._fetch_icon(result, item)
            self.root.after(0, lambda: self.render_result(item, result, icon))
        except Exception as exc:
            msg = "Error analizando ítem:\n" + "".join(traceback.format_exception_only(type(exc), exc))
            self.root.after(0, lambda: self._set_detail(msg))
        finally:
            self.root.after(0, lambda: setattr(self, "_busy", False))

    def _set_detail(self, content):
        self.detail_box.configure(state="normal")
        self.detail_box.delete("0.0", "end")
        self.detail_box.insert("0.0", content)
        self.detail_box.configure(state="disabled")

    def _first_meaningful_line(self, text):
        for ln in (text or "").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            low = ln.lower()
            if low.startswith(("item class", "rarity", "rareza", "clase de")):
                continue
            return ln
        return ""

    def _begin_item(self, text):
        import datetime
        first = self._first_meaningful_line(text)
        self._copied_at = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            self.name_lbl.configure(text=("Analizando: " + first) if first else "Analizando \u00edtem\u2026")
            self.sub_lbl.configure(text=f"reci\u00e9n copiado \u00b7 {self._copied_at}")
            self.price_lbl.configure(text="\u2026")
            self.chip_quick.configure(text="\u2014")
            self.chip_fair.configure(text="\u2014")
            self.chip_amb.configure(text="\u2014")
            self._set_icon(None)
        except Exception:
            pass

    def _set_icon(self, pil_img):
        try:
            if pil_img is None:
                self._icon_imgref = None
                try:
                    self.icon_lbl.place_forget()
                except Exception:
                    pass
                return
            img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(64, 64))
            self._icon_imgref = img
            self.icon_lbl.configure(image=img, text="")
            self.icon_lbl.place(relx=1.0, x=-12, y=10, anchor="ne")
        except Exception:
            pass

    def _fetch_icon(self, result, item=None):
        """Devuelve la imagen (miniatura) del item copiado.

        1) IconUrl del match de mercado (uniques/currency/runas/gemas).
        2) IconUrl que se trajo de un comparable del trade (rares: misma base = mismo arte).
        3) Fallback: busca en poe2scout por nombre/base por si comparte arte.
        """
        try:
            m = getattr(result, "raw_market_match", None) or {}
            url = m.get("IconUrl")
            if not url and item is not None and getattr(self, "market", None) is not None:
                try:
                    mk = self.market.find_market_item(item)
                    if mk:
                        url = mk.get("IconUrl")
                except Exception:
                    pass
            if not url:
                return None
            import urllib.request, io as _io
            from PIL import Image
            req = urllib.request.Request(url, headers={"User-Agent": "poe2valuator"})
            raw = urllib.request.urlopen(req, timeout=6).read()
            return Image.open(_io.BytesIO(raw)).convert("RGBA")
        except Exception:
            return None

    def render_result(self, item, result, icon=None):
        self.last_item = item
        self.last_result = result
        sub = " · ".join([p for p in [item.base_type, f"ilvl {item.item_level}" if item.item_level else "", item.category] if p])
        if self._copied_at:
            sub = (sub + "   ·   " if sub else "") + f"copiado {self._copied_at}"
        self.name_lbl.configure(text=result.title or item.display_name)
        self.sub_lbl.configure(text=sub or "—")
        self._set_icon(icon)
        self.price_lbl.configure(text=result.price_text)
        self.chip_quick.configure(text=result.quick_sell or "—")
        self.chip_fair.configure(text=result.fair_price or "—")
        self.chip_amb.configure(text=result.ambitious_price or "—")

        # Badge de build
        if result.build_fit is not None:
            if result.build_fit >= 55:
                col, rec = C_GREEN, "QUÉDATELO / pruébalo"
            elif result.build_fit >= 30:
                col, rec = C_YELLOW, "Compáralo con lo que usas"
            else:
                col, rec = C_RED, f"Véndelo ({result.quick_sell})"
            self.badge.configure(
                text=f"  {result.build_verdict}   ·   afinidad {result.build_fit:g}/100   ·   {rec}",
                fg_color=col)
            self.badge.pack(fill="x", padx=10, pady=(0, 6), after=self.hero)
        else:
            self.badge.pack_forget()

        # Detalle
        lines = []
        verdict = gold_decision(result.market_value_ex, self.config.get("convert_to_gold_below_ex", 1.0))
        if verdict and (result.market_value_ex > 0 or item.rarity in {"Normal", "Magic", "Rare", "Unique"}):
            if verdict == "MERCADO":
                lines.append(f"DECISIÓN: ✅ VENDER EN MERCADO (~{result.market_value_ex:g} ex)")
            else:
                gold_est = estimate_vendor_gold(item)
                tip = f" · {gold_est}" if gold_est else ""
                lines.append(f"DECISIÓN: 🪙 CONVERTIR EN ORO con el mercader (mercado ~{result.market_value_ex:g} ex){tip}")
            lines.append("")
        if result.build_fit is not None:
            if result.build_reasons:
                lines.append("PARA TU BUILD — aporta: " + ", ".join(result.build_reasons[:8]))
            if result.build_irrelevant:
                lines.append("No aporta: " + ", ".join(result.build_irrelevant[:5]))
            lines.append("")
        if result.compare_text:
            lines.append("VS TU EQUIPADO")
            lines.append("  " + result.compare_text)
            lines.append("")
        if result.roll_quality_text:
            lines.append("CALIDAD DE ROLLS (vs tope)")
            lines.append("  " + result.roll_quality_text)
            lines.append("")
        lines.append("STATS DETECTADOS")
        if item.stats:
            for k, v in sorted(item.stats.items()):
                lines.append(f"  {k}: {v:g}")
        else:
            lines.append("  — sin stats clave —")
        lines.append("")
        lines.append("POR QUÉ VALE ESTO")
        for r in result.reasons:
            lines.append(f"  + {r}")
        if result.warnings:
            lines.append("")
            lines.append("OJO")
            for w in result.warnings:
                lines.append(f"  ! {w}")
        if item.mod_lines:
            lines.append("")
            lines.append("MODS LEÍDOS")
            for m in item.mod_lines[:14]:
                lines.append(f"  - {m}")
        self._set_detail("\n".join(lines))
        self.sub_lbl.configure(text=(sub + f"   ·   {result.confidence} · {result.source}") if sub else result.source)
        self.set_status(f"Último check: {datetime.now().strftime('%H:%M:%S')}")

    # ---------------- mercado / trade / build (reutiliza lógica) ----------------
    def refresh_market(self):
        def job():
            try:
                if CACHE_PATH.exists():
                    CACHE_PATH.unlink()
            except Exception:
                pass
            self.market._items = None
            self.set_status_threadsafe("Actualizando precios…")
            self.market.ensure_loaded()
            self.root.after(0, self._refresh_meta)
        threading.Thread(target=job, daemon=True).start()

    def open_trade_search(self):
        item = self.last_item
        league = self.market.resolved_league or str(self.config.get("league", "Runes of Aldur"))
        if item and item.rarity in {"Rare", "Magic"} and item.category != "currency":
            threading.Thread(target=self._assisted_trade, args=(item, league), daemon=True).start()
            return
        self._name_trade(item, league)

    def _name_trade(self, item, league):
        url = f"{TRADE2_WEB}{urllib.parse.quote(league)}"
        query = (item.name or item.base_type or "") if item else ""
        try:
            if query:
                self.root.clipboard_clear()
                self.root.clipboard_append(query)
            webbrowser.open(url)
            self.set_status(f"Trade abierto ({league})" + (f" · copiado: {query}" if query else ""))
        except Exception as exc:
            self.set_status(f"No pude abrir el trade: {exc}")

    def _assisted_trade(self, item, league):
        query = build_trade2_query(item)
        if not query:
            self.root.after(0, lambda: self._name_trade(item, league))
            return
        self.set_status_threadsafe("Armando comparables en el trade…")
        ua = str(self.config.get("user_agent", DEFAULT_CONFIG["user_agent"]))
        n = len(query["query"].get("stats", [{"filters": []}])[0]["filters"]) if query["query"].get("stats") else 0
        try:
            data = json.dumps(query).encode("utf-8")
            req = urllib.request.Request(f"{TRADE2_API}{urllib.parse.quote(league)}", data=data,
                  headers={"User-Agent": ua, "Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            sid = payload.get("id")
            count = len(payload.get("result") or [])
            if sid:
                webbrowser.open(f"{TRADE2_WEB}{urllib.parse.quote(league)}/{sid}")
                self.set_status_threadsafe(f"Trade: {n} filtros · {count} listings")
                return
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                self.set_status_threadsafe("Trade: rate limit (429), espera unos segundos.")
                return
            self.set_status_threadsafe(f"Trade error {exc.code}; abriendo por base.")
        except Exception as exc:
            self.set_status_threadsafe(f"No pude consultar el trade ({exc}).")
        self.root.after(0, lambda: self._name_trade(item, league))

    def toggle_auto_trade(self):
        new = bool(self.auto_sw.get())
        self.config["auto_trade_comparables"] = new
        self.set_status("Auto-precio ON: rares consultan comparables reales." if new
                        else "Auto-precio OFF: rares con heurística local.")

    def load_build_file(self):
        try:
            start = self.config.get("build_file") or default_build_dir()
            initial_dir = str(Path(start).parent) if Path(start).suffix else start
            path = filedialog.askopenfilename(title="Selecciona tu .build (PoE2 / Path of Building / Descargas)",
                   initialdir=initial_dir, filetypes=[("PoE build", "*.build *.json"), ("Todos", "*.*")])
        except Exception:
            path = ""
        if not path:
            return
        if self.advisor.load(path):
            save_config(self.config)
            self._refresh_meta()
            p = self.advisor.profile
            self.set_status(f"Build cargada: {p['name']} · {p['weapon']} · {', '.join(a.upper() for a in p['attrs'])}")
        else:
            self.set_status("No se pudo cargar la build.")

    def generate_filter_from_build(self):
        if not self.advisor.profile:
            self.set_status("Primero carga tu build (🧬 Build).")
            return
        if not _generate_filter:
            self.set_status("No encuentro build_to_filter.py junto al overlay.")
            return
        try:
            prof = self.advisor.profile
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", prof.get("name", "build")).strip("_") or "build"
            out = BASE_DIR / f"{safe}.filter"
            out.write_text(_generate_filter(prof), encoding="utf-8")
            self.set_status(f"Filtro generado: {out.name}")
            try:
                if os.name == "nt":
                    os.startfile(str(BASE_DIR))  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception as exc:
            self.set_status(f"No pude generar el filtro: {exc}")

    def open_history_location(self):
        try:
            if os.name == "nt":
                os.startfile(str(BASE_DIR))  # type: ignore[attr-defined]
            else:
                self.set_status(str(BASE_DIR))
        except Exception:
            self.set_status(str(BASE_DIR))


def main() -> None:
    if HAS_CTK:
        try:
            ctk.set_appearance_mode("dark")
            root = ctk.CTk()
            OverlayAppModern(root)
            root.mainloop()
            return
        except Exception as exc:
            print("UI moderna falló, usando la clásica:", exc)
            try:
                root.destroy()
            except Exception:
                pass
    if tk is None:
        print("Tkinter no está disponible en este Python.")
        return
    root = tk.Tk()
    OverlayApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
