import json
import os

CONFIGFILE = os.path.join(os.path.dirname(__file__), "calibration.json")

DEFAULTCONFIG = {
    "mirrorregion": {"x": 0, "y": 0, "w": 400, "h": 860},
    "ui": {
        # Pokémon list screen
        "firstpokemon":   {"x": 0.50, "y": 0.18},
        "nextpokemon":    {"x": 0.50, "y": 0.18},
        "swipestart":     {"x": 0.50, "y": 0.75},
        "swipeend":       {"x": 0.50, "y": 0.25},
        # Pokémon detail screen
        "appraisebutton": {"x": 0.50, "y": 0.92},
        "menubutton":     {"x": 0.88, "y": 0.92},
        "backbutton":     {"x": 0.06, "y": 0.06},
        # Appraisal screen
        "appraisalnext":  {"x": 0.50, "y": 0.88},
        "appraisaldone":  {"x": 0.50, "y": 0.88},
        "nextarrow":      {"x": 0.93, "y": 0.80},
        # IV bar scan lines (y = vertical centre of each bar row, relative to window)
        "atkbary": 0.62,
        "defbary": 0.69,
        "stabary": 0.76,
        "barxstart": 0.28,
        "barxend":   0.94,
        "barsegments": 15,
        # OCR regions — x1/y1/x2/y2 relative to window
        "nameregion":  {"x1": 0.10, "y1": 0.10, "x2": 0.90, "y2": 0.20},
        "cpregion":    {"x1": 0.25, "y1": 0.04, "x2": 0.75, "y2": 0.12},
        "hpregion":    {"x1": 0.10, "y1": 0.52, "x2": 0.90, "y2": 0.60},
        "dustregion":  {"x1": 0.10, "y1": 0.56, "x2": 0.90, "y2": 0.64},
        "typeregion":  {"x1": 0.10, "y1": 0.30, "x2": 0.90, "y2": 0.40},
        "weightregion":{"x1": 0.10, "y1": 0.42, "x2": 0.55, "y2": 0.50},
        "heightregion":{"x1": 0.55, "y1": 0.42, "x2": 0.90, "y2": 0.50},
        # Pokémon list slots
        "pokemonslots": [
            {"x": 0.201, "y": 0.286},
            {"x": 0.502, "y": 0.286},
            {"x": 0.809, "y": 0.283},
        ],
        "listswipestart": {"x": 0.5, "y": 0.7},
        "listswipeend":   {"x": 0.5, "y": 0.28},
    },
    "barfillbrightness": 160,
    "timing": {
        "aftertap":       1.5,
        "afterswipe":     1.2,
        "afterappraise":  2.0,
        "betweenpokemon": 1.5,
        "ocrsettle":      0.8,
    },
    "randomization": {
        "tapjitterpx":    4,
        "timingsigma":    0.3,
        "mindelayfactor": 0.5,
        "maxdelayfactor": 3.0,
        "shortbreakevery": [50, 200],
        "shortbreakdur":   [15, 120],
        "longbreakevery":  [400, 600],
        "longbreakdur":    [120, 480],
        "sessionmaxmin":   [45, 90],
    },
}


def loadconfig() -> dict:
    """Load config: start from DEFAULTCONFIG, overlay saved calibration.json values."""
    cfg = _deepcopy(DEFAULTCONFIG)
    if os.path.exists(CONFIGFILE):
        try:
            with open(CONFIGFILE) as f:
                saved = json.load(f)
            _deepupdate(cfg, saved)
        except Exception as e:
            print(f"[config] Warning: could not load {CONFIGFILE}: {e}")
    return cfg


def saveconfig(cfg: dict) -> None:
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
