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
    "min_keep_level":   30,   # Keep anything caught at this level or above
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


def _is_immune(poke: dict) -> bool:
    """
    Shared immunity check — a Pokemon matching any of these is NEVER
    marked for TRANSFER, regardless of rank. Used by both evaluate_catch's
    live demotion loop and the batch enforce_top_n() cleanup.

    NOTE: is_shiny is included here. This is the ONLY place shiny
    immunity is enforced — it doesn't change KEEP/TRANSFER logic for a
    brand-new catch (is_shiny defaults to 0 until your search-based sync
    pass runs and updates it), but it protects an already-flagged-shiny
    row from ever being evicted once that flag is set.
    """
    iv_pct = poke.get("iv_pct") or 0.0
    is_hundo = iv_pct == 100.0
    is_nundo = (
        poke.get("iv_atk") == 0
        and poke.get("iv_def") == 0
        and poke.get("iv_sta") == 0
    )
    is_legendary = any(poke["name"].startswith(s) for s in KEEP_SPECIES)
    is_high_iv = iv_pct >= KEEP_RULES["iv_pct_min"]
    min_lvl = KEEP_RULES.get("min_keep_level")
    is_high_level = (
        min_lvl is not None
        and poke.get("level") is not None
        and poke["level"] >= min_lvl
    )
    is_shiny = bool(poke.get("is_shiny"))
    return (
        is_hundo or is_nundo or is_legendary
        or is_high_iv or is_high_level or is_shiny
    )

def promote_newly_immune(conn) -> list[dict]:
    candidates = conn.execute("""
        SELECT id, name, cp, hp, level, tag, iv_atk, iv_def, iv_sta, iv_pct,
               is_shiny, form_status
        FROM pokemon
        WHERE tag IS NULL OR tag != 'KEEP'
    """).fetchall()

    promoted = []
    for row in candidates:
        poke = dict(row)
        if _is_immune(poke):
            conn.execute("""
                UPDATE pokemon
                SET pending_old_tag = tag,
                    tag = 'KEEP',
                    demoted = 0,
                    tag_changed = 1
                WHERE id = ?
            """, (poke["id"],))
            promoted.append(poke)

    conn.commit()
    return promoted


def evaluate_catch(conn, name, cp, iv_atk, iv_def, iv_sta, iv_pct,
                   pvp: dict, evo_rankings: dict, level: float = None,
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

    min_lvl = KEEP_RULES.get("min_keep_level")
    if min_lvl and level is not None and level >= min_lvl:
        reasons.append(f"High-level catch (L{level} ≥ {min_lvl})")
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
        reasons.append(f"GL rank #{gl['rank']} (top {100 - gl.get('percentile', 0):.1f}%)")
        action = "KEEP"
    if ul.get("rank") and ul["rank"] <= KEEP_RULES["ul_rank_max"]:
        reasons.append(f"UL rank #{ul['rank']} (top {100 - ul.get('percentile', 0):.1f}%)")
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
        # Find the absolute best ranks you ALREADY own
        existing_gl = min((r["gl_rank"] for r in existing_top if r["gl_rank"] is not None), default=None)
        existing_ul = min((r["ul_rank"] for r in existing_top if r["ul_rank"] is not None), default=None)

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

    # ────────────────────────────────────────────────────────────────────────────────
    # DEMOTION LOGIC — Mark previously kept Pokémon for review if beaten
    # ────────────────────────────────────────────────────────────────────────────────
    if action == "KEEP" and beats_existing and existing_top:
        for old_poke in existing_top:
            # We only care about demoting things we were previously planning to KEEP
            if old_poke.get('tag', 'KEEP') != 'KEEP':
                continue

            # Immunity check — CHANGED: now uses the shared _is_immune() helper,
            # which includes is_shiny in addition to the original hundo/nundo/
            # legendary/high-IV/high-level checks. Previously a shiny old_poke
            # had no protection here.
            if _is_immune(old_poke):
                continue  # IMMUNE! Do not demote.

            # Check if the new catch strictly beats this specific old one
            demote_reasons = []

            old_gl = old_poke.get("gl_rank")
            if new_gl and old_gl and new_gl < old_gl:
                demote_reasons.append(f"GL #{new_gl} beats old #{old_gl}")

            old_ul = old_poke.get("ul_rank")
            if new_ul and old_ul and new_ul < old_ul:
                demote_reasons.append(f"UL #{new_ul} beats old #{old_ul}")

            # Ensure we don't demote an old one if it is STILL our best in a different league!
            is_still_best_ul = (old_ul is not None and (new_ul is None or old_ul < new_ul))
            is_still_best_gl = (old_gl is not None and (new_gl is None or old_gl < new_gl))

            if demote_reasons and not (is_still_best_gl or is_still_best_ul):
                reason_str = "demoted_by_better"

                conn.execute("""
                       UPDATE pokemon 
                       SET needs_review = 1, 
                           review_reason = ?
                       WHERE id = ? AND (tag = 'KEEP' OR tag IS NULL)
                   """, (reason_str, old_poke['id']))

                reasons.append(f"Demoted {old_poke['name']} #{old_poke['id']} ({', '.join(demote_reasons)})")

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

    # CHANGED: added `is_shiny` to the SELECT columns (both queries below),
    # alongside the previously-added `tag` and `level`. Without this,
    # _is_immune() can never see whether an old_poke is shiny.
    gl_rows = conn.execute(f"""
        SELECT id, name, cp, level, tag, iv_atk, iv_def, iv_sta, iv_pct, is_shiny,
               gl_rank as gl_rank, ul_rank as ul_rank, gl_best_cp as gl_best_cp, ul_best_cp as ul_best_cp
        FROM pokemon
        WHERE name = ? {exclude_clause}
        ORDER BY
            CASE WHEN gl_rank IS NOT NULL THEN gl_rank ELSE 99999 END ASC,
            iv_pct DESC
        LIMIT ?
    """, params_gl).fetchall()

    ul_best = conn.execute(f"""
        SELECT id, name, cp, level, tag, iv_atk, iv_def, iv_sta, iv_pct, is_shiny,
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


def enforce_top_n(conn, top_n: int = 5) -> list[dict]:
    groups = conn.execute("""
        SELECT DISTINCT name, (form_status = 'shadow') AS is_shadow
        FROM pokemon WHERE tag = 'KEEP'
    """).fetchall()

    demoted_all = []
    for g in groups:
        name, is_shadow = g["name"], g["is_shadow"]
        rows = conn.execute("""
            SELECT id, name, cp, level, tag, iv_atk, iv_def, iv_sta, iv_pct,
                   gl_rank, ul_rank, is_shiny, form_status
            FROM pokemon
            WHERE name = ? AND tag = 'KEEP'
              AND (form_status = 'shadow') = ?
        """, (name, is_shadow)).fetchall()
        rows = [dict(r) for r in rows]

        gl_full = sorted(
            (r for r in rows if r["gl_rank"] is not None),
            key=lambda r: (r["gl_rank"], -(r["iv_pct"] or 0.0)),
        )
        ul_full = sorted(
            (r for r in rows if r["ul_rank"] is not None),
            key=lambda r: (r["ul_rank"], -(r["iv_pct"] or 0.0)),
        )
        safe_by_rank = (
            {r["id"] for r in gl_full[:top_n]} | {r["id"] for r in ul_full[:top_n]}
        )

        for poke in rows:
            if _is_immune(poke):
                continue
            if poke["id"] in safe_by_rank:
                continue
            kind = "shadow" if is_shadow else "non-shadow"
            # CHANGED: capture pending_old_tag = 'KEEP' (guaranteed, since
            # this query only ever touches rows currently tagged KEEP)
            # before overwriting tag to TRANSFER.
            conn.execute("""
                UPDATE pokemon
                SET pending_old_tag = tag,
                    tag = 'TRANSFER',
                    demoted = 1,
                    needs_review = 1,
                    review_reason = ?
                WHERE id = ?
            """, (f"outside_top_{top_n}_{kind}_both_leagues", poke["id"]))
            demoted_all.append(poke)

    conn.commit()
    return demoted_all


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
