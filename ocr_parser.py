# ocr_parser.py
import re
import json
import logging
from pathlib import Path
from PIL import Image
import pytesseract

log = logging.getLogger(__name__)

# ── Load species lookup (built once by build_species_lookup.py) ──────────────
_LOOKUP_PATH = Path(__file__).parent / "species_lookup.json"
if _LOOKUP_PATH.exists():
    with open(_LOOKUP_PATH) as f:
        SPECIES_DB: dict = json.load(f)
else:
    SPECIES_DB = {}
    log.warning("species_lookup.json not found — run build_species_lookup.py first")

ALL_TYPES = {
    "Normal","Fire","Water","Electric","Grass","Ice","Fighting",
    "Poison","Ground","Flying","Psychic","Bug","Rock","Ghost",
    "Dragon","Dark","Steel","Fairy"
}

# ── OCR helpers ───────────────────────────────────────────────────────────────

def ocr_region(img: Image.Image, upscale: bool = False) -> str:
    """Run Tesseract OCR on a PIL image crop. Optionally upscale for small regions."""
    if upscale:
        w, h = img.size
        img = img.resize((w * 3, h * 3), Image.LANCZOS)
    text = pytesseract.image_to_string(img, config="--psm 7").strip()
    return text

def get_relative_region(img: Image.Image, region: dict) -> Image.Image:
    """
    Crop a region from img using relative coordinates (0.0–1.0).
    region = {"x": float, "y": float, "w": float, "h": float}
    """
    W, H = img.size
    x = int(region["x"] * W)
    y = int(region["y"] * H)
    w = int(region["w"] * W)
    h = int(region["h"] * H)
    return img.crop((x, y, x + w, y + h))

# ── Individual field parsers ──────────────────────────────────────────────────

def parse_cp(text: str) -> int:
    """Extract CP integer from OCR text like 'CP 310' or '310'."""
    m = re.search(r'\b(\d{1,5})\b', text.replace(",", ""))
    try:
        return int(m.group(1)) if m else 0
    except (ValueError, TypeError):
        return 0

def parse_hp(text: str) -> int:
    """Extract HP integer from OCR text like '47 / 47 HP'."""
    m = re.search(r'\b(\d{1,4})\b', text)
    try:
        return int(m.group(1)) if m else 0
    except (ValueError, TypeError):
        return 0

def parse_weight(text: str) -> float | None:
    """Extract weight in kg from OCR text like '4.20 kg' or '805.72kg'."""
    m = re.search(r'([\d.]+)\s*kg', text, re.IGNORECASE)
    try:
        return float(m.group(1)) if m else None
    except (ValueError, TypeError):
        return None

def parse_height(text: str) -> float | None:
    """Extract height in meters from OCR text like '0.40 m' or '1.70m'."""
    m = re.search(r'([\d.]+)\s*m\b', text, re.IGNORECASE)
    try:
        return float(m.group(1)) if m else None
    except (ValueError, TypeError):
        return None

def parse_types(text: str) -> set[str]:
    """Extract Pokémon types from OCR text like 'Fire Flying' or 'FireFlying'."""
    found = set()
    for t in ALL_TYPES:
        if t.lower() in text.lower():
            found.add(t)
    return found

# ── Species identification (nickname-proof) ───────────────────────────────────

def identify_species(type_text: str, weight_text: str, height_text: str = "", cp: int = 0) -> str:
    """
    Identify Pokémon species from type + weight + height OCR text.
    Fully nickname-proof — never reads the display name.
    Returns species name string, or 'Unknown' if unresolvable.
    """
    if not SPECIES_DB:
        return "Unknown"

    found_types = parse_types(type_text)
    weight      = parse_weight(weight_text)

    if not found_types:
        log.debug(f"identify_species: no types parsed from {type_text!r}")
        return "Unknown"

    # 1. Filter by exact type match
    candidates = [
        name for name, data in SPECIES_DB.items()
        if set(data["types"]) == found_types
    ]

    if not candidates:
        log.debug(f"identify_species: no species match for types={found_types}")
        return "Unknown"

    if len(candidates) == 1:
        return candidates[0]

    # 2. Narrow by weight (±12% tolerance covers GO's XS/XL size variants)
    if weight is not None:
        weight_filtered = [
            name for name in candidates
            if SPECIES_DB[name].get("weight_kg", 0) > 0
            and abs(SPECIES_DB[name]["weight_kg"] - weight) / SPECIES_DB[name]["weight_kg"] < 0.12
        ]
        if weight_filtered:
            candidates = weight_filtered

    if len(candidates) == 1:
        return candidates[0]

    # 3. Narrow by height (±12% tolerance)
    height = parse_height(height_text)
    if height is not None and len(candidates) > 1:
        height_filtered = [
            name for name in candidates
            if SPECIES_DB[name].get("height_m") is not None
            and SPECIES_DB[name]["height_m"] > 0
            and abs(SPECIES_DB[name]["height_m"] - height) / SPECIES_DB[name]["height_m"] < 0.12
        ]
        if height_filtered:
            candidates = height_filtered

    if len(candidates) == 1:
        return candidates[0]

    # 4. Closest combined weight+height match
    if weight is not None or height is not None:
        def score(name):
            d     = SPECIES_DB[name]
            w_err = abs(d["weight_kg"] - weight) / d["weight_kg"] if weight and d.get("weight_kg") else 0
            h_err = abs(d["height_m"]  - height) / d["height_m"]  if height and d.get("height_m")  else 0
            return w_err + h_err
        return min(candidates, key=score)

    log.warning(f"identify_species: ambiguous — {candidates}")
    return candidates[0]


# ── IV bar parsing ────────────────────────────────────────────────────────────

def parse_iv_bars(img: Image.Image, debug: bool = False) -> tuple[int, int, int] | None:
    """
    Read ATK / DEF / STA IV values (0–15) from the appraisal bar screenshot.
    Returns (atk_iv, def_iv, sta_iv) or None if parsing fails.
    """
    W, H = img.size

    bar_rows = {
        "atk": int(H * 0.30),
        "def": int(H * 0.55),
        "sta": int(H * 0.80),
    }

    results = {}
    for stat, row_y in bar_rows.items():
        filled = 0
        for x_frac in [i / 15 for i in range(1, 16)]:
            pixel = img.getpixel((int(x_frac * W * 0.9), row_y))
            r, g, b = pixel[:3]
            brightness = (r + g + b) / 3
            if brightness > 160:
                filled += 1
        results[stat] = filled

    if debug:
        log.debug(f"Bar parse: ATK={results['atk']} DEF={results['def']} STA={results['sta']}")

    return results["atk"], results["def"], results["sta"]


def read_appraisal_bars(img: Image.Image, ui: dict, bar_fill_brightness: float) -> tuple | None:
    """
    Read IV bars from a full appraisal screenshot using calibrated UI regions.
    Crops the bar region from img, then delegates to parse_iv_bars.
    Returns (atk_iv, def_iv, sta_iv) or None on failure.
    """
    try:
        bar_img = get_relative_region(img, ui["bar_region"])
        return parse_iv_bars(bar_img)
    except Exception as e:
        log.warning(f"read_appraisal_bars failed: {e}")
        return None


def read_appraisal_bars_debug(img: Image.Image, ui: dict, bar_fill_brightness: float) -> tuple | None:
    """
    Debug version of read_appraisal_bars — saves the cropped bar region to disk.
    Returns (atk_iv, def_iv, sta_iv) or None on failure.
    """
    try:
        bar_img = get_relative_region(img, ui["bar_region"])
        bar_img.save("debug_bars.png")
        log.info("Debug image saved to debug_bars.png")
        return parse_iv_bars(bar_img, debug=True)
    except Exception as e:
        log.warning(f"read_appraisal_bars_debug failed: {e}")
        return None