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


def parsetypes(text: str) -> set[str]:
    """Extract Pokémon types from OCR text like 'Fire Flying' or 'FireFlying'."""
    found = set()
    for t in ALLTYPES:
        if t.lower() in text.lower():
            found.add(t)
    return found


# ---------------------------------------------------------------------------
# Species identification (nickname-proof)
# ---------------------------------------------------------------------------

def identifyspecies(typetext: str, weighttext: str, heighttext: str = "",
                    cp: int = 0) -> str:
    """Identify Pokémon species from type/weight/height OCR text.

    Fully nickname-proof — never reads the display name.
    Returns species name string, or 'Unknown' if unresolvable.
    """
    if not SPECIESDB:
        return "Unknown"

    foundtypes = parsetypes(typetext)
    weight = parseweight(weighttext)

    if not foundtypes:
        log.debug(f"identifyspecies: no types parsed from {typetext!r}")
        return "Unknown"

    # 1. Filter by exact type match
    candidates = [name for name, data in SPECIESDB.items()
                  if set(data["types"]) == foundtypes]

    if not candidates:
        log.debug(f"identifyspecies: no species match for types {foundtypes}")
        return "Unknown"
    if len(candidates) == 1:
        return candidates[0]

    # 2. Narrow by weight (±12% tolerance — covers GO's XS/XL size variants)
    if weight is not None:
        weightfiltered = [
            name for name in candidates
            if SPECIESDB[name].get("weightkg", 0) > 0
            and abs(SPECIESDB[name]["weightkg"] - weight) / SPECIESDB[name]["weightkg"] <= 0.12
        ]
        if weightfiltered:
            candidates = weightfiltered
    if len(candidates) == 1:
        return candidates[0]

    # 3. Narrow by height (±12% tolerance)
    height = parseheight(heighttext)
    if height is not None:
        heightfiltered = [
            name for name in candidates
            if SPECIESDB[name].get("heightm") is not None
            and SPECIESDB[name]["heightm"] > 0
            and abs(SPECIESDB[name]["heightm"] - height) / SPECIESDB[name]["heightm"] <= 0.12
        ]
        if heightfiltered:
            candidates = heightfiltered
    if len(candidates) == 1:
        return candidates[0]

    # 4. Return first candidate (best-effort)
    return candidates[0]


# ---------------------------------------------------------------------------
# Pokémon name OCR  (NEW)
# ---------------------------------------------------------------------------

def ocrnameregion(img: Image.Image, ui: dict) -> str:
    """OCR the Pokémon name label from the appraisal screen.

    This reads the name label displayed directly below the IV bars
    (the 'nameregion' calibration region). It is used as a cross-check
    against the species identified from types/weight/height, and as a
    fallback when species ID fails.

    Returns the cleaned name string, or '' if nothing readable.
    """
    try:
        nameimg = getrelativeregion(img, ui["nameregion"])
        # Upscale so Tesseract handles the small font better
        w, h = nameimg.size
        nameimg = nameimg.resize((w * 3, h * 3), Image.LANCZOS)
        raw = pytesseract.image_to_string(
            nameimg,
            config="--psm 7 -c tessedit_char_whitelist="
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .-'é"
        ).strip()
        # Strip any trailing punctuation / stray characters
        name = re.sub(r"[^A-Za-zÀ-ÿ .'\-]", "", raw).strip()
        return name
    except Exception as e:
        log.debug(f"ocrnameregion failed: {e}")
        return ""


def resolvespeciesname(
    img: Image.Image,
    ui: dict,
    typetext: str,
    weighttext: str,
    heighttext: str,
    cp: int,
) -> str:
    """Combine type/weight/height species ID with direct name OCR for best accuracy.

    Strategy:
      1. Try species ID via types + weight + height (nickname-proof).
      2. If that fails or returns 'Unknown', fall back to name-label OCR.
      3. If the OCR name fuzzy-matches a known species, use it.
      4. Return 'Unknown' only if everything fails.
    """
    species = identifyspecies(typetext, weighttext, heighttext, cp)
    if species and species != "Unknown":
        return species

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
    """Read IV bars from a full appraisal screenshot using calibrated UI regions.

    Uses the individual bar Y lines (atkbary, defbary, stabary) and
    barxstart / barxend from calibration — NOT a single 'barregion' rect.

    Returns (atkiv, defiv, staiv) each 0–15, or None on failure.
    """
    try:
        W, H = img.size
        barsegments = ui.get("barsegments", 15)
        xstart = ui.get("barxstart", 0.141)
        xend   = ui.get("barxend",   0.457)

        bar_ys = {
            "atk": ui.get("atkbary", 0.773),
            "def": ui.get("defbary", 0.816),
            "sta": ui.get("stabary", 0.857),
        }

        results = {}
        for stat, yrel in bar_ys.items():
            rowy = int(yrel * H)
            filled = 0
            for seg in range(1, barsegments + 1):
                # Sample the centre of each segment
                xfrac = xstart + (xend - xstart) * (seg - 0.5) / barsegments
                px = int(xfrac * W)
                pixel = img.getpixel((px, rowy))
                r, g, b = pixel[:3]
                brightness = (r + g + b) / 3
                if brightness >= barfillbrightness:
                    filled += 1
            results[stat] = filled

        log.debug(f"Bar parse ATK={results['atk']} DEF={results['def']} STA={results['sta']}")
        return results["atk"], results["def"], results["sta"]

    except Exception as e:
        log.warning(f"readappraisalbars failed: {e}")
        return None


def readappraisalbarsdebug(img: Image.Image, ui: dict, barfillbrightness: float) -> tuple | None:
    """Debug version of readappraisalbars — saves the bar strip to disk."""
    try:
        W, H = img.size
        xstart = ui.get("barxstart", 0.141)
        xend   = ui.get("barxend",   0.457)
        atkbary = ui.get("atkbary", 0.773)
        stabary = ui.get("stabary", 0.857)

        # Crop the region spanning all three bars for debugging
        x1 = int(xstart * W)
        x2 = int(xend * W)
        y1 = int((atkbary - 0.02) * H)
        y2 = int((stabary + 0.02) * H)
        barstrip = img.crop((x1, y1, x2, y2))
        barstrip.save("debugbars.png")
        log.info("Debug bar image saved to debugbars.png")

        return readappraisalbars(img, ui, barfillbrightness)

    except Exception as e:
        log.warning(f"readappraisalbarsdebug failed: {e}")
        return None
