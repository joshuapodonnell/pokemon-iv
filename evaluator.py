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
    "lucky_trade_floor": 80.0,  # Keep if IV% ≥ 80 (lucky trade potential)
}

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

    # ── Rule 1: Perfect IV
    if iv_pct == 100.0:
        reasons.append("100% IV — perfect")
        action = "KEEP"

    # ── Rule 2: High IV% (3★+)
    if iv_pct >= KEEP_RULES["iv_pct_min"]:
        reasons.append(f"{iv_pct}% IV (3★+)")
        action = "KEEP"

    # ── Rule 3: Lucky trade floor
    if iv_pct >= KEEP_RULES["lucky_trade_floor"] and action != "KEEP":
        reasons.append(f"{iv_pct}% IV — lucky trade potential")
        action = "KEEP"

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
    existing_best = get_best_in_db(conn, name)
    beats_existing = False
    if existing_best:
        # "Better" = lower GL rank (or UL rank if GL not applicable)
        existing_gl = existing_best["gl_rank"]
        new_gl      = gl.get("rank")
        if new_gl and existing_gl and new_gl < existing_gl:
            beats_existing = True
            reasons.append(
                f"NEW BEST for {name}: GL #{new_gl} beats current best #{existing_gl}"
            )
            action = "KEEP"
    else:
        # First of this species — always keep
        reasons.append(f"First {name} in collection")
        action = "KEEP"
        beats_existing = True

    # ── Rule 7: Unknown species / OCR failure → flag for review
    if name in ("Unknown", "") or cp == 0:
        action = "REVIEW"
        reasons.append("OCR uncertain — needs manual check")

    return {
        "action":         action,
        "reasons":        reasons,
        "beats_existing": beats_existing,
        "existing_best":  existing_best,
    }


def get_best_in_db(conn, name: str) -> dict | None:
    """Returns the best existing entry for a species by GL rank."""
    row = conn.execute("""
        SELECT id, name, cp, iv_atk, iv_def, iv_sta, iv_pct,
               gl_rank, ul_rank, gl_best_cp, ul_best_cp
        FROM pokemon
        WHERE name = ?
        ORDER BY
            CASE WHEN gl_rank IS NOT NULL THEN gl_rank ELSE 99999 END ASC,
            iv_pct DESC
        LIMIT 1
    """, (name,)).fetchone()
    return dict(row) if row else None


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