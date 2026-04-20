import numpy as np
from PIL import Image
import subprocess

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
    try:
        import Quartz

        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID
        )

        mirror_wid = None
        for win in window_list:
            owner = win.get("kCGWindowOwnerName", "")
            if "iPhone Mirroring" in owner:
                mirror_wid = win.get("kCGWindowNumber")
                break

        if mirror_wid is None:
            raise RuntimeError("iPhone Mirroring window not found in window list")

        cg_image = Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull,
            Quartz.kCGWindowListOptionIncludingWindow,
            mirror_wid,
            Quartz.kCGWindowImageBoundsIgnoreFraming
        )

        width  = Quartz.CGImageGetWidth(cg_image)
        height = Quartz.CGImageGetHeight(cg_image)
        bpr    = Quartz.CGImageGetBytesPerRow(cg_image)

        data_provider = Quartz.CGImageGetDataProvider(cg_image)
        raw_data = Quartz.CGDataProviderCopyData(data_provider)
        img_array = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, bpr // 4, 4))
        img_array = img_array[:, :width, :]
        img_array = img_array[:, :, [2, 1, 0, 3]]  # BGRA -> RGBA
        return Image.fromarray(img_array, "RGBA").convert("RGB")

    except ImportError:
        import mss
        with mss.mss() as sct:
            monitor = {
                "left":   bounds["x"],
                "top":    bounds["y"],
                "width":  bounds["w"],
                "height": bounds["h"],
            }
            screenshot = sct.grab(monitor)
            return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

def get_relative_region(img: Image.Image, rel: dict) -> Image.Image:
    w, h = img.size
    x1 = int(rel["x1"] * w)
    y1 = int(rel["y1"] * h)
    x2 = int(rel["x2"] * w)
    y2 = int(rel["y2"] * h)
    return img.crop((x1, y1, x2, y2))