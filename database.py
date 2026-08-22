# database.py — SQLite storage for the full Pokémon IV collection

import sqlite3
import json
import os
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "pokemon_ivs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pokemon (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    cp              INTEGER,
    hp              INTEGER,
    dust            INTEGER,
    level           REAL,

    -- PvE IVs (from appraisal bars, exact 0-15)
    iv_atk          INTEGER,
    iv_def          INTEGER,
    iv_sta          INTEGER,
    iv_pct          REAL,
    iv_stars        TEXT,

    -- PvP: Great League
    gl_rank         INTEGER,
    gl_percentile   REAL,
    gl_sp           REAL,
    gl_sp_pct       REAL,
    gl_best_level   REAL,
    gl_best_cp      INTEGER,

    -- PvP: Ultra League
    ul_rank         INTEGER,
    ul_percentile   REAL,
    ul_sp           REAL,
    ul_sp_pct       REAL,
    ul_best_level   REAL,
    ul_best_cp      INTEGER,

    -- PvP: Master League
    ml_sp           REAL,
    ml_sp_pct       REAL,

    -- Metadata
    cataloged_at    TEXT DEFAULT (datetime('now')),
    screenshot_path TEXT,
    notes           TEXT,
    flagged         INTEGER DEFAULT 0,
    needs_review    INTEGER DEFAULT 0,
    review_reason   TEXT,
    caught_date     TEXT,
    tag             TEXT DEFAULT NULL,
    pending_old_tag TEXT DEFAULT NULL,
    tag_changed     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS evo_rankings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pokemon_id      INTEGER NOT NULL REFERENCES pokemon(id) ON DELETE CASCADE,
    evo_name        TEXT NOT NULL,
    gl_rank         INTEGER,
    gl_percentile   REAL,
    gl_sp           REAL,
    gl_sp_pct       REAL,
    gl_best_level   REAL,
    gl_best_cp      INTEGER,
    ul_rank         INTEGER,
    ul_percentile   REAL,
    ul_sp           REAL,
    ul_sp_pct       REAL,
    ul_best_level   REAL,
    ul_best_cp      INTEGER
);

CREATE TABLE IF NOT EXISTS cp_consensus_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT DEFAULT (datetime('now')),
    visit_num         INTEGER,
    ocr_cp            INTEGER,
    ocr_raw           TEXT,
    ocr_image_path    TEXT,        -- NEW
    vlm_votes         TEXT,
    vlm_backends      TEXT,        -- from the vision_agent change, if you added it
    vlm_consensus     INTEGER,
    reconciled_cp     INTEGER,
    reconcile_reason  TEXT,
    ground_truth_cp   INTEGER,
    frame_paths       TEXT
);

CREATE INDEX IF NOT EXISTS idx_name        ON pokemon(name);
CREATE INDEX IF NOT EXISTS idx_iv_pct      ON pokemon(iv_pct DESC);
CREATE INDEX IF NOT EXISTS idx_gl_rank     ON pokemon(name, gl_rank);
CREATE INDEX IF NOT EXISTS idx_ul_rank     ON pokemon(name, ul_rank);
CREATE INDEX IF NOT EXISTS idx_evo_pokemon ON evo_rankings(pokemon_id);
CREATE INDEX IF NOT EXISTS idx_evo_name    ON evo_rankings(evo_name, gl_rank);
"""

def get_db(db_file: str = DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Migration: add columns to any existing DB created before they were in the schema
    existing = {row[1] for row in conn.execute("PRAGMA table_info(pokemon)")}
    if "needs_review" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN needs_review INTEGER DEFAULT 0")
    if "caught_date" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN caught_date TEXT")
    if "tag" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN tag TEXT DEFAULT NULL")
    if "review_reason" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN review_reason TEXT")
    if "demoted" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN demoted INTEGER DEFAULT 0")
    # NEW — required by evaluator.py's _is_immune() and enforce_top_n()
    if "is_shiny" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN is_shiny INTEGER DEFAULT 0")
    if "form_status" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN form_status TEXT DEFAULT 'normal'")
    if "pending_old_tag" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN pending_old_tag TEXT")
    if "pending_old_tag" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN pending_old_tag TEXT")
    if "tag_changed" not in existing:  # ADD THIS
        conn.execute("ALTER TABLE pokemon ADD COLUMN tag_changed INTEGER DEFAULT 0")
    conn.commit()
    return conn

def insert_pokemon(conn: sqlite3.Connection, data: dict) -> int:
    """Insert a fully computed Pokémon record. Returns the new row ID."""
    gl = data.get("pvp", {}).get("great", {})
    ul = data.get("pvp", {}).get("ultra", {})
    ml = data.get("pvp", {}).get("master", {})

    row = (
        data["name"], data.get("cp"), data.get("hp"), data.get("dust"), data.get("level"),
        data.get("iv_atk"), data.get("iv_def"), data.get("iv_sta"),
        data.get("iv_pct"), data.get("iv_stars"),
        gl.get("rank"),        gl.get("percentile"),
        gl.get("stat_product"),gl.get("sp_pct_of_max"),
        gl.get("best_level"),  gl.get("best_cp"),
        ul.get("rank"),        ul.get("percentile"),
        ul.get("stat_product"),ul.get("sp_pct_of_max"),
        ul.get("best_level"),  ul.get("best_cp"),
        ml.get("stat_product"),ml.get("sp_pct_of_max"),
        data.get("screenshot_path"), data.get("notes"),
        int(bool(data.get("needs_review", False))),
        data.get("caught_date"),
    )
    cur = conn.execute("""
        INSERT INTO pokemon (
            name, cp, hp, dust, level,
            iv_atk, iv_def, iv_sta, iv_pct, iv_stars,
            gl_rank, gl_percentile, gl_sp, gl_sp_pct, gl_best_level, gl_best_cp,
            ul_rank, ul_percentile, ul_sp, ul_sp_pct, ul_best_level, ul_best_cp,
            ml_sp, ml_sp_pct,
            screenshot_path, notes, needs_review, caught_date
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, row)
    conn.commit()
    return cur.lastrowid

def get_all(conn: sqlite3.Connection, order_by: str = "cataloged_at DESC") -> list:
    return conn.execute(f"SELECT * FROM pokemon ORDER BY {order_by}").fetchall()

def get_by_name(conn: sqlite3.Connection, name: str) -> list:
    return conn.execute(
        "SELECT * FROM pokemon WHERE name LIKE ? ORDER BY iv_pct DESC",
        (f"%{name}%",)
    ).fetchall()

def get_top_iv(conn: sqlite3.Connection, min_pct: float = 80.0) -> list:
    return conn.execute(
        "SELECT * FROM pokemon WHERE iv_pct >= ? ORDER BY iv_pct DESC",
        (min_pct,)
    ).fetchall()

def get_top_pvp(conn: sqlite3.Connection, league: str = "great",
                max_rank: int = 10) -> list:
    col = {"great": "gl_rank", "ultra": "ul_rank"}.get(league, "gl_rank")
    return conn.execute(
        f"SELECT * FROM pokemon WHERE {col} IS NOT NULL AND {col} <= ? "
        f"ORDER BY name, {col}",
        (max_rank,)
    ).fetchall()

def delete_pokemon(conn: sqlite3.Connection, pokemon_id: int):
    conn.execute("DELETE FROM pokemon WHERE id = ?", (pokemon_id,))
    conn.commit()

def export_json(conn: sqlite3.Connection, path: str):
    rows = [dict(r) for r in get_all(conn)]
    with open(path, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"Exported {len(rows)} records to {path}")

def get_stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM pokemon").fetchone()[0]
    perfect = conn.execute("SELECT COUNT(*) FROM pokemon WHERE iv_pct = 100").fetchone()[0]
    three_star = conn.execute("SELECT COUNT(*) FROM pokemon WHERE iv_pct >= 82.2").fetchone()[0]
    gl_top10 = conn.execute("SELECT COUNT(*) FROM pokemon WHERE gl_rank <= 10").fetchone()[0]
    ul_top10 = conn.execute("SELECT COUNT(*) FROM pokemon WHERE ul_rank <= 10").fetchone()[0]
    species = conn.execute("SELECT COUNT(DISTINCT name) FROM pokemon").fetchone()[0]
    return {
        "total": total, "species": species,
        "perfect_iv": perfect, "three_star_plus": three_star,
        "gl_top10": gl_top10, "ul_top10": ul_top10,
    }

def insert_evo_rankings(conn: sqlite3.Connection, pokemon_id: int, evo_rankings: dict):
    """
    Insert evolution PvP rankings for a cataloged Pokémon.
    evo_rankings: the dict returned by all_league_rankings_with_evos,
                  minus the base species entry (evos only).
    """
    for evo_name, leagues in evo_rankings.items():
        gl = leagues.get("great", {})
        ul = leagues.get("ultra", {})
        conn.execute("""
            INSERT INTO evo_rankings (
                pokemon_id, evo_name,
                gl_rank, gl_percentile, gl_sp, gl_sp_pct, gl_best_level, gl_best_cp,
                ul_rank, ul_percentile, ul_sp, ul_sp_pct, ul_best_level, ul_best_cp
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pokemon_id, evo_name,
            gl.get("rank"),         gl.get("percentile"),
            gl.get("stat_product"), gl.get("sp_pct_of_max"),
            gl.get("best_level"),   gl.get("best_cp"),
            ul.get("rank"),         ul.get("percentile"),
            ul.get("stat_product"), ul.get("sp_pct_of_max"),
            ul.get("best_level"),   ul.get("best_cp"),
        ))
    conn.commit()

def get_evo_rankings(conn, pokemon_id: int) -> dict:
    """Reconstruct evo_rankings dict from DB for a given pokemon_id."""
    rows = conn.execute("""
        SELECT evo_name, gl_rank, gl_percentile, ul_rank, ul_percentile
        FROM evo_rankings WHERE pokemon_id = ?
    """, (pokemon_id,)).fetchall()
    result = {}
    for r in rows:
        result[r["evo_name"]] = {
            "great": {"rank": r["gl_rank"], "percentile": r["gl_percentile"]},
            "ultra": {"rank": r["ul_rank"], "percentile": r["ul_percentile"]},
        }
    return result

def log_cp_consensus(conn: sqlite3.Connection, visit_num: int, ocr_cp, ocr_raw: str,
                      vlm_votes: list, vlm_consensus, reconciled_cp,
                      reconcile_reason: str, frame_paths: list = None,
                      ocr_image_path: str = None) -> int:      # NEW param
    cur = conn.execute("""
        INSERT INTO cp_consensus_log (
            visit_num, ocr_cp, ocr_raw, ocr_image_path, vlm_votes, vlm_consensus,
            reconciled_cp, reconcile_reason, frame_paths
        ) VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        visit_num, ocr_cp, ocr_raw, ocr_image_path, json.dumps(vlm_votes), vlm_consensus,
        reconciled_cp, reconcile_reason, json.dumps(frame_paths or []),
    ))
    conn.commit()
    return cur.lastrowid

def get_cp_consensus_pending_review(conn: sqlite3.Connection) -> list:
    """Rows where OCR and the reconciled result disagree and no ground truth yet — these are your review queue."""
    return conn.execute("""
        SELECT * FROM cp_consensus_log
        WHERE ground_truth_cp IS NULL
          AND (ocr_cp IS NULL OR ocr_cp != reconciled_cp)
        ORDER BY id DESC
    """).fetchall()

def set_ground_truth_cp(conn: sqlite3.Connection, log_id: int, true_cp: int):
    conn.execute("UPDATE cp_consensus_log SET ground_truth_cp = ? WHERE id = ?", (true_cp, log_id))
    conn.commit()

def find_duplicate(conn, name, cp, iv_atk, iv_def, iv_sta, caught_date) -> bool:
    # If we have a date, it's the strongest possible key
    if caught_date:
        row = conn.execute("""
            SELECT id FROM pokemon
            WHERE name = ? AND cp = ?
              AND iv_atk = ? AND iv_def = ? AND iv_sta = ?
              AND caught_date = ?
            LIMIT 1
        """, (name, cp, iv_atk, iv_def, iv_sta, caught_date)).fetchone()
    else:
        # Fallback: no date parsed, match on stats only (old behavior)
        row = conn.execute("""
            SELECT id FROM pokemon
            WHERE name = ? AND cp = ?
              AND iv_atk = ? AND iv_def = ? AND iv_sta = ?
              AND caught_date IS NULL
            LIMIT 1
        """, (name, cp, iv_atk, iv_def, iv_sta)).fetchone()
    return row is not None

def get_best_evo_rank(conn, pokemon_id: int) -> dict:
    """
    Returns the best (lowest) GL/UL rank among all evolutions of this catch,
    or None per league if it has no evolutions or none are ranked.
    """
    row = conn.execute("""
        SELECT MIN(gl_rank) as best_evo_gl, MIN(ul_rank) as best_evo_ul
        FROM evo_rankings
        WHERE pokemon_id = ?
    """, (pokemon_id,)).fetchone()
    if not row:
        return {"gl_rank": None, "ul_rank": None}
    return {"gl_rank": row["best_evo_gl"], "ul_rank": row["best_evo_ul"]}


def get_effective_rank(conn, pokemon_id: int, own_gl: int, own_ul: int) -> dict:
    """
    The rank that should actually be used for demotion/eviction comparisons:
    the BETTER (lower/more competitive) of the Pokemon's own rank and its
    best evolution's rank. This is what makes a Bulbasaur kept for its
    Venusaur potential actually defensible/comparable on that same basis.
    """
    evo = get_best_evo_rank(conn, pokemon_id)
    eff_gl = min((r for r in (own_gl, evo["gl_rank"]) if r is not None), default=None)
    eff_ul = min((r for r in (own_ul, evo["ul_rank"]) if r is not None), default=None)
    return {"gl_rank": eff_gl, "ul_rank": eff_ul}