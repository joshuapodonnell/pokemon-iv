# dashboard_server.py
from flask import Flask, jsonify, request
from database import get_db

app = Flask(__name__)

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)