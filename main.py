#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import time
import traceback
import re
import pytesseract
from pytesseract import Output
from PIL import ImageEnhance, ImageDraw, Image

from ocr_parser import (
    resolvespeciesname,
    parsecp, parsehp,
    ocrregion, getrelativeregion, parseivbars, parse_caught_date,
    readappraisalbars, readappraisalbarsdebug
)
from pvp_rankings import all_league_rankings_with_evos
from database import get_db, get_stats, insert_pokemon, insert_evo_rankings, find_duplicate, get_evo_rankings
from evaluator import evaluate_catch, find_displaced, flag_displaced
from tagger import apply_ingame_tag, tags_are_calibrated

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def parseargs():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--mode", choices=["catalog", "newcatch"], default="catalog",
                   help="catalog: scan age0 box. newcatch: appraise most recent catch only.")
    return p.parse_args()


# ── Helpers ───────────────────────────────────────────────────────────────────
def detect_description_lines(raw_crop, debug=False, debug_path=None):
    w, h = raw_crop.size
    img = raw_crop.resize((w * 3, h * 3), Image.Resampling.LANCZOS).convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)

    data = pytesseract.image_to_data(
        img,
        config="--psm 6 --oem 3",
        output_type=Output.DICT,
    )

    line_map = {}
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue

        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = -1

        if conf < 20:
            continue

        key = (
            data["block_num"][i],
            data["par_num"][i],
            data["line_num"][i],
        )
        entry = line_map.setdefault(key, {
            "words": [],
            "conf": [],
            "left": 10**9,
            "top": 10**9,
            "right": -1,
            "bottom": -1,
        })

        l = data["left"][i]
        t = data["top"][i]
        ww = data["width"][i]
        hh = data["height"][i]

        entry["words"].append(text)
        entry["conf"].append(conf)
        entry["left"] = min(entry["left"], l)
        entry["top"] = min(entry["top"], t)
        entry["right"] = max(entry["right"], l + ww)
        entry["bottom"] = max(entry["bottom"], t + hh)

    lines = []
    for v in line_map.values():
        text = " ".join(v["words"]).strip()
        avg_conf = sum(v["conf"]) / max(1, len(v["conf"]))
        width = v["right"] - v["left"]
        height = v["bottom"] - v["top"]
        alnum = sum(ch.isalnum() for ch in text)

        if alnum < 4:
            continue
        if avg_conf < 35 and width < w * 0.45 * 3:
            continue

        lines.append({
            "text": text,
            "left": v["left"],
            "right": v["right"],
            "top": v["top"],
            "bottom": v["bottom"],
            "height": height,
            "width": width,
            "avg_conf": avg_conf,
        })

    lines.sort(key=lambda x: x["top"])

    if not lines:
        return 2, "", []

    median_h = sorted(x["height"] for x in lines)[len(lines) // 2]
    max_gap = max(18, int(median_h * 1.25))

    anchor_idx = None
    for i, line in enumerate(lines):
        txt = line["text"].lower()
        if "caught" in txt or re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", txt):
            anchor_idx = i
            break

    if anchor_idx is None:
        # fallback: biggest contiguous run of lines
        runs = []
        start = 0
        for i in range(1, len(lines)):
            gap = lines[i]["top"] - lines[i - 1]["bottom"]
            if gap > max_gap:
                runs.append((start, i - 1))
                start = i
        runs.append((start, len(lines) - 1))
        best = max(runs, key=lambda ab: ab[1] - ab[0] + 1)
        keep = lines[best[0]:best[1] + 1]
    else:
        lo = hi = anchor_idx
        while lo > 0:
            gap = lines[lo]["top"] - lines[lo - 1]["bottom"]
            if gap > max_gap:
                break
            lo -= 1
        while hi < len(lines) - 1:
            gap = lines[hi + 1]["top"] - lines[hi]["bottom"]
            if gap > max_gap:
                break
            hi += 1
        keep = lines[lo:hi + 1]

    raw_text = " ".join(line["text"] for line in keep)
    num_lines = max(2, min(5, len(keep)))

    if debug and debug_path:
        dbg = img.convert("RGB")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(dbg)
        keep_tops = {line["top"] for line in keep}
        for line in lines:
            color = "red" if line["top"] in keep_tops else "gray"
            draw.rectangle(
                (line["left"], line["top"], line["left"] + line["width"], line["bottom"]),
                outline=color,
                width=2
            )
            draw.line((0, line["top"], dbg.size[0], line["top"]), fill=color, width=2)
        dbg.save(debug_path)

    return num_lines, raw_text, keep

def waitforbarsstableimage(capturefn, readfn, ui, cfg, timeout=4.0, poll=0.3):
    prevbars = None
    previmg = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll)
        img = capturefn()
        bars = readfn(img, ui, cfg.get("bar_fill_brightness", 160))
        if bars == prevbars and prevbars is not None:
            return previmg
        prevbars = bars
        previmg = img
    return previmg


def tapnextarrow(tap, ui, cfg):
    arrowx = ui.get("nextarrow", {}).get("x", 0.93)
    arrowy = ui.get("nextarrow", {}).get("y", 0.80)
    tap.tap(arrowx, arrowy, base_delay=cfg["timing"].get("afterswipe", 1.2))


def retryreadcp(capturefn, ui, cfg, max_attempts=5):
    img = None
    for attempt in range(1, max_attempts + 1):
        img = capturefn()
        cp_img = getrelativeregion(img, ui["cp_region"])
        cp_text = ocrregion(cp_img)
        cp = parsecp(cp_text)
        if cp and cp > 0:
            if attempt > 1:
                log.info(f"  CP retry succeeded on attempt {attempt}: CP{cp}")
            return cp, img
        log.debug(f"  CP OCR attempt {attempt}/{max_attempts} failed ({cp_text!r}), retrying…")
        time.sleep(0.4)
    log.warning(f"  CP OCR failed after {max_attempts} attempts — flagging for review")
    return 0, img


def reloadcalibration(cfg):
    try:
        with open("calibration.json") as f:
            fresh = json.load(f)
        if "ui" in fresh: cfg["ui"] = fresh["ui"]
        if "barfillbrightness" in fresh: cfg["barfillbrightness"] = fresh["barfillbrightness"]
        if "timing" in fresh: cfg["timing"] = fresh["timing"]
    except Exception as e:
        log.warning(f"calibration reload failed (using current values): {e}")


# ── Pass 1: Catalog ───────────────────────────────────────────────────────────

def pass1_catalog(args, cfg, conn, tap, capture_window, readappraisalbars, compute_ivs):
    ui = cfg["ui"]
    session_ids = []
    visit_num = 0
    errors = 0

    log.info("── Pass 1: Cataloging ──────────────────────────────────────────")
    log.info("Set the in-game search to 'age0', navigate to storage, then wait.")
    for i in range(3, 0, -1):
        log.info(f"Starting in {i}s…")
        time.sleep(1)

    if not args.dry_run:
        slot = ui["pokemon_slots"][-1] if args.mode == "newcatch" else ui["pokemon_slots"][0]
        log.info(f"Tapping {'last' if args.mode == 'newcatch' else 'first'} slot")
        tap.tap(slot["x"], slot["y"], base_delay=cfg["timing"]["after_tap"])

    reloadcalibration(cfg)
    ui = cfg["ui"]

    # Open appraisal
    tap.tap(ui["menu_button"]["x"], ui["menu_button"]["y"],
            base_delay=cfg["timing"]["after_tap"])
    tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
            base_delay=cfg["timing"]["after_appraise"])
    # Dismiss trainer size commentary
    tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
            base_delay=cfg["timing"]["after_appraise"])

    try:
        while True:
            if args.limit and visit_num >= args.limit:
                log.info(f"Reached limit of {args.limit}.")
                break

            reloadcalibration(cfg)
            ui = cfg["ui"]

            time.sleep(1.2)

            # ── DETERMINE LAYOUT FROM TEXT LINES ──────────────────────────────
            img_initial = capture_window(cfg["mirror_region"])
            raw_crop = getrelativeregion(img_initial, ui["name_region"])

            num_lines, raw_text, kept_lines = detect_description_lines(
                raw_crop,
                debug=args.debug,
                debug_path=f"screenshots/nameregion_lines_{visit_num:03d}.png" if args.debug else None,
            )

            if args.debug:
                os.makedirs("screenshots", exist_ok=True)
                img_initial.save(f"screenshots/appraisal{visit_num:03d}.png")
                raw_crop.save(f"screenshots/nameregion{visit_num:03d}.png")
                log.info(f"  Name region OCR: {raw_text!r}")
                log.info(f"  Detected physical lines: {num_lines}")

            # ── WAIT FOR BARS & READ ──────────────────────────────────────────
            read_fn = readappraisalbarsdebug if args.debug else readappraisalbars

            img = waitforbarsstableimage(
                lambda: capture_window(cfg["mirror_region"]),
                lambda im, u, b: read_fn(im, u, b, lines=num_lines),
                ui, cfg,
            )

            if img is None:
                log.warning(f"#{visit_num + 1} Could not capture stable image. Skipping.")
                errors += 1
                if not args.dry_run:
                    tapnextarrow(tap, ui, cfg)
                continue

            cp, img = retryreadcp(
                lambda: capture_window(cfg["mirror_region"]),
                ui, cfg, max_attempts=5,
            )

            hp_img = getrelativeregion(img, ui["hp_region"])
            try:
                hp = int(str(parsehp(ocrregion(hp_img))).replace(",", "").strip())
            except (ValueError, TypeError):
                hp = 0

            name = resolvespeciesname(img, ui, cp)
            caught_date = parse_caught_date(raw_text)
            if not name or name == "Unknown":
                log.warning(f"#{visit_num + 1} Species ID failed (cp={cp})")
                name = "Unknown"

            # Dynamic bar strip extraction for legacy parseivbars
            offset = (num_lines - 2) * 0.027
            dynamic_bar_region = {
                "x1": ui["bar_region"]["x1"],
                "y1": ui["bar_region"]["y1"] - offset,
                "x2": ui["bar_region"]["x2"],
                "y2": ui["bar_region"]["y2"] - offset,
            }
            bar_strip = getrelativeregion(img, dynamic_bar_region)

            if args.debug:
                bar_strip.save(f"screenshots/barstrip{visit_num:03d}.png")

            bars = parseivbars(bar_strip, args.debug)

            if not bars:
                log.warning(f"#{visit_num + 1} Bar read failed for {name}. Skipping.")
                errors += 1
                if not args.dry_run:
                    tapnextarrow(tap, ui, cfg)
                continue

            atk_iv, def_iv, sta_iv = (
                (bars["atk"], bars["def"], bars["sta"])
                if isinstance(bars, dict)
                else (bars[0], bars[1], bars[2])
            )

            visit_num += 1

            if find_duplicate(conn, name, cp, atk_iv, def_iv, sta_iv, caught_date):
                log.info(f"#{visit_num} {name} CP{cp} — already in DB, skipping.")
                if not args.dry_run:
                    tap.swipe_left()
                continue

            iv_data = compute_ivs(name, cp, hp, atk_iv, def_iv, sta_iv, None)
            iv_data["caught_date"] = caught_date
            iv_data["needs_review"] = (cp == 0)

            pvp_all = all_league_rankings_with_evos(name, atk_iv, def_iv, sta_iv)
            pvp = pvp_all[name]
            pvp_evos = {k: v for k, v in pvp_all.items() if k != name}
            iv_data["pvp"] = pvp

            if not args.dry_run:
                row_id = insert_pokemon(conn, iv_data)
                if pvp_evos:
                    insert_evo_rankings(conn, row_id, pvp_evos)
                session_ids.append(row_id)

            gl = pvp.get("great", {})
            ul = pvp.get("ultra", {})
            iv_pct = iv_data.get("iv_pct", 0) or 0
            log.info(
                f"#{visit_num} {name:<15s} CP{str(cp):>4s} "
                f"IVs={atk_iv}/{def_iv}/{sta_iv} {iv_pct:.1f}% {iv_data.get('iv_stars', '?'):<6s} "
                f"GL={gl.get('rank') or '-':<6} UL={ul.get('rank') or '-'}"
            )

            if not args.dry_run:
                tap.swipe_left()
                tap.anti_bot_break()

            if args.mode == "newcatch":
                break

    except KeyboardInterrupt:
        log.info("Pass 1 interrupted by user.")

    log.info(
        f"Pass 1 complete: {visit_num} visited, {errors} errors, "
        f"{len(session_ids)} new rows inserted."
    )
    return session_ids, errors


# ── Displacement check ────────────────────────────────────────────────────────

def report_displaced(conn):
    displaced = flag_displaced(conn)
    if displaced:
        log.warning(f"\n⚠️  {len(displaced)} Pokémon displaced this session:")
        for p in displaced:
            search = f"{p['name'].lower()}&cp{p['cp']}"
            log.warning(
                f"  DISPLACED  {search:<28}  "
                f"{p['iv_atk']}/{p['iv_def']}/{p['iv_sta']}  "
                f"GL #{p['gl_rank']}  UL #{p['ul_rank']}"
            )
    else:
        log.info("No Pokémon displaced this session.")
    return displaced


# ── Pass 2: Tag ───────────────────────────────────────────────────────────────

def pass2_tag(args, cfg, conn, tap):
    ui = cfg["ui"]

    new_rows = conn.execute("""
        SELECT * FROM pokemon
        WHERE tag IS NULL
        ORDER BY id
    """).fetchall()
    new_rows = [dict(r) for r in new_rows]

    if not new_rows:
        log.info("Pass 2: nothing new to tag.")
        return

    log.info(f"── Pass 2: Tagging {len(new_rows)} Pokémon ─────────────────────────")
    log.info("Navigate back to the START of the age0-filtered storage list.")
    tap.tap(ui["back_button"]["x"], ui["back_button"]["y"],
            base_delay=cfg["timing"]["after_tap"])
    tap.tap(ui["back_button"]["x"], ui["back_button"]["y"],
            base_delay=cfg["timing"]["after_tap"])
    for i in range(5, 0, -1):
        log.info(f"Starting Pass 2 in {i}s…")
        time.sleep(1)

    if not args.dry_run:
        slot = ui["pokemon_slots"][0]
        tap.tap(slot["x"], slot["y"], base_delay=cfg["timing"]["after_tap"])

    tagged = 0
    try:
        for idx, row in enumerate(new_rows):
            name = row["name"]
            cp = row["cp"]
            iv_pct = row["iv_pct"] or 0

            pvp = {
                "great": {"rank": row["gl_rank"], "percentile": row["gl_percentile"]},
                "ultra": {"rank": row["ul_rank"], "percentile": row["ul_percentile"]},
            }
            evo_rankings = get_evo_rankings(conn, row["id"])

            decision = evaluate_catch(
                conn, name, cp,
                row["iv_atk"], row["iv_def"], row["iv_sta"],
                iv_pct, pvp, evo_rankings,
                current_id=row["id"],
            )
            action = decision["action"]

            log.info(
                f"  [{idx + 1}/{len(new_rows)}] {name:<15s} CP{cp:>4}  "
                f"{row['iv_atk']}/{row['iv_def']}/{row['iv_sta']}  → {action}"
                + (f"  ({', '.join(decision['reasons'])})" if decision["reasons"] else "")
            )

            if not args.dry_run:
                apply_ingame_tag(tap, ui, cfg["mirror_region"], action)
                conn.execute(
                    "UPDATE pokemon SET tag = ? WHERE id = ?",
                    (action, row["id"])
                )
                conn.commit()
                tap.swipe_left()
                tap.anti_bot_break()
                tagged += 1

    except KeyboardInterrupt:
        log.info("Pass 2 interrupted by user.")

    log.info(f"Pass 2 complete: {tagged} Pokémon tagged.")


# ── Entry point ───────────────────────────────────────────────────────────────

def runbot(args):
    from config import loadconfig
    from screen_capture import capture_window, get_mirror_window_bounds
    from tap_controller import TapController
    from iv_calculator import compute_ivs

    cfg = loadconfig()
    conn = get_db()
    tap = TapController(cfg)

    try:
        bounds = get_mirror_window_bounds()
        cfg["mirror_region"] = bounds
        tap.mirror = bounds
        log.info(f"iPhone Mirroring window bounds: {bounds}")
    except Exception as e:
        log.warning(f"Could not auto-detect window: {e}")

    if not tags_are_calibrated(cfg["ui"]):
        log.warning("Tag positions not calibrated — Pokémon will NOT be tagged in-game.")

    starttime = time.time()
    log.info("=" * 50)
    log.info(f"Pokémon GO IV Cataloger — Mode: {args.mode}")
    log.info(f"Limit: {args.limit or 'unlimited'}")
    log.info("=" * 50)

    try:
        session_ids, errors = pass1_catalog(
            args, cfg, conn, tap, capture_window, readappraisalbars, compute_ivs
        )

        if not args.dry_run and session_ids:
            report_displaced(conn)

        if not args.dry_run and tags_are_calibrated(cfg["ui"]):
            pass2_tag(args, cfg, conn, tap)
        elif args.dry_run:
            log.info("Dry-run: skipping Pass 2.")
        else:
            log.info("Tags not calibrated: skipping Pass 2.")

    except Exception as e:
        log.error(f"Unexpected error: {e}")
        traceback.print_exc()
    finally:
        elapsed = (time.time() - starttime) / 60
        stats = get_stats(conn)
        log.info("=" * 50)
        log.info(f"Session: {len(session_ids) if 'session_ids' in dir() else 0} cataloged, "
                 f"{errors if 'errors' in dir() else 0} errors, {elapsed:.1f} min")
        log.info(f"DB totals: {stats}")
        log.info("=" * 50)
        conn.close()


if __name__ == "__main__":
    runbot(parseargs())
