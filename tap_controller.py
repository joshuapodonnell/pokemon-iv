# tap_controller.py — Simulates human-like taps inside the iPhone Mirroring window
# Uses PyAutoGUI to move and click; macOS routes these as iPhone touch events.

import time
import random
import math
import numpy as np
import pyautogui
import subprocess
pyautogui.FAILSAFE = True   # move mouse to top-left corner to abort

# ── Humanization helpers ──────────────────────────────────────────────────────

def _jitter(value: float, std_px: float) -> float:
    return value + random.gauss(0, std_px)

def _human_delay(base: float, sigma: float = 0.3,
                 min_factor: float = 0.5, max_factor: float = 3.0) -> float:
    """Log-normal delay centered on `base`. Mimics human reaction time distribution."""
    factor = np.random.lognormal(mean=0, sigma=sigma)
    factor = max(min_factor, min(factor, max_factor))
    delay = base * factor
    time.sleep(delay)
    return delay
def _activate_mirroring_window():
    """Bring iPhone Mirroring to the front so keyboard input actually
    reaches it, rather than whatever window happens to have focus."""
    script = 'tell application "Mirroring" to activate'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)
    except Exception:
        pass  # best-effort; if this fails, type_text still attempts to type

def _bezier_path(x0, y0, x1, y1, steps=20):
    """Generate a slightly curved (bezier) path between two points."""
    # Random control point offset — slight curve, not a straight line
    cx = (x0 + x1) / 2 + random.gauss(0, abs(x1 - x0) * 0.15 + 5)
    cy = (y0 + y1) / 2 + random.gauss(0, abs(y1 - y0) * 0.15 + 5)
    points = []
    for t in np.linspace(0, 1, steps):
        # Quadratic bezier
        px = (1 - t)**2 * x0 + 2*(1-t)*t * cx + t**2 * x1
        py = (1 - t)**2 * y0 + 2*(1-t)*t * cy + t**2 * y1
        points.append((px, py))
    return points



# ── Core tap / swipe functions ────────────────────────────────────────────────

class TapController:
    def __init__(self, config: dict):
        self.cfg = config
        self.mirror = config["mirror_region"]
        self.ui = config["ui"]
        self.rand = config["randomization"]
        self.timing = config["timing"]
        self._pokemon_count = 0
        self._session_start = time.time()

    def _abs(self, rel_x: float, rel_y: float):
        """Convert relative coords (0–1) to absolute screen coords."""
        x = self.mirror["x"] + rel_x * self.mirror["w"]
        y = self.mirror["y"] + rel_y * self.mirror["h"]
        # Add gaussian jitter
        x = _jitter(x, self.rand["tap_jitter_px"])
        y = _jitter(y, self.rand["tap_jitter_px"])
        return x, y

    def tap(self, rel_x: float, rel_y: float, base_delay: float = None):
        """Tap a relative position inside the iPhone Mirroring window."""
        x, y = self._abs(rel_x, rel_y)
        cur_x, cur_y = pyautogui.position()

        # Curved mouse movement
        path = _bezier_path(cur_x, cur_y, x, y)
        move_dur = random.uniform(0.06, 0.20)
        step_dur = move_dur / len(path)
        for px, py in path:
            pyautogui.moveTo(px, py, duration=step_dur)

        # Brief hover before click (humans don't click instantly on arrival)
        time.sleep(random.uniform(0.03, 0.12))
        pyautogui.click()

        # Post-tap delay
        delay_base = base_delay or self.timing["after_tap"]
        _human_delay(delay_base, self.rand["timing_sigma"],
                     self.rand["min_delay_factor"], self.rand["max_delay_factor"])

    def swipe_up(self):
        """Swipe up to go to next Pokémon in storage."""
        start_x = self.mirror["x"] + self.ui["swipe_start"]["x"] * self.mirror["w"]
        start_y = self.mirror["y"] + self.ui["swipe_start"]["y"] * self.mirror["h"]
        end_x   = self.mirror["x"] + self.ui["swipe_end"]["x"]   * self.mirror["w"]
        end_y   = self.mirror["y"] + self.ui["swipe_end"]["y"]   * self.mirror["h"]

        # Add jitter
        start_x = _jitter(start_x, self.rand["tap_jitter_px"])
        start_y = _jitter(start_y, self.rand["tap_jitter_px"] * 2)
        end_y   = _jitter(end_y,   self.rand["tap_jitter_px"] * 2)

        swipe_dur = random.uniform(0.18, 0.40)
        pyautogui.moveTo(start_x, start_y, duration=random.uniform(0.05, 0.15))
        pyautogui.dragTo(end_x, end_y, duration=swipe_dur, button="left")
        _human_delay(self.timing["after_swipe"], self.rand["timing_sigma"])

    def swipe_right(self):
        """Swipe right on Pokémon detail screen to advance to next Pokémon."""
        start_x = self.mirror["x"] + 0.25 * self.mirror["w"]
        end_x = self.mirror["x"] + 0.75 * self.mirror["w"]
        y = self.mirror["y"] + 0.50 * self.mirror["h"]

        # Add jitter
        start_x = _jitter(start_x, self.rand["tap_jitter_px"] * 2)
        end_x = _jitter(end_x, self.rand["tap_jitter_px"] * 2)
        y = _jitter(y, self.rand["tap_jitter_px"])

        swipe_dur = random.uniform(0.18, 0.40)
        pyautogui.moveTo(start_x, y, duration=random.uniform(0.05, 0.15))
        pyautogui.dragTo(end_x, y, duration=swipe_dur, button="left")
        _human_delay(self.timing["after_swipe"], self.rand["timing_sigma"])

    def swipe_left(self):
        """Swipe left on Pokémon detail screen to advance to next Pokémon."""
        start_x = self.mirror["x"] + 0.75 * self.mirror["w"]
        end_x = self.mirror["x"] + 0.25 * self.mirror["w"]
        y = self.mirror["y"] + 0.50 * self.mirror["h"]

        start_x = _jitter(start_x, self.rand["tap_jitter_px"] * 2)
        end_x = _jitter(end_x, self.rand["tap_jitter_px"] * 2)
        y = _jitter(y, self.rand["tap_jitter_px"])

        swipe_dur = random.uniform(0.18, 0.40)
        pyautogui.moveTo(start_x, y, duration=random.uniform(0.05, 0.15))
        pyautogui.dragTo(end_x, y, duration=swipe_dur, button="left")
        _human_delay(self.timing["after_swipe"], self.rand["timing_sigma"])

    def anti_bot_break(self):
        """Inject realistic pauses to avoid bot detection."""
        self._pokemon_count += 1
        n = self._pokemon_count

        lo, hi = self.rand["long_break_every"]
        if n % random.randint(lo, hi) == 0:
            dur = random.uniform(*self.rand["long_break_dur"])
            print(f"  [anti-bot] Long break: {dur:.0f}s (~{dur/60:.1f} min)")
            time.sleep(dur)
            return

        lo, hi = self.rand["short_break_every"]
        if n % random.randint(lo, hi) == 0:
            dur = random.uniform(*self.rand["short_break_dur"])
            print(f"  [anti-bot] Short break: {dur:.0f}s")
            time.sleep(dur)

    def session_elapsed_min(self) -> float:
        return (time.time() - self._session_start) / 60

    def session_should_pause(self) -> bool:
        max_min = random.randint(*self.rand["session_max_min"])
        return self.session_elapsed_min() >= max_min

    def swipe_list_up(self):
        """Swipe the Pokémon storage LIST upward to scroll to next row."""
        import random
        start_x = self.mirror["x"] + 0.50 * self.mirror["w"]
        start_y = self.mirror["y"] + 0.70 * self.mirror["h"]
        end_x   = self.mirror["x"] + 0.50 * self.mirror["w"]
        end_y   = self.mirror["y"] + 0.30 * self.mirror["h"]
        pyautogui.moveTo(start_x, start_y)
        import time; time.sleep(0.05)
        dur = random.uniform(0.25, 0.45)
        pyautogui.dragTo(end_x, end_y, duration=dur, button="left")
        _human_delay(self.timing.get("after_swipe", 0.8), self.rand.get("timing_sigma", 0.1))

    def type_text(self, text: str, interval: float = 0.03) -> None:
        """
        Types `text` via the Mac's keyboard, which iPhone Mirroring passes
        through to whichever text field is currently focused on the phone.

        Explicitly activates the Mirroring window first, so a stray focus
        change (e.g. clicking your terminal to watch logs) can't cause
        keystrokes to silently land in the wrong application.
        """
        _activate_mirroring_window()
        time.sleep(0.3)  # give the window manager a moment to actually switch focus
        pyautogui.write(text, interval=interval)
        _human_delay(self.timing.get("after_tap", 0.3), self.rand.get("timing_sigma", 0.1))

    def select_all_and_delete(self):
        _activate_mirroring_window()
        time.sleep(0.15)
        pyautogui.hotkey("command", "a")
        time.sleep(0.15)
        pyautogui.press("delete")
        time.sleep(0.15)
