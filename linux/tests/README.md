# linux/tests — package matrix bench

`wsl-matrix.sh` installs a real package inside a WSL distribution, proves that the
proxy it ships actually carries traffic, checks its systemd unit, then uninstalls
it and verifies nothing is left behind. It prints one PASS/FAIL table per run.

It exists so that every release artifact (`.deb`, `.rpm`, `.pkg.tar.zst`,
`.tar.gz`, `.AppImage`) can be smoke-tested against several distributions
**without touching the user's live proxy on the host** (ports 10808/10809/10820
are refused outright).

```
linux/tests/
├── wsl-matrix.sh          orchestrator — runs on Windows (git-bash), drives wsl.exe
├── wsl-matrix-inner.sh    probe — runs INSIDE the distro, installs/verifies/uninstalls
├── testpkg/
│   ├── testproxy.py           toy HTTP proxy (CONNECT + absolute-URI), not a product component
│   ├── fp-matrix-test.service systemd unit for the toy proxy
│   └── build-testpkg.sh       builds the toy package as .deb / .rpm / .pkg.tar.zst
└── README.md
```

## Usage

```bash
# test a real package you just built
./wsl-matrix.sh --distro Debian --package ../../packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb
./wsl-matrix.sh --distro openSUSE-Tumbleweed --package ../../packaging-linux/out/forest-proxy-updater-1.1.0-1.x86_64.rpm
./wsl-matrix.sh --distro archlinux --package ../../packaging-linux/out/forest-proxy-updater-1.1.0-1-x86_64.pkg.tar.zst
./wsl-matrix.sh --distro Ubuntu  --package ../../packaging-linux/out/forest-proxy-updater-1.1.0-linux-x86_64.tar.gz
# AppImage installs per-user: --as-user runs the whole flow as that account
./wsl-matrix.sh --distro Ubuntu  --package ../../packaging-linux/out/ForestProxyUpdater-1.1.0-x86_64.AppImage --as-user tester

# prove the bench itself is alive (builds a throwaway package inside the distro)
./wsl-matrix.sh --distro Debian --selftest

# a second port, an explicit unit, or a fallback start command
./wsl-matrix.sh --distro archlinux --package x.pkg.tar.zst --port 11899
./wsl-matrix.sh --distro RLCPlus-10 --package x.rpm --unit forest-proxy-updater.service
./wsl-matrix.sh --distro Debian --package x.tar.gz --installer 'sh /tmp/x/install.sh'

./wsl-matrix.sh --list          # distros + discoverable payloads
```

Options: `--distro`, `--package`, `--port` (default **11808**), `--unit`,
`--service-cmd`, `--traffic-wait` (default **900 s**), `--as-user`,
`--installer`, `--uninstaller`, `--isolate`, `--selftest`, `--list`, `-h`.

Exit codes: `0` all PASS · `1` usage · `2` no such distro · `3` payload not found ·
`4` a step failed · `5` environment error.

## Steps checked

`env` · `systemd` · (`user-mode`) · `pkg-type` · `pkg-copy` · `install` ·
`unit-present` · `service-active` · `proxy-traffic` · `uninstall` ·
`residue-pkg` · `residue-files` · `residue-units` · `residue-port`

`proxy-traffic` is the real proof: it runs

```bash
curl -s -m 20 -x http://127.0.0.1:$PORT -o /dev/null -w '%{http_code}' \
     https://www.gstatic.com/generate_204
```

and requires `204` — i.e. the packaged proxy carries a genuine HTTPS tunnel out to
gstatic, not just "the daemon started".

## Why the traffic step waits for minutes

A cold ForestProxyUpdater start is not "start a daemon": the supervisor downloads
public server lists, runs a TCP prefilter, RTT and throughput tests, selects a
pool and only then starts the Xray core. On a fresh machine that is minutes, so
`--traffic-wait` defaults to 900 s and polls every 3 s (printing progress). The
throwaway toy proxy returns `204` in under a second, which is why the `--selftest`
run looks instant.

## How the bench tells the product which port to run on

The product listens on `client.socks_port` (default **10808**), and 10808 belongs
to the user's live proxy on the host — the bench may not touch it. The product
reads its configuration from the `FOREST_CONFIG` environment variable, so the
bench:

1. finds the config the payload shipped (`/etc/<name>/config.json` for packages
   and the tarball, `~/.config/<name>/config.json` in user mode);
2. copies it to `/run/fp-matrix-$PORT/config.json` and rewrites `client.socks_port`
   to the bench port, `client.listen` to `127.0.0.1`, `client.manage_system_proxy`
   to `false` and `test.port_start` to `$PORT + 100` (so temporary test cores do
   not land on the host's ports either);
3. writes a systemd drop-in that sets `Environment=FOREST_CONFIG=<that copy>`
   *after* the unit's own `Environment=` lines (later assignments win), plus
   `FP_TEST_PORT`/`FP_PROXY_PORT` for products that read env vars;
4. starts the unit, then removes the drop-in and the test config at the end of
   the run.

The shipped product configuration is therefore never modified, and neither is the
payload.

## Running the whole matrix at once

`run-matrix.sh` runs every artifact against the distributions that can install it
(one distribution at a time) and writes a `summary.csv` plus a table:

```bash
bash linux/tests/run-matrix.sh              # everything
bash linux/tests/run-matrix.sh deb rpm      # only those families
FOREST_MATRIX_WAIT=600 bash linux/tests/run-matrix.sh
```

Per-run logs land in `linux/tests/matrix-<timestamp>/`, with `summary.csv`
(family, distro, package, steps, pass/fail/skip, verdict). The exit code is 0
only if every run passed.

## Verified matrix

All five artifacts, install → active service → real traffic (204) → clean removal,
plus the throwaway-package self-test: see
[`docs/LINUX-PACKAGES-PROOF.ru.md`](../../docs/LINUX-PACKAGES-PROOF.ru.md) for the
exact runs, verbatim output and the per-distribution table.

## WSL pitfalls this bench already encodes

* **`wsl.exe` output encoding is mixed.** Its own messages (stderr, and `-l`
  listings) are UTF-16LE; a child process's stdout is UTF-8. The orchestrator
  decodes accordingly (`iconv`, falling back to `python3`, falling back to
  stripping NULs — `iconv` is *not* present in git-bash by default).
* **Passing shell commands through `wsl.exe` breaks on quoting.** The bench pipes
  the inner script over stdin and uses `wsl.exe -e env … bash -s` so no argument
  ever has to survive a second shell.
* **Relative paths cannot be mapped into WSL.** `to_wsl_path` makes the path
  absolute first (`cygpath` when available, otherwise `/d/x` → `d:/x`), so a
  relative `--package` works too.
* **A localhost proxy on the host produces a warning on every call**
  (`WSL в режиме NAT не поддерживает прокси-серверы localhost`). Harmless — but it
  means *repo* traffic from inside WSL is direct; see the dnf note below.
* **`user@*.service` can fail with `Failed to spawn executor: Device or resource
  busy`** (WSL issues #13826 / #40593): several distros running at once collide in
  the shared root cgroup / UID-1000 session. The bench terminates the target
  distro before each run, and `--isolate` terminates all others.
* **`tar`/`gzip`/`curl`/`python3` are missing from several base images**
  (Debian ships no curl/python3; openSUSE ships no curl/tar/gzip). Install them
  before a run, or the traffic step cannot happen.
* **`pacman 7` removed `-Qp --format` and needs `-p/--file` for listings**;
  package names are parsed from `pacman -Qip`.
* **Vendor repos can be unreachable in NAT mode** (Rocky/CIQ `ciq.com` times out).
  The dnf/yum path retries with `--disablerepo='*'` so a local file whose
  dependencies are already present still installs.
* **Service shutdown is asynchronous**; the `residue-port` step waits up to 15 s
  before declaring a leftover (a 1 s wait produced a false FAIL on Rocky).
* **`systemctl enable --now` does not restart an already-active unit.** The
  package's own `postinst` starts the service before the bench gets to steer the
  port, so the bench now stops the unit, applies the drop-in and *starts* it —
  otherwise the running process keeps the shipped configuration (the first run of
  this bench tested port 10808 without noticing, which is exactly the sort of
  silent no-op a bench must not have).
* **A killed cycle leaves the product's lock.** Killing the service mid-cycle
  leaves `state/lock.json`, and the next instance then refuses to run a cycle for
  hours ("другой цикл уже выполняется") — no pool, no traffic, a puzzling FAIL.
  The bench therefore wipes the fresh-install state (`state/<app>`) before
  starting the service, which also matches what it is testing: a clean install.
* **User-mode installs survive between runs, and that breaks the next one.** A
  per-user install lives in `$HOME`, so a repeat run finds the old service still
  running and the installer dies with `Text file busy` when it copies the binary
  over the running one; a stale unit from some earlier experiment also hijacks
  unit/app-name detection. In user mode the bench therefore stops and removes any
  previous self-installed unit (its `ExecStart` points into `~/.local/`) and the
  product's own config/state before installing, and it identifies the freshly
  installed unit by timestamp — never `-refresh`, preferring the one whose
  `ExecStart` contains `--run`.
* **Windows drives do not keep file modes.** Do not build packages under `/mnt/*`
  from WSL: the package would contain world-writable files. `packaging-linux`
  detects this and moves the build to a local `$TMPDIR`.
* **Keep every distro's VHDX off C: if C: is tight** — `wsl --install -d <d>
  --location D:\wsl\<d>` avoids the system drive entirely.

## Using it on a plain Linux host (CI)

Without `wsl.exe` the same script runs the probe directly on the current host
(`sudo bash` when not root). That makes it usable as a release gate in CI:

```bash
./wsl-matrix.sh --package dist/pkg.deb --traffic-wait 900
```
