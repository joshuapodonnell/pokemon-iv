# main.py
import argparse
import json
import logging
import os
import sys
import time
import traceback

from ocr_parser import (
    identify_species, parse_cp, parse_hp,
    ocr_region, get_relative_region
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--limit",   type=int, default=0)
    p.add_argument("--debug",   action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def wait_for_bars_stable_image(capture_fn, read_fn, ui, cfg, timeout=4.0, poll=0.3):
    """Capture repeatedly until bar readings stabilize. Returns the stable image."""
    prev_bars = None
    prev_img  = None
    deadline  = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll)
        img  = capture_fn()
        bars = read_fn(img, ui, cfg["bar_fill_brightness"])
        if bars == prev_bars and prev_bars is not None:
            return prev_img
        prev_bars = bars
        prev_img  = img
    return prev_img  # best effort on timeout


def _tap_next_arrow(tap, ui, cfg):
    """Tap the right arrow on the appraisal screen to advance to the next Pokémon."""
    arrow_x = ui.get("next_arrow", {}).get("x", 0.93)
    arrow_y = ui.get("next_arrow", {}).get("y", 0.50)
    tap.tap(arrow_x, arrow_y, base_delay=cfg["timing"].get("after_swipe", 1.2))


def run_bot(args):
    from config import load_config
    from screen_capture import capture_window, get_mirror_window_bounds
    from tap_controller import TapController
    from ocr_parser import read_appraisal_bars, read_appraisal_bars_debug
    from iv_calculator import compute_ivs
    from pvp_rankings import all_league_rankings
    from database import get_db, insert_pokemon, get_stats

    cfg  = load_config()
    conn = get_db()
    tap  = TapController(cfg)
    ui   = cfg["ui"]

    try:
        bounds = get_mirror_window_bounds()
        cfg["mirror_region"] = bounds
        tap.mirror = bounds
        log.info(f"iPhone Mirroring window: {bounds}")
    except Exception as e:
        log.warning(f"Could not auto-detect window: {e}")

    count      = 0
    errors     = 0
    start_time = time.time()

    log.info("=" * 50)
    log.info("  Pokémon GO IV Cataloger — Starting")
    log.info(f"  Limit: {args.limit or 'unlimited'}")
    log.info("=" * 50)
    log.info("Navigate to the Pokémon storage list now.")

    for i in range(3, 0, -1):
        log.info(f"Starting in {i}s...")
        time.sleep(1)

    # ── STEP 1: Open first Pokémon ────────────────────────────────────────────
    if not args.dry_run:
        slot = ui["pokemon_slots"][0]
        log.info(f"Tapping first Pokémon at ({slot['x']:.3f}, {slot['y']:.3f})")
        tap.tap(slot["x"], slot["y"], base_delay=cfg["timing"]["after_tap"])

    # ── STEP 2: Tap hamburger menu ────────────────────────────────────────────
    if not args.dry_run:
        log.info(f"Tapping menu button at ({ui['menu_button']['x']:.3f}, {ui['menu_button']['y']:.3f})")
        tap.tap(ui["menu_button"]["x"], ui["menu_button"]["y"],
                base_delay=cfg["timing"]["after_tap"])

    # ── STEP 3: Tap APPRAISE ──────────────────────────────────────────────────
    if not args.dry_run:
        log.info(f"Tapping APPRAISE at ({ui['appraise_button']['x']:.3f}, {ui['appraise_button']['y']:.3f})")
        tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                base_delay=cfg["timing"]["after_appraise"])

    # ── STEP 4: Dismiss trainer size commentary ───────────────────────────────
    if not args.dry_run:
        log.info("Dismissing trainer size text...")
        tap.tap(0.50, 0.50, base_delay=cfg["timing"]["after_appraise"])

    log.info("In appraisal mode — starting main loop.")

    # ── MAIN LOOP ─────────────────────────────────────────────────────────────
    try:
        while True:
            if args.limit and count >= args.limit:
                log.info(f"Reached limit of {args.limit}. Stopping.")
                break

            # Reload only mutable calibration keys — preserve mirror_region
            with open("calibration.json") as f:
                fresh = json.load(f)
            cfg["ui"]                  = fresh["ui"]
            cfg["bar_fill_brightness"] = fresh["bar_fill_brightness"]
            cfg["timing"]              = fresh["timing"]
            ui = cfg["ui"]

            # Wait for bar animation then capture stable image
            log.info("Waiting for bar animation to settle...")
            time.sleep(1.2)
            img = wait_for_bars_stable_image(
                lambda: capture_window(cfg["mirror_region"]),
                read_appraisal_bars,
                ui, cfg
            )

            if img is None:
                log.warning(f"  [{count+1}] Could not capture stable image. Skipping.")
                errors += 1
                if not args.dry_run:
                    _tap_next_arrow(tap, ui, cfg)
                continue

            if args.debug:
                os.makedirs("screenshots", exist_ok=True)
                img.save(f"screenshots/appraisal_{count+1:03d}.png")

            # ── OCR CP and HP first (needed by identify_species) ──────────────
            cp_img = get_relative_region(img, ui["cp_region"])
            hp_img = get_relative_region(img, ui["hp_region"])

            try:
                cp = int(str(parse_cp(ocr_region(cp_img))).replace(',', '').strip())
            except (ValueError, TypeError):
                cp = 0

            try:
                hp = int(str(parse_hp(ocr_region(hp_img))).replace(',', '').strip())
            except (ValueError, TypeError):
                hp = 0

            # ── Species identification (nickname-proof) ───────────────────────
            type_text   = ocr_region(get_relative_region(img, ui["type_region"]))
            weight_text = ocr_region(get_relative_region(img, ui["weight_region"]))
            height_text = ocr_region(get_relative_region(img, ui["height_region"]))
            name        = identify_species(type_text, weight_text, height_text, cp)

            if not name or name == "Unknown":
                log.warning(
                    f"  [{count+1}] Species ID failed (cp={cp}) — "
                    f"types={type_text!r} weight={weight_text!r} height={height_text!r}"
                )
                name = "Unknown"

            if not cp:
                log.warning(f"  [{count+1}] CP OCR failed (name={name}) — using 0")

            # ── Read IV bars ──────────────────────────────────────────────────
            if args.debug:
                bars = read_appraisal_bars_debug(img, ui, cfg["bar_fill_brightness"])
            else:
                bars = read_appraisal_bars(img, ui, cfg["bar_fill_brightness"])

            if not bars:
                log.warning(f"  [{count+1}] Bar read failed for {name}. Skipping.")
                errors += 1
                if not args.dry_run:
                    _tap_next_arrow(tap, ui, cfg)
                continue

            # Normalize: handle both list [atk, def, sta] and dict {"atk":..., ...}
            if isinstance(bars, dict):
                atk_iv, def_iv, sta_iv = bars["atk"], bars["def"], bars["sta"]
            else:
                atk_iv, def_iv, sta_iv = bars[0], bars[1], bars[2]

            # ── Compute IVs and PvP rankings ──────────────────────────────────
            iv_data     = compute_ivs(name, cp, hp, atk_iv, def_iv, sta_iv, None)
            pvp         = all_league_rankings(name, atk_iv, def_iv, sta_iv)
            iv_data["pvp"] = pvp

            if not args.dry_run:
                insert_pokemon(conn, iv_data)

            gl     = pvp.get("great", {})
            ul     = pvp.get("ultra", {})
            iv_pct = iv_data.get("iv_pct", 0) or 0
            iv_str = iv_data.get("iv_stars", "?")
            bars_s = f"{atk_iv}/{def_iv}/{sta_iv}"

            gl_rank = gl.get("rank")
            ul_rank = ul.get("rank")
            gl_str  = f"#{gl_rank}" if gl_rank is not None else "—"
            ul_str  = f"#{ul_rank}" if ul_rank is not None else "—"

            log.info(
                f"  [{count+1}] {str(name):<15s} CP:{str(cp):>4s} "
                f"IVs:{bars_s} ({iv_pct:.1f}%) {str(iv_str):<6s} | "
                f"GL:{gl_str:>6s} UL:{ul_str:>6s}"
            )

            count += 1

            # Advance to next Pokémon
            if not args.dry_run:
                _tap_next_arrow(tap, ui, cfg)

            tap.anti_bot_break()

    except KeyboardInterrupt:
        log.info("\n⏸  Stopped by user.")
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        traceback.print_exc()
    finally:
        elapsed = (time.time() - start_time) / 60
        stats   = get_stats(conn)
        log.info("=" * 50)
        log.info(f"Session: {count} cataloged, {errors} errors, {elapsed:.1f} min")
        log.info(f"DB totals: {stats}")
        log.info("=" * 50)
        conn.close()


if __name__ == "__main__":
    run_bot(parse_args())