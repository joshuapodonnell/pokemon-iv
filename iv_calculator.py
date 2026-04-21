# iv_calculator.py — Computes exact IV combinations from in-game data
#
# The CP formula:
#   CP = max(10, floor( (base_atk + iv_atk) * sqrt(base_def + iv_def)
#                       * sqrt(base_sta + iv_sta) * cpm^2 / 10 ))
#
# Given: CP, HP, stardust cost (→ level range), appraisal bars (ATK/DEF/STA IVs exactly)
# The appraisal bars tell us EXACT IVs (0–15 each) so we don't need to brute-force.
# We only need to find the matching level (CP multiplier) that fits CP + HP.

import math
import json
import os
from functools import lru_cache

# ── CP Multiplier table (level 1–51, every 0.5 level) ────────────────────────
# Source: Pokémon GO Hub / GameMaster (current as of level cap 50+buddy)
CPM = {
    1.0:  0.09400000, 1.5:  0.13513743, 2.0:  0.16639787, 2.5:  0.19265092,
    3.0:  0.21573247, 3.5:  0.23657266, 4.0:  0.25572005, 4.5:  0.27353038,
    5.0:  0.29024988, 5.5:  0.30605738, 6.0:  0.32108760, 6.5:  0.33544504,
    7.0:  0.34921268, 7.5:  0.36245775, 8.0:  0.37523560, 8.5:  0.38759242,
    9.0:  0.39956728, 9.5:  0.41119355, 10.0: 0.42250000, 10.5: 0.43292641,
    11.0: 0.44310755, 11.5: 0.45305996, 12.0: 0.46279840, 12.5: 0.47233609,
    13.0: 0.48168495, 13.5: 0.49085580, 14.0: 0.49985844, 14.5: 0.50870177,
    15.0: 0.51739395, 15.5: 0.52594251, 16.0: 0.53435430, 16.5: 0.54263574,
    17.0: 0.55079270, 17.5: 0.55883059, 18.0: 0.56675450, 18.5: 0.57456913,
    19.0: 0.58227890, 19.5: 0.58988791, 20.0: 0.59740000, 20.5: 0.60482367,
    21.0: 0.61215730, 21.5: 0.61940412, 22.0: 0.62656710, 22.5: 0.63364914,
    23.0: 0.64065295, 23.5: 0.64758097, 24.0: 0.65443563, 24.5: 0.66121925,
    25.0: 0.66793400, 25.5: 0.67458190, 26.0: 0.68116490, 26.5: 0.68768490,
    27.0: 0.69414365, 27.5: 0.70054287, 28.0: 0.70688420, 28.5: 0.71316911,
    29.0: 0.71939910, 29.5: 0.72557561, 30.0: 0.73170000, 30.5: 0.73474101,
    31.0: 0.73776950, 31.5: 0.74078559, 32.0: 0.74378943, 32.5: 0.74678121,
    33.0: 0.74976104, 33.5: 0.75272909, 34.0: 0.75568550, 34.5: 0.75863037,
    35.0: 0.76156384, 35.5: 0.76448606, 36.0: 0.76739717, 36.5: 0.77029727,
    37.0: 0.77318650, 37.5: 0.77606496, 38.0: 0.77893275, 38.5: 0.78179005,
    39.0: 0.78463700, 39.5: 0.78747361, 40.0: 0.79030000, 40.5: 0.79280397,
    41.0: 0.79530001, 41.5: 0.79780002, 42.0: 0.80030000, 42.5: 0.80280000,
    43.0: 0.80530000, 43.5: 0.80780000, 44.0: 0.81029999, 44.5: 0.81279999,
    45.0: 0.81529999, 45.5: 0.81779999, 46.0: 0.82029999, 46.5: 0.82279999,
    47.0: 0.82529999, 47.5: 0.82779999, 48.0: 0.83029999, 48.5: 0.83279999,
    49.0: 0.83529999, 49.5: 0.83779999, 50.0: 0.84029999,
    50.5: 0.84279999, 51.0: 0.84529999,  # Best Buddy boost levels
}

# Stardust cost → possible level ranges
# Source: Pokémon GO Hub (corrected — costs change at level 31+)
DUST_TO_LEVELS = {
    200:   [1.0, 1.5, 2.0, 2.5],
    400:   [3.0, 3.5, 4.0, 4.5],
    600:   [5.0, 5.5, 6.0, 6.5],
    800:   [7.0, 7.5, 8.0, 8.5],
    1000:  [9.0, 9.5, 10.0, 10.5],
    1300:  [11.0, 11.5, 12.0, 12.5],
    1600:  [13.0, 13.5, 14.0, 14.5],
    1900:  [15.0, 15.5, 16.0, 16.5],
    2200:  [17.0, 17.5, 18.0, 18.5],
    2500:  [19.0, 19.5, 20.0, 20.5],
    3000:  [21.0, 21.5, 22.0, 22.5],
    3500:  [23.0, 23.5, 24.0, 24.5],
    4000:  [25.0, 25.5, 26.0, 26.5],
    4500:  [27.0, 27.5, 28.0, 28.5],
    5000:  [29.0, 29.5, 30.0, 30.5],
    6000:  [31.0, 31.5, 32.0, 32.5],
    7000:  [33.0, 33.5, 34.0, 34.5],
    8000:  [35.0, 35.5, 36.0, 36.5],
    9000:  [37.0, 37.5, 38.0, 38.5],
    10000: [39.0, 39.5, 40.0, 40.5],
    11000: [41.0, 41.5, 42.0, 42.5],
    12000: [43.0, 43.5, 44.0, 44.5],
    13000: [45.0, 45.5, 46.0, 46.5],
    14000: [47.0, 47.5, 48.0, 48.5],
    15000: [49.0, 49.5, 50.0],
}

def load_pokemon_base_stats() -> dict:
    """
    Load base stats from bundled JSON file.
    Falls back to a small hardcoded set if file not found.
    Full file should be downloaded from PokeAPI / GameMaster.
    """
    stats_file = os.path.join(os.path.dirname(__file__), "data", "base_stats.json")
    if os.path.exists(stats_file):
        with open(stats_file) as f:
            return json.load(f)
    # Minimal fallback for testing — top 20 common Pokemon
    return {
        "Bulbasaur":   {"atk": 118, "def": 111, "sta": 128},
        "Charmander":  {"atk": 116, "def":  93, "sta": 118},
        "Squirtle":    {"atk": 94,  "def": 121, "sta": 127},
        "Pikachu":     {"atk": 112, "def":  96, "sta": 111},
        "Eevee":       {"atk": 104, "def":  91, "sta": 146},
        "Mewtwo":      {"atk": 300, "def": 182, "sta": 214},
        "Gengar":      {"atk": 261, "def": 149, "sta": 155},
        "Dragonite":   {"atk": 263, "def": 198, "sta": 209},
        "Snorlax":     {"atk": 190, "def": 169, "sta": 330},
        "Machamp":     {"atk": 234, "def": 159, "sta": 207},
    }

BASE_STATS = load_pokemon_base_stats()

def calc_cp(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, level) -> int:
    cpm = CPM.get(level, 0)
    cp = ((base_atk + iv_atk)
          * math.sqrt(base_def + iv_def)
          * math.sqrt(base_sta + iv_sta)
          * cpm ** 2) / 10
    return max(10, math.floor(cp))

def calc_hp(base_sta, iv_sta, level) -> int:
    cpm = CPM.get(level, 0)
    return max(10, math.floor((base_sta + iv_sta) * cpm))

def iv_percentage(iv_atk, iv_def, iv_sta) -> float:
    """Overall IV% — sum of IVs out of max 45."""
    iv_atk = int(iv_atk) if iv_atk is not None else 0
    iv_def = int(iv_def) if iv_def is not None else 0
    iv_sta = int(iv_sta) if iv_sta is not None else 0
    return round((iv_atk + iv_def + iv_sta) / 45 * 100, 1)

def iv_star_rank(pct: float) -> str:
    """In-game star rank: 0★–4★ + 100%."""
    if pct == 100.0:  return "100% ✨"
    if pct >= 82.2:   return "3★"   # 37/45
    if pct >= 66.7:   return "2★"   # 30/45
    if pct >= 51.1:   return "1★"   # 23/45
    return "0★"

def find_level(pokemon_name: str, iv_atk: int, iv_def: int, iv_sta: int,
               observed_cp: int, observed_hp: int, dust_cost: int | None) -> float | None:
    """
    Given exact IVs (from appraisal bars) + observed CP + HP,
    find the matching level by iterating candidate levels.
    Returns the level as a float (e.g. 25.0) or None if no match found.
    """
    name_key = pokemon_name.strip().title()
    stats = BASE_STATS.get(name_key)
    if not stats:
        return None  # Unknown pokemon — needs data file

    candidate_levels = list(CPM.keys())
    if dust_cost and dust_cost in DUST_TO_LEVELS:
        candidate_levels = DUST_TO_LEVELS[dust_cost]

    for level in candidate_levels:
        cp = calc_cp(stats["atk"], stats["def"], stats["sta"],
                     iv_atk, iv_def, iv_sta, level)
        hp = calc_hp(stats["sta"], iv_sta, level)
        if cp == observed_cp and hp == observed_hp:
            return level

    # Widen search if exact match fails (rounding tolerance)
    for level in CPM.keys():
        cp = calc_cp(stats["atk"], stats["def"], stats["sta"],
                     iv_atk, iv_def, iv_sta, level)
        if abs(cp - observed_cp) <= 1:
            hp = calc_hp(stats["sta"], iv_sta, level)
            if abs(hp - observed_hp) <= 1:
                return level

    return None

def compute_ivs(pokemon_name: str, observed_cp: int, observed_hp: int,
                iv_atk: int, iv_def: int, iv_sta: int,
                dust_cost: int | None = None) -> dict:
    """
    Full IV result for a single Pokémon.
    Returns a dict with all IV data ready for the database.
    """
    level = find_level(pokemon_name, iv_atk, iv_def, iv_sta,
                       observed_cp, observed_hp, dust_cost)
    pct = iv_percentage(iv_atk, iv_def, iv_sta)

    return {
        "name":     pokemon_name,
        "cp":       observed_cp,
        "hp":       observed_hp,
        "dust":     dust_cost,
        "level":    level,
        "iv_atk":   iv_atk,
        "iv_def":   iv_def,
        "iv_sta":   iv_sta,
        "iv_pct":   pct,
        "iv_stars": iv_star_rank(pct),
    }
