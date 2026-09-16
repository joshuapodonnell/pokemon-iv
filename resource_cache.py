"""
resource_cache.py — Persistent cache of discovered candy/candy-XL/mega-energy
resource-block layouts, keyed by mega-energy family (see
evolution_chains.get_mega_energy_family). Learned once via VLM discovery
(vision_agent.discover_resource_layout), reused via cheap OCR on every
subsequent catch of the same family.
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

LAYOUT_CACHE_PATH = Path(__file__).parent / "resource_layout_cache.json"


def load_layout_cache() -> dict:
    if LAYOUT_CACHE_PATH.exists():
        try:
            with open(LAYOUT_CACHE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Could not load {LAYOUT_CACHE_PATH}: {e} — starting fresh")
    return {}


def save_layout_cache(cache: dict) -> None:
    try:
        with open(LAYOUT_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError as e:
        log.warning(f"Could not save {LAYOUT_CACHE_PATH}: {e}")


def invalidate(cache: dict, cache_key: str) -> None:
    """Remove a stale/wrong cache entry and persist immediately."""
    if cache_key in cache:
        del cache[cache_key]
        save_layout_cache(cache)
        log.info(f"Invalidated resource layout cache entry for {cache_key!r}")


def is_valid_resource_read(values: dict) -> bool:
    """
    Sanity check for a fast-path (cached-bbox) OCR read. Candy and candy_xl
    should always be present and non-negative — if OCR landed on the wrong
    pixels (a layout change the cache doesn't know about), these typically
    come back None or fail to parse as an integer.
    """
    candy = values.get("candy")
    candy_xl = values.get("candy_xl")
    if not isinstance(candy, int) or not isinstance(candy_xl, int):
        return False
    if candy < 0 or candy_xl < 0:
        return False
    return True