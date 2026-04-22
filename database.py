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
    needs_review    INTEGER DEFAULT 0
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
    # Migration: add needs_review to any existing DB created before it was in the schema
    existing = {row[1] for row in conn.execute("PRAGMA table_info(pokemon)")}
    if "needs_review" not in existing:
        conn.execute("ALTER TABLE pokemon ADD COLUMN needs_review INTEGER DEFAULT 0")
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
    )
    cur = conn.execute("""
        INSERT INTO pokemon (
            name, cp, hp, dust, level,
            iv_atk, iv_def, iv_sta, iv_pct, iv_stars,
            gl_rank, gl_percentile, gl_sp, gl_sp_pct, gl_best_level, gl_best_cp,
            ul_rank, ul_percentile, ul_sp, ul_sp_pct, ul_best_level, ul_best_cp,
            ml_sp, ml_sp_pct,
            screenshot_path, notes, needs_review
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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