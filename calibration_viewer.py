# calibration_viewer.py — complete file (copy/paste to replace yours)

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw
import json
import logging
import os
from config import DEFAULT_CONFIG

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

RECT_REGIONS = [
    ("cp_region",           "#FF4444", "CP"),
    ("name_region",         "#44FF44", "Name"),
    ("hp_region",           "#4488FF", "HP"),
    ("hp_region_lucky",     "#00BFFF", "Lucky HP"),
    ("lucky_label_region",  "#FFD700", "Lucky Label"),
    ("dust_region",         "#FF44FF", "Dust"),
    ("type_region",         "#FF9900", "Type"),
    ("weight_region",       "#AAFFAA", "Weight"),
    ("height_region",       "#AAAAFF", "Height"),
]

REGION_DEFAULTS = {
    "hp_region_lucky":       {"x1": 0.10, "y1": 0.56, "x2": 0.90, "y2": 0.64},
    "lucky_label_region":    {"x1": 0.10, "y1": 0.18, "x2": 0.90, "y2": 0.28},
    "type_region":           {"x1": 0.10, "y1": 0.28, "x2": 0.90, "y2": 0.36},
    "weight_region":         {"x1": 0.10, "y1": 0.38, "x2": 0.55, "y2": 0.46},
    "height_region":         {"x1": 0.55, "y1": 0.38, "x2": 0.90, "y2": 0.46},
}

POINT_DEFAULTS = {
    "search_icon":         {"x": 0.90, "y": 0.06},
    "first_search_result": {"x": 0.20, "y": 0.31},
    "nickname_edit_btn":   {"x": 0.50, "y": 0.10},
    "nickname_save_btn":   {"x": 0.50, "y": 0.55},
}

TAG_DEFAULTS = {
    "tag_menu_btn":   {"x": 0.842, "y": 0.933},
    "tag_option_btn": {"x": 0.648, "y": 0.65},
    "tag_keep":       {"x": 0.50, "y": 0.35},
    "tag_transfer":   {"x": 0.50, "y": 0.45},
    "tag_review":     {"x": 0.50, "y": 0.55},
    "tag_dismiss":    {"x": 0.50, "y": 0.85},
}

TAG_FOREVER_FRIENDS = {
    "tag_menu_btn":   {"x": 0.842, "y": 0.933},
    "tag_option_btn": {"x": 0.648, "y": 0.65},
    "tag_keep":       {"x": 0.20, "y": 0.38},
    "tag_transfer":   {"x": 0.20, "y": 0.50},
    "tag_review":     {"x": 0.20, "y": 0.44},
    "tag_dismiss":    {"x": 0.50, "y": 0.85},
}

TEXT_LINES_KEYS = {
    2: [
        ("ATK Bar Y",   "atk_bar_y",        "#FF8800", "hline"),
        ("DEF Bar Y",   "def_bar_y",        "#FFCC00", "hline"),
        ("STA Bar Y",   "sta_bar_y",        "#FF0088", "hline"),
        ("Bar X Start", "bar_x_start",      "#00FFFF", "vline"),
        ("Bar X End",   "bar_x_end",        "#00CCFF", "vline"),
    ],
    3: [
        ("ATK Bar Y",   "atk_bar_y_3lines", "#FF8800", "hline"),
        ("DEF Bar Y",   "def_bar_y_3lines", "#FFCC00", "hline"),
        ("STA Bar Y",   "sta_bar_y_3lines", "#FF0088", "hline"),
        ("Bar X Start", "bar_x_start",      "#00FFFF", "vline"),
        ("Bar X End",   "bar_x_end",        "#00CCFF", "vline"),
    ],
    4: [
        ("ATK Bar Y",   "atk_bar_y_4lines", "#FF8800", "hline"),
        ("DEF Bar Y",   "def_bar_y_4lines", "#FFCC00", "hline"),
        ("STA Bar Y",   "sta_bar_y_4lines", "#FF0088", "hline"),
        ("Bar X Start", "bar_x_start",      "#00FFFF", "vline"),
        ("Bar X End",   "bar_x_end",        "#00CCFF", "vline"),
    ],
    5: [
        ("ATK Bar Y",   "atk_bar_y_5lines", "#FF8800", "hline"),
        ("DEF Bar Y",   "def_bar_y_5lines", "#FFCC00", "hline"),
        ("STA Bar Y",   "sta_bar_y_5lines", "#FF0088", "hline"),
        ("Bar X Start", "bar_x_start",      "#00FFFF", "vline"),
        ("Bar X End",   "bar_x_end",        "#00CCFF", "vline"),
    ],
}

# Click bounds for bot detection resistance — NEW
BOUNDS_DEFAULTS = {
    "appraise_button":   {"x1": 0.45, "y1": 0.90, "x2": 0.55, "y2": 0.94},
    "menu_button":       {"x1": 0.84, "y1": 0.90, "x2": 0.92, "y2": 0.94},
    "back_button":       {"x1": 0.02, "y1": 0.02, "x2": 0.10, "y2": 0.10},
    "clear_search":      {"x1": 0.88, "y1": 0.04, "x2": 0.96, "y2": 0.10},
    "search_icon":       {"x1": 0.86, "y1": 0.04, "x2": 0.94, "y2": 0.10},
    "first_search_result": {"x1": 0.12, "y1": 0.25, "x2": 0.32, "y2": 0.35},
    "nickname_edit_btn": {"x1": 0.45, "y1": 0.08, "x2": 0.55, "y2": 0.14},
    "nickname_save_btn": {"x1": 0.45, "y1": 0.52, "x2": 0.55, "y2": 0.58},
    "tag_menu_btn":      {"x1": 0.80, "y1": 0.91, "x2": 0.90, "y2": 0.96},
    "tag_option_btn":    {"x1": 0.60, "y1": 0.62, "x2": 0.70, "y2": 0.68},
    "tag_keep":          {"x1": 0.45, "y1": 0.33, "x2": 0.55, "y2": 0.37},
    "tag_transfer":      {"x1": 0.45, "y1": 0.43, "x2": 0.55, "y2": 0.47},
    "tag_review":        {"x1": 0.45, "y1": 0.53, "x2": 0.55, "y2": 0.57},
    "tag_dismiss":       {"x1": 0.45, "y1": 0.83, "x2": 0.55, "y2": 0.87},
}
# UNIQUE color for each bounds element — easy to distinguish
BOUNDS_COLORS = {
    "appraise_button":        "#FF0000",  # Red
    "menu_button":            "#00FF00",  # Green
    "back_button":            "#0000FF",  # Blue
    "clear_search":           "#FFFF00",  # Yellow
    "search_icon":            "#FF00FF",  # Magenta
    "first_search_result":    "#00FFFF",  # Cyan
    "nickname_edit_btn":      "#FFAA00",  # Orange
    "nickname_save_btn":      "#AA00FF",  # Purple
    "tag_menu_btn":           "#FF5555",  # Light Red
    "tag_option_btn":         "#55FF55",  # Light Green
    "tag_keep":               "#5555FF",  # Light Blue
    "tag_transfer":           "#FFFF55",  # Light Yellow
    "tag_review":             "#FF55FF",  # Light Magenta
    "tag_dismiss":            "#55FFFF",  # Light Cyan
}
BOUNDS_KEYS = [
    ("appraise_button",        "Appraise Btn"),
    ("menu_button",            "Menu Btn"),
    ("back_button",            "Back Btn"),
    ("clear_search",           "Clear Search"),
    ("search_icon",            "Search Icon"),
    ("first_search_result",    "1st Result"),
    ("nickname_edit_btn",      "Nick Edit"),
    ("nickname_save_btn",      "Nick Save"),
    ("tag_menu_btn",           "Tag Menu"),
    ("tag_option_btn",         "Tag Option"),
    ("tag_keep",               "Tag Keep"),
    ("tag_transfer",           "Tag Transfer"),
    ("tag_review",             "Tag Review"),
    ("tag_dismiss",            "Tag Dismiss"),
]


def load_config():
    logger.debug("Loading config from %s", CONFIG_FILE)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    else:
        logger.info("%s not found; creating calibration from defaults.", CONFIG_FILE)
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))

    ui = cfg.setdefault("ui", {})
    account = cfg.setdefault("account", {})
    layouts = cfg.setdefault("tag_layouts", {})

    account.setdefault("forever_friends_enabled", False)
    ui.setdefault("text_lines_layout", 2)

    for key, val in [
        ("atk_bar_y", 0.774), ("def_bar_y", 0.815), ("sta_bar_y", 0.857),
        ("atk_bar_y_3lines", 0.749), ("def_bar_y_3lines", 0.787), ("sta_bar_y_3lines", 0.830),
        ("atk_bar_y_4lines", 0.721), ("def_bar_y_4lines", 0.760), ("sta_bar_y_4lines", 0.802),
        ("atk_bar_y_5lines", 0.694), ("def_bar_y_5lines", 0.733), ("sta_bar_y_5lines", 0.775),
        ("bar_x_start", 0.132), ("bar_x_end", 0.471),
    ]:
        ui.setdefault(key, val)

    for key, default in REGION_DEFAULTS.items():
        if key not in ui:
            ui[key] = dict(default)

    for key, default in POINT_DEFAULTS.items():
        if key not in ui:
            ui[key] = dict(default)

    # NEW — click bounds
    bounds = cfg.setdefault("ui_bounds", {})
    for key, default in BOUNDS_DEFAULTS.items():
        if key not in bounds:
            bounds[key] = dict(default)

    default_layout = layouts.setdefault("default", {})
    ff_layout = layouts.setdefault("ff", {})
    for key, default in TAG_DEFAULTS.items():
        if key not in default_layout:
            default_layout[key] = default
    for key, default in TAG_FOREVER_FRIENDS.items():
        if key not in ff_layout:
            ff_layout[key] = default

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
        self.bar_vars = {}

        self._build_ui()
        self.refresh()

    def get_text_lines_layout(self):
        return int(self.cfg["ui"].get("text_lines_layout", 2))

    def get_active_bar_keys(self):
        return TEXT_LINES_KEYS.get(self.get_text_lines_layout(), TEXT_LINES_KEYS[2])

    def forever_friends_enabled(self):
        return bool(self.cfg.get("account", {}).get("forever_friends_enabled", False))

    def active_tag_handles(self):
        return [
            ("tag_menu_btn",   "#FFFFFF", "Tag Menu"),
            ("tag_option_btn", "#00FFFF", "Tag Option"),
            ("tag_keep",       "#00FF44", "Tag Keep"),
            ("tag_transfer",   "#FF3333", "Tag Transfer"),
            ("tag_review",     "#FF9900", "Tag Review"),
            ("tag_dismiss",    "#CCCCCC", "Tag Dismiss"),
        ]

    def current_tag_legend(self):
        if self.forever_friends_enabled():
            return [
                ("#00FFFF", "Tag Option (⋮)"),
                ("#00FF44", "Tag Keep (FF)"),
                ("#FF3333", "Tag Transfer (FF)"),
                ("#FF9900", "Tag Review (FF)"),
                ("#CCCCCC", "Tag Dismiss"),
            ]
        return [
            ("#00FFFF", "Tag Option (⋮)"),
            ("#00FF44", "Tag Keep"),
            ("#FF3333", "Tag Transfer"),
            ("#FF9900", "Tag Review"),
            ("#CCCCCC", "Tag Dismiss"),
        ]

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
        self.status = tk.Label(bar, text="", fg="#94a3b8", bg="#16213e", font=("Helvetica", 10))
        self.status.pack(side="right", padx=12)

        main = tk.Frame(self.root, bg="#1a1a2e")
        main.pack(fill="both", expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(main, bg="#0d0d1a", cursor="crosshair", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Left>", lambda e: self._nudge(-0.001, 0))
        self.canvas.bind("<Right>", lambda e: self._nudge(0.001, 0))
        self.canvas.bind("<Up>", lambda e: self._nudge(0, -0.001))
        self.canvas.bind("<Down>", lambda e: self._nudge(0, 0.001))
        self.canvas.bind("<Shift-Left>", lambda e: self._nudge(-0.01, 0))
        self.canvas.bind("<Shift-Right>", lambda e: self._nudge(0.01, 0))
        self.canvas.bind("<Shift-Up>", lambda e: self._nudge(0, -0.01))
        self.canvas.bind("<Shift-Down>", lambda e: self._nudge(0, 0.01))
        self.coord_label = tk.Label(
            panel,
            text="Hover or click on image\nto see coordinates",
            fg="#64748b",
            bg="#16213e",
            font=("Courier", 10),
            justify="center",
        )
        self.coord_label.pack(side="bottom", pady=6)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.focus_set()

        panel = tk.Frame(main, bg="#16213e", width=270)
        panel.pack(side="right", fill="y", padx=(8, 0))
        panel.pack_propagate(False)

        ff_row = tk.Frame(panel, bg="#16213e")
        ff_row.pack(fill="x", padx=8, pady=(10, 2))
        self.ff_var = tk.BooleanVar(value=self.forever_friends_enabled())
        tk.Checkbutton(ff_row, text="Forever Friends account", variable=self.ff_var,
                       command=self._on_ff_toggle, fg="#e2e8f0", bg="#16213e",
                       selectcolor="#0f3460", activebackground="#16213e",
                       activeforeground="#e2e8f0", font=("Helvetica", 10, "bold")).pack(anchor="w")

        top = tk.Frame(panel, bg="#16213e")
        top.pack(fill="x", padx=8, pady=(10, 6))
        tk.Label(top, text="Category:", fg="#e2e8f0", bg="#16213e", font=("Helvetica", 10, "bold")).pack(side="left")

        self.category_var = tk.StringVar(value="IV Bars")
        categories = ["IV Bars", "OCR Regions", "Buttons", "Slots", "Tags", "Click Bounds", "Legend"]
        self.category_menu = ttk.Combobox(top, textvariable=self.category_var, values=categories,
                                           state="readonly", width=15)
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
            elif cat == "Tags":
                self._build_category_legend(f, self.current_tag_legend())
            elif cat == "Click Bounds":
                # Show each bounds with its unique color
                return [(BOUNDS_COLORS[key], label) for key, label in BOUNDS_KEYS]
            elif cat == "Legend":
                legend = []
                for subset in ["OCR Regions", "Buttons", "Slots"]:
                    legend.extend(self._legend_for_category(subset))
                legend.extend(self.current_tag_legend())
                legend.extend([
                    ("#FF8800", "ATK bar (drag vert)"),
                    ("#FFCC00", "DEF bar (drag vert)"),
                    ("#FF0088", "STA bar (drag vert)"),
                    ("#00FFFF", "Bar X start/end (drag horiz)"),
                ])
                self._build_category_legend(f, legend)
            else:
                self._build_category_legend(f, self._legend_for_category(cat))

        ttk.Separator(panel, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # self.coord_label = tk.Label(panel, text="Hover or click on image\nto see coordinates",
        #                              fg="#64748b", bg="#16213e", font=("Courier", 10), justify="center")
        # self.coord_label.pack(pady=6)

        self.show_category()

    def _legend_for_category(self, cat):
        if cat == "OCR Regions":
            return [
                ("#FF4444", "CP region corners"),
                ("#44FF44", "Name region corners"),
                ("#4488FF", "HP region corners"),
                ("#00BFFF", "Lucky HP region corners"),
                ("#FFD700", "Lucky Label region corners"),
                ("#FF44FF", "Dust region corners"),
                ("#FF9900", "Type region corners"),
                ("#AAFFAA", "Weight region corners"),
                ("#AAAAFF", "Height region corners"),
            ]
        elif cat == "Buttons":
            return [
                ("#FFFFFF", "Menu button"),
                ("#FFFF00", "Appraise button"),
                ("#FF6600", "Back button"),
                ("#FF6600", "Clear Search"),
                ("#00CCFF", "Search icon"),
                ("#CCFF00", "First search result"),
                ("#FF00AA", "Nickname edit"),
                ("#AA00FF", "Nickname save"),
            ]
        elif cat == "Slots":
            return [("#00FF88", "Pokémon slots")]
        elif cat == "Click Bounds":
            return [(color, label) for _, label in BOUNDS_KEYS for color in ["#FF88FF"]]
        return []

    def _build_category_legend(self, parent, subset):
        lf = tk.Frame(parent, bg="#16213e")
        lf.pack(fill="x", pady=4)
        tk.Label(lf, text="Drag colored handles on image", fg="#94a3b8", bg="#16213e", font=("Helvetica", 9)).pack(pady=(0, 8))
        for color, text in subset:
            r = tk.Frame(lf, bg="#16213e")
            r.pack(fill="x", pady=1)
            tk.Label(r, bg=color, width=2, height=1).pack(side="left", padx=(0, 5))
            tk.Label(r, text=text, fg="#cbd5e1", bg="#16213e", font=("Helvetica", 8)).pack(side="left")

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

        tk.Label(parent, text="Bar Positions (drag or use sliders)", font=("Helvetica", 10, "bold"),
                 fg="#e2e8f0", bg="#16213e", justify="center").pack(pady=(10, 4))

        self.bar_vars = {}
        for label, key, color, _ in self.get_active_bar_keys():
            row = tk.Frame(parent, bg="#16213e")
            row.pack(fill="x", pady=3)
            tk.Label(row, bg=color, width=2).pack(side="left", padx=(0, 6))
            tk.Label(row, text=label, fg="#e2e8f0", bg="#16213e", font=("Helvetica", 9), width=11, anchor="w").pack(side="left")
            val = self.cfg["ui"].get(key, 0.5)
            var = tk.DoubleVar(value=val)
            sl = tk.Scale(row, from_=0.0, to=1.0, resolution=0.001, orient="horizontal", variable=var,
                          bg="#16213e", fg="#e2e8f0", troughcolor="#0f3460", highlightthickness=0,
                          length=100, command=lambda v, k=key, dv=var: self._bar_slider(k, dv))
            sl.pack(side="left")
            lbl = tk.Label(row, text=f"{val:.3f}", fg="#94a3b8", bg="#16213e", font=("Helvetica", 8), width=5)
            lbl.pack(side="left")
            self.bar_vars[key] = (var, lbl)

    def _build_bounds_panel(self, parent):
        for w in parent.winfo_children():
            w.destroy()
        tk.Label(parent, text="Click Bounds — drag rectangles around each button",
                 fg="#e2e8f0", bg="#16213e", font=("Helvetica", 9, "bold"), justify="center").pack(pady=(4, 8))
        tk.Label(parent, text="Jitter will be clamped to these bounds\nfor bot-detection resistance",
                 fg="#94a3b8", bg="#16213e", font=("Helvetica", 8), justify="center").pack(pady=(0, 10))

        for key, label in BOUNDS_KEYS:
            row = tk.Frame(parent, bg="#16213e")
            row.pack(fill="x", pady=1, padx=4)
            color = "#FF88FF"
            tk.Label(row, bg=color, width=2).pack(side="left", padx=(0, 6))
            tk.Label(row, text=label, fg="#e2e8f0", bg="#16213e", font=("Helvetica", 8), width=12, anchor="w").pack(side="left")
            b = self.cfg.get("ui_bounds", {}).get(key, {})
            txt = f"x1={b.get('x1',0):.2f} y1={b.get('y1',0):.2f}  x2={b.get('x2',1):.2f} y2={b.get('y2',0):.2f}"
            tk.Label(row, text=txt, fg="#64748b", bg="#16213e", font=("Courier", 7)).pack(side="left")

    def _on_ff_toggle(self):
        self.cfg.setdefault("account", {})
        self.cfg["account"]["forever_friends_enabled"] = bool(self.ff_var.get())
        self._rebuild_tags_panel()
        self._redraw()

    def _rebuild_tags_panel(self):
        frame = self.category_frames.get("Tags")
        if not frame:
            return
        for w in frame.winfo_children():
            w.destroy()
        self._build_category_legend(frame, self.current_tag_legend())

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
            self.status.config(text=f"{self.img_w}×{self.img_h} | scale {self.display_scale:.2f}× | drag handles to adjust, Save when done")
        except Exception as e:
            self.status.config(text=f"Error: {e}")
            logger.exception("Refresh failed")

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
        draw = ImageDraw.Draw(img, "RGBA")
        w, h = img.size
        ui = self.cfg["ui"]
        bounds = self.cfg.get("ui_bounds", {})
        cat = self.category_var.get()

        def draw_rect(key, color, fill_alpha=15, outline_alpha=160):
            r = ui.get(key)
            if not r:
                return
            x1, y1 = int(r["x1"] * w), int(r["y1"] * h)
            x2, y2 = int(r["x2"] * w), int(r["y2"] * h)
            hc = color.lstrip("#")
            rc, gc, bc = tuple(int(hc[i:i+2], 16) for i in (0, 2, 4))
            draw.rectangle([x1, y1, x2, y2], outline=(rc, gc, bc, outline_alpha), width=2)

        def draw_bounds(key, color, fill_alpha=0, outline_alpha=255):
            """HOLLOW bounds — no fill, thick outline"""
            b = bounds.get(key)
            if not b:
                return
            x1, y1 = int(b["x1"] * w), int(b["y1"] * h)
            x2, y2 = int(b["x2"] * w), int(b["y2"] * h)
            hc = color.lstrip("#")
            rc, gc, bc = tuple(int(hc[i:i + 2], 16) for i in (0, 2, 4))
            # Hollow rectangle - only outline, no fill
            draw.rectangle([x1, y1, x2, y2], outline=(rc, gc, bc, outline_alpha), width=3)
            # Center crosshair
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            draw.line([(cx - 8, cy), (cx + 8, cy)], fill=(rc, gc, bc, 255), width=2)
            draw.line([(cx, cy - 8), (cx, cy + 8)], fill=(rc, gc, bc, 255), width=2)

        if cat in ("OCR Regions", "Legend"):
            for region_key, color, _ in RECT_REGIONS:
                draw_rect(region_key, color)

        if cat in ("Click Bounds", "Legend"):
            for key, _ in BOUNDS_KEYS:
                draw_bounds(key, "#FF88FF")

        if cat in ("IV Bars", "Legend"):
            for label, key, color, btype in self.get_active_bar_keys():
                val = ui.get(key)
                if val is None:
                    continue
                hc = color.lstrip("#")
                rc, gc, bc = tuple(int(hc[i:i+2], 16) for i in (0, 2, 4))
                if btype == "hline":
                    y = int(val * h)
                    draw.line([(0, y), (w, y)], fill=(rc, gc, bc, 120), width=2)
                elif btype == "vline":
                    x = int(val * w)
                    draw.line([(x, 0), (x, h)], fill=(rc, gc, bc, 120), width=2)

    def _draw_handles_on_canvas(self):
        ui = self.cfg["ui"]
        bounds = self.cfg.get("ui_bounds", {})
        tag_layout = self.cfg.get("tag_layouts", {}).get("ff" if self.forever_friends_enabled() else "default", {})
        s = self.display_scale
        r = self.HANDLE_RADIUS
        cat = self.category_var.get()

        def canvas_dot(x_rel, y_rel, color, tag, label=""):
            cx = int(x_rel * self.img_w * s)
            cy = int(y_rel * self.img_h * s)
            self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline="white", width=1, tags=tag)
            if label:
                self.canvas.create_text(cx+r+3, cy, text=label, fill=color, font=("Helvetica", 8), anchor="w", tags=tag+"_lbl")

        if cat in ("OCR Regions", "Legend"):
            for region_key, color, short in RECT_REGIONS:
                reg = ui.get(region_key, {})
                canvas_dot(reg.get("x1", 0), reg.get("y1", 0), color, f"rect_tl_{region_key}", f"{short} ↖")
                canvas_dot(reg.get("x2", 1), reg.get("y2", 1), color, f"rect_br_{region_key}", f"{short} ↘")

        if cat in ("Buttons", "Legend"):
            for cfg_key, color, label in [
                ("menu_button",     "#FFFFFF", "Menu"),
                ("appraise_button", "#FFFF00", "Appraise"),
                ("back_button",     "#FF6600", "Back"),
                ("clear_search",    "#FF6600", "Clear"),
                ("search_icon",     "#00CCFF", "Search"),
                ("first_search_result", "#CCFF00", "1st Res"),
                ("nickname_edit_btn", "#FF00AA", "Nick Edit"),
                ("nickname_save_btn", "#AA00FF", "Nick Save"),
            ]:
                p = ui.get(cfg_key, {})
                canvas_dot(p.get("x", 0.5), p.get("y", 0.5), color, f"point_{cfg_key}", label)

        if cat in ("Tags", "Legend"):
            for cfg_key, color, label in self.active_tag_handles():
                p = tag_layout.get(cfg_key, {})
                canvas_dot(p.get("x", 0.5), p.get("y", 0.5), color, f"point_tag_{cfg_key}", label)

        if cat in ("Slots", "Legend"):
            for i, slot in enumerate(ui.get("pokemon_slots", [])):
                canvas_dot(slot.get("x", 0), slot.get("y", 0), "#00FF88", f"slot_{i}", f"Slot {i+1}")

        if cat in ("IV Bars", "Legend"):
            for label, key, color, btype in self.get_active_bar_keys():
                val = ui.get(key)
                if val is None:
                    continue
                if btype == "hline":
                    cx, cy = int(0.5 * self.img_w * s), int(val * self.img_h * s)
                else:
                    cx, cy = int(val * self.img_w * s), int(0.5 * self.img_h * s)
                self.canvas.create_rectangle(cx-r, cy-r, cx+r, cy+r, fill=color, outline="white", width=1, tags=f"bar_{key}")
                self.canvas.create_text(cx+r+3, cy, text=label, fill=color, font=("Helvetica", 8), anchor="w", tags=f"bar_{key}_lbl")

        if cat in ("Click Bounds", "Legend"):
            for key, label in BOUNDS_KEYS:
                b = bounds.get(key, {})
                if not b:
                    continue
                color = BOUNDS_COLORS[key]  # Unique color per element
                x1 = int(b.get("x1", 0) * self.img_w * s)
                y1 = int(b.get("y1", 0) * self.img_h * s)
                x2 = int(b.get("x2", 1) * self.img_w * s)
                y2 = int(b.get("y2", 1) * self.img_h * s)
                # Draggable corners with unique color
                canvas_dot(b.get("x1", 0), b.get("y1", 0), color, f"bounds_tl_{key}", f"{label} ↖")
                canvas_dot(b.get("x2", 1), b.get("y2", 1), color, f"bounds_br_{key}", f"{label} ↘")
                # HOLLOW rectangle outline on canvas
                self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=3, tags=f"bounds_rect_{key}")

    def _canvas_to_rel(self, cx, cy):
        s = self.display_scale
        return cx / (self.img_w * s), cy / (self.img_h * s)

    def _find_handle(self, cx, cy):
        ui = self.cfg["ui"]
        bounds = self.cfg.get("ui_bounds", {})
        tag_layout = self.cfg.get("tag_layouts", {}).get("ff" if self.forever_friends_enabled() else "default", {})
        s = self.display_scale
        r = self.HANDLE_RADIUS + 4
        cat = self.category_var.get()
        candidates = []

        if cat in ("OCR Regions", "Legend"):
            for region_key in [k for k, _, _ in RECT_REGIONS]:
                reg = ui.get(region_key, {})
                for corner, xk, yk in [("tl", "x1", "y1"), ("br", "x2", "y2")]:
                    hx = reg.get(xk, 0) * self.img_w * s
                    hy = reg.get(yk, 0) * self.img_h * s
                    dist = abs(cx - hx) + abs(cy - hy)
                    if dist < r * 2:
                        candidates.append((dist, f"rect_{corner}_{region_key}", xk, yk, region_key, "rect_corner"))

        if cat in ("Buttons", "Legend"):
            for cfg_key in ["menu_button", "appraise_button", "back_button", "clear_search",
                            "search_icon", "first_search_result", "nickname_edit_btn", "nickname_save_btn"]:
                p = ui.get(cfg_key, {})
                hx, hy = p.get("x", 0.5) * self.img_w * s, p.get("y", 0.5) * self.img_h * s
                dist = abs(cx - hx) + abs(cy - hy)
                if dist < r * 2:
                    candidates.append((dist, f"point_{cfg_key}", "x", "y", cfg_key, "point"))

        if cat in ("Tags", "Legend"):
            for cfg_key, _, _ in self.active_tag_handles():
                p = tag_layout.get(cfg_key, {})
                hx, hy = p.get("x", 0.5) * self.img_w * s, p.get("y", 0.5) * self.img_h * s
                dist = abs(cx - hx) + abs(cy - hy)
                if dist < r * 2:
                    candidates.append((dist, f"point_tag_{cfg_key}", "x", "y", cfg_key, "point_tag"))

        if cat in ("Slots", "Legend"):
            for i, slot in enumerate(ui.get("pokemon_slots", [])):
                hx, hy = slot.get("x", 0) * self.img_w * s, slot.get("y", 0) * self.img_h * s
                dist = abs(cx - hx) + abs(cy - hy)
                if dist < r * 2:
                    candidates.append((dist, f"slot_{i}", "x", "y", i, "slot"))

        if cat in ("IV Bars", "Legend"):
            for label, key, color, btype in self.get_active_bar_keys():
                val = ui.get(key)
                if val is None:
                    continue
                if btype == "hline":
                    dist = abs(cy - (val * self.img_h * s))
                else:
                    dist = abs(cx - (val * self.img_w * s))
                if dist < r * 2:
                    candidates.append((dist, f"bar_{key}", None, None, key, btype))

        if cat in ("Click Bounds", "Legend"):
            for key, _ in BOUNDS_KEYS:
                b = bounds.get(key, {})
                for corner, xk, yk in [("tl", "x1", "y1"), ("br", "x2", "y2")]:
                    hx = b.get(xk, 0) * self.img_w * s
                    hy = b.get(yk, 0) * self.img_h * s
                    dist = abs(cx - hx) + abs(cy - hy)
                    if dist < r * 2:
                        candidates.append((dist, f"bounds_{corner}_{key}", xk, yk, key, "bounds_corner"))

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
        bounds = self.cfg.setdefault("ui_bounds", {})

        if htype == "rect_corner":
            ui[cfg_key][xk] = round(rx, 3)
            ui[cfg_key][yk] = round(ry, 3)
        elif htype == "point":
            ui[cfg_key]["x"] = round(rx, 3)
            ui[cfg_key]["y"] = round(ry, 3)
        elif htype == "point_tag":
            active = "ff" if self.forever_friends_enabled() else "default"
            self.cfg["tag_layouts"][active][cfg_key]["x"] = round(rx, 3)
            self.cfg["tag_layouts"][active][cfg_key]["y"] = round(ry, 3)
        elif htype == "slot":
            ui["pokemon_slots"][cfg_key]["x"] = round(rx, 3)
            ui["pokemon_slots"][cfg_key]["y"] = round(ry, 3)
        elif htype == "hline":
            ui[cfg_key] = round(ry, 3)
            if cfg_key in self.bar_vars:
                self.bar_vars[cfg_key][0].set(ry)
                self.bar_vars[cfg_key][1].config(text=f"{ry:.3f}")
        elif htype == "vline":
            ui[cfg_key] = round(rx, 3)
            if cfg_key in self.bar_vars:
                self.bar_vars[cfg_key][0].set(rx)
                self.bar_vars[cfg_key][1].config(text=f"{rx:.3f}")
        elif htype == "bounds_corner":
            bounds[cfg_key][xk] = round(rx, 3)
            bounds[cfg_key][yk] = round(ry, 3)

        if hasattr(self, "coord_label"):
            self.coord_label.config(
                text=f"Dragging: {tag}\nx={rx:.3f}  y={ry:.3f}",
                fg="#00FF88",
            )
        self._redraw()

    def on_release(self, event):
        self.dragging = None
        self.canvas.config(cursor="crosshair")

    def on_motion(self, event):
        # Motion events can arrive while Tkinter is still building the UI.
        if self.dragging or not hasattr(self, "coord_label"):
            return

        rx, ry = self._canvas_to_rel(event.x, event.y)
        hit = self._find_handle(event.x, event.y)

        if hit:
            self.coord_label.config(
                text=f"Handle: {hit[1]}\nx={rx:.3f}  y={ry:.3f}\n← drag to move",
                fg="#FFFF00",
            )
            self.canvas.config(cursor="fleur")
        else:
            self.coord_label.config(
                text=f"x={rx:.3f}  y={ry:.3f}",
                fg="#64748b",
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
        if not self.dragging:
            return
        dist, tag, xk, yk, cfg_key, htype = self.dragging
        ui = self.cfg["ui"]
        bounds = self.cfg.setdefault("ui_bounds", {})
        tag_layout = self.cfg["tag_layouts"].get("ff" if self.forever_friends_enabled() else "default", {})

        if htype == "rect_corner":
            ui[cfg_key][xk] = round(max(0, min(1, ui[cfg_key][xk] + dx)), 3)
            ui[cfg_key][yk] = round(max(0, min(1, ui[cfg_key][yk] + dy)), 3)
        elif htype == "point":
            ui[cfg_key]["x"] = round(max(0, min(1, ui[cfg_key]["x"] + dx)), 3)
            ui[cfg_key]["y"] = round(max(0, min(1, ui[cfg_key]["y"] + dy)), 3)
        elif htype == "point_tag":
            tag_layout[cfg_key]["x"] = round(max(0, min(1, tag_layout[cfg_key]["x"] + dx)), 3)
            tag_layout[cfg_key]["y"] = round(max(0, min(1, tag_layout[cfg_key]["y"] + dy)), 3)
        elif htype == "slot":
            ui["pokemon_slots"][cfg_key]["x"] = round(max(0, min(1, ui["pokemon_slots"][cfg_key]["x"] + dx)), 3)
            ui["pokemon_slots"][cfg_key]["y"] = round(max(0, min(1, ui["pokemon_slots"][cfg_key]["y"] + dy)), 3)
        elif htype == "hline":
            ui[cfg_key] = round(max(0, min(1, ui[cfg_key] + dy)), 3)
            if hasattr(self, 'bar_vars') and cfg_key in self.bar_vars:
                self.bar_vars[cfg_key][0].set(ui[cfg_key])
                self.bar_vars[cfg_key][1].config(text=f"{ui[cfg_key]:.3f}")
        elif htype == "vline":
            ui[cfg_key] = round(max(0, min(1, ui[cfg_key] + dx)), 3)
            if hasattr(self, 'bar_vars') and cfg_key in self.bar_vars:
                self.bar_vars[cfg_key][0].set(ui[cfg_key])
                self.bar_vars[cfg_key][1].config(text=f"{ui[cfg_key]:.3f}")
        elif htype == "bounds_corner":
            bounds[cfg_key][xk] = round(max(0, min(1, bounds[cfg_key][xk] + dx)), 3)
            bounds[cfg_key][yk] = round(max(0, min(1, bounds[cfg_key][yk] + dy)), 3)

        self._redraw()

    def show_category(self):
        selected = self.category_var.get()
        for frame in self.category_frames.values():
            frame.pack_forget()
        self.category_frames[selected].pack(fill="both", expand=True, padx=8, pady=4)
        self._redraw()


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1100x820")
    app = CalibrationApp(root)
    root.mainloop()