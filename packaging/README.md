# packaging/ — сборка одного `ForestProxyUpdater.exe`

Всё, что нужно, чтобы из исходников получить **один файл**: скачал — запустил.
Python пользователю не нужен, ставить нечего: внутрь вшиты и код, и ядро Xray,
и гео-базы.

## Требования (только для СБОРКИ)

* Windows x64;
* любой 64-битный Python 3 (`py -3.12` / `python` / `python3` — что найдётся);
* интернет один раз — чтобы скачать PyInstaller и официальный релиз Xray-core.

В рантайме у программы **нет** сторонних зависимостей: только стандартная
библиотека.

## Собрать

```bat
packaging\build.bat
```

или напрямую:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Clean     :: пересобрать с нуля
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -NoVenv   :: без venv, в системный Python
$env:FOREST_PYTHON='C:\Path\to\python.exe'; powershell -File packaging\build.ps1
```

Скрипт идемпотентен — повторный запуск ничего не ломает и не требует ручных
шагов. Что он делает по порядку:

1. находит 64-битный Python 3;
2. поднимает изолированное окружение `.build-venv` и ставит в него PyInstaller
   (пин — `requirements-build.txt`), если его там нет;
3. если нет ядра — качает официальный релиз XTLS/Xray-core (`fetch_core.py`);
   если нет иконки — рисует `app.ico` (`make_icon.py`);
4. запускает PyInstaller по спеке `ForestProxyUpdater.spec`;
5. кладёт результат в `dist\` и печатает размер и SHA256, дублируя их в
   `dist\build-report.json` и `dist\ForestProxyUpdater.exe.sha256`.

Готовый файл: **`packaging\dist\ForestProxyUpdater.exe`**.

## Что внутри одного .exe

Спека `ForestProxyUpdater.spec`: onefile + `console=False` (окна консоли нет),
иконка и ресурс версии приклеены к EXE.

| Внутри | Куда ложится | Кто это находит |
|---|---|---|
| код `src/*.py` | PYZ-архив | «плоские» импорты `import config`, `import clientwrite`, … |
| ядро Xray | `bin\xray\xray.exe` | `config.find_core()` |
| гео-базы | `bin\xray\geoip.dat`, `bin\xray\geosite.dat` | `clientwrite.geo_asset_dir()` (каталог рядом с ядром) |
| лицензия ядра (MPL-2.0) | `bin\xray\LICENSE` | — |
| `config.example.json` | корень пакета | `config.example_config_path()` (первый запуск без конфига) |

Пути подобраны под уже существующий код: при распаковке onefile `__file__`
равен файлу внутри `sys._MEIPASS`, поэтому `config.BASE_DIR` == каталог
распаковки, а `bin\xray\` лежит ровно там, где его ищут.

## Проверить собранное

```bat
cd packaging\dist
copy ..\..\config.example.json .
ForestProxyUpdater.exe --selftest --config config.example.json
ForestProxyUpdater.exe --status   --config config.example.json
```

Ожидаемо: `--selftest` печатает `ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ` и возвращает код 0
(90 проверок, те же, что при запуске из исходников), а `--status` показывает
режим, путь к **вшитому** ядру (внутри `%TEMP%\_MEI...\bin\xray\xray.exe`),
размер пула и состояние системного прокси.

Дополнительно можно убедиться, что ядро и гео-базы внутри .exe побайтово
совпадают с официальным релизом:

```powershell
packaging\.build-venv\Scripts\python.exe packaging\verify_bundle.py
```

## Обновить ядро Xray-core

```bat
packaging\.build-venv\Scripts\python.exe packaging\fetch_core.py --force
```

Скачивание разрешено **только** с `github.com/XTLS/Xray-core/releases/download/...`
(проверка хоста и пути в `fetch_core.py`). Архив сверяется по SHA256 с пином из
`core.lock.json`. Чтобы перейти на новую версию: поправить `core_version.txt`,
скачать, затем `fetch_core.py --print-lock > core.lock.json` и пересобрать.

`vendor\` в git не хранится (там ~63 МиБ бинарников) — он детерминированно
воспроизводится из пина.

## Состав каталога

| Файл | Зачем |
|---|---|
| `ForestProxyUpdater.spec` | спека PyInstaller: onefile, без консоли, иконка+версия |
| `build.ps1` / `build.bat` | сборка (идемпотентно), кладёт .exe в `dist\` |
| `version_info.txt` | ресурс версии: ProductName «FOREST's Proxy Auto-updater», 1.0.0, CompanyName пустой |
| `make_icon.py` | генератор `app.ico` на чистом Python (без PIL): 16…256 px |
| `app.ico` | иконка приложения (сгенерирована `make_icon.py`) |
| `fetch_core.py` | скачивание официального ядра в `vendor\bin\xray\`, проверка SHA256 |
| `core_version.txt`, `core.lock.json` | пин версии и хешей релиза |
| `verify_bundle.py` | сверка вшитых в .exe файлов с пином |
| `requirements-build.txt` | `pyinstaller==6.22.3` (только для сборки) |

Артефакты (`.build-venv\`, `build\`, `dist\`, `vendor\`) в git не попадают —
см. `packaging\.gitignore`.

## Замечания

* **`build.ps1` сохранён в UTF-8 с BOM.** Иначе Windows PowerShell 5.1 читает
  кириллицу как ANSI, принимает её байты за «умные кавычки» и ломает разбор
  строк. При правке файла BOM нужно сохранить.
* **Побитовой идентичности .exe между сборками нет.** Штамп времени в PE
  зафиксирован через `SOURCE_DATE_EPOCH`, но порядок обхода каталогов при
  упаковке архива у PyInstaller не детерминирован, поэтому SHA256 меняется.
  Идемпотентен *процесс*: те же входы → тот же работающий результат, без ручных
  шагов.
* **CompanyName в свойствах файла пустой** — по требованию. Если понадобится,
  впишите его в `version_info.txt` и пересоберите.
* Иконка сгенерирована программно; чтобы изменить мотив, правьте `make_icon.py`
  и запускайте `python make_icon.py`.
* Проверен и отлажен основной путь `build.ps1`/`build.bat` через
  `packaging\.build-venv` (включая установку PyInstaller с нуля). Флаг `-NoVenv`
  (PyInstaller в системный Python) в этой итерации не прогонялся.
* `--status` при первом запуске создаёт каталог программы
  `%LOCALAPPDATA%\ForestProxyUpdater\{state,logs}` — это её штатное поведение;
  системный прокси команда только читает.
