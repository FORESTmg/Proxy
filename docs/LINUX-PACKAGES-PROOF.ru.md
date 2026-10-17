# Linux-пакеты: что собрано и что проверено

Отчёт о фактически выполненной работе. Все команды и выводы ниже получены
запуском; ничего не додумано. Живой Windows-прокси пользователя (порты
10808/10809/10820, реестр, системный прокси, каталог
`%LOCALAPPDATA%\ForestProxyUpdater`) не затрагивался: тесты идут на своём порту
11808 и в своих каталогах внутри WSL.

## 1. Что собрано

Все пять форматов собираются из **одной раскладки** — `stage_payload` в
`packaging-linux/lib/common.sh`, поэтому содержимое пакетов не может разъехаться.
Все они собраны из одной и той же финальной сборки Linux-приложения.

| Файл | Размер, Б | sha256 |
| --- | --- | --- |
| `forest-proxy-updater_1.1.0_amd64.deb` | 33 457 724 | `bbef11be0d871a95dec7d9b2b157a33717f0cd9515073ccd1d985e95350ef653` |
| `forest-proxy-updater-1.1.0-1.x86_64.rpm` | 33 510 589 | `762e5702446c10c309365ca80623cb92f913355098e5fe72e32ec37d84b9a5b1` |
| `forest-proxy-updater-1.1.0-1-x86_64.pkg.tar.zst` | 33 790 517 | `32406caac7d7d1cebff65f41a51bff5d97ad423de0674bd70a27e655276c9b53` |
| `forest-proxy-updater-1.1.0-linux-x86_64.tar.gz` | 33 569 800 | `1e650196cbe62040330090ac1d9f62900992f02320d1fd25526639c906db2e0e` |
| `ForestProxyUpdater-1.1.0-x86_64.AppImage` | 34 544 120 | `a21057d590856579100f179ceb58d6c42414a1e9399bfb2ef001467e407ff863` |

Рядом с каждым файлом лежит `.sha256`. Файлы — в `packaging-linux/out/`
(каталог в `.gitignore`: артефакты пересобираются одной командой).

Внутри всех пяти форматов — один и тот же ELF
(`linux/dist/forest-proxy-updater`, 34 124 352 Б, sha256
`fe899ca7bfbe4b22c0f22bd4e2a6299cc1f07b953b889e22865e898c88a9ef91`), и рядом с
ним одинаковый набор файлов:

* `/usr/lib/forest-proxy-updater/forest-proxy-updater` — самодостаточный ELF
  (Python, ядро Xray и обе гео-базы внутри);
* `/usr/bin/forest-proxy-updater` — симлинк;
* `/usr/lib/systemd/system/forest-proxy-updater{,-refresh}.service` и `.timer`;
* `/etc/forest-proxy-updater/config.json` (в `.deb` — `conffile`, в `.rpm` —
  `%config(noreplace)`);
* `/usr/share/doc/forest-proxy-updater/{README.md,INSTALL.md,INSTALL.ru.md,TERMS.md,TERMS.ru.md,PACKAGE-README.md,copyright,COPYING}`
  и `/usr/share/licenses/forest-proxy-updater/COPYING` (GPL-3.0);
* у `.tar.gz` вместо `/usr/...` — своё дерево
  `forest-proxy-updater-1.1.0-linux-x86_64/` с `install.sh`, `uninstall.sh`,
  `systemd/` и `doc/`.

Проверка, что в пакет попал именно финальный ELF:

```sh
wsl.exe -d Ubuntu -u root -e bash -c \
  'cd /tmp/vfy && dpkg-deb -x <repo>/packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb . && \
   sha256sum usr/lib/forest-proxy-updater/forest-proxy-updater'
fe899ca7bfbe4b22c0f22bd4e2a6299cc1f07b953b889e22865e898c88a9ef91  usr/lib/forest-proxy-updater/forest-proxy-updater
```

## 2. Точные команды сборки

Сборщики запускались прямо в нужных дистрибутивах WSL (репозиторий виден как
`<repo>`). Каждая команда идемпотентна.

```sh
# .deb (Debian/Ubuntu — есть dpkg-deb)
wsl.exe -d Ubuntu -u root -e env FOREST_WORK_DIR=/tmp/fp-w \
    bash <repo>/packaging-linux/build-deb.sh

# .rpm (openSUSE — есть rpmbuild); Rocky/CIQ-образ rpmbuild не ставит
wsl.exe -d openSUSE-Tumbleweed -u root -e env FOREST_WORK_DIR=/tmp/fp-w \
    bash <repo>/packaging-linux/build-rpm.sh

# Arch: makepkg (не от root — скрипт сам понижает права до пользователя tester)
wsl.exe -d archlinux -u tester -e env FOREST_WORK_DIR=/tmp/fp-arch-work \
    bash <repo>/packaging-linux/build-arch.sh

# AppImage (Ubuntu: есть mksquashfs; appimagetool скачивается сам)
wsl.exe -d Ubuntu -u root -e env FOREST_WORK_DIR=/tmp/fp-appimage-work \
    bash <repo>/packaging-linux/build-appimage.sh

# портативный .tar.gz
wsl.exe -d Ubuntu -u root -e env FOREST_WORK_DIR=/tmp/fp-tar-work \
    bash <repo>/packaging-linux/build-tar.sh
```

Один прогон всех форматов, возможных на машине (со сводкой и хешами):
`sh packaging-linux/build-all.sh`.

Сам ELF пересобирался так (в WSL Ubuntu, окружение сборки уже стояло):

```sh
wsl.exe -d Ubuntu -u tester -e bash -lc \
  'PYI_PYTHON=/home/tester/fpu-build/venv/bin/python \
   sh <repo>/packaging/build-linux.sh'
# PyInstaller 6.22.3 | Python 3.12.15, ядро Xray v26.3.27 внутри
```

## 3. Чем проверялось

Стенд `linux/tests/wsl-matrix.sh` (расширен под этот продукт, см. §6): ставит
пакет **одной командой**, дожидается **реального трафика** через прокси и
проверяет чистое удаление.

```sh
bash linux/tests/wsl-matrix.sh --distro Debian \
     --package packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb \
     --port 11808 --traffic-wait 900 --isolate
```

Проверяемые шаги: `env` · `systemd` · `pkg-type` · `pkg-copy` · `install` ·
`unit-present` · `service-active` · `proxy-traffic` · `uninstall` ·
`residue-pkg` · `residue-files` · `residue-units` · `residue-port`
(в пользовательском режиме добавляется шаг `user-mode`).

Доказательство трафика — ровно та команда, которая нужна:

```sh
curl -s -m 20 -x http://127.0.0.1:11808 -o /dev/null -w '%{http_code}' \
     https://www.gstatic.com/generate_204          # требуется 204
```

Стенд следит за тем, чтобы живой прокси на хосте не был затронут: порты
10808/10809/10820/10821 отклоняются, а продукт переводится на тестовый порт
через `FOREST_CONFIG` (drop-in юнита), при этом **штатный конфиг пакета не
меняется** — правится только его копия в `/run/fp-matrix-11808/config.json`.
Тестовый конфиг облегчён, чтобы первый цикл уложился в минуты
(`max_candidates: 150`, `top_for_speed: 20`, `speed_bytes: 1 МиБ`).

## 4. Матрица: пакет × дистрибутив

Каждый прогон — установка одной командой, затем 13–14 шагов проверки.
Ни одного FAIL, ни одного SKIP.

| Пакет | Ubuntu 26.04 | Debian 13 | openSUSE Tumbleweed | Rocky Linux 10.2 | Arch Linux |
| --- | --- | --- | --- | --- | --- |
| `.deb` | ✅ 13/13 (204 через ~174 с) | ✅ 13/13 (204 через ~174 с) | — | — | — |
| `.rpm` | — | — | ✅ 13/13 (204 через ~180 с) | ✅ 13/13 (204 через ~177 с) | — |
| `.pkg.tar.zst` | — | — | — | — | ✅ 13/13 (204 через ~165 с) |
| `.tar.gz` (системная установка) | ✅ 13/13 (204 через ~165 с) | — | — | — | ✅ 13/13 (204 через ~168 с) |
| `.AppImage` (`--as-user tester`) | ✅ 14/14 (204 через ~171 с) | — | — | — | — |

Точные дистрибутивы из журналов прогонов:

| Прогон | Дистрибутив (как сообщил `/etc/os-release`) |
| --- | --- |
| deb-ubuntu | `Ubuntu 26.04 LTS 26.04` |
| deb-debian | `Debian GNU/Linux 13 (trixie) 13` |
| rpm-opensuse | `openSUSE Tumbleweed 20260723` |
| rpm-rocky | `Rocky Linux from CIQ Plus 10.2 (Red Quartz) 10.2` |
| arch | `Arch Linux rolling` |

Ядро во всех прогонах: `6.18.33.2-microsoft-standard-WSL2`.

## 5. Дословные выводы

Каждый блок ниже — вывод стенда целиком, без правок, кроме одного:
путь репозитория сокращён до `<repo>`. Сначала стенд печатает журнал
прогона, затем таблицу шагов и итог.

### Прогон матрицы — `.deb` в Ubuntu 26.04

```
== distro: Ubuntu
== payload: packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb)
== traffic wait: 900s

================ distro output (Ubuntu) ================
=== environment ===
distro : Ubuntu 26.04 LTS 26.04
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb
=== payload ===
kind   : deb
manager: deb
name   : forest-proxy-updater
version: 1.1.0
=== copy payload into distro ===
=== install ===
=== unit: forest-proxy-updater.service ===
test config : /run/fp-matrix-11808/config.json (port 11808, core test ports from 11908)
=== service unit ===
starting forest-proxy-updater.service (systemctl enable + start) with proxy port 11808
=== proxy traffic ===
  ... waiting for the first 204: 30s (last: 000)
  ... waiting for the first 204: 60s (last: 000)
  ... waiting for the first 204: 90s (last: 000)
  ... waiting for the first 204: 120s (last: 000)
  ... waiting for the first 204: 150s (last: 000)
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---

================ PASS/FAIL matrix (Ubuntu) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Ubuntu 26.04 LTS 26.04
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   deb 'forest-proxy-updater' 1.1.0
4    pkg-copy           PASS   /tmp/forest-proxy-updater_1.1.0_amd64.deb (32M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~174s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### Прогон матрицы — `.deb` в Debian 13

```
== distro: Debian
== payload: packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb)
== traffic wait: 900s

================ distro output (Debian) ================
=== environment ===
distro : Debian GNU/Linux 13 (trixie) 13
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb
=== payload ===
kind   : deb
manager: deb
name   : forest-proxy-updater
version: 1.1.0
=== copy payload into distro ===
=== install ===
=== unit: forest-proxy-updater.service ===
test config : /run/fp-matrix-11808/config.json (port 11808, core test ports from 11908)
=== service unit ===
starting forest-proxy-updater.service (systemctl enable + start) with proxy port 11808
=== proxy traffic ===
  ... waiting for the first 204: 30s (last: 000)
  ... waiting for the first 204: 60s (last: 000)
  ... waiting for the first 204: 90s (last: 000)
  ... waiting for the first 204: 120s (last: 000)
  ... waiting for the first 204: 150s (last: 000)
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---

================ PASS/FAIL matrix (Debian) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Debian GNU/Linux 13 (trixie) 13
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   deb 'forest-proxy-updater' 1.1.0
4    pkg-copy           PASS   /tmp/forest-proxy-updater_1.1.0_amd64.deb (32M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~174s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### Прогон матрицы — `.rpm` в openSUSE Tumbleweed

```
== distro: openSUSE-Tumbleweed
== payload: packaging-linux/out/forest-proxy-updater-1.1.0-1.x86_64.rpm  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-1.x86_64.rpm)
== traffic wait: 900s

================ distro output (openSUSE-Tumbleweed) ================
=== environment ===
distro : openSUSE Tumbleweed 20260723
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-1.x86_64.rpm
=== payload ===
kind   : rpm
manager: rpm
name   : forest-proxy-updater
version: 1.1.0-1
=== copy payload into distro ===
=== install ===
=== unit: forest-proxy-updater.service ===
test config : /run/fp-matrix-11808/config.json (port 11808, core test ports from 11908)
=== service unit ===
starting forest-proxy-updater.service (systemctl enable + start) with proxy port 11808
=== proxy traffic ===
  ... waiting for the first 204: 30s (last: 000)
  ... waiting for the first 204: 60s (last: 000)
  ... waiting for the first 204: 90s (last: 000)
  ... waiting for the first 204: 120s (last: 000)
  ... waiting for the first 204: 150s (last: 000)
  ... waiting for the first 204: 180s (last: 000)
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---

================ PASS/FAIL matrix (openSUSE-Tumbleweed) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   openSUSE Tumbleweed 20260723
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   rpm 'forest-proxy-updater' 1.1.0-1
4    pkg-copy           PASS   /tmp/forest-proxy-updater-1.1.0-1.x86_64.rpm (32M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~180s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### Прогон матрицы — `.rpm` в Rocky Linux 10.2 (CIQ)

```
== distro: RLCPlus-10
== payload: packaging-linux/out/forest-proxy-updater-1.1.0-1.x86_64.rpm  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-1.x86_64.rpm)
== traffic wait: 900s

================ distro output (RLCPlus-10) ================
=== environment ===
distro : Rocky Linux from CIQ Plus 10.2 (Red Quartz) 10.2
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-1.x86_64.rpm
=== payload ===
kind   : rpm
manager: rpm
name   : forest-proxy-updater
version: 1.1.0-1
=== copy payload into distro ===
=== install ===
=== unit: forest-proxy-updater.service ===
test config : /run/fp-matrix-11808/config.json (port 11808, core test ports from 11908)
=== service unit ===
starting forest-proxy-updater.service (systemctl enable + start) with proxy port 11808
=== proxy traffic ===
  ... waiting for the first 204: 30s (last: 000)
  ... waiting for the first 204: 60s (last: 000)
  ... waiting for the first 204: 90s (last: 000)
  ... waiting for the first 204: 120s (last: 000)
  ... waiting for the first 204: 150s (last: 000)
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---

================ PASS/FAIL matrix (RLCPlus-10) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Rocky Linux from CIQ Plus 10.2 (Red Quartz) 10.2
2    systemd            PASS   systemd is-system-running=degraded
3    pkg-type           PASS   rpm 'forest-proxy-updater' 1.1.0-1
4    pkg-copy           PASS   /tmp/forest-proxy-updater-1.1.0-1.x86_64.rpm (32M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~177s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### Прогон матрицы — Arch `.pkg.tar.zst`

```
== distro: archlinux
== payload: packaging-linux/out/forest-proxy-updater-1.1.0-1-x86_64.pkg.tar.zst  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-1-x86_64.pkg.tar.zst)
== traffic wait: 900s

================ distro output (archlinux) ================
=== environment ===
distro : Arch Linux rolling
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-1-x86_64.pkg.tar.zst
=== payload ===
kind   : pac
manager: pac
name   : forest-proxy-updater
version: 1.1.0-1
=== copy payload into distro ===
=== install ===
=== unit: forest-proxy-updater.service ===
test config : /run/fp-matrix-11808/config.json (port 11808, core test ports from 11908)
=== service unit ===
starting forest-proxy-updater.service (systemctl enable + start) with proxy port 11808
=== proxy traffic ===
  ... waiting for the first 204: 30s (last: 000)
  ... waiting for the first 204: 60s (last: 000)
  ... waiting for the first 204: 90s (last: 000)
  ... waiting for the first 204: 120s (last: 000)
  ... waiting for the first 204: 150s (last: 000)
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---

================ PASS/FAIL matrix (archlinux) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Arch Linux rolling
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   pac 'forest-proxy-updater' 1.1.0-1
4    pkg-copy           PASS   /tmp/forest-proxy-updater-1.1.0-1-x86_64.pkg.tar.zst (33M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~165s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### Прогон матрицы — `.tar.gz` в Ubuntu 26.04

```
== distro: Ubuntu
== payload: packaging-linux/out/forest-proxy-updater-1.1.0-linux-x86_64.tar.gz  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-linux-x86_64.tar.gz)
== traffic wait: 900s

================ distro output (Ubuntu) ================
=== environment ===
distro : Ubuntu 26.04 LTS 26.04
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-linux-x86_64.tar.gz
=== payload ===
kind   : tar
manager: none (installer / AppImage)
name   : forest-proxy-updater
version: 1.1
=== copy payload into distro ===
=== install ===
unpacked to /tmp/fp-payload/forest-proxy-updater-1.1.0-linux-x86_64
app name: forest-proxy-updater (binary: /usr/lib/forest-proxy-updater/forest-proxy-updater)
=== unit: forest-proxy-updater.service ===
test config : /run/fp-matrix-11808/config.json (port 11808, core test ports from 11908)
=== service unit ===
starting forest-proxy-updater.service (systemctl enable + start) with proxy port 11808
=== proxy traffic ===
  ... waiting for the first 204: 30s (last: 000)
  ... waiting for the first 204: 60s (last: 000)
  ... waiting for the first 204: 90s (last: 000)
  ... waiting for the first 204: 120s (last: 000)
  ... waiting for the first 204: 150s (last: 000)
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---
慢桳›楬敮㈠㔶›楰正湟睥慟灰慮敭›潣浭湡⁤潮⁴潦湵੤
================ PASS/FAIL matrix (Ubuntu) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Ubuntu 26.04 LTS 26.04
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   tar 'forest-proxy-updater' 1.1
4    pkg-copy           PASS   /tmp/forest-proxy-updater-1.1.0-linux-x86_64.tar.gz (33M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~165s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### Прогон матрицы — `.tar.gz` в Arch Linux

```
== distro: archlinux
== payload: packaging-linux/out/forest-proxy-updater-1.1.0-linux-x86_64.tar.gz  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-linux-x86_64.tar.gz)
== traffic wait: 900s

================ distro output (archlinux) ================
=== environment ===
distro : Arch Linux rolling
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater-1.1.0-linux-x86_64.tar.gz
=== payload ===
kind   : tar
manager: none (installer / AppImage)
name   : forest-proxy-updater
version: 1.1
=== copy payload into distro ===
=== install ===
unpacked to /tmp/fp-payload/forest-proxy-updater-1.1.0-linux-x86_64
app name: forest-proxy-updater (binary: /usr/lib/forest-proxy-updater/forest-proxy-updater)
=== unit: forest-proxy-updater.service ===
test config : /run/fp-matrix-11808/config.json (port 11808, core test ports from 11908)
=== service unit ===
starting forest-proxy-updater.service (systemctl enable + start) with proxy port 11808
=== proxy traffic ===
  ... waiting for the first 204: 30s (last: 000)
  ... waiting for the first 204: 60s (last: 000)
  ... waiting for the first 204: 90s (last: 000)
  ... waiting for the first 204: 120s (last: 000)
  ... waiting for the first 204: 150s (last: 000)
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---
慢桳›楬敮㈠㔶›楰正湟睥慟灰慮敭›潣浭湡⁤潮⁴潦湵੤
================ PASS/FAIL matrix (archlinux) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Arch Linux rolling
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   tar 'forest-proxy-updater' 1.1
4    pkg-copy           PASS   /tmp/forest-proxy-updater-1.1.0-linux-x86_64.tar.gz (33M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~168s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### Прогон матрицы — `.AppImage` в Ubuntu 26.04 (`--as-user tester`)

```
== distro: Ubuntu
== payload: packaging-linux/out/ForestProxyUpdater-1.1.0-x86_64.AppImage  (inside distro: <repo>/packaging-linux/out/ForestProxyUpdater-1.1.0-x86_64.AppImage)
== user mode: tester (systemd --user)
== traffic wait: 900s

================ distro output (Ubuntu) ================
=== environment ===
distro : Ubuntu 26.04 LTS 26.04
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/ForestProxyUpdater-1.1.0-x86_64.AppImage
user   : tester (systemd --user flow)
=== payload ===
kind   : appimage
manager: none (installer / AppImage)
name   : ForestProxyUpdater
version: 1.1.0
=== copy payload into distro ===
=== install ===
running the AppImage installer (first cycle skipped — the service does it below)…
app name: forest-proxy-updater (binary: /home/tester/.local/share/forest-proxy-updater/forest-proxy-updater)
=== unit: forest-proxy-updater.service ===
test config : /run/fp-matrix-11808/config.json (port 11808, core test ports from 11908)
=== service unit ===
starting forest-proxy-updater.service (systemctl --user enable + start) with proxy port 11808
=== proxy traffic ===
  ... waiting for the first 204: 30s (last: 000)
  ... waiting for the first 204: 60s (last: 000)
  ... waiting for the first 204: 90s (last: 000)
  ... waiting for the first 204: 120s (last: 000)
  ... waiting for the first 204: 150s (last: 000)
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---
慢桳›楬敮㈠ㄱ›牰捥敬湡畟敳彲湩瑳污㩬挠浯慭摮渠瑯映畯摮戊獡㩨氠湩⁥㘲㨱瀠捩彫敮彷灡湰浡㩥挠浯慭摮渠瑯映畯摮�
================ PASS/FAIL matrix (Ubuntu) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Ubuntu 26.04 LTS 26.04
2    systemd            PASS   systemd is-system-running=running
3    user-mode          PASS   tester uid=1000 home=/home/tester
4    pkg-type           PASS   appimage 'ForestProxyUpdater' 1.1.0
5    pkg-copy           PASS   /tmp/ForestProxyUpdater-1.1.0-x86_64.AppImage (33M)
6    install            PASS   ForestProxyUpdater installed (/home/tester/.local/share/forest-proxy-updater/forest-proxy-updater)
7    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
8    service-active     PASS   forest-proxy-updater.service is active
9    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~171s
10   uninstall          PASS   forest-proxy-updater removed
11   residue-pkg        PASS   not registered in the package DB and payload gone
12   residue-files      PASS   no payload files left behind
13   residue-units      PASS   no unit file / no active service / no autostart
14   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 14 steps  |  14 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### Дословно: установка и удаление одной командой

#### `.deb` — Ubuntu 26.04 (`apt-get install` / `apt-get purge`)

```
wsl: >=D83C@0F8O ?@>:A8-A5@25@0 localhost >1=0@C65=0, => =5 >B@065=0 2 WSL. WSL 2 @568<5 NAT =5 ?>445@68205B ?@>:A8-A5@25@K localhost.
### $ apt-get install -y ./forest-proxy-updater_1.1.0_amd64.deb
Solving dependencies...
The following NEW packages will be installed:
  forest-proxy-updater
0 upgraded, 1 newly installed, 0 to remove and 158 not upgraded.
Need to get 0 B/33.5 MB of archives.
After this operation, 34.3 MB of additional disk space will be used.
Get:1 <repo>/packaging-linux/out/forest-proxy-updater_1.1.0_amd64.deb forest-proxy-updater amd64 1.1.0 [33.5 MB]
Selecting previously unselected package forest-proxy-updater.
(Reading database ... (Reading database ... 5%(Reading database ... 10%(Reading database ... 15%(Reading database ... 20%(Reading database ... 25%(Reading database ... 30%(Reading database ... 35%(Reading database ... 40%(Reading database ... 45%(Reading database ... 50%(Reading database ... 55%(Reading database ... 60%(Reading database ... 65%(Reading database ... 70%(Reading database ... 75%(Reading database ... 80%(Reading database ... 85%(Reading database ... 90%(Reading database ... 95%(Reading database ... 100%(Reading database ... 39117 files and directories currently installed.)
Preparing to unpack .../forest-proxy-updater_1.1.0_amd64.deb ...
Unpacking forest-proxy-updater (1.1.0) ...
Setting up forest-proxy-updater (1.1.0) ...
forest-proxy-updater: служба включена и запущена (systemctl status forest-proxy-updater.service)
forest-proxy-updater: программа даёт доступ ко всем сайтам, включая заблокированные.
  Ответственность за соблюдение законов своей юрисдикции лежит на пользователе.
  Условия использования: /usr/share/doc/forest-proxy-updater/TERMS.ru.md (English: TERMS.md).

### $ systemctl is-active forest-proxy-updater.service
active

### $ dpkg -l forest-proxy-updater
+++-====================-============-============-==============================================================================================
ii  forest-proxy-updater 1.1.0        amd64        FOREST's Proxy Auto-updater — автообновляемый прокси на ядре Xray

### $ apt-get purge -y forest-proxy-updater
0 upgraded, 0 newly installed, 1 to remove and 158 not upgraded.
After this operation, 34.3 MB disk space will be freed.
(Reading database ... (Reading database ... 5%(Reading database ... 10%(Reading database ... 15%(Reading database ... 20%(Reading database ... 25%(Reading database ... 30%(Reading database ... 35%(Reading database ... 40%(Reading database ... 45%(Reading database ... 50%(Reading database ... 55%(Reading database ... 60%(Reading database ... 65%(Reading database ... 70%(Reading database ... 75%(Reading database ... 80%(Reading database ... 85%(Reading database ... 90%(Reading database ... 95%(Reading database ... 100%(Reading database ... 39135 files and directories currently installed.)
Removing forest-proxy-updater (1.1.0) ...
(Reading database ... (Reading database ... 5%(Reading database ... 10%(Reading database ... 15%(Reading database ... 20%(Reading database ... 25%(Reading database ... 30%(Reading database ... 35%(Reading database ... 40%(Reading database ... 45%(Reading database ... 50%(Reading database ... 55%(Reading database ... 60%(Reading database ... 65%(Reading database ... 70%(Reading database ... 75%(Reading database ... 80%(Reading database ... 85%(Reading database ... 90%(Reading database ... 95%(Reading database ... 100%(Reading database ... 39117 files and directories currently installed.)
Purging configuration files for forest-proxy-updater (1.1.0) ...

### residue
dpkg-query: no packages found matching forest-proxy-updater
ls: cannot access '/usr/lib/forest-proxy-updater': No such file or directory
ls: cannot access '/etc/forest-proxy-updater': No such file or directory
ls: cannot access '/var/lib/forest-proxy-updater': No such file or directory
UNIT FILE STATE PRESET

0 unit files listed.
```

#### `.rpm` — openSUSE Tumbleweed (`zypper install` / `zypper remove`)

```
wsl: >=D83C@0F8O ?@>:A8-A5@25@0 localhost >1=0@C65=0, => =5 >B@065=0 2 WSL. WSL 2 @568<5 NAT =5 ?>445@68205B ?@>:A8-A5@25@K localhost.
### $ zypper --non-interactive install ./forest-proxy-updater-1.1.0-1.x86_64.rpm
forest-proxy-updater-1.1.0-1.x86_64.rpm:
    Package header is not signed!
forest-proxy-updater-1.1.0-1.x86_64 (Plain RPM files cache): Signature verification failed [6-File is unsigned]
Accepting package despite the error. (--no-gpg-checks)


Checking for file conflicts: [...done]
(1/1) Installing: forest-proxy-updater-1.1.0-1.x86_64 [...
forest-proxy-updater: служба включена и запущена
forest-proxy-updater: программа даёт доступ ко всем сайтам, включая заблокированные.
  Ответственность за соблюдение законов своей юрисдикции лежит на пользователе.
  Условия использования: /usr/share/doc/forest-proxy-updater/TERMS.ru.md (English: TERMS.md).
done]
Running post-transaction scripts [....done]

### $ systemctl is-active forest-proxy-updater.service
active

### $ systemctl status forest-proxy-updater.service --no-pager
● forest-proxy-updater.service - FOREST's Proxy Auto-updater — supervisor (watchdog + guard + pool refresh)
     Loaded: loaded (/usr/lib/systemd/system/forest-proxy-updater.service; enabled; preset: disabled)
     Active: active (running) since Sat 2026-10-17 03:33:28 MSK; 316ms ago
 Invocation: 68176a902b1149d7bda0e8885da70b02
       Docs: file:/usr/share/doc/forest-proxy-updater/README.md
             file:/usr/share/doc/forest-proxy-updater/INSTALL.md
   Main PID: 360 (forest-proxy-up)
      Tasks: 1 (limit: 19131)

### $ zypper --non-interactive remove forest-proxy-updater
              |         0 B    required by packages that will be installed
   -32.7 MiB  |  -   32.7 MiB  released by packages that will be removed

Backend:  classic_rpmtrans
Continue? [y/n/v/...? shows all options] (y): y
(1/1) Removing: forest-proxy-updater-1.1.0-1.x86_64 [...done]
Running post-transaction scripts [....done]
 

### residue
package forest-proxy-updater is not installed
ls: cannot access '/usr/lib/forest-proxy-updater': No such file or directory
ls: cannot access '/etc/forest-proxy-updater': No such file or directory
ls: cannot access '/var/lib/forest-proxy-updater': No such file or directory
UNIT FILE STATE PRESET

0 unit files listed.
```

#### `.rpm` — Rocky Linux 10.2 (`dnf install` / `dnf remove`)

```
wsl: >=D83C@0F8O ?@>:A8-A5@25@0 localhost >1=0@C65=0, => =5 >B@065=0 2 WSL. WSL 2 @568<5 NAT =5 ?>445@68205B ?@>:A8-A5@25@K localhost.
### $ dnf install -y --nogpgcheck --disablerepo=* ./forest-proxy-updater-1.1.0-1.x86_64.rpm
Transaction test succeeded.
Running transaction
  Preparing        :                                                        1/1 
  Installing       : forest-proxy-updater-1.1.0-1.x86_64                    1/1 
  Running scriptlet: forest-proxy-updater-1.1.0-1.x86_64                    1/1 
forest-proxy-updater: служба включена и запущена
forest-proxy-updater: программа даёт доступ ко всем сайтам, включая заблокированные.
  Ответственность за соблюдение законов своей юрисдикции лежит на пользователе.
  Условия использования: /usr/share/doc/forest-proxy-updater/TERMS.ru.md (English: TERMS.md).

Installed products updated.

Installed:
  forest-proxy-updater-1.1.0-1.x86_64                                           

Complete!

### $ systemctl is-active forest-proxy-updater.service
active

### $ rpm -q forest-proxy-updater
forest-proxy-updater-1.1.0-1.x86_64

### $ dnf remove -y forest-proxy-updater
  Erasing          : forest-proxy-updater-1.1.0-1.x86_64                    1/1 
  Running scriptlet: forest-proxy-updater-1.1.0-1.x86_64                    1/1 
Installed products updated.

Removed:
  forest-proxy-updater-1.1.0-1.x86_64                                           

Complete!

### residue
package forest-proxy-updater is not installed
ls: cannot access '/usr/lib/forest-proxy-updater': No such file or directory
ls: cannot access '/etc/forest-proxy-updater': No such file or directory
ls: cannot access '/var/lib/forest-proxy-updater': No such file or directory
UNIT FILE STATE PRESET

0 unit files listed.
```

#### Arch `.pkg.tar.zst` — Arch Linux (`pacman -U` / `pacman -Rns`)

```
wsl: >=D83C@0F8O ?@>:A8-A5@25@0 localhost >1=0@C65=0, => =5 >B@065=0 2 WSL. WSL 2 @568<5 NAT =5 ?>445@68205B ?@>:A8-A5@25@K localhost.
### $ pacman -U --noconfirm ./forest-proxy-updater-1.1.0-1-x86_64.pkg.tar.zst
Total Installed Size:  32.64 MiB

:: Proceed with installation? [Y/n] 
checking keyring...
checking package integrity...
loading package files...
checking for file conflicts...
:: Processing package changes...
installing forest-proxy-updater...
forest-proxy-updater: служба включена и запущена
forest-proxy-updater: программа даёт доступ ко всем сайтам, включая заблокированные.
  Ответственность за соблюдение законов своей юрисдикции лежит на пользователе.
  Условия использования: /usr/share/doc/forest-proxy-updater/TERMS.ru.md (English: TERMS.md).
:: Running post-transaction hooks...
(1/2) Reloading system manager configuration...
(2/2) Arming ConditionNeedsUpdate...

### $ systemctl is-active forest-proxy-updater.service
active

### $ pacman -Rns --noconfirm forest-proxy-updater
Total Removed Size:  32.64 MiB

:: Do you want to remove these packages? [Y/n] 
:: Processing package changes...
removing forest-proxy-updater...
:: Running post-transaction hooks...
(1/2) Reloading system manager configuration...
(2/2) Arming ConditionNeedsUpdate...

### residue
error: package 'forest-proxy-updater' was not found
ls: cannot access '/usr/lib/forest-proxy-updater': No such file or directory
ls: cannot access '/etc/forest-proxy-updater': No such file or directory
ls: cannot access '/var/lib/forest-proxy-updater': No such file or directory
```

#### `.tar.gz` — Debian 13 (`install.sh` / `uninstall.sh`)

```
wsl: >=D83C@0F8O ?@>:A8-A5@25@0 localhost >1=0@C65=0, => =5 >B@065=0 2 WSL. WSL 2 @568<5 NAT =5 ?>445@68205B ?@>:A8-A5@25@K localhost.
### $ tar xzf forest-proxy-updater-1.1.0-linux-x86_64.tar.gz && cd forest-proxy-updater-1.1.0-linux-x86_64 && sudo ./install.sh
== конфиг ==
  создан: /etc/forest-proxy-updater/config.json
== состояние ==
== документация ==
  документация: /usr/share/doc/forest-proxy-updater
== служба ==
  служба включена и запущена: systemctl status forest-proxy-updater.service

Установка завершена.
  Проверка связи (первые минуты идёт подбор серверов):
    curl -x http://127.0.0.1:10808 -o /dev/null -w '%{http_code}\n' \
         https://www.gstatic.com/generate_204          # ожидается 204
  Журнал:
    journalctl -u forest-proxy-updater -f
  Удаление:
    /tmp/tg/forest-proxy-updater-1.1.0-linux-x86_64/uninstall.sh

Программа даёт доступ ко всем сайтам, включая заблокированные.
Ответственность за соблюдение законов своей юрисдикции лежит на пользователе.
Условия использования: /usr/share/doc/forest-proxy-updater/TERMS.ru.md (English: TERMS.md).

### $ systemctl is-active forest-proxy-updater.service
active

### $ ./uninstall.sh --yes
  удалён: /usr/share/licenses/forest-proxy-updater
  удалён: /usr/bin/forest-proxy-updater
== состояние ==
  удалён: /var/lib/forest-proxy-updater
== конфиг ==
  удалён: /etc/forest-proxy-updater
  daemon-reload выполнен

Удаление завершено. Проверка:
  systemctl is-active forest-proxy-updater.service     # inactive/unknown
  command -v forest-proxy-updater || echo 'команды нет — ок'
  ls /var/lib/forest-proxy-updater 2>/dev/null || echo 'следов нет — ок'

### residue
ls: cannot access '/usr/lib/forest-proxy-updater': No such file or directory
ls: cannot access '/etc/forest-proxy-updater': No such file or directory
ls: cannot access '/var/lib/forest-proxy-updater': No such file or directory
```

#### `.AppImage` — Ubuntu 26.04, пользовательский режим (`--install` / `--uninstall`)

```
wsl: >=D83C@0F8O ?@>:A8-A5@25@0 localhost >1=0@C65=0, => =5 >B@065=0 2 WSL. WSL 2 @568<5 NAT =5 ?>445@68205B ?@>:A8-A5@25@K localhost.
### setup: copy AppImage, make it executable
### $ ./fpu.AppImage --appimage-extract-and-run --install
[2026-10-17 04:21:33] INFO  Ядро и гео-базы перенесены в постоянный каталог /home/tester/.local/share/forest-proxy-updater/bin/xray: xray, geoip.dat, geosite.dat, LICENSE
[2026-10-17 04:21:33] INFO    конфиг уже есть: /home/tester/.config/forest-proxy-updater/config.json
[2026-10-17 04:21:33] INFO    юнит записан: /home/tester/.config/systemd/user/forest-proxy-updater.service
[2026-10-17 04:21:33] INFO    юнит записан: /home/tester/.config/systemd/user/forest-proxy-updater-refresh.service
[2026-10-17 04:21:33] INFO    юнит записан: /home/tester/.config/systemd/user/forest-proxy-updater.timer
[2026-10-17 04:21:33] INFO    systemctl --user daemon-reload: OK
[2026-10-17 04:21:33] INFO    systemctl --user enable --now forest-proxy-updater.service forest-proxy-updater.timer: OK
[2026-10-17 04:21:33] INFO    автозапуск без входа в систему (linger): включён
Установка завершена (Linux).
  программа:  /home/tester/.local/share/forest-proxy-updater/forest-proxy-updater
  конфиг:     /home/tester/.config/forest-proxy-updater/config.json
  состояние:  /home/tester/.local/state/forest-proxy-updater
  служба:     systemctl --user status forest-proxy-updater
  удаление:   forest-proxy-updater --uninstall

### $ systemctl --user is-active forest-proxy-updater.service
active

### $ ./fpu.AppImage --appimage-extract-and-run --uninstall
[2026-10-17 04:21:34] INFO  Запуск FOREST's Proxy Auto-updater (аргументы: --uninstall)
[2026-10-17 04:21:34] INFO  Удаление (Linux) из /home/tester/.local/share/forest-proxy-updater
[2026-10-17 04:21:34] INFO    systemctl --user disable --now forest-proxy-updater.service: OK
[2026-10-17 04:21:34] INFO    systemctl --user disable --now forest-proxy-updater.timer: OK
[2026-10-17 04:21:34] INFO    systemctl --user disable --now forest-proxy-updater-refresh.service: OK
[2026-10-17 04:21:34] INFO    юнит удалён: /home/tester/.config/systemd/user/forest-proxy-updater.service
[2026-10-17 04:21:34] INFO    юнит удалён: /home/tester/.config/systemd/user/forest-proxy-updater-refresh.service
[2026-10-17 04:21:34] INFO    юнит удалён: /home/tester/.config/systemd/user/forest-proxy-updater.timer
[2026-10-17 04:21:34] INFO    конфиг удалён: /home/tester/.config/forest-proxy-updater/config.json
[2026-10-17 04:21:34] INFO    каталог конфига удалён: /home/tester/.config/forest-proxy-updater
[2026-10-17 04:21:34] INFO    данные программы удалён: /home/tester/.local/share/forest-proxy-updater
[2026-10-17 04:21:34] INFO    состояние/логи удалён: /home/tester/.local/state/forest-proxy-updater
Удаление завершено: юниты сняты, ядро остановлено, файлы удалены.

### residue (as tester)
ls: cannot access '/home/tester/.local/share/forest-proxy-updater': No such file or directory
ls: cannot access '/home/tester/.local/bin/forest-proxy-updater': No such file or directory
ls: cannot access '/home/tester/.config/forest-proxy-updater': No such file or directory
ls: cannot access '/home/tester/.config/systemd/user/forest-proxy-updater.service': No such file or directory
ls: cannot access '/home/tester/.local/state/forest-proxy-updater': No such file or directory
### systemd --user units:
UNIT FILE STATE PRESET

0 unit files listed.
### _MEI* left in /tmp:
ls: cannot access '/tmp/_MEI*': No such file or directory
```

## 6. Что нашлось и что стенд пришлось доработать

Половина пунктов ниже — ошибки, найденные именно прогонами (первая версия
пакета не поднималась вообще), поэтому они и описаны.

**В пакетах:**

1. **`WorkingDirectory` указывал на файл, а не на каталог.** Шаблон юнита
   подставлял в `WorkingDirectory` путь к самому бинарнику; systemd падал с
   `status=200/CHDIR`, служба уходила в бесконечный `activating`/рестарт.
   Исправлено (`@WORKDIR@` → `/usr/lib/forest-proxy-updater`).
2. **`rpm` перестал собираться из-за лишних файлов.** После добавления
   `docs/TERMS*.md` в раскладку rpmbuild отказался собирать пакет:
   `Installed (but unpackaged) file(s) found`. Файлы внесены в `%files` — это
   ровно та проверка, ради которой rpm и нужен.
3. **`%` в комментариях spec раскрывается макросом rpm.** Комментарий про
   пост-обработку превратился в `/usr/lib/rpm/brp-compress` и сломал разбор
   spec. В комментариях spec макросов больше нет.
4. **rpm оставлял после себя пустые каталоги.** Каталоги не были объявлены в
   `%files` как `%dir`, поэтому rpm не считал их своими и **не удалял** при
   удалении пакета: после `zypper remove` на openSUSE оставались пустые
   `/etc/forest-proxy-updater` и `/usr/lib/forest-proxy-updater` (файлов внутри
   уже не было — `find -mindepth 1` даёт пусто). Добавлены `%dir`-записи; после
   пересборки и перепрогона каталоги удаляются (см. §5, «Дословно: удаление
   .rpm»), хеш `.rpm` в §1 — уже от исправленной сборки.
5. **`makepkg` от root не работает** — `build-arch.sh` сам понижает права
   (`FOREST_MAKEPKG_USER`, иначе первый uid ≥ 1000). В archlinux-образе не было
   `fakeroot` — поставлен (`pacman -S fakeroot`).
6. **Windows-диск в WSL не хранит права** (`/mnt/d` — всё `0777`): пакет,
   собранный там, положил бы конфиг доступным на запись всем. `lib/common.sh`
   это проверяет и уводит сборку в локальный `$TMPDIR`.
7. **`pacman 7`** убрал `-Qp --format` и требует `-p/--file` для `-Ql` —
   метаданные читаются через `pacman -Qip`/`-Qlp`.
8. **AppImage без FUSE** (в WSL FUSE нет): и сборка, и проверка идут с
   `--appimage-extract-and-run`; после сборки автотесты запускаются прямо из
   AppImage.
9. **`appimagetool` не входит в дистрибутивы** — скачивается сборщиком с
   официального GitHub-релиза (свой можно задать `FOREST_APPIMAGETOOL`).

**В стенде:**

10. **`systemctl enable --now` не перезапускает уже активную службу.** Пакет
    запускает службу своим `postinst`, поэтому drop-in с тестовым конфигом не
    применялся, и первый прогон «проверял» порт 10808 вместо 11808. Стенд теперь
    останавливает службу, применяет drop-in и запускает её заново.
11. **Убитый цикл оставляет свой lock.** Если службу убить посреди цикла, в
    состоянии остаётся `lock.json`, и следующий запуск отказывается делать цикл
    («другой цикл уже выполняется») — пул пуст, трафика нет. Стенд перед стартом
    стирает состояние (он и проверяет чистую установку).
12. **Первый цикл — это минуты, а не секунды.** Продукт скачивает публичные
    списки и тестирует узлы, поэтому шаг трафика ждёт первую `204` до
    `--traffic-wait` (по умолчанию 900 с), а не 15 с.
13. **Продукт не читает `FP_PROXY_PORT`.** Порт задаётся только конфигом,
    поэтому стенд правит конфиг (`FOREST_CONFIG`), не изменяя сам пакет.
14. **AppImage ставится только в пользовательском режиме** — добавлен ключ
    `--as-user` (юниты `systemctl --user` + linger), а первый цикл `--install`
    пропускается штатным `FOREST_SKIP_FIRST_CYCLE`, чтобы цикл делала служба.
15. **Относительный `--package` не отображался в путь WSL** — `to_wsl_path`
    теперь сначала делает путь абсолютным.

**Наблюдения по поведению продукта (не блокеры, к пакетам не относятся):**

* пока пул пуст, сторож пишет в журнал много строк (`Watch: ... пересборка
  немедленно`) — журнал быстро растёт;
* `client.manage_system_proxy: true` в штатном конфиге на сервере без GNOME даёт
  в журнале `ERROR не удалось включить системный прокси`; программа продолжает
  работать на своём порту (в тестовом конфиге стенд этот флаг выключает);
* на дефолтном `config.example.json` (до 400 кандидатов, тест скорости по 5 МБ)
  первый цикл идёт заметно дольше, чем на урезанном тестовом конфиге стенда;
* на образе Rocky Linux (CIQ) `systemctl is-system-running` отвечает
  `degraded` — это состояние самого образа, не пакета: юнит поднялся, стал
  `active` и провёл трафик (см. §5).

## 7. Что осталось непроверенным

Проверено не всё — честный список того, что осталось:

* **FUSE.** AppImage нигде не запускался с настоящим монтированием через FUSE:
  в WSL FUSE нет. И установка, и проверка шли с
  `--appimage-extract-and-run` (та же команда, что рекомендована в
  документации для окружений без FUSE). На обычной рабочей станции с FUSE файл
  должен работать и без этого ключа, но таких прогонов не было.
* **Дистрибутивы.** Fedora, RHEL, AlmaLinux, Linux Mint, Manjaro, EndeavourOS,
  CentOS Stream, предыдущие LTS-выпуски Ubuntu — не проверялись. Пакеты для них
  те же самые (`.rpm` / `.deb` / Arch), но прогонов не делалось.
* **32-битные системы и ARM** — не проверялись: сборка только `x86_64`.
* **WSL-специфика.** Всё тестирование шло в WSL; на «железной» машине не
  проверялись ни systemd (там он обычный), ни автозапуск после перезагрузки
  (`systemctl is-enabled` проверяется, реального reboot не было).
* **`loginctl enable-linger`** для пользовательского режима выставляется
  (в выводе AppImage видно `автозапуск без входа в систему (linger): включён`),
  но проверки именно после перезагрузки не делалось.
* **`forest-proxy-updater.timer`** ставится, но не включается; его штатный
  запуск по расписанию не проверялся.
* **Обновление «поверх»** (установка пакета поверх уже установленной версии) не
  прогонялось: во всех прогонах проверялась установка на чистую систему.
* **Проверка подписи.** Пакеты не подписаны — `dnf`/`rpm` покажут
  `Signature verification failed [6-File is unsigned]`, `zypper` спросит
  подтверждение (в выводе выше это видно). При установке из GitHub-релиза это
  ожидаемо; GPG-ключа у проекта нет.

