# Pokémon GO IV Cataloger

Automated Pokémon GO IV scanning, appraisal parsing, PvP ranking, and in-game tagging using native iPhone Mirroring on macOS. No jailbreak, no modified client, no hardware robot.

---

## 1. What It Does

This project turns the iPhone Mirroring window on macOS Sequoia into a fully automated IV cataloging pipeline:

- Captures **pixel-perfect** frames from the iPhone Mirroring window via Quartz.
- Reads **name, CP, HP, type, and caught date** using OCR, cross-checked against a local/remote **VLM** for CP.
- Measures appraisal bars to recover **exact ATK / DEF / STA IVs (0–15)**.
- Computes **exact IV percentage, level**, and **PvP stat product rankings** for Great / Ultra / Master League, including all evolutions.
- Writes everything into a local **SQLite database (`pokemon_ivs.db`)** with flags for review, displacement, and demotion.
- Assigns each cataloged Pokémon a **rank-encoded nickname** (e.g. `VenuG1U37`) that uniquely fingerprints it for later lookup — this is what lets Micro Pass 2 re-locate a specific Pokémon reliably even when CP/HP alone can't disambiguate it (see [Section 6.6](#66-nickname-fingerprinting--evolution-tracking)).
- Applies **in-game tags** (keep / transfer / review) in real time using calibrated tap coordinates.
- **Logs every OCR/VLM CP parse** to a dedicated benchmarking table so parsing accuracy can be measured and improved with real data instead of guesswork.

Two main operating modes:

- `catalog` — scan the **age 0** box and catalog an entire page of fresh catches.
- `newcatch` — appraise and tag **only the most recent catch**, then stop.

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
CP OCR + VLM consensus & reconciliation
  - OCR retries + VLM multi-frame vote (remote 30B or local 4B fallback)
  - _reconcile_cp() picks a winner and logs the decision + images
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
  - Rank-encoded nickname generation (set_nickname)
         │
         ▼
SQLite database (database.py)
  - `pokemon` rows + evolution rankings + nickname
  - `cp_consensus_log` rows for OCR/VLM benchmarking
  - displaced / demoted / needs_review flags
         │
         ▼
Tagging & cleanup
  - Pass 1: live catalog + tagging
  - Micro Pass 2: demotion cleanup in-game (nickname-based re-tagging of demoted entries)
```

Anti-detection behaviours baked in:

- Gaussian **tap jitter** and **Bezier mouse paths** (human-like motion).
- Log-normal **timing variation** on all taps, swipes, and appraisals.
- Randomized **short / long breaks** and configurable session length ranges.
- A **FreezeDetector** that watches Mirroring for frozen frames and attempts recovery (center tap, back button, etc.).

---

## 3. Installation & Setup

### 3.1 Requirements

- macOS **Sequoia** on Apple Silicon (M1+).
- iPhone with **iPhone Mirroring** enabled over USB or Bluetooth.
- Python **3.10+**.
- `flask` if you want to run the benchmark review GUI or the dashboard (`pip install flask`).

### 3.2 Install Dependencies

```bash
pip install -r requirements.txt
```

Apple Vision runs via `pyobjc` on Apple Silicon. `pytesseract` is used for description-line detection and as a fallback; it is optional.

### 3.3 Download Base Stats

Fetch base ATK / DEF / STA for all species:

```bash
python download_data.py
```

This script pulls from Pokémon GO GameMaster and falls back to PokeAPI if needed, then writes `data/base_stats.json`.

### 3.4 Build Species Lookup

Generate a lookup table for name → types / height / weight:

```bash
python build_species_lookup.py
```

This creates `data/species_lookup.json` by scraping Pokemondb.net for height/weight and type information.

### 3.5 Calibrate UI Coordinates

Open **iPhone Mirroring** and navigate to your Pokémon storage, then run:

```bash
python calibrate.py
```

`deprecated/calibrate.py`:

- Detects the iPhone Mirroring window (`get_mirror_window_bounds`).
- Captures a reference screenshot and saves `calibration_screenshot.png`.
- Lets you either accept default UI coordinates or input relative coordinates (0.0–1.0) for taps and bar positions.
- Saves the configuration to `calibration.json` and merges with `config.DEFAULT_CONFIG`.

Re-run calibration whenever you change iPhone model or monitor resolution.

### 3.6 VLM Setup (Optional but Recommended)

CP reading is cross-checked against a Vision-Language Model. Two backends are supported and fail over automatically:

- **Remote** — an Ollama-compatible endpoint (default: `qwen3-vl:30b` on a Windows PC at `192.168.1.60:11434`, configurable in `vision_agent.py`).
- **Local fallback** — `mlx-vlm` running a quantized Qwen3-VL model directly on the M1 Mac when the remote PC is unreachable.

```bash
pip install -U mlx-vlm
export POGO_VLM_MODEL=mlx-community/Qwen3-VL-4B-Instruct-4bit   # default
export POGO_DISABLE_LOCAL_VLM=1   # optional: force remote-only, degrade to OCR/review if unreachable
```

The remote and local models are **not comparable in accuracy** — see [Section 9](#9-cp-consensus-benchmarking) for why this matters and how it's tracked.

---

## 4. Running the Bot

The main entry point is `main.py`.

```bash
python main.py [options]
```

### 4.1 Command-Line Options

`parse_args()` supports:

| Option | Values | Description |
| :----- | :----- | :---------- |
| `--limit N` | integer | Stop after scanning at most `N` Pokémon (0 = unlimited). |
| `--debug` | flag | Save intermediate screenshots (CP region, name region, bar strip, VLM frames, etc.) to `screenshots/`. |
| `--log-cp-images` | flag | Save **only** the OCR/VLM CP crops needed for consensus benchmarking, without the full `--debug` overhead (no appraisal/name-region/bar-strip dumps). Use this for normal cataloging sessions when you still want to build a ground-truth review set. |
| `--dry-run` | flag | Run the full OCR + evaluation pipeline **without** tapping or tagging in-game. |
| `--mode` | `catalog` / `newcatch` / `sync-flags` | `catalog`: scan the age 0 box; `newcatch`: appraise and tag only the most recent catch; `sync-flags`: sync shiny/shadow/purified status from in-game search filters. |
| `--tag-layout` | `default` / `ff` | Choose which **in-game tag menu layout** to use for keep/transfer/review taps. |

### 4.2 Session Controls

`PauseController` binds hotkeys:

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
  - Uses OCR + VLM to reconcile CP and description lines, logging the outcome to `cp_consensus_log`.
  - Opens the appraisal screen, reads IV bars, and computes IVs + PvP ranks.
  - Evaluates the catch (keep/transfer/review) and writes to the database.
  - Generates and stores the rank-encoded nickname (`set_nickname()`).
  - Applies the appropriate **in-game tag**.
  - Taps the next arrow to advance.

#### New Catch Mode (`--mode newcatch`)

- Taps the **last slot** in `ui["pokemon_slots"]` (most recent Pokémon).
- Runs a single `scan_one_pokemon()` cycle.
- Tags the Pokémon and then exits without swiping further.

#### Sync Flags Mode (`--mode sync-flags`)

- Walks the in-game search filters for **Shiny**, **Shadow**, and **Purified** one Pokémon at a time (via `sync_special_flags()`), using the game's own filters as ground truth for `is_shiny`/`form_status`.
- Opens the appraisal overlay per entry to read name/caught-date (not present on the base screen), then dismisses it without tagging.
- Recomputes PvP rankings for newly-flagged shadows and re-runs top-N enforcement afterward.

---

## 5. OCR, VLM, and Robustness

### 5.1 Description Line Detection

The helper `detect_description_lines()`:

- Crops and upscales the name/description region.
- Calls Tesseract (`image_to_data`) to detect individual text lines.
- Filters low-confidence or tiny hits and excludes loading-bar artifacts by bounding-box height.
- Anchors on words like **"caught"**, **"around"**, or the **date**, then expands up/down within a dynamic vertical gap.
- Produces `num_lines` (2–5) and concatenated description text.

The number of lines drives which appraisal bar layout to use (different Y coordinates for 3/4/5-line layouts).

### 5.2 CP OCR + VLM Reconciliation

For CP parsing, the bot:

- Re-tries OCR up to `max_attempts` (default 5) via `retry_read_cp()`.
- Crops a tight CP sub-region, upscales 3×, and re-OCRs.
- Launches a **VLM CP consensus** job (`_vlm_cp_consensus()`) in a background thread (`vlm-cp` executor), feeding 3 CP frames captured *before any taps* to `vision_agent`, and tracks which backend (`remote`/`local`) answered each vote via `call_vlm_with_backend()`.
- Reconciles OCR vs VLM using `_reconcile_cp()`, which returns both the winning CP and a `reason` string:
  - `agree` — OCR and VLM independently landed on the same number (the only case treated as automatic ground truth for benchmarking).
  - `slash_assumed_7` — OCR raw text contained a slash/backslash (a common misread of the digit `7`); OCR is trusted **only if** the resulting CP falls in the valid range (10–5500) and doesn't conflict with a valid VLM reading.
  - `slash_ocr_rejected_trust_vlm` — the slash-derived OCR value was out of range or conflicted with a valid VLM reading, so VLM is trusted instead. This branch was added after real-world testing caught OCR text like `'cPe6/75'` producing an impossible CP of 6775 while the VLM unanimously read the correct value (675) — the fix ensures the reconciler always cross-checks plausibility rather than blindly trusting the slash heuristic.
  - `vlm_trailing_digit` / `vlm_leading_digit` — VLM has a spurious extra digit vs. OCR; OCR is trusted.
  - `ocr_extra_digit` — OCR has a spurious extra digit vs. VLM; VLM is trusted.
  - `same_length_trust_vlm` — same digit count but different values; VLM is trusted as the tie-breaker.
- Every parse writes a row to `cp_consensus_log` for later benchmarking (see [Section 9](#9-cp-consensus-benchmarking)).

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

Freeze handling is used both in Pass 1 and in Micro Pass 2 cleanup.

### 5.6 VLM Backend Dispatch

`vision_agent.py`'s dispatcher (`_dispatch_vlm()`) tries the remote endpoint first and transparently falls back to the local `mlx-vlm` model on connection failure, with a circuit breaker (`_local_broken`) that disables local inference for the rest of the session if it also fails. Two public entry points share this logic:

- `call_vlm(prompt, images)` — unchanged signature, returns just the text. Used by `analyze_base_screen()`, `analyze_appraisal_screen()`, `correct_ocr()`, and `recover_failed_parse()`.
- `call_vlm_with_backend(prompt, images)` — returns `(text, backend)` where `backend` is `"remote"` or `"local"`. Used by the CP consensus path so benchmarking can distinguish which model actually answered each vote.

`reset_remote_status()` re-probes the remote PC between passes; `reset_local_circuit_breaker()` manually re-enables local inference after a tripped failure.

---

## 6. Database, Evaluation, and Tagging

### 6.1 Database Schema

`database.py` initializes `pokemon_ivs.db` and ensures columns exist across three tables:

**`pokemon`** — core catalog rows (simplified):

- Identity and stats: `id`, `name`, `cp`, `hp`, `dust`, `level`.
- IVs: `iv_atk`, `iv_def`, `iv_sta`, `iv_pct`, `iv_stars`.
- PvP Great / Ultra / Master: `gl_rank`, `gl_percentile`, `gl_sp`, `gl_sp_pct`, `gl_best_level`, `gl_best_cp`, and the Ultra/Master equivalents.
- **`nickname`** — the rank-encoded fingerprint (e.g. `VenuG1U37`) used to uniquely re-locate this individual Pokémon in-game. See [Section 6.6](#66-nickname-fingerprinting--evolution-tracking).
- Metadata: `screenshot_path`, `notes`, `caught_date`.
- Flags: `needs_review`, `tag`, `review_reason`, `demoted`, `is_shiny`, `form_status`, `tag_changed`, `pending_old_tag`.

**`evo_rankings`** — per-evolution PvP rankings, populated by `insert_evo_rankings()`. Also serves as the source of valid "evolve to" options offered by the dashboard (`/pokemon/<id>/evo_options`).

**`cp_consensus_log`** — one row per CP parse attempt, independent of whether the catch itself gets inserted. Used purely for measuring OCR-vs-VLM accuracy (see [Section 9](#9-cp-consensus-benchmarking)):

- `ocr_cp`, `ocr_raw`, `ocr_image_path` — what OCR read and the crop it read it from.
- `vlm_votes`, `vlm_consensus`, `vlm_backends`, `frame_paths` — every VLM vote, the winning value, which backend (remote/local) produced each vote, and the saved frame images.
- `reconciled_cp`, `reconcile_reason` — the final value `_reconcile_cp()` chose and why.
- `ground_truth_cp`, `label_source` — filled in later, either automatically (`auto_agree`, only when OCR and VLM independently agreed) or manually (`manual`, via human review of the saved images).

### 6.2 Evaluation Logic

`evaluate_catch()` in `evaluator.py` computes the decision:

- Considers IV%, league ranks, and evolution PvP rankings.
- Applies special handling for legendaries / mythicals (`KEEP_SPECIES`).
- Returns an action (`KEEP`, `TRANSFER`, `REVIEW`) plus reasons.

`scan_one_pokemon()` then:

- Inserts or updates the row in `pokemon`.
- Writes evolution rankings.
- Generates the nickname via `set_nickname()`.
- Sets `tag`, `needs_review`, and `review_reason` based on the decision.

### 6.3 Pass 1 Catalog + Tagging

During Pass 1:

- Each Pokémon is scanned, evaluated, tagged, and nicknamed.
- Tagging uses the chosen `--tag-layout` (different coordinates for `default` vs `ff` layouts). The bot taps:
  - Tag menu button.
  - Tag option button.
  - One of `tag_keep`, `tag_transfer`, or `tag_review`.
  - Appraisal done / dismiss.

If `tags_are_calibrated(tag_layout)` returns false, the bot logs a warning and **skips** in-game tagging (database writes still occur).

### 6.4 Micro Pass 2 Cleanup (In-Place Demotion)

- After Pass 1, if tags are calibrated and this is not a dry run, `micro_pass2_cleanup()` runs.
- It queries all rows where `demoted = 1` or `tag_changed = 1` — Pokémon whose desired tag changed after re-evaluation.
- For each affected Pokémon, it:
  - **Searches in-game by nickname** (falling back to the legacy `name&CP&HP` string only if a row has no nickname yet, e.g. rows cataloged before this feature existed) to locate the specific Pokémon. This replaces the original name+CP+HP search, which could return multiple ambiguous matches for level-1/CP10 catches whose CP and HP overlap heavily across different IV spreads.
  - Safely **deselects the old tag before applying the new one** — since in-game tags are additive rather than exclusive, skipping deselection would stack tags permanently with no record. If the old or new tag isn't calibrated for the active layout, the Pokémon is skipped and flagged `needs_review` rather than risking a silent stack.
  - Clears search and returns to the list.
- Handles freezes and respects pause/quit signals.

This keeps in-game tags in sync with the latest evaluator rules without a separate script.

### 6.5 Displaced Pokémon Reporting

`report_displaced(conn)` uses `flag_displaced()` / `find_displaced()` to identify Pokémon whose position in the collection is now "displaced" relative to previous evaluations (e.g., better candidates found later), and logs them for manual follow-up.

### 6.6 Nickname Fingerprinting & Evolution Tracking

**The problem this solves.** Level-1 (CP10) catches overlap heavily on CP and HP alone — the CP/HP formulas compress a wide range of different IV spreads into the same rounded integers at minimum level, so Micro Pass 2's original `name&CP&HP` search could return several ambiguous candidates for the same species. Two disambiguators were considered and rejected before landing on the current approach:

- **Weight/height tracking** — real per-catch values, but requires an extra detail-screen visit and OCR pass per Pokémon that the pipeline doesn't otherwise need, and turned out to be unnecessary once rank injectivity was confirmed (below).
- **A raw incrementing ID suffix** — solves uniqueness but tells you nothing about the Pokémon and adds an extra tap-typing burden for no informational gain.

**The actual fix: rank-encoded nicknames.** Each cataloged Pokémon is renamed to `{Species}{G<gl_rank>}{U<ul_rank>}` (e.g. `VenuG1U37`), truncated to fit Pokémon GO's 12-character nickname limit, via `build_nickname()` / `set_nickname()` in `database.py`. The species used is whichever of the Pokémon's own species or **best future evolution** has the single best (lowest) league rank — so a Bulbasaur that projects to a rank-1 Great League Venusaur gets named for that Venusaur potential, not for itself.

This works as a reliable fingerprint because **IV rank is injective**: standard PvP ranking tools assign each of the 4,096 possible IV combinations (for a given species/level cap/league) a unique ordinal position with no ties. That means:

- Two Pokémon can only share a nickname if they are genuinely IV-identical duplicates — in which case it's provably safe for Micro Pass 2 to tag either one, since they're interchangeable.
- A matching Great League rank *forces* a matching Ultra League rank (both are derived from the same fixed IV spread), so partial/prefix collisions like `VenuG1U37` vs. `VenuG1U370` are mathematically impossible — no quoting or exact-match search trickery is needed.
- Pokémon GO nicknames persist through evolution, and there is no documented rate limit on renaming your own Pokémon (unlike the friend-nickname and trainer-username limits, which are unrelated features) — so nicknames can be assigned freely without throttling concerns.

**Evolution tracking is manual, not automated.** Rather than trying to detect species changes during routine scans (which would mean re-scanning the entire ~11,000-row catalog just to catch a handful of manual evolutions), the dashboard (`dashboard_server.py`) exposes an **"Evolved →"** button per row:

- `GET /pokemon/<id>/evo_options` returns the tracked evolution names for that row (pulled straight from `evo_rankings`), populating a simple choice prompt.
- `POST /pokemon/<id>/evolve` calls `promote_evolution()`, which updates the existing row **in place** — new species, CP, HP, and PvP projection fields — rather than inserting a new row, and deletes the now-redundant `evo_rankings` entry for the species it just became. You can jump straight to whatever final form you land on (e.g. Bulbasaur → Venusaur) without needing to separately mark the intermediate stage first.
- The nickname is re-derived after promotion via `set_nickname()`, but since nicknames are already based on projected best-evolution rank, evolving a Pokémon typically doesn't change its nickname at all — the DB catches up to a name that was already correct.

---

## 7. Querying and Review Tools

Beyond `main.py`, several helper tools exist:

- `query_db_gui.py` — desktop GUI for browsing, filtering, and exporting the catalog to CSV.
- `query_db_basic.py` — terminal-friendly summary of collection stats.
- `show_review.py` — prints all rows with `needs_review = 1`.
- `dashboard_server.py` — Flask REST API + dashboard UI. Binds to `0.0.0.0:8001` so it's reachable from other devices on the LAN (e.g., viewing the catalog from a bigger screen). Endpoints:
  - `GET /pokemon` — full catalog rows, including nickname and first/second evolution PvP projections, for the main table.
  - `GET /pokemon/<id>/evolutions` — full evolution ranking breakdown for the expandable per-row panel.
  - `GET /pokemon/<id>/evo_options` — valid "evolve to" species choices for that row, sourced from `evo_rankings`.
  - `POST /pokemon/<id>/evolve` — manually promotes a row to a new species after an in-game evolution (see [Section 6.6](#66-nickname-fingerprinting--evolution-tracking)).
  - `GET /stats` — KEEP/TRANSFER/REVIEW totals for the summary cards.
  - `GET /all` — unfiltered dump of every column for every row.

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

-- Find a specific individual by its rank-encoded nickname
SELECT * FROM pokemon WHERE nickname = 'VenuG1U37';
```

---

## 8. Known Fixes & Robustness Notes

- **`slash_assumed_7` reconciliation bug (fixed).** Earlier versions of `_reconcile_cp()` trusted any OCR reading containing a slash/backslash unconditionally, without checking plausibility or cross-referencing the VLM. This produced at least one confirmed impossible CP (6775, outside the valid 10–5500 range) that was only caught by downstream validation forcing `REVIEW` — while the VLM had already unanimously read the correct value. The reconciler now requires the OCR-derived CP to be in range and non-conflicting with a valid VLM reading before trusting it; otherwise it defers to VLM (`slash_ocr_rejected_trust_vlm`).
- **Auto-labeling ground truth only from `reconcile_reason == 'agree'`.** Any reconciliation branch that "picks a side" (e.g. `slash_assumed_7`, `same_length_trust_vlm`) makes `ocr_cp == reconciled_cp` (or `vlm_cp == reconciled_cp`) trivially true by construction — that's not independent confirmation, so the benchmarking tools never treat it as ground truth automatically.
- **CP10/level-1 duplicate ambiguity (fixed).** The original Micro Pass 2 search key (`name&CP&HP`) could return multiple candidates for level-1 catches, since the CP/HP formulas compress many distinct IV spreads into identical rounded values at minimum level. Fixed by switching to nickname-based search — see [Section 6.6](#66-nickname-fingerprinting--evolution-tracking) for the full reasoning, including why weight/height tracking and quote-wrapped exact-match search both turned out to be unnecessary once IV-rank injectivity was confirmed.

---

## 9. CP Consensus Benchmarking

Every CP parse (OCR + VLM) is logged to `cp_consensus_log` so parsing accuracy can be measured with real data instead of assumed. This closes the loop on the "OCR vs VLM vs OpenCV" question with actual numbers instead of a gut feeling.

### 9.1 What Gets Logged

Run with `--log-cp-images` (lighter than full `--debug` — only saves the CP-region crops needed for review) to capture, per catch:

- The OCR crop (`ocr_image_path`) and raw OCR text (`ocr_raw`).
- Every VLM vote frame (`frame_paths`), the votes themselves (`vlm_votes`), which backend answered each one (`vlm_backends`), and the winning consensus value (`vlm_consensus`).
- The final reconciled CP and the reason `_reconcile_cp()` chose it (`reconciled_cp`, `reconcile_reason`).

### 9.2 Establishing Ground Truth

`ground_truth_cp` starts `NULL` on every row — nothing grades itself automatically except the narrow case where OCR and VLM **independently** agreed:

- **Auto-labeled** (`label_source = 'auto_agree'`): only rows where `reconcile_reason == 'agree'`.
- **Manually labeled** (`label_source = 'manual'`): everything else, reviewed against the saved images.

### 9.3 Review Tools

Two ways to review and label:

- **`benchmark_report.py`** — CLI tool. `--review` walks pending (unlabeled) rows and opens images via macOS `open`; `--audit` walks *every* row, including auto-labeled agreements, so you can spot-check that agreement actually means correctness. Prints a full accuracy report broken down by `reconcile_reason` and VLM backend.
- **`benchmark_gui.py`** — local Flask web GUI (`python benchmark_gui.py`, then open `http://127.0.0.1:5051/?mode=audit`). Renders all images for a row inline in the browser instead of opening a Preview window per image, with a pre-filled input and one-click confirm/save/skip/stop controls. Binds to `0.0.0.0` like `dashboard_server.py`, so it's reachable from another device on the LAN or Tailscale for reviewing on a bigger screen.

Both tools share the same DB, the same auto-labeling rule, and the same `label_source` tracking, so switching between them mid-review is safe.

### 9.4 Reading the Report

```
n=48
  OCR accuracy:        48/48  (100.0%)
  VLM accuracy:        47/48  (97.9%)
  Reconciled accuracy: 48/48  (100.0%)

By reconcile_reason (reconciled-vs-truth accuracy):
  agree                        n=47   correct=47   (100.0%)
  slash_ocr_rejected_trust_vlm n=1    correct=1    (100.0%)

By VLM backend (remote 30B vs local 4B fallback):
  remote     n=45   vlm_correct=44   (97.8%)
  local      n=3    vlm_correct=3    (100.0%)
```

The backend breakdown matters because the remote `qwen3-vl:30b` and the local `mlx-vlm` fallback are not comparable models — conflating sessions where the Windows PC was reachable with sessions where it wasn't would blend two different systems into one misleading number.

---

## 10. Repository Layout

Approximate structure:

```text
pokemon-iv/
├── main.py                  # Entry point: Pass 1 catalog + nickname-based Micro Pass 2 cleanup
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
├── database.py              # SQLite schema, inserts, exports, stats, nickname generation, evolution promotion
├── evaluator.py             # Keep/transfer/review rules and displacement logic
├── tagger.py                # In-game tagging primitives
│
├── query_db_gui.py          # Desktop GUI viewer
├── query_db_basic.py        # CLI summary tool
├── show_review.py           # Needs-review listing script
├── dashboard_server.py      # Local REST API + dashboard for the catalog, incl. manual evolution promotion (0.0.0.0:8001)
├── benchmark_report.py      # CLI: auto-label + review + accuracy report for cp_consensus_log
├── benchmark_gui.py         # Local web GUI for reviewing/labeling CP consensus ground truth (0.0.0.0:5051)
│
├── data/
│   ├── base_stats.json      # Base stats (generated)
│   └── species_lookup.json  # Species lookup (generated)
│
├── pokemon_ivs.db           # SQLite database (created on first run)
├── screenshots/             # Debug / --log-cp-images crops (OCR + VLM frames)
├── bot.log                  # Session logs
├── requirements.txt         # Python dependencies
└── README.md                # This documentation
```
