# pvp_rankings.py — PvP IV rankings for Great, Ultra, and Master League
#
# PvP IVs are DIFFERENT from PvE IVs. In PvP:
# - You want the highest stat product at or under the league CP cap
# - Lower ATK IVs can be better (ATK increases breakpoints but also CP,
#   letting you power up more, gaining more bulk)
# - Classic rankings: rank 1 = best possible IV combo for that league
#
# This module computes stat product rankings for a Pokémon at a given league cap.
import logging
import math

from iv_calculator import CPM, BASE_STATS, calc_cp
from evolution_chains import get_evolutions, normalize_name
log = logging.getLogger(__name__)
LEAGUE_CAPS = {
    "great":  1500,
    "ultra":  2500,
    "master": 10000,  # no cap — 15/15/15 is always rank 1
}



def stat_product(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, level) -> float:
    """Compute the PvP stat product at a given level."""
    cpm = CPM.get(level, 0)
    atk = (base_atk + iv_atk) * cpm
    def_ = (base_def + iv_def) * cpm
    sta = math.floor((base_sta + iv_sta) * cpm)
    return atk * def_ * sta

def best_level_for_cap(base_atk, base_def, base_sta,
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
                         league: str = "great", observed_level: float = None) -> dict:
    """
    Compute the PvP rank and stat product for a specific IV combo in a league.

    observed_level: the Pokemon's ACTUAL current level (from find_level()).
    If provided and it already exceeds the level needed to fit under the
    league's CP cap, the Pokemon is marked ineligible — it can never be
    powered DOWN, so no theoretical rank is meaningful.
    """
    name_key = normalize_name(pokemon_name)
    stats = BASE_STATS.get(name_key)
    cp_cap = LEAGUE_CAPS.get(league, 1500)
    if not stats:
        return {"league": league, "rank": None, "error": f"Unknown Pokemon {pokemon_name}"}
    b_atk, b_def, b_sta = stats["atk"], stats["def"], stats["sta"]

    # Master league has no CP cap — eligibility never applies there.
    if league == "master":
        max_level = max(CPM.keys())
        max_sp = stat_product(b_atk, b_def, b_sta, 15, 15, 15, max_level)
        target_sp = stat_product(b_atk, b_def, b_sta, iv_atk, iv_def, iv_sta, max_level)
        return {
            "league": "master",
            "rank": 1 if (iv_atk == 15 and iv_def == 15 and iv_sta == 15) else None,
            "eligible": True,
            "stat_product": round(target_sp, 1),
            "sp_pct_of_max": round(target_sp / max_sp * 100, 2),
            "best_level": max_level,
            "best_cp": calc_cp(b_atk, b_def, b_sta, iv_atk, iv_def, iv_sta, max_level),
        }

    target_level = best_level_for_cap(b_atk, b_def, b_sta, iv_atk, iv_def, iv_sta, cp_cap)
    if target_level is None:
        return {"league": league, "rank": None, "eligible": False,
                "error": "Cannot reach league CP cap"}

    # NEW — the actual eligibility check. If this Pokemon is already
    # leveled past the point where it fits under the cap, it's stuck
    # there permanently — powering down isn't possible in Pokemon GO.
    if observed_level is not None and observed_level > target_level:
        return {
            "league": league,
            "rank": None,
            "eligible": False,
            "error": (
                f"Current level {observed_level} already exceeds the level "
                f"needed for this league's CP cap (target level {target_level}) "
                f"— cannot power down, permanently ineligible"
            ),
        }

    target_sp = stat_product(b_atk, b_def, b_sta, iv_atk, iv_def, iv_sta, target_level)
    target_cp = calc_cp(b_atk, b_def, b_sta, iv_atk, iv_def, iv_sta, target_level)

    all_sps = []
    for a in range(16):
        for d in range(16):
            for s in range(16):
                lv = best_level_for_cap(b_atk, b_def, b_sta, a, d, s, cp_cap)
                if lv is None:
                    continue
                all_sps.append(stat_product(b_atk, b_def, b_sta, a, d, s, lv))
    all_sps.sort(reverse=True)
    max_sp = all_sps[0]

    rank = 1
    for sp in all_sps:
        if sp > target_sp:
            rank += 1
        else:
            break
    total = len(all_sps)
    percentile = round((1 - rank / total) * 100, 1)

    return {
        "league": league,
        "rank": rank,
        "eligible": True,
        "percentile": percentile,
        "stat_product": round(target_sp, 1),
        "sp_pct_of_max": round(target_sp / max_sp * 100, 2),
        "best_level": target_level,
        "best_cp": target_cp,
    }


def all_league_rankings(pokemon_name: str, iv_atk: int, iv_def: int, iv_sta: int,
                         observed_level: float = None) -> dict:
    """Get PvP rankings for all three leagues at once."""
    return {
        "great":  rank_ivs_for_league(pokemon_name, iv_atk, iv_def, iv_sta, "great", observed_level),
        "ultra":  rank_ivs_for_league(pokemon_name, iv_atk, iv_def, iv_sta, "ultra", observed_level),
        "master": rank_ivs_for_league(pokemon_name, iv_atk, iv_def, iv_sta, "master", observed_level),
    }


def all_league_rankings_with_evos(pokemon_name: str, iv_atk: int, iv_def: int, iv_sta: int,
                                   observed_level: float = None, is_shadow=False) -> dict:
    """
    Rankings for the Pokemon itself plus all its evolved forms.
    IVs are identical across evolutions — but CP is NOT, since evolving
    keeps the same level/CPM while jumping base stats. observed_level is
    passed through UNCHANGED to every evolution's ranking, since evolving
    doesn't let you re-level — a level-30 Charmeleon becomes a level-30
    Charizard, which may push it out of league eligibility entirely even
    if the pre-evolution form was still fine.
    """
    results = {}
    results[pokemon_name] = all_league_rankings(pokemon_name, iv_atk, iv_def, iv_sta, observed_level)
    evos = get_evolutions(pokemon_name)
    if not evos:
        log.debug(f"pvp_rankings: no evolutions found for {pokemon_name!r} — check EVOLUTION_CHAINS")
    for evo in get_evolutions(pokemon_name):
        results[evo] = all_league_rankings(evo, iv_atk, iv_def, iv_sta, observed_level)
    return results

