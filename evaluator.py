# evaluator.py — Decides keep/transfer for new catches based on existing collection

from pvp_rankings import all_league_rankings_with_evos

# Thresholds — tune these to your preference
KEEP_RULES = {
    "iv_pct_min":       82.2,   # Keep any 3★+ regardless of PvP
    "gl_rank_max":      500,    # Keep if GL rank ≤ 500
    "ul_rank_max":      500,    # Keep if UL rank ≤ 500
    "evo_gl_rank_max":  500,    # Keep if any evolution is GL rank ≤ 500
    "evo_ul_rank_max":  500,    # Keep if any evolution is UL rank ≤ 500
    "perfect_iv":       True,   # Always keep 100% IV
    "zero_iv":            True,   # Always keep 0% IV
   # "lucky_trade_floor": 80.0,  # Keep if IV% ≥ 80 (lucky trade potential)
}
KEEP_SPECIES = frozenset({
        # Gen 1 Birds / Mewtwo / Mew
        "Articuno", "Zapdos", "Moltres", "Mewtwo", "Mew",
        # Gen 2
        "Raikou", "Entei", "Suicune", "Lugia", "Ho-Oh", "Celebi",
        # Gen 3
        "Regirock", "Regice", "Registeel", "Latias", "Latios",
        "Kyogre", "Groudon", "Rayquaza", "Jirachi", "Deoxys",
        # Gen 4
        "Uxie", "Mesprit", "Azelf", "Dialga", "Palkia", "Heatran",
        "Regigigas", "Giratina", "Cresselia", "Phione", "Manaphy",
        "Darkrai", "Shaymin", "Arceus",
        # Gen 5
        "Cobalion", "Terrakion", "Virizion", "Tornadus", "Thundurus",
        "Reshiram", "Zekrom", "Landorus", "Kyurem", "Keldeo",
        "Meloetta", "Genesect",
        # Gen 6
        "Xerneas", "Yveltal", "Zygarde", "Diancie", "Hoopa", "Volcanion",
        # Gen 7 + Ultra Beasts
        "Tapu Koko", "Tapu Lele", "Tapu Bulu", "Tapu Fini",
        "Cosmog", "Cosmoem", "Solgaleo", "Lunala", "Necrozma",
        "Magearna", "Marshadow", "Zeraora",
        "Nihilego", "Buzzwole", "Pheromosa", "Xurkitree",
        "Celesteela", "Kartana", "Guzzlord",
        "Poipole", "Naganadel", "Stakataka", "Blacephalon",
        # Gen 8
        "Zacian", "Zamazenta", "Eternatus", "Kubfu", "Urshifu",
        "Zarude", "Regieleki", "Regidrago", "Glastrier", "Spectrier", "Calyrex",
        # Gen 9
        "Wo-Chien", "Chien-Pao", "Ting-Lu", "Chi-Yu",
        "Koraidon", "Miraidon", "Ogerpon", "Terapagos",
    })

def evaluate_catch(conn, name, cp, iv_atk, iv_def, iv_sta, iv_pct,
                   pvp: dict, evo_rankings: dict) -> dict:
    """
    Returns a decision dict:
    {
        "action":  "KEEP" | "TRANSFER" | "REVIEW",
        "reasons": [...],
        "beats_existing": bool,   # True if this is better than best in DB
        "existing_best": dict | None,
    }
    """
    reasons = []
    action  = "TRANSFER"

    # ── Rule 1: Perfect IV / nundo
    is_hundo = (iv_atk == 15 and iv_def == 15 and iv_sta == 15)
    is_nundo = (iv_atk == 0 and iv_def == 0 and iv_sta == 0)
    if KEEP_RULES["perfect_iv"] and is_hundo:
        reasons.append("100% IV — hundo")
        action = "KEEP"
    if KEEP_RULES["zero_iv"] and is_nundo:
        reasons.append("0% IV — nundo")
        action = "KEEP"

    # ── Rule 2: High IV% (3★+)
    if iv_pct >= KEEP_RULES["iv_pct_min"]:
        reasons.append(f"{iv_pct}% IV (3★+)")
        action = "KEEP"



    # ── Rule 2.5: Legendary / Mythical / Ultra Beast — always keep
    if any(name.startswith(s) for s in KEEP_SPECIES):
        reasons.append("Legendary/mythical/UB — always keep")
        action = "KEEP"

    # # ── Rule 3: Lucky trade floor
    # if iv_pct >= KEEP_RULES["lucky_trade_floor"] and action != "KEEP":
    #     reasons.append(f"{iv_pct}% IV — lucky trade potential")
    #     action = "KEEP"

    # ── Rule 4: PvP rank on base species
    gl = pvp.get("great", {})
    ul = pvp.get("ultra", {})
    if gl.get("rank") and gl["rank"] <= KEEP_RULES["gl_rank_max"]:
        reasons.append(f"GL rank #{gl['rank']} (top {100-gl.get('percentile',0):.1f}%)")
        action = "KEEP"
    if ul.get("rank") and ul["rank"] <= KEEP_RULES["ul_rank_max"]:
        reasons.append(f"UL rank #{ul['rank']} (top {100-ul.get('percentile',0):.1f}%)")
        action = "KEEP"

    # ── Rule 5: Evolution PvP ranks
    for evo_name, evo_pvp in evo_rankings.items():
        evo_gl = evo_pvp.get("great", {})
        evo_ul = evo_pvp.get("ultra", {})
        if evo_gl.get("rank") and evo_gl["rank"] <= KEEP_RULES["evo_gl_rank_max"]:
            reasons.append(f"Evolves → {evo_name} GL rank #{evo_gl['rank']}")
            action = "KEEP"
        if evo_ul.get("rank") and evo_ul["rank"] <= KEEP_RULES["evo_ul_rank_max"]:
            reasons.append(f"Evolves → {evo_name} UL rank #{evo_ul['rank']}")
            action = "KEEP"

    # ── Rule 6: Compare against existing best in DB
    existing_top = get_best_in_db(conn, name)  # list of ≤5
    beats_existing = False

    if is_hundo or is_nundo:
        beats_existing = True
    elif existing_top:
        # [0] is already the best-ranked — ordered by gl_rank ASC
        best = existing_top[0]
        existing_gl = best["gl_rank"]
        new_gl = gl.get("rank")
        if new_gl and (existing_gl is None or new_gl < existing_gl):
            beats_existing = True
            reasons.append(
                f"NEW BEST for {name}: GL #{new_gl} beats current best #{existing_gl}"
            )
            action = "KEEP"
    else:
        reasons.append(f"First {name} in collection")
        action = "KEEP"
        beats_existing = True

    # ── Rule 7: OCR failure → flag for review
    if not is_hundo and not is_nundo:
        if name in ("Unknown", "") or cp == 0:
            action = "REVIEW"
            reasons.append("OCR uncertain — needs manual check")

    return {
        "action": action,
        "reasons": reasons,
        "beats_existing": beats_existing,
        "existing_best": existing_top[0] if existing_top else None,  # caller compat
        "existing_top": existing_top,  # full list
    }


def get_best_in_db(conn, name: str, limit: int = 5) -> list[dict]:
    """Returns the top N existing entries for a species by GL rank."""
    rows = conn.execute("""
        SELECT id, name, cp, iv_atk, iv_def, iv_sta, iv_pct,
               gl_rank, ul_rank, gl_best_cp, ul_best_cp
        FROM pokemon
        WHERE name = ?
        ORDER BY
            CASE WHEN gl_rank IS NOT NULL THEN gl_rank ELSE 99999 END ASC,
            iv_pct DESC
        LIMIT ?
    """, (name, limit)).fetchall()
    return [dict(r) for r in rows]


def get_species_summary(conn, name: str) -> dict:
    """
    Summary of all instances of a species in the DB.
    Useful for deciding how many to keep.
    """
    rows = conn.execute("""
        SELECT COUNT(*) as cnt,
               MIN(gl_rank) as best_gl,
               MIN(ul_rank) as best_ul,
               MAX(iv_pct)  as best_iv_pct
        FROM pokemon WHERE name = ?
    """, (name,)).fetchone()
    return dict(rows) if rows else {}