"""
vision_agent.py
---------------
MLX-VLM-based vision + error-correction agent for the Pokémon IV Cataloger.

Responsibilities
----------------
1. analyze_base_screen(img)      → locate CP / HP / type / weight / height regions
                                   and return corrected text for each field.
2. analyze_appraisal_screen(img) → locate the Pokémon name label and the three
                                   IV bars; return bar bounding boxes + estimated
                                   fill values (0-15).
3. correct_ocr(fields, img)      → given a dict of already-extracted text fields
                                   that contain suspicious values, ask the VLM to
                                   correct only the flagged ones.
4. recover_failed_parse(base_img, appraisal_img, partial)
                                 → last-resort structured recovery when the normal
                                   pipeline could not produce a valid result.

Design contract
---------------
* Every public method returns a plain dict with a top-level "confidence" key
  (0.0 – 1.0) and a "source" key set to "vlm".
* The caller MUST validate numeric fields with the same rules used on the
  normal pipeline output before trusting the result.
* The agent NEVER decides KEEP / TRANSFER / REVIEW – that stays in evaluator.py.
* All VLM calls are guarded by a try/except so a model failure never crashes
  the bot; methods return an empty dict with confidence=0.0 on failure.

Local model (M1 MacBook Air)
----------------------------
Install:
    pip install -U mlx-vlm

Recommended models for 8 GB unified memory:
    mlx-community/Qwen2-VL-2B-Instruct-4bit   ← default, fast, fits in ~3 GB
    mlx-community/Qwen2-VL-7B-Instruct-4bit   ← better accuracy, needs ~5 GB

Set the model via env var:
    export POGO_VLM_MODEL=mlx-community/Qwen2-VL-2B-Instruct-4bit

To disable local fallback entirely (remote-only mode, degrades to OCR/review):
    export POGO_DISABLE_LOCAL_VLM=1

Or edit MODEL_PATH below.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import requests
import threading
from typing import Optional

from PIL import Image

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WINDOWS_PC_IP = "192.168.1.229"
API_PORT = "11434"
API_URL = f"http://{WINDOWS_PC_IP}:{API_PORT}/v1/chat/completions"
VLM_MODEL = "qwen2.5vl:32b"

CONFIDENCE_THRESHOLD: float = 0.75
MAX_TOKENS: int = 400

# Set POGO_DISABLE_LOCAL_VLM=1 to skip local fallback entirely and degrade to
# OCR/review when remote is unreachable. Local is ON by default.
_DISABLE_LOCAL_VLM: bool = os.environ.get("POGO_DISABLE_LOCAL_VLM", "0") == "1"

# ---------------------------------------------------------------------------
# Local MLX-VLM fallback (M1 Mac)
# ---------------------------------------------------------------------------

LOCAL_MODEL_PATH = os.environ.get(
    "POGO_VLM_MODEL",
    "mlx-community/Qwen2-VL-2B-Instruct-4bit"
)

_local_model = None
_local_processor = None
_local_config = None          # cached once in _load_local_model(); reused every call
_local_model_lock = threading.Lock()
_local_available: bool | None = None   # None = untested, True/False = known
_local_broken: bool = False            # set True after first inference failure this session


def _load_local_model() -> bool:
    """Load and cache the local MLX model + config. Returns True on success."""
    global _local_model, _local_processor, _local_config, _local_available
    with _local_model_lock:
        if _local_model is not None:
            return True
        try:
            from mlx_vlm import load
            from mlx_vlm.utils import load_config
            log.info(f"[VLM-local] Loading {LOCAL_MODEL_PATH} …")
            _local_model, _local_processor = load(LOCAL_MODEL_PATH)
            _local_config = load_config(LOCAL_MODEL_PATH)   # cached here; never called again
            _local_available = True
            log.info("[VLM-local] Model ready.")
            return True
        except Exception as e:
            log.warning(f"[VLM-local] Could not load local model: {e}")
            _local_available = False
            return False


def _call_vlm_local(prompt: str, images: list) -> str:
    """
    Run inference on the local MLX model.

    Uses the module-level _local_config cache loaded by _load_local_model()
    so load_config() is never called more than once per session.
    """
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template
    import tempfile

    img = images[0]

    # mlx-vlm generate() requires a file path, not a PIL Image.
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        img.save(tmp, format="PNG")
        tmp_path = tmp.name

    try:
        if _local_config is None:
            raise RuntimeError("Local VLM config not initialised — _load_local_model() was not called")

        formatted = apply_chat_template(
            _local_processor,
            _local_config,       # ← reuse cached config, no extra load_config() call
            prompt,
            num_images=1,
        )

        output = generate(
            _local_model,
            _local_processor,
            formatted,
            [tmp_path],
            verbose=False,
            max_tokens=MAX_TOKENS,
            temperature=0.0,
        )
        return output.strip()
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Remote backend
# ---------------------------------------------------------------------------

REMOTE_CONNECT_TIMEOUT = 3     # seconds — keep short so failures are fast
REMOTE_READ_TIMEOUT    = 180   # seconds — model inference can be slow
REMOTE_WARMUP_TIMEOUT  = 180   # seconds — 32B needs time to load into VRAM

_remote_available: bool | None = None   # None = untested


def _call_vlm_remote(prompt: str, images: list) -> str:
    """Send a vision request to the Windows PC Ollama endpoint."""
    img = images[0]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    payload = {
        "model": VLM_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
            ]
        }],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0,
    }

    response = requests.post(
        API_URL,
        json=payload,
        timeout=(REMOTE_CONNECT_TIMEOUT, REMOTE_READ_TIMEOUT),
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Unified VLM dispatcher with circuit breaker
# ---------------------------------------------------------------------------

def call_vlm(prompt: str, images: list, max_tokens: int = MAX_TOKENS) -> str:
    """
    Try the remote Windows PC first.
    On any connection error, fall back to the local MLX model (unless disabled).

    Circuit breaker: if local inference throws an exception, _local_broken is
    set to True and all subsequent calls skip local entirely, raising
    RuntimeError so _safe_call() can return confidence=0.0 gracefully.

    Raises RuntimeError only when BOTH backends are unavailable/broken.
    """
    global _remote_available, _local_broken

    # ── 1. Remote ─────────────────────────────────────────────────────────
    if _remote_available is not False:
        try:
            result = _call_vlm_remote(prompt, images)
            if _remote_available is not True:
                log.info("[VLM] Remote PC is reachable — using remote inference.")
            _remote_available = True
            return result

        except requests.exceptions.ConnectionError:
            log.warning("[VLM] Remote PC unreachable (connection refused). "
                        "Switching to local MLX model for this session.")
            _remote_available = False

        except requests.exceptions.Timeout:
            log.warning(f"[VLM] Remote PC did not respond within "
                        f"{REMOTE_CONNECT_TIMEOUT}s connect / "
                        f"{REMOTE_READ_TIMEOUT}s read. "
                        "Switching to local MLX model for this session.")
            _remote_available = False

        except requests.exceptions.RequestException as e:
            log.warning(f"[VLM] Remote request failed ({e}). "
                        "Trying local MLX model.")
            _remote_available = False

    # ── 2. Local MLX fallback ─────────────────────────────────────────────
    if _DISABLE_LOCAL_VLM:
        raise RuntimeError(
            "VLM unavailable: remote PC is down and local fallback is disabled "
            "(POGO_DISABLE_LOCAL_VLM=1). Degrading to OCR/review."
        )

    if _local_broken:
        raise RuntimeError(
            "VLM unavailable: remote PC is down and local MLX model is disabled "
            "for this session after a previous inference failure."
        )

    if _load_local_model():
        try:
            log.debug("[VLM-local] Running local inference.")
            return _call_vlm_local(prompt, images)
        except Exception as e:
            # Circuit breaker: disable local for the rest of this session.
            _local_broken = True
            log.warning(
                f"[VLM-local] Inference failed ({e}). "
                "Disabling local VLM for the remainder of this session — "
                "subsequent failures will degrade to OCR/review."
            )
            raise RuntimeError(
                f"Local VLM inference failed; disabled for this session: {e}"
            ) from e

    raise RuntimeError(
        "VLM unavailable: remote PC is down and local MLX model failed to load."
    )


def reset_remote_status() -> None:
    """Allow the next VLM call to re-probe the remote PC (called between passes)."""
    global _remote_available
    _remote_available = None
    log.info("[VLM] Remote PC status reset — will probe on next call.")


def reset_local_circuit_breaker() -> None:
    """
    Manually re-enable local inference after it was tripped by the circuit
    breaker. Only use this if you have fixed the underlying MLX issue.
    """
    global _local_broken
    _local_broken = False
    log.info("[VLM-local] Circuit breaker reset — local inference re-enabled.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pil_to_list(img: Image.Image) -> list:
    return [img]


def _parse_json_response(raw: str) -> dict:
    """Extract the first JSON object from the VLM's text output."""
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        log.warning(f"VLM returned no JSON: {raw[:120]!r}")
        return {}
    try:
        return json.loads(m.group())
    except json.JSONDecodeError as e:
        log.warning(f"VLM JSON parse error: {e}  raw={raw[:120]!r}")
        return {}


def _safe_call(prompt: str, images: list, max_tokens: int = MAX_TOKENS) -> dict:
    """Wrapper that catches all exceptions and returns an empty failure dict."""
    try:
        raw = call_vlm(prompt, images, max_tokens)
        result = _parse_json_response(raw)
        result.setdefault("source", "vlm")
        result.setdefault("confidence", 0.0)
        return result
    except Exception as e:
        log.warning(f"VisionAgent VLM call failed: {e}")
        return {"source": "vlm", "confidence": 0.0, "error": str(e)}


# ---------------------------------------------------------------------------
# Image crop helpers
# ---------------------------------------------------------------------------

def crop_for_vlm(img: Image.Image) -> Image.Image:
    w, h = img.size
    return img.crop((0, int(h * 0.44), w, int(h * 0.65)))


def _crop_cp_region(img: Image.Image) -> Image.Image:
    """CP header area, upscaled 2× for digit clarity."""
    w, h = img.size
    crop = img.crop((0, 0, w, int(h * 0.22)))
    return crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)


def _crop_hp_region(img: Image.Image) -> Image.Image:
    w, h = img.size
    return img.crop((0, int(h * 0.40), w, int(h * 0.52)))


def _crop_type_region(img: Image.Image) -> Image.Image:
    w, h = img.size
    return img.crop((0, int(h * 0.52), w, int(h * 0.65)))


def _crop_candy_region(img: Image.Image) -> Image.Image:
    w, h = img.size
    return img.crop((0, int(h * 0.65), w, int(h * 0.78)))


VALID_TYPES = {
    "normal", "fire", "water", "electric", "grass", "ice", "fighting",
    "poison", "ground", "flying", "psychic", "bug", "rock", "ghost",
    "dragon", "dark", "steel", "fairy"
}


def _validate_type(text: str) -> str:
    return text if text.lower() in VALID_TYPES else ""


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def _parse_qa_response(raw: str) -> dict:
    patterns = {
        "cp":     r"CP:\s*(\d{2,4})",
        "hp":     r"HP:\s*(\d+)",
        "type1":  r"TYPE1:\s*(\w+)",
        "type2":  r"TYPE2:\s*(\w+)",
        "weight": r"WEIGHT:\s*([\d.]+\s*kg)",
        "height": r"HEIGHT:\s*([\d.]+\s*m)",
    }
    result = {"screen_type": "base_screen"}
    found = 0
    for key, pattern in patterns.items():
        m = re.search(pattern, raw, re.IGNORECASE)
        if m:
            result[key] = {"text": m.group(1).strip(), "confidence": 0.9}
            found += 1
        else:
            result[key] = {"text": "", "confidence": 0.0}
    result["confidence"] = 0.9 if found >= 5 else round(found / 6, 2)
    return result


def _parse_candy_response(raw: str) -> dict:
    patterns = {
        "candy":         r"CANDY:\s*([\d,]+)",
        "candy_xl":      r"CANDY_XL:\s*([\d,]+)",
        "candy_species": r"CANDY_SPECIES:\s*(.+)",
    }
    result = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, raw, re.IGNORECASE)
        if m:
            text = m.group(1).strip()
            if key in ("candy", "candy_xl"):
                text = text.replace(",", "")
            result[key] = {"text": text, "confidence": 0.9}
        else:
            result[key] = {"text": "", "confidence": 0.0}
    return result


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_BASE_SCREEN_PROMPT = """Look at this Pokémon GO screenshot and answer these questions.
Read the EXACT text visible on screen for each answer.

Layout reference:
- CP number is at the very top after the letters "CP"
- HP is shown as "X / Y HP" — the text literally contains "/ Y HP". Give only X (the first number before the slash)
- Weight is on the LEFT below the type badges, labeled "WEIGHT", ends in "kg"
- Types are in the MIDDLE between weight and height — read the text words, not icons
- Height is on the RIGHT below the type badges, labeled "HEIGHT", ends in "m"

Answer in this exact format:
CP: <number>
HP: <number>
TYPE1: <word>
TYPE2: <word or none>
WEIGHT: <number> kg
HEIGHT: <number> m"""

_APPRAISAL_SCREEN_PROMPT = """You are analyzing a Pokémon GO appraisal screen on an iPhone.
The appraisal overlay shows the Pokémon's name label at the bottom and three
coloured stat bars (Attack, Defense, HP/Stamina) showing IV values 0-15.

Return ONLY a single JSON object:

{
  "screen_type": "appraisal",
  "name": {
    "text": "<species name>",
    "bbox_rel": [x1_frac, y1_frac, x2_frac, y2_frac],
    "confidence": 0.0
  },
  "bars": {
    "attack":  {"value": 0, "bbox_rel": [x1, y1, x2, y2], "confidence": 0.0},
    "defense": {"value": 0, "bbox_rel": [x1, y1, x2, y2], "confidence": 0.0},
    "stamina": {"value": 0, "bbox_rel": [x1, y1, x2, y2], "confidence": 0.0}
  },
  "confidence": 0.0
}

Rules:
- bbox_rel values are fractions of the image width/height (0.0 – 1.0).
- bar value is an integer 0-15 (count of filled orange/pink segments).
- Overall "confidence" is the minimum of individual confidences.
- Return JSON only."""

_OCR_CORRECTION_PROMPT = """You are correcting OCR extraction errors from a Pokémon GO screenshot.
The following fields were extracted by Tesseract and may contain errors:

{fields_json}

Looking at the image, correct only the fields that appear wrong.
Do NOT change values that look correct.

Return ONLY a single JSON object with the same keys, each value being:
  {{"text": "<corrected text>", "confidence": 0.0, "changed": true/false}}

Overall structure:
{{
  "cp":     {{"text": "", "confidence": 0.0, "changed": false}},
  "hp":     {{"text": "", "confidence": 0.0, "changed": false}},
  "type1":  {{"text": "", "confidence": 0.0, "changed": false}},
  "type2":  {{"text": "", "confidence": 0.0, "changed": false}},
  "weight": {{"text": "", "confidence": 0.0, "changed": false}},
  "height": {{"text": "", "confidence": 0.0, "changed": false}},
  "name":   {{"text": "", "confidence": 0.0, "changed": false}},
  "confidence": 0.0
}}

Return JSON only."""

_RECOVERY_PROMPT = """You are performing a last-resort analysis of a Pokémon GO appraisal.
You have two images: [0] the base Pokémon screen, [1] the appraisal overlay.

Extract as much as you can and return this JSON:

{
  "name":    {"text": "",  "confidence": 0.0},
  "cp":      {"text": "",  "confidence": 0.0},
  "hp":      {"text": "",  "confidence": 0.0},
  "type1":   {"text": "",  "confidence": 0.0},
  "type2":   {"text": "",  "confidence": 0.0},
  "weight":  {"text": "",  "confidence": 0.0},
  "height":  {"text": "",  "confidence": 0.0},
  "bars": {
    "attack":  {"value": -1, "confidence": 0.0},
    "defense": {"value": -1, "confidence": 0.0},
    "stamina": {"value": -1, "confidence": 0.0}
  },
  "confidence": 0.0,
  "notes": ""
}

Use value -1 for bars you cannot determine.
Return JSON only."""

_CP_PROMPT = """Read the exact number shown after 'CP' in this Pokémon GO screenshot.

Rules:
- Report ONLY the digits you can clearly see
- The number is between 10 and 5500
- Do NOT add leading zeros
- Do NOT add extra digits if the image is unclear
- If you cannot read the number clearly, return: CP: 0

Format: CP: <number>

Examples:
- If you see "CP161" clearly → CP: 161
- If you see "CP12" or partial text → CP: 12
- If the image is blurry or cut off → CP: 0"""

_STATS_PROMPT = """Look at this Pokémon GO stats panel and extract these values.

IMPORTANT: There are circular colored icons showing type badges.
IGNORE the icons completely.
Read ONLY the TEXT WORD written beneath the icons (e.g. "FAIRY", "ELECTRIC", "DRAGON").
The type text is always a single English word in capital letters under the icon.

The panel contains (top to bottom):
1. Pokémon name
2. HP shown as "X / Y HP" — give only X
3. A row: WEIGHT (kg) on left | type ICON with TEXT LABEL in middle | HEIGHT (m) on right
   → Read the text label under the icon, not the icon itself

IGNORE: Stardust, candy counts, POWER UP, EVOLVE, NEW RECORD banners.

Answer in this exact format:
HP: <number>
TYPE1: <word>
TYPE2: <word or none>
WEIGHT: <number> kg
HEIGHT: <number> m"""

_HP_PROMPT = """This is a crop from a Pokémon GO stats card showing the Pokémon name and HP bar.

Find the HP value shown as "X / Y HP" — a green bar with two numbers and the letters HP.
Return ONLY the first number (X), the current HP before the slash.

The number is typically between 10 and 500.
Ignore the Pokémon name, nickname, or any other text.

Answer in this exact format with nothing else:
HP: <number>"""

_TYPE_PROMPT = """This is a crop from a Pokémon GO stats card showing ONLY the weight/type/height row.

The row has exactly three columns:
- LEFT:   a number followed by "kg" — this is the WEIGHT
- MIDDLE: one or two circular colored icons, each with a word beneath it — these are the TYPES
- RIGHT:  a number followed by "m" — this is the HEIGHT

Read the TEXT WORD beneath each circular icon in the middle column.
Each word will be one of these exact words (never abbreviated):
NORMAL, FIRE, WATER, ELECTRIC, GRASS, ICE, FIGHTING, POISON, GROUND,
FLYING, PSYCHIC, BUG, ROCK, GHOST, DRAGON, DARK, STEEL, FAIRY

If there is ONE type icon, set TYPE2 to NONE.
If there are TWO type icons, read both words left to right.

Answer in this exact format with nothing else:
TYPE1: <word>
TYPE2: <word or NONE>
WEIGHT: <number> kg
HEIGHT: <number> m"""

_CANDY_PROMPT = """This is a crop from a Pokémon GO stats card showing the resource row.

This row contains 2-4 items in this order:
1. STARDUST — a large number with a purple/pink icon, labeled "STARDUST"
2. CANDY — a number with a round icon, labeled "<SPECIES> CANDY"
3. CANDY XL — a number with a square icon, labeled "<SPECIES> CANDY XL"
4. Sometimes a MEGA ENERGY or PRIMAL ENERGY count appears as a 4th item

Extract only the CANDY and CANDY XL numbers (ignore stardust).
The species name in the label tells you which Pokémon this is.

Answer in this exact format with nothing else:
CANDY: <number>
CANDY_XL: <number>
CANDY_SPECIES: <species name>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_base_screen(img: Image.Image) -> dict:
    log.debug("VisionAgent.analyze_base_screen called")
    try:
        cp_img    = _crop_cp_region(img)
        hp_img    = _crop_hp_region(img)
        type_img  = _crop_type_region(img)
        candy_img = _crop_candy_region(img)

        # Debug crops
        cp_img.save("cp_region.png")
        hp_img.save("hp_region.png")
        type_img.save("type_region.png")
        candy_img.save("candy_region.png")

        cp_raw    = call_vlm(_CP_PROMPT,    [cp_img])
        hp_raw    = call_vlm(_HP_PROMPT,    [hp_img])
        type_raw  = call_vlm(_TYPE_PROMPT,  [type_img])
        candy_raw = call_vlm(_CANDY_PROMPT, [candy_img])

        print(f"DEBUG cp_raw:    {cp_raw!r}")
        print(f"DEBUG hp_raw:    {hp_raw!r}")
        print(f"DEBUG type_raw:  {type_raw!r}")
        print(f"DEBUG candy_raw: {candy_raw!r}")

        cp_result    = _parse_qa_response(cp_raw)
        hp_result    = _parse_qa_response(hp_raw)
        type_result  = _parse_qa_response(type_raw)
        candy_result = _parse_candy_response(candy_raw)

        result = {
            "screen_type":    "base_screen",
            "cp":             cp_result.get("cp",            {"text": "", "confidence": 0.0}),
            "hp":             hp_result.get("hp",            {"text": "", "confidence": 0.0}),
            "type1":          type_result.get("type1",       {"text": "", "confidence": 0.0}),
            "type2":          type_result.get("type2",       {"text": "", "confidence": 0.0}),
            "weight":         type_result.get("weight",      {"text": "", "confidence": 0.0}),
            "height":         type_result.get("height",      {"text": "", "confidence": 0.0}),
            "candy":          candy_result.get("candy",      {"text": "", "confidence": 0.0}),
            "candy_xl":       candy_result.get("candy_xl",   {"text": "", "confidence": 0.0}),
            "candy_species":  candy_result.get("candy_species", {"text": "", "confidence": 0.0}),
            "source": "vlm",
        }

        # Reject hallucinated types
        for key in ("type1", "type2"):
            t = result[key].get("text", "").lower()
            if t and t not in ("none", "") and t not in VALID_TYPES:
                log.warning(f"VLM returned invalid type '{t}' — rejecting")
                result[key] = {"text": "", "confidence": 0.0}

        fields_found = sum(
            1 for k in ("cp", "hp", "type1", "weight", "height")
            if result.get(k, {}).get("text")
        )
        result["confidence"] = 0.9 if fields_found >= 5 else round(fields_found / 5, 2)
        return result

    except Exception as e:
        log.warning(f"VisionAgent VLM call failed: {e}")
        return {"source": "vlm", "confidence": 0.0, "error": str(e)}


def analyze_appraisal_screen(img: Image.Image) -> dict:
    """Analyze the dark appraisal overlay screen."""
    log.debug("VisionAgent.analyze_appraisal_screen called")
    return _safe_call(_APPRAISAL_SCREEN_PROMPT, _pil_to_list(img))


def correct_ocr(fields: dict, img: Optional[Image.Image] = None) -> dict:
    """Ask the VLM to correct suspicious OCR-extracted fields."""
    log.debug("VisionAgent.correct_ocr called")
    prompt = _OCR_CORRECTION_PROMPT.format(fields_json=json.dumps(fields, indent=2))
    images = _pil_to_list(img) if img is not None else []
    return _safe_call(prompt, images)


def recover_failed_parse(
    base_img: Image.Image,
    appraisal_img: Image.Image,
    partial: Optional[dict] = None,
) -> dict:
    """Last-resort full-screen recovery when the normal pipeline failed."""
    log.debug("VisionAgent.recover_failed_parse called")
    prompt = _RECOVERY_PROMPT
    if partial:
        hint = json.dumps(
            {k: v for k, v in partial.items() if v not in (None, 0, "", "Unknown")},
            indent=2,
        )
        prompt += f"\n\nHint – these values were already extracted successfully:\n{hint}"
    return _safe_call(prompt, [base_img, appraisal_img], max_tokens=500)


# ---------------------------------------------------------------------------
# Convenience validators
# ---------------------------------------------------------------------------

def is_reliable(agent_result: dict, threshold: float = CONFIDENCE_THRESHOLD) -> bool:
    return agent_result.get("confidence", 0.0) >= threshold


def extract_bar_values(agent_result: dict) -> Optional[tuple[int, int, int]]:
    bars = agent_result.get("bars", {})
    try:
        atk  = int(bars["attack"]["value"])
        def_ = int(bars["defense"]["value"])
        sta  = int(bars["stamina"]["value"])
        if all(0 <= v <= 15 for v in (atk, def_, sta)):
            return atk, def_, sta
    except (KeyError, TypeError, ValueError):
        pass
    return None


def extract_bar_bboxes(agent_result: dict, img_w: int, img_h: int) -> Optional[dict]:
    bars = agent_result.get("bars", {})
    result = {}
    for stat in ("attack", "defense", "stamina"):
        bbox = bars.get(stat, {}).get("bbox_rel")
        if not bbox or len(bbox) != 4:
            return None
        x1, y1, x2, y2 = bbox
        result[stat] = (
            int(x1 * img_w), int(y1 * img_h),
            int(x2 * img_w), int(y2 * img_h),
        )
    return result


# ---------------------------------------------------------------------------
# Warmup
# ---------------------------------------------------------------------------

def warmup_remote() -> bool:
    """
    Send a trivial text-only ping to Ollama to force the model into VRAM
    before scanning begins. Returns True if remote is ready.
    """
    global _remote_available
    log.info(f"[VLM] Warming up remote model ({VLM_MODEL}) — this may take 60-90s for 32B…")

    payload = {
        "model": VLM_MODEL,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Reply with the word READY and nothing else."}]}],
        "max_tokens": 5,
        "temperature": 0.0,
    }
    try:
        response = requests.post(
            API_URL,
            json=payload,
            timeout=(REMOTE_CONNECT_TIMEOUT, REMOTE_WARMUP_TIMEOUT),
        )
        response.raise_for_status()
        _remote_available = True
        log.info("[VLM] Remote model warmed up and ready.")
        return True
    except requests.exceptions.ConnectionError:
        log.warning("[VLM] Remote PC unreachable during warmup — will use local model.")
        _remote_available = False
        return False
    except requests.exceptions.Timeout:
        log.warning(f"[VLM] Remote warmup timed out after {REMOTE_WARMUP_TIMEOUT}s — will use local model.")
        _remote_available = False
        return False
    except Exception as e:
        log.warning(f"[VLM] Remote warmup failed: {e} — will use local model.")
        _remote_available = False
        return False
