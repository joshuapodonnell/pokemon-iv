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
      min-width: 1180px;
    }

    th, td {
      padding: 12px 14px;
      text-align: left;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }

    th {
      color: var(--muted);
      cursor: pointer;
      font-size: 12px;
      letter-spacing: .04em;
      text-transform: uppercase;
    }

    th .sort-arrow {
      display: inline-block;
      margin-left: 4px;
      opacity: 0.6;
    }

    tr:last-child td { border-bottom: 0; }
    tbody tr.main-row:hover { background: #202d44; cursor: pointer; }

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

    .evo-name-tag {
      color: var(--muted);
      font-size: 11px;
      display: block;
      margin-bottom: 1px;
    }

    .expand-toggle {
      display: inline-block;
      width: 18px;
      text-align: center;
      color: var(--muted);
      font-weight: 800;
      transition: transform 0.15s ease;
    }
    .expand-toggle.open { transform: rotate(90deg); }

    tr.evo-row td {
      background: #0f1729;
      padding: 0;
      border-bottom: 1px solid var(--border);
    }

    .evo-panel {
      padding: 14px 18px 18px 46px;
    }

    .evo-panel .evo-title {
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .06em;
      text-transform: uppercase;
      margin-bottom: 8px;
    }

    table.evo-table {
      width: 100%;
      min-width: 0;
      background: transparent;
    }

    table.evo-table th {
      cursor: pointer;
      font-size: 11px;
      padding: 6px 10px;
      user-select: none;
    }

    table.evo-table td {
      padding: 8px 10px;
      border-bottom: 1px solid #1e293f;
      font-size: 13px;
    }

    table.evo-table tr:last-child td { border-bottom: 0; }

    .best-rank { color: #86efac; font-weight: 800; }
    .evo-loading, .evo-empty {
      color: var(--muted);
      font-size: 13px;
      padding: 4px 0;
    }

    @media (max-width: 650px) {
      body { padding: 16px; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .controls { flex-direction: column; }
      input { width: 100%; }
      .evo-panel { padding-left: 20px; }
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
        <tr id="headerRow">
          <th></th>
          <th data-key="name">Pokémon</th>
          <th data-key="cp">CP</th>
          <th data-key="iv_pct">IV %</th>
          <th>IVs</th>
          <th data-key="gl_rank">GL Rank</th>
          <th data-key="ul_rank">UL Rank</th>
          <th data-key="evo1_gl_rank">1st Evo GL Rank</th>
          <th data-key="evo1_ul_rank">1st Evo UL Rank</th>
          <th data-key="evo2_gl_rank">2nd Evo GL Rank</th>
          <th data-key="evo2_ul_rank">2nd Evo UL Rank</th>
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
    let expandedIds = new Set();
    let evoCache = new Map();
    let evoSortKey = "gl_rank";
    let evoSortAscending = true;

    const value = (item, key) => item[key] ?? "";

    function formatRank(rank, cp) {
      if (rank === null || rank === undefined) return "—";
      const cls = rank <= 100 ? "best-rank" : "";
      const cpText = cp ? ` (${cp} CP)` : "";
      return `<span class="${cls}">#${rank}</span>${cpText}`;
    }

    function formatEvoCell(name, rank, cp) {
      if (!name) return "—";
      return `<span class="evo-name-tag">${name}</span>${formatRank(rank, cp)}`;
    }

    function evoArrow(key) {
      if (key !== evoSortKey) return "";
      return `<span class="sort-arrow">${evoSortAscending ? "▲" : "▼"}</span>`;
    }

    function mainArrow(key) {
      if (key !== sortKey) return "";
      return `<span class="sort-arrow">${sortAscending ? "▲" : "▼"}</span>`;
    }

    function evoPanelHtml(pokemonId) {
      const cached = evoCache.get(pokemonId);
      if (!cached) {
        return `<div class="evo-loading">Loading evolution rankings…</div>`;
      }
      if (!cached.length) {
        return `<div class="evo-empty">No evolution ranking data for this Pokémon.</div>`;
      }
      const sorted = [...cached].sort((a, b) => {
        const av = value(a, evoSortKey) === "" ? Infinity : value(a, evoSortKey);
        const bv = value(b, evoSortKey) === "" ? Infinity : value(b, evoSortKey);
        const comparison = typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv));
        return evoSortAscending ? comparison : -comparison;
      });
      const rows = sorted.map(e => `
        <tr>
          <td><strong>${e.evo_name}</strong></td>
          <td>${formatRank(e.gl_rank, e.gl_best_cp)}</td>
          <td>${formatRank(e.ul_rank, e.ul_best_cp)}</td>
        </tr>
      `).join("");
      return `
        <div class="evo-title">Full evolution breakdown</div>
        <table class="evo-table">
          <thead>
            <tr>
              <th data-evo-key="evo_name">Evolution${evoArrow("evo_name")}</th>
              <th data-evo-key="gl_rank">GL Rank (best CP)${evoArrow("gl_rank")}</th>
              <th data-evo-key="ul_rank">UL Rank (best CP)${evoArrow("ul_rank")}</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }

    async function toggleEvoRow(pokemonId) {
      if (expandedIds.has(pokemonId)) {
        expandedIds.delete(pokemonId);
      } else {
        expandedIds.add(pokemonId);
        if (!evoCache.has(pokemonId)) {
          render();
          try {
            const resp = await fetch(`/pokemon/${pokemonId}/evolutions`);
            const data = await resp.json();
            evoCache.set(pokemonId, data);
          } catch (err) {
            evoCache.set(pokemonId, []);
          }
        }
      }
      render();
    }

    function renderHeader() {
      document.querySelectorAll("#headerRow th[data-key]").forEach(header => {
        const key = header.dataset.key;
        const label = header.dataset.label || header.textContent.replace(/[▲▼]/g, "").trim();
        header.dataset.label = label;
        header.innerHTML = `${label}${mainArrow(key)}`;
      });
    }

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

      document.getElementById("pokemonRows").innerHTML = filtered.map(p => {
        const isOpen = expandedIds.has(p.id);
        const mainRow = `
          <tr class="main-row" data-id="${p.id}">
            <td><span class="expand-toggle ${isOpen ? "open" : ""}">▶</span></td>
            <td><strong>${p.name}</strong></td>
            <td>${p.cp ?? "—"}</td>
            <td class="${p.iv_pct >= 82.2 ? "iv-high" : ""}">${p.iv_pct ?? "—"}%</td>
            <td>${p.iv_atk} / ${p.iv_def} / ${p.iv_sta}</td>
            <td>${p.gl_rank ?? "—"}</td>
            <td>${p.ul_rank ?? "—"}</td>
            <td>${formatEvoCell(p.evo1_name, p.evo1_gl_rank, p.evo1_gl_best_cp)}</td>
            <td>${formatEvoCell(p.evo1_name, p.evo1_ul_rank, p.evo1_ul_best_cp)}</td>
            <td>${formatEvoCell(p.evo2_name, p.evo2_gl_rank, p.evo2_gl_best_cp)}</td>
            <td>${formatEvoCell(p.evo2_name, p.evo2_ul_rank, p.evo2_ul_best_cp)}</td>
            <td><span class="tag tag-${p.tag || "REVIEW"}">${p.tag || "REVIEW"}</span></td>
            <td>${p.caught_date || "—"}</td>
          </tr>
        `;
        const evoRow = isOpen ? `
          <tr class="evo-row">
            <td colspan="13">
              <div class="evo-panel">${evoPanelHtml(p.id)}</div>
            </td>
          </tr>
        ` : "";
        return mainRow + evoRow;
      }).join("");

      renderHeader();
    }

    document.getElementById("pokemonRows").addEventListener("click", (e) => {
      const evoHeader = e.target.closest("th[data-evo-key]");
      if (evoHeader) {
        const key = evoHeader.dataset.evoKey;
        evoSortAscending = key === evoSortKey ? !evoSortAscending : true;
        evoSortKey = key;
        render();
        return;
      }
      const mainRow = e.target.closest("tr.main-row");
      if (mainRow) {
        toggleEvoRow(Number(mainRow.dataset.id));
      }
    });

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

    document.querySelectorAll("#headerRow th[data-key]").forEach(header => {
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
        WITH staged AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY pokemon_id ORDER BY id ASC) AS stage
            FROM evo_rankings
        )
        SELECT
            p.id, p.name, p.cp, p.iv_atk, p.iv_def, p.iv_sta, p.iv_pct, p.tag,
            p.gl_rank, p.ul_rank, p.caught_date,
            e1.evo_name   AS evo1_name,
            e1.gl_rank    AS evo1_gl_rank,
            e1.gl_best_cp AS evo1_gl_best_cp,
            e1.ul_rank    AS evo1_ul_rank,
            e1.ul_best_cp AS evo1_ul_best_cp,
            e2.evo_name   AS evo2_name,
            e2.gl_rank    AS evo2_gl_rank,
            e2.gl_best_cp AS evo2_gl_best_cp,
            e2.ul_rank    AS evo2_ul_rank,
            e2.ul_best_cp AS evo2_ul_best_cp
        FROM pokemon p
        LEFT JOIN staged e1 ON e1.pokemon_id = p.id AND e1.stage = 1
        LEFT JOIN staged e2 ON e2.pokemon_id = p.id AND e2.stage = 2
        ORDER BY p.id DESC LIMIT 200
    """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/pokemon/<int:pokemon_id>/evolutions")
def pokemon_evolutions(pokemon_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT evo_name, gl_rank, gl_percentile, gl_best_level, gl_best_cp,
               ul_rank, ul_percentile, ul_best_level, ul_best_cp
        FROM evo_rankings
        WHERE pokemon_id = ?
        ORDER BY id ASC
    """, (pokemon_id,)).fetchall()
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
