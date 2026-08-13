#!/usr/bin/env python3
# calibrate.py — One-time setup: find the iPhone Mirroring window bounds
# and identify key UI element positions.
#
# Run this ONCE before running main.py.
# Usage: python calibrate.py

import json
import time
import sys
import os

def main():
    print("=" * 60)
    print("  Pokémon GO IV Bot — Calibration")
    print("=" * 60)
    print()
    print("STEP 1: Make sure iPhone Mirroring is open on your Mac.")
    print("        Your iPhone should be showing the Pokémon storage list.")
    input("Press ENTER when ready...")

    # Auto-detect window bounds
    try:
        from screen_capture import get_mirror_window_bounds
        bounds = get_mirror_window_bounds()
        print(f"\n✅ Found iPhone Mirroring window: {bounds}")
    except Exception as e:
        print(f"\n❌ Could not auto-detect window: {e}")
        print("Enter window position manually.")
        bounds = {
            "x": int(input("  Window X (left edge, pixels from left of screen): ")),
            "y": int(input("  Window Y (top edge, pixels from top of screen): ")),
            "w": int(input("  Window width in pixels: ")),
            "h": int(input("  Window height in pixels: ")),
        }

    # Capture a screenshot for visual reference
    print("\nCapturing iPhone Mirroring screenshot for reference...")
    try:
        from screen_capture import capture_window
        img = capture_window(bounds)
        img.save("calibration_screenshot.png")
        print("✅ Saved calibration_screenshot.png — open this to verify positions.")
    except Exception as e:
        print(f"⚠️  Could not capture: {e}")

    print()
    print("STEP 2: UI Coordinate Calibration")
    print("─" * 40)
    print("The bot uses RELATIVE coordinates (0.0–1.0 within the mirror window).")
    print("Default values are pre-set for iPhone 14/15 layout.")
    print()

    use_defaults = input("Use default UI coordinates? (y/n, default=y): ").strip().lower()

    from config import DEFAULT_CONFIG, save_config
    cfg = DEFAULT_CONFIG.copy()
    cfg["mirror_region"] = bounds

    if use_defaults != "n":
        print("\n✅ Using default UI coordinates.")
        print("   If the bot mis-taps, re-run calibrate.py and choose 'n' to adjust.")
    else:
        print("\nFor each button, enter its X and Y as fractions of the window size.")
        print("Example: if the window is 400px wide and a button is at x=200, enter 0.50")
        print()
        fields = [
            ("appraise_button",  "Appraise button (the ★ or '...' menu)"),
            ("menu_button",      "'...' overflow menu button"),
            ("back_button",      "Back arrow button"),
            ("appraisal_next",   "Next/continue on appraisal screen"),
            ("swipe_start",      "Swipe start Y (finger-down position, ~75% down)"),
            ("swipe_end",        "Swipe end Y (finger-up position, ~25% down)"),
        ]
        for key, label in fields:
            print(f"\n  {label}")
            x = float(input(f"    X (0.0–1.0): ") or cfg["ui"][key].get("x", 0.5))
            y = float(input(f"    Y (0.0–1.0): ") or cfg["ui"][key].get("y", 0.5))
            cfg["ui"][key] = {"x": x, "y": y}

        print("\n  Appraisal bar positions (Y center of each bar row)")
        cfg["ui"]["atk_bar_y"] = float(input("    Attack bar Y (0.0–1.0, default 0.62): ") or 0.62)
        cfg["ui"]["def_bar_y"] = float(input("    Defense bar Y (0.0–1.0, default 0.69): ") or 0.69)
        cfg["ui"]["sta_bar_y"] = float(input("    Stamina bar Y (0.0–1.0, default 0.76): ") or 0.76)
        cfg["ui"]["bar_x_start"] = float(input("    Bar left edge X (0.0–1.0, default 0.28): ") or 0.28)
        cfg["ui"]["bar_x_end"]   = float(input("    Bar right edge X (0.0–1.0, default 0.94): ") or 0.94)

    print()
    print("STEP 3: Timing preferences")
    session_max = input("Max session length in minutes (default 60-90): ").strip()
    if session_max:
        try:
            val = int(session_max)
            cfg["randomization"]["session_max_min"] = [max(30, val - 15), val]
        except ValueError:
            pass

    save_config(cfg)

    print()
    print("=" * 60)
    print("✅ Calibration complete!")
    print()
    print("Next steps:")
    print("  1. Download base stats: python download_data.py")
    print("  2. Run the bot:         python main.py")
    print("=" * 60)

if __name__ == "__main__":
    main()
