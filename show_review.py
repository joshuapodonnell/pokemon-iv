# show_review.py
from database import get_db

conn = get_db()
rows = conn.execute("""
    SELECT name, cp, iv_atk, iv_def, iv_sta, iv_pct, gl_rank, ul_rank
    FROM pokemon
    WHERE needs_review = 1
    ORDER BY name, gl_rank
""").fetchall()

print(f"{'Name':<15} {'CP':>5}  {'IVs':<8}  {'IV%':>5}  {'GL':>6}  {'UL':>6}")
print("─" * 55)
for r in rows:
    ivs = f"{r['iv_atk']}/{r['iv_def']}/{r['iv_sta']}"
    gl  = f"#{r['gl_rank']}" if r['gl_rank'] else "  —"
    ul  = f"#{r['ul_rank']}" if r['ul_rank'] else "  —"
    print(f"{r['name']:<15} {r['cp']:>5}  {ivs:<8}  {r['iv_pct']:>5.1f}  {gl:>6}  {ul:>6}")

conn.close()