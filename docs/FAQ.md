# FAQ and troubleshooting

Common questions and problems. For the honest description of what the program
does to your system, read the security section in [`../README.md`](../README.md)
first.

## Where are the logs?

- Main log: `%LOCALAPPDATA%\ForestProxyUpdater\logs\main.log`
  (paste `%LOCALAPPDATA%\ForestProxyUpdater` into the Explorer address bar).
- Core output: `%LOCALAPPDATA%\ForestProxyUpdater\state\forest_xray.log`.
- Config-validation output: `...\state\forest_validate.log`.

If you moved the state directory (`FOREST_ROOT` or `paths.root`), the logs follow
it. If the main log directory is not writable, the program falls back to a
`logs` folder next to the code and then to `%LOCALAPPDATA%\ForestProxyUpdater\logs`.

## "It can't find any servers" / the pool stays empty

The usual causes, in order:

1. **The first cycle can take a few minutes and needs a working internet
   connection.** The program must download public lists before it can test
   anything. Give it time and watch the log.
2. **Free lists are hit-and-miss.** Public servers go down constantly, and at
   some hours there may be none usable. Try again later.
3. **Your own connection is blocked or offline.** If the machine cannot reach
   GitHub / the subscription URLs at all, there is nothing to test. Check that
   you are online and that a normal browser can open
   `https://raw.githubusercontent.com`.
4. **`curl.exe` is missing.** The program uses `curl.exe`, which ships with
   Windows 10 1803+. On older systems, install it. Without it, fetching and
   probing do not work.
5. **Thresholds are too strict** for your network. In `config.json` you can
   lower `test.min_speed_kbps` (default 1000), raise `test.max_rtt_ms`
   (default 1500) or raise `test.max_jitter_ms` (default 800), then run `--once`
   again.

Look for the summary lines in `main.log` (`RTT пройдено`, `Рабочих`) to see how
far the pipeline got.

## Why were my servers rejected? (reading the pool log)

If the pool stays empty or tiny, the cycle itself says *why* each candidate
dropped out. In `main.log` look for these lines:

- `причины отсева: {...}` — a breakdown of why the candidates in the speed stage
  failed. The usual values:
  - `core_start_failed` — the throwaway Xray instance for that node did not
    start, i.e. the node's config/transport is broken. A lot of these means the
    list is dead or misparsed, not that your settings are wrong.
  - `gate_unreachable` — the node could not reach a domain from
    `test.gate_urls`. **This only appears if you set `test.gate_urls`**; by
    default the list is empty and there is no gate check at all.
  - `gate_403` — the gate was reachable but answered HTTP 403 (typical of some
    exits); same note — only with `test.gate_urls` set.
  - `http_<code>` — the node answered something other than `204` to the RTT
    probe.
- `живы, но ниже порога N КБ/с: ... (лучшие: ...)` — nodes that answered fine but
  are slower than `test.min_speed_kbps`. If most of your candidates land here,
  the threshold is too high for your network: lower `test.min_speed_kbps` (or
  raise `test.max_rtt_ms` / `test.max_jitter_ms`, see the first section).
- `Разнообразие пула: X из Y (подсетей Z, кап C)` — the subnet-diversity cap was
  applied.

**Pool stuck on one subnet.** By default `diversity.per_subnet_cap` is `1`, i.e.
at most one server per /24, so the pool is spread across subnets. If your
candidates all come from one hosting network, the cap can gut the pool — then
the safety net `diversity.min_pool_after_cap` (default `12`) kicks in and relaxes
the cap up to `diversity.max_cap_relax` (default `4`), logged as
`Страховка пула: кап по подсетям ослаблен 1 -> N`. If the pool is still
clustered, raise `diversity.per_subnet_cap` or lower
`diversity.min_pool_after_cap`.

## "Nodes behind Cloudflare give me almost no speed"

Many free lists are full of nodes whose address resolves into Cloudflare's
ranges (the "CDN fronting" trick). Those nodes often pass the RTT probe but carry
almost no throughput, so the speed stage measures near zero and drops them at
`test.min_speed_kbps` — and the pool stays thin.

The program filters them out on purpose: step 5 of the cycle calls
`netfilters.drop_cloudflare`, controlled by `blacklist.cloudflare_nodes`, which
is **on (`true`) by default**. If you set `blacklist.cloudflare_nodes` to
`false` in `config.json` (or toggle the tray menu item «Cloudflare — обход»),
those nodes re-enter the candidate pool — usually not worth it, since they are
the classic source of "connected but zero speed". Leave it on unless you know
your network needs it.

## "There's no internet after I started it"

The program points the Windows system proxy at its local port
(`127.0.0.1:10808`). If no server is up (empty pool, no working core), the proxy
has nothing to forward to and applications that use the system proxy will show
"no internet".

What to do:

- **Fastest fix:** run the program with `--uninstall`. This restores the system
  proxy to the state it had before the first run and removes the program, so your
  internet comes back immediately.
- Or turn the proxy off by hand (Windows *Settings → Network & Internet →
  Proxy*, disable "Use a proxy server"), or let the program know: create the file
  `state\proxy_off.flag` in `%LOCALAPPDATA%\ForestProxyUpdater`. With that flag
  present the program will not raise the proxy again on its own.
- Check `state\forest_xray.log` and `logs\main.log`: usually the core could not
  start (bad config, missing core, or a misbehaving server).

Note that some applications ignore the Windows system proxy entirely; those will
not be affected either way.

## The antivirus / SmartScreen complains

The `.exe` is **not code-signed**, and its behaviour — editing the system proxy
registry keys and launching another executable — matches what packers and some
unwanted software do, so heuristic scanners will flag it. This is expected for a
program of this kind.

- To run it anyway: on the SmartScreen prompt choose *More info → Run anyway*;
  add an exclusion in your antivirus if you are sure you trust the build.
- If you do not trust the build, **do not run it**: build it yourself from source
  ([`BUILDING.md`](BUILDING.md)) and read the code first.

The program never asks for administrator rights and only touches
`HKEY_CURRENT_USER`.

## "Xray core not found" / the core will not start

In standalone mode the program needs `xray.exe`. It looks in this order: the
explicit `client.core` path, `bin\xray\xray.exe` next to the program, then
`xray.exe` in `PATH`.

- Download the official core from
> Since 1.0.1 **you do not need to download the core**: the `.exe` already
> contains Xray and both geo databases. Put your own `bin\xray\` beside the
> `.exe` only if you want to override or update the core — that copy wins.
  most common cause is an invalid server config, but the program validates the
  config before switching, so this is rare.

## "Port 10808 is already in use" / another xray is running

The program uses `client.socks_port` (10808) and, for tests,
`test.port_start`…+N (10810 and up). If another proxy client already listens on
10808, either close it or change `client.socks_port` in `config.json`.

In standalone mode the program never kills a process that is not its own: if
the port is held by a foreign process it only logs a warning. If you run it
alongside v2rayN, prefer the `v2rayn` mode instead of `standalone`.

## It re-selects servers too often / too rarely

Tune in `config.json`:

- Rebuild more eagerly: lower `watch.max_strikes`, lower `watch.min_speed_kbps`
  or `watch.speed_min_kbps`.
- Rebuild less often (a working pool is kept for `watch.pool_freeze_s`, default
  3 hours): raise `watch.pool_freeze_s`, raise `cycle.full_refresh_hours`.
- Change how often the whole list is re-fetched: `cycle.full_refresh_hours`
  (default 0.5 h). Between full refreshes only the existing servers are re-tested.

## How are YouTube and speed checked?

The program uses YouTube (`https://www.youtube.com/`) as a canary: 3 failures in
a row trigger a full cycle. Speed is measured against
`speed.cloudflare.com`. Both endpoints are fixed in the code
(`clientwrite.py` / `watch.py`); the speed-test download size is
`test.speed_bytes`.

## How do I get the current pool as a subscription?

`%LOCALAPPDATA%\ForestProxyUpdater\state\subscription_base64.txt` is a base64
subscription of the current pool — import it into any compatible client
(v2rayN, v2rayNG, etc.).

## How do I remove everything?

Run the `.exe` with `--uninstall`. This stops the core, restores the system proxy
to the state before the first run, removes the autostart entry and the shortcut,
and deletes `%LOCALAPPDATA%\ForestProxyUpdater`.

If something was left behind (for example the core was busy and the directory
could not be deleted), close the program, stop any leftover `xray.exe` that has
`forest_xray.json` in its command line, and delete
`%LOCALAPPDATA%\ForestProxyUpdater` manually. Then check in Windows *Settings →
Network & Internet → Proxy* that nothing is left pointing at `127.0.0.1:10808`.

## Can I run it once and exit, without autostart?

Yes: run `--once` for a single selection cycle, or `--guard` for a single
recovery pass. `--install` is what adds the autostart entry; if you only run
`--once`, nothing is installed and no autostart is created. `--dry-run` performs
a full cycle without writing anything or starting the core.

## Can I use it with my own servers / v2rayN?

- **Your own servers:** in standalone mode you can edit
  `state\servers.json` (or import your links into a client and copy the pool).
  Servers you add yourself are preserved; the program only manages its own
  `[AUTO]`-tagged entries.
- **v2rayN:** set `client.mode` to `"v2rayn"` in `config.json`. The program then
  works through your installed v2rayN's database and core (and backs up the
  database before writing).

## Is it using the provider-specific options by default?

No. `test.gate_urls` is empty and `watch.ru_direct` is `false` in the shipped
config. They exist for particular network conditions and are your
responsibility to enable — see the security section in
[`../README.md`](../README.md).

## Still stuck

1. Read the tail of `%LOCALAPPDATA%\ForestProxyUpdater\logs\main.log`.
2. Run `--status` to see mode, core path, pool size and proxy state.
3. Run `--selftest` to confirm the program itself is healthy (it changes
   nothing).
4. Open an issue with the log excerpt and your `config.json` (remove anything
   you consider private first).

---

Русская версия: [`FAQ.ru.md`](FAQ.ru.md).
