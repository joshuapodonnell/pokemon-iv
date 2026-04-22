# pvp_rankings.py — PvP IV rankings for Great, Ultra, and Master League
#
# PvP IVs are DIFFERENT from PvE IVs. In PvP:
# - You want the highest stat product at or under the league CP cap
# - Lower ATK IVs can be better (ATK increases breakpoints but also CP,
#   letting you power up more, gaining more bulk)
# - Classic rankings: rank 1 = best possible IV combo for that league
#
# This module computes stat product rankings for a Pokémon at a given league cap.

import math
from iv_calculator import CPM, BASE_STATS, calc_cp
from evolution_chains import get_evolutions

LEAGUE_CAPS = {
    "great":  1500,
    "ultra":  2500,
    "master": 10000,  # no cap — 15/15/15 is always rank 1
}



def all_league_rankings_with_evos(
    pokemon_name: str, iv_atk: int, iv_def: int, iv_sta: int
) -> dict:
    """
    Rankings for the Pokémon itself plus all its evolved forms.
    IVs are identical across evolutions in Pokémon GO.

    Returns:
    {
        "Panpour":   {"great": {...}, "ultra": {...}, "master": {...}},
        "Simipour":  {"great": {...}, "ultra": {...}, "master": {...}},
    }
    """
    results = {}

    # Rankings for the Pokémon itself
    results[pokemon_name] = all_league_rankings(pokemon_name, iv_atk, iv_def, iv_sta)

    # Rankings for each evolved form with the same IVs
    for evo in get_evolutions(pokemon_name):
        results[evo] = all_league_rankings(evo, iv_atk, iv_def, iv_sta)

    return results


def _stat_product(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, level) -> float:
    """Compute the PvP stat product at a given level."""
    cpm = CPM.get(level, 0)
    atk = (base_atk + iv_atk) * cpm
    def_ = (base_def + iv_def) * cpm
    sta = math.floor((base_sta + iv_sta) * cpm)
    return atk * def_ * sta

def _best_level_for_cap(base_atk, base_def, base_sta,
                         iv_atk, iv_def, iv_sta, cp_cap) -> float | None:
    """Find the highest level where CP <= cp_cap."""
    best_level = None
    for level in sorted(CPM.keys()):
        cp = calc_cp(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, level)
        if cp <= cp_cap:
            best_level = level
        else:
            break
    return best_level

def rank_ivs_for_league(pokemon_name: str, iv_atk: int, iv_def: int, iv_sta: int,
                         league: str = "great") -> dict:
    """
    Compute the PvP rank and stat product for a specific IV combo in a league.

    Returns:
        {
          "league": str,
          "rank": int,               # 1 = best possible for this species
          "percentile": float,       # what % of IV combos this beats
          "stat_product": float,
          "best_level": float,       # level to power up to
          "best_cp": int,
          "sp_pct_of_max": float,    # stat product as % of rank-1 combo
        }
    """
    name_key = pokemon_name.strip().title()
    stats = BASE_STATS.get(name_key)
    cp_cap = LEAGUE_CAPS.get(league, 1500)

    if not stats:
        return {"league": league, "rank": None, "error": f"Unknown Pokémon: {pokemon_name}"}

    b_atk, b_def, b_sta = stats["atk"], stats["def"], stats["sta"]

    # The IV combo we're evaluating
    target_level = _best_level_for_cap(b_atk, b_def, b_sta, iv_atk, iv_def, iv_sta, cp_cap)
    if target_level is None:
        return {"league": league, "rank": None, "error": "Cannot reach league CP cap"}

    target_sp = _stat_product(b_atk, b_def, b_sta, iv_atk, iv_def, iv_sta, target_level)
    target_cp = calc_cp(b_atk, b_def, b_sta, iv_atk, iv_def, iv_sta, target_level)

    # For master league — shortcut, just return the stat product rank vs 15/15/15
    if league == "master":
        max_level = max(CPM.keys())
        max_sp = _stat_product(b_atk, b_def, b_sta, 15, 15, 15, max_level)
        return {
            "league": "master",
            "rank": 1 if (iv_atk == 15 and iv_def == 15 and iv_sta == 15) else None,
            "stat_product": round(target_sp, 1),
            "sp_pct_of_max": round(target_sp / max_sp * 100, 2),
            "best_level": max_level,
            "best_cp": calc_cp(b_atk, b_def, b_sta, iv_atk, iv_def, iv_sta, max_level),
        }

    # For Great/Ultra — enumerate all 4096 IV combos and rank
    all_sps = []
    for a in range(16):
        for d in range(16):
            for s in range(16):
                lv = _best_level_for_cap(b_atk, b_def, b_sta, a, d, s, cp_cap)
                if lv is None:
                    continue
                sp = _stat_product(b_atk, b_def, b_sta, a, d, s, lv)
                all_sps.append(sp)

    all_sps.sort(reverse=True)
    max_sp = all_sps[0]

    # Find rank of our combo (1-indexed, ties share rank)
    rank = 1
    for sp in all_sps:
        if sp > target_sp:
            rank += 1
        else:
            break

    total = len(all_sps)
    percentile = round((1 - rank / total) * 100, 1)

    return {
        "league":       league,
        "rank":         rank,
        "percentile":   percentile,
        "stat_product": round(target_sp, 1),
        "sp_pct_of_max": round(target_sp / max_sp * 100, 2),
        "best_level":   target_level,
        "best_cp":      target_cp,
    }

def all_league_rankings(pokemon_name: str, iv_atk: int, iv_def: int, iv_sta: int) -> dict:
    """Get PvP rankings for all three leagues at once."""
    return {
        "great":  rank_ivs_for_league(pokemon_name, iv_atk, iv_def, iv_sta, "great"),
        "ultra":  rank_ivs_for_league(pokemon_name, iv_atk, iv_def, iv_sta, "ultra"),
        "master": rank_ivs_for_league(pokemon_name, iv_atk, iv_def, iv_sta, "master"),
    }
