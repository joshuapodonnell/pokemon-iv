# tagger.py — Applies in-game Pokémon GO tags via UI automation
# Requires tags "keep", "transfer", "review" to exist in-game before use.
# Call apply_ingame_tag() while the Pokémon detail screen is open.

import time
import logging
import tap_controller
from tap_controller import TapController

log = logging.getLogger(__name__)

# How long to wait for the tag menu to animate open
TAG_MENU_SETTLE  = 0.8
TAG_SELECT_PAUSE = 0.5
TAG_DISMISS_PAUSE = 0.6

# Maps decision action → calibration key for that tag's tap target
ACTION_TO_TAG_KEY = {
    "KEEP":     "tag_keep",
    "TRANSFER": "tag_transfer",
    "REVIEW":   "tag_review",
}


def apply_ingame_tag(tap: TapController, ui: dict, window: dict, action: str):
    """
    Applies the appropriate in-game tag to the currently open Pokémon.
    Must be called while the Pokémon detail screen is visible.

    Steps:
      1. Open the ⋮ menu
      2. Tap "Tag"
      3. Tap the correct tag
      4. Dismiss the tag sheet
    """
    tag_key = ACTION_TO_TAG_KEY.get(action)
    if not tag_key:
        log.warning(f"  Unknown action '{action}' — skipping tag")
        return

    if tag_key not in ui:
        log.warning(f"  Tag position '{tag_key}' not in calibration — skipping tag")
        log.warning(f"  Run calibrate.py to set tag positions")
        return

    # Step 1: Open ⋮ menu
    menu = ui.get("menubutton", {"x": 0.842, "y": 0.933})
    tap.tap( menu["x"], menu["y"])
    time.sleep(TAG_MENU_SETTLE)

    # Step 2: Tap "Tag" option
    tag_option = ui.get("tag_option_btn")
    if not tag_option:
        log.warning("  'tag_option_btn' not calibrated — skipping tag")
        # Dismiss the menu we just opened
        tap.tap( 0.1, 0.5)
        return
    tap.tap( tag_option["x"], tag_option["y"])
    time.sleep(TAG_MENU_SETTLE)

    # Step 3: Tap the specific tag
    tag_pos = ui[tag_key]
    tap.tap( tag_pos["x"], tag_pos["y"])
    time.sleep(TAG_SELECT_PAUSE)

    # Step 4: Dismiss tag sheet (tap outside / back)
    dismiss = ui.get("tag_dismiss", {"x": 0.500, "y": 0.850})
    tap.tap( dismiss["x"], dismiss["y"])
    time.sleep(TAG_DISMISS_PAUSE)

    icons = {"KEEP": "🟢", "TRANSFER": "🔴", "REVIEW": "🟡"}
    log.info(f"  {icons.get(action, '•')} Tagged in-game: {action.lower()}")


def tags_are_calibrated(ui: dict) -> bool:
    """Returns True if all tag positions are present in calibration."""
    required = ["tag_option_btn", "tag_keep", "tag_transfer", "tag_review"]
    missing  = [k for k in required if k not in ui]
    if missing:
        log.warning(f"  Missing tag calibration keys: {missing}")
        return False
    return True