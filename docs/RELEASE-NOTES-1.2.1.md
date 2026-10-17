# v1.2.1 — одноэкземплярность на замке ОС / single-instance lock

**Дата / Date:** 2026-10-17 · **Тег / Tag:** `v1.2.1`
**Артефакты / Artifacts:** `ForestProxyUpdater.exe` (Windows), `forest-ui.exe`
(Windows helper), `forest-proxy-updater` (Linux ELF), `forest-ui` (Linux helper),
пакеты `.deb` / `.rpm` / Arch `.pkg.tar.zst` / AppImage / `.tar.gz`.

---

## 🇷🇺 Русский

### Что было не так

Программа могла работать **двумя экземплярами одновременно**, и у каждого был
свой помощник интерфейса — то есть **два значка в трее** и два супервизора.
Воспроизведено на живой машине, в журнале — две строки «Супервизор запущен» и
две строки «помощник интерфейса запущен» в одну секунду, а также драка за общие
файлы состояния (`state.json.tmp`, `WinError 32`).

### Корень

«Защита от второго экземпляра» была **файлом-маркером с номером процесса** плюс
скан списка процессов. Это эвристика, и ошибается она в обе стороны — оба
случая проверены:

* **два одновременных запуска → не выживал НИКТО.** Каждый запуск видел в
  списке процессов другого (своя командная строка `--run`, свой путь `.exe`) и
  отказывался стартовать. Проверка до правки: запуск двух копий с разницей
  0.34 с → через 45 секунд **0 процессов**;
* **номер процесса «мёртвый» → маркер забирали, а старый супервизор продолжал
  жить.** Отсюда две пары. Плюс к этому поток каждого супервизора раз в 30 с
  зовёт `ui_helper.ensure()` и поднимал **своего** помощника — отсюда два значка.

### Что сделано

1. **Настоящий замок вместо маркера.** Новый модуль `src/instancelock.py`:
   эксклюзивная блокировка файла на **всё время жизни процесса**
   (`msvcrt.locking`/`LockFile` на Windows, `fcntl.flock` на POSIX). Замок
   снимает **ядро ОС** вместе с процессом — «мёртвых» замков не бывает.
   Блокировка неблокирующая: вторая попытка сразу получает отказ. Файл замка
   `state/supervisor.lock` дополнительно хранит PID/пути — но только для
   диагностики: **все решения принимаются по замку, а не по содержимому**.
2. **Одно правило самоконтроля.** `watchdog.ensure()` (это и `--ensure`, и
   действие задачи Планировщика, и любой внутренний вызов) делает ничего, если
   замок занят; процесс, который **сам** является супервизором, не поднимает
   вторую копию ни при каких обстоятельствах (`FOREST_SUPERVISOR=1` плюс
   отказ в `_spawn_detached`). Запуск сериализован коротким замком
   `state/ensure.lock` — тоже настоящим, без проверок «возраста файла».
3. **Помощник — один значок.** `forest_ui` держит свой замок
   (`state/forest-ui.lock`) с момента старта до выхода; `ui_helper.running()`
   решает по замку (пульс `state/ui_helper.json` — только для показа PID), а
   `ui_helper.ensure()` сериализован и не поднимает копию изнутри помощника.
   Второй помощник теперь тихо выходит.
4. **Встроенный значок трея не спорит с помощником.** Поток трея ждёт помощника
   до 20 с (помощник поднимается на секунду-две позже старта супервизора) и не
   создаёт свой значок вовсе; если помощник появился позже — свой значок
   убирается. Раньше встроенный значок создавался и оставался → два значка.
5. **Скан процессов стал честнее** (только как справка/диагностика): процесс
   считается «нашим» лишь если в его командной строке есть корень **этой**
   установки, поэтому разные установки, песочница и автотесты больше не путают
   друг друга.
6. **Linux:** `posix_platform.ensure()` уважает тот же замок супервизора.
7. **Автотесты:** в `--selftest` добавлены проверки замка (эксклюзивность
   подтверждается независимой попыткой: потомок `fork` на POSIX, второй
   дескриптор на Windows; смерть владельца замок не оставляет; живой замок
   блокирует запуск второй копии; у супервизора и помощника проверено одно и то
   же правило). Проверки добавлены и в самопроверку помощника, и в POSIX-набор.

### Доказательства (живая машина, Windows 11)

| Проверка | Результат |
|---|---|
| (а) чистый старт → ровно одна пара программы и один помощник | `30712 ← WmiPrvSE` → `20248` (программа) и `24528 ← 20248` → `23984` (помощник); состав неизменен **149 с** наблюдения и далее (>3,5 мин по журналу) |
| (б) повторный `--ensure` ×2 и тик задачи при живом супервизоре | состав процессов не изменился ни на один процесс; в журнале трижды «супервизор жив (pid 20248; замок занят) — ничего не делаю» |
| (в) убить супервизор → задача поднимает ровно один | `36348 ← 29640` (процесс `--ensure` задачи) → `16872`; помощник при этом не пострадал |
| (г) помощник один — один значок | второй `forest-ui.exe` вручную: «помощник уже работает — второй не нужен», выход 0; в трее значок помощника, встроенный **не создавался** (в журнале нет `NIM_ADD`, есть «интерфейс ведёт помощник — встроенный значок ждёт в резерве») |
| (д) два одновременных запуска (разница 0.38 с) | выжил **ровно один** экземпляр (`30712`→`20248`, владелец замка `20248`) и **один** помощник; до правки в этом же опыте выживало **0** |
| (е) `--selftest` | Windows: исходники — «ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ»; собранный `.exe` — код 0; собранный помощник `.exe` — код 0 (в покое 0.0 мс CPU за 3 с). Linux: ELF — код 0, **259 OK, 0 FAIL**; `--selftest` помощника на Linux — проверки замка зелёные, единственная красная строка — порог «в покое < 60 мс CPU за 3 с» (в WSL измерено 71.9 мс; на Windows та же сборка даёт 0.0 мс — порог зависит от виртуализации таймеров) |

Ядро (xray на 10808/10820) не трогалось: порт 10808 слушался тем же процессом до
и после установки новой сборки, реестр системного прокси не менялся.

### Файлы

См. таблицу сумм в конце этой заметки и `SHA256SUMS`.

---

## 🇬🇧 English

### What was wrong

The program could run as **two instances at once**, each with its own interface
helper — i.e. **two tray icons** and two supervisors. Reproduced on a live
machine: the log shows two “supervisor started” and two “interface helper
launched” lines within one second, plus two supervisors fighting over the shared
state files (`state.json.tmp`, `WinError 32`).

### Root cause

The “second instance” guard was a **marker file with a process id** plus a
process-list scan. That is a heuristic, and it is wrong in both directions —
both cases were reproduced:

* **two simultaneous launches → ZERO survivors.** Each launch saw the other
  `--run` process in the list (its own command line, its own `.exe` path) and
  refused to start. Before the fix: two copies 0.34 s apart → **0 processes**
  after 45 seconds.
* **the recorded pid looked dead → the marker was taken over while the old
  supervisor kept running.** Hence two pairs. On top of that, every supervisor’s
  `watch` thread calls `ui_helper.ensure()` every 30 s and brought up **its own**
  helper — hence two icons.

### What changed

1. **A real lock instead of a marker.** New module `src/instancelock.py`: an
   exclusive file lock held for the **whole life of the process**
   (`msvcrt.locking`/`LockFile` on Windows, `fcntl.flock` on POSIX). The **OS
   kernel** releases it together with the process, so stale locks cannot exist.
   Locking is non-blocking: a second attempt is refused immediately. The lock
   file `state/supervisor.lock` also carries the pid and paths — but for
   **diagnostics only**: every decision is made by the lock, not by its content.
2. **One rule for self-control.** `watchdog.ensure()` (that is `--ensure`, the
   Task Scheduler action, and any internal caller) does nothing while the lock is
   held; a process that *is* the supervisor never brings up a second copy
   (`FOREST_SUPERVISOR=1` plus a refusal inside `_spawn_detached`). Launching is
   serialised by a short `state/ensure.lock`, also a real lock — no file-age
   heuristics.
3. **One helper, one tray icon.** `forest_ui` holds its own lock
   (`state/forest-ui.lock`) from start to exit; `ui_helper.running()` decides by
   that lock (the `state/ui_helper.json` heartbeat is only used to show the pid),
   `ui_helper.ensure()` is serialised and never launches a copy from inside a
   helper. A second helper now exits quietly.
4. **The built-in tray icon no longer competes with the helper.** The tray thread
   waits up to 20 s for the helper (the helper comes up a second or two after the
   supervisor) and then does not create its own icon at all; if the helper
   appears later, its own icon is removed. Previously the built-in icon was
   created and kept → two icons.
5. **The process scan became honest** (reporting/diagnostics only): a process
   counts as “ours” only if its command line mentions the root of *this*
   installation, so different installations, the sandbox and the self-tests no
   longer see each other.
6. **Linux:** `posix_platform.ensure()` honours the same supervisor lock.
7. **Self-tests:** `--selftest` gained lock checks (exclusivity is proven by an
   independent attempt: a forked child on POSIX, a second handle on Windows; a
   dead owner leaves no held lock; a live lock blocks a second copy; both the
   supervisor and the helper are checked against the same rule). The helper’s own
   self-test and the POSIX set got the same checks.

### Evidence (live machine, Windows 11)

| Check | Result |
|---|---|
| (a) clean start → exactly one program pair and one helper | `30712 ← WmiPrvSE` → `20248` (program) and `24528 ← 20248` → `23984` (helper); unchanged for **149 s** of sampling and beyond (>3.5 min in the log) |
| (b) repeated `--ensure` ×2 and a task tick with a live supervisor | the process set changed by not a single process; the log shows three times “supervisor is alive (pid 20248; lock held) — doing nothing” |
| (c) kill the supervisor → the task brings up exactly one | `36348 ← 29640` (the task’s `--ensure`) → `16872`; the helper was unaffected |
| (d) one helper → one tray icon | a manual second `forest-ui.exe`: “helper is already running — a second is not needed”, exit 0; the tray icon is the helper’s and the built-in icon was **never created** (no `NIM_ADD` in the log, but “the helper owns the interface — the built-in icon waits in reserve”) |
| (e) two simultaneous launches (0.38 s apart) | exactly **one** instance survived (`30712`→`20248`, lock owner `20248`) and **one** helper; before the fix the same experiment ended with **0** survivors |
| (f) `--selftest` | Windows: sources — “ALL CHECKS PASSED”; the built `.exe` — exit 0; the built helper `.exe` — exit 0 (0.0 ms CPU in 3 s idle). Linux: the ELF — exit 0, **259 OK, 0 FAIL**; the helper `--selftest` on Linux — all lock checks green, the single red line is the “< 60 ms CPU in 3 s idle” threshold (71.9 ms measured under WSL, while the same build reports 0.0 ms on Windows — the threshold depends on virtualised timers) |

The core (xray on 10808/10820) was not touched: port 10808 was held by the same
process before and after installing the new build, and the system-proxy registry
was not modified.

---

## SHA256SUMS

| Файл / File | SHA-256 |
|---|---|
| `ForestProxyUpdater.exe` | `af855246d80d37042fcb04b6f96ed3f0a8bb7b2f870d67a17998e4034e8562b9` |
| `forest-ui.exe` | `f063c3748fa8cdb185ec0444e47895b0f2dec5f42ceb8f4ffc7b79052248280a` |
| `forest-proxy-updater-linux-x86_64` | `757c057c6a4940c579d928b7186650b8dc014e98badc3315af324b669a8172a2` |
| `forest-ui-linux-x86_64` | `1c29046f7544189eac44583aedff693c6e8e3cb4a3f00762208b3ae0976599a3` |
| `forest-proxy-updater_1.2.1_amd64.deb` | `bc7d59415f856ee4…` (полностью — в `SHA256SUMS`) |
| `forest-proxy-updater-1.2.1-1.x86_64.rpm` | `a78c69856d09f6de…` |
| `forest-proxy-updater-1.2.1-1-x86_64.pkg.tar.zst` | `6862307eceb71992…` |
| `ForestProxyUpdater-1.2.1-x86_64.AppImage` | `7892dae28f718e4e…` |
| `forest-proxy-updater-1.2.1-linux-x86_64.tar.gz` | `8305a7b76c7e369d…` |

Пакеты и их суммы — в `SHA256SUMS` рядом с этой заметкой / Packages and their
sums are in `SHA256SUMS` next to this note.
