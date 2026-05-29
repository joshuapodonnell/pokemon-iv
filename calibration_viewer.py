"""
Calibration Viewer — drag handles to adjust all regions and points.
Run: python calibration_viewer.py
"""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw
import json
import logging
import traceback
CONFIG_FILE = "calibration.json"
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
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_LANCZOS = Image.LANCZOS

# All editable handles: (label, color, config_path, handle_type)
HANDLES = [
    ("CP x1/y1",       "#FF4444", "ui.cp_region.x1y1",       "rect_tl"),
    ("CP x2/y2",       "#FF4444", "ui.cp_region.x2y2",       "rect_br"),
    ("Name x1/y1",     "#44FF44", "ui.name_region.x1y1",     "rect_tl"),
    ("Name x2/y2",     "#44FF44", "ui.name_region.x2y2",     "rect_br"),
    ("HP x1/y1",       "#4488FF", "ui.hp_region.x1y1",       "rect_tl"),
    ("HP x2/y2",       "#4488FF", "ui.hp_region.x2y2",       "rect_br"),
    ("Dust x1/y1",     "#FF44FF", "ui.dust_region.x1y1",     "rect_tl"),
    ("Dust x2/y2",     "#FF44FF", "ui.dust_region.x2y2",     "rect_br"),
    ("Type x1/y1",     "#FF9900", "ui.type_region.x1y1",     "rect_tl"),
    ("Type x2/y2",     "#FF9900", "ui.type_region.x2y2",     "rect_br"),
    ("Weight x1/y1",   "#AAFFAA", "ui.weight_region.x1y1",   "rect_tl"),
    ("Weight x2/y2",   "#AAFFAA", "ui.weight_region.x2y2",   "rect_br"),
    ("Height x1/y1",   "#AAAAFF", "ui.height_region.x1y1",   "rect_tl"),
    ("Height x2/y2",   "#AAAAFF", "ui.height_region.x2y2",   "rect_br"),
    ("Menu Button",    "#FFFFFF", "ui.menu_button",           "point"),
    ("Appraise Btn",   "#FFFF00", "ui.appraise_button",       "point"),
    ("Back Button",    "#FF6600", "ui.back_button",           "point"),
    ("Clear Search",    "#FF6600", "ui.clear_search",           "point"),
    ("Slot 1",         "#00FF88", "ui.pokemon_slots.0",       "point_slot"),
    ("Slot 2",         "#00DD77", "ui.pokemon_slots.1",       "point_slot"),
    ("Slot 3",         "#00BB66", "ui.pokemon_slots.2",       "point_slot"),
]

# We map the number of text lines (2, 3, 4, 5) to the respective config keys
TEXT_LINES_KEYS = {
    2: [
        ("ATK Bar Y",   "atk_bar_y",   "#FF8800", "hline"),
        ("DEF Bar Y",   "def_bar_y",   "#FFCC00", "hline"),
        ("STA Bar Y",   "sta_bar_y",   "#FF0088", "hline"),
        ("Bar X Start", "bar_x_start", "#00FFFF", "vline"),
        ("Bar X End",   "bar_x_end",   "#00CCFF", "vline"),
    ],
    3: [
        ("ATK Bar Y",   "atk_bar_y_3lines",   "#FF8800", "hline"),
        ("DEF Bar Y",   "def_bar_y_3lines",   "#FFCC00", "hline"),
        ("STA Bar Y",   "sta_bar_y_3lines",   "#FF0088", "hline"),
        ("Bar X Start", "bar_x_start",        "#00FFFF", "vline"),
        ("Bar X End",   "bar_x_end",          "#00CCFF", "vline"),
    ],
    4: [
        ("ATK Bar Y",   "atk_bar_y_4lines",   "#FF8800", "hline"),
        ("DEF Bar Y",   "def_bar_y_4lines",   "#FFCC00", "hline"),
        ("STA Bar Y",   "sta_bar_y_4lines",   "#FF0088", "hline"),
        ("Bar X Start", "bar_x_start",        "#00FFFF", "vline"),
        ("Bar X End",   "bar_x_end",          "#00CCFF", "vline"),
    ],
    5: [
        ("ATK Bar Y",   "atk_bar_y_5lines",   "#FF8800", "hline"),
        ("DEF Bar Y",   "def_bar_y_5lines",   "#FFCC00", "hline"),
        ("STA Bar Y",   "sta_bar_y_5lines",   "#FF0088", "hline"),
        ("Bar X Start", "bar_x_start",        "#00FFFF", "vline"),
        ("Bar X End",   "bar_x_end",          "#00CCFF", "vline"),
    ],
}

# Regions drawn as coloured overlays on the screenshot
RECT_REGIONS = [
    ("cp_region",     "#FF4444"),
    ("name_region",   "#44FF44"),
    ("hp_region",     "#4488FF"),
    ("dust_region",   "#FF44FF"),
    ("type_region",   "#FF9900"),
    ("weight_region", "#AAFFAA"),
    ("height_region", "#AAAAFF"),
]

# Default values injected into calibration.json if a region is missing
REGION_DEFAULTS = {
    "type_region":   {"x1": 0.10, "y1": 0.28, "x2": 0.90, "y2": 0.36},
    "weight_region": {"x1": 0.10, "y1": 0.38, "x2": 0.55, "y2": 0.46},
    "height_region": {"x1": 0.55, "y1": 0.38, "x2": 0.90, "y2": 0.46},
}

TAG_DEFAULTS = {
    "tag_option_btn": {"x": 0.85, "y": 0.92},
    "tag_keep":       {"x": 0.25, "y": 0.70},
    "tag_transfer":   {"x": 0.50, "y": 0.70},
    "tag_review":     {"x": 0.75, "y": 0.70},
}


def load_config():
    logger.debug("Loading config from %s", CONFIG_FILE)
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)

    # Inject missing regions so the viewer works even before calibration
    ui = cfg.setdefault("ui", {})
    logger.debug("Config loaded. UI keys: %s", sorted(ui.keys()))
    # Default text lines selection
    ui.setdefault("text_lines_layout", 2)

    # 2 Lines (Default)
    ui.setdefault("atk_bar_y", 0.774)
    ui.setdefault("def_bar_y", 0.815)
    ui.setdefault("sta_bar_y", 0.857)

    # 3 Lines
    ui.setdefault("atk_bar_y_3lines", 0.749)
    ui.setdefault("def_bar_y_3lines", 0.787)
    ui.setdefault("sta_bar_y_3lines", 0.830)

    # 4 Lines
    ui.setdefault("atk_bar_y_4lines", 0.721)
    ui.setdefault("def_bar_y_4lines", 0.760)
    ui.setdefault("sta_bar_y_4lines", 0.802)

    # 5 Lines (Extrapolated from the 0.027 vertical shift per line)
    ui.setdefault("atk_bar_y_5lines", 0.694)
    ui.setdefault("def_bar_y_5lines", 0.733)
    ui.setdefault("sta_bar_y_5lines", 0.775)

    # General X-axis boundaries for the bars
    ui.setdefault("bar_x_start", 0.132)
    ui.setdefault("bar_x_end", 0.471)

    for key, default in REGION_DEFAULTS.items():
        if key not in ui:
            ui[key] = default
    for key, default in TAG_DEFAULTS.items():
        if key not in ui:
            ui[key] = default

    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def capture_screenshot(cfg):
    from screen_capture import capture_window, get_mirror_window_bounds
    logger.debug("Starting screenshot capture")
    try:
        bounds = get_mirror_window_bounds()
        cfg["mirror_region"] = bounds
        logger.debug("Mirror bounds from window detection: %s", bounds)
    except Exception:
        logger.exception("Failed to get mirror window bounds; using fallback")
        bounds = cfg.get("mirror_region", {"x": 0, "y": 0, "w": 400, "h": 800})
        img = capture_window(bounds)
        logger.debug("Captured screenshot size: %s", getattr(img, "size", None))
    return capture_window(bounds)


class CalibrationApp:
    HANDLE_RADIUS = 9

    def __init__(self, root):
        self.root = root
        self.root.title("Pokémon GO IV Bot — Calibration Viewer")
        self.root.configure(bg="#1a1a2e")
        self.cfg = load_config()
        self.raw_img = None
        self.photo = None
        self.display_scale = 1.0
        self.dragging = None
        self.img_w = 1
        self.img_h = 1

        # Legend categorized data
        self.legend_subsets = {
            "OCR Regions": [
                ("#FF4444", "CP region corners"),
                ("#44FF44", "Name region corners"),
                ("#4488FF", "HP region corners"),
                ("#FF44FF", "Dust region corners"),
                ("#FF9900", "Type region corners"),
                ("#AAFFAA", "Weight region corners"),
                ("#AAAAFF", "Height region corners"),
            ],
            "Buttons": [
                ("#FFFFFF", "Menu button"),
                ("#FFFF00", "Appraise button"),
                ("#FF6600", "Back button"),
                ("#FF6600", "Clear Search"),
            ],
            "Slots": [
                ("#00FF88", "Pokémon slots"),
            ],
            "Tags": [
                ("#00FFFF", "Tag ⋮ (option button)"),
                ("#00FF44", "Tag Keep"),
                ("#FF3333", "Tag Transfer"),
                ("#FF9900", "Tag Review"),
            ]
        }

        # Combine all subsets for the "Legend" view
        self.legend_subsets["Legend"] = [item for sub in self.legend_subsets.values() for item in sub]
        self.legend_subsets["Legend"].extend([
            ("#FF8800", "ATK bar (drag vert)"),
            ("#FFCC00", "DEF bar (drag vert)"),
            ("#FF0088", "STA bar (drag vert)"),
            ("#00FFFF", "Bar X start/end (drag horiz)")
        ])

        self._build_ui()
        self.refresh()

    def get_text_lines_layout(self):
        return int(self.cfg["ui"].get("text_lines_layout", 2))

    def get_active_bar_keys(self):
        return TEXT_LINES_KEYS.get(self.get_text_lines_layout(), TEXT_LINES_KEYS[2])

    def show_category(self):
        selected = self.category_var.get()
        for frame in self.category_frames.values():
            frame.pack_forget()
        self.category_frames[selected].pack(fill="both", expand=True, padx=8, pady=4)

    def _build_category_legend(self, parent, subset):
        lf = tk.Frame(parent, bg="#16213e")
        lf.pack(fill="x", pady=4)
        tk.Label(lf, text="Drag colored handles on image",
                 fg="#94a3b8", bg="#16213e", font=("Helvetica", 9)).pack(pady=(0, 8))
        for color, text in subset:
            r = tk.Frame(lf, bg="#16213e")
            r.pack(fill="x", pady=1)
            tk.Label(r, bg=color, width=2, height=1).pack(side="left", padx=(0, 5))
            tk.Label(r, text=text, fg="#cbd5e1", bg="#16213e",
                     font=("Helvetica", 8)).pack(side="left")

    def _build_iv_bars_panel(self, parent):
        for w in parent.winfo_children():
            w.destroy()

        top_f = tk.Frame(parent, bg="#16213e")
        top_f.pack(fill="x", pady=4)
        tk.Label(top_f, text="Catch Text Lines:", fg="#e2e8f0", bg="#16213e").pack(side="left")

        layout_var = tk.StringVar(value=str(self.get_text_lines_layout()))
        cb = ttk.Combobox(top_f, textvariable=layout_var, values=["2", "3", "4", "5"], state="readonly", width=5)
        cb.pack(side="left", padx=8)

        def on_layout_change(e):
            self.cfg["ui"]["text_lines_layout"] = int(layout_var.get())
            self._build_iv_bars_panel(parent)
            self._redraw()

        cb.bind("<<ComboboxSelected>>", on_layout_change)

        tk.Label(parent, text="Bar Positions (drag or use sliders)",
                 font=("Helvetica", 10, "bold"), fg="#e2e8f0",
                 bg="#16213e", justify="center").pack(pady=(10, 4))

        self.bar_vars = {}
        for label, key, color, _ in self.get_active_bar_keys():
            row = tk.Frame(parent, bg="#16213e")
            row.pack(fill="x", pady=3)
            tk.Label(row, bg=color, width=2).pack(side="left", padx=(0, 6))
            tk.Label(row, text=label, fg="#e2e8f0", bg="#16213e",
                     font=("Helvetica", 9), width=11, anchor="w").pack(side="left")
            val = self.cfg["ui"].get(key, 0.5)
            var = tk.DoubleVar(value=val)
            sl = tk.Scale(row, from_=0.0, to=1.0, resolution=0.001,
                          orient="horizontal", variable=var,
                          bg="#16213e", fg="#e2e8f0", troughcolor="#0f3460",
                          highlightthickness=0, length=100,
                          command=lambda v, k=key, dv=var: self._bar_slider(k, dv))
            sl.pack(side="left")
            lbl = tk.Label(row, text=f"{val:.3f}", fg="#94a3b8", bg="#16213e",
                           font=("Helvetica", 8), width=5)
            lbl.pack(side="left")
            self.bar_vars[key] = (var, lbl)

    # ── UI BUILD ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        bar = tk.Frame(self.root, bg="#16213e", pady=6)
        bar.pack(fill="x")
        tk.Label(bar, text="📍 Calibration Viewer", font=("Helvetica", 14, "bold"),
                 fg="#e2e8f0", bg="#16213e").pack(side="left", padx=12)
        tk.Button(bar, text="🔄 Refresh", command=self.refresh,
                  bg="#0f3460", fg="white", font=("Helvetica", 11),
                  relief="flat", padx=10, pady=4).pack(side="left", padx=6)
        tk.Button(bar, text="💾 Save Config", command=self.save,
                  bg="#1a472a", fg="white", font=("Helvetica", 11),
                  relief="flat", padx=10, pady=4).pack(side="left", padx=4)
        self.status = tk.Label(bar, text="", fg="#94a3b8", bg="#16213e",
                               font=("Helvetica", 10))
        self.status.pack(side="right", padx=12)

        main = tk.Frame(self.root, bg="#1a1a2e")
        main.pack(fill="both", expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(main, bg="#0d0d1a", cursor="crosshair",
                                highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>",   self.on_press)
        self.canvas.bind("<B1-Motion>",       self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Left>",       lambda e: self._nudge(-0.001,  0))
        self.canvas.bind("<Right>",      lambda e: self._nudge( 0.001,  0))
        self.canvas.bind("<Up>",         lambda e: self._nudge( 0, -0.001))
        self.canvas.bind("<Down>",       lambda e: self._nudge( 0,  0.001))
        self.canvas.bind("<Shift-Left>",  lambda e: self._nudge(-0.01,  0))
        self.canvas.bind("<Shift-Right>", lambda e: self._nudge( 0.01,  0))
        self.canvas.bind("<Shift-Up>",    lambda e: self._nudge( 0, -0.01))
        self.canvas.bind("<Shift-Down>",  lambda e: self._nudge( 0,  0.01))
        self.canvas.focus_set()
        self.canvas.bind("<Motion>", self.on_motion)

        # ── Right panel ──
        panel = tk.Frame(main, bg="#16213e", width=270)
        panel.pack(side="right", fill="y", padx=(8, 0))
        panel.pack_propagate(False)

        top = tk.Frame(panel, bg="#16213e")
        top.pack(fill="x", padx=8, pady=(10, 6))

        tk.Label(top, text="Category:", fg="#e2e8f0", bg="#16213e",
                 font=("Helvetica", 10, "bold")).pack(side="left")

        self.category_var = tk.StringVar(value="IV Bars")
        categories = ["IV Bars", "OCR Regions", "Buttons", "Slots", "Tags", "Legend"]
        self.category_menu = ttk.Combobox(top, textvariable=self.category_var,
                                          values=categories, state="readonly", width=15)
        self.category_menu.pack(side="right", fill="x", expand=True, padx=(8, 0))
        self.category_menu.bind("<<ComboboxSelected>>", lambda e: self.show_category())

        self.panel_body = tk.Frame(panel, bg="#16213e")
        self.panel_body.pack(fill="both", expand=True)

        self.category_frames = {}
        for cat in categories:
            f = tk.Frame(self.panel_body, bg="#16213e")
            self.category_frames[cat] = f
            if cat == "IV Bars":
                self._build_iv_bars_panel(f)
            else:
                self._build_category_legend(f, self.legend_subsets[cat])

        ttk.Separator(panel, orient="horizontal").pack(fill="x", padx=8, pady=6)

        self.coord_label = tk.Label(panel,
                                    text="Hover or click on image\nto see coordinates",
                                    fg="#64748b", bg="#16213e",
                                    font=("Courier", 10), justify="center")
        self.coord_label.pack(pady=6)

        self.show_category()

    # ── SCREENSHOT + DRAW ─────────────────────────────────────────────────────
    def refresh(self):
        self.status.config(text="Capturing...")
        self.root.update()
        try:
            img = capture_screenshot(self.cfg)
            self.raw_img = img
            self.img_w, self.img_h = img.size
            cw = max(300, self.root.winfo_width() - 290)
            ch = max(400, self.root.winfo_height() - 60)
            self.display_scale = min(cw / self.img_w, ch / self.img_h, 2.0)
            self._redraw()
            self.status.config(text=f"{self.img_w}×{self.img_h} | "
                                    f"scale {self.display_scale:.2f}×  |  "
                                    f"drag handles to adjust, Save when done")
        except Exception as e:
            self.status.config(text=f"Error: {e}")

    def _redraw(self):
        if self.raw_img is None:
            return
        img = self.raw_img.copy().convert("RGBA")
        self._draw_all(img)
        dw = int(self.img_w * self.display_scale)
        dh = int(self.img_h * self.display_scale)
        img_rgb = img.convert("RGB").resize((dw, dh), RESAMPLE_LANCZOS)
        self.photo = ImageTk.PhotoImage(img_rgb)
        self.canvas.config(width=dw, height=dh)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self._draw_handles_on_canvas()

    def _draw_all(self, img):
        """Draw region overlays (filled semi-transparent rects) on PIL image."""
        draw = ImageDraw.Draw(img, "RGBA")
        w, h = img.size
        ui = self.cfg["ui"]

        def rect(key, color):
            r = ui.get(key)
            if not r:
                return
            x1, y1 = int(r["x1"] * w), int(r["y1"] * h)
            x2, y2 = int(r["x2"] * w), int(r["y2"] * h)
            hc = color.lstrip("#")
            rc, gc, bc = tuple(int(hc[i:i+2], 16) for i in (0, 2, 4))
            draw.rectangle([x1, y1, x2, y2], fill=(rc, gc, bc, 40),
                           outline=(rc, gc, bc, 200), width=2)

        for region_key, color in RECT_REGIONS:
            rect(region_key, color)

        for _, key, color, btype in self.get_active_bar_keys():
            val = ui.get(key)
            if val is None:
                continue
            hc = color.lstrip("#")
            rc, gc, bc = tuple(int(hc[i:i+2], 16) for i in (0, 2, 4))
            if btype == "hline":
                y = int(val * h)
                draw.line([(0, y), (w, y)], fill=(rc, gc, bc, 220), width=2)
            elif btype == "vline":
                x = int(val * w)
                draw.line([(x, 0), (x, h)], fill=(rc, gc, bc, 220), width=2)

    def _draw_handles_on_canvas(self):
        """Draw draggable handle circles/squares on the Tkinter canvas."""
        ui = self.cfg["ui"]
        s = self.display_scale
        r = self.HANDLE_RADIUS

        def dot(x_rel, y_rel, color, tag, label=""):
            cx = int(x_rel * self.img_w * s)
            cy = int(y_rel * self.img_h * s)
            self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r,
                                    fill=color, outline="white",
                                    width=1, tags=tag)
            if label:
                self.canvas.create_text(cx+r+3, cy, text=label,
                                        fill=color, font=("Helvetica", 8),
                                        anchor="w", tags=tag+"_lbl")

        # All rect regions (existing + new)
        rect_handles = [
            ("cp_region",     "#FF4444", "CP"),
            ("name_region",   "#44FF44", "Name"),
            ("hp_region",     "#4488FF", "HP"),
            ("dust_region",   "#FF44FF", "Dust"),
            ("type_region",   "#FF9900", "Type"),
            ("weight_region", "#AAFFAA", "Wt"),
            ("height_region", "#AAAAFF", "Ht"),
        ]
        for cfg_key, color, short in rect_handles:
            reg = ui.get(cfg_key, {})
            dot(reg.get("x1", 0), reg.get("y1", 0), color,
                f"rect_tl_{cfg_key}", f"{short} ↖")
            dot(reg.get("x2", 1), reg.get("y2", 1), color,
                f"rect_br_{cfg_key}", f"{short} ↘")

        # Point handles
        for cfg_key, color, label in [
            ("menu_button",     "#FFFFFF", "Menu"),
            ("appraise_button", "#FFFF00", "Appraise"),
            ("back_button",     "#FF6600", "Back"),
            ("clear_search", "#FF6600", "Clear"),
            ("tag_option_btn", "#00FFFF", "Tag ⋮"),
            ("tag_keep", "#00FF44", "Tag Keep"),
            ("tag_transfer", "#FF3333", "Tag Transfer"),
            ("tag_review", "#FF9900", "Tag Review"),
        ]:
            p = ui.get(cfg_key, {})
            dot(p.get("x", 0.5), p.get("y", 0.5), color,
                f"point_{cfg_key}", label)

        # Slots
        for i, slot in enumerate(ui.get("pokemon_slots", [])):
            dot(slot.get("x", 0), slot.get("y", 0),
                "#00FF88", f"slot_{i}", f"Slot{i+1}")

        # Bar handles (squares)
        for label, key, color, btype in self.get_active_bar_keys():
            val = ui.get(key)
            if val is None:
                continue
            if btype == "hline":
                cx = int(0.5 * self.img_w * s)
                cy = int(val * self.img_h * s)
            else:
                cx = int(val * self.img_w * s)
                cy = int(0.5 * self.img_h * s)
            self.canvas.create_rectangle(cx-r, cy-r, cx+r, cy+r,
                                         fill=color, outline="white",
                                         width=1, tags=f"bar_{key}")
            self.canvas.create_text(cx+r+3, cy, text=label,
                                    fill=color, font=("Helvetica", 8),
                                    anchor="w", tags=f"bar_{key}_lbl")

    # ── DRAG LOGIC ────────────────────────────────────────────────────────────
    def _canvas_to_rel(self, cx, cy):
        s = self.display_scale
        return cx / (self.img_w * s), cy / (self.img_h * s)

    def _find_handle(self, cx, cy):
        ui = self.cfg["ui"]
        s = self.display_scale
        r = self.HANDLE_RADIUS + 4

        candidates = []

        # All rect region corners
        all_rect_keys = ("cp_region", "name_region", "hp_region", "dust_region",
                         "type_region", "weight_region", "height_region")
        for cfg_key in all_rect_keys:
            reg = ui.get(cfg_key, {})
            for corner, xk, yk in [("tl", "x1", "y1"), ("br", "x2", "y2")]:
                hx = reg.get(xk, 0) * self.img_w * s
                hy = reg.get(yk, 0) * self.img_h * s
                dist = abs(cx - hx) + abs(cy - hy)
                if dist < r * 2:
                    candidates.append((dist, f"rect_{corner}_{cfg_key}",
                                       xk, yk, cfg_key, "rect_corner"))

        # Points
        for cfg_key in ("menu_button", "appraise_button", "back_button", "clear_search",
                        "tag_option_btn", "tag_keep", "tag_transfer", "tag_review"):
            p = ui.get(cfg_key, {})
            hx = p.get("x", 0.5) * self.img_w * s
            hy = p.get("y", 0.5) * self.img_h * s
            dist = abs(cx - hx) + abs(cy - hy)
            if dist < r * 2:
                candidates.append((dist, f"point_{cfg_key}",
                                   "x", "y", cfg_key, "point"))

        # Slots
        for i, slot in enumerate(ui.get("pokemon_slots", [])):
            hx = slot.get("x", 0) * self.img_w * s
            hy = slot.get("y", 0) * self.img_h * s
            dist = abs(cx - hx) + abs(cy - hy)
            if dist < r * 2:
                candidates.append((dist, f"slot_{i}", "x", "y", i, "slot"))

        # Bars
        for label, key, color, btype in self.get_active_bar_keys():
            val = ui.get(key)
            if val is None:
                continue
            if btype == "hline":
                hy = val * self.img_h * s
                dist = abs(cy - hy)
            else:
                hx = val * self.img_w * s
                dist = abs(cx - hx)
            if dist < r * 2:
                candidates.append((dist, f"bar_{key}", None, None, key, btype))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0]

    def on_press(self, event):
        result = self._find_handle(event.x, event.y)
        if result:
            self.dragging = result
            self.canvas.config(cursor="fleur")

    def on_drag(self, event):
        if not self.dragging:
            return
        dist, tag, xk, yk, cfg_key, htype = self.dragging
        rx, ry = self._canvas_to_rel(event.x, event.y)
        rx = max(0.0, min(1.0, rx))
        ry = max(0.0, min(1.0, ry))
        ui = self.cfg["ui"]

        if htype == "rect_corner":
            ui[cfg_key][xk] = round(rx, 3)
            ui[cfg_key][yk] = round(ry, 3)
        elif htype == "point":
            ui[cfg_key]["x"] = round(rx, 3)
            ui[cfg_key]["y"] = round(ry, 3)
        elif htype == "slot":
            ui["pokemon_slots"][cfg_key]["x"] = round(rx, 3)
            ui["pokemon_slots"][cfg_key]["y"] = round(ry, 3)
        elif htype == "hline":
            ui[cfg_key] = round(ry, 3)
            if hasattr(self, 'bar_vars') and cfg_key in self.bar_vars:
                self.bar_vars[cfg_key][0].set(ry)
                self.bar_vars[cfg_key][1].config(text=f"{ry:.3f}")
        elif htype == "vline":
            ui[cfg_key] = round(rx, 3)
            if hasattr(self, 'bar_vars') and cfg_key in self.bar_vars:
                self.bar_vars[cfg_key][0].set(rx)
                self.bar_vars[cfg_key][1].config(text=f"{rx:.3f}")

        self.coord_label.config(
            text=f"Dragging: {tag}\nx={rx:.3f}  y={ry:.3f}",
            fg="#00FF88"
        )
        self._redraw()

    def on_release(self, event):
        self.dragging = None
        self.canvas.config(cursor="crosshair")

    def on_motion(self, event):
        if self.dragging:
            return
        rx, ry = self._canvas_to_rel(event.x, event.y)
        hit = self._find_handle(event.x, event.y)
        if hit:
            self.coord_label.config(
                text=f"Handle: {hit[1]}\nx={rx:.3f}  y={ry:.3f}\n← drag to move",
                fg="#FFFF00"
            )
            self.canvas.config(cursor="fleur")
        else:
            self.coord_label.config(
                text=f"x={rx:.3f}  y={ry:.3f}",
                fg="#64748b"
            )
            self.canvas.config(cursor="crosshair")

    def _bar_slider(self, key, var):
        val = var.get()
        self.cfg["ui"][key] = round(val, 3)
        if hasattr(self, 'bar_vars') and key in self.bar_vars:
            self.bar_vars[key][1].config(text=f"{val:.3f}")
        self._redraw()

    def save(self):
        save_config(self.cfg)
        self.status.config(text="✅ Saved to calibration.json")

    def _nudge(self, dx, dy):
        """Nudge the last-clicked handle by dx, dy in relative coords."""
        if not self.dragging:
            return
        dist, tag, xk, yk, cfg_key, htype = self.dragging
        ui = self.cfg["ui"]

        if htype == "rect_corner":
            ui[cfg_key][xk] = round(max(0, min(1, ui[cfg_key][xk] + dx)), 3)
            ui[cfg_key][yk] = round(max(0, min(1, ui[cfg_key][yk] + dy)), 3)
        elif htype == "point":
            ui[cfg_key]["x"] = round(max(0, min(1, ui[cfg_key]["x"] + dx)), 3)
            ui[cfg_key]["y"] = round(max(0, min(1, ui[cfg_key]["y"] + dy)), 3)
        elif htype == "slot":
            ui["pokemon_slots"][cfg_key]["x"] = round(max(0, min(1, ui["pokemon_slots"][cfg_key]["x"] + dx)), 3)
            ui["pokemon_slots"][cfg_key]["y"] = round(max(0, min(1, ui["pokemon_slots"][cfg_key]["y"] + dy)), 3)
        elif htype == "hline":
            new_val = round(max(0, min(1, ui[cfg_key] + dy)), 3)
            ui[cfg_key] = new_val
            if hasattr(self, 'bar_vars') and cfg_key in self.bar_vars:
                self.bar_vars[cfg_key][0].set(new_val)
                self.bar_vars[cfg_key][1].config(text=f"{new_val:.3f}")
        elif htype == "vline":
            new_val = round(max(0, min(1, ui[cfg_key] + dx)), 3)
            ui[cfg_key] = new_val
            if hasattr(self, 'bar_vars') and cfg_key in self.bar_vars:
                self.bar_vars[cfg_key][0].set(new_val)
                self.bar_vars[cfg_key][1].config(text=f"{new_val:.3f}")

        self._redraw()


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1100x820")
    app = CalibrationApp(root)
    root.mainloop()