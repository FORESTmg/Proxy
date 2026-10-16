# Building and releasing

This document explains how to build the single-file `.exe` yourself and how to
publish a release on GitHub. It is written for a maintainer, not an end user.

The build produces an unsigned `.exe`. Signing is not part of this project, so
Windows SmartScreen and some antivirus products will warn about the result —
that is expected (see the security section in [`../README.md`](../README.md)).

Everything needed to build lives in `packaging/`.

## What you need

- **Windows x64** (the program is Windows-only; a POSIX port exists in the
  source but is not built here).
- **A 64-bit Python 3** (`build.ps1` looks for one in this order: the `-Python`
  argument, the `FOREST_PYTHON` environment variable, `py -3.12`, `py -3.13`,
  `py -3.11`, `py -3`, `python`, `python3`). Python 3.10 or newer is fine; the
  reference build used 3.12.
- **Internet, once** — to download PyInstaller and the official Xray-core
  release.

You do **not** install PyInstaller yourself: the build script puts it into an
isolated environment and pins it (`requirements-build.txt`, currently
`pyinstaller==6.22.3`). The program itself has **no third-party Python
dependencies** at runtime (standard library only).

## Build

The whole build is one script, `packaging/build.ps1`, with a `.bat` wrapper.
The simplest form:

```bat
packaging\build.bat
```

Or drive the script directly:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Clean      :: rebuild from scratch
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -NoVenv    :: no venv, into the system Python
$env:FOREST_PYTHON='C:\Path\to\python.exe'; powershell -File packaging\build.ps1
```

The script is **idempotent** — running it again changes nothing and needs no
manual steps. In order it:

1. finds a 64-bit Python 3;
2. creates the isolated build environment `packaging\.build-venv` and installs
   PyInstaller into it (pin from `requirements-build.txt`) if it is not already
   there;
3. if the core is missing, downloads the official XTLS/Xray-core release
   (`fetch_core.py`); if the icon is missing, draws `app.ico` (`make_icon.py`);
4. runs PyInstaller with the spec `ForestProxyUpdater.spec`;
5. puts the result in `packaging\dist\` and prints its size and SHA-256, also
   writing them to `dist\build-report.json` and
   `dist\ForestProxyUpdater.exe.sha256`.

The finished artifact is **`packaging\dist\ForestProxyUpdater.exe`**.

The reference build in this repository:

| Field | Value |
|---|---|
| Size | 30 709 514 bytes (29.29 MiB) |
| SHA-256 | `06dbfc2a46820b1106177a5f269840d33108a99085aa478f197e3742b21bb27d` |
| Built (UTC) | 2026-10-16T18:34:54Z |
| PyInstaller | 6.22.3 |
| Base Python | Python 3.12 (64-bit) |
| Xray-core | v26.3.27 |
| Layout | onefile, `console=False` |

## What is inside the one `.exe`

The spec `ForestProxyUpdater.spec` builds onefile + `console=False` (no console
window); the icon and the Windows version resource are attached to the EXE.

| Inside | Lands at | Who finds it |
|---|---|---|
| code `src/*.py` | PYZ archive | "flat" imports `import config`, `import clientwrite`, … |
| the Xray core | `bin\xray\xray.exe` | `config.find_core()` |
| geo databases | `bin\xray\geoip.dat`, `bin\xray\geosite.dat` | `clientwrite.geo_asset_dir()` (the directory next to the core) |
| core license (MPL-2.0) | `bin\xray\LICENSE` | — |
| `config.example.json` | package root | `config.example_config_path()` (first run without a config) |

The paths are chosen to match the existing code: when a onefile build unpacks,
`__file__` points inside `sys._MEIPASS`, so `config.BASE_DIR` equals the unpack
directory and `bin\xray\` sits exactly where it is looked for.

## Reproducibility: the `.exe` is not bit-identical between builds

PyInstaller stamps a timestamp into the PE, so `build.ps1` pins
`SOURCE_DATE_EPOCH` (to `1735689600`, i.e. 2025-01-01T00:00:00Z) to keep the PE
stamp from drifting between builds. **This does not make the `.exe`
bit-identical**: the order in which PyInstaller walks directories while packing
the archive is not deterministic, so the SHA-256 **can change between builds**
(verified on this project). What is stable is that the *process* is repeatable
and needs no manual steps, and that the archive contents are the same.

So: the **process** is idempotent, the **bytes** are not. To prove the embedded
core and geo databases match the official release byte for byte, run
`verify_bundle.py` (see below) — it compares them against the pin in
`core.lock.json`.

## Verify what you built

```bat
cd packaging\dist
copy ..\..\config.example.json .
ForestProxyUpdater.exe --selftest --config config.example.json
ForestProxyUpdater.exe --status   --config config.example.json
```

Expected: `--selftest` prints `ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ` and returns exit code 0
(the same 90 checks as running from source), and `--status` shows the mode, the
path to the **embedded** core (inside
`%TEMP%\_MEI...\bin\xray\xray.exe`), the pool size and the system-proxy state.

To confirm the core and geo databases inside the `.exe` are byte-for-byte the
official release:

```powershell
packaging\.build-venv\Scripts\python.exe packaging\verify_bundle.py
```

## Updating the Xray core

```bat
packaging\.build-venv\Scripts\python.exe packaging\fetch_core.py --force
```

Downloads are allowed **only** from
`github.com/XTLS/Xray-core/releases/download/...` (host and path checked in
`fetch_core.py`). The archive is verified by SHA-256 against the pin in
`core.lock.json`. To move to a new version: edit `core_version.txt`, download,
then `fetch_core.py --print-lock > core.lock.json`, and rebuild.

`vendor\` is not stored in git (~63 MiB of binaries) — it is reproduced
deterministically from the pin.

## Building without PyInstaller (running from source)

For development you do not need to build anything — run the modules directly:

```
python src\v2ray_updater.py --status
python src\v2ray_updater.py --once --dry-run
python src\v2ray_updater.py --selftest
```

`--install` from a source checkout copies the `.py` files into
`%LOCALAPPDATA%\ForestProxyUpdater\src`, creates the Start Menu shortcut and the
autostart entry, and runs a first cycle.

## Publishing a release on GitHub

1. **Update the changelog.** Add the release's entries to `CHANGELOG.md` (a new
   `## [x.y.z] — YYYY` section) and commit it.
2. **Bump the version** in the changelog and anywhere the project records it.
3. **Tag the release** (annotated, matching the version):
   ```
   git tag -a v1.0.0 -m "FOREST's Proxy Auto-updater 1.0.0"
   git push origin v1.0.0
   ```
4. **Create the GitHub Release** for the tag:
   ```
   gh release create v1.0.0 "packaging\dist\ForestProxyUpdater.exe" ^
      --title "FOREST's Proxy Auto-updater 1.0.0" ^
      --notes-file RELEASE_NOTES.md
   ```
   (or use the web UI: *Releases → Draft a new release*, choose the tag, attach
   the built `.exe` as a binary asset).
5. **Attach the `.exe` as a release asset** — do not just link to a build
   artifact that expires. The core is already inside the single `.exe`, so there
   is nothing to ship separately; if you also publish the checksum, attach
   `dist\ForestProxyUpdater.exe.sha256`.

### What to write in the release description

Keep it factual and short. A good release note covers:

- **What it is**, in one or two sentences (automatic proxy selection for
  Windows; standalone by default).
- **Requirements**: Windows 10/11. The Xray core is already bundled inside the
  single `.exe` — nothing has to be added by hand.
- **Install**: download, run, and that Windows will show an unsigned-program
  warning.
- **Uninstall**: run with `--uninstall`; it restores the system proxy.
- **A plain warning**: the program changes the Windows system proxy and starts
  an `xray.exe` process on purpose; free servers are unstable; use it lawfully.
- **Changes in this release**: the relevant items from `CHANGELOG.md`
  (features, fixes, known limitations).
- **Verification**, if you publish checksums: a short SHA-256 list of the
  attached files.

Do not promise reliability, speed or anonymity that the program cannot deliver —
the honest framing in [`../README.md`](../README.md) is the standard to match.

## Notes and caveats

- **`build.ps1` is saved as UTF-8 with a BOM.** Otherwise Windows PowerShell
  5.1 reads Cyrillic as ANSI, mistakes its bytes for "smart quotes" and breaks
  line parsing. Keep the BOM when editing the file.
- The main path (`build.ps1`/`build.bat` via `packaging\.build-venv`, including
  installing PyInstaller from scratch) is tested. The `-NoVenv` flag
  (PyInstaller into the system Python) has not been exercised in this iteration.
- `--status` on its first run creates the program directory
  `%LOCALAPPDATA%\ForestProxyUpdater\{state,logs}` — that is its normal
  behaviour; the command only reads the system proxy.

## Checklist

- [ ] `python -m py_compile src\*.py` passes
- [ ] `python src\v2ray_updater.py --selftest` passes
- [ ] `packaging\build.bat` completed and printed the size and SHA-256
- [ ] `CHANGELOG.md` updated and version bumped
- [ ] `.exe` built at `packaging\dist\ForestProxyUpdater.exe`
- [ ] core + geo databases bundled (already inside the onefile `.exe`)
- [ ] `verify_bundle.py` reports the embedded core matches the pin
- [ ] smoke-tested, including `--uninstall`
- [ ] tag pushed, GitHub Release created, `.exe` attached
- [ ] release notes include requirements, install/uninstall and the security
      warning

---

Русская версия: [`BUILDING.ru.md`](BUILDING.ru.md).
