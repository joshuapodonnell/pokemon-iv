import re
import json
import logging
from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps
import pytesseract

log = logging.getLogger(__name__)

LOOKUPPATH = Path(__file__).parent / "species_lookup.json"
if LOOKUPPATH.exists():
    with open(LOOKUPPATH) as f:
        SPECIESDB = dict(json.load(f))
else:
    SPECIESDB = {}
    log.warning("species_lookup.json not found — run build_species_lookup.py first")


ALLTYPES = [
    "Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting",
    "Poison", "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost",
    "Dragon", "Dark", "Steel", "Fairy",
]

def parse_types(raw):
    if not raw:
        return None, None

    cleaned = re.sub(r"[^A-Za-z/ ]", "", raw).strip().title()

    if "/" in cleaned:
        parts = [p.strip() for p in cleaned.split("/") if p.strip()]
        valid = [p for p in parts if p in ALLTYPES]
        if len(valid) >= 2:
            return valid[0], valid[1]
        if len(valid) == 1:
            return valid[0], None

    compact = re.sub(r"[^A-Za-z]", "", cleaned)

    if compact in ALLTYPES:
        return compact, None

    for t1 in sorted(ALLTYPES, key=len, reverse=True):
        if compact.startswith(t1):
            rest = compact[len(t1):]
            for t2 in sorted(ALLTYPES, key=len, reverse=True):
                if rest == t2:
                    return t1, t2

    return None, None

def ocr_type_region(img):
    w, h = img.size
    crop = img.resize((w * 4, h * 4), Image.Resampling.LANCZOS).convert("L")
    crop = ImageEnhance.Contrast(crop).enhance(2.0)

    raw = pytesseract.image_to_string(
        crop,
        config="--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz/"
    ).strip()

    raw = raw.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
    log.info(f"raw type_text: {raw!r}")
    return raw

VARIANT_TYPE_MAP = {
    ("Slowpoke",    "Poison"):          "Slowpoke (Galarian)",
    ("Slowbro",     "Poison"):          "Slowbro (Galarian)",
    ("Slowking",    "Poison"):          "Slowking (Galarian)",
    ("Meowth",      "Steel"):           "Meowth (Galarian)",
    ("Meowth",      "Dark"):            "Meowth (Alolan)",
    ("Persian",     "Dark"):            "Persian (Alolan)",
    ("Perrserker",  "Steel"):           "Perrserker",        # only exists as Galarian Meowth evo
    ("Farfetch'd",  "Fighting"):        "Farfetch'd (Galarian)",
    ("Sirfetch'd",  "Fighting"):        "Sirfetch'd",        # only Galarian evo, no ambiguity
    ("Weezing",     "Fairy"):           "Weezing (Galarian)",
    ("Ponyta",      "Psychic"):         "Ponyta (Galarian)",
    ("Rapidash",    "Fairy"):           "Rapidash (Galarian)",
    ("Voltorb",     "Grass"):           "Voltorb (Hisuian)",
    ("Electrode",   "Grass"):           "Electrode (Hisuian)",
    ("Growlithe",   "Rock"):            "Growlithe (Hisuian)",
    ("Arcanine",    "Rock"):            "Arcanine (Hisuian)",
    ("Typhlosion",  "Ghost"):           "Typhlosion (Hisuian)",
    ("Samurott",    "Dark"):            "Samurott (Hisuian)",
    ("Decidueye",   "Fighting"):        "Decidueye (Hisuian)",
    ("Qwilfish",    "Dark"):            "Qwilfish (Hisuian)",
    ("Overqwil",    "Dark"):            "Overqwil",
    ("Sneasel",     "Fighting"):        "Sneasel (Hisuian)",
    ("Sneasler",    "Fighting"):        "Sneasler",
    ("Avalugg",     "Rock"):            "Avalugg (Hisuian)",
    ("Zorua",       "Normal"):          "Zorua (Hisuian)",
    ("Zoroark",     "Normal"):          "Zoroark (Hisuian)",
    ("Braviary",    "Psychic"):         "Braviary (Hisuian)",
    ("Lilligant",   "Fighting"):        "Lilligant (Hisuian)",
    ("Goodra",      "Steel"):           "Goodra (Hisuian)",
    ("Sliggoo",     "Steel"):           "Sliggoo (Hisuian)",
    ("Basculin",    "Fighting"):        "Basculin (White-Striped)",
    ("Basculegion", "Ghost"):           "Basculegion",
    ("Diglett",     "Steel"):           "Diglett (Alolan)",
    ("Dugtrio",     "Steel"):           "Dugtrio (Alolan)",
    ("Geodude",     "Electric"):        "Geodude (Alolan)",
    ("Graveler",    "Electric"):        "Graveler (Alolan)",
    ("Golem",       "Electric"):        "Golem (Alolan)",
    ("Grimer",      "Dark"):            "Grimer (Alolan)",
    ("Muk",         "Dark"):            "Muk (Alolan)",
    ("Exeggutor",   "Dragon"):          "Exeggutor (Alolan)",
    ("Marowak",     "Ghost"):           "Marowak (Alolan)",
    ("Raichu",      "Psychic"):         "Raichu (Alolan)",
    ("Sandshrew",   "Ice"):             "Sandshrew (Alolan)",
    ("Sandslash",   "Ice"):             "Sandslash (Alolan)",
    ("Vulpix",      "Ice"):             "Vulpix (Alolan)",
    ("Ninetales",   "Fairy"):           "Ninetales (Alolan)",
    ("Zigzagoon",   "Dark"):            "Zigzagoon (Galarian)",
}
# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def ocrregion(img: Image.Image, upscale: bool = False) -> str:
    """Run Tesseract OCR on a PIL image crop. Optionally upscale for small regions."""
    if upscale:
        w, h = img.size
        img = img.convert("RGB").resize((w, h), Image.Resampling.LANCZOS)
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

def normalize_species_name(name: str) -> str:
    if not name:
        return name

    text = " ".join(name.replace("\n", " ").split()).strip()

    special_patterns = [
        (r".*\bSinistea\b.*", "Sinistea"),
        (r".*\bPolteageist\b.*", "Polteageist"),
        (r".*\bSinistcha\b.*", "Sinistcha"),
        (r".*\bPoltchageist\b.*", "Poltchageist"),
        (r".*\bPumpkaboo\b.*", "Pumpkaboo"),
        (r".*\bGiratina\b.*Origin.*", "GiratinaOrigin Forme"),
        (r".*\bGiratina\b.*Altered.*", "GiratinaAltered Forme"),
    ]

    for pattern, normalized in special_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return normalized

    for known in SPECIESDB:
        if re.search(rf"\b{re.escape(known)}\b", text, re.IGNORECASE):
            return known

    return text

# ---------------------------------------------------------------------------
# Individual field parsers
# ---------------------------------------------------------------------------

def parsecp(text: str) -> int:
    """Extract CP integer from OCR text like 'CP 310', '310', or slash-misread values."""
    if not text:
        return 0

    cleaned = text.strip()

    # Common OCR error: slash or backslash instead of 7
    cleaned = cleaned.replace("/", "7").replace("\\", "7")

    m = re.search(r"(\d{1,4})", cleaned)
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


def parse_caught_date(ocr_text: str) -> str | None:
    """Extract catch date from 'This X was caught on M/D/YYYY' string."""
    match = re.search(r'caught on (\d{1,2}/\d{1,2}/\d{4})', ocr_text)
    if match:
        return match.group(1)  # e.g. "4/18/2026"
    return None


# ---------------------------------------------------------------------------
# Pokémon name OCR  (NEW)
# ---------------------------------------------------------------------------

def ocrnameregion(img, ui):
    region = ui.get("name_region")
    if not region:
        return ""

    crop = getrelativeregion(img, region)
    W, H = crop.size
    crop = crop.resize((W * 3, H * 3), Image.Resampling.LANCZOS)

    crop = crop.convert("L")
    from PIL import ImageEnhance
    crop = ImageEnhance.Contrast(crop).enhance(2.0)

    text = pytesseract.image_to_string(crop, config="--psm 6 --oem 3").strip()
    text = text.replace("\n", " ")

    m = re.search(r"\bThis\s+(.+?)\s+was\b", text, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        log.debug(f"ocrnameregion: extracted {name!r} from: {text!r}")
        return name

    log.warning(f"ocrnameregion: pattern not found in: {text!r}")
    return ""


def resolvespeciesname(img: Image.Image, ui: dict, cp: int, type_text: str) -> str:
    ocr_name = ocrnameregion(img, ui)
    if not ocr_name:
        return "Unknown"

    ocr_lower = ocr_name.lower()
    for known in SPECIESDB:
        if known.lower() == ocr_lower:
            canonical = known
            break
    else:
        matches = [k for k in SPECIESDB if k.lower().startswith(ocr_lower)]
        if len(matches) == 1:
            canonical = matches[0]
        elif matches:
            canonical = min(matches, key=len)
        else:
            canonical = normalize_species_name(ocr_name)

    type1, type2 = parse_types(type_text)


    for type_name in (type1, type2):
        if not type_name:
            continue
        variant = VARIANT_TYPE_MAP.get((canonical, type_name))
        if variant:
            return variant

    return canonical



# ---------------------------------------------------------------------------
# IV bar parsing  (FIXED)
# ---------------------------------------------------------------------------

def readappraisalbars(img: Image.Image, ui: dict, barfillbrightness: float, lines: int = 2) -> tuple | None:
    """Read ATK/DEF/STA IVs (0–15) from a full appraisal screenshot dynamically."""
    try:
        W, H = img.size
        bar_segments = ui.get("bar_segments", 15)
        x_start = ui.get("bar_x_start", 0.141)
        x_end = ui.get("bar_x_end", 0.457)

        # Dynamic parameter retrieval based on line count
        if lines == 2:
            atk_y = ui.get("atk_bar_y", 0.774)
            def_y = ui.get("def_bar_y", 0.815)
            sta_y = ui.get("sta_bar_y", 0.857)
        else:
            atk_y = ui.get(f"atk_bar_y_{lines}lines", ui.get("atk_bar_y", 0.774))
            def_y = ui.get(f"def_bar_y_{lines}lines", ui.get("def_bar_y", 0.815))
            sta_y = ui.get(f"sta_bar_y_{lines}lines", ui.get("sta_bar_y", 0.857))

        bar_ys = {
            "atk": atk_y,
            "def": def_y,
            "sta": sta_y,
        }

        results = {}
        for stat, yrel in bar_ys.items():
            filled = 0
            py = int(yrel * H)
            for seg in range(bar_segments):
                xfrac = x_start + (x_end - x_start) * (seg + 0.5) / bar_segments
                px = int(xfrac * W)
                votes = 0
                for dy in (-3, 0, 3):
                    sample_y = max(0, min(py + dy, H - 1))
                    pixel = img.getpixel((px, sample_y))
                    r, g, b = pixel[0], pixel[1], pixel[2]
                    brightness = (r + g + b) / 3
                    if brightness >= barfillbrightness:
                        votes += 1
                if votes >= 2:
                    filled += 1
            results[stat] = filled

        log.debug(f"Bar parse ATK={results['atk']} DEF={results['def']} STA={results['sta']}")
        return results["atk"], results["def"], results["sta"]

    except Exception as e:
        log.warning(f"readappraisalbars failed: {e}")
        return None


def readappraisalbarsdebug(img: Image.Image, ui: dict, barfillbrightness: float, lines: int = 2) -> tuple | None:
    """Debug version — saves an annotated bar strip to debugbars.png, then delegates."""
    try:
        W, H = img.size
        x_start = ui.get("bar_x_start", 0.141)
        x_end = ui.get("bar_x_end", 0.457)

        # Dynamic parameter retrieval based on line count
        if lines == 2:
            atk_bar_y = ui.get("atk_bar_y", 0.773)
            sta_bar_y = ui.get("sta_bar_y", 0.857)
            def_bar_y = ui.get("def_bar_y", 0.816)
        else:
            atk_bar_y = ui.get(f"atk_bar_y_{lines}lines", ui.get("atk_bar_y", 0.773))
            sta_bar_y = ui.get(f"sta_bar_y_{lines}lines", ui.get("sta_bar_y", 0.857))
            def_bar_y = ui.get(f"def_bar_y_{lines}lines", ui.get("def_bar_y", 0.816))

        x1 = int(x_start * W)
        x2 = int(x_end * W)
        # Pad the crop area slightly so we can see the context around the bars
        y1 = int((atk_bar_y - 0.035) * H)
        y2 = int((sta_bar_y + 0.035) * H)
        barstrip = img.crop((x1, y1, x2, y2))

        # Save the exact strip we are analyzing for debug purposes
        sw, sh = barstrip.size
        barstrip = barstrip.resize((sw * 3, sh * 3), Image.Resampling.LANCZOS)

        # Draw on the strip where the horizontal line checks are occurring
        from PIL import ImageDraw
        draw = ImageDraw.Draw(barstrip)
        for stat_y in [atk_bar_y, def_bar_y, sta_bar_y]:
            # Convert the absolute yrel to the relative coordinate inside the cropped strip
            rel_y = (stat_y * H - y1) * 3
            draw.line((0, rel_y, sw * 3, rel_y), fill="cyan", width=2)

        barstrip.save(f"screenshots/debugbars_lines{lines}.png")

        W2, H2 = img.size
        for stat, (yrel, color) in [
            ("ATK", (atk_bar_y, "orange")),
            ("DEF", (def_bar_y, "pink")),
            ("STA", (sta_bar_y, "orange")),
        ]:
            py = int(yrel * H2)
            sample_px = []
            for seg in range(ui.get("bar_segments", 15)):
                xfrac = x_start + (x_end - x_start) * (seg + 0.5) / ui.get("bar_segments", 15)
                px = int(xfrac * W2)
                r, g, b = img.getpixel((px, py))[:3]
                sample_px.append(f"({r},{g},{b})")
            log.debug(f"  {stat} y={py}: {' '.join(sample_px)}")
        log.info(f"Debug bar image saved to screenshots/debugbars_lines{lines}.png")

        return readappraisalbars(img, ui, barfillbrightness, lines)

    except Exception as e:
        log.warning(f"readappraisalbarsdebug failed: {e}")
        return None

def parseivbars(barimg: Image.Image, debug: bool = False):
    W, H = barimg.size

    Y_ATK = 0.155
    Y_DEF = 0.483
    Y_HP = 0.816

    def _classify(r, g, b):
        if r > 195 and 100 < g < 215 and b < 145 and r > g + 15:
            return 'filled'
        if r > 170 and g < 165 and b < 165 and r > g + 30 and r > b + 30:
            return 'filled'
        if 190 < r < 250 and 190 < g < 250 and 190 < b < 250 \
                and abs(r - g) < 18 and abs(g - b) < 18:
            return 'empty'
        return 'outside'

    def _count_at_row(y_rel):
        y = int(y_rel * H)

        col = []
        for x in range(W):
            votes = {'filled': 0, 'empty': 0, 'outside': 0}
            for dy in (-3, 0, 3):
                sy = max(0, min(y + dy, H - 1))
                r, g, b = barimg.getpixel((x, sy))[:3]
                votes[_classify(r, g, b)] += 1
            col.append(max(votes, key=votes.get))

        groups = []
        in_group = False
        gstart = 0
        outside_run = 0
        for x, cls in enumerate(col):
            if cls == 'outside':
                outside_run += 1
                if in_group and outside_run >= 2:
                    groups.append((gstart, x - outside_run))
                    in_group = False
            else:
                if not in_group:
                    gstart = x
                    in_group = True
                outside_run = 0
        if in_group:
            groups.append((gstart, len(col) - 1))

        if not groups:
            return 0

        gw = groups[0][1] - groups[0][0] + 1

        final = []
        for gs, ge in groups:
            w = ge - gs + 1
            if w > gw * 1.4:
                x = gs
                while x <= ge:
                    end = min(x + gw - 1, ge)
                    final.append((x, end))
                    x = end + 1
                    while x <= ge and col[x] == 'outside':
                        x += 1
            else:
                final.append((gs, ge))

        total = 0
        for gs, ge in final[:3]:
            chunk = col[gs:ge + 1]
            fp = sum(1 for c in chunk if c == 'filled')
            frac = fp / len(chunk) if chunk else 0
            total += round(frac * 5)
        return total

    try:
        atk = _count_at_row(Y_ATK)
        def_ = _count_at_row(Y_DEF)
        sta = _count_at_row(Y_HP)
        if debug:
            log.debug(f"Bar scan ATK={atk} DEF={def_} STA={sta}")
        return atk, def_, sta
    except Exception as e:
        log.warning(f"parseivbars failed: {e}")
        return None