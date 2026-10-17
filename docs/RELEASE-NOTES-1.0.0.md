<!--
  Заметки о выпуске 1.0.0 / Release notes 1.0.0
  Файл двуязычный: сначала русский, затем английский.
  Готов для вставки в описание GitHub Release (gh release create --notes-file).
-->

# FOREST's Proxy Auto-updater 1.0.0 — заметки о выпуске

**Что это.** Программа для Windows, которая автоматически подбирает и
переключает прокси-серверы. Она скачивает публичные списки серверов,
проверяет их, отбирает рабочие и поддерживает связь, переключаясь между ними —
чтобы падение одного сервера не обрывало интернет. По умолчанию работает сама
по себе, **v2rayN не нужен**.

## Два режима

Режим выбирается в `config.json` (ключ `client.mode`), без правки кода:

- **`standalone` (по умолчанию).** Программа сама хранит список серверов,
  сама пишет конфиг ядра Xray, сама запускает и останавливает `xray.exe` и сама
  ставит/снимает системный прокси Windows.
- **`v2rayn` (опция).** Работа через уже установленный v2rayN: его базу
  (`guiNDB.db`), его конфиг (`guiNConfig.json`) и его ядро. Перед записью база
  резервируется, при неудаче — откат.

## Ключевые возможности

- **Свой пул серверов.** Программа ведёт собственный список серверов и
  сохраняет ваши серверы: они не вытесняются автоматически подобранными.
- **Балансировщик Xray.** Серверы, прошедшие проверку, кладутся в **одно**
  запущенное ядро как пул выходов с нативным `observatory` (проверки здоровья)
  и балансировкой `leastPing`. Xray отправляет новые соединения на живой и
  быстрый узел **без перезапуска ядра** — падение одного узла не рвёт связь.
- **Сторож (watchdog).** Непрерывно проверяет локальный порт через ядро;
  мёртвый порт замечает за 1–2 секунды и пересобирает пул. Следит за
  пропускной способностью и использует YouTube как «канарейку»; при полном
  отказе запрашивает полный цикл подбора.
- **Автопереключение и страховка.** При сбое — переключение по сохранённым
  серверам, затем полный цикл; при отсутствии живых серверов поднимается
  аварийный пул «последний удачный». Плюс страховка размера пула: ограничение
  «не больше N узлов с одной подсети» автоматически ослабляется, если иначе
  пул выходит слишком маленьким для переключения при обрыве.
- **Трей с меню.** Значок в системном трее (три состояния: зелёный — работает,
  серый — прокси выключен вручную, красный — нет связи) с контекстным меню:
  включить/выключить прокси вручную, показать состояние, обновить серверы
  сейчас, открыть лог, выход.
- **Один процесс-супервизор** вместо трёх отдельных задач Планировщика: внутри
  одного процесса — сторож, гвард (быстрая самопроверка), цикл обновления и
  трей.
- **Без сторонних зависимостей Python** — только стандартная библиотека.
- **Двуязычный интерфейс** — русский и английский (выбор в `ui.lang` или по
  локали системы).

## Что меняется в системе

Программа меняет систему намеренно, и об этом стоит знать до запуска:

- **Системный прокси Windows.** Записываются `ProxyEnable`/`ProxyServer` в
  `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Internet
  Settings` и указывают на локальный порт программы (`127.0.0.1:10808` по
  умолчанию), чтобы системный трафик шёл через выбранный сервер. Это
  пользовательская настройка (права администратора не нужны). Исходное значение
  сохраняется при первом изменении и восстанавливается командой `--uninstall`.
- **Процесс ядра.** В режиме standalone программа запускает и останавливает
  `xray.exe`. Она завершает только **своё** ядро (по имени своего конфига),
  другие процессы `xray.exe` не трогает.
- Рабочий конфиг, состояние и логи пишутся в `%LOCALAPPDATA%\ForestProxyUpdater`
  — каталог, куда распакован `.exe`, остаётся чистым.

## Требования

- **Windows 10 или новее.** Используются штатные средства системы: `curl.exe`
  (есть в Windows 10 1803+), `PowerShell`, `tasklist`, `taskkill`, `netstat`.
- **Права администратора не нужны.**
- Ядро Xray (**v26.3.27**) и гео-базы (`geoip.dat`, `geosite.dat`) **уже вшиты
  в `.exe`** — отдельно ничего ставить и скачивать не нужно.

## Установка и удаление

- **Установка:** скачать `.exe` и запустить. Windows покажет предупреждение о
  неподписанной программе (SmartScreen) — сборка не подписана, это ожидаемо.
  При первом запуске программа создаёт рабочий конфиг из `config.example.json`,
  раскладывается в `%LOCALAPPDATA%\ForestProxyUpdater`, добавляет ярлык в меню
  «Пуск» и запись в автозапуск и выполняет первый цикл подбора.
- **Удаление:** запустить `.exe` с аргументом `--uninstall`. Останавливает
  ядро, возвращает системный прокси в состояние до первого запуска, убирает
  автозапуск, ярлык и каталог программы.

## Лицензия

**GPL-3.0-only.** См. [`LICENSE`](../LICENSE). Copyright (C) 2026 FOREST.

Программа распространяется в надежде, что будет полезной, но **без каких-либо
гарантий**. Используйте по назначению и по закону: за соблюдение применимых к
вам законов и условий обслуживания отвечаете вы.

---

# FOREST's Proxy Auto-updater 1.0.0 — Release Notes

**What it is.** A Windows program that automatically selects and switches
proxy servers. It downloads public server lists, tests them, keeps the working
ones and keeps your connection going by switching between them — so that a
single server dying does not break your internet access. It works on its own by
default; **v2rayN is not required**.

## Two modes

The mode is chosen in `config.json` (`client.mode`), with no code changes:

- **`standalone` (default).** The program keeps its own server list, writes the
  Xray-core config itself, starts and stops `xray.exe` itself and sets/clears
  the Windows system proxy itself.
- **`v2rayn` (optional).** Works through an already installed v2rayN: its
  database (`guiNDB.db`), its config (`guiNConfig.json`) and its core. The
  database is backed up before writing, with rollback on failure.

## Key features

- **Its own server pool.** The program keeps its own server list and preserves
  your servers: they are not dropped in favour of auto-discovered ones.
- **Native Xray balancer.** Servers that passed the tests are written into
  **one** running core as a pool of outbounds with Xray's own `observatory`
  (health checks) and `leastPing` balancing. Xray sends new connections to a
  live, fast node **without restarting the core**, so a single node dying does
  not break the connection.
- **Watchdog.** Continuously probes the local port through the core; a dead port
  is noticed in 1–2 seconds and the pool is rebuilt. It also watches throughput
  and uses YouTube as a canary; on full failure it asks for a full selection
  cycle.
- **Automatic failover and insurance.** On failure it fails over across the
  stored servers, then runs a full cycle; when no live servers can be found it
  raises the emergency "last good" pool. Plus pool-size insurance: the "at most
  N nodes per subnet" cap is relaxed automatically if the pool would otherwise
  be too small to switch on a drop.
- **Tray icon with a menu.** A system-tray icon (three states: green — working,
  grey — proxy switched off by hand, red — no connection) with a context menu:
  toggle the proxy by hand, show status, refresh servers now, open the log,
  exit.
- **A single supervisor process** instead of three separate scheduled tasks: the
  watchdog, the guard (quick self-check), the update loop and the tray run as
  threads inside one program.
- **No third-party Python dependencies** — the standard library only.
- **Bilingual interface** — Russian and English (`ui.lang`, or the system
  locale).

## What it changes on the system

The program changes the system on purpose, and you should know this before
running it:

- **The Windows system proxy.** It writes `ProxyEnable`/`ProxyServer` under
  `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Internet
  Settings` and points them at the program's local port (`127.0.0.1:10808` by
  default) so that system-wide traffic goes through the selected server. This
  is a user-level setting (no administrator rights required). The original
  value is saved on the first change and restored by `--uninstall`.
- **The core process.** In standalone mode the program starts and stops
  `xray.exe`. It only ever kills *its own* core (identified by its own config
  name); it does not touch other `xray.exe` processes.
- The working config, state and logs live under `%LOCALAPPDATA%\ForestProxyUpdater`
  — the folder you unpacked the `.exe` into stays clean.

## Requirements

- **Windows 10 or newer.** It uses tools that ship with Windows: `curl.exe`
  (Windows 10 1803+), `PowerShell`, `tasklist`, `taskkill`, `netstat`.
- **No administrator rights required.**
- The Xray core (**v26.3.27**) and the geo databases (`geoip.dat`,
  `geosite.dat`) are **already bundled inside the `.exe`** — there is nothing to
  install or download separately.

## Install and uninstall

- **Install:** download the `.exe` and run it. Windows will show an
  unsigned-program warning (SmartScreen) — the build is not signed, and that is
  expected. On first run the program creates its working config from
  `config.example.json`, lays itself out under `%LOCALAPPDATA%\ForestProxyUpdater`,
  adds a Start Menu shortcut and an autostart entry, and runs the first
  selection cycle.
- **Uninstall:** run the `.exe` with `--uninstall`. It stops the core, restores
  the system proxy to the state it had before the first run, and removes the
  autostart entry, the shortcut and the program directory.

## License

**GPL-3.0-only.** See [`LICENSE`](../LICENSE). Copyright (C) 2026 FOREST.

This program is distributed in the hope that it will be useful, but **WITHOUT
ANY WARRANTY**. Use it lawfully — you are responsible for complying with the
laws and terms of service that apply to you.
