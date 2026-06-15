"""
build_to_filter.py  —  by Polietileno
====================================
Genera un loot filter (.filter) de Path of Exile 2 **a la medida de una build**,
a partir de un archivo `.build` exportado desde poe.ninja.

Qué hace
--------
- Lee cualquier `.build` (JSON con name/ascendancy/passives/skills).
- Deriva un "perfil" de la build:
    * clase de arma (Spears, Bows, Quarterstaves, ...) a partir de las skills/pasivas,
    * atributo(s) principal(es) (Dex/Int/Str) por conteo de nodos de pasivas,
    * tipo de defensa preferido (Evasion / Energy Shield / Armour) según el atributo,
    * temas de daño (crit, proyectil, frío, etc.) sólo para comentarios.
- Escribe un `.filter` de PoE2 que:
    * resalta MUCHO la clase de arma de la build (rares + bases para craftear),
    * resalta las BASES de armadura cuya familia corresponde al atributo de la build
      (p. ej. evasión "Vest/Garb/Jacket" para una build de destreza),
    * resalta TODOS los rares de los slots usados + joyería + jewels,
    * resalta QoL: currency valioso, runas, gemas sin tallar, waystones,
    * baja el ruido de armas de otras clases y bases del atributo equivocado.

Limitación honesta
------------------
Un filtro de suelo de PoE2 NO puede leer los MODS de un rare; sólo conoce clase,
base, rareza, ilvl, sockets y calidad. Por eso este filtro resalta las *bases*
correctas para tu build, pero para saber si un rare concreto tiene los mods que te
sirven hay que leerlo (Ctrl+C) con el overlay. Ambos se complementan.

El match de BaseType en PoE2 es por substring, así que usamos "familias" de base
(p. ej. "Vest" matchea "Leather Vest", "Studded Vest", etc.). Las tablas de familias
son editables aquí abajo si quieres ajustar algo.

Uso
---
    python build_to_filter.py "Spirit Walker - Level 94 - Morttinian - poe.ninja.build"
    python build_to_filter.py mibuild.build -o mi_filtro.filter
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

# --------------------------------------------------------------------------------------
# Tablas editables (PoE2). El match de BaseType es por substring, así que basta la "familia".
# attrs: 'str' = Armadura, 'dex' = Evasión, 'int' = Energy Shield (y combinaciones híbridas).
# --------------------------------------------------------------------------------------

# Detección de clase de arma a partir de texto de skills/pasivas.
WEAPON_SIGNALS = {
    "Spears": ["spear"],
    "Quarterstaves": ["quarterstaff", "quarterstave", "warstaff", "staff_melee"],
    "Bows": ["bow", "arrow"],
    "Crossbows": ["crossbow", "bolt"],
    "Wands": ["wand"],
    "Sceptres": ["sceptre", "scepter"],
    "Staves": ["staff", "stave"],
    "One Hand Maces": ["onemace", "one_hand_mace"],
    "Two Hand Maces": ["twomace", "two_hand_mace", "mace"],
    "Flails": ["flail"],
    "Daggers": ["dagger"],
    "Claws": ["claw"],
}

# Familias de base por slot (Class de PoE2) y atributo. Editable.
# Cada entrada: (substring_de_base, set_de_atributos)
ARMOUR_FAMILIES = {
    "Body Armours": [
        ("Cuirass", {"str"}), ("Plate", {"str"}), ("Regalia", {"str"}),
        ("Vest", {"dex"}), ("Garb", {"dex"}), ("Jacket", {"dex"}),
        ("Robe", {"int"}), ("Raiment", {"int"}),
        ("Mail", {"str", "dex"}), ("Ringmail", {"str", "dex"}),
        ("Vestments", {"str", "int"}),
        ("Mantle", {"dex", "int"}),
    ],
    "Helmets": [
        ("Greathelm", {"str"}), ("Helm", {"str"}), ("Visor", {"str"}), ("Visage", {"str"}),
        ("Hood", {"dex"}), ("Cap", {"dex"}), ("Mask", {"dex"}),
        ("Circlet", {"int"}), ("Tiara", {"int"}),
        ("Crown", {"str", "int"}),
    ],
    "Gloves": [
        ("Gauntlets", {"str"}), ("Mitts", {"str"}), ("Manchettes", {"str"}),
        ("Bracers", {"dex"}), ("Wraps", {"dex"}),
        ("Cuffs", {"int"}),
        ("Gloves", {"str", "dex"}),
    ],
    "Boots": [
        ("Greaves", {"str"}), ("Sabatons", {"str"}), ("Cuisses", {"str"}),
        ("Boots", {"dex"}), ("Shoes", {"dex"}),
        ("Slippers", {"int"}), ("Sandals", {"dex", "int"}),
        ("Leggings", {"dex", "int"}),
    ],
}

# Slots de gear que casi cualquier build usa (para resaltar rares).
GEAR_SLOTS = ["Body Armours", "Helmets", "Gloves", "Boots"]
JEWELRY = ["Amulets", "Rings", "Belts"]
OFFHAND = {"Bows": [], "Crossbows": []}  # bows/crossbows no usan offhand; el resto puede usar Foci/Shields/Quivers

# Deteccion fiable del arma desde el gear equipado (exports de mobalytics traen inventory_slots).
# El orden importa: "crossbow" antes que "bow", "quarterstaff" antes que "staff".
WEAPON_BASE_TO_CLASS = [
    ("crossbow", "Crossbows"),
    ("quarterstaff", "Quarterstaves"), ("quarterstave", "Quarterstaves"),
    ("spear", "Spears"),
    ("bow", "Bows"),
    ("wand", "Wands"),
    ("sceptre", "Sceptres"), ("scepter", "Sceptres"),
    ("staff", "Staves"), ("stave", "Staves"),
    ("flail", "Flails"),
    ("dagger", "Daggers"),
    ("claw", "Claws"),
    ("mace", "Two Hand Maces"),
]


def weapon_from_inventory(data: dict) -> str | None:
    """Lee el arma realmente equipada (Weapon1) de inventory_slots y devuelve su clase PoE2."""
    slots = data.get("inventory_slots") or []
    # Preferir Weapon1; si no, cualquier slot que empiece con "Weapon".
    candidates = [s for s in slots if str(s.get("inventory_id", "")).lower().startswith("weapon")]
    candidates.sort(key=lambda s: str(s.get("inventory_id", "")))
    for s in candidates:
        # En un arma rara la 1a linea es el NOMBRE (p. ej. "Twister"), no la base;
        # la base ("Hunting Spear") va en la 2a linea. Por eso escaneamos TODO el
        # bloque, no solo la primera linea, para no perder el arma equipada.
        text = (s.get("additional_text", "") or "").lower()
        if not text.strip():
            continue
        for kw, cls in WEAPON_BASE_TO_CLASS:
            if kw in text:
                return cls
    return None


# Pista de arma por ascendencia (cuando no hay arma equipada ni nodos claros).
# Las gemas/skills NO son fiables (una build de lanza puede usar gemas de arco), por eso
# esto va por encima de la deteccion por nombres de skills.
ASCENDANCY_WEAPON_HINT = {
    "huntress": "Spears",
    "amazon": "Spears",
    "deadeye": "Bows", "pathfinder": "Bows", "ranger": "Bows",
    "monk": "Quarterstaves", "invoker": "Quarterstaves", "acolyte": "Quarterstaves", "chayula": "Quarterstaves",
    "mercenary": "Crossbows", "witchhunter": "Crossbows", "gemling": "Crossbows",
    "titan": "Two Hand Maces", "warbringer": "Two Hand Maces", "warrior": "Two Hand Maces", "smith": "Two Hand Maces",
}


def weapon_from_ascendancy(ascendancy: str) -> str | None:
    a = (ascendancy or "").lower()
    for kw, cls in ASCENDANCY_WEAPON_HINT.items():
        if kw in a:
            return cls
    return None


ALL_WEAPON_CLASSES = list(WEAPON_SIGNALS.keys())

# Currency de alto valor a resaltar siempre (substring por BaseType).
CHASE_CURRENCY = [
    "Mirror of Kalandra", "Divine Orb", "Perfect Jeweller's Orb", "Perfect Exalted Orb",
    "Perfect Chaos Orb", "Perfect Regal Orb", "Hinekora's Lock", "Orb of Annulment",
    "Greater Exalted Orb", "Fracturing Orb", "Chaos Orb",
]

# --------------------------------------------------------------------------------------
# Perfil de build
# --------------------------------------------------------------------------------------

ATTR_DEFENSE = {"str": "Armadura", "dex": "Evasión", "int": "Energy Shield"}

PASSIVE_THEMES = {
    "crit": ["critical"], "projectile": ["projectil"], "spear": ["spear"],
    "cold": ["cold"], "lightning": ["lightning"], "fire": ["fire"], "chaos": ["chaos"],
    "attack": ["attack", "melee"], "speed": ["speed"], "minion": ["minion"],
    "spirit": ["spirit"], "evasion": ["evasion"], "energy_shield": ["energy", "shield"],
    "armour": ["armour", "armor"], "life": ["life"], "elemental": ["elemental"],
}


def _pretty(mid: str) -> str:
    base = mid.split("/")[-1]
    base = base.replace("SkillGem", "").replace("SupportGem", "").replace("Ascendancy", "")
    base = base.replace("Player Default", "").replace("Metadata", "")
    return re.sub(r"(?<!^)(?=[A-Z])", " ", base).strip()


def build_profile(data: dict) -> dict:
    name = data.get("name", "Build")
    ascendancy = data.get("ascendancy", "")
    passive_ids = [str(p.get("id", "")).lower() for p in data.get("passives", [])]
    skill_blob = " ".join(_pretty(s.get("id", "")) for s in data.get("skills", [])).lower()
    all_text = " ".join(passive_ids) + " " + skill_blob

    # 1) Clase de arma. Prioridad: (a) arma equipada, (b) nodos de pasivas, (c) nombres de skills.
    #    Las pasivas son mas fiables que las skills (una build de spear usa skills con nombre de arco).
    passive_text = " ".join(passive_ids)

    def _score(text):
        sc: Counter = Counter()
        for wclass, kws in WEAPON_SIGNALS.items():
            for kw in kws:
                sc[wclass] += text.count(kw)
        return sc

    weapon_score = _score(passive_text)
    weapon = weapon_score.most_common(1)[0][0] if weapon_score and weapon_score.most_common(1)[0][1] else None
    # Si las pasivas no dicen nada, usar la ascendencia (Huntress = Spears, etc.).
    if weapon is None:
        weapon = weapon_from_ascendancy(ascendancy)
    # Ultimo recurso: nombres de skills (poco fiable: las gemas pueden ser de otro tipo).
    if weapon is None:
        sk = _score(all_text)
        weapon = sk.most_common(1)[0][0] if sk and sk.most_common(1)[0][1] else None
    # El arma realmente equipada manda sobre todo lo demas.
    weapon_equipped = weapon_from_inventory(data)
    if weapon_equipped:
        weapon = weapon_equipped

    # 2) Atributos por conteo de nodos
    attr_score = Counter()
    for pid in passive_ids:
        if "dexterity" in pid or re.search(r"\bdex", pid):
            attr_score["dex"] += 1
        if "intelligence" in pid or re.search(r"\bint", pid):
            attr_score["int"] += 1
        if "strength" in pid or re.search(r"\bstr", pid):
            attr_score["str"] += 1
    # Defensa también informa el atributo
    for pid in passive_ids:
        if "evasion" in pid:
            attr_score["dex"] += 0.5
        if "energy" in pid or "shield" in pid:
            attr_score["int"] += 0.5
        if "armour" in pid or "armor" in pid:
            attr_score["str"] += 0.5
    ranked = [a for a, _ in attr_score.most_common() if attr_score[a] > 0]
    primary_attrs = ranked[:2] if len(ranked) >= 2 else (ranked or ["dex"])

    # 3) Temas (para comentarios)
    theme_score = Counter()
    for pid in passive_ids:
        for theme, kws in PASSIVE_THEMES.items():
            if any(k in pid for k in kws):
                theme_score[theme] += 1
    themes = [t for t, _ in theme_score.most_common(6)]

    return {
        "name": name,
        "ascendancy": ascendancy,
        "weapon": weapon,
        "attrs": primary_attrs,
        "defenses": [ATTR_DEFENSE[a] for a in primary_attrs if a in ATTR_DEFENSE],
        "themes": themes,
    }


# --------------------------------------------------------------------------------------
# Generación del filtro
# --------------------------------------------------------------------------------------

def _q(items) -> str:
    return " ".join(f'"{i}"' for i in items)


def preferred_bases(profile: dict) -> dict:
    """Para cada slot, devuelve (bases preferidas según atributo, bases de atributo equivocado)."""
    attrs = set(profile["attrs"])
    out = {}
    for slot, families in ARMOUR_FAMILIES.items():
        good, bad = [], []
        for sub, fam_attrs in families:
            if fam_attrs & attrs:
                good.append(sub)
            else:
                bad.append(sub)
        out[slot] = (good, bad)
    return out


def block(action: str, conditions: list[str], styles: list[str]) -> str:
    lines = [action]
    lines += [f"    {c}" for c in conditions]
    lines += [f"    {s}" for s in styles]
    return "\n".join(lines) + "\n"


def generate_filter(profile: dict) -> str:
    weapon = profile["weapon"]
    attrs = profile["attrs"]
    pref = preferred_bases(profile)
    off_weapons = [w for w in ALL_WEAPON_CLASSES if w != weapon]

    # Estilos reutilizables (R G B)
    S_WEAPON = ["SetFontSize 45", "SetTextColor 255 255 255", "SetBorderColor 255 200 60",
                "SetBackgroundColor 90 40 0", 'PlayEffect Yellow', "MinimapIcon 0 Yellow Diamond",
                "PlayAlertSound 1 300"]
    S_WEAPON_BASE = ["SetFontSize 38", "SetTextColor 255 230 150", "SetBorderColor 150 110 30",
                     "SetBackgroundColor 35 25 0"]
    S_RARE_GEAR = ["SetFontSize 40", "SetTextColor 255 255 120", "SetBorderColor 200 200 80",
                   "SetBackgroundColor 30 30 0"]
    S_PREF_BASE = ["SetFontSize 36", "SetTextColor 180 255 180", "SetBorderColor 80 160 80"]
    S_JEWEL = ["SetFontSize 40", "SetTextColor 0 240 190", "SetBorderColor 0 200 160",
               "SetBackgroundColor 0 40 35", "MinimapIcon 1 Cyan Circle", "PlayEffect Cyan"]
    S_CHASE = ["SetFontSize 45", "SetTextColor 255 0 0", "SetBorderColor 255 0 0",
               "SetBackgroundColor 255 255 255", "MinimapIcon 0 Red Star", "PlayEffect Red",
               "PlayAlertSound 6 300"]
    S_CURR = ["SetFontSize 38", "SetTextColor 170 255 170", "SetBorderColor 120 200 120"]
    S_GEMS = ["SetFontSize 40", "SetTextColor 200 140 255", "SetBorderColor 170 90 230",
              "SetBackgroundColor 25 0 40", "MinimapIcon 1 Purple Triangle"]
    S_DIM = ["SetFontSize 30", "SetTextColor 130 130 130", "SetBorderColor 60 60 60"]

    out: list[str] = []
    out.append(f"#==================================================================")
    out.append(f"# Loot filter para build: {profile['name']}  ({profile['ascendancy']})")
    out.append(f"# Arma: {weapon or '—'} | Atributos: {', '.join(a.upper() for a in attrs)}"
               f" | Defensa: {', '.join(profile['defenses']) or '—'}")
    out.append(f"# Temas: {', '.join(profile['themes'])}")
    out.append(f"# Generado por build_to_filter.py (by Polietileno) — editable a mano.")
    out.append(f"# NOTA: un filtro no lee mods de rares; usa el overlay (Ctrl+C) para eso.")
    out.append(f"#==================================================================\n")

    # 1) Chase currency (siempre, arriba de todo)
    out.append("# --- Currency de alto valor ---")
    out.append(block("Show", [f"BaseType {_q(CHASE_CURRENCY)}"], S_CHASE))

    # 2) Arma de la build: rares (muy visible)
    if weapon:
        out.append(f"# --- Arma de la build: {weapon} (rares) ---")
        out.append(block("Show", [f'Class "{weapon}"', "Rarity Rare"], S_WEAPON))
        out.append(f"# --- Arma de la build: {weapon} (bases para craftear, ilvl alto) ---")
        out.append(block("Show", [f'Class "{weapon}"', "Rarity Normal Magic", "ItemLevel >= 65"], S_WEAPON_BASE))

    # 3) Rares de slots de gear + joyería + jewels + offhand
    rare_classes = GEAR_SLOTS + JEWELRY + ["Jewels", "Quivers", "Foci", "Shields"]
    out.append("# --- Rares de gear/joyería/jewels (revísalos con el overlay) ---")
    out.append(block("Show", [f"Class {_q(rare_classes)}", "Rarity Rare"], S_RARE_GEAR))

    # 4) Jewels siempre + gemas sin tallar
    out.append("# --- Jewels y gemas sin tallar ---")
    out.append(block("Show", ['Class "Jewels"'], S_JEWEL))
    out.append(block("Show", ['Class "Uncut Spirit Gem" "Uncut Skill Gem" "Uncut Support Gem"'], S_GEMS))

    # 5) Bases preferidas por atributo (Normal/Magic) para craftear
    out.append(f"# --- Bases preferidas por atributo ({', '.join(profile['defenses'])}) para craftear ---")
    for slot in GEAR_SLOTS:
        good, _bad = pref[slot]
        if good:
            out.append(block(
                "Show",
                [f'Class "{slot}"', f"BaseType {_q(good)}", "Rarity Normal Magic", "ItemLevel >= 70"],
                S_PREF_BASE,
            ))

    # 6) Runas y waystones (QoL)
    out.append("# --- Runas y Waystones ---")
    out.append(block("Show", ['Class "Rune"'], S_CURR))
    out.append(block("Show", ['Class "Waystone"', "WaystoneTier >= 1"], S_CURR))

    # 7) Currency genérico (todo lo demás stackable)
    out.append("# --- Resto de currency ---")
    out.append(block("Show", ['Class "Currency" "Stackable Currency"'], S_CURR))

    # 8) Bajar ruido: armas de otras clases en blanco/magic
    if off_weapons:
        out.append("# --- Atenuar armas de clases que esta build no usa (Normal/Magic) ---")
        out.append(block("Hide", [f"Class {_q(off_weapons)}", "Rarity Normal Magic"], []))

    # 9) Atenuar bases de atributo equivocado (Normal/Magic) en slots de gear
    out.append("# --- Atenuar bases del atributo equivocado (Normal/Magic) ---")
    for slot in GEAR_SLOTS:
        _good, bad = pref[slot]
        if bad:
            out.append(block("Hide", [f'Class "{slot}"', f"BaseType {_q(bad)}", "Rarity Normal Magic"], []))

    # 10) Catch-all: mostrar todo lo no contemplado (seguro)
    out.append("# --- Catch-all: mostrar el resto en pequeño ---")
    out.append(block("Show", [], S_DIM))

    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera un .filter de PoE2 desde un .build de poe.ninja")
    ap.add_argument("build", help="Ruta al archivo .build")
    ap.add_argument("-o", "--output", help="Ruta de salida .filter (por defecto junto al .build)")
    args = ap.parse_args()

    build_path = Path(args.build)
    data = json.loads(build_path.read_text(encoding="utf-8"))
    profile = build_profile(data)

    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", profile["name"]).strip("_") or "build"
    out_path = Path(args.output) if args.output else build_path.with_name(f"{safe}.filter")
    out_path.write_text(generate_filter(profile), encoding="utf-8")

    print("Perfil detectado:")
    print(f"  Build:      {profile['name']} ({profile['ascendancy']})")
    print(f"  Arma:       {profile['weapon']}")
    print(f"  Atributos:  {', '.join(profile['attrs'])}")
    print(f"  Defensa:    {', '.join(profile['defenses'])}")
    print(f"  Temas:      {', '.join(profile['themes'])}")
    print(f"\nFiltro escrito en: {out_path}")


if __name__ == "__main__":
    main()
