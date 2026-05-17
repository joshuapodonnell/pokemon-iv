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

Or edit MODEL_PATH below.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
from typing import Optional

from PIL import Image

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_PATH: str = os.environ.get(
    "POGO_VLM_MODEL",
    "mlx-community/Qwen2-VL-2B-Instruct-4bit",
)

# Minimum confidence below which callers should treat the result as unreliable
# and fall through to the needsreview path.
CONFIDENCE_THRESHOLD: float = 0.75

# Maximum number of output tokens; keep small to reduce latency.
MAX_TOKENS: int = 400

# ---------------------------------------------------------------------------
# Lazy model loader – load once, reuse across calls
# ---------------------------------------------------------------------------

_model = None
_processor = None


def _load_model():
    global _model, _processor
    if _model is not None:
        return _model, _processor
    try:
        from mlx_vlm import load  # type: ignore
        log.info(f"Loading VLM: {MODEL_PATH} …")
        t0 = time.time()
        _model, _processor = load(MODEL_PATH)
        log.info(f"VLM loaded in {time.time() - t0:.1f}s")
    except ImportError:
        raise RuntimeError(
            "mlx-vlm is not installed. Run: pip install -U mlx-vlm"
        )
    return _model, _processor


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pil_to_list(img: Image.Image) -> list:
    """Return the image wrapped in a list as mlx_vlm.generate expects."""
    return [img]


def _call_vlm(prompt: str, images: list, max_tokens: int = MAX_TOKENS) -> str:
    """Send prompt + images to the local VLM; return the raw text response."""
    from mlx_vlm import generate  # type: ignore
    from mlx_vlm.prompt_utils import apply_chat_template  # type: ignore

    model, processor = _load_model()
    formatted = apply_chat_template(
        processor, model.config, prompt, num_images=len(images)
    )
    result = generate(
        model, processor, formatted, images,
        verbose=False, max_tokens=max_tokens, temp=0.0,
    )
    return result.strip()


def _parse_json_response(raw: str) -> dict:
    """
    Extract the first JSON object from the VLM's text output.
    VLMs sometimes wrap JSON in markdown code fences – strip those first.
    """
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
        raw = _call_vlm(prompt, images, max_tokens)
        result = _parse_json_response(raw)
        result.setdefault("source", "vlm")
        result.setdefault("confidence", 0.0)
        return result
    except Exception as e:
        log.warning(f"VisionAgent VLM call failed: {e}")
        return {"source": "vlm", "confidence": 0.0, "error": str(e)}


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_BASE_SCREEN_PROMPT = """You are analyzing a Pokémon GO storage screen on an iPhone.
Return ONLY a single JSON object with these exact keys:

{
  "screen_type": "base_screen",
  "cp":     {"text": "<number>",       "confidence": 0.0},
  "hp":     {"text": "<number>",       "confidence": 0.0},
  "type1":  {"text": "<type name>",    "confidence": 0.0},
  "type2":  {"text": "<type or none>", "confidence": 0.0},
  "weight": {"text": "<float> kg",     "confidence": 0.0},
  "height": {"text": "<float> m",      "confidence": 0.0},
  "confidence": 0.0
}

Rules:
- confidence values are 0.0 to 1.0.
- Overall "confidence" is the minimum of all individual confidences.
- If a field is not visible, set text to "" and confidence to 0.0.
- Do NOT invent values. If unsure, lower confidence.
- Return JSON only – no markdown, no prose."""

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_base_screen(img: Image.Image) -> dict:
    """
    Analyze the bright Pokémon storage screen (before appraisal overlay).

    Returns a dict with keys: cp, hp, type1, type2, weight, height,
    confidence, source.
    """
    log.debug("VisionAgent.analyze_base_screen called")
    return _safe_call(_BASE_SCREEN_PROMPT, _pil_to_list(img))


def analyze_appraisal_screen(img: Image.Image) -> dict:
    """
    Analyze the dark appraisal overlay screen.

    Returns a dict with keys: name, bars (attack/defense/stamina with
    value + bbox_rel), confidence, source.
    """
    log.debug("VisionAgent.analyze_appraisal_screen called")
    return _safe_call(_APPRAISAL_SCREEN_PROMPT, _pil_to_list(img))


def correct_ocr(fields: dict, img: Optional[Image.Image] = None) -> dict:
    """
    Given a dict of already-extracted OCR fields (cp, hp, type1, type2,
    weight, height, name), ask the VLM to correct suspicious values.

    `fields` keys and expected format:
        {
            "cp": "310",
            "hp": "47",
            "type1": "Fire",
            "type2": "none",
            "weight": "4.20 kg",
            "height": "0.40 m",
            "name": "Charmander"
        }

    If `img` is provided the VLM can use it visually. If None, the VLM
    works from the text alone (less accurate but still useful for
    obvious character substitutions like 0/O, 1/I/l).
    """
    log.debug("VisionAgent.correct_ocr called")
    prompt = _OCR_CORRECTION_PROMPT.format(
        fields_json=json.dumps(fields, indent=2)
    )
    images = _pil_to_list(img) if img is not None else []
    return _safe_call(prompt, images)


def recover_failed_parse(
    base_img: Image.Image,
    appraisal_img: Image.Image,
    partial: Optional[dict] = None,
) -> dict:
    """
    Last-resort full-screen recovery when the normal pipeline produced
    invalid or incomplete data.

    Pass both the base screen and the appraisal screen. `partial` may
    contain whatever fields *did* parse successfully (they will be
    included in the prompt as hints to avoid over-correction).
    """
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
# Convenience validators (used by main.py after agent call)
# ---------------------------------------------------------------------------

def is_reliable(agent_result: dict, threshold: float = CONFIDENCE_THRESHOLD) -> bool:
    """Return True if the agent result is above the confidence threshold."""
    return agent_result.get("confidence", 0.0) >= threshold


def extract_bar_values(agent_result: dict) -> Optional[tuple[int, int, int]]:
    """
    Pull (atk_iv, def_iv, sta_iv) from an analyze_appraisal_screen result.
    Returns None if bars are missing or confidence is too low.
    """
    bars = agent_result.get("bars", {})
    try:
        atk = int(bars["attack"]["value"])
        def_ = int(bars["defense"]["value"])
        sta = int(bars["stamina"]["value"])
        if all(0 <= v <= 15 for v in (atk, def_, sta)):
            return atk, def_, sta
    except (KeyError, TypeError, ValueError):
        pass
    return None


def extract_bar_bboxes(agent_result: dict, img_w: int, img_h: int) -> Optional[dict]:
    """
    Convert bbox_rel fractions to absolute pixel boxes.
    Returns dict keyed by "attack", "defense", "stamina", or None on failure.
    """
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
