#!/usr/bin/env python3
"""
benchmark_report.py — Review CP-consensus disagreements and report OCR/VLM/
reconciled accuracy for the Pokemon GO IV Cataloger's CP parsing pipeline.

Usage:
    python benchmark_report.py                    # auto-label agreements, print report
    python benchmark_report.py --review            # also interactively label disagreements
    python benchmark_report.py --review --limit 20 # only review 20 rows this run
    python benchmark_report.py --skip-auto-label    # report only, no auto-labeling
"""
import argparse
import json
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path

DB_FILE = "pokemon_ivs.db"


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def has_column(conn, table, col):
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    return col in cols


def auto_label_agreements(conn):
    """Rows where OCR and the reconciled result already agree are treated as
    ground truth automatically. This is an assumption, not proof — it can't
    catch cases where OCR and VLM agree on the same wrong number — so the
    disagreement subset (reviewed separately) still matters."""
    cur = conn.execute("""
        UPDATE cp_consensus_log
        SET ground_truth_cp = reconciled_cp
        WHERE ground_truth_cp IS NULL
          AND ocr_cp IS NOT NULL
          AND ocr_cp = reconciled_cp
    """)
    conn.commit()
    return cur.rowcount


def open_images(paths):
    existing = [p for p in paths if p and Path(p).exists()]
    missing = [p for p in paths if p and not Path(p).exists()]
    if existing:
        subprocess.run(["open"] + existing)
    return existing, missing


def review_pending(conn, limit=None):
    query = """
        SELECT id, visit_num, ocr_cp, ocr_raw, ocr_image_path,
               vlm_votes, vlm_consensus, reconciled_cp, reconcile_reason, frame_paths
        FROM cp_consensus_log
        WHERE ground_truth_cp IS NULL
        ORDER BY id
    """
    rows = conn.execute(query).fetchall()
    if limit:
        rows = rows[:limit]

    if not rows:
        print("No pending rows need review — every logged catch already has ground truth.")
        return

    print(f"\n{len(rows)} rows pending review.")
    print("Images will open in Preview for each row. Enter the TRUE CP you see,")
    print("'s' to skip (leave unlabeled), or 'q' to stop reviewing.\n")

    for i, r in enumerate(rows, 1):
        votes = json.loads(r["vlm_votes"] or "[]")
        frames = json.loads(r["frame_paths"] or "[]")
        all_images = [r["ocr_image_path"]] + frames

        print(f"\n[{i}/{len(rows)}] id={r['id']}  visit={r['visit_num']}")
        print(f"  OCR raw={r['ocr_raw']!r}  ->  OCR_CP={r['ocr_cp']}")
        print(f"  VLM votes={votes}  ->  VLM_consensus={r['vlm_consensus']}")
        print(f"  Reconciled={r['reconciled_cp']}   reason={r['reconcile_reason']}")

        existing, missing = open_images(all_images)
        if missing:
            print(f"  (missing image files, could not open: {missing})")
        if not existing:
            print("  No images available for this row — you'll need to label from context only.")

        while True:
            ans = input("  True CP (number / s=skip / q=quit): ").strip().lower()
            if ans == "q":
                print("Stopping review — progress saved so far.")
                return
            if ans == "s":
                break
            if ans.isdigit():
                conn.execute(
                    "UPDATE cp_consensus_log SET ground_truth_cp = ? WHERE id = ?",
                    (int(ans), r["id"]),
                )
                conn.commit()
                break
            print("  Please enter a number, 's', or 'q'.")


def print_report(conn):
    rows = conn.execute(
        "SELECT * FROM cp_consensus_log WHERE ground_truth_cp IS NOT NULL"
    ).fetchall()
    total = len(rows)
    total_logged = conn.execute("SELECT COUNT(*) FROM cp_consensus_log").fetchone()[0]
    pending = total_logged - total

    print("\n" + "=" * 64)
    print("CP CONSENSUS BENCHMARK REPORT")
    print("=" * 64)
    print(f"Total logged catches:   {total_logged}")
    print(f"Ground-truth labeled:   {total}")
    print(f"Still pending review:   {pending}")

    if total == 0:
        print("\nNo labeled rows yet.")
        print("Run: python benchmark_report.py --review   (to label disagreements)")
        print("=" * 64 + "\n")
        return

    ocr_correct = sum(1 for r in rows if r["ocr_cp"] == r["ground_truth_cp"])
    vlm_correct = sum(1 for r in rows if r["vlm_consensus"] == r["ground_truth_cp"])
    final_correct = sum(1 for r in rows if r["reconciled_cp"] == r["ground_truth_cp"])
    agree = sum(1 for r in rows if r["ocr_cp"] == r["vlm_consensus"])

    print(f"\nn={total}")
    print(f"  OCR accuracy:        {ocr_correct}/{total}  ({ocr_correct/total:.1%})")
    print(f"  VLM accuracy:        {vlm_correct}/{total}  ({vlm_correct/total:.1%})")
    print(f"  Reconciled accuracy: {final_correct}/{total}  ({final_correct/total:.1%})")
    print(f"  OCR/VLM agreement:   {agree}/{total}  ({agree/total:.1%})")

    print("\nBy reconcile_reason (reconciled-vs-truth accuracy):")
    by_reason = defaultdict(lambda: {"n": 0, "correct": 0})
    for r in rows:
        reason = r["reconcile_reason"] or "unknown"
        by_reason[reason]["n"] += 1
        if r["reconciled_cp"] == r["ground_truth_cp"]:
            by_reason[reason]["correct"] += 1
    for reason, d in sorted(by_reason.items(), key=lambda kv: -kv[1]["n"]):
        pct = d["correct"] / d["n"] if d["n"] else 0
        print(f"  {reason:<28} n={d['n']:<4} correct={d['correct']:<4} ({pct:.1%})")

    if has_column(conn, "cp_consensus_log", "vlm_backends"):
        print("\nBy VLM backend (remote 30B vs local 4B fallback):")
        by_backend = defaultdict(lambda: {"n": 0, "correct": 0})
        for r in rows:
            raw_backends = r["vlm_backends"] if "vlm_backends" in r.keys() else None
            backends = json.loads(raw_backends) if raw_backends else []
            tag = "local" if "local" in backends else ("remote" if backends else "unknown")
            by_backend[tag]["n"] += 1
            if r["vlm_consensus"] == r["ground_truth_cp"]:
                by_backend[tag]["correct"] += 1
        for tag, d in by_backend.items():
            pct = d["correct"] / d["n"] if d["n"] else 0
            print(f"  {tag:<10} n={d['n']:<4} vlm_correct={d['correct']:<4} ({pct:.1%})")
    else:
        print("\n(No 'vlm_backends' column yet — add it to see remote-vs-local breakdown.)")

    misses = [r for r in rows if r["reconciled_cp"] != r["ground_truth_cp"]]
    print(f"\nMismatches where final result was wrong ({len(misses)}):")
    if not misses:
        print("  None — reconciled CP matched ground truth on every labeled row.")
    for r in misses:
        print(f"  id={r['id']} visit={r['visit_num']}  OCR={r['ocr_cp']} "
              f"VLM={r['vlm_consensus']} final={r['reconciled_cp']} "
              f"truth={r['ground_truth_cp']}  reason={r['reconcile_reason']}")

    print("=" * 64 + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--review", action="store_true",
                    help="Interactively label pending disagreement rows using saved images")
    p.add_argument("--limit", type=int, default=None,
                    help="Limit number of rows to review this run")
    p.add_argument("--skip-auto-label", action="store_true",
                    help="Don't auto-label OCR==reconciled rows before reporting")
    args = p.parse_args()

    conn = get_conn()

    if not args.skip_auto_label:
        n = auto_label_agreements(conn)
        if n:
            print(f"Auto-labeled {n} rows where OCR and the reconciled CP already agreed.")

    if args.review:
        review_pending(conn, limit=args.limit)

    print_report(conn)
    conn.close()


if __name__ == "__main__":
    main()
