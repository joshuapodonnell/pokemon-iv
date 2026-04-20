# config.py — Screen coordinates and thresholds
# Run calibrate.py first to populate MIRROR_REGION and UI_COORDS

import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "calibration.json")

# Default config — override via calibration
DEFAULT_CONFIG = {
    # iPhone Mirroring window bounds on your Mac screen {x, y, w, h}
    "mirror_region": {"x": 0, "y": 0, "w": 400, "h": 860},

    # Relative positions (0.0–1.0) within the mirror window
    # These are tuned for iPhone 14/15 layout — recalibrate if different
    "ui": {
        # Pokemon list screen
        "first_pokemon":     {"x": 0.50, "y": 0.18},  # first slot in storage
        "next_pokemon":      {"x": 0.50, "y": 0.18},  # same slot after swipe
        "swipe_start":       {"x": 0.50, "y": 0.75},
        "swipe_end":         {"x": 0.50, "y": 0.25},

        # Pokemon detail screen
        "appraise_button":   {"x": 0.50, "y": 0.92},  # "..." menu -> Appraise
        "menu_button":       {"x": 0.88, "y": 0.92},  # "..." button
        "back_button":       {"x": 0.06, "y": 0.06},

        # Appraisal screen
        "appraisal_next":    {"x": 0.50, "y": 0.88},  # tap to advance appraisal
        "appraisal_done":    {"x": 0.50, "y": 0.88},  # same button on last screen

        # Bar scan regions (relative to mirror window) — y center of each bar
        "atk_bar_y":  0.62,
        "def_bar_y":  0.69,
        "sta_bar_y":  0.76,
        "bar_x_start": 0.28,
        "bar_x_end":   0.94,

        # Text regions for OCR (x1,y1,x2,y2 relative)
        "name_region":  {"x1": 0.10, "y1": 0.10, "x2": 0.90, "y2": 0.20},
        "cp_region":    {"x1": 0.25, "y1": 0.04, "x2": 0.75, "y2": 0.12},
        "hp_region":    {"x1": 0.10, "y1": 0.52, "x2": 0.90, "y2": 0.60},
        "dust_region":  {"x1": 0.10, "y1": 0.56, "x2": 0.90, "y2": 0.64},
    },

    # Color thresholds
    "bar_fill_brightness": 180,   # pixel brightness >= this = filled segment
    "bar_segments": 15,            # always 15 segments per bar

    # Timing (seconds) — base values before randomization
    "timing": {
        "after_tap":         0.6,
        "after_swipe":       0.8,
        "after_appraise":    1.0,
        "between_pokemon":   1.2,
        "ocr_settle":        0.3,
    },

    # Anti-bot randomization
    "randomization": {
        "tap_jitter_px":     4,     # gaussian std dev in pixels
        "timing_sigma":      0.3,   # log-normal sigma for delays
        "min_delay_factor":  0.5,
        "max_delay_factor":  3.0,
        "short_break_every": [50, 200],   # [min, max] pokemon between short breaks
        "short_break_dur":   [15, 120],   # [min, max] seconds
        "long_break_every":  [400, 600],
        "long_break_dur":    [120, 480],
        "session_max_min":   [45, 90],    # session length in minutes
    },
}

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            saved = json.load(f)
        cfg.update(saved)
    return cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"Config saved to {CONFIG_FILE}")
