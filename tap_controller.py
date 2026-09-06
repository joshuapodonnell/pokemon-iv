# tap_controller.py — complete file (copy/paste to replace yours)

import time
import random
import numpy as np
import pyautogui
import subprocess

pyautogui.FAILSAFE = True


def _clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(value, max_val))


def _jitter(value: float, std_px: float) -> float:
    return value + random.gauss(0, std_px)


def _human_delay(base: float, sigma: float = 0.3,
                 min_factor: float = 0.5, max_factor: float = 3.0) -> float:
    factor = np.random.lognormal(mean=0, sigma=sigma)
    factor = max(min_factor, min(factor, max_factor))
    delay = base * factor
    time.sleep(delay)
    return delay


def _activate_mirroring_window():
    script = 'tell application "Mirroring" to activate'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)
    except Exception:
        pass


def _bezier_path(x0, y0, x1, y1, steps=20, bounds=None):
    cx = (x0 + x1) / 2 + random.gauss(0, abs(x1 - x0) * 0.15 + 5)
    cy = (y0 + y1) / 2 + random.gauss(0, abs(y1 - y0) * 0.15 + 5)

    if bounds:
        cx = _clamp(cx, bounds["x"], bounds["x"] + bounds["w"])
        cy = _clamp(cy, bounds["y"], bounds["y"] + bounds["h"])

    points = []
    for t in np.linspace(0, 1, steps):
        px = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
        py = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
        if bounds:
            px = _clamp(px, bounds["x"], bounds["x"] + bounds["w"])
            py = _clamp(py, bounds["y"], bounds["y"] + bounds["h"])
        points.append((px, py))
    return points


class TapController:
    def __init__(self, config: dict):
        self.cfg = config
        self.mirror = config["mirror_region"]
        self.ui = config["ui"]
        self.ui_bounds = config.get("ui_bounds", {})  # NEW
        self.rand = config["randomization"]
        self.timing = config["timing"]
        self._pokemon_count = 0
        self._session_start = time.time()

        self._mirror_left = self.mirror["x"]
        self._mirror_top = self.mirror["y"]
        self._mirror_right = self.mirror["x"] + self.mirror["w"]
        self._mirror_bottom = self.mirror["y"] + self.mirror["h"]
        self._mirror_bounds = {
            "x": self._mirror_left,
            "y": self._mirror_top,
            "w": self.mirror["w"],
            "h": self.mirror["h"]
        }

    def _abs(self, rel_x: float, rel_y: float, elem_key: str = None):
        """Convert relative coords to absolute, clamped to element bounds if available."""
        x = self.mirror["x"] + rel_x * self.mirror["w"]
        y = self.mirror["y"] + rel_y * self.mirror["h"]

        x = _jitter(x, self.rand["tap_jitter_px"])
        y = _jitter(y, self.rand["tap_jitter_px"])

        # Per-element bounds clamping (NEW)
        if elem_key and elem_key in self.ui_bounds:
            b = self.ui_bounds[elem_key]
            left = self.mirror["x"] + b["x1"] * self.mirror["w"]
            right = self.mirror["x"] + b["x2"] * self.mirror["w"]
            top = self.mirror["y"] + b["y1"] * self.mirror["h"]
            bottom = self.mirror["y"] + b["y2"] * self.mirror["h"]
            x = _clamp(x, left, right)
            y = _clamp(y, top, bottom)
        else:
            # Fallback to mirror region
            x = _clamp(x, self._mirror_left, self._mirror_right)
            y = _clamp(y, self._mirror_top, self._mirror_bottom)

        return x, y

    def tap(self, rel_x: float, rel_y: float, base_delay: float = None, elem_key: str = None):
        x, y = self._abs(rel_x, rel_y, elem_key)
        cur_x, cur_y = pyautogui.position()

        bounds = self._mirror_bounds
        if elem_key and elem_key in self.ui_bounds:
            b = self.ui_bounds[elem_key]
            bounds = {
                "x": self.mirror["x"] + b["x1"] * self.mirror["w"],
                "y": self.mirror["y"] + b["y1"] * self.mirror["h"],
                "w": (b["x2"] - b["x1"]) * self.mirror["w"],
                "h": (b["y2"] - b["y1"]) * self.mirror["h"]
            }

        path = _bezier_path(cur_x, cur_y, x, y, bounds=bounds)

        move_dur = random.uniform(0.06, 0.20)
        step_dur = move_dur / len(path)
        for px, py in path:
            pyautogui.moveTo(px, py, duration=step_dur)

        time.sleep(random.uniform(0.03, 0.12))
        pyautogui.click()

        delay_base = base_delay or self.timing["after_tap"]
        _human_delay(delay_base, self.rand["timing_sigma"],
                     self.rand["min_delay_factor"], self.rand["max_delay_factor"])

    def swipe_up(self):
        start_x = self.mirror["x"] + self.ui["swipe_start"]["x"] * self.mirror["w"]
        start_y = self.mirror["y"] + self.ui["swipe_start"]["y"] * self.mirror["h"]
        end_x = self.mirror["x"] + self.ui["swipe_end"]["x"] * self.mirror["w"]
        end_y = self.mirror["y"] + self.ui["swipe_end"]["y"] * self.mirror["h"]

        start_x = _jitter(start_x, self.rand["tap_jitter_px"])
        start_y = _jitter(start_y, self.rand["tap_jitter_px"] * 2)
        end_y = _jitter(end_y, self.rand["tap_jitter_px"] * 2)

        # start_x = _clamp(start_x, self._mirror_left, self._mirror_right)
        # start_y = _clamp(start_y, self._mirror_top, self._mirror_bottom)
        # end_x = _clamp(end_x, self._mirror_left, self._mirror_right)
        # end_y = _clamp(end_y, self._mirror_top, self._mirror_bottom)

        swipe_dur = random.uniform(0.18, 0.40)
        pyautogui.moveTo(start_x, start_y, duration=random.uniform(0.05, 0.15))
        pyautogui.dragTo(end_x, end_y, duration=swipe_dur, button="left")
        _human_delay(self.timing["after_swipe"], self.rand["timing_sigma"])

    def swipe_right(self):
        start_x = self.mirror["x"] + 0.25 * self.mirror["w"]
        end_x = self.mirror["x"] + 0.75 * self.mirror["w"]
        y = self.mirror["y"] + 0.50 * self.mirror["h"]

        start_x = _jitter(start_x, self.rand["tap_jitter_px"] * 2)
        end_x = _jitter(end_x, self.rand["tap_jitter_px"] * 2)
        y = _jitter(y, self.rand["tap_jitter_px"])

        # start_x = _clamp(start_x, self._mirror_left, self._mirror_right)
        # end_x = _clamp(end_x, self._mirror_left, self._mirror_right)
        # y = _clamp(y, self._mirror_top, self._mirror_bottom)

        swipe_dur = random.uniform(0.18, 0.40)
        pyautogui.moveTo(start_x, y, duration=random.uniform(0.05, 0.15))
        pyautogui.dragTo(end_x, y, duration=swipe_dur, button="left")
        _human_delay(self.timing["after_swipe"], self.rand["timing_sigma"])

    def swipe_left(self):
        # Horizontal swipe to advance to the next Pokémon in the catalog
        # flow. y is config-driven (ui["swipe_left"]["y"]) so the drag path can
        # be lifted above the in-game "Power Up" button, which sits near the
        # vertical center (y ~0.50) of the detail screen.
        sw = self.ui.get("swipe_left", {})
        start_x = self.mirror["x"] + sw.get("x_start", 0.75) * self.mirror["w"]
        end_x = self.mirror["x"] + sw.get("x_end", 0.25) * self.mirror["w"]
        y = self.mirror["y"] + sw.get("y", 0.40) * self.mirror["h"]

        start_x = _jitter(start_x, self.rand["tap_jitter_px"] * 2)
        end_x = _jitter(end_x, self.rand["tap_jitter_px"] * 2)
        y = _jitter(y, self.rand["tap_jitter_px"])

        # start_x = _clamp(start_x, self._mirror_left, self._mirror_right)
        # end_x = _clamp(end_x, self._mirror_left, self._mirror_right)
        # y = _clamp(y, self._mirror_top, self._mirror_bottom)

        swipe_dur = random.uniform(0.18, 0.40)
        pyautogui.moveTo(start_x, y, duration=random.uniform(0.05, 0.15))
        pyautogui.dragTo(end_x, y, duration=swipe_dur, button="left")
        _human_delay(self.timing["after_swipe"], self.rand["timing_sigma"])

    def wait_after_pokemon(self):
        self._pokemon_count += 1
        if self._pokemon_count % random.randint(*self.rand["short_break_every"]) == 0:
            dur = random.uniform(*self.rand["short_break_dur"])
            time.sleep(dur)
        if self._pokemon_count % random.randint(*self.rand["long_break_every"]) == 0:
            dur = random.uniform(*self.rand["long_break_dur"])
            time.sleep(dur)
        if (time.time() - self._session_start) / 60 > random.uniform(*self.rand["session_max_min"]):
            raise RuntimeError("Session time limit reached")
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
        start_x = self.mirror["x"] + 0.50 * self.mirror["w"]
        start_y = self.mirror["y"] + 0.70 * self.mirror["h"]
        end_x = self.mirror["x"] + 0.50 * self.mirror["w"]
        end_y = self.mirror["y"] + 0.30 * self.mirror["h"]

        pyautogui.moveTo(start_x, start_y)
        time.sleep(0.05)

        dur = random.uniform(0.25, 0.45)
        pyautogui.dragTo(end_x, end_y, duration=dur, button="left")

        _human_delay(
            self.timing.get("after_swipe", 0.8),
            self.rand.get("timing_sigma", 0.1),
        )

    def type_text_applescript(self, text: str) -> None:
        _activate_mirroring_window()
        time.sleep(0.3)

        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{escaped}"'
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )

        _human_delay(
            self.timing.get("after_tap", 0.3),
            self.rand.get("timing_sigma", 0.1),
        )

    def select_all_and_delete(self):
        _activate_mirroring_window()
        time.sleep(0.15)

        pyautogui.keyDown("command")
        time.sleep(0.12)
        pyautogui.press("a")
        time.sleep(0.12)
        pyautogui.keyUp("command")

        time.sleep(0.15)
        pyautogui.press("delete")
        time.sleep(0.15)

    def paste_text(self, text: str) -> None:
        _activate_mirroring_window()
        time.sleep(0.3)

        subprocess.run("pbcopy", input=text.encode("utf-8"))
        time.sleep(3.0)  # Universal Clipboard synchronization
        pyautogui.hotkey("command", "v")

        _human_delay(
            self.timing.get("after_tap", 0.3),
            self.rand.get("timing_sigma", 0.1),
        )