#!/usr/bin/env python3
"""
benchmark_gui.py — Local web GUI for reviewing CP-consensus rows and labeling
ground truth.
"""
import json
import sqlite3
import os
from pathlib import Path

from flask import Flask, request, redirect, session, send_file, abort, render_template_string

DB_FILE = os.path.join(os.path.dirname(__file__), "benchmark_logs.db")
app = Flask(__name__)
app.secret_key = "pogo-iv-benchmark-local-only"

BENCHMARK_SCHEMA = """
CREATE TABLE IF NOT EXISTS cp_consensus_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT DEFAULT (datetime('now')),
    visit_num         INTEGER,
    ocr_cp            INTEGER,
    ocr_raw           TEXT,
    ocr_image_path    TEXT,
    vlm_votes         TEXT,
    vlm_backends      TEXT,
    vlm_consensus     INTEGER,
    reconciled_cp     INTEGER,
    reconcile_reason  TEXT,
    ground_truth_cp   INTEGER,
    frame_paths       TEXT,
    label_source      TEXT
);
"""


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.executescript(BENCHMARK_SCHEMA)
    return conn


def retract_untrustworthy_autolabels(conn):
    cur = conn.execute("""
        UPDATE cp_consensus_log
        SET ground_truth_cp = NULL, label_source = NULL
        WHERE reconcile_reason != 'agree'
          AND ground_truth_cp = reconciled_cp
          AND (label_source IS NULL OR label_source = 'auto_agree')
    """)
    conn.commit()
    return cur.rowcount


def auto_label_agreements(conn):
    cur = conn.execute("""
        UPDATE cp_consensus_log
        SET ground_truth_cp = reconciled_cp, label_source = 'auto_agree'
        WHERE ground_truth_cp IS NULL
          AND reconcile_reason = 'agree'
    """)
    conn.commit()
    return cur.rowcount


PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>CP Consensus Review</title>
<style>
  body { font-family: -apple-system, sans-serif; background:#1e1e1e; color:#eee; margin:0; padding:24px; }
  .bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; background:#2a2a2a; padding:12px 16px; border-radius:8px; }
  .bar a { color:#7ab8ff; text-decoration:none; margin-left:12px; font-weight:600; }
  .bar a.active { color:#fff; border-bottom: 2px solid #7ab8ff; }
  .progress { color:#aaa; font-weight: 500; }

  /* Mode Description Cards */
  .mode-desc-container { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
  .mode-card { background:#252525; border: 1px solid #333; border-radius:8px; padding:12px 16px; text-decoration:none; color:inherit; display:block; transition: border-color 0.2s; }
  .mode-card:hover { border-color:#7ab8ff; }
  .mode-card.active-mode { border-color:#2d7a3d; background:#1e2e22; }
  .mode-card h4 { margin: 0 0 6px 0; color:#7ab8ff; font-size:14px; }
  .mode-card p { margin: 0; color:#aaa; font-size:12px; line-height:1.4; }

  .images { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:16px; }
  .images figure { margin:0; background:#2a2a2a; padding:8px; border-radius:8px; }
  .images img { max-height:160px; display:block; border-radius:4px; }
  .images figcaption { font-size:12px; color:#999; margin-top:4px; text-align:center; }
  .missing { color:#e67; font-size:13px; }
  .info { background:#2a2a2a; border-radius:8px; padding:16px; margin-bottom:16px; line-height:1.6; }
  .info b { color:#7ab8ff; }
  .reason { display:inline-block; padding:2px 8px; border-radius:4px; background:#444; font-size:13px; }
  .reason.agree { background:#2d5a2d; }
  .reason.trust { background:#5a4a2d; }
  form { display:flex; gap:10px; align-items:center; }
  input[type=text] { font-size:18px; padding:8px 12px; width:120px; border-radius:6px; border:1px solid #555; background:#111; color:#eee; }
  button { font-size:15px; padding:8px 16px; border-radius:6px; border:none; cursor:pointer; }
  button.confirm { background:#2d7a3d; color:#fff; }
  button.save { background:#2d6a9d; color:#fff; }
  button.skip { background:#555; color:#eee; }
  button.stop { background:#7a2d2d; color:#fff; }
  .done { font-size:20px; margin-top:40px; }
</style>
</head>
<body>

<div class="bar">
  <div class="progress">Active Mode: <b>{{ mode|upper }}</b> &middot; Item {{ idx + 1 }} of {{ total }}</div>
  <div>
    <a href="/?mode=pending" class="{{ 'active' if mode == 'pending' else '' }}">Pending</a>
    <a href="/?mode=auto" class="{{ 'active' if mode == 'auto' else '' }}">Auto-Agreed</a>
    <a href="/?mode=audit" class="{{ 'active' if mode == 'audit' else '' }}">Audit All</a>
    <a href="/report">Full Report</a>
  </div>
</div>

<!-- Mode description navigation blocks -->
<div class="mode-desc-container">
  <a href="/?mode=pending" class="mode-card {{ 'active-mode' if mode == 'pending' else '' }}">
    <h4>Pending Mode</h4>
    <p>Shows only rows with no ground truth assigned yet (<code>ground_truth_cp IS NULL</code>). Use this to label new catches.</p>
  </a>
  <a href="/?mode=auto" class="mode-card {{ 'active-mode' if mode == 'auto' else '' }}">
    <h4>Auto-Agreed Mode</h4>
    <p>Shows rows automatically labeled because OCR and VLM independently matched. Use this to spot-check AI consensus accuracy.</p>
  </a>
  <a href="/?mode=audit" class="mode-card {{ 'active-mode' if mode == 'audit' else '' }}">
    <h4>Audit All Mode</h4>
    <p>Shows every single row in the database unconditionally for a complete end-to-end inspection pass.</p>
  </a>
</div>

{% if row %}
  <div class="images">
    {% for img in images %}
      <figure><img src="/img?path={{ img.path|urlencode }}"><figcaption>{{ img.label }}</figcaption></figure>
    {% endfor %}
    {% if not images %}
      <div class="missing">No saved images for this row.</div>
    {% endif %}
  </div>

  <div class="info">
    <b>id</b> {{ row.id }} &nbsp; <b>visit</b> {{ row.visit_num }}<br>
    <b>OCR raw</b> {{ row.ocr_raw }} &rarr; <b>OCR CP</b> {{ row.ocr_cp }}<br>
    <b>VLM votes</b> {{ votes }} &rarr; <b>VLM consensus</b> {{ row.vlm_consensus }}<br>
    <b>Reconciled</b> {{ row.reconciled_cp }} &nbsp;
    <span class="reason {{ 'agree' if row.reconcile_reason == 'agree' else 'trust' }}">{{ row.reconcile_reason }}</span><br>
    <b>Current ground truth</b> {{ row.ground_truth_cp }} &nbsp;
    <span style="color:#999">({{ row.label_source or 'unset' }})</span>
  </div>

  <form method="post" action="/label">
    <input type="hidden" name="row_id" value="{{ row.id }}">
    <input type="hidden" name="mode" value="{{ mode }}">
    <input type="text" name="cp" placeholder="True CP" value="{{ suggested_cp }}" autofocus>
    <button class="save" type="submit" name="action" value="save">Save &amp; Next</button>
    <button class="confirm" type="submit" name="action" value="confirm">Confirm shown value</button>
    <button class="skip" type="submit" name="action" value="skip">Skip</button>
    <button class="stop" type="submit" name="action" value="stop">Stop here</button>
  </form>
{% else %}
  <div class="done">
    {{ done_message }}
  </div>
{% endif %}

</body>
</html>
"""

REPORT_PAGE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>Benchmark Report</title>
<style>
  body { font-family: -apple-system, sans-serif; background:#1e1e1e; color:#eee; padding:24px; }
  a { color:#7ab8ff; }
  pre { background:#111; padding:16px; border-radius:8px; }
</style></head>
<body>
<a href="/?mode=pending">&larr; Back to review</a>
<pre>{{ report_text }}</pre>
</body></html>
"""


def _row_images(row):
    images = []
    if row["ocr_image_path"] and Path(row["ocr_image_path"]).exists():
        images.append({"path": row["ocr_image_path"], "label": "OCR crop"})
    frames = json.loads(row["frame_paths"] or "[]")
    for i, f in enumerate(frames, 1):
        if f and Path(f).exists():
            images.append({"path": f, "label": f"VLM frame {i}"})
    return images


def _get_rows(conn, mode, limit):
    if mode == "audit":
        q = "SELECT * FROM cp_consensus_log ORDER BY id"
    elif mode == "auto":
        q = "SELECT * FROM cp_consensus_log WHERE label_source = 'auto_agree' ORDER BY id"
    else:  # default to "pending"
        q = "SELECT * FROM cp_consensus_log WHERE ground_truth_cp IS NULL ORDER BY id"

    rows = conn.execute(q).fetchall()
    if limit:
        rows = rows[:limit]
    return [r["id"] for r in rows]


@app.route("/")
def index():
    mode = request.args.get("mode", "pending")
    limit = request.args.get("limit", type=int)

    if session.get("mode") != mode or "row_ids" not in session or request.args.get("reset"):
        conn = get_conn()
        retract_untrustworthy_autolabels(conn)
        auto_label_agreements(conn)
        session["row_ids"] = _get_rows(conn, mode, limit)
        session["mode"] = mode
        session["idx"] = 0
        conn.close()

    row_ids = session["row_ids"]
    idx = session.get("idx", 0)
    total = len(row_ids)

    if idx >= total or total == 0:
        msg = "No rows to show." if total == 0 else "All done! Every row in this pass has been handled."
        return render_template_string(PAGE, row=None, mode=mode, idx=idx, total=max(total, 1), done_message=msg)

    conn = get_conn()
    row = conn.execute("SELECT * FROM cp_consensus_log WHERE id = ?", (row_ids[idx],)).fetchone()
    conn.close()

    images = _row_images(row)
    votes = json.loads(row["vlm_votes"] or "[]")
    suggested_cp = row["ground_truth_cp"] if row["ground_truth_cp"] is not None else row["reconciled_cp"]

    return render_template_string(
        PAGE, row=row, mode=mode, idx=idx, total=total,
        images=images, votes=votes, suggested_cp=suggested_cp, done_message="",
    )


@app.route("/label", methods=["POST"])
def label():
    row_id = int(request.form["row_id"])
    mode = request.form.get("mode", "pending")
    action = request.form.get("action")

    conn = get_conn()
    if action == "save":
        cp_text = request.form.get("cp", "").strip()
        if cp_text.isdigit():
            conn.execute(
                "UPDATE cp_consensus_log SET ground_truth_cp = ?, label_source = 'manual' WHERE id = ?",
                (int(cp_text), row_id),
            )
            conn.commit()
    elif action == "confirm":
        row = conn.execute("SELECT reconciled_cp FROM cp_consensus_log WHERE id = ?", (row_id,)).fetchone()
        conn.execute(
            "UPDATE cp_consensus_log SET ground_truth_cp = ?, label_source = 'manual' WHERE id = ?",
            (row["reconciled_cp"], row_id),
        )
        conn.commit()
    conn.close()

    if action == "stop":
        session["idx"] = len(session.get("row_ids", []))
        return redirect(f"/report")

    session["idx"] = session.get("idx", 0) + 1
    return redirect(f"/?mode={mode}")


@app.route("/img")
def img():
    rel = request.args.get("path", "")
    if not (rel.startswith("screenshots/") or rel.startswith("training_images/")) or ".." in rel:
        abort(403)
    full = Path(rel)
    if not full.exists():
        abort(404)
    return send_file(full)


@app.route("/report")
def report():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cp_consensus_log WHERE ground_truth_cp IS NOT NULL").fetchall()
    total = len(rows)
    total_logged = conn.execute("SELECT COUNT(*) FROM cp_consensus_log").fetchone()[0]

    lines = [
        "CP CONSENSUS BENCHMARK REPORT",
        "=" * 50,
        f"Total logged catches:   {total_logged}",
        f"Ground-truth labeled:   {total}",
        f"Still pending review:   {total_logged - total}",
    ]

    if total > 0:
        ocr_correct = sum(1 for r in rows if r["ocr_cp"] == r["ground_truth_cp"])
        vlm_correct = sum(1 for r in rows if r["vlm_consensus"] == r["ground_truth_cp"])
        final_correct = sum(1 for r in rows if r["reconciled_cp"] == r["ground_truth_cp"])
        lines += [
            "",
            f"n={total}",
            f"  OCR accuracy:        {ocr_correct}/{total}  ({ocr_correct / total:.1%})",
            f"  VLM accuracy:        {vlm_correct}/{total}  ({vlm_correct / total:.1%})",
            f"  Reconciled accuracy: {final_correct}/{total}  ({final_correct / total:.1%})",
        ]
        misses = [r for r in rows if r["reconciled_cp"] != r["ground_truth_cp"]]
        lines.append(f"\nMismatches ({len(misses)}):")
        for r in misses:
            lines.append(f"  id={r['id']} visit={r['visit_num']} OCR={r['ocr_cp']} "
                         f"VLM={r['vlm_consensus']} final={r['reconciled_cp']} "
                         f"truth={r['ground_truth_cp']} reason={r['reconcile_reason']}")
    conn.close()
    return render_template_string(REPORT_PAGE, report_text="\n".join(lines))


if __name__ == "__main__":
    print("Starting review GUI at http://0.0.0.0:5050/?mode=pending")
    app.run(host="0.0.0.0", port=5050, debug=False)