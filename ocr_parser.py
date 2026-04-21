import re
import json
import logging
from pathlib import Path
from PIL import Image
import pytesseract

log = logging.getLogger(__name__)

LOOKUPPATH = Path(__file__).parent / "species_lookup.json"
if LOOKUPPATH.exists():
    with open(LOOKUPPATH) as f:
        SPECIESDB = dict(json.load(f))
else:
    SPECIESDB = {}
    log.warning("specieslookup.json not found — run buildspecieslookup.py first")

ALLTYPES = [
    "Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting",
    "Poison", "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost",
    "Dragon", "Dark", "Steel", "Fairy",
]


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def ocrregion(img: Image.Image, upscale: bool = False) -> str:
    """Run Tesseract OCR on a PIL image crop. Optionally upscale for small regions."""
    if upscale:
        w, h = img.size
        img = img.resize((w * 3, h * 3), Image.LANCZOS)
    text = pytesseract.image_to_string(img, config="--psm 7").strip()
    return text


def getrelativeregion(img, region):
    W, H = img.size
    if "x1" in region:
        x1 = int(region["x1"] * W)
        y1 = int(region["y1"] * H)
        x2 = int(region["x2"] * W)
        y2 = int(region["y2"] * H)
    else:
        x1 = int(region["x"] * W)
        y1 = int(region["y"] * H)
        x2 = x1 + int(region["w"] * W)
        y2 = y1 + int(region["h"] * H)
    return img.crop((x1, y1, x2, y2))


# ---------------------------------------------------------------------------
# Individual field parsers
# ---------------------------------------------------------------------------

def parsecp(text: str) -> int:
    """Extract CP integer from OCR text like 'CP 310' or '310'."""
    m = re.search(r"(\d{1,4})", text)
    try:
        return int(m.group(1)) if m else 0
    except (ValueError, TypeError):
        return 0


def parsehp(text: str) -> int:
    """Extract HP integer from OCR text like '47 / 47 HP'."""
    m = re.search(r"(\d{1,5})", text.replace(",", ""))
    try:
        return int(m.group(1)) if m else 0
    except (ValueError, TypeError):
        return 0


def parseweight(text: str) -> float | None:
    """Extract weight in kg from OCR text like '4.20 kg' or '805.72kg'."""
    m = re.search(r"([\d.]+)\s*kg", text, re.IGNORECASE)
    try:
        return float(m.group(1)) if m else None
    except (ValueError, TypeError):
        return None


def parseheight(text: str) -> float | None:
    """Extract height in meters from OCR text like '0.40 m' or '1.70m'."""
    m = re.search(r"([\d.]+)\s*m\b", text, re.IGNORECASE)
    try:
        return float(m.group(1)) if m else None
    except (ValueError, TypeError):
        return None


# def parsetypes(text: str) -> set[str]:
#     """Extract Pokémon types from OCR text like 'Fire Flying' or 'FireFlying'."""
#     found = set()
#     for t in ALLTYPES:
#         if t.lower() in text.lower():
#             found.add(t)
#     return found


# ---------------------------------------------------------------------------
# Species identification (nickname-proof)
# ---------------------------------------------------------------------------

# def identifyspecies(weighttext: str, heighttext: str = "",
#                     cp: int = 0) -> str:
#     """Identify Pokémon species from type/weight/height OCR text.
#
#     Fully nickname-proof — never reads the display name.
#     Returns species name string, or 'Unknown' if unresolvable.
#     """
#     if not SPECIESDB:
#         return "Unknown"
#
#     #foundtypes = parsetypes(typetext)
#     weight = parseweight(weighttext)
#     #
#     # if not foundtypes:
#     #     log.debug(f"identifyspecies: no types parsed from {typetext!r}")
#     #     return "Unknown"
#
#     # # 1. Filter by exact type match
#     # candidates = [name for name, data in SPECIESDB.items()
#     #               if set(data["types"]) == foundtypes]
#     #
#     # if not candidates:
#     #     log.debug(f"identifyspecies: no species match for types {foundtypes}")
#     #     return "Unknown"
#     # if len(candidates) == 1:
#     #     return candidates[0]
#
#     # 2. Narrow by weight (±12% tolerance — covers GO's XS/XL size variants)
#     if weight is not None:
#         weightfiltered = [
#             name for name in candidates
#             if SPECIESDB[name].get("weightkg", 0) > 0
#             and abs(SPECIESDB[name]["weightkg"] - weight) / SPECIESDB[name]["weightkg"] <= 0.12
#         ]
#         if weightfiltered:
#             candidates = weightfiltered
#     if len(candidates) == 1:
#         return candidates[0]
#
#     # 3. Narrow by height (±12% tolerance)
#     height = parseheight(heighttext)
#     if height is not None:
#         heightfiltered = [
#             name for name in candidates
#             if SPECIESDB[name].get("heightm") is not None
#             and SPECIESDB[name]["heightm"] > 0
#             and abs(SPECIESDB[name]["heightm"] - height) / SPECIESDB[name]["heightm"] <= 0.12
#         ]
#         if heightfiltered:
#             candidates = heightfiltered
#     if len(candidates) == 1:
#         return candidates[0]
#
#     # 4. Return first candidate (best-effort)
#     return candidates[0]


# ---------------------------------------------------------------------------
# Pokémon name OCR  (NEW)
# ---------------------------------------------------------------------------

def ocrnameregion(img, ui):
    region = ui.get("name_region")
    if not region:
        return ""

    crop = getrelativeregion(img, region)
    W, H = crop.size
    crop = crop.resize((W * 3, H * 3), Image.LANCZOS)

    # Don't binarise — the teal text is close to the threshold and gets destroyed.
    # Greyscale + mild contrast boost is enough for Tesseract on this font.
    crop = crop.convert("L")
    from PIL import ImageEnhance
    crop = ImageEnhance.Contrast(crop).enhance(2.0)

    # PSM 6 = block of text (two lines); no whitelist so teal text isn't mangled
    text = pytesseract.image_to_string(crop, config="--psm 6 --oem 3").strip()
    # Collapse newlines so the regex works across the two-line caption
    text = text.replace("\n", " ")

    m = re.search(r"\bThis\s+(.+?)\s+was\b", text, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        log.debug(f"ocrnameregion: extracted {name!r} from: {text!r}")
        return name

    log.warning(f"ocrnameregion: pattern not found in: {text!r}")
    return ""

def resolvespeciesname(
    img: Image.Image,
    ui: dict,
    cp: int,
) -> str:
    """Combine type/weight/height species ID with direct name OCR for best accuracy.

    Strategy:
      1. Try species ID via types + weight + height (nickname-proof).
      2. If that fails or returns 'Unknown', fall back to name-label OCR.
      3. If the OCR name fuzzy-matches a known species, use it.
      4. Return 'Unknown' only if everything fails.
    """
    # species = identifyspecies(weighttext, heighttext, cp)
    # if species and species != "Unknown":
    #     return species

    # Fallback: OCR the name label visible below the IV bars
    ocr_name = ocrnameregion(img, ui)
    if not ocr_name:
        return "Unknown"

    # Exact match first (case-insensitive)
    ocr_lower = ocr_name.lower()
    for known in SPECIESDB:
        if known.lower() == ocr_lower:
            log.debug(f"resolvespeciesname: name OCR exact match → {known}")
            return known

    # Prefix match (handles truncated names like "Charizard" vs "CharizardMega …")
    matches = [k for k in SPECIESDB if k.lower().startswith(ocr_lower)]
    if len(matches) == 1:
        log.debug(f"resolvespeciesname: name OCR prefix match → {matches[0]}")
        return matches[0]
    if matches:
        # Prefer the shortest (base form)
        best = min(matches, key=len)
        log.debug(f"resolvespeciesname: name OCR best prefix match → {best}")
        return best

    # Return the raw OCR name as a last resort so the record is still saved
    log.debug(f"resolvespeciesname: using raw OCR name {ocr_name!r}")
    return ocr_name.title()


# ---------------------------------------------------------------------------
# IV bar parsing  (FIXED)
# ---------------------------------------------------------------------------

def readappraisalbars(img: Image.Image, ui: dict, barfillbrightness: float) -> tuple | None:
    """Read ATK/DEF/STA IVs (0–15) from a full appraisal screenshot.

    Uses colour detection (not brightness) to distinguish filled bar
    segments from the white card background and grey empty segments:
      - ATK / STA bars are orange: R>190, 110<G<190, B<100
      - DEF bar is pink/red:       R>155, G<145, R > G+25

    Samples each segment at its centre ±3px vertically (majority vote)
    to survive the thin inter-segment gap lines.
    """
    try:
        W, H = img.size
        bar_segments = ui.get("bar_segments", 15)
        x_start = ui.get("bar_x_start", 0.141)
        x_end   = ui.get("bar_x_end",   0.457)

        bar_ys = {
            "atk": (ui.get("atk_bar_y", 0.773), "orange"),
            "def": (ui.get("def_bar_y", 0.816), "pink"),
            "sta": (ui.get("sta_bar_y", 0.857), "orange"),
        }

        results = {}
        for stat, (yrel, color) in bar_ys.items():
            filled = 0
            py = int(yrel * H)
            for seg in range(bar_segments):
                xfrac = x_start + (x_end - x_start) * (seg + 0.5) / bar_segments
                px = int(xfrac * W)
                # Vote across 3 vertical samples to survive segment gap lines
                votes = 0
                for dy in (-3, 0, 3):
                    sample_y = max(0, min(py + dy, H - 1))
                    pixel = img.getpixel((px, sample_y))
                    r, g, b = pixel[0], pixel[1], pixel[2]
                    if color == "orange" and r > 190 and 110 < g < 190 and b < 100:
                        votes += 1
                    elif color == "pink" and r > 155 and g < 145 and r > g + 25:
                        votes += 1
                if votes >= 2:
                    filled += 1
            results[stat] = filled

        log.debug(f"Bar parse ATK={results['atk']} DEF={results['def']} STA={results['sta']}")
        return results["atk"], results["def"], results["sta"]

    except Exception as e:
        log.warning(f"readappraisalbars failed: {e}")
        return None


def readappraisalbarsdebug(img: Image.Image, ui: dict, barfillbrightness: float) -> tuple | None:
    """Debug version — saves an annotated bar strip to debugbars.png, then delegates."""
    try:
        W, H = img.size
        x_start   = ui.get("bar_x_start", 0.141)
        x_end     = ui.get("bar_x_end",   0.457)
        atk_bar_y = ui.get("atk_bar_y",   0.773)
        sta_bar_y = ui.get("sta_bar_y",   0.857)

        x1 = int(x_start * W)
        x2 = int(x_end   * W)
        y1 = int((atk_bar_y - 0.025) * H)
        y2 = int((sta_bar_y + 0.025) * H)
        barstrip = img.crop((x1, y1, x2, y2))

        # Upscale 3× so the saved image is readable at a glance
        sw, sh = barstrip.size
        barstrip = barstrip.resize((sw * 3, sh * 3), Image.LANCZOS)
        barstrip.save("debugbars.png")
        # Log the actual pixel colour at each bar's centre for calibration
        W2, H2 = img.size
        for stat, (yrel, color) in [
            ("ATK", (ui.get("atk_bar_y", 0.773), "orange")),
            ("DEF", (ui.get("def_bar_y", 0.816), "pink")),
            ("STA", (ui.get("sta_bar_y", 0.857), "orange")),
        ]:
            py = int(yrel * H2)
            sample_px = []
            for seg in range(ui.get("bar_segments", 15)):
                xfrac = x_start + (x_end - x_start) * (seg + 0.5) / ui.get("bar_segments", 15)
                px = int(xfrac * W2)
                r, g, b = img.getpixel((px, py))[:3]
                sample_px.append(f"({r},{g},{b})")
            log.debug(f"  {stat} y={py}: {' '.join(sample_px)}")
        log.info("Debug bar image saved to debugbars.png")

        return readappraisalbars(img, ui, barfillbrightness)

    except Exception as e:
        log.warning(f"readappraisalbarsdebug failed: {e}")
        return None