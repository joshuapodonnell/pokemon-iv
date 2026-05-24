import vision_agent
from screen_capture import capture_window
from config import loadconfig

cfg  = loadconfig()
base_img = capture_window(cfg['mirror_region'])   # drop your screenshot here
cropped = vision_agent.crop_for_vlm(base_img)
cropped.save("cropped_debug.png")
print(f"Original: {base_img.size}  →  Cropped: {cropped.size}")

from PIL import Image
import vision_agent

raw = vision_agent.call_vlm(
    "What color is the background of this image? Answer in one word.",
    [cropped]
)
print("Raw VLM response:", raw)