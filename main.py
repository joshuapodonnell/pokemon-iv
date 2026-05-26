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
import vision_agent

from ocr_parser import (
    resolvespeciesname,
    parsecp, parsehp,
    ocrregion, getrelativeregion, parseivbars, parse_caught_date,
    readappraisalbars, readappraisalbarsdebug
)
from pvp_rankings import all_league_rankings_with_evos
from database import get_db, get_stats, insert_pokemon, insert_evo_rankings, find_duplicate, get_evo_rankings
from evaluator import evaluate_catch, find_displaced, flag_displaced, get_best_in_db
from tagger import apply_ingame_tag, tags_are_calibrated

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def parse_args():
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


def wait_for_bars_stable_image(capture_fn, read_fn, ui, cfg, timeout=4.0, poll=0.3):
    prev_bars = None
    prev_img = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll)
        img = capture_fn()
        bars = read_fn(img, ui, cfg.get("bar_fill_brightness", 160))
        if bars == prev_bars and prev_bars is not None:
            return prev_img
        prev_bars = bars
        prev_img = img
    return prev_img


def tap_next_arrow(tap, ui, cfg):
    arrow_x = ui.get("next_arrow", {}).get("x", 0.93)
    arrow_y = ui.get("next_arrow", {}).get("y", 0.80)
    tap.tap(arrow_x, arrow_y, base_delay=cfg["timing"].get("after_swipe", 1.2))


def retry_read_cp(capture_fn, ui, cfg, max_attempts=5):
    img = None
    for attempt in range(1, max_attempts + 1):
        img = capture_fn()
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


def reload_calibration(cfg):
    try:
        with open("calibration.json") as f:
            fresh = json.load(f)
        if "ui" in fresh: cfg["ui"] = fresh["ui"]
        if "bar_fill_brightness" in fresh: cfg["bar_fill_brightness"] = fresh["bar_fill_brightness"]
        if "timing" in fresh: cfg["timing"] = fresh["timing"]
    except Exception as e:
        log.warning(f"calibration reload failed (using current values): {e}")


def _is_valid_base_parse(cp, hp, typetext, weighttext, heighttext, name=None):
    """Return True when the base-screen OCR looks trustworthy."""
    if cp is None or cp <= 0:
        return False
    if hp is None or hp <= 0:
        return False
    if not typetext or typetext.strip().lower() in ("", "unknown"):
        return False
    if weighttext == "" and heighttext == "":
        return False
    return True


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

    reload_calibration(cfg)
    ui = cfg["ui"]

    try:
        for visit_num in range(1, args.limit + 1):
            log.info(f"--- Scanning Pokemon {visit_num} ---")

            # ── 1. OCR BASE SCREEN ────────────────────────────────────────────
            base_img = capture_window(cfg['mirror_region'])

            cp_text    = ocrregion(getrelativeregion(base_img, ui["cp_region"]))
            hp         = parsehp(ocrregion(getrelativeregion(base_img, ui["hp_region"])))
            type_text  = ocrregion(getrelativeregion(base_img, ui["type_region"]))
            weight_text = ocrregion(getrelativeregion(base_img, ui["weight_region"]))
            height_text = ocrregion(getrelativeregion(base_img, ui["height_region"]))
            cp         = parsecp(cp_text)

            # ── VLM base-screen fallback ──────────────────────────────────────
            _base_vlm_used = False
            _bvlm = {}

            if not _is_valid_base_parse(cp, hp, type_text, weight_text, height_text):
                log.info("Base-screen OCR suspect – calling VisionAgent")
                _bvlm = vision_agent.analyze_base_screen(base_img)

                if vision_agent.is_reliable(_bvlm):
                    _base_vlm_used = True
                    if _bvlm.get("cp",     {}).get("confidence", 0) > 0.75:
                        cp_text     = _bvlm["cp"]["text"]
                        cp          = parsecp(cp_text) or cp
                    if _bvlm.get("hp",     {}).get("confidence", 0) > 0.75:
                        hp          = parsehp(_bvlm["hp"]["text"]) or hp
                    if _bvlm.get("type1",  {}).get("confidence", 0) > 0.75:
                        type_text   = _bvlm["type1"]["text"]
                    if _bvlm.get("weight", {}).get("confidence", 0) > 0.75:
                        weight_text = _bvlm["weight"]["text"]
                    if _bvlm.get("height", {}).get("confidence", 0) > 0.75:
                        height_text = _bvlm["height"]["text"]
                    log.info(f"VLM base result: cp={cp} hp={hp} type={type_text} "
                             f"conf={_bvlm['confidence']:.2f}")
                else:
                    log.warning(f"VLM base-screen confidence too low "
                                f"({_bvlm.get('confidence', 0):.2f}), keeping OCR values")
            # ─────────────────────────────────────────────────────────────────

            # ── 2. OPEN APPRAISAL ─────────────────────────────────────────────
            tap.tap(ui['menu_button']['x'],   ui['menu_button']['y'],   base_delay=cfg['timing']['after_tap'])
            tap.tap(ui['appraise_button']['x'], ui['appraise_button']['y'], base_delay=cfg['timing']['after_appraise'])
            tap.tap(0.5, 0.5, base_delay=cfg['timing']['after_tap'])

            appraisal_img = wait_for_bars_stable_image(
                lambda: capture_window(cfg['mirror_region']),
                readappraisalbars,
                ui,
                cfg,
            )

            # ── 3. OCR NAME & IVS ────────────────────────────────────────────
            name_crop     = getrelativeregion(appraisal_img, ui['name_region'])
            raw_name_text = pytesseract.image_to_string(name_crop, config='--psm 6 --oem 3').strip()
            log.debug(f"[OCR RAW] name_region text → {raw_name_text!r}")
            name = resolvespeciesname(appraisal_img, ui, cp)
            log.debug(f"[OCR RESOLVED] → {name!r}")

            bar_strip = getrelativeregion(appraisal_img, ui['bar_region'])
            bars      = parseivbars(bar_strip)

            # ── VLM appraisal fallback ────────────────────────────────────────
            _appraisal_vlm_used = False
            _avlm = {}
            _name_needs_vlm = (name is None or name == "Unknown")
            _bars_need_vlm  = (bars is None or None in (bars or [None]))

            if _name_needs_vlm or _bars_need_vlm:
                log.info(f"Appraisal OCR suspect (name={name!r}, bars={bars}) "
                         f"– calling VisionAgent")
                _avlm = vision_agent.analyze_appraisal_screen(appraisal_img)

                if vision_agent.is_reliable(_avlm):
                    _appraisal_vlm_used = True

                    if _name_needs_vlm:
                        vlm_name = _avlm.get("name", {}).get("text", "")
                        if vlm_name:
                            resolved = resolvespeciesname(
                                vlm_name, type_text, weight_text, height_text)
                            if resolved and resolved != "Unknown":
                                log.info(f"VLM corrected name: {name!r} → {resolved!r}")
                                name          = resolved
                                raw_name_text = vlm_name

                    if _bars_need_vlm:
                        vlm_bars = vision_agent.extract_bar_values(_avlm)
                        if vlm_bars is not None:
                            log.info(f"VLM provided bars: {vlm_bars}")
                            bars = vlm_bars

                    log.info(f"VLM appraisal conf={_avlm.get('confidence', 0):.2f}")
                else:
                    log.warning(f"VLM appraisal confidence too low "
                                f"({_avlm.get('confidence', 0):.2f})")
            # ─────────────────────────────────────────────────────────────────

            # ── PATCH 5: Last-resort VLM recovery ────────────────────────────
            _still_broken = (
                name in (None, "Unknown")
                or bars is None
                or None in (bars or [None])
            )

            if _still_broken and not _appraisal_vlm_used:
                log.warning("Attempting last-resort VisionAgent recovery …")
                partial = {
                    "cp":     str(cp) if cp else "",
                    "hp":     str(hp) if hp else "",
                    "name":   name or "",
                    "type1":  type_text or "",
                    "weight": weight_text or "",
                    "height": height_text or "",
                }
                _rvlm = vision_agent.recover_failed_parse(base_img, appraisal_img, partial)

                if vision_agent.is_reliable(_rvlm):
                    log.info(f"Recovery VLM result (conf={_rvlm['confidence']:.2f}): {_rvlm}")

                    if name in (None, "Unknown"):
                        vlm_name_r = _rvlm.get("name", {}).get("text", "")
                        if vlm_name_r:
                            resolved_r = resolvespeciesname(
                                vlm_name_r, type_text, weight_text, height_text)
                            if resolved_r and resolved_r != "Unknown":
                                name = resolved_r

                    if bars is None or None in (bars or [None]):
                        vlm_bars_r = vision_agent.extract_bar_values(_rvlm)
                        if vlm_bars_r is not None:
                            bars = vlm_bars_r

                    if not cp or cp <= 0:
                        cp_text_r = _rvlm.get("cp", {}).get("text", "")
                        cp = parsecp(cp_text_r) or cp
                else:
                    log.warning(f"Recovery VLM also unreliable "
                                f"(conf={_rvlm.get('confidence', 0):.2f})")

            # Re-evaluate after all VLM attempts
            _still_broken = (
                name in (None, "Unknown")
                or bars is None
                or None in (bars or [None])
            )
            # ─────────────────────────────────────────────────────────────────

            # ── 4. DATA VALIDATION ────────────────────────────────────────────
            cp_valid = True
            if cp is None or cp > 5500 or cp < 10:
                log.warning(f"Impossible CP read: {cp}. Forcing REVIEW tag.")
                cp_valid = False

            if _still_broken:
                log.warning(f"Could not resolve name/bars after all fallbacks "
                            f"(name={name!r}, bars={bars}) – forcing REVIEW tag.")
                cp_valid = False      # guarantees the REVIEW branch below

            # ── 5. INSERT & EVALUATE ────────────────────────────x──────────────
            # Guard: unpack bars only when we have a clean tuple
            if bars and len(bars) == 3 and None not in bars:
                atk_iv, def_iv, sta_iv = bars
            else:
                atk_iv = def_iv = sta_iv = 0   # sentinel – will be REVIEW anyway
            if args.debug:
                log.info(
                    f"[SCAN] {name} | CP={cp} | "
                    f"ATK={atk_iv} DEF={def_iv} STA={sta_iv} | "
                    f"IV%={round((atk_iv + def_iv + sta_iv) / 45 * 100, 1)}%"
                )
            iv_data = compute_ivs(name, cp, hp, atk_iv, def_iv, sta_iv, 0)

            all_rankings = all_league_rankings_with_evos(name, atk_iv, def_iv, sta_iv)
            pvp = all_rankings.get(name, {"great": {}, "ultra": {}})
            evo_rankings = {
                s: l for s, l in all_rankings.items() if s != name
            }

            poke_id = insert_pokemon(conn, iv_data)
            insert_evo_rankings(conn, poke_id, evo_rankings)

            if not cp_valid:
                decision = {
                    "action": "REVIEW",
                    "reasons": ["Impossible CP read" if (cp is None or cp > 5500 or cp < 10)
                                else "Could not resolve name or IV bars"],
                    "beats_existing": False,
                    "existing_best": None,
                    "existing_top": [],
                }
            else:
                decision = evaluate_catch(
                    conn, name, cp,
                    atk_iv, def_iv, sta_iv,
                    iv_data["iv_pct"], pvp, evo_rankings,
                    current_id=poke_id,
                )

            action  = decision["action"]
            reasons = decision["reasons"]
            log.info(f"Result: {action} ({reasons})")

            # ── 6. CLOSE APPRAISAL ────────────────────────────────────────────
            tap.tap(0.5, 0.5, base_delay=cfg['timing']['after_tap'])

            # ── 7. APPLY TAG IN-GAME ──────────────────────────────────────────
            tap.tap(ui['menu_button']['x'],      ui['menu_button']['y'],      base_delay=cfg['timing']['after_tap'])
            tap.tap(ui['tag_option_btn']['x'],   ui['tag_option_btn']['y'],   base_delay=cfg['timing']['after_tap'])

            if action == "KEEP":
                tap.tap(ui['tag_keep']['x'],     ui['tag_keep']['y'])
            elif action == "TRANSFER":
                tap.tap(ui['tag_transfer']['x'], ui['tag_transfer']['y'])
            else:
                tap.tap(ui['tag_review']['x'],   ui['tag_review']['y'])

            tap.tap(ui['appraisal_done']['x'],ui['appraisal_done']['y'], base_delay=cfg['timing']['after_tap'])

            # ── 8. SWIPE TO NEXT ──────────────────────────────────────────────
            tap.swipe_left()

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

def pass2_tag(args, cfg, conn, tap, session_ids):
    ui = cfg["ui"]

    if not session_ids:
        log.info("Pass 2: nothing new to tag.")
        return

    placeholders = ",".join("?" * len(session_ids))
    new_rows = conn.execute(f"""
        SELECT * FROM pokemon
        WHERE id IN ({placeholders})
        ORDER BY id
    """, session_ids).fetchall()
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
            name   = row["name"]
            cp     = row["cp"]
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


def micro_pass_2_cleanup(conn, tap, ui, cfg):
    demoted_rows = conn.execute(
        "SELECT id, cp, hp, name FROM pokemon WHERE demoted = 1"
    ).fetchall()

    if not demoted_rows:
        log.info("No Pokémon were demoted. Pass 2 skipped! You are done.")
        return

    log.info(f"Micro Pass 2: Cleaning up {len(demoted_rows)} demoted Pokémon...")

    for p in demoted_rows:
        log.info(f"Demoting {p['name']} (CP {p['cp']}, HP {p['hp']}) to TRANSFER...")

        tap.tap(ui['search_icon']['x'], ui['search_icon']['y'], base_delay=cfg['timing']['after_tap'])
        search_str = f"{p['name']}&cp{p['cp']}&hp{p['hp']}"
        tap.type_text(search_str)
        time.sleep(1.5)

        tap.tap(ui['first_search_result']['x'], ui['first_search_result']['y'],
                base_delay=cfg['timing']['after_tap'])

        tap.tap(ui['menu_button']['x'],    ui['menu_button']['y'],    base_delay=cfg['timing']['after_tap'])
        tap.tap(ui['tag_option_btn']['x'], ui['tag_option_btn']['y'], base_delay=cfg['timing']['after_tap'])
        tap.tap(ui['tag_keep']['x'],     ui['tag_keep']['y'])
        tap.tap(ui['tag_transfer']['x'], ui['tag_transfer']['y'])
        tap.tap(0.5, 0.2, base_delay=cfg['timing']['after_tap'])

        tap.tap(ui['back_button']['x'],  ui['back_button']['y'],  base_delay=cfg['timing']['after_tap'])
        tap.tap(ui['clear_search']['x'], ui['clear_search']['y'], base_delay=cfg['timing']['after_tap'])

    log.info("Micro Pass 2 Complete.")


# ── Entry point ───────────────────────────────────────────────────────────────

def run_bot(args):
    from config import loadconfig
    from screen_capture import capture_window, get_mirror_window_bounds
    from tap_controller import TapController
    from iv_calculator import compute_ivs

    cfg  = loadconfig()
    conn = get_db()
    tap  = TapController(cfg)

    try:
        bounds = get_mirror_window_bounds()
        cfg["mirror_region"] = bounds
        tap.mirror = bounds
        log.info(f"iPhone Mirroring window bounds: {bounds}")
    except Exception as e:
        log.warning(f"Could not auto-detect window: {e}")

    if not tags_are_calibrated(cfg["ui"]):
        log.warning("Tag positions not calibrated — Pokémon will NOT be tagged in-game.")

    start_time = time.time()
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
            micro_pass_2_cleanup(conn, tap, cfg["ui"], cfg)
        elif args.dry_run:
            log.info("Dry-run: skipping Pass 2.")
        else:
            log.info("Tags not calibrated: skipping Pass 2.")

    except Exception as e:
        log.error(f"Unexpected error: {e}")
        traceback.print_exc()
    finally:
        elapsed = (time.time() - start_time) / 60
        stats   = get_stats(conn)
        log.info("=" * 50)
        log.info(f"Session: {len(session_ids) if 'session_ids' in dir() else 0} cataloged, "
                 f"{errors if 'errors' in dir() else 0} errors, {elapsed:.1f} min")
        log.info(f"DB totals: {stats}")
        log.info("=" * 50)
        conn.close()


if __name__ == "__main__":
    run_bot(parse_args())
