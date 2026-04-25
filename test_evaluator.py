# test_evaluator.py
import sqlite3
from database import get_db
from evaluator import evaluate_catch, find_displaced, flag_displaced

conn = get_db(":memory:")  # pass ":memory:" so nothing hits disk

# Test hundo
r = evaluate_catch(conn, "Pikachu", 500, 15, 15, 15, 100.0, {}, {})
assert r["action"] == "KEEP", f"Expected KEEP, got {r['action']}"
assert "hundo" in r["reasons"][0].lower()
print("✓ hundo → KEEP")

# Test nundo
r = evaluate_catch(conn, "Pikachu", 10, 0, 0, 0, 0.0, {}, {})
assert r["action"] == "KEEP", f"Expected KEEP, got {r['action']}"
assert "nundo" in r["reasons"][0].lower()
print("✓ nundo → KEEP")

# Test first of species → always keep
r = evaluate_catch(conn, "Rattata", 200, 5, 5, 5, 33.3, {}, {})
assert r["action"] == "KEEP", f"Expected KEEP, got {r['action']}"
assert r["beats_existing"] == True
print("✓ first of species → KEEP")

# Test displacement: insert rank-100, then find rank-50 beats it
conn.execute("""
    INSERT INTO pokemon (name, cp, iv_atk, iv_def, iv_sta, iv_pct, gl_rank)
    VALUES (?,?,?,?,?,?,?)
""", ("Pikachu", 500, 8, 14, 13, 77.8, 100))
conn.commit()

r = evaluate_catch(conn, "Pikachu", 480, 1, 15, 14, 66.7,
                   {"great": {"rank": 50, "percentile": 95.0}}, {})
assert r["beats_existing"] == True
assert r["action"] == "KEEP"
print("✓ better GL rank → beats_existing")

displaced = flag_displaced(conn)
print(f"✓ displaced: {[p['name'] + ' GL#' + str(p['gl_rank']) for p in displaced]}")

print("\nAll tests passed ✓")
conn.close()