import sqlite3, json
conn = sqlite3.connect("pokemon_ivs.db")
rows = conn.execute("SELECT * FROM cp_consensus_log WHERE ground_truth_cp IS NOT NULL").fetchall()
total = len(rows)
ocr_correct = sum(1 for r in rows if r["ocr_cp"] == r["ground_truth_cp"])
vlm_correct = sum(1 for r in rows if r["vlm_consensus"] == r["ground_truth_cp"])
final_correct = sum(1 for r in rows if r["reconciled_cp"] == r["ground_truth_cp"])
print(f"n={total}  OCR:{ocr_correct/total:.1%}  VLM:{vlm_correct/total:.1%}  Final:{final_correct/total:.1%}")