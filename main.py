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
    resolvespeciesname,  # NEW — combines type-based ID + name OCR fallback
    parsecp, parsehp,
    ocrregion, getrelativeregion, parseweight, parseheight, parseivbars,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def parseargs():
    p = argparse.ArgumentParser()
    p.add_argument("--limit",   type=int, default=0)
    p.add_argument("--debug",   action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def waitforbarsstableimage(capturefn, readfn, ui, cfg, timeout=4.0, poll=0.3):
    """Capture repeatedly until bar readings stabilise. Returns the stable image."""
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
    return previmg  # best effort on timeout


def tapnextarrow(tap, ui, cfg):
    """Tap the right arrow on the appraisal screen to advance to the next Pokémon."""
    # BUG FIX: use correct default y=0.80 (matches calibration.json default)
    arrowx = ui.get("nextarrow", {}).get("x", 0.93)
    arrowy = ui.get("nextarrow", {}).get("y", 0.80)
    tap.tap(arrowx, arrowy, base_delay=cfg["timing"].get("afterswipe", 1.2))

def retryreadcp(capturefn, ui, cfg, max_attempts: int = 5):
    """
    Retry CP OCR up to max_attempts times, re-capturing the screen each time.
    Returns (cp, img) — cp=0 and img=last_capture if all attempts fail.
    Waits a short settle delay between retries to let the UI stabilise.
    """
    from ocr_parser import getrelativeregion, ocrregion, parsecp

    for attempt in range(1, max_attempts + 1):
        img = capturefn()
        cp_img = getrelativeregion(img, ui["cp_region"])
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
    """Hot-reload mutable calibration keys from disk, preserving mirrorregion."""
    # BUG FIX: wrapped in try/except so a malformed calibration.json mid-run
    # never crashes the bot; logs a warning and continues with the current values.
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


def runbot(args):
    from config import loadconfig
    from screen_capture import capture_window, get_mirror_window_bounds, get_relative_region
    from tap_controller import TapController
    from ocr_parser import readappraisalbars, readappraisalbarsdebug
    from iv_calculator import compute_ivs
    from pvp_rankings import all_league_rankings
    from database import get_db, insert_pokemon, get_stats

    cfg  = loadconfig()
    conn = get_db()
    tap  = TapController(cfg)

    ui = cfg["ui"]
    try:
        bounds = get_mirror_window_bounds()
        cfg["mirrorregion"] = bounds
        tap.mirror = bounds
        log.info(f"iPhone Mirroring window bounds: {bounds}")
    except Exception as e:
        log.warning(f"Could not auto-detect window: {e}")

    count  = 0
    errors = 0
    starttime = time.time()

    log.info("=" * 50)
    log.info("Pokémon GO IV Cataloger — Starting")
    log.info(f"Limit: {args.limit or 'unlimited'}")
    log.info("=" * 50)
    log.info("Navigate to the Pokémon storage list now.")
    for i in range(3, 0, -1):
        log.info(f"Starting in {i}s…")
        time.sleep(1)

    # STEP 1: Open first Pokémon
    if not args.dry_run:
        slot = ui["pokemon_slots"][0]
        log.info(f"Tapping first Pokémon at {slot['x']:.3f}, {slot['y']:.3f}")
        tap.tap(slot["x"], slot["y"], base_delay=cfg["timing"]["after_tap"])

    # STEP 2: Tap hamburger menu
    if not args.dry_run:
        log.info(f"Tapping menu button at {ui['menu_button']['x']:.3f}, {ui['menu_button']['y']:.3f}")
        tap.tap(ui["menu_button"]["x"], ui["menu_button"]["y"],
                base_delay=cfg["timing"]["after_tap"])

    # STEP 3: Tap APPRAISE
    if not args.dry_run:
        log.info(f"Tapping APPRAISE at {ui['appraise_button']['x']:.3f}, {ui['appraise_button']['y']:.3f}")
        tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                base_delay=cfg["timing"]["after_appraise"])

    # STEP 4: Dismiss trainer size commentary
    if not args.dry_run:
        log.info("Dismissing trainer size text…")
        #tap.tap(0.50, 0.50, base_delay=cfg["timing"]["after_appraise"])
        tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                base_delay=cfg["timing"]["after_appraise"])

    log.info("In appraisal mode — starting main loop.")

    try:
        while True:
            if args.limit and count >= args.limit:
                log.info(f"Reached limit of {args.limit}. Stopping.")
                break

            # Hot-reload calibration (allows live adjustments without restarting)
            reloadcalibration(cfg)
            ui = cfg["ui"]

            # Wait for bar animation then capture stable image
            log.info("Waiting for bar animation to settle…")
            time.sleep(1.2)
            img = waitforbarsstableimage(
                lambda: capture_window(cfg["mirror_region"]),
                readappraisalbars, ui, cfg,
            )
            if args.debug:
                raw_crop = getrelativeregion(img, ui["name_region"])
                raw_crop.save(f"screenshots/nameregion{count:03d}.png")
                raw_text = pytesseract.image_to_string(
                    raw_crop.convert("L"), config="--psm 6 --oem 3"
                ).strip().replace("\n", " ")
                log.info(f"  Name region raw OCR: {raw_text!r}")
            if img is None:
                log.warning(f"#{count+1} Could not capture stable image. Skipping.")
                errors += 1
                if not args.dry_run:
                    tapnextarrow(tap, ui, cfg)
                continue

            if args.debug:
                os.makedirs("screenshots", exist_ok=True)
                img.save(f"screenshots/appraisal{count:03d}.png")

            # OCR CP and HP
            # OCR CP with retry loop
            cp, img = retryreadcp(
                lambda: capture_window(cfg["mirror_region"]),
                ui, cfg,
                max_attempts=5,
            )

            # OCR HP (single attempt — HP failures are less impactful)
            hp_img = get_relative_region(img, ui["hp_region"])
            try:
                hp = int(str(parsehp(ocrregion(hp_img))).replace(",", "").strip())
            except (ValueError, TypeError):
                hp = 0


            name = resolvespeciesname(img, ui, cp)
            if not name or name == "Unknown":
                log.warning(
                    f"#{count+1} Species ID failed (cp={cp} )"
                    #f"weight={weight_text!r} height={height_text!r})"
                )
                name = "Unknown"
            if not cp:
                log.warning(f"#{count+1} CP OCR failed for {name}, using 0")

            # Read IV bars
            # if args.debug:
            #     bars = readappraisalbarsdebug(img, ui, cfg.get("bar_fill_brightness", 160))
            # else:
            #     bars = readappraisalbars(img, ui, cfg.get("bar_fill_brightness", 160))
            bar_strip = getrelativeregion(img, ui["bar_region"])
            if args.debug:
                bar_strip.save(f"screenshots/barstrip{count:03d}.png")
            bars = parseivbars(bar_strip, args.debug)



            if not bars:
                log.warning(f"#{count+1} Bar read failed for {name}. Skipping.")
                errors += 1
                if not args.dry_run:
                    tapnextarrow(tap, ui, cfg)
                continue

            # Normalise — handle both list (atk, def, sta) and dict {"atk":…}
            if isinstance(bars, dict):
                atk_iv, def_iv, sta_iv = bars["atk"], bars["def"], bars["sta"]
            else:
                atk_iv, def_iv, sta_iv = bars[0], bars[1], bars[2]

            # Compute IVs and PvP rankings
            iv_data = compute_ivs(name, cp, hp, atk_iv, def_iv, sta_iv, None)
            iv_data["needs_review"] = (cp == 0)
            pvp    = all_league_rankings(name, atk_iv, def_iv, sta_iv)
            iv_data["pvp"] = pvp

            if not args.dry_run:
                insert_pokemon(conn, iv_data)

            gl    = pvp.get("great", {})
            ul    = pvp.get("ultra", {})
            iv_pct = iv_data.get("iv_pct", 0) or 0
            iv_str = iv_data.get("iv_stars", "?")
            barss = f"{atk_iv}/{def_iv}/{sta_iv}"
            gl_rank = gl.get("rank")
            ul_rank = ul.get("rank")
            gl_str  = f"{gl_rank}" if gl_rank is not None else "-"
            ul_str  = f"{ul_rank}" if ul_rank is not None else "-"

            review_flag = " ⚠ NEEDS REVIEW" if cp == 0 else ""
            log.info(
                f"#{count + 1} {str(name):<15s} CP{str(cp):>4s} "
                f"IVs={barss} {iv_pct:.1f}% {str(iv_str):<6s} "
                f"GL={gl_str:<6s} UL={ul_str:<6s}{review_flag}"
            )
            count += 1

            if not args.dry_run:
                tapnextarrow(tap, ui, cfg)
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
