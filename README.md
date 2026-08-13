# Pokémon GO IV Cataloger

Automated Pokémon GO IV scanning, appraisal parsing, PvP ranking, and in-game tagging using native iPhone Mirroring on macOS. No jailbreak, no modified client, no hardware robot.

---

## 1. What This Bot Does

This project turns the iPhone Mirroring window on macOS Sequoia into a fully automated IV cataloging pipeline:

- Captures **pixel-perfect** frames from the iPhone Mirroring window via Quartz.
- Reads **name, CP, HP, type, height, weight, stardust, and caught date** using OCR.
- Measures appraisal bars to recover **exact ATK / DEF / STA IVs (0–15)**.
- Computes **exact IV percentage, level**, and **PvP stat product rankings** for Great / Ultra / Master League, including all evolutions.
- Writes everything into a local **SQLite database (`pokemon_ivs.db`)** with flags for review, displacement, and demotion.[file:1][file:2]
- Applies **in-game tags** (keep / transfer / review) in real time using calibrated tap coordinates.

Two main operating modes:

- `catalog` — scan the **age 0** box and catalog an entire page of fresh catches.
- `newcatch` — appraise and tag **only the most recent catch**, then stop.[file:2]

---

## 2. High-Level Architecture

```
iPhone Mirroring (macOS Sequoia)
         │
         ▼
Quartz window capture (screen_capture.py)
         │
         ▼
Base-screen OCR & parsing
  - Apple Vision OCR (primary)
  - Tesseract (description / fallback)
  - CP / HP / type / height / weight / dust / caught date
         │
         ▼
Appraisal bar analysis
  - Color segmentation of ATK / DEF / STA bars
  - Layout-aware bar cropping (2–5 description lines)
         │
         ▼
IV & PvP engine
  - Exact IVs + level
  - League rankings for current form + all evolutions
         │
         ▼
SQLite database (database.py)
  - `pokemon` rows + evolution rankings
  - displaced / demoted / needs_review flags
         │
         ▼
Tagging & cleanup
  - Pass 1: live catalog + tagging
  - Micro Pass 2: demotion cleanup in-game (re-tags demoted entries)
```

Anti-detection behaviours baked in:

- Gaussian **tap jitter** and **Bezier mouse paths** (human-like motion).
- Log-normal **timing variation** on all taps, swipes, and appraisals.
- Randomized **short / long breaks** and configurable session length ranges.
- A **FreezeDetector** that watches Mirroring for frozen frames and attempts recovery (center tap, back button, etc.).[file:2]

---

## 3. Installation & Setup

### 3.1 Requirements

- macOS **Sequoia** on Apple Silicon (M1+).
- iPhone with **iPhone Mirroring** enabled over USB.
- Python **3.10+**.

### 3.2 Install Dependencies

```bash
pip install -r requirements.txt
```

Apple Vision runs via `pyobjc` on Apple Silicon. `pytesseract` is used for description-line detection and as a fallback; it is optional.[file:1][file:2]

### 3.3 Download Base Stats

Fetch base ATK / DEF / STA for all species:

```bash
python download_data.py
```

This script pulls from Pokémon GO GameMaster and falls back to PokeAPI if needed, then writes `data/base_stats.json`.[file:1]

### 3.4 Build Species Lookup

Generate a lookup table for name → types / height / weight:

```bash
python build_species_lookup.py
```

This creates `data/species_lookup.json` by scraping Pokemondb.net for height/weight and type information.[file:1]

### 3.5 Calibrate UI Coordinates

Open **iPhone Mirroring** and navigate to your Pokémon storage, then run:

```bash
python calibrate.py
```

`calibrate.py`:

- Detects the iPhone Mirroring window (`get_mirror_window_bounds`).
- Captures a reference screenshot and saves `calibration_screenshot.png`.
- Lets you either accept default UI coordinates or input relative coordinates (0.0–1.0) for taps and bar positions.
- Saves the configuration to `calibration.json` and merges with `config.DEFAULT_CONFIG`.[file:1]

Re-run calibration whenever you change iPhone model or monitor resolution.

---

## 4. Running the Bot

The main entry point is `main.py`.

```bash
python main.py [options]
```

### 4.1 Command-Line Options

`parse_args()` supports:[file:2]

| Option | Values | Description |
| :----- | :----- | :---------- |
| `--limit N` | integer | Stop after scanning at most `N` Pokémon (0 = unlimited). |
| `--debug` | flag | Save intermediate screenshots (CP region, name region, bar strip, etc.) to `screenshots/`. |
| `--dry-run` | flag | Run the full OCR + evaluation pipeline **without** tapping or tagging in-game. |
| `--mode` | `catalog` / `newcatch` | `catalog`: scan the age 0 box; `newcatch`: appraise and tag only the most recent catch. |
| `--tag-layout` | `default` / `ff` | Choose which **in-game tag menu layout** to use for keep/transfer/review taps. |

### 4.2 Session Controls

`PauseController` binds hotkeys:[file:2]

- **F9** — pause/resume the current session.
- **F10** — emergency stop (clean shutdown).
- **F8** — **reprocess** the last scanned Pokémon in-place (re-run OCR/IV/PvP and update its row).

Emergency mouse-kill is also supported by moving the cursor to a configured corner.

### 4.3 Modes

#### Catalog Mode (`--mode catalog`)

- Assumes the in-game search is set to **age 0**.
- Taps the **first slot** in `ui["pokemon_slots"]` and starts scanning forward.
- For each Pokémon, `scan_one_pokemon()`:
  - Captures the base screen (CP, HP, type, description).
  - Uses OCR + VLM to reconcile CP and description lines.
  - Opens the appraisal screen, reads IV bars, and computes IVs + PvP ranks.
  - Evaluates the catch (keep/transfer/review) and writes to the database.
  - Applies the appropriate **in-game tag**.
  - Taps the next arrow to advance.[file:2]

#### New Catch Mode (`--mode newcatch`)

- Taps the **last slot** in `ui["pokemon_slots"]` (most recent Pokémon).
- Runs a single `scan_one_pokemon()` cycle.
- Tags the Pokémon and then exits without swiping further.[file:2]

---

## 5. OCR, VLM, and Robustness

### 5.1 Description Line Detection

The helper `detect_description_lines()`:

- Crops and upscales the name/description region.
- Calls Tesseract (`image_to_data`) to detect individual text lines.
- Filters low-confidence or tiny hits and excludes loading-bar artifacts by bounding-box height.
- Anchors on words like **"caught"**, **"around"**, or the **date**, then expands up/down within a dynamic vertical gap.
- Produces `num_lines` (2–5) and concatenated description text.

The number of lines drives which appraisal bar layout to use (different Y coordinates for 3/4/5-line layouts).[file:2]

### 5.2 CP OCR + VLM Reconciliation

For CP parsing, the bot:

- Re-tries OCR up to `max_attempts` (default 5) via `retry_read_cp()`.
- Crops a tight CP sub-region, upscales 3×, and re-OCRs.
- Launches a **VLM CP consensus** job in a background thread, feeding multiple CP frames to `vision_agent`.
- Reconciles OCR vs VLM using `_reconcile_cp()`:
  - Treats slashes/backslashes as misread `7` and prefers OCR in that case.
  - Detects extraneous leading/trailing digits and discards them.
  - Falls back to VLM when lengths disagree and OCR looks like it has the stray digit.[file:2]

### 5.3 Base-Screen VLM Fallback

If base CP/HP/type parsing looks suspect (`_is_valid_base_parse()` fails), the bot:

- Calls `vision_agent.analyze_base_screen()`.
- Selectively trusts VLM fields when confidence ≥ 0.75 (HP, primary type, height, weight).
- Logs confidence and falls back to OCR when VLM is uncertain.

### 5.4 Appraisal-Screen VLM Fallbacks

For appraisal parsing:

- Uses `resolvespeciesname(img, ui, cp, typetext)` on the name region.
- Reads IV bars from a dynamic bar strip that compensates for 2–5 description lines.
- If name or bars remain unresolved, calls `vision_agent.analyze_appraisal_screen()` and `vision_agent.extract_bar_values()`.
- As a **last resort**, uses `vision_agent.recover_failed_parse()` to fix name, bars, and CP when everything else fails.

The goal is to either obtain trustworthy `(name, ATK, DEF, STA)` or explicitly flag the record for review.

### 5.5 Freeze Detection & Recovery

`FreezeDetector` monitors tiny grayscale downscaled frames for changes. When the screen appears frozen:

- Attempts a center tap to wake Mirroring.
- Escalates to tapping the back button.
- Aborts the session only if multiple recovery attempts fail.

Freeze handling is used both in Pass 1 and in Micro Pass 2 cleanup.[file:2]

---

## 6. Database, Evaluation, and Tagging

### 6.1 Database Schema

`database.py` initializes `pokemon_ivs.db` and ensures columns exist:[file:1]

Core `pokemon` columns include (simplified):

- Identity and stats: `id`, `name`, `cp`, `hp`, `dust`, `level`.
- IVs: `iv_atk`, `iv_def`, `iv_sta`, `iv_pct`, `iv_stars`.
- PvP Great / Ultra / Master: `gl_rank`, `gl_percentile`, `gl_stat_product`, `gl_sp_pct_of_max`, `gl_best_level`, `gl_best_cp`, and the Ultra/Master equivalents.
- Metadata: `screenshot_path`, `notes`, `caught_date`.
- Flags: `needs_review`, `tag`, `review_reason`, `demoted`.

There is also an evolution rankings table populated by `insert_evo_rankings()`.

### 6.2 Evaluation Logic

`evaluate_catch()` in `evaluator.py` computes the decision:

- Considers IV%, league ranks, and evolution PvP rankings.
- Applies special handling for legendaries / mythicals (`KEEP_SPECIES`).
- Returns an action (`KEEP`, `TRANSFER`, `REVIEW`) plus reasons.

`scan_one_pokemon()` then:

- Inserts or updates the row in `pokemon`.
- Writes evolution rankings.
- Sets `tag`, `needs_review`, and `review_reason` based on the decision.

### 6.3 Pass 1 Catalog + Tagging

During Pass 1:

- Each Pokémon is scanned, evaluated, and tagged.
- Tagging uses the chosen `--tag-layout` (different coordinates for `default` vs `ff` layouts). The bot taps:
  - Tag menu button.
  - Tag option button.
  - One of `tag_keep`, `tag_transfer`, or `tag_review`.
  - Appraisal done / dismiss.[file:2]

If `tags_are_calibrated(tag_layout)` returns false, the bot logs a warning and **skips** in-game tagging (database writes still occur).[file:2]

### 6.4 Micro Pass 2 Cleanup (In-Place Demotion)

The legacy `pass2_tagger.py` script is deprecated. Instead, `main.py` implements a built-in **Micro Pass 2** cleanup step:[file:2]

- After Pass 1, if tags are calibrated and this is not a dry run, `micropass2_cleanup()` runs.
- It queries all rows where `demoted = 1` — Pokémon whose desired tag changed after re-evaluation.
- For each demoted Pokémon, it:
  - Uses in-game search (name + CP + HP) to locate the specific Pokémon.
  - Applies the correct tag again via the chosen tag layout.
  - Clears search and returns to the list.
- Handles freezes and respects pause/quit signals.

This keeps in-game tags in sync with the latest evaluator rules without a separate script.

### 6.5 Displaced Pokémon Reporting

`report_displaced(conn)` uses `flag_displaced()` / `find_displaced()` to identify Pokémon whose position in the collection is now "displaced" relative to previous evaluations (e.g., better candidates found later), and logs them for manual follow-up.[file:2]

---

## 7. Querying and Review Tools

Beyond `main.py`, several helper tools exist:[file:1]

- `query_db_gui.py` — desktop GUI for browsing, filtering, and exporting the catalog to CSV.
- `query_db_basic.py` — terminal-friendly summary of collection stats.
- `show_review.py` — prints all rows with `needs_review = 1`.
- `dashboard_server.py` — Flask REST API exposing `/pokemon` and `/stats` endpoints for web dashboards.

Example SQL queries:

```sql
-- Perfect IVs
SELECT name, cp, level, caught_date
FROM pokemon
WHERE iv_pct = 100.0;

-- Great League rank 1s
SELECT name, cp, gl_rank, gl_best_cp
FROM pokemon
WHERE gl_rank = 1;

-- Transfer candidates (low IV and weak PvP)
SELECT name, cp, iv_pct, gl_rank, ul_rank
FROM pokemon
WHERE iv_pct < 82.2
  AND (gl_rank IS NULL OR gl_rank > 500)
  AND (ul_rank IS NULL OR ul_rank > 500)
ORDER BY iv_pct ASC;
```

---

## 8. Repository Layout

Approximate structure:[file:1]

```text
pokemon-iv/
├── main.py                  # Entry point: Pass 1 catalog + Micro Pass 2 cleanup
├── calibrate.py             # Interactive UI calibration to generate calibration.json
├── calibration_viewer.py    # Inspect and tweak saved calibration coordinates
├── download_data.py         # Base stats downloader (GameMaster + PokeAPI)
├── build_species_lookup.py  # Species lookup (types, height, weight)
│
├── config.py                # Default config and calibration merging
├── calibration.json         # Saved mirror region + UI coordinates
│
├── screen_capture.py        # Quartz-based window capture and bounds detection
├── tap_controller.py        # Tap/swipe/Bézier path simulation
├── pause_controller.py      # F9/F10/F8 pause, stop, and reprocess hotkeys
├── freeze_detector.py       # Screen freeze detection and recovery helpers
│
├── ocr_parser.py            # OCR regions, bar parsing, caught date parsing
├── vision_agent.py          # Remote/local VLM integration and appraisal analysis
├── iv_calculator.py         # IV + level + CP formula engine
├── pvp_rankings.py          # Great / Ultra / Master league ranking engine
├── evolution_chains.py      # Evolution chain data (including branches)
│
├── database.py              # SQLite schema, inserts, exports, and stats
├── evaluator.py             # Keep/transfer/review rules and displacement logic
├── tagger.py                # In-game tagging primitives
│
├── query_db_gui.py          # Desktop GUI viewer
├── query_db_basic.py        # CLI summary tool
├── show_review.py           # Needs-review listing script
├── dashboard_server.py      # Local REST API for dashboards
│
├── data/
│   ├── base_stats.json      # Base stats (generated)
│   └── species_lookup.json  # Species lookup (generated)
│
├── pokemon_ivs.db           # SQLite database (created on first run)
├── bot.log                  # Session logs
├── requirements.txt         # Python dependencies
└── README.md                # This documentation
```

The deprecated `pass2_tagger.py` bulk retagging script is no longer part of the recommended workflow; use the built-in Micro Pass 2 cleanup in `main.py` instead.[file:1][file:2]
