import os
import json
import sqlite3
from pathlib import Path

# Connect to your new isolated benchmark database
DB_FILE = "benchmark_logs.db"
IMAGE_DIR = "training_images"


def prune_orphans():
    if not os.path.exists(IMAGE_DIR):
        print(f"Directory '{IMAGE_DIR}' not found. Nothing to prune.")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    valid_paths = set()

    # 1. Gather all valid paths currently referenced in the database
    try:
        rows = conn.execute("SELECT ocr_image_path, frame_paths FROM cp_consensus_log").fetchall()
        for row in rows:
            if row["ocr_image_path"]:
                valid_paths.add(os.path.normpath(row["ocr_image_path"]))

            # Extract paths from the JSON-encoded frame_paths column
            frames = json.loads(row["frame_paths"] or "[]")
            for f in frames:
                if f:
                    valid_paths.add(os.path.normpath(f))
    except sqlite3.OperationalError:
        print(f"Table cp_consensus_log not found in {DB_FILE}. Have you run the bot yet?")
        return
    finally:
        conn.close()

    # 2. Scan the directory and safely delete orphans
    deleted_count = 0
    kept_count = 0

    print(f"Scanning {IMAGE_DIR}/ for unreferenced images...")

    for filepath in Path(IMAGE_DIR).glob("*.png"):
        normalized_path = os.path.normpath(str(filepath))

        if normalized_path not in valid_paths:
            os.remove(filepath)
            deleted_count += 1
        else:
            kept_count += 1

    print(f"Cleanup complete!")
    print(f"  - Kept: {kept_count} valid training images")
    print(f"  - Deleted: {deleted_count} orphaned images")


if __name__ == "__main__":
    prune_orphans()