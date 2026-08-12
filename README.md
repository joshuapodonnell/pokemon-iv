# Pokémon GO IV Cataloger

Fully automated IV cataloging system using iPhone Mirroring on macOS.
No jailbreak. No robot arm. Just your MacBook Air M1 + USB cable.

---

## How It Works

```
iPhone Mirroring (macOS Sequoia)
         ↓  pixel-perfect screen capture (Quartz)
Apple Vision OCR  →  name, CP, HP, stardust, type, weight, height
Color detection   →  appraisal bar IVs (ATK/DEF/STA, exact 0–15)
         ↓
IV Calculator  →  exact IVs + level
PvP Rankings   →  Great / Ultra / Master League rank + stat product
         ↓
SQLite database  →  pokemon_ivs.db
         ↓
Web dashboard    →  browse, sort, filter, export
```

**Anti-bot measures built in:** Gaussian tap jitter, log-normal timing delays,
randomized short/long breaks, Bézier curved mouse paths, variable session lengths.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

> **macOS M1 note:** The primary OCR engine is Apple Vision (via `pyobjc`). `pytesseract` is an optional fallback and is commented out in `requirements.txt` by default — only install it if Apple Vision is unavailable.

### 2. Download Pokémon base stats

Required for IV calculation. Fetches base ATK/DEF/STA for all species.

```bash
python download_data.py
```

### 3. Build the species lookup table

Required for OCR name matching. Run after `download_data.py`.

```bash
python build_species_lookup.py
```

### 4. Calibrate (one time per device)

Open iPhone Mirroring and navigate to your Pokémon storage. Then:

```bash
python calibrate.py
```

This auto-detects the iPhone Mirroring window, lets you drag-and-drop UI coordinate handles visually, and saves everything to `calibration.json`.

Re-run calibration if you change iPhone models or display resolution.

### 5. Run the cataloger

```bash
python main.py
```

**Options:**

| Flag | Description |
|---|---|
| `--limit N` | Stop after N Pokémon (good for testing) |
| `--debug` | Save screenshots and debug bar images to disk |
| `--dry-run` | OCR test without tapping (hold phone still) |

**Emergency stop:** Move your mouse to the top-left corner of your screen, or press **F10**.

**Pause / Resume:** Press **F9** to pause mid-session. Press again to resume.

---

## Database

Results are saved to `pokemon_ivs.db` (SQLite). Each row is one scanned Pokémon.

### Key Columns

| Column | Description |
|---|---|
| `name` | Species name, including regional variant (e.g. `Meowth (Galarian)`) |
| `cp` | Combat Power as displayed in-game |
| `hp` | HP as displayed in-game |
| `level` | Inferred Pokémon level (0.5 increments) |
| `iv_atk` / `iv_def` / `iv_sta` | Exact IVs 0–15 |
| `iv_pct` | Overall IV% (0–100) |
| `iv_stars` | `0★` / `1★` / `2★` / `3★` / `100%✨` |
| `gl_rank` | Great League PvP rank (1 = best possible for species) |
| `ul_rank` | Ultra League PvP rank |
| `ml_rank` | Master League PvP rank |
| `gl_sp_pct` | Great League stat product as % of rank-1 |
| `ml_sp_pct` | Master League stat product as % of perfect |
| `dust_cost` | Stardust cost to power up (used to infer level range) |
| `caught_date` | Date caught, parsed from the appraisal screen |
| `needs_review` | `1` if OCR confidence was low and manual review is recommended |
| `cataloged_at` | Timestamp of when this record was inserted |

### Query Examples

```sql
-- All 100% IVs
SELECT name, cp, iv_pct FROM pokemon WHERE iv_pct = 100;

-- Great League rank 1s
SELECT name, cp, gl_rank, gl_best_cp FROM pokemon WHERE gl_rank = 1;

-- Top PvP picks for a species
SELECT * FROM pokemon WHERE name = 'Medicham' ORDER BY gl_rank ASC LIMIT 5;

-- Pokémon flagged for manual review
SELECT name, cp, iv_pct FROM pokemon WHERE needs_review = 1;

-- Candidates for transfer (weak PvE and poor PvP)
SELECT name, cp, iv_pct, gl_rank FROM pokemon
WHERE iv_pct < 50 AND (gl_rank IS NULL OR gl_rank > 100)
ORDER BY iv_pct ASC;
```

---

## Querying & Review

### GUI Query Tool

```bash
python query_db_gui.py
```

A desktop GUI for browsing, filtering, and sorting your collection. Supports export to CSV.

### Command-line Review

```bash
python show_review.py
```

Prints all Pokémon flagged `needs_review = 1` — species where OCR confidence was low and a manual check is recommended.

### Basic Query Script

```bash
python query_db_basic.py
```

Quick terminal-friendly summary of your collection stats.

---

## Tagging

The cataloger supports automatic tagging in-game via two passes:

- **Pass 1 (`tagger.py`):** Tags Pokémon immediately after scanning based on evaluator rules.
- **Pass 2 (`deprecated_tests/pass2_tagger.py`):** Re-evaluates the full database and applies updated tags. Run after bulk imports or rule changes.

Tagger outcomes are one of: **keep**, **transfer**, or **review**.

Tag rules are configured in `evaluator.py`. The default rule keeps any Pokémon with:
- IV% ≥ threshold, **or**
- Great League rank ≤ threshold, **or**
- Ultra League rank ≤ threshold

---

## PvP IV Rankings

PvP IVs differ from PvE IVs. In Great and Ultra League:

- **Lower ATK IV is often better** — a lower ATK IV keeps CP lower, allowing more power-ups and greater bulk (DEF × STA product) within the league cap.
- **Rank 1** = the single best IV combination for that species at that league cap.
- **Stat product** = `ATK × DEF × floor(STA)` at the best achievable level — the primary ranking metric.

Rankings cover all evolutions. A Pokémon is evaluated not just as its current species but also as every possible evolution, so a good Gastly is ranked as a Gengar too.

> **Note:** Cosmog and Cosmoem can evolve into either Solgaleo or Lunala — both branches are evaluated.

---

## Accuracy Notes

- **Bar detection** is ~99% accurate — the appraisal bars have a fixed layout and high-contrast color segmentation.
- **Apple Vision OCR** is excellent on M1 but may struggle with:
  - Non-standard species names (regional variants, special characters like `♀` / `♂`)
  - Dim screen brightness or low-contrast UI themes
  - Pokémon names that span multiple lines in the appraisal view
- Run `--debug` to save screenshots and bar images when results seem wrong.
- Recalibrate if you change iPhone models or screen resolution.

---

## Files

```
pokemon-iv-bot/
├── main.py                  # Entry point — run this to start cataloging
├── calibrate.py             # One-time UI calibration (drag-and-drop GUI)
├── calibration_viewer.py    # View/adjust saved calibration coordinates
├── download_data.py         # Downloads base stats JSON from PokéAPI
├── build_species_lookup.py  # Builds species_lookup.json for OCR matching
│
├── config.py                # Settings, defaults, and config loading
├── calibration.json         # Saved calibration (generated by calibrate.py)
│
├── screen_capture.py        # Quartz window capture (pixel-perfect)
├── tap_controller.py        # Human-like tap/swipe/Bézier path simulation
├── pause_controller.py      # F9/F10 pause and emergency stop
├── freeze_detector.py       # Detects if the app has frozen mid-session
│
├── ocr_parser.py            # Apple Vision OCR + appraisal bar detection
├── vision_agent.py          # VLM fallback for ambiguous OCR cases
├── iv_calculator.py         # CP formula, level inference, IV computation
├── pvp_rankings.py          # Great / Ultra / Master League ranking engine
├── evolution_chains.py      # Full evolution chain data (Gen 1–9 + regionals)
│
├── database.py              # SQLite schema and query helpers
├── evaluator.py             # Keep / transfer / review decision rules
├── tagger.py                # In-game tagging (pass 1)
├── pass2_tagger.py          # Full-database re-tagging (pass 2)
│
├── query_db_gui.py          # Desktop GUI for browsing your collection
├── query_db_basic.py        # Quick terminal summary
├── show_review.py           # Lists Pokémon flagged for manual review
│
├── debug_crop.py            # Dev tool: crop and inspect screen regions
├── test_evaluator.py        # Unit tests for evaluator logic
│
├── data/
│   ├── base_stats.json      # Generated by download_data.py
│   └── species_lookup.json  # Generated by build_species_lookup.py
│
├── pokemon_ivs.db           # Your collection (created on first run)
├── bot.log                  # Session logs
└── requirements.txt
```
