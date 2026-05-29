import json
import os

CONFIGFILE = os.path.join(os.path.dirname(__file__), "calibration.json")

DEFAULT_CONFIG = {
    "mirror_region": {"x": 0, "y": 0, "w": 400, "h": 860},
    "ui": {
        # Pokémon list screen
        "first_pokemon":   {"x": 0.50, "y": 0.18},
        "next_pokemon":    {"x": 0.50, "y": 0.18},
        "swipe_start":     {"x": 0.50, "y": 0.75},
        "swipe_end":       {"x": 0.50, "y": 0.25},
        # Pokémon detail screen
        "appraise_button": {"x": 0.50, "y": 0.92},
        "menu_button":     {"x": 0.88, "y": 0.92},
        "back_button":     {"x": 0.06, "y": 0.06},
        # Appraisal screen
        "appraisal_next":  {"x": 0.50, "y": 0.88},
        "appraisal_done":  {"x": 0.50, "y": 0.88},
        "next_arrow":      {"x": 0.93, "y": 0.80},
        # IV bar scan lines (y = vertical centre of each bar row, relative to window)
        "atk_bar_y": 0.62,
        "def_bar_y": 0.69,
        "sta_bar_y": 0.76,
        "bar_x_start": 0.28,
        "bar_x_end":   0.94,
        "bar_segments": 15,
        # OCR regions — x1/y1/x2/y2 relative to window
        "name_region":  {"x1": 0.10, "y1": 0.10, "x2": 0.90, "y2": 0.20},
        "cp_region":    {"x1": 0.25, "y1": 0.04, "x2": 0.75, "y2": 0.12},
        "hp_region":    {"x1": 0.10, "y1": 0.52, "x2": 0.90, "y2": 0.60},
        "dust_region":  {"x1": 0.10, "y1": 0.56, "x2": 0.90, "y2": 0.64},
        "type_region":  {"x1": 0.10, "y1": 0.30, "x2": 0.90, "y2": 0.40},
        "weight_region":{"x1": 0.10, "y1": 0.42, "x2": 0.55, "y2": 0.50},
        "height_region":{"x1": 0.55, "y1": 0.42, "x2": 0.90, "y2": 0.50},
        # Pokémon list slots
        "pokemon_slots": [
            {"x": 0.201, "y": 0.286},
            {"x": 0.502, "y": 0.286},
            {"x": 0.809, "y": 0.283},
        ],
        "list_swipe_start": {"x": 0.5, "y": 0.7},
        "list_swipe_end":   {"x": 0.5, "y": 0.28},
    },
    "bar_fill_brightness": 160,
    "timing": {
        "after_tap":       1.5,
        "after_swipe":     1.2,
        "after_appraise":  2.0,
        "between_pokemon": 1.5,
        "ocr_settle":      0.8,
    },
    "randomization": {
        "tap_jitter_px":    4,
        "timing_sigma":    0.3,
        "min_delay_factor": 0.5,
        "max_delay_factor": 3.0,
        "short_break_every": [50, 200],
        "short_break_dur":   [15, 120],
        "long_break_every":  [400, 600],
        "long_break_dur":    [120, 480],
        "session_max_min":   [45, 90],
    },
    "account": {
        "forever_friends": False
    },
    "tag_layouts": {
        "normal": {
            "tag_option_btn": {"x": 0.648, "y": 0.65},
            "tag_keep": {"x": 0.50, "y": 0.35},
            "tag_review": {"x": 0.50, "y": 0.55},
            "tag_transfer": {"x": 0.50, "y": 0.45},
            "tag_dismiss": {"x": 0.50, "y": 0.85}
        },
        "forever_friends": {
            "tag_option_btn": {"x": 0.648, "y": 0.65},
            "tag_keep": {"x": 0.50, "y": 0.40},
            "tag_review": {"x": 0.50, "y": 0.50},
            "tag_transfer": {"x": 0.50, "y": 0.60},
            "tag_dismiss": {"x": 0.50, "y": 0.85}
        }
    }
}


def load_config() -> dict:
    """Load config: start from DEFAULTCONFIG, overlay saved calibration.json values."""
    cfg = _deepcopy(DEFAULT_CONFIG)
    if os.path.exists(CONFIGFILE):
        try:
            with open(CONFIGFILE) as f:
                saved = json.load(f)
            _deepupdate(cfg, saved)
        except Exception as e:
            print(f"[config] Warning: could not load {CONFIGFILE}: {e}")
    return cfg


def save_config(cfg: dict) -> None:
    """Persist the current config dict to calibration.json."""
    with open(CONFIGFILE, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"[config] Config saved to {CONFIGFILE}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deepcopy(obj):
    """Simple deep-copy for plain JSON-compatible dicts/lists."""
    if isinstance(obj, dict):
        return {k: _deepcopy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deepcopy(v) for v in obj]
    return obj


def _deepupdate(base: dict, override: dict) -> None:
    """Recursively merge override into base (in-place). Lists are replaced wholesale."""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deepupdate(base[k], v)
        else:
            base[k] = v
