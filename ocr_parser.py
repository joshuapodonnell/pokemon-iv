import re
import json
import logging
import os
from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps, ImageDraw
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
    # =========================================================================
    # Alolan forms (Gen 7)
    # =========================================================================
    ("Diglett",     "Steel"):     "Diglett (Alolan)",
    ("Dugtrio",     "Steel"):     "Dugtrio (Alolan)",
    ("Exeggutor",   "Dragon"):    "Exeggutor (Alolan)",
    ("Geodude",     "Electric"):  "Geodude (Alolan)",
    ("Golem",       "Electric"):  "Golem (Alolan)",
    ("Graveler",    "Electric"):  "Graveler (Alolan)",
    ("Grimer",      "Dark"):      "Grimer (Alolan)",
    ("Marowak",     "Ghost"):     "Marowak (Alolan)",
    ("Meowth",      "Dark"):      "Meowth (Alolan)",
    ("Muk",         "Dark"):      "Muk (Alolan)",
    ("Ninetales",   "Fairy"):     "Ninetales (Alolan)",
    ("Persian",     "Dark"):      "Persian (Alolan)",
    ("Raichu",      "Psychic"):   "Raichu (Alolan)",
    ("Rattata",     "Dark"):      "Rattata (Alolan)",
    ("Raticate",    "Dark"):      "Raticate (Alolan)",
    ("Sandshrew",   "Ice"):       "Sandshrew (Alolan)",
    ("Sandslash",   "Ice"):       "Sandslash (Alolan)",
    ("Vulpix",      "Ice"):       "Vulpix (Alolan)",

    # =========================================================================
    # Galarian forms (Gen 8)
    # =========================================================================
    ("Corsola",     "Ghost"):     "Corsola (Galarian)",
    ("Darmanitan",  "Ice"):       "Darmanitan (Galarian)",
    ("Darumaka",    "Ice"):       "Darumaka (Galarian)",
    ("Farfetch'd",  "Fighting"):  "Farfetch'd (Galarian)",
    ("Linoone",     "Dark"):      "Linoone (Galarian)",
    ("Meowth",      "Steel"):     "Meowth (Galarian)",
    ("Mr. Mime",    "Ice"):       "Mr. Mime (Galarian)",
    ("Ponyta",      "Psychic"):   "Ponyta (Galarian)",
    ("Rapidash",    "Fairy"):     "Rapidash (Galarian)",
    ("Slowbro",     "Poison"):    "Slowbro (Galarian)",
    ("Slowking",    "Poison"):    "Slowking (Galarian)",
    ("Slowpoke",    "Psychic"):   "Slowpoke (Galarian)",
    ("Stunfisk",    "Steel"):     "Stunfisk (Galarian)",   # keyed on Steel, not Ground -- shared with regular form
    ("Weezing",     "Fairy"):     "Weezing (Galarian)",
    ("Yamask",      "Ground"):    "Yamask (Galarian)",
    ("Zigzagoon",   "Dark"):      "Zigzagoon (Galarian)",

    # Galarian-only evolutions (unambiguous names -- kept for consistency/validation)
    ("Cursola",     "Ghost"):     "Cursola",       # only Galarian Corsola evo
    ("Mr. Rime",    "Ice"):       "Mr. Rime",      # only Galarian Mr. Mime evo
    ("Obstagoon",   "Dark"):      "Obstagoon",     # only Galarian Linoone evo
    ("Perrserker",  "Steel"):     "Perrserker",    # only Galarian Meowth evo
    ("Runerigus",   "Ground"):    "Runerigus",     # only Galarian Yamask evo
    ("Sirfetch'd",  "Fighting"):  "Sirfetch'd",    # only Galarian Farfetch'd evo

    # =========================================================================
    # Hisuian forms (Legends: Arceus / Gen 8 region)
    # =========================================================================
    ("Arcanine",    "Rock"):      "Arcanine (Hisuian)",
    ("Avalugg",     "Rock"):      "Avalugg (Hisuian)",
    ("Basculin",    "Fighting"):  "Basculin (White-Striped)",
    ("Braviary",    "Psychic"):   "Braviary (Hisuian)",
    ("Decidueye",   "Fighting"):  "Decidueye (Hisuian)",
    ("Electrode",   "Grass"):     "Electrode (Hisuian)",
    ("Goodra",      "Steel"):     "Goodra (Hisuian)",
    ("Growlithe",   "Rock"):      "Growlithe (Hisuian)",
    ("Lilligant",   "Fighting"):  "Lilligant (Hisuian)",
    ("Qwilfish",    "Dark"):      "Qwilfish (Hisuian)",
    ("Samurott",    "Dark"):      "Samurott (Hisuian)",
    ("Sliggoo",     "Steel"):     "Sliggoo (Hisuian)",
    ("Sneasel",     "Fighting"):  "Sneasel (Hisuian)",
    ("Typhlosion",  "Ghost"):     "Typhlosion (Hisuian)",
    ("Voltorb",     "Grass"):     "Voltorb (Hisuian)",
    ("Zorua",       "Normal"):    "Zorua (Hisuian)",
    ("Zoroark",     "Normal"):    "Zoroark (Hisuian)",

    # Hisuian-only evolutions (unambiguous names -- kept for consistency/validation)
    ("Basculegion", "Ghost"):     "Basculegion",   # only Basculin (White-Striped) evo
    ("Overqwil",    "Dark"):      "Overqwil",      # only Hisuian Qwilfish evo
    ("Sneasler",    "Fighting"):  "Sneasler",      # only Hisuian Sneasel evo

    # =========================================================================
    # Paldean forms (Gen 9)
    # =========================================================================
    ("Wooper",      "Poison"):    "Wooper (Paldean)",   # keyed on Poison, not Ground -- shared with regular form

    # Paldean-only evolutions (unambiguous names -- kept for consistency/validation)
    ("Clodsire",    "Poison"):    "Clodsire",      # only Paldean Wooper evo
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

def is_lucky_pokemon(img: Image.Image, ui: dict) -> bool:
    """
    Cheap layout detector. OCR only the small label region where
    'Lucky Pokemon' is displayed.
    """
    region = ui.get("lucky_label_region")
    if not region:
        return False

    crop = getrelativeregion(img, region)
    w, h = crop.size
    crop = crop.resize((w * 3, h * 3), Image.Resampling.LANCZOS).convert("L")
    crop = ImageEnhance.Contrast(crop).enhance(2.0)

    text = pytesseract.image_to_string(
        crop,
        config=(
            "--psm 7 --oem 3 "
            "-c tessedit_char_whitelist="
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz "
        ),
    ).strip().lower()

    is_lucky = "lucky" in text
    log.debug("Lucky detection: raw=%r is_lucky=%s", text, is_lucky)
    return is_lucky

def ocr_hp_region(img: Image.Image, ui: dict) -> tuple[int, bool, str]:
    """
    Pick normal or Lucky HP layout, OCR it, and return:
    (parsed_hp, is_lucky, raw_ocr_text).
    """
    is_lucky = is_lucky_pokemon(img, ui)

    if is_lucky:
        region = ui.get("hp_region_lucky", ui.get("hp_region"))
    else:
        region = ui.get("hp_region")

    if not region:
        log.warning("No HP region configured")
        return 0, is_lucky, ""

    crop = getrelativeregion(img, region)
    w, h = crop.size

    # HP text is small; enlarge it before OCR.
    crop = crop.resize((w * 4, h * 4), Image.Resampling.LANCZOS).convert("L")
    crop = ImageEnhance.Contrast(crop).enhance(2.5)

    raw = pytesseract.image_to_string(
        crop,
        config=(
            "--psm 7 --oem 3 "
            "-c tessedit_char_whitelist=0123456789HP/ "
        ),
    ).strip()

    hp = parsehp(raw)
    log.info(
        "HP OCR: layout=%s raw=%r parsed=%s",
        "lucky" if is_lucky else "normal",
        raw,
        hp,
    )
    return hp, is_lucky, raw


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
    """Extract maximum HP from OCR text such as '31 / 47 HP'."""
    cleaned = text.replace(",", "")

    m = re.search(r"\d{1,5}\s*/\s*(\d{1,5})", cleaned)
    if m:
        return int(m.group(1))

    # Keep this only as an OCR fallback.
    m = re.search(r"(\d{1,5})", cleaned)
    return int(m.group(1)) if m else 0


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

def _classify_pixel(r, g, b):
    if r > 195 and 100 < g < 215 and b < 145 and r > g + 15:
        return 'filled'
    if r > 170 and g < 165 and b < 165 and r > g + 30 and r > b + 30:
        return 'filled'
    if 190 < r < 250 and 190 < g < 250 and 190 < b < 250 \
            and abs(r - g) < 18 and abs(g - b) < 18:
        return 'empty'
    return 'outside'


def _classify_row(barimg, y_rel, W, H):
    y = int(y_rel * H)
    col = []
    for x in range(W):
        votes = {'filled': 0, 'empty': 0, 'outside': 0}
        for dy in (-3, 0, 3):
            sy = max(0, min(y + dy, H - 1))
            r, g, b = barimg.getpixel((x, sy))[:3]
            votes[_classify_pixel(r, g, b)] += 1
        col.append(max(votes, key=votes.get))
    return y, col


def _group_columns(col):
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
        return []

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
    return final


def _score_row(barimg, y_rel, W, H):
    y, col = _classify_row(barimg, y_rel, W, H)
    groups = _group_columns(col)

    total = 0
    seg_scores = []
    for gs, ge in groups[:3]:
        chunk = col[gs:ge + 1]
        fp = sum(1 for c in chunk if c == 'filled')
        frac = fp / len(chunk) if chunk else 0
        seg_val = round(frac * 5)
        seg_scores.append((gs, ge, frac, seg_val))
        total += seg_val
    return y, col, groups, seg_scores, total

def parseivbars(barimg: Image.Image, debug: bool = False):
    W, H = barimg.size
    Y_ATK, Y_DEF, Y_HP = 0.164, 0.483, 0.803
    try:
        *_, atk = _score_row(barimg, Y_ATK, W, H)
        *_, def_ = _score_row(barimg, Y_DEF, W, H)
        *_, sta = _score_row(barimg, Y_HP, W, H)
        if debug:
            log.debug(f"Bar scan ATK={atk} DEF={def_} STA={sta}")
        return atk, def_, sta
    except Exception as e:
        log.warning(f"parseivbars failed: {e}")
        return None

def parseivbarsdebug(barimg: Image.Image, debug_path: str = "screenshots/debugivbars.png"):
    """Debug version of parseivbars — saves an annotated strip showing per-column
    classification (filled/empty/outside), detected segment groups, and scan rows."""
    W, H = barimg.size
    Y_ATK, Y_DEF, Y_HP = 0.164, 0.483, 0.803

    scale = 4
    annotated = barimg.resize((W * scale, H * scale), Image.Resampling.LANCZOS).convert("RGB")
    draw = ImageDraw.Draw(annotated)

    color_map = {
        'filled':  (34, 197, 94),    # green
        'empty':   (148, 163, 184),  # gray
        'outside': (239, 68, 68),    # red
    }

    results = {}
    try:
        for label, y_rel in [("ATK", Y_ATK), ("DEF", Y_DEF), ("STA", Y_HP)]:
            y, col, groups, seg_scores, total = _score_row(barimg, y_rel, W, H)
            results[label] = total
            sy = y * scale

            # Strip of classification color just above the scan line
            for x, cls in enumerate(col):
                draw.line(
                    (x * scale, sy - 4, x * scale + scale, sy - 4),
                    fill=color_map[cls], width=6,
                )

            # Cyan scan line at the exact row being sampled
            draw.line((0, sy, W * scale, sy), fill=(6, 182, 212), width=2)

            # Yellow boxes around each detected segment with its computed value
            for gs, ge, frac, seg_val in seg_scores:
                box = (gs * scale, sy - 14, (ge + 1) * scale, sy + 14)
                draw.rectangle(box, outline=(255, 255, 0), width=2)
                draw.text((gs * scale, sy + 16), str(seg_val), fill=(255, 255, 0))

            draw.text((4, sy - 26), f"{label}={total}", fill=(255, 255, 255))

        os.makedirs(os.path.dirname(debug_path) or ".", exist_ok=True)
        annotated.save(debug_path)
        log.info(f"Debug IV-bar image saved to {debug_path}")

    except Exception as e:
        log.warning(f"parseivbarsdebug failed: {e}")

    return results.get("ATK"), results.get("DEF"), results.get("STA")