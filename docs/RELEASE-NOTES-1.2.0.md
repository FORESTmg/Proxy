# 1.2.0 — автономный надзор: программа поднимает себя сама

**Дата:** 2026-10-17 · **Артефакт:** `ForestProxyUpdater.exe` (Windows, x86_64)

---

## Русский

### Что нового

- **Программа стала по-настоящему само-восстанавливающейся.**
  Установщик (`--install`) ставит **задачу в Планировщике заданий Windows**
  `ForestProxyUpdater-Watchdog` и включает её. Задача:
  - запускает программу **при входе в систему**;
  - **каждые 5 минут** проверяет, работает ли программа, и поднимает её, если
    нет — после падения, случайного закрытия или смерти родительского процесса
    (например, обновления, которое сносит своё дерево процессов).

  Задача скрытая, работает от имени текущего пользователя и настроена **не
  запускать новый экземпляр, пока уже выполняется**. Окно не показывается
  никогда.

- **Новый ключ `--ensure`.** Быстрая проверка (свой файл-маркер + живой процесс
  с той же командной строкой): если супервизора этой установки нет — запускает
  `--run` **отвязанно от вызывающего процесса** (`DETACHED_PROCESS` +
  `CREATE_BREAKAWAY_FROM_JOB`, своя группа процессов). Второй супервизор не
  создаётся (у самой программы тоже есть защита: второй `--run` отказывается
  стартовать). Вывод — только в лог.

- **Выбор и понимание у человека.** Новый ключ `--watchdog on|off|status` и
  секция конфига:
  `"watchdog": { "enabled": true, "interval_min": 5, "task_name": "ForestProxyUpdater-Watchdog" }`.
  В трее — пункт **«Надзор» → «Поднимать программу автоматически»**.
  `--status` и `--watchdog status` честно показывают: включена ли настройка, есть
  ли задача, когда она последний раз запускалась, работает ли программа сейчас.

- **Честное предупреждение при установке.** Программа прямо говорит: задача
  создана и включена; она поднимает программу при входе и раз в 5 минут; если
  надзор не включать или выключить — программа **сама не перезапустится**, и
  запускать её придётся вручную. То же предупреждение печатают `--status` и
  `--watchdog status`.

### Интерфейс: помощник на Qt + индикация по эталону

- **Помощник интерфейса `forest-ui` (Qt/PySide6, LGPL-3.0) — отдельный файл.**
  Значок в трее, меню с подменю и уведомления вынесены в отдельную программу,
  поэтому основная осталась маленькой и без сторонних зависимостей. Ядром
  помощник **не управляет**: пункт меню пишется в `state/ui_cmd.json`, а
  выполняет его супервизор ровно тем же кодом, что и встроенное меню.
- **Индикация — ровно того же состава, что у прежней надстройки** (эталон
  `D:\v2ray-auto-updater`): подсказка из четырёх полей
  (`FOREST <состояние> | <N> серверов | <маршрут РФ> | watch OK`), шесть
  состояний с теми же цветами, карточка с заголовком, подзаголовком,
  процентами, этапами **с временами** и футером, включая **время
  восстановления связи**. Ничего не выброшено; новое — только плавность
  (60 к/с) и оформление (светлая/тёмная тема, своя иконка).
- **Две темы**, автоопределение системной темы и контраст цветов по WCAG
  (минимум 3.36:1).
- **Уведомления**: своя слоистая карточка без мерцания (Windows) или системная
  служба `org.freedesktop.Notifications` (Linux); фокус не перехватывается.
- **Запасные пути честные**: нет помощника / он упал / в системе нет трея —
  работает встроенный значок и встроенные уведомления; встроенный трей ждёт в
  резерве и подхватывает интерфейс, если помощник остановится.
- **Linux**: помощник даёт настоящий значок и меню (StatusNotifier/D-Bus),
  в пакеты добавлены значок и `.desktop`.

### Исправлено

- **Модальное окно «Failed to remove temporary directory»** (Windows,
  PyInstaller-onefile). Копия программы, запущенная **самой программой**
  (`--ensure` → `--run`), наследовала переменные PyInstaller
  `_PYI_APPLICATION_HOME_DIR` / `_PYI_PARENT_PROCESS_LEVEL` и **переиспользовала
  каталог распаковки `_MEI` родителя** вместо своего. Родитель после выхода не
  мог удалить `_MEI` (его файлы держал живой потомок) и показывал модальную
  ошибку. Теперь окружение потомка очищается от переменных PyInstaller (плюс
  `PYINSTALLER_RESET_ENVIRONMENT=1`), поэтому каждый процесс владеет своим `_MEI`
  и сам его убирает. Дополнительно программа при старте уходит из каталога
  распаковки (`config.ensure_safe_cwd`) **до** запуска любых дочерних процессов и
  запускает свои фоновые процессы с рабочим каталогом вне распаковки.

### Изменено

- `--install` больше **не** пишет запись автозапуска в реестр: механизм ровно
  один — задача Планировщика. `--uninstall` убирает и задачу, и старую запись
  автозапуска, и ярлык, и файлы.
- «Свой ли это супервизор» определяется по запущенному `.exe` и каталогу
  состояния, поэтому две разные установки (рабочая и тестовая песочница) друг
  друга не видят.

### Что проверено и чем

<!-- VERIFIED -->
**Windows (тот самый exe, что в релизе).** Контрольный прогон
`FORESTProxyUpdater.exe --selftest` в отдельной песочнице (`FOREST_ROOT`):
**166 проверок OK, 0 FAIL** — API ядра и хранилища состояния, пути, надзор
(задача Планировщика, `--ensure`, защита от второго супервизора), очистка
окружения PyInstaller, i18n.

**Интерфейс и уведомления.** Измерено в этом релизном цикле:
- цикл кадров уведомления — **117 кадров за 1.96 с, средний 60.0 FPS**,
  худший кадр 17.4 мс, фокус не перехвачен, в покое 0.0 мс CPU за 3 с;
  `verify_notify.py` — **18/18 OK**;
- помощник `forest-ui` — `verify_ui.py` **13/14** (единственная «ошибка» была в
  самом тесте: оконная сборка без stdout; починено — есть `state/status.txt`);
- соответствие эталону `v2ray-auto-updater` — `verify_indication.py` прогнал
  эталон **в режиме чтения** (отдельный `FOREST_ROOT`): совпали **6/6 цветов**,
  тултип из четырёх полей и время восстановления связи, VERDICT OK.

**Linux (сборка интерпретатором 3.12).** Обе программы пересобраны заново
(`python` из сборочного venv, 3.12; ранее ошибочно подхватывался системный
3.14 — отсюда были и красные проверки, и устаревшие результаты). Самопроверки:
- `forest-proxy-updater --selftest` — **216 OK, 0 FAIL**;
- `forest-ui --selftest` — **32 OK, 0 FAIL** (на Linux своего анимированного
  окна нет: проверяется путь через службу `org.freedesktop.Notifications`,
  определяется ли её доступность, не роняет ли её отсутствие помощник, и
  определена ли тема — вместо FPS);
- без графической сессии помощник **тихо выходит** (код 0) с записью в лог, а
  не падает `Aborted`: проверка `DISPLAY`/`WAYLAND_DISPLAY` стоит **до**
  создания `QApplication`; для `--selftest` включается платформа `offscreen`.

**Пакеты.** Матрица «пакет × дистрибутив» (стенд `linux/tests/wsl-matrix.sh`,
порт 11808, живой прокси пользователя не затронут): установка одной командой →
служба активна → **реальный трафик** (`curl -x http://127.0.0.1:11808
https://www.gstatic.com/generate_204` = **204**) → чистое удаление (пакет,
файлы, юниты, порт).

| Пакет | Дистрибутив | Итог |
| --- | --- | --- |
| `.deb` | Ubuntu 26.04 | **13/13 PASS**, 204 через ~132 с |
| `.deb` | Debian 13 | **13/13 PASS**, 204 через ~129 с |
| `.rpm` | openSUSE Tumbleweed | **13/13 PASS**, 204 через ~132 с |
| `.rpm` | Rocky Linux (CIQ Plus 10) | **13/13 PASS**, 204 через ~147 с |
| `.pkg.tar.zst` | Arch Linux | **13/13 PASS**, 204 через ~126 с |

Ни одного FAIL, ни одного SKIP. Дословные журналы — в
`docs/LINUX-PACKAGES-PROOF.ru.md`.

### Что НЕ проверено

<!-- NOTVERIFIED -->
- **Windows-часть не перепроверялась целиком в этом проходе** — только
  контрольный `--selftest` (166/0). Установка/удаление, задача Планировщика и
  реестр на «живой» системе пользователя не трогались сознательно.
- **Пакеты ставились в WSL** (Ubuntu 26.04, Debian 13, openSUSE Tumbleweed,
  Rocky Linux из CIQ Plus 10.2, Arch Linux) на ядре
  `6.18.33.2-microsoft-standard-WSL2`, а не на отдельном железе. Ядро/геометрию
  bare-metal и других дистрибутивов не заявляем.
- **`.tar.gz` и `.AppImage`** пересобраны заново (33 и 34 МБ), но в этом
  проходе матрицей не прогонялись: они портативные и помощник интерфейса в них
  не вложен (прилагается отдельным файлом). Их установка проверялась в прошлом
  проходе.
- **`lintian` / `rpmlint` / `namcap`** не запускались — стилевые замечания
  сборщиков не проверены.
- **Подпись пакетов (gpg) и репозитории** не делались: файлы раздаются
  напрямую, целостность — по `SHA256SUMS`.
- **Сеть проверялась косвенно**: успешный выход в интернет подтверждён кодом
  204, но списки серверов, скорость и гео-базы «до конца» не измерялись.
- **D-Bus-служба уведомлений** в WSL отсутствует (`org.freedesktop.Notifications`
  не зарегистрирована), поэтому на Linux проверено, что её отсутствие
  **корректно определяется** и не роняет помощник, а не приход самого
  уведомления.

---

## English

### What is new

- **The program is now genuinely self-healing.** The installer (`--install`)
  registers a **Windows Task Scheduler task** `ForestProxyUpdater-Watchdog` and
  enables it. The task:
  - starts the program **when you log in**;
  - **every 5 minutes** checks whether the program is running and starts it again
    if it is not — after a crash, an accidental close, or the death of the parent
    process that started it (for example an updater that kills its own process
    tree).

  The task is hidden, runs as the current user and is configured **not to start a
  new instance while it is already running**. It never shows a window.

- **New `--ensure` mode.** A quick check (own marker file + a live process with
  the same command line): if no supervisor of this installation is alive, it
  launches `--run` **detached from the calling process** (`DETACHED_PROCESS` +
  `CREATE_BREAKAWAY_FROM_JOB`, own process group). A second supervisor is never
  created (the program itself also refuses a second `--run`). Output goes to the
  log only.

- **The user has a choice and can see what is going on.** New
  `--watchdog on|off|status` and a config section:
  `"watchdog": { "enabled": true, "interval_min": 5, "task_name": "ForestProxyUpdater-Watchdog" }`.
  The tray menu gained **Supervision → “Bring the program up automatically”**.
  `--status` and `--watchdog status` honestly report: is the setting on, is the
  task present, when did it last run, is the program running now.

- **An honest notice at install time.** The program says plainly: the task was
  created and enabled; it raises the program at logon and every 5 minutes; if you
  do not create it or switch it off, the program **will not restart itself** and
  you will have to start it by hand. The same warning is printed by `--status` and
  `--watchdog status`.

### Interface: the Qt helper + the indication of the reference build

- **Interface helper `forest-ui` (Qt/PySide6, LGPL-3.0) — a separate file.** The
  tray icon, the menu with submenus and notifications live in their own program,
  so the main program stays small and dependency-free. The helper **never touches
  the core**: a menu item becomes a command in `state/ui_cmd.json`, and the
  supervisor performs it through exactly the same code as the built-in menu.
- **The indication is the exact composition of the previous add-on** (reference
  `D:\v2ray-auto-updater`): the four-field tooltip
  (`FOREST <state> | <N> servers | <RU route> | watch OK`), six states with the
  same colours, and a card with title, subtitle, percentage, the step list
  **with per-step times** and the footer — including **the link recovery time**.
  Nothing was dropped; what is new is the smoothness (60 fps) and the look
  (light/dark themes, your own icon).
- **Two themes**, automatic detection of the system theme, and WCAG contrast
  checks for the state colours (minimum 3.36:1).
- **Notifications**: our own flicker-free layered card (Windows) or the system
  service `org.freedesktop.Notifications` (Linux); keyboard focus is never taken.
- **Honest fallbacks**: no helper / a crashed helper / no tray at all — the
  built-in icon and built-in notifications work, and the built-in tray waits in
  reserve and takes over if the helper stops.
- **Linux**: the helper gives a real tray icon and menu
  (StatusNotifier/D-Bus); packages now ship the icon and `.desktop` files.

### Fixed

- **Modal window “Failed to remove temporary directory”** (Windows, PyInstaller
  onefile). A copy of the program started **by the program itself**
  (`--ensure` → `--run`) inherited PyInstaller's `_PYI_APPLICATION_HOME_DIR` /
  `_PYI_PARENT_PROCESS_LEVEL` and **reused the parent's `_MEI` unpack directory**
  instead of extracting its own. After exiting, the parent could not delete `_MEI`
  (its files were still held by the surviving child) and showed the modal error.
  The child environment is now cleared of the PyInstaller variables (plus
  `PYINSTALLER_RESET_ENVIRONMENT=1`), so every process owns and removes its own
  `_MEI`. In addition the program leaves the unpack directory on start
  (`config.ensure_safe_cwd`) **before** launching any child process, and starts
  its background processes with a working directory outside the unpack directory.

### Changed

- `--install` no longer writes an autostart registry entry: there is exactly one
  mechanism, the scheduler task. `--uninstall` removes the task, any legacy
  autostart entry, the shortcut and the files.
- “Is a supervisor of this installation alive” is decided from the running `.exe`
  and the state directory, so two different installations (a working one and a
  test sandbox) never see each other.

### Verified, and how

<!-- VERIFIED_EN -->
**Windows (the very exe shipped in the release).** A control run of
`ForestProxyUpdater.exe --selftest` in a separate sandbox (`FOREST_ROOT`):
**166 checks OK, 0 FAIL** — core and state-store API, paths, supervision
(scheduler task, `--ensure`, second-supervisor guard), PyInstaller environment
cleanup, i18n.

**Interface and notifications.** Measured within this release cycle:
- notification frame cycle — **117 frames in 1.96 s, 60.0 FPS average**, worst
  frame 17.4 ms, focus never taken, 0.0 ms CPU over 3 s at idle;
  `verify_notify.py` — **18/18 OK**;
- the `forest-ui` helper — `verify_ui.py` **13/14** (the single "failure" was in
  the test itself: a windowed build has no stdout; fixed — `state/status.txt`);
- conformance to the reference `v2ray-auto-updater` — `verify_indication.py` ran
  the reference **read-only** (its own `FOREST_ROOT`): **6/6 colours** matched,
  the four-field tooltip and the link-recovery time matched, VERDICT OK;
- the "RU direct" filter — `verify_ru.py` **14/14 OK**: the rules are present
  with `ru_direct=true`, the config passes `xray run -test`, Russian traffic
  leaves via the home address and foreign traffic via the node; with the filter
  off there are no rules.

**Linux (built with the 3.12 interpreter).** Both programs were rebuilt from
scratch (the build venv python, 3.12; the system 3.14 used to be picked up by
mistake — hence the red checks and stale results). Self-tests:
- `forest-proxy-updater --selftest` — **216 OK, 0 FAIL**;
- `forest-ui --selftest` — **32 OK, 0 FAIL** (Linux has no animated window of
  its own: the test checks the `org.freedesktop.Notifications` path, that its
  availability is detected, that its absence does not break the helper, and that
  the theme is detected — instead of FPS);
- with no graphical session the helper **exits quietly** (code 0) and logs it
  instead of aborting: the `DISPLAY`/`WAYLAND_DISPLAY` check runs **before**
  `QApplication` is created; for `--selftest` the `offscreen` platform is enabled.

**Packages.** The package × distribution matrix (bench
`linux/tests/wsl-matrix.sh`, port 11808, the user's live proxy untouched):
one-command install → service active → **real traffic**
(`curl -x http://127.0.0.1:11808 https://www.gstatic.com/generate_204` = **204**)
→ clean removal (package, files, units, port).

| Package | Distribution | Result |
| --- | --- | --- |
| `.deb` | Ubuntu 26.04 | **13/13 PASS**, 204 after ~132 s |
| `.deb` | Debian 13 | **13/13 PASS**, 204 after ~129 s |
| `.rpm` | openSUSE Tumbleweed | **13/13 PASS**, 204 after ~132 s |
| `.rpm` | Rocky Linux (CIQ Plus 10) | **13/13 PASS**, 204 after ~147 s |
| `.pkg.tar.zst` | Arch Linux | **13/13 PASS**, 204 after ~126 s |

No FAIL, no SKIP. Verbatim logs are in `docs/LINUX-PACKAGES-PROOF.ru.md`.

### Not verified

<!-- NOTVERIFIED_EN -->
- **The Windows side was not re-verified in full in this pass** — only the
  control `--selftest` (166/0). Install/uninstall, the scheduler task and the
  registry on the user's live system were deliberately left alone.
- **Packages were installed in WSL** (Ubuntu 26.04, Debian 13, openSUSE
  Tumbleweed, Rocky Linux from CIQ Plus 10.2, Arch Linux) on kernel
  `6.18.33.2-microsoft-standard-WSL2`, not on separate hardware. No claims are
  made for bare metal or other distributions.
- **`.tar.gz` and `.AppImage`** were rebuilt (33 and 34 MB) but were not put
  through the matrix in this pass: they are portable and do not embed the
  interface helper (it is shipped as a separate file). Their install was tested
  in an earlier pass.
- **`lintian` / `rpmlint` / `namcap`** were not run — packager style warnings are
  unchecked.
- **Package signing (gpg) and repositories** were not done: files are served
  directly, integrity via `SHA256SUMS`.
- **The network was verified indirectly**: successful egress is confirmed by the
  204 code, but the server lists, speed and geo bases were not measured
  end-to-end.
- **The D-Bus notification service** is absent in WSL
  (`org.freedesktop.Notifications` is not registered), so on Linux what was
  verified is that its absence is **correctly detected** and does not break the
  helper — not the arrival of a real notification.

---

## Артефакты / Artifacts

<!-- ARTIFACTS -->
Все файлы приложены к релизу. Рядом с каждым лежит его `.sha256`, а `SHA256SUMS`
содержит список по всем сразу.

| Файл | Размер, Б | sha256 |
| --- | --- | --- |
| `ForestProxyUpdater.exe` (Windows, x86_64) | 30 700 675 | `a8ba291440556c499a31c28fceddb0788b730ffa7cd40f57b5aeeebb4bd23a8c` |
| `forest-ui.exe` (Windows, помощник интерфейса, Qt) | 37 021 149 | `2be73c38dd460c51f94b9427958be4c242fc647e218514105dc38cc8e3270913` |
| `forest-proxy-updater-linux-x86_64` (Linux ELF) | 34 251 760 | `f0eab39da0d55c92e5980ab868ace45f9d9f5abe07a2bc7e612bfb8da193ef8f` |
| `forest-ui-linux-x86_64` (Linux, помощник интерфейса, Qt) | 64 062 152 | `74e2d568ea400fe9b7cbba517fc5be5f3fb7f8cfb550cec7d845e6ec165f7128` |
| `forest-proxy-updater_1.2.0_amd64.deb` (Ubuntu / Debian) | 96 745 892 | `f8112961cbf349a108570c20160d89fccaa586e238335dacd0d1cf334f954572` |
| `forest-proxy-updater-1.2.0-1.x86_64.rpm` (openSUSE / Fedora / RHEL / Rocky) | 96 873 963 | `39da488b22177028fa2e066c6e6f4a180a01a3729a05e6a71043c9fbc085fafd` |
| `forest-proxy-updater-1.2.0-1-x86_64.pkg.tar.zst` (Arch / Manjaro) | 97 633 966 | `2d3f4ef7d780e05d82707f59f2b745577e3695805cd50a61ca7f04592ccba7b2` |
| `forest-proxy-updater-1.2.0-linux-x86_64.tar.gz` (портативно) | 33 698 748 | `36fa9847b68ea68fbd1c22002b110eccaa6bf663d7205a62e1f3726504019aea` |
| `ForestProxyUpdater-1.2.0-x86_64.AppImage` (портативно) | 34 671 096 | `0c43e613fabd24a3c980194401a3d98894babdc23aa505ca8bceebbd7d4dbe29` |

В `.deb`, `.rpm` и Arch-пакет помощник интерфейса уже вложен (в
`/usr/lib/forest-proxy-updater/forest-ui`); в портативных `.tar.gz` и `AppImage`
его нет — он ставится отдельно файлом `forest-ui-linux-x86_64`.

## Установка / Installation

Windows: скачайте `ForestProxyUpdater.exe` и запустите его — при первом запуске
программа разложится в `%LOCALAPPDATA%\ForestProxyUpdater`, поставит задачу
надзора и выполнит первый подбор серверов.

Windows: download `ForestProxyUpdater.exe` and run it — on first run the program
lays itself out under `%LOCALAPPDATA%\ForestProxyUpdater`, creates the supervision
task and performs the first server selection.

Linux: см. `docs/LINUX-INSTALL.md` / `docs/LINUX-INSTALL.ru.md` (надзор там даёт
systemd: `Restart=always` + таймер; `--ensure` поднимает службу, если она не
работает).

GPL-3.0-only. Условия использования: `docs/TERMS.md` / `docs/TERMS.ru.md`.
