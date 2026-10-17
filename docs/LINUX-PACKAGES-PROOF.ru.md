# Linux: пакеты 1.2.0 — что собрано и что проверено

Отчёт о фактически выполненной работе. Каждый хеш, размер и вывод ниже получены запуском на этой машине; ничего не додумано. Живой Windows-прокси пользователя (порты 10808/10820, реестр, системный прокси, каталог
`%LOCALAPPDATA%\ForestProxyUpdater`) не затрагивался: тесты идут на своём порту 11808 и в своих каталогах внутри WSL.

Дата сборки и проверки: 2026-10-17.

## 1. Сборка приложения (вход для всех пакетов)

Обе программы собраны PyInstaller 6.22.3 **интерпретатором 3.12** (`packaging/.build-venv-linux`, создан через `uv venv --python 3.12`). Это существенно: сборка системным `python3` (3.14) давала нерабочие проверки и устаревшие результаты.

```sh
PYI_PYTHON=<repo>/packaging/.build-venv-linux/bin/python \
    bash packaging/build-linux.sh --skip-core      # linux/dist/forest-proxy-updater
bash packaging/build-ui.sh                          # linux/dist/forest-ui (Qt)
```

| Артефакт | Размер, Б | sha256 |
| --- | --- | --- |
| `linux/dist/forest-proxy-updater` | 34 251 760 | `f0eab39da0d55c92e5980ab868ace45f9d9f5abe07a2bc7e612bfb8da193ef8f` |
| `linux/dist/forest-ui` | 64 062 152 | `74e2d568ea400fe9b7cbba517fc5be5f3fb7f8cfb550cec7d845e6ec165f7128` |

## 2. Пакеты

Все форматы, кроме портативных, собираются из **одной раскладки** — `stage_payload` в `packaging-linux/lib/common.sh`. Поэтому содержимое `.deb`, `.rpm` и Arch-пакета не может разъехаться: в каждом лежат оба ELF (программа и помощник интерфейса), юниты systemd, `.desktop`-файлы и значок.

Один прогон (в дистрибутиве, где есть нужные инструменты):

```sh
bash packaging-linux/build-all.sh
```

> `build-all.sh` перезапускает себя под bash, если его вызвали через `sh`: сборщики используют `${BASH_SOURCE}`, и в dash (Ubuntu) падали с `Bad substitution`, из-за чего полный прогон не собирался.

| Файл | Размер, Б | sha256 |
| --- | --- | --- |
| `forest-proxy-updater_1.2.0_amd64.deb` | 96 745 892 | `f8112961cbf349a108570c20160d89fccaa586e238335dacd0d1cf334f954572` |
| `forest-proxy-updater-1.2.0-1.x86_64.rpm` | 96 873 963 | `39da488b22177028fa2e066c6e6f4a180a01a3729a05e6a71043c9fbc085fafd` |
| `forest-proxy-updater-1.2.0-1-x86_64.pkg.tar.zst` | 97 633 966 | `2d3f4ef7d780e05d82707f59f2b745577e3695805cd50a61ca7f04592ccba7b2` |
| `forest-proxy-updater-1.2.0-linux-x86_64.tar.gz` | 33 698 748 | `36fa9847b68ea68fbd1c22002b110eccaa6bf663d7205a62e1f3726504019aea` |
| `ForestProxyUpdater-1.2.0-x86_64.AppImage` | 34 671 096 | `0c43e613fabd24a3c980194401a3d98894babdc23aa505ca8bceebbd7d4dbe29` |

Рядом с каждым файлом — `.sha256`. Артефакты в git не добавляются (`packaging-linux/out/` в `.gitignore`).

Раскладка внутри `.deb`/`.rpm`/Arch (проверено распаковкой `.deb`):

```
/usr/lib/forest-proxy-updater/forest-proxy-updater   самодостаточный ELF (Python, ядро Xray, гео-базы)
/usr/lib/forest-proxy-updater/forest-ui              помощник интерфейса (Qt), программа ищет его рядом с собой
/usr/bin/forest-proxy-updater, /usr/bin/forest-ui     симлинки в PATH
/usr/lib/systemd/system/forest-proxy-updater*.{service,timer}
/etc/forest-proxy-updater/config.json
/usr/share/applications/forest-proxy-updater{,-ui}.desktop
/usr/share/icons/hicolor/256x256/apps/forest-proxy-updater.png
/usr/share/doc/forest-proxy-updater/*, /usr/share/licenses/forest-proxy-updater/COPYING
```

`.tar.gz` и `AppImage` — облегчённые портативные сборки: в них только сама программа (33–34 МБ против 93–94 МБ у пакетов), помощник интерфейса к ним прилагается отдельным файлом.

## 3. Самопроверки на Linux

| Прогон | OK | FAIL |
| --- | --- | --- |
| `forest-proxy-updater --selftest` (основная программа) | 216 | 0 |
| `forest-ui --selftest` (помощник интерфейса) | 32 | 0 |

Основная программа — общий набор плюс POSIX-часть (`linux/posix_selftest.py`): подмена примитивов, XDG-пути, процессы через `/proc`, рендер юнитов systemd, мягкая деградация уведомлений.

### 3.1 Помощник интерфейса: чем Linux отличается

Своего анимированного окна на Linux **нет** — уведомления отдаёт системная служба `org.freedesktop.Notifications` (D-Bus). Поэтому самотест на Linux проверяет не кадры/FPS, а: выбран ли путь через службу, определяется ли её доступность, не роняет ли помощник её отсутствие, и определена ли тема. Вывод (последние строки `forest-ui --selftest`):

```
  Linux: своё окно не рисуем (кадров=0); служба уведомлений доступна: False; уведомление отдано: ok=True
  Linux: определённая тема: light (палитра (250, 250, 250))
  OK   Linux: уведомление уходит системной службе (своего окна нет) — {'frames': 0, 'avg_fps': 0.0, 'worst_ms': 0.0, 'dbus': True, 'ok': True, 'svc': False}
  OK   Linux: доступность службы уведомлений определена (bool) — False
  OK   Linux: отсутствие службы уведомлений не роняет помощник
  OK   Linux: тема определена и известна (light/dark) — light
```

Значок каждого состояния проверяется по цвету из той же таблицы, из которой он нарисован (`tray_icon.states`): состояния эталона обязаны повторять `status_info` дословно, четыре «рабочих» — совпадать с палитрой темы. Раньше значок сверялся с палитрой напрямую, и на светлой теме (по умолчанию в WSL) четыре состояния из восьми падали — на Windows это не проявлялось только потому, что там тема тёмная.

### 3.2 Нет графической сессии — тихий выход, а не падение

Без `DISPLAY`/`WAYLAND_DISPLAY` помощник проверяет сессию **до** создания `QApplication` (иначе Qt падает с `Aborted`) и тихо выходит, записав строку в лог. `--selftest` в этом случае сам включает платформу `offscreen`:

```
$ env -u DISPLAY -u WAYLAND_DISPLAY ./linux/dist/forest-ui
[2026-10-17 17:20:22] INFO  forest-ui: нет графической сессии (DISPLAY/WAYLAND_DISPLAY не заданы) — помощник не запущен
forest-ui: нет графической сессии (DISPLAY/WAYLAND_DISPLAY не заданы) — помощник не запущен
код возврата: 0
```

### 3.3 Windows — контрольный прогон

Тот же exe, что уходит в релиз (`ForestProxyUpdater.exe`), прогнан ещё раз в песочнице со своим `FOREST_ROOT`:

```
$ FOREST_ROOT=<песочница> ./packaging/dist/ForestProxyUpdater.exe --selftest
OK: 166   FAIL: 0   -> ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ, код возврата 0
```

## 4. Матрица: пакет × дистрибутив

Каждый прогон: установка одной командой → служба активна → **реальный трафик** через прокси на порту 11808 → чистое удаление (пакет, файлы, юниты, порт). Ни одного FAIL, ни одного SKIP.

```sh
bash linux/tests/wsl-matrix.sh --distro <дистрибутив> \
     --package packaging-linux/out/<файл> --port 11808 --traffic-wait 900 --isolate
```

| Прогон | Дистрибутив | Пакет | Итог |
| --- | --- | --- | --- |
| deb-ubuntu | Ubuntu 26.04 | .deb | 13/13 PASS, 204 через ~132 с — PASS |
| deb-debian | Debian 13 | .deb | 13/13 PASS, 204 через ~129 с — PASS |
| rpm-opensuse | openSUSE Tumbleweed | .rpm | 13/13 PASS, 204 через ~132 с — PASS |
| rpm-rocky | Rocky Linux (CIQ Plus 10) | .rpm | 13/13 PASS, 204 через ~147 с — PASS |
| arch | Arch Linux | .pkg.tar.zst | 13/13 PASS, 204 через ~126 с — PASS |

## 5. Дословные выводы матрицы

Ниже — вывод стенда целиком (путь репозитория сокращён до `<repo>`).

### deb-ubuntu — Ubuntu 26.04

```
== distro: Ubuntu
== payload: packaging-linux/out/forest-proxy-updater_1.2.0_amd64.deb  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater_1.2.0_amd64.deb)
== traffic wait: 900s

================ distro output (Ubuntu) ================
=== environment ===
distro : Ubuntu 26.04 LTS 26.04
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater_1.2.0_amd64.deb
=== payload ===
kind   : deb
manager: deb
name   : forest-proxy-updater
version: 1.2.0
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
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---
wsl: Конфигурация прокси-сервера localhost обнаружена, но не отражена в WSL. WSL в режиме NAT не поддерживает прокси-серверы localhost.

================ PASS/FAIL matrix (Ubuntu) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Ubuntu 26.04 LTS 26.04
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   deb 'forest-proxy-updater' 1.2.0
4    pkg-copy           PASS   /tmp/forest-proxy-updater_1.2.0_amd64.deb (93M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~132s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### deb-debian — Debian 13

```
== distro: Debian
== payload: packaging-linux/out/forest-proxy-updater_1.2.0_amd64.deb  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater_1.2.0_amd64.deb)
== traffic wait: 900s

================ distro output (Debian) ================
=== environment ===
distro : Debian GNU/Linux 13 (trixie) 13
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater_1.2.0_amd64.deb
=== payload ===
kind   : deb
manager: deb
name   : forest-proxy-updater
version: 1.2.0
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
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---
wsl: Конфигурация прокси-сервера localhost обнаружена, но не отражена в WSL. WSL в режиме NAT не поддерживает прокси-серверы localhost.

================ PASS/FAIL matrix (Debian) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Debian GNU/Linux 13 (trixie) 13
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   deb 'forest-proxy-updater' 1.2.0
4    pkg-copy           PASS   /tmp/forest-proxy-updater_1.2.0_amd64.deb (93M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~129s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### rpm-opensuse — openSUSE Tumbleweed

```
== distro: openSUSE-Tumbleweed
== payload: packaging-linux/out/forest-proxy-updater-1.2.0-1.x86_64.rpm  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater-1.2.0-1.x86_64.rpm)
== traffic wait: 900s

================ distro output (openSUSE-Tumbleweed) ================
=== environment ===
distro : openSUSE Tumbleweed 20260723
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater-1.2.0-1.x86_64.rpm
=== payload ===
kind   : rpm
manager: rpm
name   : forest-proxy-updater
version: 1.2.0-1
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
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---
wsl: Конфигурация прокси-сервера localhost обнаружена, но не отражена в WSL. WSL в режиме NAT не поддерживает прокси-серверы localhost.

================ PASS/FAIL matrix (openSUSE-Tumbleweed) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   openSUSE Tumbleweed 20260723
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   rpm 'forest-proxy-updater' 1.2.0-1
4    pkg-copy           PASS   /tmp/forest-proxy-updater-1.2.0-1.x86_64.rpm (93M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~132s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### rpm-rocky — Rocky Linux (CIQ Plus 10)

```
== distro: RLCPlus-10
== payload: packaging-linux/out/forest-proxy-updater-1.2.0-1.x86_64.rpm  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater-1.2.0-1.x86_64.rpm)
== traffic wait: 900s

================ distro output (RLCPlus-10) ================
=== environment ===
distro : Rocky Linux from CIQ Plus 10.2 (Red Quartz) 10.2
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater-1.2.0-1.x86_64.rpm
=== payload ===
kind   : rpm
manager: rpm
name   : forest-proxy-updater
version: 1.2.0-1
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
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---
wsl: Конфигурация прокси-сервера localhost обнаружена, но не отражена в WSL. WSL в режиме NAT не поддерживает прокси-серверы localhost.

================ PASS/FAIL matrix (RLCPlus-10) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Rocky Linux from CIQ Plus 10.2 (Red Quartz) 10.2
2    systemd            PASS   systemd is-system-running=degraded
3    pkg-type           PASS   rpm 'forest-proxy-updater' 1.2.0-1
4    pkg-copy           PASS   /tmp/forest-proxy-updater-1.2.0-1.x86_64.rpm (93M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~147s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

### arch — Arch Linux

```
== distro: archlinux
== payload: packaging-linux/out/forest-proxy-updater-1.2.0-1-x86_64.pkg.tar.zst  (inside distro: <repo>/packaging-linux/out/forest-proxy-updater-1.2.0-1-x86_64.pkg.tar.zst)
== traffic wait: 900s

================ distro output (archlinux) ================
=== environment ===
distro : Arch Linux rolling
kernel : 6.18.33.2-microsoft-standard-WSL2
port   : 11808
payload: <repo>/packaging-linux/out/forest-proxy-updater-1.2.0-1-x86_64.pkg.tar.zst
=== payload ===
kind   : pac
manager: pac
name   : forest-proxy-updater
version: 1.2.0-1
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
=== uninstall ===
=== residue ===
------------------------------------------------------------
inner verdict: ALL PASS
--- wsl/diagnostic stderr ---
wsl: Конфигурация прокси-сервера localhost обнаружена, но не отражена в WSL. WSL в режиме NAT не поддерживает прокси-серверы localhost.

================ PASS/FAIL matrix (archlinux) ================
#    STEP               STATUS DETAIL
--   ------------------ ------ ---------------------------------------------
1    env                PASS   Arch Linux rolling
2    systemd            PASS   systemd is-system-running=running
3    pkg-type           PASS   pac 'forest-proxy-updater' 1.2.0-1
4    pkg-copy           PASS   /tmp/forest-proxy-updater-1.2.0-1-x86_64.pkg.tar.zst (94M)
5    install            PASS   forest-proxy-updater installed (/usr/lib/forest-proxy-updater/forest-proxy-updater)
6    unit-present       PASS   systemd unit 'forest-proxy-updater.service' installed and visible
7    service-active     PASS   forest-proxy-updater.service is active
8    proxy-traffic      PASS   curl -x http://127.0.0.1:11808 -> 204 after ~126s
9    uninstall          PASS   forest-proxy-updater removed
10   residue-pkg        PASS   not registered in the package DB and payload gone
11   residue-files      PASS   no payload files left behind
12   residue-units      PASS   no unit file / no active service / no autostart
13   residue-port       PASS   127.0.0.1:11808 is closed

TOTAL: 13 steps  |  13 PASS  |  0 FAIL  |  0 SKIP
RESULT: PASS
```

## 6. Сверка с эталоном (v2ray-auto-updater)

`src/status_info.py` повторяет эталонный скрипт дословно (поля, порядок, формулировки, цвета). Проверка `verify_indication.py` прогнала эталон в режиме чтения (отдельный `FOREST_ROOT`): совпали **6/6 цветов**, тултип из четырёх полей и время восстановления связи — VERDICT OK, стенд эталона не изменялся. То же подтверждает самотест помощника: «шесть состояний эталона дают свои цвета», «тексты окна совпадают с эталоном дословно», «время восстановления связи есть».

### Что не проверено

- Виндовые/Deb-пакеты ставились **в WSL**, а не на «живом» железе: systemd работает, ядро WSL2 (см. §5). Пакеты не проверялись на bare-metal и не проходили lintian/rpmlint.
- `.tar.gz` и `AppImage` установлены и проверены ранее (см. историю репозитория); в текущей редакции они пересобраны, но матрицей заново не прогонялись.
- Загрузка обновлений из интернета проверялась только косвенно (через факт успешного выхода в сеть — код 204).
- Подпись пакетов (gpg) не делалась.

