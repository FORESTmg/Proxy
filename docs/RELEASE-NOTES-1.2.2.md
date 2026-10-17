# v1.2.2 — иконка пользователя, живое уведомление, «Фильтры» в меню / the user's icon, a live notification, “Filters” in the menu

**Дата / Date:** 2026-10-17 · **Тег / Tag:** `v1.2.2`
**Артефакты / Artifacts:** `ForestProxyUpdater.exe` (Windows), `forest-ui.exe`
(Windows helper), `forest-proxy-updater` (Linux ELF), `forest-ui` (Linux helper),
пакеты `.deb` / `.rpm` / Arch `.pkg.tar.zst` / AppImage / `.tar.gz`.

---

## 🇷🇺 Русский

### Что было не так

1. **Значок в трее был не рисунком пользователя.** `tray_icon.user_state_ico`
   накладывал цвет состояния **поверх** `app.ico` с 90 % смешением — рисунок
   (бирюзовое кольцо, зелёная дуга, красная цепочка, белый самолётик)
   превращался в одноцветную плитку.
2. **Сборка могла молча подменить иконку.** `build.ps1` рисовал *сгенерированный*
   `app.ico` (`make_icon.py`), если файла не было, а `make_icon.py` перезаписывал
   существующий файл без вопросов.
3. **Окно уведомления было не таким, как в эталоне.** Входа анимации почти не
   было видно (260 мс, без индикатора на удержании), а этапы шли в секундах, не в
   миллисекундах.
4. **В меню не было раздела «Фильтры».** Логика была (`tray_menu`:
   `CMD_FILTER_RU`, `CMD_FILTER_CF`, `ru_direct()`, `cloudflare()`), а в меню
   помощника на Qt раздел не выводился.
5. **Модальное окно на рабочем столе.** Помощник в режиме `--selftest` печатал
   символ `✓` (U+2713) в stdout. У оконной сборки PyInstaller консоли нет, а её
   «кодировка» на Windows — cp1251: `UnicodeEncodeError` вылетал наружу, и
   PyInstaller показывал окно «Unhandled exception in script».

### Что сделано

**1. Иконка — рисунок пользователя, без единого изменённого пикселя.**
`tray_icon.mark_state` больше ничего не заливает: рисунок копируется как есть, а
состояние связи показывает **метка-кружок в правом нижнем углу** (цвет состояния
+ тонкая тёмная обводка, чтобы читалось и на светлой, и на тёмной панели задач).
Доказательство по пикселям (`forest-ui --selftest`, раздел 1):

```
ДОКАЗАТЕЛЬСТВО ПО ПИКСЕЛЯМ [ok]: совпало с рисунком пользователя 32x32 77.8%,
                               16x16 73.0%; метка в углу 100%
```

77.8 % точек 32×32 совпадают с `app.ico` **байт в байт**; остальные 22.2 % — это
ровно площадь метки. Прежний вариант давал 37.5 % — рисунок был перекрашен.

**2. Сборка иконку не теряет и не подменяет.** `packaging/app.ico.sha256` хранит
хеш иконки пользователя (`df66f49a…6d876`), `build.ps1` и `build-ui.ps1` его
сверяют и **останавливают сборку**, если файла нет (раньше молча рисовалась
другая картинка); `make_icon.py` пишет поверх только с `--force`; Linux-сборки
зовут `packaging/check_icon.sh`.

**3. Окно уведомления — как в эталоне, и анимацию ВИДНО.** Три фазы:

| Фаза | Что происходит | Длительность |
|---|---|---|
| Вход | сдвиг справа на 48 px + проявление из прозрачности | **350 мс** |
| Удержание | у значка крутится индикатор, полоса прогресса доводится плавно (как `pctShown` в эталоне) | 5 с (4 с на финале) |
| Выход | обратный сдвиг + угасание | 260 мс |

60 кадров в секунду, без мерцания, **фокус не перехватывается**
(`Qt.Tool | Qt.WindowDoesNotAcceptFocus`, `WA_ShowWithoutActivating`, показ без
`activateWindow`). Этапы показаны **с временем в миллисекундах**, а финал — с
итоговым временем восстановления связи:

```
Восстановление связи
обрыв обнаружен · пульс порта
[##########------] 60%
✓ Обрыв обнаружен (пульс порта)   50 мс (0.05 с)
✓ Порт поднят (пульс 204)         120 мс (0.12 с)
· Трафик подтверждён (204 + TLS)  180 мс (0.18 с)
прошло 0.35 с · ожидание ~1.2 с
```

Доказательство — серия снимков окна во времени (раздел 5 самотеста):

```
кадров=168 средний FPS=58.8 худший интервал=20.3 мс
фаза входа: 350 мс; разных положений=22, разных прозрачностей=30
положение: (-3573, -3561) -> (-3525, -3561); прозрачность: 0.0 -> 1.0
СНИМКИ ВО ВРЕМЕНИ: 28мс x=-3525 a=0.0 | 268мс x=-3571 a=0.953 | 506мс x=-3573 a=1.0 | …
```

**4. В меню — раздел «Фильтры».** Два пункта-галочки: **«РФ — напрямую»**
(`watch.ru_direct`) и **«Cloudflare — обход»** (`blacklist.cloudflare_nodes`).
Галочка отражает текущее состояние настроек (меню перечитывает `config.json`
каждый тик), а нажатие уходит супервизору через `state/ui_cmd.json`
(`filter_ru_on/off`, `filter_cf_on/off`) и выполняется **тем же кодом**, что и
встроенное меню. Доказано в песочнице на настоящем супервизоре: правила
`geosite:category-ru` / `geosite:tld-ru` / `geosite:category-gov-ru` /
`geosite:category-bank-ru` / `geosite:private` и `geoip:ru` / `geoip:private`
**появляются в живом конфиге ядра** при включении и **исчезают** при выключении,
а узел Cloudflare выпадает из пула.

**5. Модального окна больше не бывает.** `src/safestdio.py`:

* `safe_stdio()` — `stdout`/`stderr` переводятся в `utf-8` + `errors="replace"`,
  а если потока нет вовсе (оконная сборка) — подставляется заглушка;
* `say()` — в stdout уходит **только ASCII** (не-ASCII → `?`), а человекочитаемый
  отчёт пишется в UTF-8-файлы (`state/ui_selftest.txt`, `state/status.txt`,
  `logs/main.log`); `log.py` тоже переведён на него;
* `crash_log()` / `install_excepthook()` / `guarded()` — **любое** необработанное
  исключение пишется трассировкой в `logs/crash.log`, процесс завершается кодом
  70; в спеках PyInstaller включён `disable_windowed_traceback=True`.

Проверено на собранных `.exe` (`win_check.py`: окна перечисляются через
`EnumWindows` до и после прогонов):

```
[B] helper-selftest: код=0, только ASCII=True
[B] helper-crash:    код=70, только ASCII=True
[B] main-selftest:   код=0, только ASCII=True
[B] main-crash:      код=70, только ASCII=True
[C] окон до прогонов: 25; НОВЫХ: 0
[D] crash.log есть и содержит трассировку: True
```

Попутно: `forest_ui` больше не падает `NameError` при импорте без Qt (раньше
вместо тихого «Qt недоступен» была авария), а устаревшая проверка
`tray_check.py` (`state=switch -> ok`) приведена к фактическому поведению
(жёлтый `busy`).

**6. Linux.** Своего окна уведомлений там нет — **этапы и их длительности в
миллисекундах уходят в ТЕЛО** системного уведомления
(`org.freedesktop.Notifications`). Значок приложения
(`forest-proxy-updater.png` — тот же рисунок пользователя, проверено: отличие от
исходного PNG = 0.0 на канал) ставится в
`share/icons/hicolor/256x256/apps` и указан в `.desktop`
(`Icon=forest-proxy-updater`); тема берётся из системных настроек.

---

## 🇬🇧 English

### What was wrong

1. **The tray icon was not the user's artwork.** `tray_icon.user_state_ico` painted
   the state colour **over** `app.ico` at 90 % blend — the drawing collapsed into a
   flat coloured tile.
2. **The build could silently replace the icon.** `build.ps1` drew a *generated*
   `app.ico` when the file was missing and `make_icon.py` overwrote an existing file.
3. **The notification window was not the reference one** — the entrance was barely
   visible (260 ms, no hold indicator) and steps were in seconds, not milliseconds.
4. **No "Filters" section in the menu** — the logic existed, the Qt menu never
   showed it.
5. **A modal window on the desktop.** `--selftest` printed `✓` (U+2713) to stdout;
   a windowed build has no console and cp1251 on Windows, so `UnicodeEncodeError`
   escaped and PyInstaller showed "Unhandled exception in script".

### What was done

1. **The artwork is copied with not a single altered pixel**; the state is a
   **badge in the bottom-right corner** (`tray_icon.mark_state`). Proof:
   `77.8 %` of the 32×32 pixels are byte-identical to `app.ico` (was 37.5 %).
2. **The build verifies the icon** against `packaging/app.ico.sha256` and stops
   when it is missing (`-GenerateIcon` is the opt-in); `make_icon.py` needs
   `--force`; the Linux builds run `packaging/check_icon.sh`.
3. **Three visible animation phases** — entrance 48 px slide + fade **350 ms**,
   hold (spinner + eased progress bar), exit 260 ms — 60 fps, no flicker, focus
   never taken. Steps carry **millisecond durations** and the final line carries
   the **recovery time in ms**: `восстановлено за 1.85 с (1850 мс)`.
4. **A "Filters" submenu** with **RU direct** and **Cloudflare bypass** checkable
   items; the tick follows the live settings and the click travels through
   `state/ui_cmd.json` to the supervisor. Proved in the sandbox against the real
   supervisor: the `geosite:` / `geoip:` rules appear in the **live core config**
   when enabled and disappear when disabled.
5. **No modal window is possible any more** (`src/safestdio.py`): safe stdout,
   ASCII-only `say()`, UTF-8 report files, `crash_log()` + `guarded()` (exit 70),
   and `disable_windowed_traceback=True` in every spec. Verified on the built
   `.exe` files with window enumeration before/after: **0 new windows**.
6. **Linux**: steps and their ms go into the **body** of the system notification;
   the app icon is the same artwork and is installed into the hicolor theme and
   named in the `.desktop` file.

---

## Проверки / Checks

| Что | Как проверено |
|---|---|
| значок = рисунок пользователя | `forest-ui --selftest`, раздел 1: 77.8 % пикселей 32×32 идентичны `app.ico`, метка 100 % в центре |
| анимация видна | раздел 5: 22 разных положения, 30 разных прозрачностей, фаза входа 350 мс, 58.8 к/с, фокус не перехвачен |
| этапы в мс | разделы 5, 5а: `50 мс (0.05 с)`, `120 мс`, `180 мс`, `1850 мс` |
| «Фильтры» в меню | раздел 2 (подменю + две галочки), раздел 4 (обе команды в каждую сторону) |
| фильтры ДЕЙСТВУЮТ | песочница, реальный супервизор: правила РФ в живом конфиге ядра появляются/исчезают; узел Cloudflare выпадает из пула |
| нет модального окна | `win_check.py`: 4 прогона (selftest/crash × помощник/программа), 0 новых окон, stdout только ASCII, `crash.log` с трассировкой, коды 0/0/70/70 |
| Linux | `forest-ui --selftest` в WSL: этапы в теле уведомления, тема, служба уведомлений; `forest-proxy-updater --selftest`: POSIX-тесты пройдены |
