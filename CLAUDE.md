# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

S7Trace is a real-time chart/recorder for Siemens S7 PLCs (PySide6 GUI, pyqtgraph, python-snap7; OPC UA / Web API / Modbus drivers). The UI, help texts and README are in Polish; code and comments are in English. Work in this repo happens on more than one computer (git only, never OneDrive).

## Commands

Windows only. Use the project venv (`.venv`, created by `run.bat`).

```
run.bat                                   # create .venv on first start, run the app (main.py)
run_sim.bat                               # local snap7 PLC simulator on 127.0.0.1:1102 (python -m s7trace.sim)
.venv\Scripts\python -m pytest tests -q   # full suite (~100 s)
.venv\Scripts\python -m pytest tests/test_round4.py -k "ip_ or device" -q   # subset / single test
powershell -ExecutionPolicy Bypass -File build-portable.ps1                 # portable build -> dist\S7Trace + dist\S7Trace-portable-<date>.zip
```

- Tests run Qt offscreen; set `QT_QPA_PLATFORM=offscreen` and `QT_QPA_FONTDIR=C:\Windows\Fonts` (otherwise no glyphs in screenshots). `tests/shot_*.py` are helper scripts that render offscreen screenshots (`python tests/shot_panel.py <out_dir>`), not tests.
- No linter is configured.
- `dist/`, `snapshots/`, `rec/` are git-ignored. Only commit/push when the user asks; end commit messages with the Co-Authored-By line from the harness. Write the commit message to a file and use `git commit -F <file>` (here-strings / `-F -` from PowerShell do not work).

## Hard constraints

- **PySide6 is pinned to 6.7.3** in `requirements-portable.txt` (the app must run on Windows Server 2016 / Win10 1607; Qt >= 6.8 needs `SetThreadDescription`, >= 6.9 needs system ICU). `tools/check_deps.py` enforces this during the portable build. Do not bump it.
- The portable build bundles an embeddable Python 3.12 and installs wheels offline-ready; changing dependencies means updating `requirements-portable.txt` and re-running the build script.

## Architecture

`s7trace/core/` is Qt-free (unit-testable); `s7trace/ui/` is PySide6. One window = `MainWindow` with one `TraceTab` per PLC connection (each tab is an independent connection with its own signals, trigger, REC, buffer).

**Acquisition path** (spans several files): `TraceTab.start()` -> `ProcAcquirer` (`core/acq_process.py`) spawns a **child process** running `Acquirer`/`DriverAcquirer` (`core/acquisition.py`) so GUI work (GIL) cannot delay PLC cycles. The child talks to the parent over a pipe (messages `batch`, `state`, `signals`, `info`); a parent reader thread feeds the `TraceBuffer` (`core/buffer.py`) and invokes `on_state`/`on_sample`/`on_info`, which the tab re-emits as Qt signals (`_stateRaw`, `_infoRaw`) to reach the GUI thread. `core/planner.py` groups signals into read requests; `core/drivers.py` gives OPC UA / Web API / Modbus the same client interface as snap7. `core/detect.py` (`identify_s7`, `probe_s7`) reads PLC identity and is shared by the connection wizard and the acquirer (device data is sent after every (re)connect).

**Plot** (`ui/plotview.py`): main plot + overview strip. Default Y layout is "lanes": each plotted signal gets a vertical band (row order, height proportional to `Signal.share`) scaled to the MIN..MAX of the visible window (BOOL fixed 0..gain); the alternative "offset" layout uses Offset Y/Gain/Auto Y. `clamp_view` keeps the manual view inside the collected data (also for the overview region); `MIN_WINDOW = 0.1 s`.

**Config** (`core/config.py`): JSON in `%APPDATA%\S7Trace` (`TabConfig` per tab + `ui` section: theme, geometry, splitters). `data_dir()` = `<Documents>\S7Trace` is where relative snapshot/REC folders resolve, per Windows user. File-name templates (`core/trigger.py`): `{confname} {ip} {tab} {date} {time}`; Start asks for `{confname}` only when a file will be written.

**Multi-user (same computer)**: `core/ip_history.py` (per-user connected-address history in `%APPDATA%`) and `core/sessions.py` (registry of running instances in `%ProgramData%\S7Trace\sessions`, fallback `C:\Users\Public\S7Trace`; heartbeat 2 s, stale after 10 s; `MainWindow` owns `Registry` and sets module global `sessions.REGISTRY`; `TraceTab.start()` only warns when another user scans the same PLC).

**REC targets** (full user-facing description in `BAZY_DANYCH.md`; keep it in sync when changing `store.py`) (`core/store.py`, Qt-free): `StoreConfig` (per tab, `TabConfig.store`; secrets saved only with "remember") selects CSV / SQLite / InfluxDB 1.x-2.x (plain HTTP + line protocol, urllib) / TimescaleDB (`psycopg`, lazy import). Samples are events (time, signal, value); mode "changes" (default, also for CSV) stores only changed values, `events_to_matrix` rebuilds step curves on read. `DbRecorder` has the same interface as `CsvRecorder` but writes from its own thread (batching, retry, bounded queue; network targets connect inside the thread). UI: REC panel combos + `ui/store_dialog.py` (settings dialog, "Import z bazy" window). All time/reliability parameters live in `StoreConfig` and are described once in `store.PARAMS` (limits + help text, shown in the "Czasy i bufory" tab of `StoreDialog`; menu Ustawienia -> "Zapis nagrań w bazach danych…" -> `TraceTab.edit_store(pick=True)`): keyframe interval (full state every N min in "changes" mode), batch/retry/timeouts, memory queue, disk `Spool` (local SQLite queue in `data_dir()/spool`, drained on reconnect, orphaned files delivered by the next run), SQLite rotation (`rotated_sqlite_path`, `sqlite_family`), TimescaleDB compression policy after `compress_days` (default 7, 0 = off; compressed chunks make deleting a recording harder), read thinning (`downsample_minmax`; SQLite also buckets in SQL beyond `MAX_READ_ROWS`). Influx has no NaN: availability goes to field `<sig>__ok`; range reads add a carry-in query. REC press runs `test_connection` in a thread (`TraceTab._probe_db`) and shows a non-modal box with "Przerwij REC". Recordings carry title/notes/tags/owner/computer (`Backend.update_session`, `delete_session`, `stats`; trash = `deleted_us`; InfluxDB 3 support was removed because it cannot delete a recording; a saved "influx3" target loads as CSV); `StoreImportDialog` is the "Przegląd nagrań" window (sort/search/user filter, properties, trash, retention, CSV export, load), `RecInfoDialog` asks for the title per `StoreConfig.title_ask` (start/during/end/off, see `TraceTab._open_recorder`/`_close_recorder(ask=…)`), `SpoolDialog` manages leftover disk buffers. PostgreSQL driver: `psycopg`, falling back to `pg8000` (`_psycopg`, `_pg_connect`); `tools/check_deps.py` and build-portable.ps1 report which one works in the package. Tests use a fake InfluxDB HTTP server and a fake `psycopg` (no real servers were available; psycopg/pg8000 on Server 2016 are untested).

**Chart rendering settings**: `core/render_cfg.py` (`PARAMS` = limits + help text, `normalize`), saved in `ui["render"]`, edited in `ui/render_dialog.py` (Ustawienia -> Renderowanie wykresu), applied by `MainWindow._apply_render` -> `TraceTab.apply_render` (timer interval = fps, `_tick` skips invisible tabs but still drains data / trigger / REC) -> `PlotView.apply_render` (curve / overview resolution, points limit `points_hidden`, point size, antialiasing, overview interval).

**UI frames**: `ui/fold_splitter.py` (thin hover-only resize handle, colour / "always" from theme keys `bar`, `bar_always`), `ui/pan_label.py` (status bar: draggable text, `status_lines`, `status_bg`, `status_text`), `ui/dialog_kit.py` (`@dialog_info(title, text)` on a QDialog: header strip + scroll area + fit to the screen on first show; the bottom button row stays outside the scroll area). `TraceTab._fit_left_min` keeps the settings panel at least as wide as its content. `TraceTab.import_db` / `load_recording` / `tooltip_html` (opening a DB recording into this or a new tab; the main window answers the tab-bar ToolTip event with `tooltip_html`).

**Web mode** (`s7trace/web/`, Qt-free, stdlib only; user-facing description in `WEB.md`, keep it in sync): central server `python -m s7trace.web` (`__main__.py`; `Web-Serwer.bat` in the package). `server.py` = `ThreadingHTTPServer` + `Handler` (cookie sessions in `WebSessions`, POST needs header `X-S7Trace: 1`, SSE `/api/connections/<id>/stream`, static front end in `web/static`: `index.html`, `app.js`, `style.css`, canvas chart), `auth.py` = `UserStore` (SQLite `web_users.db`, PBKDF2, lockout, protects last admin; Windows/AD via `LogonUserW`, replaceable `windows_check` in tests; roles viewer < operator < admin), `hosted.py` = `HostedConnection`/`HostManager` (headless tab: `ProcAcquirer` + `TraceBuffer`; every account has its own workspace file `workspaces/u_<user>.json`, connections without owner = shared from `--config`; `can_view`/`can_edit`/`can_run` by owner + role), `editing.py` = validated patch of a `TabConfig` from the browser (structural keys only while stopped; trigger / REC settings also while running, REC settings not while recording), `files.py` (per-account folders `files/u_<user>/{snapshots,rec}`, file-name templates, path-traversal-safe resolve), `targets.py` (DB recording targets defined by an admin in `web_targets.json`; secrets never leave the server), `HostedConnection` runs the trigger state machine and REC (`CsvRecorder` / `DbRecorder`) in the acquisition reader thread (`_on_sample`) and stops REC with the connection. Tests: `tests/test_web.py`, `tests/test_web_rec.py`. Done: login, overview, live chart, Start/Stop, accounts, per-account workspace, editing of connections + signals, trigger + REC + files + targets; `recordings.py` = `Library` (sources: own SQLite file / shared file / admin's other accounts / admin-defined targets; visibility + modify rules by role, owner and the target's `view_scope` / `delete_others`; list, thinned read, CSV, update, trash / purge, trash + retention policies applied on listing) used by `/api/recordings*`; `agents.py` (desktop programs report to `/api/agent/report` with an agent token; `Agents.scans` feeds the overview 'others' column and the answer to programs), `sso.py` (Negotiate / SSPI via ctypes: `Negotiate` server side per HTTP connection, `NegotiateClient` for tests; `/api/sso`, enabled by `--sso`, account must be registered with kind windows), wizard = `/api/detect` -> `core/detect.run_detection`. Desktop side: `core/web_agent.py` (`WebReporter`, Qt-free; `sessions.REMOTE` adds remote scans to `sessions.others_scanning` = the warning before Start), `ui/web_server_dialog.py`, `MainWindow._start_reporter` / `_refresh_agent_payload` (payload built in the GUI thread), config in `ui["web_server"]`. Tests: `tests/test_web_more.py`.

**Theming**: all styling is the QSS from `ui/theme.py::build_qss` (bold values in edit fields/combos/tables, one left padding for all fields). `IpEdit`/`IpCombo` (`ui/ip_edit.py`) are 4 fixed-width octet cells with undeletable dots; `text()` returns the plain address. `DurationCombo` is the editable "Okno czasu [s]" field with presets.

## Gotchas

- QMenuBar corner widget (tab bar) does not re-layout when its width changes: `MainWindow._place_corner()` sets its geometry manually.
- pyqtgraph: use `LegendItem.sigDoubleClicked` for legend double-click (scene click events are not emitted).
- Narrow left panel (min ~200 px): wide spin ranges / long combo items squeeze form labels; fields have `setMinimumWidth(70)` plus adjust policies (regression test exists).
- Tests: `tests/conftest.py` autouse fixtures redirect `%APPDATA%`, `%ProgramData%`, `%PUBLIC%` to temp dirs, auto-answer the `{confname}` prompt, and **stop and delete every TraceTab/MainWindow/dialog a test creates** (leftover widgets are re-styled on every later `setStyleSheet` and made the full run take 17 min). Do not delete arbitrary top-level widgets there (it crashes Python).
- Bash tool here collapses backslashes inside heredocs; for patch scripts or Windows paths with `\` use the Write/Edit tools instead.
- Web mode stage 1 is built (see Architecture); later stages (signal editing, trigger, REC from the browser, desktop app reporting its sessions to the server = a central registry across computers) wait for the user's decision. Open topic to resume only when the user returns: remote access/routing/VPN. The desktop `core/sessions.py` registry still covers one computer only.

## Status pracy równoległej (N komputerów)

Ten projekt bywa edytowany z więcej niż jednego komputera na przemian. `git push` robimy tylko na wyraźne żądanie użytkownika, więc jeden komputer może mieć niewypchnięte zmiany. Każdy komputer dopisuje/aktualizuje tu wpis o sobie (nazwę bierz z `hostname`).

**Aktualny stan:**

- `PL-LAP-00354` (Windows 11) — **brak aktywnych zmian** (ostatni push: 2026-10-04, `337439a` opis trybu Web `WEB.md`; wcześniej `8d7fffd` tryb Web etapy 2–3 i `f7c100a` etap 1).

**Zasada:** na początku sesji sprawdź tę listę i `ListAgents`; jeśli inny komputer ma „w trakcie edycji”, powiedz o tym przed commitem/push. Po realnym `git push` zaktualizuj swój wpis.
