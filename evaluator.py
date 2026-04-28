# evaluator.py — Decides keep/transfer for new catches based on existing collection

from pvp_rankings import all_league_rankings_with_evos

KEEP_RULES = {
    "iv_pct_min":       82.2,
    "gl_rank_max":      500,
    "ul_rank_max":      500,
    "evo_gl_rank_max":  500,
    "evo_ul_rank_max":  500,
    "perfect_iv":       True,
    "zero_iv":          True,
    "min_trusted_cp":   10,   # CP under this is treated as OCR uncertainty
}

KEEP_SPECIES = frozenset({
    "Articuno", "Zapdos", "Moltres", "Mewtwo", "Mew",
    "Raikou", "Entei", "Suicune", "Lugia", "Ho-Oh", "Celebi",
    "Regirock", "Regice", "Registeel", "Latias", "Latios",
    "Kyogre", "Groudon", "Rayquaza", "Jirachi", "Deoxys",
    "Uxie", "Mesprit", "Azelf", "Dialga", "Palkia", "Heatran",
    "Regigigas", "Giratina", "Cresselia", "Phione", "Manaphy",
    "Darkrai", "Shaymin", "Arceus",
    "Cobalion", "Terrakion", "Virizion", "Tornadus", "Thundurus",
    "Reshiram", "Zekrom", "Landorus", "Kyurem", "Keldeo",
    "Meloetta", "Genesect",
    "Xerneas", "Yveltal", "Zygarde", "Diancie", "Hoopa", "Volcanion",
    "Tapu Koko", "Tapu Lele", "Tapu Bulu", "Tapu Fini",
    "Cosmog", "Cosmoem", "Solgaleo", "Lunala", "Necrozma",
    "Magearna", "Marshadow", "Zeraora",
    "Nihilego", "Buzzwole", "Pheromosa", "Xurkitree",
    "Celesteela", "Kartana", "Guzzlord",
    "Poipole", "Naganadel", "Stakataka", "Blacephalon",
    "Zacian", "Zamazenta", "Eternatus", "Kubfu", "Urshifu",
    "Zarude", "Regieleki", "Regidrago", "Glastrier", "Spectrier", "Calyrex",
    "Wo-Chien", "Chien-Pao", "Ting-Lu", "Chi-Yu",
    "Koraidon", "Miraidon", "Ogerpon", "Terapagos",
})

def evaluate_catch(conn, name, cp, iv_atk, iv_def, iv_sta, iv_pct,
                   pvp: dict, evo_rankings: dict,
                   current_id: int = None) -> dict:
    reasons = []
    action = "TRANSFER"
    existing_top = get_best_in_db(conn, name, exclude_id=current_id)

    is_hundo = (iv_atk == 15 and iv_def == 15 and iv_sta == 15)
    is_nundo = (iv_atk == 0 and iv_def == 0 and iv_sta == 0)

    if KEEP_RULES["perfect_iv"] and is_hundo:
        reasons.append("100% IV — hundo")
        action = "KEEP"
    if KEEP_RULES["zero_iv"] and is_nundo:
        reasons.append("0% IV — nundo")
        action = "KEEP"

    if iv_pct >= KEEP_RULES["iv_pct_min"]:
        reasons.append(f"{iv_pct}% IV (3★+)")
        action = "KEEP"

    if any(name.startswith(s) for s in KEEP_SPECIES):
        reasons.append("Legendary/mythical/UB — always keep")
        action = "KEEP"

    gl = pvp.get("great", {})
    ul = pvp.get("ultra", {})

    if gl.get("rank") and gl["rank"] <= KEEP_RULES["gl_rank_max"]:
        reasons.append(f"GL rank #{gl['rank']} (top {100-gl.get('percentile',0):.1f}%)")
        action = "KEEP"
    if ul.get("rank") and ul["rank"] <= KEEP_RULES["ul_rank_max"]:
        reasons.append(f"UL rank #{ul['rank']} (top {100-ul.get('percentile',0):.1f}%)")
        action = "KEEP"

    for evo_name, evo_pvp in evo_rankings.items():
        evo_gl = evo_pvp.get("great", {})
        evo_ul = evo_pvp.get("ultra", {})
        if evo_gl.get("rank") and evo_gl["rank"] <= KEEP_RULES["evo_gl_rank_max"]:
            reasons.append(f"Evolves → {evo_name} GL rank #{evo_gl['rank']}")
            action = "KEEP"
        if evo_ul.get("rank") and evo_ul["rank"] <= KEEP_RULES["evo_ul_rank_max"]:
            reasons.append(f"Evolves → {evo_name} UL rank #{evo_ul['rank']}")
            action = "KEEP"

    beats_existing = False
    new_gl = gl.get("rank")
    new_ul = ul.get("rank")

    if is_hundo or is_nundo:
        beats_existing = True
        if not existing_top:
            reasons.append(f"First {name} in collection")
    elif existing_top:
        existing_gl = existing_top[0]["gl_rank"]
        existing_ul = min(
            (r["ul_rank"] for r in existing_top if r["ul_rank"] is not None),
            default=None
        )

        beats_gl = new_gl and (existing_gl is None or new_gl < existing_gl)
        beats_ul = new_ul and (existing_ul is None or new_ul < existing_ul)

        if beats_gl:
            beats_existing = True
            reasons.append(f"NEW BEST GL for {name}: #{new_gl} beats #{existing_gl}")
            action = "KEEP"
        if beats_ul:
            beats_existing = True
            reasons.append(f"NEW BEST UL for {name}: #{new_ul} beats #{existing_ul}")
            action = "KEEP"
    else:
        reasons.append(f"First {name} in collection")
        action = "KEEP"
        beats_existing = True

    if not is_hundo and not is_nundo:
        if name in ("Unknown", "") or cp < KEEP_RULES["min_trusted_cp"]:
            action = "REVIEW"
            reasons.append(f"OCR uncertain — needs manual check (CP < {KEEP_RULES['min_trusted_cp']} or unknown name)")

        # NEW DEMOTION LOGIC — mark previously kept Pokémon for review if beaten
    if action == "KEEP" and beats_existing and existing_top:
        for old_poke in existing_top:
            # Only demote if it was previously tagged KEEP
            if old_poke.get('tag') == 'KEEP':
                conn.execute("""
                       UPDATE pokemon 
                       SET needs_review = 1, 
                           review_reason = 'demoted_by_better'
                       WHERE id = ? AND tag = 'KEEP'
                   """, (old_poke['id'],))
                reasons.append(f"Demoted {old_poke['name']} #{old_poke['id']} from top ranks")
    return {
        "action": action,
        "reasons": reasons,
        "beats_existing": beats_existing,
        "existing_best": existing_top[0] if existing_top else None,
        "existing_top": existing_top,
    }


def get_best_in_db(conn, name: str, limit: int = 5, exclude_id: int = None) -> list[dict]:
    exclude_clause = "AND id != ?" if exclude_id is not None else ""
    params_gl = (name, exclude_id, limit) if exclude_id is not None else (name, limit)
    params_ul = (name, exclude_id) if exclude_id is not None else (name,)

    gl_rows = conn.execute(f"""
        SELECT id, name, cp, iv_atk, iv_def, iv_sta, iv_pct,
               gl_rank as gl_rank, ul_rank as ul_rank, gl_best_cp as gl_best_cp, ul_best_cp as ul_best_cp
        FROM pokemon
        WHERE name = ? {exclude_clause}
        ORDER BY
            CASE WHEN gl_rank IS NOT NULL THEN gl_rank ELSE 99999 END ASC,
            iv_pct DESC
        LIMIT ?
    """, params_gl).fetchall()

    ul_best = conn.execute(f"""
        SELECT id, name, cp, iv_atk, iv_def, iv_sta, iv_pct,
               gl_rank as gl_rank, ul_rank as ul_rank, gl_best_cp as gl_best_cp, ul_best_cp as ul_best_cp
        FROM pokemon
        WHERE name = ? {exclude_clause}
        ORDER BY
            CASE WHEN ul_rank IS NOT NULL THEN ul_rank ELSE 99999 END ASC,
            iv_pct DESC
        LIMIT 1
    """, params_ul).fetchone()

    seen_ids = {r["id"] for r in gl_rows}
    combined = [dict(r) for r in gl_rows]
    if ul_best and ul_best["id"] not in seen_ids:
        combined.append(dict(ul_best))
    return combined


def find_displaced(conn, limit: int = 5) -> list[dict]:
    rows = conn.execute(f"""
        SELECT * FROM pokemon p
        WHERE (
            SELECT COUNT(*) FROM pokemon p2
            WHERE p2.name = p.name
            AND COALESCE(p2.gl_rank, 99999) < COALESCE(p.gl_rank, 99999)
        ) >= {limit}
        AND p.needs_review = 0
    """).fetchall()
    return [dict(r) for r in rows]


def flag_displaced(conn, limit: int = 5):
    displaced = find_displaced(conn, limit)
    ids = [r["id"] for r in displaced]
    if ids:
        conn.execute(
            f"UPDATE pokemon SET needs_review = 1 WHERE id IN ({','.join('?'*len(ids))})",
            ids
        )
        conn.commit()
    return displaced


def get_species_summary(conn, name: str) -> dict:
    row = conn.execute("""
        SELECT COUNT(*) as cnt,
               MIN(gl_rank) as best_gl,
               MIN(ul_rank) as best_ul,
               MAX(iv_pct)  as best_iv_pct
        FROM pokemon
        WHERE name = ?
    """, (name,)).fetchone()
    return dict(row) if row else {}