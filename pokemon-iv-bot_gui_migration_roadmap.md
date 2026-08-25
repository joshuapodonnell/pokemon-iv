# pokemon-iv-bot: CLI → FastAPI + React/TypeScript + Tauri Roadmap

Goal: replace the CLI-driven `main.py` workflow plus the two standalone Flask apps
(`dashboard_server.py`, `benchmark_gui.py`) with a single unified control app —
FastAPI backend, React + TypeScript frontend, packaged as a native desktop app
via Tauri with the Python backend running as a sidecar.

Guiding principle at every stage: **do not touch the working automation pipeline**
(screen_capture.py, ocr_parser.py, vision_agent.py, tap_controller.py,
pause_controller.py, iv_calculator.py, database.py). Only the layer that talks to
these modules changes.

---

## Stage 0 — Baseline safety net

- [ ] Commit current working state of the repo to a git branch (e.g. `pre-gui-migration`)
      before touching anything, so the working CLI bot is always recoverable.
- [ ] Write down the exact current CLI invocations you use regularly
      (e.g. `python main.py --mode sync-flags --limit 2 --debug`) so nothing gets
      lost when flags become UI controls.
- [ ] Confirm `PauseController` hotkeys (F8 reprocess, F9 pause/resume, F10 clean quit)
      and note which internal functions they call — these become button handlers later.

## Stage 1 — Stand up FastAPI without changing any UI

- [ ] Add FastAPI + Uvicorn to `requirements.txt`.
- [ ] Create a new `api/` module (or `server.py`) that imports from existing
      `database.py`, `pvp_rankings.py`, `iv_calculator.py` — reuse logic, don't rewrite it.
- [ ] Port `dashboard_server.py` routes to FastAPI endpoints:
  - [ ] `GET /api/pokemon` — list/filter catalog (mirrors current dashboard table)
  - [ ] `POST /api/pokemon/{id}/evolve` — mirrors "Evolved →" button logic
  - [ ] `GET /api/rankings/{league}` — wraps `all_league_rankings_with_evos`
- [ ] Port `benchmark_gui.py` routes to FastAPI endpoints:
  - [ ] `GET /api/review` — pending review queue (`needs_review = 1` rows)
  - [ ] `POST /api/review/{id}/label` — commit a manual label
  - [ ] Preserve the `cp_consensus_log` / `label_source` logic already in `get_conn()`
- [ ] Add bot-control endpoints wrapping `main.py`:
  - [ ] `POST /api/bot/start` — body: `{mode, limit, debug}` → launches run in background thread/process
  - [ ] `POST /api/bot/pause`, `POST /api/bot/resume`, `POST /api/bot/quit`, `POST /api/bot/reprocess`
        — call the same functions the F8/F9/F10 hotkeys currently trigger
  - [ ] `WS /ws/bot-log` — WebSocket streaming log lines (wrap/duplicate current logging handler)
- [ ] Sanity check: hit every endpoint with `curl`/Postman/FastAPI's auto `/docs` page —
      confirm data shape matches what a frontend will need before writing any React code.
- [ ] Keep old Flask apps running untouched in parallel until FastAPI parity is confirmed.

**Exit criteria for Stage 1:** every feature currently in `dashboard_server.py`,
`benchmark_gui.py`, and the CLI hotkeys has a working FastAPI equivalent you've
manually tested via `/docs` or curl.

## Stage 2 — React + TypeScript SPA against the FastAPI backend

- [ ] Scaffold frontend: `npm create vite@latest pokemon-iv-ui -- --template react-ts`
- [ ] Define shared TypeScript interfaces matching your DB rows, e.g.:
      `PokemonRecord { name: string; cp: number; iv_atk: number; iv_def: number; iv_sta: number; iv_pct: number; gl_rank: number | null; ul_rank: number | null; needs_review: boolean }`
- [ ] Build three routed views:
  - [ ] **Catalog view** — table/grid of `/api/pokemon`, sortable by IV%/rank, "Evolved →" action button
  - [ ] **Review view** — queue from `/api/review`, label buttons, mirrors old benchmark_gui flow
  - [ ] **Bot Control view** — mode/limit/debug form, Start/Pause/Resume/Quit/Reprocess buttons,
        live-scrolling log panel fed by the `/ws/bot-log` WebSocket
- [ ] Reuse the dark theme (`--bg`, `--panel`, `--border`, `--text`, `--muted`, `--keep`, `--transfer`
      CSS variables) from the existing `DASHBOARD_HTML` so the new UI keeps visual continuity.
- [ ] Add basic loading/error states for each API call (don't skip this — it's what makes it feel
      like a real app instead of a demo).
- [ ] Run the SPA in dev mode against the FastAPI server running locally (`uvicorn` on one port,
      `vite dev` on another, CORS enabled) — confirm every view works end-to-end.

**Exit criteria for Stage 2:** you can fully operate the bot (start/pause/quit runs) and
browse/review the catalog entirely from the browser-based React app, FastAPI server
running locally, old Flask apps no longer needed.

## Stage 3 — Package the Python backend as a standalone binary

- [ ] Add PyInstaller to your dev dependencies.
- [ ] Write a `.spec` file for the FastAPI server entrypoint, including hidden imports for
      any dynamically-loaded modules (OCR/vision libraries often need `--hidden-import` flags).
- [ ] Build the binary and name it with the correct Tauri target-triple suffix, e.g.
      `fastapi-server-aarch64-apple-darwin` for the M1 Air.
- [ ] Test the standalone binary by running it directly (no `python` interpreter invoked) and
      confirming the API/WebSocket endpoints still respond identically to the dev version.
- [ ] Note and document any runtime file paths (`base_stats.json`, `calibration.json`, the
      SQLite `pokemon_ivs.db` file) the bundled binary needs — these must resolve correctly
      relative to the bundled binary's location, not relative to a source checkout.

**Exit criteria for Stage 3:** a double-clickable/CLI-runnable binary of the backend
works with zero Python environment installed on the machine.

## Stage 4 — Wrap everything in Tauri

- [ ] Scaffold: `npm create tauri-app@latest` — choose React + TypeScript template.
- [ ] Point the Tauri frontend build at the Stage 2 React app (or merge the scaffolded
      project structure with your existing frontend code).
- [ ] Add the Stage 3 binary to `src-tauri/binaries/` and register it in `externalBin`
      inside `tauri.conf.json`.
- [ ] Add the minimal Rust sidecar-spawn code in `src-tauri/src/lib.rs` to launch the
      FastAPI binary on app startup and shut it down cleanly on app quit.
- [ ] Confirm the frontend's API base URL / WebSocket URL point at the sidecar's local port
      (consider picking a fixed port or having the sidecar write its chosen port to a file
      the frontend reads on launch).
- [ ] Test full dev loop: `npm run tauri dev` — app window opens, sidecar spawns, all three
      views (Catalog/Review/Bot Control) work exactly as they did in the browser.
- [ ] Verify pyautogui/screen-capture timing is unaffected by running inside the Tauri
      window vs. a terminal — the bot control still needs to interact with the separate
      iPhone Mirroring window, not the Tauri app window itself.

**Exit criteria for Stage 4:** `npm run tauri build` produces a working macOS app bundle
that launches, spawns its own backend, and fully replaces the CLI + two Flask apps.

## Stage 5 — Polish and wrap-up

- [ ] Update `README.md` to describe the new architecture (FastAPI + React/TS + Tauri)
      and remove/relocate outdated CLI-only instructions.
- [ ] Add a short architecture diagram or section describing the sidecar pattern —
      useful both for your own reference and as a talking point.
- [ ] Write down 2-3 metric-backed bullet points describing the finished system  (e.g. records cataloged, time saved vs. manual entry, stack breadth).
- [ ] Tag a release/commit marking "GUI migration complete" for a clean before/after reference.

---

### Quick reference: what replaces what

| Old piece | New piece |
|---|---|
| `python main.py --mode ... --debug` CLI | Bot Control view + `/api/bot/*` endpoints |
| F8/F9/F10 hotkeys | Buttons in Bot Control view calling `/api/bot/pause` etc. |
| `dashboard_server.py` (Flask) | Catalog view + `/api/pokemon` (FastAPI) |
| `benchmark_gui.py` (Flask) | Review view + `/api/review` (FastAPI) |
| Terminal log scrollback | Live log panel via `/ws/bot-log` WebSocket |
