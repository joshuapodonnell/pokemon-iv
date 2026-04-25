# test_ocr.py
from PIL import Image
from ocr_parser import parsecp, parsehp, parseivbars, ocrregion, getrelativeregion
from config import loadconfig

cfg = loadconfig()
ui  = cfg["ui"]
img = Image.open("test_screen.png")

cp       = parsecp(ocrregion(getrelativeregion(img, ui["cp_region"])))
hp       = parsehp(ocrregion(getrelativeregion(img, ui["hp_region"])))
bars     = parseivbars(getrelativeregion(img, ui["bar_region"]))

print(f"CP: {cp}  HP: {hp}  Bars: {bars}")