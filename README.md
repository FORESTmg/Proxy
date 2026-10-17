# FOREST's Proxy Auto-updater

Automatic selection and switching of proxy servers on **Windows and Linux**. The
program downloads public server lists, tests the servers, picks the working ones
and keeps your connection going by switching between them — so that a single
server dying out does not break your internet access.

**Standalone by default.** The program does *not* require v2rayN. It keeps its
own server list, writes the Xray-core config itself, starts and stops
`xray.exe` itself and sets/clears the Windows system proxy itself. An optional
v2rayN mode is available for people who already use v2rayN.

- License: **GPL-3.0-only** (see [`LICENSE`](LICENSE))
- Languages: Russian + English (see [`README.ru.md`](README.ru.md))
- Vibe-coded — written iteratively in close dialogue with an AI assistant, so
  please verify behaviour yourself before you rely on it
- No third-party Python dependencies — the standard library only
- One process (supervisor) instead of three separate scheduled tasks

> **Read the [Security and limitations](#security-and-limitations) section
> before you run it.** The program changes the Windows system proxy and manages
> a proxy-core process. That is by design, and it is described plainly there.
>
> **By using the program you accept the
> [Terms of use](docs/TERMS.md)** — it provides access to all websites, including
> blocked ones, and complying with the laws of your jurisdiction is your
> responsibility.

---

## Who it is for

- People who want a **working proxy on Windows without babysitting it** —
  start it once, and it re-selects servers as the free ones die.
- People who already have subscription links or a v2rayN setup and want the
  server list kept fresh and the active server switched automatically.
- People who want to **see exactly what it does** — it runs a plain Xray core
  and points the Windows system proxy at a local port; there is no hidden
  magic, and no third-party Python packages.

It is **not** for you if you need a guaranteed, stable, high-speed service.
Public free servers are unstable by nature — see the limitations section.

## How it differs from v2rayN

v2rayN is a full GUI client: you import servers, choose one and connect.
FOREST's Proxy Auto-updater is the opposite kind of tool — it is a **background
worker** with no server-management GUI. It:

- **finds and tests servers for you** rather than waiting for you to pick one;
- **keeps a pool of servers inside one running core** and lets Xray switch
  between them, instead of restarting on every change;
- **watches the connection continuously** and re-selects when servers die;
- **manages the Windows system proxy** so that system-wide traffic follows the
  working core.

In other words, v2rayN is the client you configure; this program is the thing
that keeps a client's server list alive. They are not competitors, and the
program can also *drive an installed v2rayN* if you prefer (see the two modes
below).

## Two modes

You choose the mode in `config.json` (in `client.mode`). No code changes.

| `client.mode` | What it does |
|---|---|
| `standalone` (default) | Own Xray core, own server store, own system-proxy management. v2rayN is not needed. |
| `v2rayn` | Works through an installed v2rayN: its database (`guiNDB.db`), its config (`guiNConfig.json`) and its core. The database is backed up before writing. |

In standalone mode the core is looked up in this order:

1. an explicit path from the config (`client.core`);
2. `bin\xray\xray.exe` next to the program;
3. `xray.exe` in `PATH`.

If the core is not found, the program tells you and points you to the official
Xray-core release page. **The program does not download the core for you** — you
put `xray.exe` in place yourself.

## Quick start

The distributable is a single `.exe`. The usual flow:

1. **Download** the `.exe` from the project's GitHub Releases page.
   2. **Nothing to download — the core is already inside.** The `.exe` ships with
      Xray v26.3.27 and both geo databases (`geoip.dat`, `geosite.dat`) embedded, so
      standalone mode works on a clean machine with no extra files. Put your own
      `bin\xray\` folder beside the `.exe` only if you want to override or update
      the core — that copy takes priority over the built-in one.
      v2rayN mode needs no files at all: v2rayN provides its own core.
3. **Run the `.exe`.** Windows will warn about an unsigned program
   (SmartScreen) — see the security section. On first run the program creates
   its working config from `config.example.json`, lays itself out under
   `%LOCALAPPDATA%\ForestProxyUpdater`, adds a Start Menu shortcut and an
   autostart entry, and runs the first selection cycle.
4. After the first cycle, **the Windows system proxy is pointed at the local
   port** `127.0.0.1:10808` and traffic goes through the selected servers.

State, logs and the working config live under
`%LOCALAPPDATA%\ForestProxyUpdater`. The folder you unzipped the program into
stays clean.

At runtime the program uses tools that ship with Windows — `curl.exe`
(Windows 10 1803+), and `PowerShell`/`tasklist`/`taskkill`/`netstat` for
process and port checks. No administrator rights are required.

### Removing it

Run the `.exe` with `--uninstall` (or the "uninstall" entry the packaged build
provides). This stops the core, **restores the system proxy to the state it had
before the first run**, removes the autostart entry and the shortcut, and
deletes `%LOCALAPPDATA%\ForestProxyUpdater`.

## Linux

The same program, packaged for Linux (x86_64): the proxy core is `xray`, service
management is systemd. **Nothing has to be dropped in by hand** — the Xray core
and both geo databases (`geoip.dat`, `geosite.dat`) are embedded in the single
executable, and Python is not required. The only dependency is `curl`.

Every package installs with **one command**:

| Format | Distributions | Install | Root |
| --- | --- | --- | --- |
| `.deb` | Debian, Ubuntu, Linux Mint | `sudo apt install ./forest-proxy-updater_1.1.0_amd64.deb` | yes |
| `.rpm` | Fedora, RHEL, Rocky, Alma, openSUSE | `sudo dnf install ./forest-proxy-updater-1.1.0-1.x86_64.rpm` | yes |
| `.pkg.tar.zst` | Arch, Manjaro, EndeavourOS | `sudo pacman -U ./forest-proxy-updater-1.1.0-1-x86_64.pkg.tar.zst` | yes |
| `.AppImage` | any glibc x86_64 | `./ForestProxyUpdater-1.1.0-x86_64.AppImage --install` | **no** |
| `.tar.gz` | any | `tar xzf forest-proxy-updater-1.1.0-linux-x86_64.tar.gz && cd forest-proxy-updater-1.1.0-linux-x86_64 && sudo ./install.sh` | yes |

Check it once the first selection cycle has finished (a few minutes — the
program is downloading and testing hundreds of public servers):

```sh
curl -x http://127.0.0.1:10808 -o /dev/null -w '%{http_code}\n' \
     https://www.gstatic.com/generate_204          # expect 204
systemctl status forest-proxy-updater.service
journalctl -u forest-proxy-updater -f
```

The packages install a **system** service, so autostart needs no login and no
`loginctl enable-linger`. The AppImage and `install.sh --user` install
`systemd --user` units instead and enable linger automatically. Removal is
handled by the package manager (`apt purge` / `dnf remove` / `pacman -Rns`) or by
`uninstall.sh` / `--uninstall`.

Full instructions: [`docs/LINUX-INSTALL.md`](docs/LINUX-INSTALL.md) (English) and
[`docs/LINUX-INSTALL.ru.md`](docs/LINUX-INSTALL.ru.md) (Russian) — install,
configuration, logs, verification, removal, and what to do when `systemctl --user`
is unavailable. Internals: [`docs/LINUX-ARCHITECTURE.ru.md`](docs/LINUX-ARCHITECTURE.ru.md)
(Russian). Packaging from source: [`packaging-linux/README.md`](packaging-linux/README.md).

## How it works

A single program runs several worker threads (a "supervisor"):

- **Source manager** — fetches subscription files from the fixed URLs in the
  config and, periodically, searches GitHub for fresh public server repos. A
  source is dropped if it has not changed for `sources.stale_days`.
- **Test pipeline** — candidates are de-duplicated, optionally pre-filtered by
  TCP reachability, then each candidate is raised as a **throwaway Xray
  instance** on a temporary port to measure RTT, then the best ones are speed
  tested, then the top ones are re-checked (RTT again + a YouTube reachability
  probe). Servers have to pass speed and jitter thresholds to be kept.
- **Balancer** — the servers that passed are written into **one** Xray config
  as a pool of outbounds, together with Xray's own `observatory` (health
  checks) and a `leastPing` balancer. Xray then sends new connections to a
  live, fast node **without restarting**, so the connection does not drop when
  a single node dies.
- **Watchdog ("watch")** — every few seconds it probes the local port through
  the core. If the port is dead or the core process is gone it rebuilds the
  pool in 1–2 seconds; if the probes keep failing it falls back to a full
  selection cycle. It also watches throughput and uses YouTube as a canary.
- **Guard** — a lighter periodic self-check that restores a connection from the
  stored servers (or does a full cycle as a last resort).
- **Update loop** — runs a full selection cycle on a schedule
  (`cycle.full_refresh_hours`).

When the balancer cannot be brought up, the program falls back to a single
server, and then to an **emergency "last good" pool** it saved earlier.

### Seamlessness: when the core is NOT restarted

Restarting the core means a short link gap, so it only happens when it really is
needed:

- **The new config is validated by the core before the running one is stopped** —
  `xray run -test -config <file>`. A broken config is never applied, so it cannot
  take the link down (if a core build does not support `-test`, the program falls
  back automatically to starting it on free ports).
- **Unchanged pool means no restart at all.** The program remembers the hash of
  the config the running core actually uses (`balancer_cfg_sha`) and the pool
  fingerprint (`balancer_sig`); if the freshly built config matches the running
  one, the core is not touched, even on `force=True`.
- **Pool freeze** (`watch.pool_freeze_s`, 3 h by default): while the core is alive
  and the link works, a re-computed top-10 does not reshuffle the config.
- **Restart only for a reason**: the active node is dead / the core is not
  answering, the pool really changed after the freeze expired, or the user
  pressed "Rebuild" in the tray.
- **The gap is measured and logged in milliseconds** — from stopping the old core
  to the new one accepting the client port, plus the time until data transfer is
  confirmed. The fixed 300 ms sleep is gone; the port is polled for release.

Log line template: `перезапуск ядра: РАЗРЫВ связи <ms> мс (порт принял
соединения), подтверждение данных <ms> мс, rtt=<ms> мс`.

The program saves the original system-proxy settings on its first intervention
and can restore them exactly.

## Key settings (from `config.example.json`)

Everything below can be tuned in `config.json`. Defaults are chosen to be safe
for a new user: the provider-specific switches are **off**.

> ### ⚖️ Terms of use
>
> The program provides access to **all** websites, including those blocked by
> network filtering in a given country or network. **You are responsible for
> complying with the laws of your jurisdiction** and with your provider's rules.
> By using the program you confirm that you accept these terms.
>
> Full text: [`docs/TERMS.md`](docs/TERMS.md) (Russian:
> [`docs/TERMS.ru.md`](docs/TERMS.ru.md)).

### General

| Key | Default | Meaning |
|---|---|---|
| `ui.lang` | `""` | Interface/CLI language: `""` = auto (system locale), `"ru"`, `"en"`. |
| `client.mode` | `"standalone"` | `standalone` (own core) or `v2rayn` (through installed v2rayN). |
| `client.socks_port` | `10808` | Local mixed SOCKS/HTTP port of the core. |
| `client.torrent_port` | `10820` | A second local SOCKS port for a torrent client (routed like normal traffic). |
| `client.listen` | `"127.0.0.1"` | Interface the core listens on. Local only by default. |
| `client.manage_system_proxy` | `true` | Whether the program sets/clears the Windows system proxy. |
| `client.core` | `""` | Explicit path to `xray.exe` (standalone). Empty = auto-discovery. |
| `client.dir`, `client.exe`, `client.db_rel`, `client.cfg_rel`, `client.core_rel` | v2rayN defaults | Where v2rayN's executable, database and core are, in `v2rayn` mode. |
| `cycle.full_refresh_hours` | `0.5` | How often a full refresh (fetch sources) runs; between them only the existing servers are re-tested. |
| `limits.max_servers` | `100` | Cap on how many servers are kept/ranked. |

### Testing

| Key | Default | Meaning |
|---|---|---|
| `test.port_start` | `10810` | First port used for throwaway test cores. |
| `test.workers` | `8` | Parallel test threads. |
| `test.rtt_timeout` | `6` | Per-RTT timeout (seconds). |
| `test.rtt_repeats` | `2` | RTT measurements averaged per server. |
| `test.speed_timeout` | `15` | Speed-test timeout (seconds). |
| `test.speed_bytes` | `5242880` | Bytes (5 MB) to download in the speed test. |
| `test.speed_rounds` | `1` | Speed-test rounds. |
| `test.min_speed_kbps` | `1000` | Minimum speed (KB/s) to keep a server. |
| `test.max_rtt_ms` | `1500` | Maximum acceptable RTT. |
| `test.max_jitter_ms` | `800` | Reject servers whose RTT jitter is higher. |
| `test.top_for_speed` | `60` | How many best-by-RTT servers get a speed test. |
| `test.max_candidates` | `400` | Cap on candidates to test per cycle. |
| `test.tcp_prefilter` | `true` | Drop `host:port` with no TCP reachability before testing. |
| `test.min_pool` | `60` | Pool target size. |
| `test.reserve_min` | `30` | Minimum final pool size; below it, servers are added back by RTT. |
| `test.reserve_verify` | `20` | How many reserve servers get a speed verification. |
| `test.final_verify_top` | `60` | How many servers get the final RTT + YouTube re-check. |
| `test.gate_urls` | `[]` | Extra domains that a server must be able to reach. **Empty = off.** See security section. |

### Watchdog and balancer

| Key | Default | Meaning |
|---|---|---|
| `watch.balancer_mode` | `true` | Use Xray's native balancer pool (recommended). |
| `watch.balancer_pool_n` | `10` | How many servers sit inside the running core's pool. |
| `watch.check_interval_s` | `10` | Watchdog probe interval. |
| `watch.probe_timeout_s` | `4` | Watchdog probe timeout. |
| `watch.max_strikes` | `3` | Consecutive failures before the pool is rebuilt. |
| `watch.probe_retries` | `2` | Extra probe attempts before counting a failure. |
| `watch.strict_check_every_s` | `300` | How often a strict ("real data + TLS") probe runs. |
| `watch.pool_refresh_s` | `600` | How often the pool inside the core is refreshed. |
| `watch.pool_freeze_s` | `10800` | Do not rebuild a pool that is working for this long. |
| `watch.speed_check_every_s` | `300` | Throughput check interval. |
| `watch.speed_min_kbps` | `1500` | Below this throughput the pool is rebuilt. |
| `watch.min_speed_kbps` | `200` | Minimum server speed to be allowed into the pool. |
| `watch.youtube_check_every_s` | `300` | YouTube-canary interval; 3 failures in a row trigger a full cycle. |
| `watch.hotcache_n` | `20` | How many verified servers are kept in the fast-failover cache. |
| `watch.hotcache_ttl_s` | `3600` | Lifetime of a hot-cache entry. |

### Sources and selection

| Key | Default | Meaning |
|---|---|---|
| `sources.fixed_urls` | list | Fixed subscription URLs, each with an `every_minutes` refresh interval. |
| `sources.search_queries` | list | GitHub search queries used to discover new sources. |
| `sources.seed_repos` | list | Fallback repositories if discovery finds nothing. |
| `sources.known_files` | list | File names sniffed inside a repository. |
| `sources.stale_days` | `30` | Drop a source that has not changed for this many days. |
| `sources.rediscover_hours` | `12` | How often the GitHub search runs. |
| `diversity.per_subnet_cap` | `1` | Max servers from one /24 subnet. |
| `diversity.min_pool_after_cap` | `12` | If the cap shrinks the pool below this, the cap is relaxed. |
| `diversity.max_cap_relax` | `4` | How far the cap may be relaxed. |
| `activation.prefer_current_if_healthy` | `true` | Keep the current server if it is healthy and competitive. |
| `activation.max_restart_wait_s` | `40` | Max wait for a core restart during activation. |

## Command-line interface

Run the program (`.exe`, or `python src/v2ray_updater.py` from source) with one
of these:

```
--install     lay out under %LOCALAPPDATA%\ForestProxyUpdater (the .exe itself is
              copied there), create the Start Menu shortcut and the autostart
              entry "<install dir>\ForestProxyUpdater.exe" --run, run the first cycle
--uninstall   stop the core, restore the system proxy, remove the autostart entry,
              the shortcut, the installed .exe and the program directory
--run         normal run: the supervisor with its worker threads (until stopped)
--once        one full server-selection cycle            (alias: --auto)
--guard       one quick self-check / recovery pass
--status      show the current state
--selftest    run the built-in test suite
--watch       run only the watchdog (one process)
--dry-run     run a cycle without writing anything or starting the core
--config PATH use a specific config.json
--help        show the built-in help
```

Background work runs without console windows (`CREATE_NO_WINDOW` / `pythonw`
semantics).

## Files and logs

Everything the program writes lives under `%LOCALAPPDATA%\ForestProxyUpdater`
(override with `FOREST_ROOT` or `paths.root` in the config):

| Path | What it is |
|---|---|
| `config.json` | The working configuration (created from `config.example.json` on first run). |
| `logs/main.log` | Main log (UTF-8). |
| `state/servers.json` | Own server store (standalone mode). |
| `state/forest_xray.json` | Config of our own core. |
| `state/forest_xray.log` | Output of our own core. |
| `state/state.json` | Internal state: hot cache, blacklist, balance signature, etc. |
| `state/subscription_base64.txt` | Current pool as a base64 subscription (for manual import into any client). |
| `state/proxy_orig.json` | The system-proxy state saved before the first change. |

Where to find problems is described in [`docs/FAQ.md`](docs/FAQ.md).

## Security and limitations

Read this before running the program. Nothing here is a bug — it is how the
program works, and you should know it.

**The program changes the Windows system proxy.** It writes
`ProxyEnable`/`ProxyServer` under
`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Internet Settings`
and points them at its local port (`127.0.0.1:10808` by default) so that
system-wide traffic goes through the selected server. This is a user-level
setting (no administrator rights required), and it affects every application
that follows the Windows system proxy. It saves the original value on the first
change and restores it on `--uninstall`.

**The program manages a process.** In standalone mode it starts and stops
`xray.exe`. It only ever kills *its own* core (identified by its own config
name); it does not touch other `xray.exe` processes.

**The `.exe` is not code-signed.** Windows SmartScreen and some antivirus
products will warn about an unsigned program that changes proxy settings and
launches another executable — this is expected for a program of this kind. If
you do not trust the build, do not run it: build it yourself from source (see
[`docs/BUILDING.md`](docs/BUILDING.md)) and read the code first. The source is
GPL-3.0 and has no third-party dependencies.

**You are routing your traffic through third-party servers you did not
choose.** The program pulls public server lists from external sources on the
internet. It tests the servers, but **it does not and cannot verify the
operator of a server**. Whoever runs a proxy node can see and modify the
traffic that goes through it. Do not send sensitive traffic through servers you
do not trust. The program does not encrypt anything itself — it relies on the
transport security (TLS/REALITY) configured by whoever published each server.

**Free servers are unstable.** Public free nodes go down, get blocked, throttle,
or disappear constantly. Expect the connection to be uneven, to re-select
often, and sometimes to have no working server at all. This is a property of
the servers, not of the program. For a stable, fast connection, use a paid
provider.

**Extra options exist for particular network conditions, and enabling them is
your responsibility.** `test.gate_urls` (empty by default) is a "gate": extra
domains a server must reach, used to reject servers that cannot reach a specific
site. Turning it on changes how your traffic is routed on *your* network — do it
on your own responsibility.

**Intended use.** The program is meant for lawful use — for example, keeping a
working connection to servers you are entitled to use. You are responsible for
how you use it and for complying with the laws and terms of service that apply
to you. The program is provided under GPL-3.0, **without any warranty**.

## FAQ

Short answers; the full list is in [`docs/FAQ.md`](docs/FAQ.md).

- **"It can't find any servers."** The first run can need a few minutes and a
  working internet connection; free lists are hit-and-miss. Check
  `logs/main.log`. See [`docs/FAQ.md`](docs/FAQ.md).
- **"There's no internet after I started it."** The program points the system
  proxy at its local port; if no server is up, the system proxy has nothing to
  talk to. Run `--uninstall` to put the proxy back, or see the FAQ.
- **"My antivirus complains."** The build is unsigned. See the security
  section and [`docs/FAQ.md`](docs/FAQ.md).
- **"How do I remove it?"** Run `--uninstall`.
- **"Where are the logs?"** `%LOCALAPPDATA%\ForestProxyUpdater\logs\main.log`.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how it is built inside.
- [`docs/BUILDING.md`](docs/BUILDING.md) — building the `.exe` and releasing.
- [`docs/FAQ.md`](docs/FAQ.md) — common problems and answers.
- [`docs/LINUX-INSTALL.md`](docs/LINUX-INSTALL.md) — installing on Linux:
  `.deb` / `.rpm` / Arch / AppImage / `.tar.gz`, configuration, removal
  (Russian version: [`docs/LINUX-INSTALL.ru.md`](docs/LINUX-INSTALL.ru.md)).
- [`docs/TERMS.md`](docs/TERMS.md) — terms of use and disclaimer (Russian:
  [`docs/TERMS.ru.md`](docs/TERMS.ru.md)).
- [`packaging-linux/README.md`](packaging-linux/README.md) — building the Linux
  packages from source.

## License

GPL-3.0-only. See [`LICENSE`](LICENSE).

Copyright (C) 2026 FOREST.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. This program is distributed in the hope that it will be useful, but
**WITHOUT ANY WARRANTY**; without even the implied warranty of MERCHANTABILITY
or FITNESS FOR A PARTICULAR PURPOSE.
