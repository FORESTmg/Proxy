# Changelog

All notable changes to **FOREST's Proxy Auto-updater** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
