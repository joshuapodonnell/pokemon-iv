import sqlite3

conn = sqlite3.connect("pokemon_ivs.db")
conn.row_factory = sqlite3.Row

print("=== pokemon table ===")
rows = conn.execute("SELECT COUNT(*) as n FROM pokemon").fetchone()
print(f"  {rows['n']} total records\n")

print("=== evo_rankings table ===")
rows = conn.execute("SELECT COUNT(*) as n FROM evo_rankings").fetchone()
print(f"  {rows['n']} total evo records\n")

print("=== Latest 10 with evo rankings ===")
rows = conn.execute("""
    SELECT p.id, p.name, p.cp, p.iv_atk, p.iv_def, p.iv_sta,
           e.evo_name, e.gl_rank, e.gl_best_cp, e.ul_rank, e.ul_best_cp
    FROM evo_rankings e
    JOIN pokemon p ON p.id = e.pokemon_id
    ORDER BY p.id DESC
    LIMIT 10
""").fetchall()
for r in rows:
    print(f"  #{r['id']} {r['name']} {r['iv_atk']}/{r['iv_def']}/{r['iv_sta']}"
          f" → {r['evo_name']} GL:{r['gl_rank']} ({r['gl_best_cp']}cp)"
          f" UL:{r['ul_rank']} ({r['ul_best_cp']}cp)")

conn.close()