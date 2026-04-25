# pass2_tagger.py
def compute_tags(conn):
    """Re-evaluate every Pokémon against the complete DB."""
    rows = conn.execute("SELECT * FROM pokemon ORDER BY id").fetchall()
    results = []
    for row in rows:
        row = dict(row)
        pvp = rebuild_pvp_from_row(row)       # reconstruct from stored ranks
        evo_rankings = {}                      # skip evo check — already in DB
        decision = evaluate_catch(
            conn,
            row["name"], row["cp"],
            row["iv_atk"], row["iv_def"], row["iv_sta"], row["iv_pct"],
            pvp, evo_rankings
        )
        results.append((row["id"], decision["action"]))
    return results