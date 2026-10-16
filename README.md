# FOREST's Proxy Auto-updater

Automatic selection and switching of proxy servers. **Standalone by default**:
the program does not require v2rayN — it keeps its own server list, writes the
Xray-core config itself, starts/stops `xray.exe` itself and sets/clears the
Windows system proxy itself. Optional v2rayN mode is available for users who
already run v2rayN.

- License: **GPL-3.0** (see `LICENSE`)
- Languages: Russian + English (see `README.ru.md`)
- No third-party Python dependencies — standard library only
- One process (supervisor) instead of three separate scheduled tasks

## Layout

```
ForestProxyUpdater/
  src/       program code (Python, stdlib only)
  docs/      documentation (separate stage)
  packaging/ .exe build (PyInstaller spec, separate stage)
  LICENSE, README.md, README.ru.md, .gitignore, config.example.json
```

## Two modes (chosen in config.json, no code changes)

| `client.mode` | Behaviour |
|---|---|
| `standalone` (default) | Own Xray core, own server store, own system-proxy management. No v2rayN needed. |
| `v2rayn` | Works through an installed v2rayN (its database and core), like the original project. |

Core discovery in standalone mode: `bin\xray\xray.exe` next to the program →
`PATH` → otherwise the program tells you to download the official Xray-core
release (`https://github.com/XTLS/Xray-core/releases`).

## First run without a config

If there is no config, `config.example.json` is copied to `config.json` with
sane defaults: no Cloudflare gate, `diversity.per_subnet_cap: 1`,
`min_pool_after_cap: 12`, **RU-direct off** (so a stranger's routing is not
broken), ports `10808`/`10820`, minimum speed `1000` KB/s.

State, logs and the working config live under
`%LOCALAPPDATA%\ForestProxyUpdater` by default — the source tree stays clean.

## Commands

```
python v2ray_updater.py --install     # lay out into %LOCALAPPDATA%\ForestProxyUpdater,
                                      # shortcut + autostart + first cycle
python v2ray_updater.py --uninstall   # remove everything, restore the system proxy
python v2ray_updater.py --run         # normal run: supervisor with tray (threads)
python v2ray_updater.py --once        # one full server-selection cycle
python v2ray_updater.py --guard       # one quick self-check / recovery
python v2ray_updater.py --status      # current status
python v2ray_updater.py --selftest    # run the test suite
```

Background work runs with `CREATE_NO_WINDOW` / `pythonw` semantics — no console
windows.

## Tests

```
python -m py_compile src/*.py
python src/v2ray_updater.py --selftest
```

## What is not done yet (next stages)

- Tray icon (Win32 NotifyIcon via ctypes). The status channel
  (`state/tray_status.json`) and its consumer thread already exist; only the
  visual icon is missing.
- Full i18n coverage (the CLI strings are translated; long-cycle log messages
  are still Russian).
- PyInstaller build of a single `.exe` (see `packaging/`).
- Documentation (see `docs/`).
