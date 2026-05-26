import time
import logging
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

class FreezeDetector:
    def __init__(self, threshold: float = 0.995, freeze_after: float = 15.0):
        """
        threshold:    similarity ratio above which two frames are "identical" (0.0–1.0)
        freeze_after: seconds of no change before declaring a freeze
        """
        self._threshold    = threshold
        self._freeze_after = freeze_after
        self._last_change  = time.time()
        self._last_pixels  = None

    def update(self, img: Image.Image) -> bool:
        """
        Call after every capture. Returns True if a freeze is detected.
        img: the raw PIL screenshot from capture_window()
        """
        # Downscale before comparing — faster and noise-resistant
        small = img.resize((64, 128)).convert("L")
        pixels = np.array(small, dtype=np.int16)

        if self._last_pixels is None:
            self._last_pixels = pixels
            self._last_change = time.time()
            return False

        diff  = np.abs(pixels - self._last_pixels)
        total = diff.size
        same  = int(np.sum(diff < 8))        # pixels within ±8 brightness = "same"
        ratio = same / total

        if ratio < self._threshold:
            # Screen changed — reset the clock
            self._last_change = time.time()
            self._last_pixels = pixels
            return False

        # Screen looks identical — check how long it's been
        frozen_for = time.time() - self._last_change
        if frozen_for >= self._freeze_after:
            log.warning(
                f"[FREEZE] Screen unchanged for {frozen_for:.1f}s "
                f"(similarity={ratio:.4f})"
            )
            return True

        return False

    def reset(self):
        """Call after a successful recovery to restart the clock."""
        self._last_change = time.time()
        self._last_pixels = None