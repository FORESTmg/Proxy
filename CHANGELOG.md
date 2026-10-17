# Changelog

All notable changes to **FOREST's Proxy Auto-updater** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.2] — 2026-10-17

### Fixed

- **The tray icon was not the user's artwork.** `tray_icon.user_state_ico` painted
  the connection colour **over** the user's `app.ico` at 90 % blend, so the icon
  collapsed into a single flat coloured tile — the drawing (cyan ring, green
  swoosh, red chain, white plane) was gone. The artwork is now copied **without a
  single altered pixel** and the state is shown by a small **badge in the
  bottom-right corner** (`tray_icon.mark_state`). Proved pixel by pixel in
  `forest-ui --selftest`: 77.8 % of the 32×32 pixels are byte-identical to
  `app.ico`, and the badge reads 100 % at the badge centre.
- **The build could silently replace the icon.** `build.ps1` drew a *generated*
  `app.ico` (`make_icon.py`) whenever the file was missing, and `make_icon.py`
  overwrote an existing file without asking. The build now verifies `app.ico`
  against the hash recorded in `packaging/app.ico.sha256` and **stops** if the
  file is missing (`-GenerateIcon` is the explicit opt-in); `make_icon.py` refuses
  to overwrite without `--force`; the Linux builds run `packaging/check_icon.sh`.
- **The notification window had no visible animation and no step times.** The
  entrance was 260 ms and there was no hold indicator. The card now has three
  clearly visible phases — entrance (48 px slide + fade, **350 ms**), hold (a
  spinner turns by the icon and the progress bar is eased), exit (slide back +
  fade, 260 ms) — at 60 fps without flicker and without ever taking focus. Steps
  are rendered **with their duration in milliseconds** and the final line carries
  the **link-recovery time in ms** as well (`восстановлено за 1.85 с (1850 мс)`).
- **The "Filters" section was missing from the Qt menu.** `forest_ui` now shows a
  **Filters** submenu with two checkable items (**RU direct**, **Cloudflare
  bypass**); the tick follows the live settings and the click goes through
  `state/ui_cmd.json` to the supervisor (`filter_ru_on/off`, `filter_cf_on/off`),
  which applies it through the very same code as the built-in menu.
- **`Unhandled exception in script` modal window on the desktop.** The helper's
  `--selftest` printed `✓` (U+2713) to stdout; a windowed PyInstaller build has no
  console and its "console encoding" on Windows is cp1251, so `UnicodeEncodeError`
  escaped and PyInstaller showed a **modal window**. Fixed at three levels
  (`src/safestdio.py`): stdout/stderr are switched to `utf-8` + `errors="replace"`
  (a missing stream gets a sink), stdout is **ASCII-only** (non-ASCII becomes `?`)
  while the human-readable report goes to UTF-8 files, and any unhandled exception
  is written to `logs/crash.log` with exit code 70 — `disable_windowed_traceback`
  is on in every spec, so a modal window is impossible.
- **`forest_ui` crashed on import when Qt was absent** (`class Toast(QtWidgets.
  QWidget)` → `NameError`) instead of exiting quietly with "Qt is unavailable";
  stub classes now let the module import.
- `src/tray_check.py` expected `state=switch/restoring` to give the `ok` icon; the
  code has returned `busy` (amber, "switching") for a long time — the stale check
  was corrected (it was red before this release).
- `log.py` printed every line to stdout with `print()`; it now goes through the
  safe printer (stdout ASCII, full text always in the log file).

### Added

- **`src/safestdio.py`** — safe stdout/stderr, ASCII-only `say()`, UTF-8 report
  files, `crash_log()`, `install_excepthook()` and `guarded()` (the entry-point
  wrapper). Used by both the main program and the helper.
- **`packaging/app.ico.sha256`** and **`packaging/check_icon.sh`** — the icon pin
  and the Linux-side check.
- **`state/ui_selftest.txt`** — the full UTF-8 self-test report (stdout stays
  ASCII, as a windowed build requires).
- New self-test sections: the icon pixel proof, the Filters submenu and its
  commands, the animation phase/position/opacity time series, the notification
  text in milliseconds, and the crash-safety checks (7 and 15).

### Changed

- **Linux**: the notification has no window of its own, so the **recovery steps
  and their millisecond durations are passed in the BODY** of the system
  notification; the app icon (`forest-proxy-updater.png`, the same artwork) is
  installed into `share/icons/hicolor/256x256/apps` and named in the `.desktop`
  file. `--status` prints an ASCII summary and the full report goes to
  `state/status.txt` (UTF-8).

## [1.2.1] — 2026-10-17

### Fixed

- **Two copies of the program and two helpers (two tray icons) could run at
  once.** The single-instance guard was a *marker file with a process id* plus a
  process-list scan, and both sides of that heuristic were wrong on a live
  machine:
  * starting two copies **at the same instant** ended with **zero** survivors —
    each copy saw the other `--run` process in the list and both refused to
    start;
  * when the recorded pid was judged dead (a killed/restarted supervisor, a
    dead-recorded marker) a new launch **took the marker over** while the old
    supervisor kept running, and its `watch`/`tray` threads launched a **second
    helper** as well — the log shows two supervisors and two helper launches at
    the same second, hence two tray icons and two supervisors competing for
    `state/state.json` (`WinError 32`, `state.json.tmp`).

### Added

- **`src/instancelock.py` — a real single-instance lock.** An exclusive file lock
  held for the whole life of the process: `msvcrt.locking` (`LockFile`) on
  Windows, `fcntl.flock` on POSIX. The kernel releases the lock together with the
  process, so there are no stale locks and no start-up race. Locking is
  non-blocking: a second attempt gets an immediate refusal. The file also carries
  JSON with pid/exe/root/argv, but that is **diagnostics only** — every decision
  is made by the lock itself. `--selftest` proves exclusivity with an independent
  attempt (a forked child on POSIX, a second handle on Windows) and checks that a
  dead owner leaves no held lock.

### Changed

- **`watchdog.py`** — `state/supervisor.lock` is now that lock (the name and the
  diagnostics JSON stay, so `--status` and the docs keep working). `claim_supervisor`
  makes exactly one atomic decision — the lock — and no longer scans the process
  list to decide whether a second copy is needed. `find_live_supervisor`,
  `_marker_live_pid` and `watchdog_report` report the pid from the lock (with the
  old marker/scan path kept only as a transition/compat path), and the process
  scan additionally requires the process to belong to *this* installation (its
  root or config path must appear in the command line), so installations, the
  sandbox and the self-test can no longer see each other.
- **One rule for self-control.** `run_supervisor` marks its process
  (`FOREST_SUPERVISOR=1`); `watchdog.ensure()` refuses to start anything from
  such a process, and `_spawn_detached()` refuses as a second line of defence.
  `--ensure`, the Task Scheduler action and every internal caller therefore share
  one rule: **a live lock means do nothing**; the start-up itself is serialised by
  a short `state/ensure.lock` (also a real lock, no stale-age heuristics).
- **`ui_helper.py` / `forest_ui.py` / `tray.py` — one helper, one tray icon.** The
  helper now holds an exclusive lock (`state/forest-ui.lock`) for its whole life,
  which it takes before building the interface; `ui_helper.running()` decides by
  that lock (the heartbeat JSON is only used to show the pid), `ui_helper.ensure()`
  is serialised by a short lock and never launches a copy from inside a helper. A
  second helper now exits quietly instead of adding a second icon. The built-in
  (reserve) tray icon no longer competes with the helper: the tray thread waits up
  to 20 s for the helper — which comes up a second or two after the supervisor —
  and then does not create its own icon at all, and if the helper appears later it
  removes its own icon (`tray-handover`).
- **Linux**: `posix_platform.ensure()` respects the same supervisor lock, and the
  POSIX self-test gained lock checks (`--selftest` covers the lock on both
  platforms).
- Documentation (README, README.ru, ARCHITECTURE, ARCHITECTURE.ru) explains the
  lock and the three properties it guarantees.

## [1.2.0] — 2026-10-17

### Added

- **Indication is now exactly the composition of the previous add-on.** The old
  setup (`D:\v2ray-auto-updater`, switched off but kept for rollback) is the
  reference: its contents, texts and colour codes were ported verbatim into one
  place (`src/status_info.py`) and are used by **both** interfaces (the built-in
  icon and the Qt helper), so nothing is lost and the two can never drift apart:
  * the icon tooltip keeps the four reference fields in order —
    `FOREST <link state> | <N> servers | <RU route> | watch OK` (the previous
    version always printed “10 servers”, a hard-coded default — the field is
    kept, the number is now the real pool size);
  * the indication card keeps the reference title, subtitle, percentage, the
    step list **with per-step times**, and the footer, including
    **the link recovery time** (`восстановено за N.NN с · окно закроется через
    4 с`, `связь подтверждена · N.NN с`) — recovery time is now also persisted
    (`last_restore_s`/`last_restore_ts`) so it stays readable in the menu after
    the card is gone;
  * six icon states with the reference colours: `ok` (57,194,109), `off`
    (132,132,140), `switch` (240,180,41), `noanswer` (240,180,41), `down`
    (229,72,77), `restoring` (79,140,255);
  * the menu keeps the reference items (open log, open status, enable/disable the
    proxy by hand, exit) and adds what cannot be left out (supervision,
    notifications, theme, refresh, about).
  What changed is only the smoothness (60 fps) and the look (our light/dark
  palette, the user's own icon with the state colour inside).
  Verified side by side by running the reference read-only (its modules imported
  in a throwaway state directory — the live proxy, ports 10808/10820 and the
  registry are untouched): every title, subtitle and colour matches, the field
  lists are identical.
- **Interface helper `forest-ui` (Qt/PySide6, LGPL-3.0).** The interface is now a
  **separate program** shipped as its own artefact, so the main program stays
  small and dependency-free. It draws the tray icon (your `app.ico` with the
  connection colour painted **inside** the picture — four distinct states,
  readable on light and dark taskbars), a **menu with submenus** (status,
  supervision on/off, notifications on/off, **theme: follow system / light /
  dark**, refresh now, test notification, open log, about, quit) and
  **notifications** as a frameless translucent card (rounded corners, shadow,
  your icon) sliding in and fading out at **60 fps** that **never takes focus**.
  The helper **does not touch the core**: a menu item is written to
  `state/ui_cmd.json` and performed by the supervisor through exactly the same
  code as the built-in menu; state comes back through `state/tray_status.json`
  and a heartbeat in `state/ui_helper.json`. Settings: `ui.helper` =
  `auto`|`on`|`off`, `ui.helper_exe`. Build: `packaging/build-ui.ps1`,
  `packaging/build-ui.sh`, spec `packaging/forest-ui.spec`.
- **Interface fallback, honestly.** No helper, a crashed helper, no system tray —
  the built-in ctypes icon and the built-in notifications (`src/notify.py`) work
  as before; the built-in tray waits in reserve while the helper is alive and
  takes over within seconds after it stops, and notifications are only shown by
  whichever side owns the interface (never twice).
- **Themes (light/dark) as one source of truth** — `src/theme.py`: palettes for
  the notification card, the tray icon and the menu styling (QSS comes from the
  same palette), automatic detection (Windows registry / `gsettings`, with
  `FOREST_THEME`, `GTK_THEME`, `COLORFGBG` as fallbacks) and a `ui.theme`
  override. State colours are checked against WCAG (minimum contrast 3.36:1).
- **Notifications (`src/notify.py`, Windows)** — layered window drawn with a
  single `UpdateLayeredWindow` per frame (no flicker at all, no `WM_PAINT`, no
  child controls), shown with `SW_SHOWNOACTIVATE`/`WS_EX_NOACTIVATE` so the
  active window keeps focus, frames scheduled on a **high-resolution waitable
  timer** on an absolute timeline (no drift) — measured: **60.0 fps average,
  worst frame 17.4 ms, 0.0 ms CPU in idle, focus unchanged**.
- **Helper keep-alive.** `--install`, the scheduled task (`--ensure`, every
  minute) and the supervisor (every 30 s) all call the same `ui_helper.ensure()`,
  so a crashed helper comes back by itself and a second copy is never started
  (`state/ui_helper.json` plus a live-process check).
- **Linux**: the same helper provides a real tray icon and menu (StatusNotifier/
  D-Bus); notifications in the helper go through `org.freedesktop.Notifications`
  (the fallback path in `posix_platform.py` now uses the same `gdbus` →
  `notify-send` chain with the app icon and urgency); packages install the icon
  and `.desktop` files (`forest-proxy-updater.desktop`, `...-ui.desktop`).
- **Autonomous supervision — the program brings itself back.** `--install` now
  registers a **Task Scheduler task** `ForestProxyUpdater-Watchdog` (hidden, runs
  as the current user, `MultipleInstancesPolicy=IgnoreNew`) with a logon trigger
  and a repeat-every-5-minutes trigger, whose action is
  `ForestProxyUpdater.exe --ensure`. It **replaces** the old `HKCU\...\Run`
  autostart entry (removed by `--install`), so exactly one mechanism brings the
  program up.
- **`--ensure`** — a quick check (own marker file + live-process scan) that
  launches `--run` **detached from the calling process** (`DETACHED_PROCESS` +
  `CREATE_BREAKAWAY_FROM_JOB`, own process group) when no supervisor of *this*
  installation is alive. It refuses to create a second supervisor, writes only to
  the log and never shows a window.
- **`--watchdog on|off|status`** and a `watchdog` config section
  (`{"enabled": true, "interval_min": 5, "task_name": "..."}`, on by default).
  `--watchdog off` deletes the task and the program honestly stops restarting
  itself; `--status` and `--watchdog status` print the supervision state (setting,
  task present?, last run, is the program running now). The tray menu gained
  **Supervision → “Bring the program up automatically”**.
- **Honest first-run notice.** `--install` tells the user in plain words that a
  task was created and enabled, that it raises the program at logon and every
  5 minutes, and that switching supervision off means the program will **not**
  restart itself and must be started by hand. The same warning is printed by
  `--watchdog status` / `--status`.
- **Self-test section 14** (watchdog): config defaults, task XML (logon trigger,
  5-minute repetition, hidden, IgnoreNew, current user), marker/claim logic
  (a second `--ensure`/`--run` must not create a second supervisor) and a check
  that `watchdog.enabled=false` does not create a task.
- **Linux**: `--ensure` implemented for systemd — it starts the user service if it
  is not active. Supervision on Linux remains systemd's job
  (`Restart=always` plus the update timer).
- **Console debug build** for safe testing: `FOREST_CONSOLE_BUILD=1` builds
  `ForestProxyUpdater-console.exe`, whose bootloader errors go to stderr instead
  of a desktop dialog.

### Fixed

- **Notification animation did not run (0 frames) after the switch to the
  high-resolution waitable timer.** The timer was armed once in `start()` and
  never re-armed, so exactly one frame was drawn and then the window sat still
  until it timed out. Frames are now scheduled on an **absolute timeline**
  (`next_due += period`), the timer is re-armed after every frame, `_disarm()`
  uses `CancelWaitableTimer()`, and frames that are more than one period late are
  counted as dropped instead of accumulating debt (which would make the animation
  stutter). Verified: 117 frames for a 1.96 s animation, average **60.0 fps**,
  worst frame **17.4 ms**.
- **Modal window “Failed to remove temporary directory”** (Windows, PyInstaller
  onefile). A copy of the program started **by the program itself** (the new
  `--ensure` → `--run` launch) inherited PyInstaller's `_PYI_APPLICATION_HOME_DIR`
  and `_PYI_PARENT_PROCESS_LEVEL`, so the child **reused the parent's `_MEI`
  unpack directory** instead of extracting its own; the parent then could not
  delete `_MEI` (its files were still in use by the surviving child) and showed
  the modal error. The child environment is now cleared of the PyInstaller
  variables (plus `PYINSTALLER_RESET_ENVIRONMENT=1`), so every process owns and
  removes its own `_MEI`. In addition the program leaves the unpack directory on
  start (`config.ensure_safe_cwd`, before any child process is launched) and
  starts its background processes with a working directory outside the unpack
  directory.

### Changed

- `--install` no longer writes an autostart entry to the registry; the single
  autostart mechanism is the scheduler task. `--uninstall` removes the task, any
  legacy autostart entry, the shortcut and the files.
- The identity used for “is a supervisor of *this* installation alive” is derived
  from the running executable (`sys.executable`) and the state directory, so two
  different installations (a working one and a test sandbox) never see each other.

## [1.1.0] — 2026-10-17

### Added

- **Linux packages.** The Linux build now ships as real packages, all built from
  one shared file layout (`packaging-linux/lib/common.sh`, so the formats cannot
  drift apart): `.deb` (Debian/Ubuntu/Mint), `.rpm` (Fedora/RHEL/Rocky/Alma/
  openSUSE), Arch `PKGBUILD` + `.pkg.tar.zst`, a universal `AppImage` and a
  portable `.tar.gz` with `install.sh` / `uninstall.sh`. Every format installs
  **one systemd system service** (no logged-in user and no
  `loginctl enable-linger` required) and needs nothing dropped in by hand: the
  Xray core and both geo databases are inside the binary. Installation is a
  single command, removal is the distribution's own (`apt purge` / `dnf remove` /
  `pacman -Rns`) or `uninstall.sh`. Instructions:
  `docs/LINUX-INSTALL.md` and `docs/LINUX-INSTALL.ru.md`.
- **Terms of use and disclaimer** (`docs/TERMS.md`, Russian: `docs/TERMS.ru.md`),
  linked from both READMEs, printed for a few lines by the package installers
  (`.deb` / `.rpm` / Arch / `.tar.gz`) and shown once on the first run (plus a
  line in `--help`). The program gives access to
  all websites, including blocked ones; complying with the laws of your own
  jurisdiction is your responsibility. GPL-3.0 is not replaced by this notice —
  it is added to.
- **Package matrix bench.** `linux/tests/wsl-matrix.sh` now also handles
  `.tar.gz`, `.AppImage` and user-mode (`systemctl --user`) installs, waits for
  the product's real first selection cycle before probing traffic
  (`--traffic-wait`, minutes not seconds) and steers the payload to a test port
  through `FOREST_CONFIG` without modifying the shipped config;
  `linux/tests/run-matrix.sh` runs the whole package × distribution matrix and
  writes a `summary.csv`. Results of the release run:
  `docs/LINUX-PACKAGES-PROOF.ru.md`.

### Fixed

- **Modal window “Failed to remove temporary directory” and leftover `_MEI*`
  folders.** The app is a PyInstaller onefile bundle, and the Xray core used to
  be started straight **from the unpacked temp directory** (`_MEIxxxx/bin/xray`).
  The core outlives the program by design (the proxy must keep running), so the
  file stayed busy: the PyInstaller cleanup could not delete the directory,
  showed a modal `Warning` window and left `_MEI*` folders behind (on Windows
  every run with an empty `client.core`). The core and both geo databases are
  now **copied once from the bundle into a permanent directory** and the core is
  started only from there: `%LOCALAPPDATA%\ForestProxyUpdater\bin\xray`
  (Windows, or `<FOREST_ROOT>\bin\xray`) and
  `~/.local/share/forest-proxy-updater/bin/xray` (`$XDG_DATA_HOME`) on Linux.
  The copy is compared by size and SHA-256 and only happens when the file is
  missing or the bundle is newer, so an ordinary start neither copies nor reads
  anything extra. `client.core` may now stay empty (or relative —
  `bin/xray/xray(.exe)` is resolved against the data/program directory); no
  machine-specific absolute path is required. The program also removes **its
  own** stale `_MEI*` folders from temp on start (a background thread; only
  directories that contain our `bin/xray`, never the current unpack directory,
  never younger than 2 minutes, and never one a process is still running from —
  on Windows that is decided by a non-destructive write probe on the files).
- **Installer wrote a broken launch command.** `--install` used to register the
  Start Menu shortcut and the autostart entry as `pythonw.exe "<dev
  folder>\src\v2ray_updater.py" --run`, so clicking the shortcut or rebooting
  produced a modal error window. `--install` now **copies the product `.exe`
  into the install directory** (`%LOCALAPPDATA%\ForestProxyUpdater\
  ForestProxyUpdater.exe`) and registers exactly
  `"<install dir>\ForestProxyUpdater.exe" --run` — no extra script argument and
  no dependency on the folder the archive was unpacked into. Both the shortcut
  and the registry value are read back and compared right after being written
  (the result is logged). `--uninstall` now also removes the installed `.exe`
  (deferring to a cleanup script when `--uninstall` runs from that very `.exe`,
  which Windows will not let a process delete).
- **State file lost keys written by another writer.** `StateStore.save()`
  replaced the whole file from its own in-memory snapshot, so the pool
  fingerprint, its hash and the freeze timestamp written while the balancer was
  raised were wiped by the cycle's final save — the pool freeze and the
  "unchanged pool" fast path silently stopped working. Saves now merge with what
  is on disk (keys are never dropped).
- **Orphan cores were never reaped.** The "our core" lookup matched the literal
  `forest_xray.json`, while the config actually used is
  `state/xray_config.json`; a leftover core could keep holding the client port.
  The lookup now matches our own state directory.

### Changed

- **Seamless core switching.** The new core config is validated **before** the
  running core is stopped (`xray run -test -config <file>`; automatic fallback
  to the old "start on free ports" check if a core build does not support
  `-test`), so a broken config can no longer take the link down. The live config
  file is only replaced after it passes.
- The core is **not restarted when nothing changed**: the pool fingerprint
  (`balancer_sig`) and the hash of the config the running core actually uses
  (`balancer_cfg_sha`) are compared first; an identical config or a frozen pool
  (`watch.pool_freeze_s`) means no restart at all, even for `force=True`.
- Restart is now measured: the log gets the actual **link gap in milliseconds**
  (from stopping the old core to the new one accepting the client port, plus the
  time until data is confirmed). The fixed 300 ms sleep after stopping the core
  is gone — the new process starts immediately and the port is polled for
  release.
- Faster restart path (the measured gap drops from ~0.9–1.1 s to ~0.2 s):
  stopping uses `TerminateProcess` (no `taskkill.exe` spawn), the orphan sweep
  (a ~0.4 s PowerShell query) only runs when there was no live core to stop, the
  port is polled in 10–50 ms steps, and the balancer no longer re-probes a link
  that the restart already confirmed.
- `start_core` verifies that the new core process is still alive after the port
  comes up, so a foreign/orphan process holding the port is not mistaken for a
  healthy core.
- `--install` now reports a first cycle that found no live servers (the install
  itself is complete; the watchdog keeps retrying and raises the link as soon as
  usable nodes appear) instead of staying silent about it.
- The single-server activation path and the guard failover path validate their
  configs before touching the live one as well.

## [1.0.0] — 2026

First public release.

### Added

- **Standalone mode (default).** The program does not need v2rayN. It keeps its
  own server list (`state/servers.json`), writes the Xray-core config itself,
  starts and stops `xray.exe` itself, and sets/clears the Windows system proxy
  itself.
- **Optional v2rayN mode** (`client.mode: "v2rayn"`). Works through an already
  installed v2rayN — its SQLite database (`guiNDB.db`), its config
  (`guiNConfig.json`) and its core — with backup/rollback of the database.
- **Automatic server selection.** Subscriptions are fetched from configured
  fixed URLs and from GitHub repositories found by search; share links
  (`vless://`, `vmess://`, `trojan://`, `ss://`) are parsed, de-duplicated and
  filtered.
- **Test pipeline:** TCP pre-filter, RTT measurement through one throwaway Xray
  instance per candidate, jitter filter, speed test on the best-by-RTT subset,
  final re-check (RTT + a YouTube reachability check).
- **Native Xray balancer.** One running core holds a pool of servers with
  `observatory` (health checks) and `leastPing` balancing, so new connections
  go to a live/fast node without restarting the core.
- **Watchdog ("watch")** that keeps the core alive, notices a dead port in
  1–2 s, monitors throughput and uses YouTube as a canary; on full failure it
  asks for a full refresh cycle.
- **Guard loop** for one quick self-check/recovery pass (failover over the
  stored `[AUTO]` servers, then a full cycle).
- **Automatic failover and an emergency "last good" pool** that is raised when
  no live servers can be found.
- **Subnet diversity cap** (default: at most one server per /24) with a floor
  that relaxes the cap if the pool would otherwise be too small.
- **Cloudflare-node filter** (on by default): nodes whose address is inside
  Cloudflare's ranges are dropped from the server list.
- **Manual proxy-off flag**: if the proxy is switched off by hand, the program
  does not raise it again on its own.
- **Single-process supervisor** running the watchdog, guard, update and tray
  threads in one program instead of three separate scheduled tasks.
- **Save/restore of the original system proxy** so `--uninstall` returns
  Windows to the state it was in before the first run.
- **Bilingual output (Russian + English)** for the CLI strings (status,
  install, self-test, banners), selected by `ui.lang` or the system locale.
- **Self-test suite** (`--selftest`) that checks the API surface, the server
  store, core/balancer config generation, the mode dispatcher, i18n, first-run
  config creation and core discovery — without network, without touching the
  system proxy and without occupying the real ports.
- **No third-party Python dependencies** — the standard library only.

### Known limitations in 1.0.0

- The **visual tray icon is not implemented yet** (planned via Win32
  `NotifyIcon`/ctypes). The status channel (`state/tray_status.json`) and its
  consumer thread already exist; only the on-screen icon is missing.
- **i18n is partial:** CLI strings are translated, long-cycle log messages are
  still Russian only.
- Long-cycle messages are written to the log in Russian regardless of
  `ui.lang`.

### Notes

- Licensed under **GPL-3.0-only** (see `LICENSE`).
