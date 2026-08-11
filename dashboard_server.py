# dashboard_server.py
from flask import Flask, jsonify, request, render_template_string
from database import get_db

app = Flask(__name__)

DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Pokémon GO IV Catalog</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #172033;
      --border: #2c3a55;
      --text: #e6edf7;
      --muted: #9bacbf;
      --keep: #22c55e;
      --transfer: #ef4444;
      --review: #f59e0b;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      padding: 28px;
      color: var(--text);
      background: var(--bg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    h1 { margin: 0 0 6px; font-size: 28px; }
    .subtitle { color: var(--muted); margin: 0 0 24px; }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }

    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
    }

    .card-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .08em;
    }

    .card-value {
      font-size: 30px;
      font-weight: 800;
      margin-top: 6px;
    }

    .keep { color: var(--keep); }
    .transfer { color: var(--transfer); }
    .review { color: var(--review); }

    .controls {
      display: flex;
      gap: 12px;
      margin-bottom: 16px;
    }

    input, select {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      background: var(--panel);
      color: var(--text);
      font-size: 14px;
    }

    input { width: 280px; }

    .table-wrap {
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
    }

    table {
      border-collapse: collapse;
      width: 100%;
      min-width: 800px;
    }

    th, td {
      padding: 12px 14px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }

    th {
      color: var(--muted);
      cursor: pointer;
      font-size: 12px;
      letter-spacing: .04em;
      text-transform: uppercase;
    }

    tr:last-child td { border-bottom: 0; }
    tbody tr:hover { background: #202d44; }

    .tag {
      display: inline-block;
      min-width: 80px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      text-align: center;
    }

    .tag-KEEP { background: #14532d; color: #86efac; }
    .tag-TRANSFER { background: #7f1d1d; color: #fca5a5; }
    .tag-REVIEW { background: #78350f; color: #fcd34d; }
    .iv-high { color: #86efac; font-weight: 800; }

    @media (max-width: 650px) {
      body { padding: 16px; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .controls { flex-direction: column; }
      input { width: 100%; }
    }
  </style>
</head>
<body>
  <h1>Pokémon GO IV Catalog</h1>
  <p class="subtitle">Latest scanned Pokémon and tagging decisions</p>

  <section class="stats">
    <div class="card"><div class="card-label">TOTAL</div><div class="card-value" id="total">—</div></div>
    <div class="card"><div class="card-label">KEEP</div><div class="card-value keep" id="keep">—</div></div>
    <div class="card"><div class="card-label">TRANSFER</div><div class="card-value transfer" id="transfer">—</div></div>
    <div class="card"><div class="card-label">REVIEW</div><div class="card-value review" id="review">—</div></div>
  </section>

  <section class="controls">
    <input id="search" placeholder="Search Pokémon name…">
    <select id="tagFilter">
      <option value="">All tags</option>
      <option value="KEEP">KEEP</option>
      <option value="TRANSFER">TRANSFER</option>
      <option value="REVIEW">REVIEW</option>
    </select>
  </section>

  <section class="table-wrap">
    <table>
      <thead>
        <tr>
          <th data-key="name">Pokémon</th>
          <th data-key="cp">CP</th>
          <th data-key="iv_pct">IV %</th>
          <th>IVs</th>
          <th data-key="gl_rank">GL Rank</th>
          <th data-key="ul_rank">UL Rank</th>
          <th data-key="tag">Decision</th>
          <th data-key="caught_date">Caught</th>
        </tr>
      </thead>
      <tbody id="pokemonRows"></tbody>
    </table>
  </section>

  <script>
    let pokemon = [];
    let sortKey = "iv_pct";
    let sortAscending = false;

    const value = (item, key) => item[key] ?? "";

    function render() {
      const search = document.getElementById("search").value.toLowerCase();
      const tag = document.getElementById("tagFilter").value;

      const filtered = pokemon
        .filter(p => p.name.toLowerCase().includes(search))
        .filter(p => !tag || p.tag === tag)
        .sort((a, b) => {
          const av = value(a, sortKey);
          const bv = value(b, sortKey);
          const comparison = typeof av === "number"
            ? av - bv
            : String(av).localeCompare(String(bv));
          return sortAscending ? comparison : -comparison;
        });

      document.getElementById("pokemonRows").innerHTML = filtered.map(p => `
        <tr>
          <td><strong>${p.name}</strong></td>
          <td>${p.cp ?? "—"}</td>
          <td class="${p.iv_pct >= 82.2 ? "iv-high" : ""}">${p.iv_pct ?? "—"}%</td>
          <td>${p.iv_atk} / ${p.iv_def} / ${p.iv_sta}</td>
          <td>${p.gl_rank ?? "—"}</td>
          <td>${p.ul_rank ?? "—"}</td>
          <td><span class="tag tag-${p.tag || "REVIEW"}">${p.tag || "REVIEW"}</span></td>
          <td>${p.caught_date || "—"}</td>
        </tr>
      `).join("");
    }

    async function loadDashboard() {
      const [pokemonResponse, statsResponse] = await Promise.all([
        fetch("/pokemon"),
        fetch("/stats")
      ]);

      pokemon = await pokemonResponse.json();
      const stats = await statsResponse.json();

      for (const key of ["total", "keep", "transfer", "review"]) {
        document.getElementById(key).textContent = stats[key] ?? 0;
      }
      render();
    }

    document.getElementById("search").addEventListener("input", render);
    document.getElementById("tagFilter").addEventListener("change", render);

    document.querySelectorAll("th[data-key]").forEach(header => {
      header.addEventListener("click", () => {
        const key = header.dataset.key;
        sortAscending = key === sortKey ? !sortAscending : true;
        sortKey = key;
        render();
      });
    });

    loadDashboard();
  </script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route("/pokemon")
def list_pokemon():
    conn = get_db()
    rows = conn.execute("""
        SELECT name, cp, iv_atk, iv_def, iv_sta, iv_pct, tag,
               gl_rank, ul_rank, caught_date
        FROM pokemon ORDER BY id DESC LIMIT 200
    """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/stats")
def stats():
    conn = get_db()
    row = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN tag='KEEP' THEN 1 ELSE 0 END) as keep,
               SUM(CASE WHEN tag='TRANSFER' THEN 1 ELSE 0 END) as transfer,
               SUM(CASE WHEN tag='REVIEW' THEN 1 ELSE 0 END) as review
        FROM pokemon
    """).fetchone()
    return jsonify(dict(row))

@app.route("/all")
def list_all_pokemon():
    conn = get_db()
    rows = conn.execute("""
        SELECT *
        FROM pokemon ORDER BY id DESC
    """).fetchall()
    return jsonify([dict(r) for r in rows])
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)