"""Local Pokémon IV review dashboard.
Run: python dashboard_server.py
"""

import sqlite3
from flask import Flask, abort, redirect, render_template_string, request, url_for

from database import get_db
from iv_calculator import compute_ivs

DB_FILE = "pokemon_ivs.db"
app = Flask(__name__)

PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pokémon IV Review Dashboard</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f172a;
      --panel: #16213e;
      --panel-2: #1e293b;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --border: #334155;
      --save: #15803d;
      --delete: #b91c1c;
      --review: #b45309;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    h1 { margin: 0; font-size: 24px; }
    .sub { color: var(--muted); margin: 8px 0 20px; }
    .empty {
      margin-top: 28px;
      padding: 24px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--panel);
      color: var(--muted);
    }
    .card {
      margin: 14px 0;
      padding: 16px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--panel);
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin: 0 0 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .reason {
      color: #fbbf24;
      font-size: 13px;
    }
    .pokemon-form {
      display: grid;
      grid-template-columns: minmax(150px, 1.5fr) repeat(5, minmax(64px, 90px)) minmax(105px, 120px) minmax(160px, 1.5fr) auto;
      gap: 8px;
      align-items: center;
    }
    input, select, button {
      min-width: 0;
      border-radius: 6px;
      font: inherit;
    }
    input, select {
      width: 100%;
      padding: 8px;
      border: 1px solid #475569;
      background: #0b1220;
      color: var(--text);
    }
    button {
      padding: 8px 12px;
      border: 0;
      color: white;
      font-weight: 600;
      cursor: pointer;
    }
    .save { background: var(--save); }
    .delete { background: var(--delete); }
    .delete-form { display: inline-block; margin-top: 10px; }
    .labels {
      display: grid;
      grid-template-columns: minmax(150px, 1.5fr) repeat(5, minmax(64px, 90px)) minmax(105px, 120px) minmax(160px, 1.5fr) auto;
      gap: 8px;
      margin: 0 0 4px;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    @media (max-width: 1050px) {
      .pokemon-form, .labels { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .labels { display: none; }
    }
  </style>
</head>
<body>
  <h1>Pokémon IV Review Dashboard</h1>
  <p class="sub">Showing {{ rows|length }} unresolved Review-tagged record{{ '' if rows|length == 1 else 's' }}. Saving Keep or Transfer clears its review status.</p>

  {% if rows %}
    <div class="labels">
      <span>Name / Form</span><span>CP</span><span>Max HP</span><span>ATK IV</span><span>DEF IV</span><span>STA IV</span><span>Decision</span><span>Review reason</span><span>Save</span>
    </div>

    {% for row in rows %}
      <section class="card">
        <div class="meta">
          <span>ID {{ row.id }}</span>
          <span>IV% {{ "%.1f"|format(row.iv_pct or 0) }}</span>
          {% if row.level is not none %}<span>Level {{ row.level }}</span>{% endif %}
          {% if row.caught_date %}<span>Caught {{ row.caught_date }}</span>{% endif %}
          {% if row.review_reason %}<span class="reason">{{ row.review_reason }}</span>{% endif %}
        </div>

        <form method="post" action="{{ url_for('update_pokemon', pokemon_id=row.id) }}" class="pokemon-form">
          <input type="text" name="name" value="{{ row.name or '' }}" placeholder="Species / form" required>
          <input type="number" name="cp" value="{{ row.cp or 0 }}" min="0" max="5500" required>
          <input type="number" name="hp" value="{{ row.hp or 0 }}" min="0" max="999" required>
          <input type="number" name="iv_atk" value="{{ row.iv_atk or 0 }}" min="0" max="15" required>
          <input type="number" name="iv_def" value="{{ row.iv_def or 0 }}" min="0" max="15" required>
          <input type="number" name="iv_sta" value="{{ row.iv_sta or 0 }}" min="0" max="15" required>
          <select name="tag">
            <option value="REVIEW" {% if row.tag == "REVIEW" %}selected{% endif %}>Review</option>
            <option value="KEEP" {% if row.tag == "KEEP" %}selected{% endif %}>Keep</option>
            <option value="TRANSFER" {% if row.tag == "TRANSFER" %}selected{% endif %}>Transfer</option>
          </select>
          <input type="text" name="review_reason" value="{{ row.review_reason or '' }}" placeholder="Required only if retaining Review">
          <button class="save" type="submit">Save</button>
        </form>

        <form method="post" action="{{ url_for('delete_pokemon', pokemon_id=row.id) }}" class="delete-form" onsubmit="return confirm('Delete local record ID {{ row.id }} ({{ row.name }})? This cannot be undone.');">
          <button class="delete" type="submit">Delete failed scan</button>
        </form>
      </section>
    {% endfor %}
  {% else %}
    <div class="empty">No unresolved Review-tagged records. Resolved Keep and Transfer records are intentionally excluded.</div>
  {% endif %}
</body>
</html>
"""


def get_conn():
    """Open the project database with mapping-style rows."""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def existing_columns(conn: sqlite3.Connection, requested: dict) -> dict:
    """Keep writes compatible with small schema variations during development."""
    available = table_columns(conn, "pokemon")
    return {column: value for column, value in requested.items() if column in available}


@app.get("/")
def index():
    conn = get_conn()
    columns = table_columns(conn, "pokemon")

    optional = [
        column for column in ("level", "caught_date", "iv_pct", "review_reason", "tag")
        if column in columns
    ]
    selected = ["id", "name", "cp", "hp", "iv_atk", "iv_def", "iv_sta"] + optional

    tag_filter = "AND tag = 'REVIEW'" if "tag" in columns else ""
    query = f"""
        SELECT {", ".join(selected)}
        FROM pokemon
        WHERE needs_review = 1
        {tag_filter}
        ORDER BY id DESC
    """
    rows = conn.execute(query).fetchall()
    conn.close()
    return render_template_string(PAGE, rows=rows)


@app.post("/pokemon/<int:pokemon_id>/update")
def update_pokemon(pokemon_id: int):
    name = request.form.get("name", "").strip()
    tag = request.form.get("tag", "REVIEW").strip().upper()
    review_reason = request.form.get("review_reason", "").strip()

    if not name:
        abort(400, "Species/form name is required.")
    if tag not in {"REVIEW", "KEEP", "TRANSFER"}:
        abort(400, "Invalid decision.")
    if tag == "REVIEW" and not review_reason:
        abort(400, "Provide a reason when retaining Review.")

    try:
        cp = int(request.form.get("cp", "0"))
        hp = int(request.form.get("hp", "0"))
        iv_atk = int(request.form.get("iv_atk", "0"))
        iv_def = int(request.form.get("iv_def", "0"))
        iv_sta = int(request.form.get("iv_sta", "0"))
    except ValueError:
        abort(400, "CP, HP, and IVs must be integers.")

    if not 10 <= cp <= 5500:
        abort(400, "CP must be between 10 and 5500.")
    if not 10 <= hp <= 999:
        abort(400, "Maximum HP must be between 10 and 999.")
    if not all(0 <= value <= 15 for value in (iv_atk, iv_def, iv_sta)):
        abort(400, "Each IV must be between 0 and 15.")

    conn = get_conn()
    columns = table_columns(conn, "pokemon")
    row = conn.execute("SELECT * FROM pokemon WHERE id = ?", (pokemon_id,)).fetchone()
    if row is None:
        conn.close()
        abort(404, "Pokémon record not found.")

    dust_cost = row["dust"] if "dust" in columns else None
    iv_data = compute_ivs(
        pokemon_name=name,
        observed_cp=cp,
        observed_hp=hp,
        iv_atk=iv_atk,
        iv_def=iv_def,
        iv_sta=iv_sta,
        dust_cost=dust_cost,
    )

    values = existing_columns(conn, {
        "name": name,
        "cp": cp,
        "hp": hp,
        "iv_atk": iv_atk,
        "iv_def": iv_def,
        "iv_sta": iv_sta,
        "iv_pct": iv_data["iv_pct"],
        "iv_stars": iv_data["iv_stars"],
        "level": iv_data["level"],
        "tag": tag,
        "needs_review": int(tag == "REVIEW"),
        "review_reason": review_reason if tag == "REVIEW" else None,
    })

    assignments = ", ".join(f"{column} = ?" for column in values)
    conn.execute(
        f"UPDATE pokemon SET {assignments} WHERE id = ?",
        (*values.values(), pokemon_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.post("/pokemon/<int:pokemon_id>/delete")
def delete_pokemon(pokemon_id: int):
    conn = get_conn()
    row = conn.execute("SELECT id FROM pokemon WHERE id = ?", (pokemon_id,)).fetchone()
    if row is None:
        conn.close()
        abort(404, "Pokémon record not found.")

    tables = {entry["name"] for entry in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "evo_rankings" in tables:
        conn.execute("DELETE FROM evo_rankings WHERE pokemon_id = ?", (pokemon_id,))

    conn.execute("DELETE FROM pokemon WHERE id = ?", (pokemon_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
