# FOREST's Proxy Auto-updater

Автоматический подбор и переключение прокси-серверов. **По умолчанию —
standalone**: программа НЕ требует v2rayN — сама хранит список серверов, сама
пишет конфиг ядра Xray, сама запускает/останавливает `xray.exe` и сама
ставит/снимает системный прокси Windows. Есть и опциональный режим работы
через v2rayN — для тех, у кого он уже установлен.

- Лицензия: **GPL-3.0** (см. `LICENSE`)
- Языки: Русский + English (см. `README.md`)
- Без сторонних зависимостей — только стандартная библиотека Python
- Один процесс-супервизор вместо трёх отдельных задач Планировщика

## Структура

```
ForestProxyUpdater/
  src/       код программы (Python, только stdlib)
  docs/      документация (отдельный этап)
  packaging/ сборка .exe (PyInstaller-спек, отдельный этап)
  LICENSE, README.md, README.ru.md, .gitignore, config.example.json
```

## Два режима (выбираются в config.json, без правки кода)

| `client.mode` | Поведение |
|---|---|
| `standalone` (по умолчанию) | Своё ядро Xray, свой стор серверов, своё управление системным прокси. v2rayN не нужен. |
| `v2rayn` | Работа через установленный v2rayN (его база и ядро), как в исходном проекте. |

Поиск ядра в standalone: `bin\xray\xray.exe` рядом с программой → `PATH` →
иначе программа предлагает скачать официальный релиз Xray-core
(`https://github.com/XTLS/Xray-core/releases`).

## Первый запуск без настроек

Если конфига нет — `config.example.json` копируется в `config.json` с
разумными дефолтами: без шлюза Cloudflare, `diversity.per_subnet_cap: 1`,
`min_pool_after_cap: 12`, **РФ-напрямую выключено** (чтобы чужим не ломать
маршрутизацию), порты `10808`/`10820`, минимум скорости `1000` КБ/с.

Состояние, логи и рабочий конфиг по умолчанию лежат в
`%LOCALAPPDATA%\ForestProxyUpdater` — каталог исходников остаётся чистым.

## Команды

```
python v2ray_updater.py --install     # раскладка в %LOCALAPPDATA%\ForestProxyUpdater,
                                      # ярлык + автозапуск + первый цикл
python v2ray_updater.py --uninstall   # снять всё, вернуть системный прокси
python v2ray_updater.py --run         # обычный запуск: супервизор с треем (потоки)
python v2ray_updater.py --once        # один полный цикл подбора серверов
python v2ray_updater.py --guard       # одна быстрая самопроверка/восстановление
python v2ray_updater.py --status      # текущее состояние
python v2ray_updater.py --selftest    # автотесты
```

Фоновые процессы запускаются без окон консоли (`CREATE_NO_WINDOW` /
семантика `pythonw`).

## Проверка

```
python -m py_compile src/*.py
python src/v2ray_updater.py --selftest
```

## Что осталось на следующие этапы

- Значок в трее (Win32 NotifyIcon через ctypes). Канал состояния
  (`state/tray_status.json`) и его поток-потребитель уже есть — не хватает
  только визуального значка.
- Полное покрытие i18n (строки CLI переведены; сообщения длинных циклов пока
  на русском).
- Сборка одного `.exe` через PyInstaller (см. `packaging/`).
- Документация (см. `docs/`).
