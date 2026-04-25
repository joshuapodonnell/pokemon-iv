#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import time
import traceback
import pytesseract

from ocr_parser import (
    resolvespeciesname,
    parsecp, parsehp,
    ocrregion, getrelativeregion, parseivbars, parse_caught_date,
)
from pvp_rankings import all_league_rankings_with_evos
from database import insert_evo_rankings, find_duplicate
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
    p.add_argument("--limit",  type=int, default=0)
    p.add_argument("--debug",  action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--mode", choices=["catalog", "newcatch"], default="catalog",
                   help="catalog: scan whole box. newcatch: appraise most recent catch only.")
    return p.parse_args()


def waitforbarsstableimage(capturefn, readfn, ui, cfg, timeout=4.0, poll=0.3):
    prevbars = None
    previmg  = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll)
        img  = capturefn()
        bars = readfn(img, ui, cfg.get("bar_fill_brightness", 160))
        if bars == prevbars and prevbars is not None:
            return previmg
        prevbars = bars
        previmg  = img
    return previmg


def tapnextarrow(tap, ui, cfg):
    arrowx = ui.get("nextarrow", {}).get("x", 0.93)
    arrowy = ui.get("nextarrow", {}).get("y", 0.80)
    tap.tap(arrowx, arrowy, base_delay=cfg["timing"].get("afterswipe", 1.2))


def retryreadcp(capturefn, ui, cfg, max_attempts=5):
    for attempt in range(1, max_attempts + 1):
        img = capturefn()
        cp_img  = getrelativeregion(img, ui["cp_region"])
        cp_text = ocrregion(cp_img)
        cp = parsecp(cp_text)
        if cp and cp > 0:
            if attempt > 1:
                log.info(f"  CP retry succeeded on attempt {attempt}: CP{cp}")
            return cp, img
        log.debug(f"  CP OCR attempt {attempt}/{max_attempts} failed (got {cp_text!r}), retrying…")
        time.sleep(0.4)
    log.warning(f"  CP OCR failed after {max_attempts} attempts — flagging for manual review")
    return 0, img


def reloadcalibration(cfg):
    try:
        with open("calibration.json") as f:
            fresh = json.load(f)
        if "ui" in fresh:
            cfg["ui"] = fresh["ui"]
        if "barfillbrightness" in fresh:
            cfg["barfillbrightness"] = fresh["barfillbrightness"]
        if "timing" in fresh:
            cfg["timing"] = fresh["timing"]
    except Exception as e:
        log.warning(f"calibration reload failed (using current values): {e}")


def already_cataloged(conn, cp, iv_atk, iv_def, iv_sta, name):
    return conn.execute("""
        SELECT 1 FROM pokemon
        WHERE name=? AND cp=? AND iv_atk=? AND iv_def=? AND iv_sta=?
        LIMIT 1
    """, (name, cp, iv_atk, iv_def, iv_sta)).fetchone() is not None


def runbot(args):
    from config import loadconfig
    from screen_capture import capture_window, get_mirror_window_bounds
    from tap_controller import TapController
    from ocr_parser import readappraisalbars
    from iv_calculator import compute_ivs
    from database import get_db, insert_pokemon, get_stats

    cfg  = loadconfig()
    conn = get_db()
    tap  = TapController(cfg)
    ui   = cfg["ui"]

    try:
        bounds = get_mirror_window_bounds()
        cfg["mirror_region"] = bounds
        tap.mirror = bounds
        log.info(f"iPhone Mirroring window bounds: {bounds}")
    except Exception as e:
        log.warning(f"Could not auto-detect window: {e}")

    if not tags_are_calibrated(ui):
        log.warning("Tag positions not calibrated — Pokémon will NOT be tagged in-game.")

    visit_num = 0
    count     = 0
    errors    = 0
    starttime = time.time()

    log.info("=" * 50)
    log.info(f"Pokémon GO IV Cataloger — Mode: {args.mode}")
    log.info(f"Limit: {args.limit or 'unlimited'}")
    log.info("=" * 50)
    log.info("Navigate to the Pokémon storage list now.")
    for i in range(3, 0, -1):
        log.info(f"Starting in {i}s…")
        time.sleep(1)

    # ── Open first Pokémon ────────────────────────────────────────────────────
    if not args.dry_run:
        # newcatch: most recent = last slot; catalog: start from first slot
        slot = ui["pokemon_slots"][-1] if args.mode == "newcatch" else ui["pokemon_slots"][0]
        log.info(f"Tapping {'last' if args.mode == 'newcatch' else 'first'} "
                 f"Pokémon at {slot['x']:.3f}, {slot['y']:.3f}")
        tap.tap(slot["x"], slot["y"], base_delay=cfg["timing"]["after_tap"])

        # tap.tap(ui["menu_button"]["x"], ui["menu_button"]["y"],
        #         base_delay=cfg["timing"]["after_tap"])
        # tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
        #         base_delay=cfg["timing"]["after_appraise"])
        # # Dismiss trainer size commentary
        # tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
        #         base_delay=cfg["timing"]["after_appraise"])

    log.info("In appraisal mode — starting main loop.")

    try:
        while True:
            if args.limit and visit_num >= args.limit:
                log.info(f"Reached limit of {args.limit}. Stopping.")
                break

            reloadcalibration(cfg)
            ui = cfg["ui"]
            tap.tap(ui["menu_button"]["x"], ui["menu_button"]["y"],
                    base_delay=cfg["timing"]["after_tap"])
            tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                    base_delay=cfg["timing"]["after_appraise"])
            # Dismiss trainer size commentary
            tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                    base_delay=cfg["timing"]["after_appraise"])

            log.info("Waiting for bar animation to settle…")
            time.sleep(1.2)
            img = waitforbarsstableimage(
                lambda: capture_window(cfg["mirror_region"]),
                readappraisalbars, ui, cfg,
            )

            if img is None:
                log.warning(f"#{visit_num} Could not capture stable image. Skipping.")
                errors += 1
                if not args.dry_run and args.mode == "catalog":
                    tapnextarrow(tap, ui, cfg)
                continue

            raw_crop = getrelativeregion(img, ui["name_region"])
            raw_text = pytesseract.image_to_string(
                raw_crop.convert("L"), config="--psm 6 --oem 3"
            ).strip().replace("\n", " ")

            if args.debug:
                os.makedirs("screenshots", exist_ok=True)
                img.save(f"screenshots/appraisal{count:03d}.png")

                raw_crop.save(f"screenshots/nameregion{count:03d}.png")

                log.info(f"  Name region raw OCR: {raw_text!r}")

            # ── OCR CP ────────────────────────────────────────────────────────
            cp, img = retryreadcp(
                lambda: capture_window(cfg["mirror_region"]),
                ui, cfg, max_attempts=5,
            )

            # ── OCR HP ────────────────────────────────────────────────────────
            hp_img = getrelativeregion(img, ui["hp_region"])   # FIX: use getrelativeregion
            try:
                hp = int(str(parsehp(ocrregion(hp_img))).replace(",", "").strip())
            except (ValueError, TypeError):
                hp = 0

            # ── Species name ──────────────────────────────────────────────────
            name = resolvespeciesname(img, ui, cp)
            caught_date = parse_caught_date(raw_text)  # new
            if not name or name == "Unknown":
                log.warning(f"#{visit_num} Species ID failed (cp={cp}) — OCR returned no match")
                name = "Unknown"
            if not cp:
                log.warning(f"#{visit_num} CP OCR failed for {name}, using 0")


            # ── IV bars ───────────────────────────────────────────────────────
            bar_strip = getrelativeregion(img, ui["bar_region"])
            if args.debug:
                bar_strip.save(f"screenshots/barstrip{count:03d}.png")
            bars = parseivbars(bar_strip, args.debug)

            if not bars:
                log.warning(f"#{visit_num} Bar read failed for {name}. Skipping.")
                errors += 1
                if not args.dry_run and args.mode == "catalog":
                    tapnextarrow(tap, ui, cfg)
                continue

            atk_iv, def_iv, sta_iv = (
                (bars["atk"], bars["def"], bars["sta"])
                if isinstance(bars, dict)
                else (bars[0], bars[1], bars[2])
            )

            # ── Duplicate check ───────────────────────────────────────────────
            visit_num += 1
            if find_duplicate(conn, name, cp, atk_iv, def_iv, sta_iv, caught_date):
                log.info(f"#{visit_num} {name} CP{cp} caught {caught_date} — already in DB, skipping.")
                if not args.dry_run and args.mode == "catalog":
                    tap.swipe_left()
                continue

            # ── Compute IVs + PvP ─────────────────────────────────────────────
            iv_data  = compute_ivs(name, cp, hp, atk_iv, def_iv, sta_iv, None)
            iv_data["caught_date"] = caught_date
            iv_data["needs_review"] = (cp == 0)

            pvp_all  = all_league_rankings_with_evos(name, atk_iv, def_iv, sta_iv)
            pvp      = pvp_all[name]
            pvp_evos = {k: v for k, v in pvp_all.items() if k != name}
            iv_data["pvp"] = pvp

            # ── Database insert ───────────────────────────────────────────────
            if not args.dry_run:
                row_id = insert_pokemon(conn, iv_data)
                if pvp_evos:
                    insert_evo_rankings(conn, row_id, pvp_evos)

            # ── Log line ──────────────────────────────────────────────────────
            gl      = pvp.get("great", {})
            ul      = pvp.get("ultra", {})
            iv_pct  = iv_data.get("iv_pct", 0) or 0
            iv_str  = iv_data.get("iv_stars", "?")
            gl_rank = gl.get("rank")
            ul_rank = ul.get("rank")
            review_flag = " ⚠ NEEDS REVIEW" if cp == 0 else ""
            log.info(
                f"#{visit_num} {str(name):<15s} CP{str(cp):>4s} "
                f"IVs={atk_iv}/{def_iv}/{sta_iv} {iv_pct:.1f}% {str(iv_str):<6s} "
                f"GL={gl_rank or '-':<6} UL={ul_rank or '-':<6}{review_flag}"
            )
            count += 1

            # ── Evaluate + tag ────────────────────────────────────────────────
            decision = evaluate_catch(conn, name, cp, atk_iv, def_iv, sta_iv,
                                      iv_pct, pvp, pvp_evos)
            apply_ingame_tag(tap, ui, cfg["mirror_region"], decision["action"]) # FIX: was 'window'

            # ── Advance ───────────────────────────────────────────────────────
            if not args.dry_run:
                if args.mode == "catalog":
                    # Swipe right on detail screen to go to next Pokémon
                    tap.swipe_left()
                else:
                    break
                tap.anti_bot_break()

    except KeyboardInterrupt:
        log.info("Stopped by user.")
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        traceback.print_exc()
    finally:
        elapsed = (time.time() - starttime) / 60
        stats   = get_stats(conn)
        log.info("=" * 50)
        log.info(f"Session: {count} cataloged, {errors} errors, {elapsed:.1f} min")
        log.info(f"DB totals: {stats}")
        log.info("=" * 50)
        conn.close()


if __name__ == "__main__":
    runbot(parseargs())