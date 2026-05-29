import numpy as np
from PIL import Image
import subprocess
import logging
LOG_FILE = "calibration_viewer.log"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("calibration_viewer")

def get_mirror_window_bounds():
    """Find the iPhone Mirroring app window bounds using AppleScript."""
    script = '''
    tell application "System Events"
        tell process "iPhone Mirroring"
            set w to window 1
            set pos to position of w
            set sz to size of w
            set x to item 1 of pos
            set y to item 2 of pos
            set w2 to item 1 of sz
            set h to item 2 of sz
            return (x as string) & " " & (y as string) & " " & (w2 as string) & " " & (h as string)
        end tell
    end tell
    '''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not find iPhone Mirroring window.\n"
            f"Make sure the app is open and your iPhone is connected.\n"
            f"Error: {result.stderr.strip()}"
        )
    parts = result.stdout.strip().split()
    x, y, w, h = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return {"x": x, "y": y, "w": w, "h": h}

def capture_window(bounds: dict) -> Image.Image:
    logger.debug("capture_window entered bounds=%s", bounds)
    try:
        import Quartz
        logger.debug("Quartz import succeeded")
        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID
        )
        logger.debug("Window list retrieved: count=%s", len(window_list) if window_list else 0)
        mirror_wid = None
        for win in window_list:
            owner = win.get("kCGWindowOwnerName", "")
            name = win.get("kCGWindowName", "")
            wid = win.get("kCGWindowNumber")
            logger.debug("Window candidate owner=%r name=%r wid=%r", owner, name, wid)
            if "iPhone Mirroring" in owner:
                mirror_wid = win.get("kCGWindowNumber")
                logger.debug("Matched iPhone Mirroring window: wid=%s", mirror_wid)
                break

        if mirror_wid is None:
            raise RuntimeError("iPhone Mirroring window not found in window list")

        logger.debug("Calling CGWindowListCreateImage for wid=%s", mirror_wid)
        cg_image = Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull,
            Quartz.kCGWindowListOptionIncludingWindow,
            mirror_wid,
            Quartz.kCGWindowImageBoundsIgnoreFraming
        )
        logger.debug("CGWindowListCreateImage returned: %r", cg_image)
        if cg_image is None:
            raise RuntimeError("CGWindowListCreateImage returned None")
        width  = Quartz.CGImageGetWidth(cg_image)
        height = Quartz.CGImageGetHeight(cg_image)
        bpr    = Quartz.CGImageGetBytesPerRow(cg_image)
        logger.debug("CGImage stats width=%s height=%s bytes_per_row=%s", width, height, bpr)
        if width <= 0 or height <= 0:
            raise RuntimeError(f"Invalid CGImage dimensions: {width}x{height}")
        data_provider = Quartz.CGImageGetDataProvider(cg_image)
        logger.debug("Data provider: %r", data_provider)
        if data_provider is None:
            raise RuntimeError("CGImageGetDataProvider returned None")

        raw_data = Quartz.CGDataProviderCopyData(data_provider)
        logger.debug("Raw data length=%s", len(raw_data) if raw_data is not None else None)
        if raw_data is None:
            raise RuntimeError("CGDataProviderCopyData returned None")
        img_array = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, bpr // 4, 4))
        img_array = img_array[:, :width, :]
        logger.debug("Trimmed numpy array shape=%s", img_array.shape)
        img_array = img_array[:, :, [2, 1, 0, 3]]  # BGRA -> RGBA
        logger.debug("Converted BGRA to RGBA")
        pil_img = Image.fromarray(img_array, "RGBA").convert("RGB")
        logger.debug("Returning PIL image size=%s mode=%s", pil_img.size, pil_img.mode)
        return pil_img


    except ImportError:

        logger.debug("Quartz import failed, falling back to mss")

        import mss

        with mss.mss() as sct:

            monitor = {

                "left": bounds["x"],

                "top": bounds["y"],

                "width": bounds["w"],

                "height": bounds["h"],

            }

            logger.debug("Using mss monitor=%s", monitor)

            screenshot = sct.grab(monitor)

            logger.debug("mss screenshot size=%s", screenshot.size)

            pil_img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            logger.debug("Returning mss PIL image size=%s mode=%s", pil_img.size, pil_img.mode)

            return pil_img

    except Exception:

        logger.exception("capture_window failed bounds=%s", bounds)

        raise

def get_relative_region(img: Image.Image, rel: dict) -> Image.Image:
    w, h = img.size
    x1 = int(rel["x1"] * w)
    y1 = int(rel["y1"] * h)
    x2 = int(rel["x2"] * w)
    y2 = int(rel["y2"] * h)
    return img.crop((x1, y1, x2, y2))