#!/usr/bin/env python3
"""
benchmark_report.py — Review CP-consensus rows and report OCR/VLM/reconciled
accuracy for the Pokemon GO IV Cataloger's CP parsing pipeline.

Modes:
    python benchmark_report.py                     # auto-label true agreements, print report
    python benchmark_report.py --review             # review only rows that still need a label
    python benchmark_report.py --audit               # review EVERY row (including auto-labeled
                                                       # 'agree' rows) — use this to spot-check that
                                                       # OCR/VLM agreement is actually correct, not
                                                       # just self-consistent
    python benchmark_report.py --audit --limit 20     # cap how many rows to look at this run
    python benchmark_report.py --skip-auto-label       # report only, no auto-labeling

Ground-truth labeling rules:
    - Only reconcile_reason == 'agree' rows are auto-labeled. Every other
      reason (slash_assumed_7, vlm_trailing_digit, same_length_trust_vlm, ...)
      means the reconciler picked a side WITHOUT independent confirmation —
      auto-trusting those would just measure the reconciler agreeing with
      itself, not whether it was right.
    - label_source tracks how each ground_truth_cp was set: 'auto_agree'
      (both sides matched independently) or 'manual' (you looked at the
      image and typed/confirmed a value).
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
    _ensure_label_source_column(conn)
    return conn


def has_column(conn, table, col):
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    return col in cols


def _ensure_label_source_column(conn):
    if not has_column(conn, "cp_consensus_log", "label_source"):
        conn.execute("ALTER TABLE cp_consensus_log ADD COLUMN label_source TEXT")
        conn.commit()


def retract_untrustworthy_autolabels(conn):
    """One-time cleanup: undo ground truth that was set to reconciled_cp for
    any row whose reconcile_reason wasn't 'agree' (i.e. labeled by the old,
    buggy version of this script before reason-filtering was added)."""
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
    """Only trust rows where OCR and VLM independently landed on the same
    number (reconcile_reason == 'agree'). Any other reason means the
    reconciler picked a side without cross-confirmation."""
    cur = conn.execute("""
        UPDATE cp_consensus_log
        SET ground_truth_cp = reconciled_cp, label_source = 'auto_agree'
        WHERE ground_truth_cp IS NULL
          AND reconcile_reason = 'agree'
    """)
    conn.commit()
    return cur.rowcount


def open_images(paths):
    existing = [p for p in paths if p and Path(p).exists()]
    missing = [p for p in paths if p and not Path(p).exists()]
    if existing:
        subprocess.run(["open"] + existing)
    return existing, missing


def _print_row(r, index, total):
    votes = json.loads(r["vlm_votes"] or "[]")
    print(f"\n[{index}/{total}] id={r['id']}  visit={r['visit_num']}")
    print(f"  OCR raw={r['ocr_raw']!r}  ->  OCR_CP={r['ocr_cp']}")
    print(f"  VLM votes={votes}  ->  VLM_consensus={r['vlm_consensus']}")
    print(f"  Reconciled={r['reconciled_cp']}   reason={r['reconcile_reason']}")
    print(f"  Current ground_truth={r['ground_truth_cp']}   label_source={r['label_source']}")


def _prompt_and_label(conn, r, allow_confirm_default=False):
    votes = json.loads(r["vlm_votes"] or "[]")
    frames = json.loads(r["frame_paths"] or "[]")
    all_images = [r["ocr_image_path"]] + frames
    existing, missing = open_images(all_images)
    if missing:
        print(f"  (missing image files, could not open: {missing})")
    if not existing:
        print("  No images available for this row — label from context only.")

    default_hint = f" [enter = keep {r['ground_truth_cp']}]" if allow_confirm_default and r["ground_truth_cp"] is not None else ""
    while True:
        ans = input(f"  True CP (number / s=skip / q=quit){default_hint}: ").strip().lower()
        if ans == "q":
            return "quit"
        if ans == "s":
            return "skip"
        if ans == "" and allow_confirm_default and r["ground_truth_cp"] is not None:
            conn.execute(
                "UPDATE cp_consensus_log SET label_source = 'manual' WHERE id = ?",
                (r["id"],),
            )
            conn.commit()
            return "confirmed"
        if ans.isdigit():
            conn.execute(
                "UPDATE cp_consensus_log SET ground_truth_cp = ?, label_source = 'manual' WHERE id = ?",
                (int(ans), r["id"]),
            )
            conn.commit()
            return "labeled"
        print("  Please enter a number, 's', or 'q' (or press enter to confirm the current value).")


def review_pending(conn, limit=None):
    rows = conn.execute("""
        SELECT * FROM cp_consensus_log WHERE ground_truth_cp IS NULL ORDER BY id
    """).fetchall()
    if limit:
        rows = rows[:limit]
    if not rows:
        print("No pending rows need review — every logged catch already has ground truth.")
        return
    print(f"\n{len(rows)} rows pending review. Images open in Preview for each.\n")
    for i, r in enumerate(rows, 1):
        _print_row(r, i, len(rows))
        result = _prompt_and_label(conn, r)
        if result == "quit":
            print("Stopping review — progress saved so far.")
            return


def audit_all(conn, limit=None):
    """Walk EVERY row, including already-labeled 'agree' rows, so you can
    spot-check that agreement actually means correctness, not just that the
    reconciler was internally consistent."""
    rows = conn.execute("SELECT * FROM cp_consensus_log ORDER BY id").fetchall()
    if limit:
        rows = rows[:limit]
    if not rows:
        print("No rows logged yet.")
        return
    print(f"\nAuditing {len(rows)} rows (all of them, labeled or not).")
    print("Press enter to confirm the current ground truth, type a number to correct it,\n"
          "'s' to skip without touching this row, or 'q' to stop.\n")
    for i, r in enumerate(rows, 1):
        _print_row(r, i, len(rows))
        result = _prompt_and_label(conn, r, allow_confirm_default=True)
        if result == "quit":
            print("Stopping audit — progress saved so far.")
            return


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
        print("Run: python benchmark_report.py --review   (label pending rows)")
        print("Run: python benchmark_report.py --audit     (spot-check everything)")
        print("=" * 64 + "\n")
        return

    auto_n = sum(1 for r in rows if r["label_source"] == "auto_agree")
    manual_n = sum(1 for r in rows if r["label_source"] == "manual")
    print(f"  (auto-labeled: {auto_n}, manually verified: {manual_n}, other/legacy: {total - auto_n - manual_n})")

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
        print(f"  {reason:<32} n={d['n']:<4} correct={d['correct']:<4} ({pct:.1%})")

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
                    help="Interactively label rows that still need ground truth")
    p.add_argument("--audit", action="store_true",
                    help="Interactively spot-check EVERY row, including auto-labeled agreements")
    p.add_argument("--limit", type=int, default=None,
                    help="Limit number of rows to review/audit this run")
    p.add_argument("--skip-auto-label", action="store_true",
                    help="Don't auto-label true-agreement rows before reporting")
    args = p.parse_args()

    conn = get_conn()

    retracted = retract_untrustworthy_autolabels(conn)
    if retracted:
        print(f"Retracted {retracted} previously auto-labeled rows whose reconcile_reason "
              f"wasn't 'agree' (they weren't independently cross-checked).")

    if not args.skip_auto_label:
        n = auto_label_agreements(conn)
        if n:
            print(f"Auto-labeled {n} rows where OCR and VLM independently agreed.")

    if args.audit:
        audit_all(conn, limit=args.limit)
    elif args.review:
        review_pending(conn, limit=args.limit)

    print_report(conn)
    conn.close()


if __name__ == "__main__":
    main()
