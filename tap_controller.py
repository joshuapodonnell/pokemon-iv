import time
import random
import numpy as np
import pyautogui
import subprocess

pyautogui.FAILSAFE = True
# We own all movement timing via time.sleep() between near-instant position
# sets. The default PAUSE (0.1s) would otherwise add a choppy delay after
# EVERY bezier point, making moves look like a series of teleports.
pyautogui.PAUSE = 0
if hasattr(pyautogui, "MINIMUM_DURATION"):
    pyautogui.MINIMUM_DURATION = 0


# --------------------------------------------------------------------------- #
# Math / timing helpers
# --------------------------------------------------------------------------- #
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


def _ease_in_out_cubic(t: float) -> float:
    """Velocity profile: slow start, fast middle, slow end (human-like)."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - pow(-2 * t + 2, 3) / 2


def _ease_out_cubic(t: float) -> float:
    """Decelerating profile: fast start, slow end. Used for DRAGS/swipes so the
    finger has immediate momentum when it touches down — iPhone Mirroring only
    registers a drag (not a tap/long-press) if movement happens promptly after
    mouseDown. A real flick also lands already moving and decelerates."""
    return 1 - pow(1 - t, 3)


def _duration_for_distance(distance: float) -> float:
    """Scale movement duration by distance — humans take longer for longer
    moves. Returns ~0.16s for a short tap, up to ~0.45s across the screen."""
    dur = 0.13 + (distance / 2500.0) * 0.32
    return _clamp(dur, 0.16, 0.50)


def _cubic_bezier_point(t, p0, p1, p2, p3):
    u = 1 - t
    x = (u**3) * p0[0] + 3 * (u**2) * t * p1[0] + 3 * u * (t**2) * p2[0] + (t**3) * p3[0]
    y = (u**3) * p0[1] + 3 * (u**2) * t * p1[1] + 3 * u * (t**2) * p2[1] + (t**3) * p3[1]
    return x, y


# --------------------------------------------------------------------------- #
# Core human-like movement primitives
# --------------------------------------------------------------------------- #
def _human_move_to(target_x, target_y, start_x=None, start_y=None,
                   duration=None, curve=True, bounds=None):
    """Move the cursor to (target_x, target_y) along a human-like path.

    - Cubic bezier (two jittered control points) for organic curvature.
    - Ease-in/ease-out velocity profile so movement starts and ends slowly.
    - The PATH is clamped only to the broad mirror region (``bounds``) — never
      to a small target element. Clamping the path to the element bounding box
      is what made the cursor appear to "teleport" to the element edge.
    """
    if start_x is None or start_y is None:
        start_x, start_y = pyautogui.position()
    dx = target_x - start_x
    dy = target_y - start_y
    dist = (dx * dx + dy * dy) ** 0.5
    if duration is None:
        duration = _duration_for_distance(dist)

    # Near-straight eased move for very short hops (no visible curve needed).
    if not curve or dist < 4:
        n = max(8, int(duration / 0.012))
        step = duration / n
        for i in range(1, n + 1):
            e = _ease_in_out_cubic(i / n)
            px = start_x + dx * e
            py = start_y + dy * e
            if bounds:
                px = _clamp(px, bounds["x"], bounds["x"] + bounds["w"])
                py = _clamp(py, bounds["y"], bounds["y"] + bounds["h"])
            pyautogui.moveTo(px, py, duration=0)
            time.sleep(step)
        return

    # Perpendicular offset for the control points, kept modest so swipes stay
    # mostly straight (too much curve makes iPhone Mirroring misread gestures).
    curve_amount = min(dist * 0.10 + 5, 45)
    if dist > 0:
        nx, ny = -dy / dist, dx / dist
    else:
        nx, ny = 0.0, 0.0
    sign = random.choice((-1, 1))
    off1 = random.gauss(0, curve_amount * 0.35)
    off2 = random.gauss(0, curve_amount * 0.35)
    c1 = (start_x + dx * 0.30 + nx * (curve_amount + off1) * sign,
          start_y + dy * 0.30 + ny * (curve_amount + off1) * sign)
    c2 = (start_x + dx * 0.70 + nx * (curve_amount + off2) * sign,
          start_y + dy * 0.70 + ny * (curve_amount + off2) * sign)

    n = max(14, int(duration / 0.010))
    step = duration / n
    for i in range(1, n + 1):
        e = _ease_in_out_cubic(i / n)
        px, py = _cubic_bezier_point(e, (start_x, start_y), c1, c2, (target_x, target_y))
        if bounds:
            px = _clamp(px, bounds["x"], bounds["x"] + bounds["w"])
            py = _clamp(py, bounds["y"], bounds["y"] + bounds["h"])
        pyautogui.moveTo(px, py, duration=0)
        time.sleep(step)


def _human_drag(start_x, start_y, end_x, end_y, duration=None, bounds=None):
    """Press, drag, and release along a human-like eased path.

    Moves to the start point first (human-like, NO path clamping so a cursor
    starting outside the window isn't snapped to the edge), pauses briefly (a
    real finger settles before dragging), then drags through a shallow cubic
    bezier with ease-in/ease-out timing. The drag path is clamped to the
    mirror region so the finger stays on-screen during the swipe.
    """
    _human_move_to(start_x, start_y, duration=random.uniform(0.14, 0.26),
                  bounds=None)
    time.sleep(random.uniform(0.05, 0.13))  # settle before pressing

    dx = end_x - start_x
    dy = end_y - start_y
    dist = (dx * dx + dy * dy) ** 0.5
    if duration is None:
        duration = _duration_for_distance(dist)
    # Keep the drag path shallow and mostly straight — too much curve makes
    # iPhone Mirroring misread the gesture. Ease-OUT (not in-out) so the drag
    # starts with momentum and is recognized as a swipe, not a long-press.
    curve_amount = min(dist * 0.03, 12)
    if dist > 0:
        nx, ny = -dy / dist, dx / dist
    else:
        nx, ny = 0.0, 0.0
    sign = random.choice((-1, 1))
    off = random.gauss(0, curve_amount * 0.4)
    c1 = (start_x + dx * 0.33 + nx * (curve_amount + off) * sign,
          start_y + dy * 0.33 + ny * (curve_amount + off) * sign)
    c2 = (start_x + dx * 0.66 + nx * (curve_amount - off) * sign,
          start_y + dy * 0.66 + ny * (curve_amount - off) * sign)

    n = max(18, int(duration / 0.008))
    step = duration / n
    pyautogui.mouseDown(button="left")
    try:
        for i in range(1, n + 1):
            e = _ease_out_cubic(i / n)
            px, py = _cubic_bezier_point(e, (start_x, start_y), c1, c2, (end_x, end_y))
            if bounds:
                px = _clamp(px, bounds["x"], bounds["x"] + bounds["w"])
                py = _clamp(py, bounds["y"], bounds["y"] + bounds["h"])
            pyautogui.moveTo(px, py, duration=0)
            time.sleep(step)
    finally:
        pyautogui.mouseUp(button="left")


# --------------------------------------------------------------------------- #
# Window activation
# --------------------------------------------------------------------------- #
def _activate_mirroring_window():
    script = 'tell application "Mirroring" to activate'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)
    except Exception:
        pass


class TapController:
    def __init__(self, config: dict):
        self.cfg = config
        self.rand = config["randomization"]
        self.timing = config["timing"]
        self.ui = config["ui"]
        self.ui_bounds = config.get("ui_bounds", {})
        self._pokemon_count = 0
        self._session_start = time.time()
        self.set_mirror_region(config["mirror_region"])

    def set_mirror_region(self, mirror: dict):
        """Update the mirrored window bounds and all derived clamp regions.

        Call this whenever the Mirroring window moves or resizes. The cached
        bounds are used to keep movement paths on-screen.
        """
        self.mirror = mirror
        self._mirror_left = mirror["x"]
        self._mirror_top = mirror["y"]
        self._mirror_right = mirror["x"] + mirror["w"]
        self._mirror_bottom = mirror["y"] + mirror["h"]
        self._mirror_bounds = {
            "x": self._mirror_left,
            "y": self._mirror_top,
            "w": mirror["w"],
            "h": mirror["h"],
        }

    def _abs(self, rel_x: float, rel_y: float, elem_key: str = None):
        """Convert relative coords to absolute. Only the final TARGET is
        clamped to the element bounds — never the movement path to it."""
        x = self.mirror["x"] + rel_x * self.mirror["w"]
        y = self.mirror["y"] + rel_y * self.mirror["h"]

        x = _jitter(x, self.rand["tap_jitter_px"])
        y = _jitter(y, self.rand["tap_jitter_px"])

        if elem_key and elem_key in self.ui_bounds:
            b = self.ui_bounds[elem_key]
            left = self.mirror["x"] + b["x1"] * self.mirror["w"]
            right = self.mirror["x"] + b["x2"] * self.mirror["w"]
            top = self.mirror["y"] + b["y1"] * self.mirror["h"]
            bottom = self.mirror["y"] + b["y2"] * self.mirror["h"]
            x = _clamp(x, left, right)
            y = _clamp(y, top, bottom)
        else:
            x = _clamp(x, self._mirror_left, self._mirror_right)
            y = _clamp(y, self._mirror_top, self._mirror_bottom)

        return x, y

    # ------------------------------------------------------------------ #
    # Tap
    # ------------------------------------------------------------------ #
    def tap(self, rel_x: float, rel_y: float, base_delay: float = None,
            elem_key: str = None):
        x, y = self._abs(rel_x, rel_y, elem_key)  # target clamped to element

        # Move along a human path with NO path clamping — the cursor may start
        # outside the Mirroring window, and clamping the approach path to the
        # window would snap the first point to the edge (another teleport).
        # The target itself is already clamped to the element by _abs().
        _human_move_to(x, y, bounds=None)

        time.sleep(random.uniform(0.03, 0.12))  # brief settle before clicking
        pyautogui.click()

        delay_base = base_delay or self.timing["after_tap"]
        _human_delay(delay_base, self.rand["timing_sigma"],
                     self.rand["min_delay_factor"], self.rand["max_delay_factor"])

    # ------------------------------------------------------------------ #
    # Swipes
    # ------------------------------------------------------------------ #
    def swipe_up(self):
        start_x = self.mirror["x"] + self.ui["swipe_start"]["x"] * self.mirror["w"]
        start_y = self.mirror["y"] + self.ui["swipe_start"]["y"] * self.mirror["h"]
        end_x = self.mirror["x"] + self.ui["swipe_end"]["x"] * self.mirror["w"]
        end_y = self.mirror["y"] + self.ui["swipe_end"]["y"] * self.mirror["h"]

        start_x = _jitter(start_x, self.rand["tap_jitter_px"])
        start_y = _jitter(start_y, self.rand["tap_jitter_px"] * 2)
        end_y = _jitter(end_y, self.rand["tap_jitter_px"] * 2)

        _human_drag(start_x, start_y, end_x, end_y,
                    duration=random.uniform(0.18, 0.40),
                    bounds=self._mirror_bounds)
        _human_delay(self.timing["after_swipe"], self.rand["timing_sigma"])

    def swipe_right(self):
        start_x = self.mirror["x"] + 0.25 * self.mirror["w"]
        end_x = self.mirror["x"] + 0.75 * self.mirror["w"]
        y = self.mirror["y"] + 0.50 * self.mirror["h"]

        start_x = _jitter(start_x, self.rand["tap_jitter_px"] * 2)
        end_x = _jitter(end_x, self.rand["tap_jitter_px"] * 2)
        y = _jitter(y, self.rand["tap_jitter_px"])

        _human_drag(start_x, y, end_x, y,
                    duration=random.uniform(0.18, 0.40),
                    bounds=self._mirror_bounds)
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

        swipe_dur = random.uniform(0.18, 0.40)
        pyautogui.moveTo(start_x, y, duration=random.uniform(0.05, 0.15))
        pyautogui.dragTo(end_x, y, duration=swipe_dur, button="left")
        _human_delay(self.timing["after_swipe"], self.rand["timing_sigma"])

    def swipe_list_up(self):
        """Swipe the Pokémon storage LIST upward to scroll to next row."""
        start_x = self.mirror["x"] + 0.50 * self.mirror["w"]
        start_y = self.mirror["y"] + 0.70 * self.mirror["h"]
        end_x = self.mirror["x"] + 0.50 * self.mirror["w"]
        end_y = self.mirror["y"] + 0.30 * self.mirror["h"]

        _human_drag(start_x, start_y, end_x, end_y,
                    duration=random.uniform(0.25, 0.45),
                    bounds=self._mirror_bounds)
        _human_delay(
            self.timing.get("after_swipe", 0.8),
            self.rand.get("timing_sigma", 0.1),
        )

    # ------------------------------------------------------------------ #
    # Breaks / session
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    # Keyboard helpers
    # ------------------------------------------------------------------ #
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
