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
from freeze_detector import FreezeDetector
import vision_agent
import numpy as np
import random
from pause_controller import PauseController
from ocr_parser import (
    resolvespeciesname,
    parsecp, parsehp,
    ocrregion, getrelativeregion, parseivbars, parseivbarsdebug, parse_caught_date,
    readappraisalbars, readappraisalbarsdebug, ocr_type_region, parse_types, normalize_species_name
)
from pvp_rankings import all_league_rankings_with_evos
from database import get_db, get_stats, insert_pokemon, insert_evo_rankings, find_duplicate, get_evo_rankings, log_cp_consensus, set_nickname
from evaluator import evaluate_catch, get_best_in_db, enforce_top_n, promote_newly_immune
from tagger import apply_ingame_tag, tags_are_calibrated

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)
import concurrent.futures

_vlm_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="vlm-cp"
)

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--mode", choices=["catalog", "newcatch", "sync-flags"], default="catalog",
                   help="catalog: scan age0 box. newcatch: appraise most recent catch only.sync-flags: sync shiny/shadow/"                         "purified status from in-game search filters.")
    p.add_argument(
        "--tag-layout",
        choices=["default", "ff"],
        default="default",
        help="Choose which in-game tag menu layout to use."
    )
    p.add_argument("--log-cp-images", action="store_true",
                   help="Save OCR/VLM CP crops for consensus benchmarking, without full --debug overhead")
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
        if avg_conf < 40:
            continue
        aspect = width / max(1, height)
        # Allow confident short lines (e.g. a date fragment or short city name)
        # even if their aspect ratio is low; only block low-confidence narrow hits
        if aspect < 2.5 and avg_conf < 70:
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

    # Filter out lines whose height is anomalously large vs the median —
    # loading-bar artifacts tend to produce oversized bounding boxes
    median_h = sorted(x["height"] for x in lines)[len(lines) // 2]
    lines = [l for l in lines if l["height"] < median_h * 2.5]

    if not lines:
        return 2, "", []

    # Recompute median from the cleaned set so max_gap reflects real text height
    clean_median_h = sorted(x["height"] for x in lines)[len(lines) // 2]
    max_gap = max(18, int(clean_median_h * 1.25))

    # Anchor on the "caught" line, the date, or the "around" location line —
    # any of these three uniquely identifies the description block even when
    # Tesseract splits "caught … date" and "around … location" into separate
    # blocks due to contrast-enhanced mid-line breaks
    anchor_idx = None
    for i, line in enumerate(lines):
        txt = line["text"].lower()
        if (
            "caught" in txt
            or "around" in txt
            or re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", txt)
        ):
            anchor_idx = i
            break

    if anchor_idx is None:
        # No anchor found — fall back to the longest unbroken run of lines
        runs = []
        start = 0
        for i in range(1, len(lines)):
            gap = lines[i]["top"] - lines[i - 1]["bottom"]
            if gap > max_gap:
                runs.append((start, i - 1))
                start = i
        runs.append((start, len(lines) - 1))
        best = max(runs, key=lambda ab: ab[1] - ab[0] + 1)
        keep = lines[best[0] : best[1] + 1]
    else:
        # Expand outward from the anchor as long as lines are within max_gap
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
        keep = lines[lo : hi + 1]

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
                width=2,
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
            return img
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

def _valid_cp(cp):
    return cp is not None and 10 <= cp <= 5500

def _reconcile_cp(ocr_cp, vlm_cp, ocr_raw=""):
    if "/" in ocr_raw or "\\" in ocr_raw:
        ocr_valid = _valid_cp(ocr_cp)
        vlm_valid = _valid_cp(vlm_cp)
        if ocr_valid and (not vlm_valid or ocr_cp == vlm_cp):
            log.info(f"CP reconcile: OCR raw {ocr_raw!r} has slash/backslash — assuming 7 and trusting OCR {ocr_cp}")
            return ocr_cp, "slash_assumed_7"
        if vlm_valid:
            log.info(f"CP reconcile: OCR raw {ocr_raw!r} slash-parse gave {ocr_cp} (invalid or conflicts with VLM) — trusting VLM {vlm_cp}")
            return vlm_cp, "slash_ocr_rejected_trust_vlm"
        return ocr_cp or vlm_cp, "slash_no_valid_candidate"

    if ocr_cp is None:
        return vlm_cp, "ocr_missing_fallback_vlm"
    if vlm_cp is None:
        return ocr_cp, "vlm_missing_fallback_ocr"
    if ocr_cp == vlm_cp:
        return ocr_cp, "agree"

    ocr_s, vlm_s = str(ocr_cp), str(vlm_cp)
    if len(vlm_s) == len(ocr_s) + 1:
        if vlm_s.startswith(ocr_s):
            log.info(f"CP reconcile: VLM {vlm_cp} has spurious trailing digit vs OCR {ocr_cp} — trusting OCR")
            return ocr_cp, "vlm_trailing_digit"
        if vlm_s.endswith(ocr_s):
            log.info(f"CP reconcile: VLM {vlm_cp} has spurious leading digit vs OCR {ocr_cp} — trusting OCR")
            return ocr_cp, "vlm_leading_digit"
    if len(ocr_s) == len(vlm_s) + 1:
        if ocr_s.startswith(vlm_s) or ocr_s.endswith(vlm_s):
            log.info(f"CP reconcile: OCR {ocr_cp} has extra digit vs VLM {vlm_cp} — trusting VLM")
            return vlm_cp, "ocr_extra_digit"

    log.info(f"CP reconcile: same length OCR={ocr_cp} VLM={vlm_cp} — trusting VLM")
    return vlm_cp, "same_length_trust_vlm"

def reload_calibration(cfg):
    try:
        with open("calibration.json") as f:
            fresh = json.load(f)
        if "ui" in fresh: cfg["ui"] = fresh["ui"]
        if "bar_fill_brightness" in fresh: cfg["bar_fill_brightness"] = fresh["bar_fill_brightness"]
        if "timing" in fresh: cfg["timing"] = fresh["timing"]
    except Exception as e:
        log.warning(f"calibration reload failed (using current values): {e}")


def _is_valid_base_parse(cp, hp, typetext,name=None):
    """Return True when the base-screen OCR looks trustworthy."""
    if cp is None or cp <= 0:
        return False
    if hp is None or hp <= 0:
        return False
    type1, type2 = parse_types(typetext or "")
    if not type1:
        return False

    return True


def crop_cp_region(img: Image.Image) -> Image.Image:
    """Crop to just the CP number — exclude status bar and arc dot."""
    w, h = img.size

    # Skip the top ~8% (status bar) and bottom of the CP zone
    # CP number lives roughly between 8%-18% vertically
    # Horizontally centered — exclude the star/camera icons on the right
    top = int(h * 0.10)
    bottom = int(h * 0.18)
    left = int(w * 0.20)  # skip left edge noise
    right = int(w * 0.80)  # skip star icon on right

    crop = img.crop((left, top, right, bottom))


    # Upscale 3x — tighter crop means we can go bigger
    return crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS)


def _handle_freeze(tap, cfg, capture_window, freeze: FreezeDetector,
                   max_attempts: int = 3) -> bool:
    """
    Attempt to recover from a frozen iPhone Mirroring session.
    Returns True if the screen started changing again.
    """
    ui = cfg["ui"]

    for attempt in range(1, max_attempts + 1):
        log.warning(f"[FREEZE] Recovery attempt {attempt}/{max_attempts}...")

        # Attempt 1: no tap yet — just re-check in case it was a
        # transient stall (or a false trigger) that resolves on its own.
        if attempt == 1:
            time.sleep(1.5)
        # Attempt 2: safer nudge via a known control, not a blind
        # screen-center tap that could land on arbitrary UI.
        elif attempt == 2:
            log.warning("[FREEZE] Trying back button...")
            tap.tap(ui["back_button"]["x"], ui["back_button"]["y"], base_delay=2.0)
        else:
            log.warning("[FREEZE] Trying center-screen tap as last resort...")
            tap.tap(0.5, 0.5, base_delay=2.0)

        img   = capture_window(cfg["mirror_region"])
        ratio = freeze.similarity_to_last(img)

        if ratio < freeze._threshold:
            log.info(f"[FREEZE] Screen changed (similarity={ratio:.4f}) — recovered!")
            freeze.reset()
            return True

        time.sleep(3.0)

    log.error("[FREEZE] All recovery attempts failed.")
    return False

def _capture_cp_frames(capture_fn, cfg, n=5, interval=0.4,
                       debug=False, visit_num=0) -> list:
    frames = []
    for i in range(n):
        img = capture_fn(cfg["mirror_region"])
        frame = getrelativeregion(img, cfg["ui"]["cp_region"])
        if debug:
            os.makedirs("training_images", exist_ok=True)
            frame.save(f"training_images/cp_vlm_{visit_num:03d}_frame{i + 1}.png")
        frames.append(frame)
        time.sleep(interval)
    return frames


def _vlm_cp_consensus(frames: list, ocr_cp: int | None = None) -> tuple:
    from collections import Counter
    votes, backends = [], []
    ocr_len = len(str(ocr_cp)) if ocr_cp and ocr_cp > 0 else None

    for i, frame in enumerate(frames):
        try:
            raw, backend = vision_agent.call_vlm_with_backend(vision_agent._CP_PROMPT, [frame])
            parsed = vision_agent._parse_qa_response(raw)
            cp = parsecp(parsed.get("cp", {}).get("text", ""))
            if not cp:
                continue
            votes.append(cp)
            backends.append(backend)
            counts = Counter(votes)
            if ocr_len:
                matching = [v for v in votes if len(str(v)) == ocr_len]
                if len(matching) >= 2:
                    mcounts = Counter(matching)
                    best, count = mcounts.most_common(1)[0]
                    if count >= 2:
                        log.info(f"VLM CP early consensus (digit-filtered to {ocr_len} digits): "
                                 f"{best} ({count}/{len(matching)} matching votes, total votes={votes})")
                        return best, votes          # CHANGED
            best, count = counts.most_common(1)[0]
            if count >= 2:
                log.info(f"VLM CP early consensus: {best} ({count}/{len(votes)} votes so far, total votes={votes})")
                return best, votes                  # CHANGED
        except Exception as e:
            log.debug(f"  CP frame {i+1} failed: {e}")

    if not votes:
        return None, votes                          # CHANGED

    log.info(f"VLM CP consensus: all votes: {votes}")
    if ocr_len:
        matching = [v for v in votes if len(str(v)) == ocr_len]
        if matching:
            best, count = Counter(matching).most_common(1)[0]
            log.info(f"VLM CP (digit-filtered to {ocr_len} digits): {best} ({count}/{len(matching)} matching votes)")
            return best, votes                      # CHANGED

    best, count = Counter(votes).most_common(1)[0]
    log.info(f"VLM CP consensus: {best} ({count}/{len(votes)} votes)")
    return (best if count >= 2 else None), votes     # CHANGED
# ── Core scan logic ───────────────────────────────────────────────────────────

def scan_one_pokemon(visit_num, args, cfg, conn,
                     tap, capture_window, readappraisalbars, compute_ivs,
                     existing_id=None, base_img=None):
    ui = cfg["ui"]
    #log.info("args are {}".format(args))
    tag_layout = cfg.get("tag_layouts", {}).get(args.tag_layout, {})
    #log.info("tag_layout is {}".format(tag_layout))
    # ── 1. CAPTURE BASE SCREEN ────────────────────────────────────────────
    if base_img is None:
        base_img = capture_window(cfg["mirror_region"])

    cp_image = getrelativeregion(base_img, ui["cp_region"])
    if args.debug or args.log_cp_images:
        os.makedirs("training_images", exist_ok=True)

        cp_image.save(f"training_images/cp_ocr_{visit_num:03d}.png")

    os.makedirs("screenshots", exist_ok=True)
    cp_text     = ocrregion(cp_image)
    log.info(f"raw cp_text: {cp_text!r}")
    type_img = getrelativeregion(base_img, ui["type_region"])
    type_img.save(f"screenshots/type_{visit_num:03d}.png")
    type_text = ocr_type_region(type_img)
    # weight_text = ocrregion(getrelativeregion(base_img, ui["weight_region"]))
    # height_text = ocrregion(getrelativeregion(base_img, ui["height_region"]))
    log.info(f"normalized type_text: {type_text!r}")

    cp = parsecp(cp_text)
    _ocr_has_slash = "/" in cp_text or "\\" in cp_text
    if _ocr_has_slash:
        log.info("CP text contains slash/backslash — assuming it is a 7")

    hp_img = getrelativeregion(base_img, ui["hp_region"])
    hp_img.save(f"screenshots/hp{visit_num:03d}.png")
    try:
        hp = int(str(parsehp(ocrregion(hp_img))).replace(",", "").strip())
        log.info(f"HP text converted to number: {hp}")
    except (ValueError, TypeError):
        hp = 0

    # ── Submit CP consensus BEFORE any taps, while base screen is still visible
    # Capture frames immediately so all 5 land on the base screen
    _cp_frames = _capture_cp_frames(
        capture_window, cfg, n=capture_frames, interval=0.2,
        debug=(args.debug or args.log_cp_images), visit_num=visit_num,
    )
    _ocr_cp_at_capture = cp  # snapshot before any mutation

    def _run_consensus():
        return _vlm_cp_consensus(_cp_frames, ocr_cp=_ocr_cp_at_capture)

    _cp_vlm_future = _vlm_executor.submit(_run_consensus)
    # ─────────────────────────────────────────────────────────────────────

    # ── Base-screen VLM fallback (only if OCR is suspect) ─────────────────
    _base_vlm_used = False
    if not _is_valid_base_parse(cp, hp, type_text):
        log.info("Base-screen OCR suspect – calling VisionAgent")
        _bvlm = vision_agent.analyze_base_screen(base_img, visit_num)

        if vision_agent.is_reliable(_bvlm):
            _base_vlm_used = True
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
    # ─────────────────────────────────────────────────────────────────────

    # ── 2. OPEN APPRAISAL ─────────────────────────────────────────────────
    tap.tap(ui['menu_button']['x'],     ui['menu_button']['y'],
            base_delay=cfg['timing']['after_tap'])
    tap.tap(ui['appraise_button']['x'], ui['appraise_button']['y'],
            base_delay=random.uniform(0.1, 0.2))
    tap.tap(ui['appraise_button']['x'], ui['appraise_button']['y'],
            base_delay=random.uniform(0.2, 0.3))

    # ── Detect text layout ────────────────────────────────────────────────
    img_initial = capture_window(cfg["mirror_region"])
    raw_crop    = getrelativeregion(img_initial, ui["name_region"])

    num_lines, raw_text, kept_lines = detect_description_lines(
        raw_crop,
        debug=args.debug,
        debug_path=(f"screenshots/nameregion_lines_{visit_num:03d}.png"
                    if args.debug else None),
    )

    if args.debug:
        os.makedirs("screenshots", exist_ok=True)
        img_initial.save(f"screenshots/appraisal{visit_num:03d}.png")
        raw_crop.save(f"screenshots/nameregion{visit_num:03d}.png")
        log.info(f"  Name region OCR: {raw_text!r}")
        log.info(f"  Detected physical lines: {num_lines}")

    # ── Wait for bars & read ──────────────────────────────────────────────
    img = wait_for_bars_stable_image(
        lambda: capture_window(cfg["mirror_region"]),
        lambda im, u, b: readappraisalbars(im, u, b, lines=num_lines),
        ui, cfg,
    )
    if img is not None and args.debug:
        readappraisalbarsdebug(img, ui, cfg.get("bar_fill_brightness", 160), lines=num_lines)

    if img is None:
        log.warning(f"#{visit_num} Could not capture stable image. Skipping.")
        return None, None

    # ── Collect VLM CP consensus (frames were captured before any taps) ───
    try:
        vlm_cp, vlm_votes = _cp_vlm_future.result(timeout=60)
        reconciled, reconcile_reason = _reconcile_cp(_ocr_cp_at_capture, vlm_cp, ocr_raw=cp_text)
        if reconciled and reconciled > 0:
            if reconciled != cp:
                log.info(f"CP correction: {cp} → {reconciled} "
                         f"(ocr_at_capture={_ocr_cp_at_capture}, raw={cp_text!r}, vlm={vlm_cp})")
            cp = reconciled
        else:
            log.warning(f"Could not reconcile CP from OCR={_ocr_cp_at_capture}, vlm={vlm_cp}; keeping {cp}")

        _wants_cp_images = args.debug or args.log_cp_images

        try:
            log_cp_consensus(
                visit_num, _ocr_cp_at_capture, cp_text,  # Removed 'conn,' here
                vlm_votes, vlm_cp, reconciled, reconcile_reason,
                frame_paths=[f"training_images/cp_vlm_{visit_num:03d}_frame{i + 1}.png"
                             for i in range(len(_cp_frames))] if _wants_cp_images else [],
                ocr_image_path=f"training_images/cp_ocr_{visit_num:03d}.png" if _wants_cp_images else None,
            )
        except Exception as log_err:
            log.debug(f"cp_consensus_log insert failed (non-fatal): {log_err}")

    except Exception as e:
        log.warning(f"VLM CP consensus failed: {e} — keeping OCR CP {cp}")
    # ─────────────────────────────────────────────────────────────────────

    # ── 3. OCR NAME, BARS, CAUGHT DATE ───────────────────────────────────
    name        = resolvespeciesname(img, ui, cp, type_text)
    caught_date = parse_caught_date(raw_text)
    if not name or name == "Unknown":
        log.warning(f"#{visit_num} Species ID failed (cp={cp})")
        name = "Unknown"

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

    if args.debug:
        bars = parseivbarsdebug(bar_strip, debug_path=f"screenshots/ivbars_{visit_num:03d}.png")
    else:
        bars = parseivbars(bar_strip)

    if not bars:
        log.warning(f"#{visit_num} Bar read failed for {name}")

    # ── VLM appraisal fallback ────────────────────────────────────────────
    _name_needs_vlm = not name or name == "Unknown"
    vals = bars.values() if isinstance(bars, dict) else bars
    _bars_need_vlm = False #not bars or any(v is None for v in vals)
    _appraisal_vlm_used = False

    if _name_needs_vlm or _bars_need_vlm:
        log.info(f"Appraisal OCR suspect (name={name!r}, bars={bars}) "
                 f"– calling VisionAgent")
        _avlm = vision_agent.analyze_appraisal_screen(img_initial, visit_num)

        if vision_agent.is_reliable(_avlm):
            _appraisal_vlm_used = True
            if _name_needs_vlm:
                vlm_name = _avlm.get("name", {}).get("text", "")
                if vlm_name:
                    # Use the correct resolvespeciesname signature: (img, ui, cp, type_text)
                    resolved = resolvespeciesname(img, ui, cp, type_text)
                    if resolved and resolved != "Unknown":
                        log.info(f"VLM corrected name: {name!r} → {resolved!r}")
                        name = resolved
            if _bars_need_vlm:
                vlm_bars = vision_agent.extract_bar_values(_avlm)
                if vlm_bars is not None:
                    log.info(f"VLM provided bars: {vlm_bars}")
                    bars = vlm_bars
            log.info(f"VLM appraisal conf={_avlm.get('confidence', 0):.2f}")
        else:
            log.warning(f"VLM appraisal confidence too low "
                        f"({_avlm.get('confidence', 0):.2f})")

    # ── Last-resort recovery ──────────────────────────────────────────────
    if isinstance(bars, dict):
        bars = (bars.get("atk"), bars.get("def"), bars.get("sta"))

    _still_broken = (
            name in (None, "Unknown")
            or not bars
            or any(v is None for v in bars)
    )

    if _still_broken and not _appraisal_vlm_used:
        log.warning("Attempting last-resort VisionAgent recovery …")
        partial = {
            "cp":     str(cp)          if cp          else "",
            "hp":     str(hp)          if hp          else "",
            "name":   name             or "",
            "type1":  type_text        or "",
            # "weight": weight_text      or "",
            # "height": height_text      or "",
        }
        _rvlm = vision_agent.recover_failed_parse(base_img, img_initial, partial)

        if vision_agent.is_reliable(_rvlm):
            log.info(f"Recovery VLM (conf={_rvlm['confidence']:.2f}): {_rvlm}")
            if name in (None, "Unknown"):
                vlm_name_r = _rvlm.get("name", {}).get("text", "")
                if vlm_name_r:
                    resolved_r = resolvespeciesname(img, ui, cp, type_text)
                    if resolved_r and resolved_r != "Unknown":
                        name = resolved_r
            if not bars or None in (bars if isinstance(bars, list) else bars.values()):
                vlm_bars_r = vision_agent.extract_bar_values(_rvlm)
                if vlm_bars_r is not None:
                    bars = vlm_bars_r
            if not cp or cp <= 0:
                cp = parsecp(_rvlm.get("cp", {}).get("text", "")) or cp
        else:
            log.warning(f"Recovery VLM also unreliable "
                        f"(conf={_rvlm.get('confidence', 0):.2f})")

    # ── Extract IVs after all fallbacks have had a chance to fix bars ─────
    if isinstance(bars, dict):
        bars = (bars.get("atk"), bars.get("def"), bars.get("sta"))

    _still_broken = (
            name in (None, "Unknown")
            or not bars
            or any(v is None for v in bars)
    )

    if bars and not _still_broken:
        atk_iv, def_iv, sta_iv = (
            (bars["atk"], bars["def"], bars["sta"])
            if isinstance(bars, dict)
            else (bars[0], bars[1], bars[2])
        )
    else:
        atk_iv = def_iv = sta_iv = 0
    # ─────────────────────────────────────────────────────────────────────

    # ── 4. VALIDATION ─────────────────────────────────────────────────────
    cp_valid = True
    if not cp or cp > 5500 or cp < 10:
        log.warning(f"Impossible CP: {cp!r}. Forcing REVIEW.")
        cp_valid = False
    if _still_broken:
        log.warning(f"Unresolved name/bars after all fallbacks "
                    f"(name={name!r}, bars={bars}) – forcing REVIEW.")
        cp_valid = False

    # ── 5. INSERT / UPDATE & EVALUATE ────────────────────────────────────
    log.info(
        f"[SCAN] {name} | CP={cp} | "
        f"ATK={atk_iv} DEF={def_iv} STA={sta_iv} | "
        f"IV%={round((atk_iv + def_iv + sta_iv) / 45 * 100, 1)}%"
    )

    iv_data = compute_ivs(name, cp, hp, atk_iv, def_iv, sta_iv, 0)
    iv_data['caught_date'] = caught_date
    all_rankings = all_league_rankings_with_evos(name, atk_iv, def_iv, sta_iv)
    pvp          = all_rankings.get(name, {"great": {}, "ultra": {}})
    evo_rankings = {s: l for s, l in all_rankings.items() if s != name}
    iv_data["pvp"] = pvp

    if existing_id is None:
        is_dup = find_duplicate(
            conn, name, cp, atk_iv, def_iv, sta_iv, caught_date
        )
        if is_dup:
            log.warning(
                f"[DUPLICATE] {name} CP{cp} caught {caught_date!r} already "
                f"exists in DB — skipping insert to avoid double-counting."
            )
            tap.tap(ui['appraise_button']['x'], ui['appraise_button']['y'],
                    base_delay=random.uniform(0.1, 0.2))
            tap.swipe_left()
            return None, {
                "action": "SKIPPED_DUPLICATE",
                "reasons": [f"Duplicate of existing catch: {name} CP{cp} {caught_date}"],
                "beats_existing": False,
                "existing_best": None,
                "existing_top": [],
            }
        poke_id = insert_pokemon(conn, iv_data)
    else:
        poke_id = existing_id
        conn.execute("""
            UPDATE pokemon SET
                name=?, cp=?, hp=?, iv_atk=?, iv_def=?, iv_sta=?, iv_pct=?,
                gl_rank=?, gl_percentile=?, ul_rank=?, ul_percentile=?,
                caught_date=?
            WHERE id=?
        """, (
            iv_data["name"], iv_data["cp"], iv_data["hp"],
            atk_iv, def_iv, sta_iv, iv_data["iv_pct"],
            pvp.get("great", {}).get("rank"),
            pvp.get("great", {}).get("percentile"),
            pvp.get("ultra", {}).get("rank"),
            pvp.get("ultra", {}).get("percentile"),
            caught_date,
            poke_id,
        ))
        log.info(f"[REPROCESS] Updated existing row id={poke_id}")

    insert_evo_rankings(conn, poke_id, evo_rankings)
    set_nickname(conn, poke_id)

    if not cp_valid:
        reasons = []
        if not cp or cp <= 0 or cp > 5500:
            reasons.append("Impossible CP read")
        if _still_broken:
            reasons.append("Could not resolve name or IV bars")
        decision = {
            "action": "REVIEW",
            "reasons": reasons,
            "beats_existing": False,
            "existing_best": None,
            "existing_top": [],
        }
    else:
        decision = evaluate_catch(
            conn, name, cp,
            atk_iv, def_iv, sta_iv,
            iv_data["iv_pct"], pvp, evo_rankings,
            level=iv_data.get("level"),
            current_id=poke_id,
        )

    tag_value = decision["action"]
    reasons   = "; ".join(decision.get("reasons") or []) or None

    conn.execute("""
        UPDATE pokemon
           SET tag=?, needs_review=?, review_reason=?
         WHERE id=?
    """, (tag_value, 1 if tag_value == "REVIEW" else 0, reasons, poke_id))
    conn.commit()

    log.info(f"[TAG] {name} id={poke_id} → {tag_value}"
             + (f" | {reasons}" if reasons else ""))

    # ── 6. CLOSE APPRAISAL, RENAME, & APPLY TAG ───────────────────────────
    # close appraisal
    tap.tap(ui['appraise_button']['x'], ui['appraise_button']['y'],
            base_delay=random.uniform(0.1, 0.2))
    # find nickname in DB and rename in-game if present, but only if I was planning to keep it — otherwise, don't waste time renaming something I'm about to transfer or review.
    if tag_value == "KEEP":
        nickname_row = conn.execute(
            "SELECT nickname FROM pokemon WHERE id = ?", (poke_id,)
        ).fetchone()
        if nickname_row and nickname_row["nickname"]:
            rename_pokemon_ingame(tap, ui, cfg, nickname_row["nickname"])
            conn.execute(
                "UPDATE pokemon SET nickname_applied = 1 WHERE id = ?", (poke_id,)
            )
            conn.commit()
        else:
            log.warning(f"No nickname computed for id={poke_id}, skipping in-game rename")
    # TRANSFER / REVIEW: intentionally skip renaming, nickname_applied stays
    # 0 (its column default). Micro Pass 2 self-heals this the first time
    # the tag is ever revised — see PATCH 3.
    # set tag
    tap.tap(tag_layout['tag_menu_btn']['x'], tag_layout['tag_menu_btn']['y'],
            base_delay=cfg['timing']['after_tap'])
    tap.tap(tag_layout['tag_option_btn']['x'], tag_layout['tag_option_btn']['y'],
            base_delay=cfg['timing']['after_tap'])

    if tag_value == "KEEP":
        #log.info(f"keep tag coordinates: {tag_layout['tag_keep']['x']} {tag_layout['tag_keep']['y']}")
        tap.tap(tag_layout['tag_keep']['x'],     tag_layout['tag_keep']['y'])
    elif tag_value == "TRANSFER":
        #log.info(f"transfer tag coordinates: {tag_layout['tag_transfer']['x']} {tag_layout['tag_transfer']['y']}")
        tap.tap(tag_layout['tag_transfer']['x'], tag_layout['tag_transfer']['y'])
    else:
        #log.info(f"review tag coordinates: {tag_layout['tag_review']['x']} {tag_layout['tag_review']['y']}")
        tap.tap(tag_layout['tag_review']['x'],   tag_layout['tag_review']['y'])

    tap.tap(ui['appraisal_done']['x'], ui['appraisal_done']['y'],
            base_delay=cfg['timing']['after_tap'])

    return poke_id, decision

# =============================================================================
# main.py — sync_special_flags, REWRITTEN to walk the filtered list one
# Pokemon at a time instead of OCR-ing a scrolling grid. Reuses the same
# detail-screen OCR helpers as scan_one_pokemon(), just reads name/cp/
# caught_date and skips the appraisal/IV/tagging steps entirely.
# =============================================================================


def read_list_entry(base_img, appraisal_img, ui):
    """
    CP and type are read from the base screen (correct — those regions
    really are calibrated for that layout, same as scan_one_pokemon).

    Name and caught_date MUST come from the appraisal overlay — name_region
    is calibrated for that layout's position of the "This X was caught on..."
    text, which doesn't exist anywhere on the plain base screen.
    """
    cp_img = getrelativeregion(base_img, ui["cp_region"])
    cp_text = ocrregion(cp_img)
    cp = parsecp(cp_text)

    type_img = getrelativeregion(base_img, ui["type_region"])
    type_text = ocr_type_region(type_img)

    # CHANGED: use appraisal_img, not base_img
    name = resolvespeciesname(appraisal_img, ui, cp, type_text)

    desc_img = getrelativeregion(appraisal_img, ui["name_region"])
    _, raw_text, _ = detect_description_lines(desc_img)
    caught_date = parse_caught_date(raw_text)

    return (name, cp, caught_date)


def sync_special_flags(args, cfg, conn, tap, capture_window, pause):
    """
    Syncs is_shiny / form_status flags using the in-game search bar's own
    "Shiny" / "Shadow" / "Purified" filters as ground truth. Walks the
    filtered list one Pokemon at a time via next_arrow.

    CHANGED: now opens the appraisal overlay for each Pokemon (same tap
    sequence scan_one_pokemon uses to open it) before reading name/
    caught_date, then dismisses it via appraisal_done — WITHOUT applying
    any tag — before advancing. This is heavier per-Pokemon than the
    previous base-screen-only version, but it's necessary since the
    description text this function needs to match against the DB simply
    doesn't exist on the base screen.
    """
    ui = cfg["ui"]
    freeze = FreezeDetector(threshold=0.995, freeze_after=15.0)

    passes = [
        ("Shiny",    "is_shiny",    1),
        ("Shadow",   "form_status", "shadow"),
        ("Purified", "form_status", "purified"),
    ]

    for keyword, column, value in passes:
        log.info(f"--- Syncing {keyword} flags ---")

        tap.tap(ui["search_icon"]["x"], ui["search_icon"]["y"],
                base_delay=cfg["timing"].get("after_tap", 1.0))
        tap.type_text_applescript(keyword)
        time.sleep(1.5)

        tap.tap(ui["pokemon_slots"][0]["x"], ui["pokemon_slots"][0]["y"],
                base_delay=cfg["timing"].get("after_tap", 1.0))

        matched = 0
        skipped_no_match = 0
        last_entry = None
        repeatFlag = False
        visited = 0

        # NEW — open appraisal overlay, same sequence scan_one_pokemon uses.
        tap.tap(ui["menu_button"]["x"], ui["menu_button"]["y"],
                base_delay=cfg["timing"].get("after_tap"))
        tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                base_delay=random.uniform(0.1, 0.2))
        tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                base_delay=random.uniform(0.2, 0.3))

        while True:
            # Check if we've hit the limit for this specific category
            if args.limit > 0 and visited >= args.limit:
                log.info(f"Reached per-pass limit of {args.limit} for {keyword} sync.")
                break
            if pause.wait_if_paused():
                pass
            if pause.should_stop():
                log.info(f"Stop requested — ending {keyword} sync early.")
                break

            base_img = capture_window(cfg["mirror_region"])

            if freeze.update(base_img):
                recovered = _handle_freeze(tap, cfg, capture_window, freeze)
                if not recovered:
                    log.error(f"[FREEZE] Could not recover during {keyword} sync — stopping.")
                    break
                continue


            appraisal_img = capture_window(cfg["mirror_region"])

            entry = read_list_entry(base_img, appraisal_img, ui)
            name, cp, caught_date = entry
            log.info(f"{keyword} sync: read entry {visited+1}: {name} CP{cp} caught {caught_date}\n")

            # End of list: next_arrow stopped advancing, same Pokemon showing twice
            if entry == last_entry:
                log.info(f"{keyword} sync: reached end of list after {visited} entries.")
                repeatFlag = True
                break
            last_entry = entry
            visited += 1

            if name and name != "Unknown" and cp:
                log.info(f"[{keyword}] Read entry: name={name!r} cp={cp} caught_date={caught_date!r}")

                row = None
                if caught_date:
                    row = conn.execute(f"""
                                SELECT id, {column} FROM pokemon
                                WHERE name = ? AND cp = ? AND caught_date = ? AND {column} != ?
                                LIMIT 1
                            """, (name, cp, caught_date, value)).fetchone()
                    if row:
                        log.debug(
                            f"[{keyword}] Matched via (name, cp, caught_date): "
                            f"id={row['id']} current {column}={row[column]!r}"
                        )
                    else:
                        log.debug(
                            f"[{keyword}] No exact (name, cp, caught_date) match for "
                            f"name={name!r} cp={cp} date={caught_date!r} — trying (name, cp) fallback"
                        )
                else:
                    log.debug(f"[{keyword}] caught_date OCR was empty — going straight to (name, cp) fallback")

                if not row:
                    candidates = conn.execute("""
                                SELECT id, cp, caught_date FROM pokemon WHERE name = ? AND cp = ?
                            """, (name, cp)).fetchall()

                    if len(candidates) == 1:
                        row = candidates[0]
                        log.debug(
                            f"[{keyword}] Matched via unique (name, cp) fallback: "
                            f"id={row['id']} (only candidate for {name!r} CP{cp})"
                        )
                    elif len(candidates) > 1:
                        log.warning(
                            f"[{keyword}] Ambiguous match for {name!r} CP{cp}: "
                            f"{len(candidates)} candidates found "
                            f"(caught_dates={[c['caught_date'] for c in candidates]}) — "
                            f"skipping rather than risk flagging the wrong row"
                        )
                    else:
                        log.warning(
                            f"[{keyword}] Zero DB matches at all for {name!r} CP{cp} "
                            f"date={caught_date!r} — this Pokemon may not be in the "
                            f"database yet, or name/cp OCR is wrong"
                        )

                if row:
                    conn.execute(
                        f"UPDATE pokemon SET {column} = ? WHERE id = ?",
                        (value, row["id"])
                    )
                    matched += 1
                    log.info(f"[{keyword}] FLAGGED id={row['id']} ({name} CP{cp}) → {column}={value!r}")
                else:
                    skipped_no_match += 1
                    log.debug(
                        f"[{keyword}] No unique DB match for {name} CP{cp} date={caught_date} "
                        f"— skipped"
                    )
            else:
                skipped_no_match += 1
                log.warning(
                    f"[{keyword}] Skipping entry — OCR gave unusable data: "
                    f"name={name!r} cp={cp!r} caught_date={caught_date!r}"
                )

            tap_next_arrow(tap, ui, cfg)
            time.sleep(cfg["timing"].get("after_swipe", 0.8))

        conn.commit()
        log.info(
            f"{keyword} sync complete: {matched} flagged, "
            f"{skipped_no_match} skipped (no unique match), {visited} visited"
        )
        if repeatFlag:
            tap.tap(ui["back_button"]["x"], ui["back_button"]["y"],
                    base_delay=cfg["timing"].get("after_tap", 1.0))
            tap.tap(ui["clear_search"]["x"], ui["clear_search"]["y"],
                    base_delay=cfg["timing"].get("after_tap", 1.0))
        else:
            tap.tap(ui["back_button"]["x"], ui["back_button"]["y"],
                    base_delay=cfg["timing"].get("after_tap", 1.0))
            tap.tap(ui["back_button"]["x"], ui["back_button"]["y"],
                    base_delay=cfg["timing"].get("after_tap", 1.0))
            tap.tap(ui["clear_search"]["x"], ui["clear_search"]["y"],
                    base_delay=cfg["timing"].get("after_tap", 1.0))




def _wait_for_cp_screen_stable(capture_window, ui, cfg, timeout=4.0, poll=0.3):
    """
    Polls the CP region until two consecutive reads return the same
    (non-empty) text, or timeout is hit. Prevents OCR-ing a detail screen
    that's still mid-transition (sprite loading, intro animation, etc.) —
    specifically needed for the FIRST Pokemon opened from the list view,
    since that transition is heavier than swiping between two already-
    open detail screens.
    """
    prev_cp_text = None
    deadline = time.time() + timeout
    last_img = None
    while time.time() < deadline:
        img = capture_window(cfg["mirror_region"])
        last_img = img
        cp_img = getrelativeregion(img, ui["cp_region"])
        cp_text = ocrregion(cp_img).strip()
        if cp_text and cp_text == prev_cp_text:
            return img
        prev_cp_text = cp_text
        time.sleep(poll)
    return last_img

def check_freeze(capture_window, cfg, freeze, tap):
    img = capture_window(cfg["mirror_region"])
    if freeze.update(img):
        return _handle_freeze(tap, cfg, capture_window, freeze)
    return True  # not frozen (or recovered)

def rename_pokemon_ingame(tap, ui, cfg, nickname):
    """
    Renames the currently-displayed Pokemon on its detail screen (NOT the
    appraisal overlay) to the given nickname. Requires calibrated
    ui["nickname_edit_btn"] and ui["nickname_save_btn"] coordinates.
    """
    tap.tap(ui["nickname_edit_btn"]["x"], ui["nickname_edit_btn"]["y"],
            base_delay=cfg["timing"].get("after_tap"))
    tap.select_all_and_delete()
    tap.type_text_applescript(nickname)
    tap.tap(ui["nickname_save_btn"]["x"], ui["nickname_save_btn"]["y"],
            base_delay=cfg["timing"].get("after_tap"))

# =============================================================================
# PATCH — build_fallback_search() + candidate-walking logic in
# micro_pass2_cleanup(), replacing the v2 build_fallback_search /
# search_result_is_unique approach entirely.
#
# The search bar can only narrow to an IV BUCKET (5 buckets per stat:
#   atk0 = exact 0
#   atk1 = 1-4
#   atk2 = 5-9
#   atk3 = 10-14
#   atk4 = exact 15
# same for def/sta), never an exact IV. So the search string narrows the
# pool, then the bot has to open each visible result and read its real
# appraisal bars to find the one that actually matches.
# =============================================================================

# =============================================================================
# PATCH — build_fallback_search() gains shiny/shadow/purified filters.
# These are exactly the columns sync_special_flags() already writes
# (is_shiny, form_status), and exactly the keywords it already types into
# the search bar on its own filter passes ("Shiny", "Shadow", "Purified").
# Reusing them here narrows the fallback candidate pool further, which
# matters most for the shiny-discovery case that motivated this whole fix.
# =============================================================================

def iv_to_bucket(iv: int) -> int:
    """Maps an exact 0-15 IV to the search bar's 0-4 bucket filter value."""
    if iv == 0:
        return 0
    if iv <= 4:
        return 1
    if iv <= 9:
        return 2
    if iv <= 14:
        return 3
    return 4


def build_fallback_search(p) -> str:
    """
    Used only when nickname_applied = 0. Narrows the in-game search to a
    small candidate pool via species + CP + IV buckets + shiny/shadow/
    purified status + current tag. Still NOT guaranteed unique — caller
    must walk the resulting candidates and verify exact IVs
    (see locate_exact_candidate()).

    e.g. "zubat&cp10&atk0&def1&sta2&shiny&#transfer"
         "sableye&cp847&atk4&def4&sta3&shadow&#review"
    """
    parts = [p["name"].lower(), f"cp{p['cp']}"]
    if p["iv_atk"] is not None:
        parts.append(f"atk{iv_to_bucket(p['iv_atk'])}")
    if p["iv_def"] is not None:
        parts.append(f"def{iv_to_bucket(p['iv_def'])}")
    if p["iv_sta"] is not None:
        parts.append(f"sta{iv_to_bucket(p['iv_sta'])}")
    if p["is_shiny"]:
        parts.append("shiny")
    form = (p["form_status"] or "normal").lower()
    if form in ("shadow", "purified"):
        parts.append(form)
    old_tag = p["pending_old_tag"]
    if old_tag:
        parts.append(f"#{old_tag.lower()}")
    return "&".join(parts)


def locate_exact_candidate(tap, ui, cfg, capture_window, readappraisalbars,
                            target, max_candidates=15) -> bool:
    """
    Walks the currently-filtered search results one at a time (via the same
    pokemon_slots / swipe mechanics pass1_catalog uses) and opens each one's
    appraisal to compare its ACTUAL iv_atk/iv_def/iv_sta against `target`
    (a dict with cp, iv_atk, iv_def, iv_sta pulled from the DB row).

    Leaves the matching Pokemon's detail screen open on success (ready for
    the tag-change taps that follow in micro_pass2_cleanup). Returns False
    if no exact match was found among the first `max_candidates` results.
    """
    first_slot = ui["pokemon_slots"][0]
    tap.tap(first_slot["x"], first_slot["y"], base_delay=cfg["timing"].get("after_tap"))

    for attempt in range(max_candidates):
        img = capture_window(cfg["mirror_region"])
        cp_img = get_relative_region(img, ui["cp_region"])
        cp_text = ocr_region(cp_img)
        cp = parse_cp(cp_text)

        if cp != target["cp"]:
            log.debug(f"  Candidate {attempt + 1}: CP{cp} != target CP{target['cp']}, skipping")
            tap.swipe_left()
            continue

        tap.tap(ui["menu_button"]["x"], ui["menu_button"]["y"],
                base_delay=cfg["timing"].get("after_tap"))
        tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                base_delay=random.uniform(0.1, 0.2))
        tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                base_delay=random.uniform(0.2, 0.3))

        bar_img = wait_for_bars_stable(
            lambda: capture_window(cfg["mirror_region"]),
            lambda im, u, b: readappraisalbars(im, u, b, lines=None),
            ui, cfg,
        )
        bars = parse_iv_bars(bar_img) if bar_img is not None else None
        atk, def_, sta = (bars if bars else (None, None, None))

        tap.tap(ui["appraise_button"]["x"], ui["appraise_button"]["y"],
                base_delay=random.uniform(0.1, 0.2))  # close appraisal overlay

        if (atk, def_, sta) == (target["iv_atk"], target["iv_def"], target["iv_sta"]):
            log.info(f"  Candidate {attempt + 1}: exact IV match "
                      f"({atk}/{def_}/{sta}) — locked in")
            return True

        log.debug(f"  Candidate {attempt + 1}: IVs {atk}/{def_}/{sta} != "
                  f"target {target['iv_atk']}/{target['iv_def']}/{target['iv_sta']}, "
                  f"trying next")
        tap.swipe_left()

    return False

# ── Pass 1: Catalog ───────────────────────────────────────────────────────────

def pass1_catalog(args, cfg, conn,
                  tap, capture_window, readappraisalbars,
                  compute_ivs, pause):
    from screen_capture import capture_window, get_mirror_window_bounds
    ui = cfg["ui"]
    session_ids = []
    visit_num   = 0
    errors      = 0
    last_poke_id = None
    freeze = FreezeDetector(threshold=0.995, freeze_after=15.0)

    log.info("── Pass 1: Cataloging ──────────────────────────────────────────")
    log.info("Set the in-game search to 'age0', navigate to storage, then wait.")
    for i in range(3, 0, -1):
        log.info(f"Starting in {i}s…")
        time.sleep(1)

    if not args.dry_run:
        slot = ui["pokemon_slots"][-1] if args.mode == "newcatch" else ui["pokemon_slots"][0]
        log.info(f"Tapping {'last' if args.mode == 'newcatch' else 'first'} slot")
        tap.tap(slot["x"], slot["y"], base_delay=cfg["timing"]["after_tap"])

        # NEW — explicit settle-wait for the FIRST detail screen only.
        # This is the transition from list-view to detail-view, which is
        # heavier (asset loading, intro animation) than the swipe-based
        # transitions used for every subsequent Pokemon in the loop.
        log.info("Waiting for first Pokémon's detail screen to stabilize...")
        _wait_for_cp_screen_stable(capture_window, ui, cfg)

    reload_calibration(cfg)
    ui = cfg["ui"]

    try:
        for visit_num in range(1, args.limit + 1):

            # ── Pause / quit check ────────────────────────────────────
            if pause.wait_if_paused():
                reload_calibration(cfg)
                try:
                    bounds = get_mirror_window_bounds()
                    cfg["mirror_region"] = bounds
                    tap.mirror = bounds
                    log.info(f"[RESUME] Re-detected window bounds: {bounds}")
                except Exception as e:
                    log.warning(f"[RESUME] Could not re-detect window bounds: {e}")
                ui = cfg["ui"]

            if pause.should_stop():
                log.info("Clean stop requested — ending Pass 1.")
                break

            # ── Reprocess check ───────────────────────────────────────
            if pause.should_reprocess() and last_poke_id is not None:
                log.info(f"[REPROCESS] Re-scanning id={last_poke_id}…")
                poke_id, decision = scan_one_pokemon(
                    visit_num, args, cfg, conn,
                    tap, capture_window, readappraisalbars, compute_ivs,
                    existing_id=last_poke_id,
                )
                if poke_id:
                    tap.swipe_left()
                continue
            # ─────────────────────────────────────────────────────────

            log.info(f"--- Scanning Pokemon {visit_num} ---")

            # ── Freeze check ──────────────────────────────────────────
            base_img = capture_window(cfg["mirror_region"])
            if freeze.update(base_img):
                recovered = _handle_freeze(tap, cfg, capture_window, freeze)
                if not recovered:
                    log.error("[FREEZE] Could not recover — stopping bot.")
                    break
                continue
            # ─────────────────────────────────────────────────────────

            poke_id, decision = scan_one_pokemon(
                visit_num, args, cfg, conn,
                tap, capture_window, readappraisalbars, compute_ivs,
                base_img=base_img
            )

            if poke_id is None:
                errors += 1
                if not args.dry_run:
                    tap_next_arrow(tap, ui, cfg)
                continue

            last_poke_id = poke_id
            session_ids.append(poke_id)

            # ── Swipe to next ─────────────────────────────────────────
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

# =============================================================================
# micro_pass2_cleanup() — updated body for the fallback branch. The
# nickname-search branch (nickname_applied = 1) is unchanged from before:
# it's already unique by construction, so no candidate-walking needed there.
# =============================================================================

def micro_pass2_cleanup(args, conn, tap, ui, cfg, pause):
    tag_layout = cfg.get("tag_layouts", {}).get(args.tag_layout, {})
    # =============================================================================
    # micro_pass2_cleanup() only needs its SELECT widened to pull is_shiny and
    # form_status so build_fallback_search() has them available. Everything
    # else in the function (locate_exact_candidate, candidate walking, retag,
    # self-heal rename) is unchanged from the last version.
    # =============================================================================

    rows = conn.execute("""
            SELECT id, cp, hp, name, nickname, nickname_applied,
                   iv_atk, iv_def, iv_sta, is_shiny, form_status,
                   tag, pending_old_tag
            FROM pokemon
            WHERE demoted = 1 OR tag_changed = 1
        """).fetchall()

    if not rows:
        log.info("No Pokémon need in-game re-tagging. Pass 2 skipped!")
        return
    log.info(f"Micro Pass 2: re-tagging {len(rows)} Pokémon...")
    from screen_capture import capture_window
    freeze = FreezeDetector(threshold=0.995, freeze_after=15.0)
    tag_key_map = {"KEEP": "tag_keep", "TRANSFER": "tag_transfer", "REVIEW": "tag_review"}

    for p in rows:
        pause.wait_if_paused()
        if pause.should_stop():
            log.info("Clean stop requested — ending Pass 2.")
            break

        old_tag = p["pending_old_tag"]
        new_tag = p["tag"]
        old_key = tag_key_map.get(old_tag) if old_tag else None
        new_key = tag_key_map.get(new_tag)

        if old_tag and (old_key is None or old_key not in tag_layout):
            conn.execute("UPDATE pokemon SET needs_review = 1, "
                         "review_reason = 'retag_skipped_old_tag_uncalibrated' WHERE id = ?",
                         (p["id"],))
            conn.commit()
            continue
        if new_key is None or new_key not in tag_layout:
            conn.execute("UPDATE pokemon SET needs_review = 1, "
                         "review_reason = 'retag_skipped_new_tag_uncalibrated' WHERE id = ?",
                         (p["id"],))
            conn.commit()
            continue

        img = capture_window(cfg["mirror_region"])
        if freeze.update(img):
            if not handle_freeze(tap, cfg, capture_window, freeze):
                log.error("FREEZE: Could not recover in micro Pass 2, stopping.")
                break
            continue

        tap.tap(ui["search_icon"]["x"], ui["search_icon"]["y"],
                base_delay=cfg["timing"].get("after_tap"))
        if not check_freeze(capture_window, cfg, freeze, tap):
            break

        using_nickname_search = bool(p["nickname_applied"] and p["nickname"])
        search_str = p["nickname"] if using_nickname_search else build_fallback_search(p)
        if not using_nickname_search:
            log.warning(f"No in-game nickname for {p['name']} id={p['id']} — "
                        f"narrowing via '{search_str}', will verify IVs candidate-by-candidate")
        tap.type_text_applescript(search_str)
        time.sleep(1.5)

        if using_nickname_search:
            tap.tap(ui["first_search_result"]["x"], ui["first_search_result"]["y"],
                    base_delay=cfg["timing"].get("after_tap"))
        else:
            target = {"cp": p["cp"], "iv_atk": p["iv_atk"], "iv_def": p["iv_def"], "iv_sta": p["iv_sta"]}
            found = locate_exact_candidate(tap, ui, cfg, capture_window, readappraisalbars, target)
            if not found:
                log.warning(f"[{p['name']} id={p['id']}] no candidate matched exact IVs — "
                            f"flagging for manual review")
                conn.execute("""
                    UPDATE pokemon SET needs_review = 1,
                           review_reason = 'pass2_fallback_no_exact_iv_match'
                    WHERE id = ?
                """, (p["id"],))
                conn.commit()
                tap.tap(cfg["ui"]["back_button"]["x"], cfg["ui"]["back_button"]["y"],
                        base_delay=cfg["timing"].get("after_tap"))
                tap.tap(cfg["ui"]["clear_search"]["x"], cfg["ui"]["clear_search"]["y"],
                        base_delay=cfg["timing"].get("after_tap"))
                continue

        if not check_freeze(capture_window, cfg, freeze, tap):
            break

        tap.tap(ui["menu_button"]["x"], ui["menu_button"]["y"],
                base_delay=cfg["timing"].get("after_tap"))
        tap.tap(tag_layout["tag_option_btn"]["x"], tag_layout["tag_option_btn"]["y"],
                base_delay=cfg["timing"].get("after_tap"))
        if not check_freeze(capture_window, cfg, freeze, tap):
            break

        if old_key:
            tap.tap(tag_layout[old_key]["x"], tag_layout[old_key]["y"])
            time.sleep(cfg["timing"].get("after_tap", 0.5))
        tap.tap(tag_layout[new_key]["x"], tag_layout[new_key]["y"])
        dismiss = ui.get("tag_dismiss", {"x": 0.500, "y": 0.850})
        tap.tap(dismiss["x"], dismiss["y"])

        if not p["nickname_applied"] and p["nickname"]:
            rename_pokemon_ingame(tap, ui, cfg, p["nickname"])
            conn.execute("UPDATE pokemon SET nickname_applied = 1 WHERE id = ?", (p["id"],))

        tap.tap(cfg["ui"]["back_button"]["x"], cfg["ui"]["back_button"]["y"],
                base_delay=cfg["timing"].get("after_tap"))
        tap.tap(cfg["ui"]["clear_search"]["x"], cfg["ui"]["clear_search"]["y"],
                base_delay=cfg["timing"].get("after_tap"))
        conn.execute("""
            UPDATE pokemon SET demoted = 0, tag_changed = 0, pending_old_tag = NULL
            WHERE id = ?
        """, (p["id"],))
        conn.commit()

    log.info("Micro Pass 2 complete.")



# ── Entry point ───────────────────────────────────────────────────────────────

def run_bot(args):
    from config import load_config
    from screen_capture import capture_window, get_mirror_window_bounds
    from tap_controller import TapController
    from iv_calculator import compute_ivs
    import vision_agent
    cfg  = load_config()
    conn = get_db()
    tap  = TapController(cfg)
    tag_layout = cfg.get("tag_layouts", {}).get(args.tag_layout, {})

    pause = PauseController(pause_key='f9', quit_key='f10', reprocess_key='f8')
    pause.start()

    try:
        bounds = get_mirror_window_bounds()
        cfg["mirror_region"] = bounds
        tap.mirror = bounds
        log.info(f"iPhone Mirroring window bounds: {bounds}")
    except Exception as e:
        log.warning(f"Could not auto-detect window: {e}")

    start_time = time.time()
    log.info("=" * 50)
    log.info(f"Pokémon GO IV Cataloger — Mode: {args.mode}")
    log.info("=" * 50)

    # ── sync-flags mode: entirely separate path, skips VLM warmup/Pass 1/Pass 2 ──
    if args.mode == "sync-flags":
        try:
            for i in range(3, 0, -1):
                log.info(f"Starting flag sync in {i}s…")
                time.sleep(1)
            sync_special_flags(args, cfg, conn, tap, capture_window, pause)

            log.info("Recomputing PvP rankings for newly-flagged shadows…")
            from evaluator import recompute_shadow_rankings, promote_newly_immune, enforce_top_n
            n = recompute_shadow_rankings(conn)
            log.info(f"Recomputed rankings for {n} shadow Pokémon")

            # ADD THIS BLOCK to promote shinies/immunes:
            log.info("Promoting newly-immune Pokémon (e.g., shinies)…")
            promoted = promote_newly_immune(conn)
            if promoted:
                log.info(f"Promoted {len(promoted)} Pokémon to KEEP after flag sync")

            log.info("Re-running top-N enforcement with updated flags…")
            demoted = enforce_top_n(conn, top_n=5)
            if demoted:
                log.warning(f"{len(demoted)} Pokémon demoted after flag sync")

            if tags_are_calibrated(tag_layout):
                micro_pass2_cleanup(args, conn, tap, cfg["ui"], cfg, pause)
        except Exception as e:
            log.error(f"Sync-flags mode failed: {e}")
            traceback.print_exc()
        finally:
            conn.close()
        return  # don't fall through to the catalog flow below

    # ── normal catalog / newcatch modes (unchanged) ──────────────────────────
    if not tags_are_calibrated(tag_layout):
        log.warning("Tag positions not calibrated — Pokémon will NOT be tagged in-game.")

    log.info("Warming up VLM — scanning will begin once model is ready…")
    vlm_ready = vision_agent.warmup_remote()
    if vlm_ready:
        log.info("VLM ready on remote PC.")
    else:
        log.warning("VLM falling back to local M1 model (2B).")

    for i in range(3, 0, -1):
        log.info(f"Starting in {i}s…")
        time.sleep(1)

    try:
        session_ids, errors = pass1_catalog(
            args, cfg, conn, tap, capture_window, readappraisalbars, compute_ivs, pause
        )

        if not args.dry_run and session_ids:
            from evaluator import enforce_top_n
            demoted = enforce_top_n(conn, top_n=5)
            if demoted:
                log.warning(f"{len(demoted)} Pokémon demoted beyond top-5 this session")

        # CHANGED: removed the duplicate reset_remote_status() call —
        # your pasted version calls this twice back-to-back, once inside
        # the `if not args.dry_run and session_ids:` block and once again
        # unconditionally right after. Only need it once.
        vision_agent.reset_remote_status()

        if not args.dry_run and tags_are_calibrated(tag_layout):
            tap.tap(cfg["ui"]["back_button"]["x"], cfg["ui"]["back_button"]["y"],
                    base_delay=cfg["timing"].get("after_tap"))
            tap.tap(cfg["ui"]["clear_search"]["x"], cfg["ui"]["clear_search"]["y"],
                    base_delay=cfg["timing"].get("after_tap"))
            micro_pass2_cleanup(args, conn, tap, cfg["ui"], cfg, pause)
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
    capture_frames = 3
    run_bot(parse_args())

