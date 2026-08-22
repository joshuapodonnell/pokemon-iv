import time
import logging
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

class FreezeDetector:
    def __init__(self, threshold: float = 0.995, freeze_after: float = 15.0,
                 resize_dims: tuple = (64, 128), pixel_tolerance: int = 8):
        """
        threshold:       similarity ratio above which two frames are "identical" (0.0-1.0)
        freeze_after:    seconds of no change before declaring a freeze
        resize_dims:     downscale size used for comparison (w, h)
        pixel_tolerance: max per-pixel brightness delta to count as "same" pixel
        """
        self._threshold       = threshold
        self._freeze_after     = freeze_after
        self._resize_dims      = resize_dims
        self._pixel_tolerance  = pixel_tolerance
        self._last_change      = time.time()
        self._last_pixels      = None

    def _downscale(self, img: Image.Image) -> np.ndarray:
        small = img.resize(self._resize_dims).convert("L")
        return np.array(small, dtype=np.int16)

    def similarity_to_last(self, img: Image.Image) -> float:
        """
        Returns the similarity ratio (0.0-1.0) between img and the last
        stored frame. Returns 1.0 if there's no prior frame yet (nothing
        to compare against, so treat as "unknown/same" by convention).

        This is the single source of truth for the comparison math —
        update() and any external recovery/diagnostic code should call
        this instead of re-implementing the downscale/diff/threshold logic.
        """
        pixels = self._downscale(img)

        if self._last_pixels is None:
            return 1.0

        diff  = np.abs(pixels - self._last_pixels)
        same  = int(np.sum(diff < self._pixel_tolerance))
        return same / diff.size

    def update(self, img: Image.Image) -> bool:
        """
        Call after every capture. Returns True if a freeze is detected.
        img: the raw PIL screenshot from capture_window()
        """
        pixels = self._downscale(img)
        ratio  = self.similarity_to_last(img)

        if self._last_pixels is None:
            self._last_pixels = pixels
            self._last_change = time.time()
            return False

        if ratio < self._threshold:
            self._last_change = time.time()
            self._last_pixels = pixels
            return False

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