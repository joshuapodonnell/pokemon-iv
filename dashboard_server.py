from flask import Flask, jsonify, request, render_template_string, abort
from database import get_db, promote_evolution
from pvp_rankings import all_league_rankings_with_evos

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

    /* Modal Styles */
    .modal-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.75);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
    }
    .modal-overlay.hidden { display: none; }
    .modal {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      width: 360px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    }
    .modal h3 { margin: 0 0 16px; font-size: 18px; }
    .modal .form-group { margin-bottom: 14px; }
    .modal label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
      font-weight: 700;
    }
    .modal select, .modal input { width: 100%; }
    .modal-actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 20px;
    }
    .modal-actions button {
      padding: 8px 16px;
      border-radius: 6px;
      border: 1px solid var(--border);
      cursor: pointer;
      background: var(--panel);
      color: var(--text);
    }
    .modal-actions button.primary {
      background: #2563eb;
      border-color: #3b82f6;
      color: #fff;
      font-weight: 600;
    }

    @media (max-width: 650px) {
      body { padding: 16px; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .controls { flex-direction: column; }
      input { width: 100%; }
      .evo-panel { padding-left: 20px; }
    }
     .review-button { background:#2563eb; border:1px solid #3b82f6; color:#fff; cursor:pointer; font-weight:700; }
 .review-card { border:1px solid var(--border); border-radius:8px; padding:12px; margin:10px 0; background:#0f1729; }
 .review-meta { color:var(--muted); font-size:12px; margin-bottom:8px; }
 .review-reason { color:#fcd34d; }
 .review-form { display:grid; grid-template-columns:minmax(145px,1.5fr) repeat(5,78px) 105px minmax(170px,1.5fr) auto; gap:7px; align-items:center; }
 .review-form input, .review-form select { width:100%; }
 .review-delete { margin-top:8px; background:#991b1b !important; border-color:#b91c1c !important; }
 @media (max-width: 850px) { .review-form { grid-template-columns:repeat(2, minmax(0, 1fr)); } }
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

  <button
    type="button"
    class="review-button"
    onclick="openReviewModal()"
  >
    Fix Review Records
  </button>
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
          <th></th>
        </tr>
      </thead>
      <tbody id="pokemonRows"></tbody>
    </table>
  </section>

  <!-- Evolution Modal -->
  <div id="evolveModal" class="modal-overlay hidden">
    <div class="modal">
      <h3 id="modalTitle">Evolve Pokémon</h3>
      <div class="form-group">
        <label for="evoSpeciesSelect">New Species</label>
        <select id="evoSpeciesSelect"></select>
      </div>
      <div class="form-group">
        <label for="evoCpInput">New CP</label>
        <input type="number" id="evoCpInput" placeholder="e.g. 1450">
      </div>
      <div class="form-group">
        <label for="evoHpInput">New HP</label>
        <input type="number" id="evoHpInput" placeholder="e.g. 112">
      </div>
      <div class="modal-actions">
        <button type="button" onclick="closeEvolveModal()">Cancel</button>
        <button type="button" class="primary" onclick="submitEvolve()">Confirm</button>
      </div>
    </div>
  </div>
<!-- Manual Review Modal -->
<div id="reviewModal" class="modal-overlay hidden">
  <div class="modal" style="width:min(1120px, 96vw); max-height:90vh; overflow:auto;">
    <h3>Manual Review Queue</h3>
    <p id="reviewSummary" style="color:var(--muted); margin-top:-6px;">Loading…</p>
    <div id="reviewRows"></div>
    <div class="modal-actions">
      <button type="button" onclick="closeReviewModal()">Close</button>
    </div>
  </div>
</div>

  <script>
    let pokemon = [];
    let sortKey = "iv_pct";
    let sortAscending = false;
    let expandedIds = new Set();
    let evoCache = new Map();
    let evoSortKey = "gl_rank";
    let evoSortAscending = true;
    let currentEvolveId = null;

    const value = (item, key) => {
      const val = item[key];
      if (val === null || val === undefined || val === "") return null;
      return val;
    };

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

    async function evolveRow(id) {
      const p = pokemon.find(x => x.id === id);
      const options = await fetch(`/pokemon/${id}/evo_options`).then(r => r.json());
      if (!options || options.length === 0) {
        alert("No known evolutions tracked for this Pokémon.");
        return;
      }

      currentEvolveId = id;
      document.getElementById("modalTitle").textContent = `Evolve ${p ? p.name : 'Pokémon'}`;

      const select = document.getElementById("evoSpeciesSelect");
      select.innerHTML = options.map(opt => `<option value="${opt}">${opt}</option>`).join("");

      document.getElementById("evoCpInput").value = "";
      document.getElementById("evoHpInput").value = "";

      document.getElementById("evolveModal").classList.remove("hidden");
    }

    function closeEvolveModal() {
      document.getElementById("evolveModal").classList.add("hidden");
      currentEvolveId = null;
    }

    async function submitEvolve() {
      if (!currentEvolveId) return;
      const choice = document.getElementById("evoSpeciesSelect").value;
      const cp = document.getElementById("evoCpInput").value;
      const hp = document.getElementById("evoHpInput").value;

      if (!choice) {
        alert("Please select a species.");
        return;
      }
      if (!cp || !hp) {
        alert("Please enter both CP and HP.");
        return;
      }

      try {
        const res = await fetch(`/pokemon/${currentEvolveId}/evolve`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ new_species: choice, cp: Number(cp), hp: Number(hp) })
        });
        if (res.ok) {
          closeEvolveModal();
          loadDashboard();
        } else {
          alert("Failed to update evolution.");
        }
      } catch (err) {
        alert("Error submitting evolution: " + err);
      }
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

          // Always push missing/dash values to the bottom
          if (av === null && bv === null) return 0;
          if (av === null) return 1;
          if (bv === null) return -1;

          const comparison = typeof av === "number" && typeof bv === "number"
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
            <td><button onclick="event.stopPropagation(); evolveRow(${p.id})">Evolved →</button></td>
          </tr>
        `;
        const evoRow = isOpen ? `
          <tr class="evo-row">
            <td colspan="14">
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

async function openReviewModal() {
  const modal = document.getElementById("reviewModal");
  modal.classList.remove("hidden");
  await loadReviewQueue();
}

function closeReviewModal() {
  document.getElementById("reviewModal").classList.add("hidden");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function reviewCardHtml(row) {
  const id = Number(row.id);
  const reason = escapeHtml(row.review_reason || "No reason recorded");
  const name = escapeHtml(row.name || "");
  const tag = row.tag || "REVIEW";
  return `
    <section class="review-card" id="review-card-${id}">
      <div class="review-meta">
        ID ${id} · Current tag: ${escapeHtml(tag)} ·
        <span class="review-reason">${reason}</span>
      </div>
      <form class="review-form" onsubmit="saveReviewRecord(event, ${id})">
        <input name="name" value="${name}" placeholder="Species / form" required>
        <input name="cp" type="number" value="${Number(row.cp || 0)}" min="0" max="5500" required>
        <input name="hp" type="number" value="${Number(row.hp || 0)}" min="0" max="999" required>
        <input name="iv_atk" type="number" value="${Number(row.iv_atk || 0)}" min="0" max="15" required>
        <input name="iv_def" type="number" value="${Number(row.iv_def || 0)}" min="0" max="15" required>
        <input name="iv_sta" type="number" value="${Number(row.iv_sta || 0)}" min="0" max="15" required>
        <select name="tag">
          <option value="REVIEW" ${tag === "REVIEW" ? "selected" : ""}>Review</option>
          <option value="KEEP">Keep</option>
          <option value="TRANSFER">Transfer</option>
        </select>
        <input name="review_reason" value="${reason === "No reason recorded" ? "" : reason}" placeholder="Reason only if retaining Review">
        <button class="primary" type="submit">Save</button>
      </form>
      <button class="review-delete" type="button" onclick="deleteReviewRecord(${id}, '${name.replaceAll("'", "\\'")}')">Delete failed scan</button>
    </section>`;
}

async function loadReviewQueue() {
  const target = document.getElementById("reviewRows");
  const summary = document.getElementById("reviewSummary");
  target.innerHTML = '<div class="evo-loading">Loading review records…</div>';
  try {
    const response = await fetch("/api/review-records");
    const rows = await response.json();
    summary.textContent = `${rows.length} unresolved Review-tagged record${rows.length === 1 ? "" : "s"}`;
    target.innerHTML = rows.length
      ? rows.map(reviewCardHtml).join("")
      : '<div class="evo-empty">No unresolved Review-tagged records.</div>';
  } catch (error) {
    target.innerHTML = `<div class="evo-empty">Unable to load review records: ${escapeHtml(error)}</div>`;
  }
}

async function saveReviewRecord(event, pokemonId) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  for (const key of ["cp", "hp", "iv_atk", "iv_def", "iv_sta"]) {
    payload[key] = Number(payload[key]);
  }

  const response = await fetch(`/pokemon/${pokemonId}/review-update`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    alert(data.error || "Failed to save record.");
    return;
  }
  await loadReviewQueue();
  await loadDashboard();
}

async function deleteReviewRecord(pokemonId, name) {
  if (!confirm(`Delete local record ID ${pokemonId} (${name || "Unknown"})? This cannot be undone.`)) {
    return;
  }
  const response = await fetch(`/pokemon/${pokemonId}/delete`, {method: "POST"});
  const data = await response.json();
  if (!response.ok) {
    alert(data.error || "Failed to delete record.");
    return;
  }
  await loadReviewQueue();
  await loadDashboard();
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
        ORDER BY p.id DESC
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


@app.route("/pokemon/<int:pokemon_id>/evo_options")
def evo_options(pokemon_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT evo_name FROM evo_rankings WHERE pokemon_id = ?",
        (pokemon_id,)
    ).fetchall()
    return jsonify([r["evo_name"] for r in rows])


@app.route("/pokemon/<int:pokemon_id>/evolve", methods=["POST"])
def evolve_pokemon(pokemon_id):
    data = request.get_json()
    new_species = data.get("new_species")
    new_cp = data.get("cp")
    new_hp = data.get("hp")
    new_dust = data.get("dust")
    new_level = data.get("level")

    conn = get_db()
    row = conn.execute("SELECT * FROM pokemon WHERE id = ?", (pokemon_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    all_rankings = all_league_rankings_with_evos(
        new_species, row["iv_atk"], row["iv_def"], row["iv_sta"]
    )
    new_pvp = all_rankings.get(new_species, {"great": {}, "ultra": {}})

    nickname = promote_evolution(
        conn, pokemon_id, new_species, new_cp, new_hp, new_dust, new_level, new_pvp
    )
    return jsonify({"ok": True, "nickname": nickname})


@app.route("/api/review-records")
def review_records():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, name, cp, hp, iv_atk, iv_def, iv_sta,
               iv_pct, tag, needs_review, review_reason, caught_date
        FROM pokemon
        WHERE needs_review = 1
          AND tag = 'REVIEW'
        ORDER BY id DESC
        """
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/pokemon/<int:pokemon_id>/review-update", methods=["POST"])
def review_update_pokemon(pokemon_id):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    tag = str(data.get("tag", "REVIEW")).strip().upper()
    review_reason = str(data.get("review_reason", "")).strip()

    if not name:
        return jsonify(error="Species/form name is required."), 400
    if tag not in {"REVIEW", "KEEP", "TRANSFER"}:
        return jsonify(error="Invalid decision."), 400
    if tag == "REVIEW" and not review_reason:
        return jsonify(error="Enter a reason when retaining Review."), 400

    try:
        cp = int(data.get("cp", 0))
        hp = int(data.get("hp", 0))
        iv_atk = int(data.get("iv_atk", 0))
        iv_def = int(data.get("iv_def", 0))
        iv_sta = int(data.get("iv_sta", 0))
    except (TypeError, ValueError):
        return jsonify(error="CP, HP, and IVs must be integers."), 400

    if not 10 <= cp <= 5500:
        return jsonify(error="CP must be between 10 and 5500."), 400
    if not 10 <= hp <= 999:
        return jsonify(error="Maximum HP must be between 10 and 999."), 400
    if not all(0 <= value <= 15 for value in (iv_atk, iv_def, iv_sta)):
        return jsonify(error="Each IV must be from 0 through 15."), 400

    conn = get_db()
    row = conn.execute("SELECT * FROM pokemon WHERE id = ?", (pokemon_id,)).fetchone()
    if row is None:
        return jsonify(error="Pokémon record not found."), 404

    dust = row["dust"] if "dust" in row.keys() else None
    level = None
    iv_pct = round((iv_atk + iv_def + iv_sta) / 45 * 100, 1)
    try:
        from iv_calculator import compute_ivs
        iv_data = compute_ivs(name, cp, hp, iv_atk, iv_def, iv_sta, dust)
        level = iv_data.get("level")
        iv_pct = iv_data.get("iv_pct", iv_pct)
    except Exception:
        pass

    available_columns = {entry[1] for entry in conn.execute("PRAGMA table_info(pokemon)")}
    updates = {
        "name": name,
        "cp": cp,
        "hp": hp,
        "iv_atk": iv_atk,
        "iv_def": iv_def,
        "iv_sta": iv_sta,
        "iv_pct": iv_pct,
        "level": level,
        "tag": tag,
        "needs_review": int(tag == "REVIEW"),
        "review_reason": review_reason if tag == "REVIEW" else None,
    }
    updates = {key: value for key, value in updates.items() if key in available_columns}
    assignments = ", ".join(f"{key} = ?" for key in updates)
    conn.execute(
        f"UPDATE pokemon SET {assignments} WHERE id = ?",
        (*updates.values(), pokemon_id),
    )
    conn.commit()
    return jsonify(ok=True, id=pokemon_id, tag=tag)


@app.route("/pokemon/<int:pokemon_id>/delete", methods=["POST"])
def delete_pokemon(pokemon_id):
    conn = get_db()

    row = conn.execute(
        """
        SELECT id, name, cp, iv_atk, iv_def, iv_sta
        FROM pokemon
        WHERE id = ?
        """,
        (pokemon_id,),
    ).fetchone()

    if row is None:
        return jsonify(error="Pokémon record not found."), 404

    obvious_failed_scan = (
        row["name"] in (None, "", "Unknown")
        or (row["cp"] or 0) < 10
        or (
            (row["iv_atk"] or 0) == 0
            and (row["iv_def"] or 0) == 0
            and (row["iv_sta"] or 0) == 0
        )
    )

    if not obvious_failed_scan:
        return jsonify(
            error="Deletion is limited to obvious failed scans."
        ), 400

    tables = {
        entry["name"]
        for entry in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    if "evo_rankings" in tables:
        conn.execute(
            "DELETE FROM evo_rankings WHERE pokemon_id = ?",
            (pokemon_id,),
        )

    conn.execute(
        "DELETE FROM pokemon WHERE id = ?",
        (pokemon_id,),
    )
    conn.commit()

    return jsonify(ok=True, id=pokemon_id)


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