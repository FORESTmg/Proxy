# Доказательство работоспособности Linux-версии (WSL Ubuntu)

Отчёт о фактически выполненной проверке: все команды и выводы ниже получены
запуском, ничего не додумано. Окружение — WSL2 Ubuntu на этом же компьютере;
живой Windows-прокси (порты 10808/10820, реестр, системный прокси) не
затрагивался: тесты идут на своих портах (11808 / с 11810) и в своих каталогах.

## 0. Окружение и предустановки

```sh
wsl -d Ubuntu -- uname -a
# Linux <host> 6.18.33.2-microsoft-standard-WSL2 ... x86_64 GNU/Linux

python3 --version      # Python 3.14.4 (в системе; pip нет — PEP 668)
command -v curl        # /usr/bin/curl
```

Для systemd нужно было включить его в WSL (`/etc/wsl.conf`):

```ini
[user]
default=tester

[boot]
systemd=true
```

```sh
wsl --shutdown && wsl -d Ubuntu -- systemctl --user is-system-running
# running
loginctl enable-linger tester       # службы живут без входа в систему
# Linger=yes
```

Замечено и учтено: в WSL менеджер пользователя иногда не поднимается
(сообщение `Failed to connect to user scope bus`). Лечится перезапуском
`user@<uid>.service`; теперь программа честно сообщает об этом и не делает вид,
что автозапуск настроен (см. `linux/posix_platform.py::user_manager_ok`).

## 1. Артефакт

Сборка (venv только для сборки, в сам бинарник ничего не попадает):

```sh
uv venv --python 3.12 /home/tester/fpu-build/venv
uv pip install --python /home/tester/fpu-build/venv/bin/python pyinstaller
# PyInstaller 6.22.3 | Python 3.12.15

cd <repo>/packaging
python3 fetch_core_linux.py            # ядро Xray-linux-64.zip (пин core.lock.linux.json)
PYI_PYTHON=/home/tester/fpu-build/venv/bin/python sh build-linux.sh --skip-core
```

Результат (итоговый прогон):

```console
$ ls -l linux/dist/
-rwxrwxrwx 1 tester tester 34106472 forest-proxy-updater
-rwxrwxrwx 1 tester tester       87 forest-proxy-updater.sha256

$ cat linux/dist/forest-proxy-updater.sha256
38a8ad4fd09d3de488012ae2d49c410e092ce3a5f9704f1083181e7c956f5fc6  forest-proxy-updater

$ file linux/dist/forest-proxy-updater
ELF 64-bit LSB executable, x86-64, version 1 (SYSV), dynamically linked,
interpreter /lib64/ld-linux-x86-64.so.2, for GNU/Linux 3.2.0,
BuildID[sha1]=e150a976096419cc5c8f6263525324b69993c408, stripped
```

Запуск **вне venv и из /tmp** (в системе Python 3.14 без pip — то есть бинарник
несёт свой Python и своё ядро):

```console
$ cd /tmp/fpu-demo && ./forest-proxy-updater --selftest
rc=0
строк OK:  158
строк FAIL:0
POSIX-тесты пройдены.
```

Внутри пакета: `bin/xray/{xray,geoip.dat,geosite.dat,LICENSE}`, весь код
`src/` + `linux/` и шаблоны юнитов `linux/systemd/`.

## 2. Доказательство A — РЕАЛЬНЫЕ публичные серверы

Боевой конфиг (`config.example.json` с источниками по умолчанию), свой корень,
порт 11808, тестовые порты с 11810, системный прокси выключен.

```sh
FOREST_ROOT=/home/tester/fpu-real FOREST_CONFIG=/home/tester/fpu-real/config.json \
  timeout 720 /tmp/fpu-demo/forest-proxy-updater --once
# --- rc=0 ---
```

Выдержка из лога (полный — `logs/main.log`):

```
INFO  Найдено репозиториев: 33, свежих: 23
INFO    + источник Pawdroid/Free-servers -> https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub
INFO    НОВЫЙ (fixed): rjsxrd-bypass (310151 байт)
INFO    без изменений (fixed): pawdroid-freeservers        <-- кэш источников работает
INFO    ebrasha-free-v2ray: распознано 13684 серверов
INFO    epodonios-v2ray-configs: распознано 4426 серверов
INFO    aliiLAPRO-v2rayNG: распознано 3156 серверов
INFO  Кандидатов > 120; взято 120
INFO  TCP-предфильтр: 75/96 доступны по сети
INFO  RTT пройдено: 40, отсеяно: 35 | причины: {'http_0': 35}
INFO  Стабильных (джиттер <= 800 мс): 35/40
INFO  Тест скорости: отобрано 27 из 33 (подсетей: 27, кап на подсеть: 1)
INFO  Скорость: проверено 27, отсеяно 4, медленных 6
INFO    прошедших порог: 17 (макс 15015, медиана 3347 КБ/с)
INFO  Финал. проверка 17: RTT повторно + YouTube
INFO  Финальный отбор: 14/16 прошли RTT+YouTube
INFO  Топ-10 по скорости:
INFO    #1 vless 78.159.x.x:2053 ... rtt=315 мс | speed=14.7 МБ/с   (адрес узла сокращён)
INFO  Стор обновлён: 14 [AUTO]-серверов, активный: 148473100437392988
INFO  перезапуск ядра: РАЗРЫВ связи 72 мс (порт принял соединения), подтверждение данных 1110 мс, rtt=503 мс
INFO  Балансировщик поднят: 5 серверов (rtt=503.1 мс, разрыв 72 мс)
INFO  Активация завершена: balancer_ok (rtt=1098.6 мс)
INFO  Подписка для ручного импорта: .../state/subscription_base64.txt (14 серверов)
```

Трафик через наше ядро на реальных серверах:

```console
$ curl -x http://127.0.0.1:11808 -o /dev/null -w '%{http_code}' \
      https://www.gstatic.com/generate_204
HTTP=204 time=1.354833s
```

Вывод: полный путь продукта на Linux работает на живых публичных списках —
автопоиск источников, разбор, фильтры (подсети),
TCP-предфильтр, RTT, скорость, финальная проверка, балансировщик, замер разрыва.

## 3. Доказательство B — песочница целиком (установка → служба → ядро → 204 → восстановление → удаление)

Детерминированный вариант: узел — локальный сервер xray (`127.0.0.1:12808`),
отдаваемый программе обычным источником (локальный HTTP на `127.0.0.1:12810`).
Цепочка трафика настоящая:
`curl → 127.0.0.1:11808 (наше ядро) → 127.0.0.1:12808 (сервер) → интернет`.

### 3.1 Установка

```console
$ FOREST_ROOT=/home/tester/fpu-sandbox FOREST_CONFIG=/home/tester/fpu-sandbox/config.json \
    /tmp/fpu-demo/forest-proxy-updater --install
INFO  бинарь установлен: /home/tester/fpu-sandbox/forest-proxy-updater (34106472 байт)
INFO    ядро и гео-базы в /home/tester/fpu-sandbox/bin/xray: xray, geoip.dat, geosite.dat, LICENSE
INFO    конфиг уже есть: /home/tester/fpu-sandbox/config.json
INFO    юнит записан: /home/tester/.config/systemd/user/forest-proxy-updater.service
INFO    юнит записан: /home/tester/.config/systemd/user/forest-proxy-updater-refresh.service
INFO    юнит записан: /home/tester/.config/systemd/user/forest-proxy-updater.timer
INFO    systemctl --user daemon-reload: OK
INFO    systemctl --user enable --now forest-proxy-updater.service forest-proxy-updater.timer: OK
INFO    автозапуск без входа в систему (linger): включён
--- rc=0 ---
```

Что разложено:

```
     16725  /home/tester/fpu-sandbox/bin/xray/LICENSE
  19768301  /home/tester/fpu-sandbox/bin/xray/geoip.dat
  10491954  /home/tester/fpu-sandbox/bin/xray/geosite.dat
  36577406  /home/tester/fpu-sandbox/bin/xray/xray
      1799  /home/tester/fpu-sandbox/config.json
  34106472  /home/tester/fpu-sandbox/forest-proxy-updater
```

Юнит (важные строки):

```
StartLimitIntervalSec=0
ExecStart=/home/tester/fpu-sandbox/forest-proxy-updater --run
Environment=FOREST_ROOT=/home/tester/fpu-sandbox
Environment=FOREST_CONFIG=/home/tester/fpu-sandbox/config.json
KillMode=control-group
Restart=always
RestartSec=5
```

### 3.2 Отбор серверов и активация (цикл, начатый СЛУЖБОЙ)

```
порт 11808 поднялся через 30 с
INFO  Цикл FOREST's Proxy Auto-updater | режим: standalone | ядро: /tmp/_MEI.../bin/xray/xray
INFO    НОВЫЙ (fixed): local-test (111 байт)
INFO    local-test: распознано 1 серверов
INFO  Кандидатов на тест: 1
INFO  TCP-предфильтр: 1/1 доступны по сети
INFO  RTT пройдено: 1, отсеяно: 0 | причины: {}
INFO  Скорость: проверено 1, отсеяно 0, медленных 0
INFO  Финал. проверка 1: RTT повторно + YouTube
INFO  Финальный отбор: 0/1 прошли RTT+YouTube        <-- см. «ограничения» ниже
WARN  Строгий отбор пуст — резерв по RTT: 1 серверов
INFO  Проверка скорости резерва: 1 из 1 прошли порог 100 КБ/с
INFO  Пишу стор и активирую (режим балансировщика)...
INFO  перезапуск ядра: РАЗРЫВ связи 72 мс (порт принял соединения), подтверждение данных 425 мс, rtt=36 мс
INFO  Балансировщик поднят: 1 серверов (rtt=35.6 мс, разрыв 72 мс)
INFO  Активация завершена: balancer_ok (rtt=30.8 мс)
```

### 3.3 Служба

```console
$ systemctl --user status forest-proxy-updater.service --no-pager | head -16
● forest-proxy-updater.service - FOREST's Proxy Auto-updater (супервизор: сторож + гвард + обновление)
     Loaded: loaded (/home/tester/.config/systemd/user/forest-proxy-updater.service; enabled; preset: enabled)
     Active: active (running) since Sat 2026-10-17 00:14:29 MSK; 30s ago
   Main PID: 832 (forest-proxy-up)
      Tasks: 20 (limit: 19131)
     Memory: 126.4M (peak: 129.5M)
     CGroup: /user.slice/user-1000.slice/user@1000.service/app.slice/forest-proxy-updater.service
             ├─832 /home/tester/fpu-sandbox/forest-proxy-updater --run
             ├─864 /home/tester/fpu-sandbox/forest-proxy-updater --run
             └─978 /tmp/_MEI.../bin/xray/xray run -c /home/tester/fpu-sandbox/state/xray_config.json

$ systemctl --user is-active  forest-proxy-updater.service   -> active
$ systemctl --user is-enabled forest-proxy-updater.service   -> enabled
$ systemctl --user list-timers forest-proxy-updater.timer --no-pager
NEXT                         LEFT   UNIT                        ACTIVATES
Sat 2026-10-17 00:22:58 MSK  7min   forest-proxy-updater.timer  forest-proxy-updater-refresh.service
```

### 3.4 Реальный трафик через ядро

```console
$ ss -lntH | grep 11808
LISTEN 0  4096  127.0.0.1:11808  0.0.0.0:*

$ curl -x http://127.0.0.1:11808 -o /dev/null -w '%{http_code}' \
      https://www.gstatic.com/generate_204
HTTP=204  time=0.030420s
$ curl -x socks5h://127.0.0.1:11808 ... https://www.gstatic.com/generate_204
HTTP=204  time=0.029351s
$ x3 подряд: try1=204 try2=204 try3=204

$ соединения ядра (видно ретрансляцию на 12808):
ESTAB  0  0  127.0.0.1:50822  127.0.0.1:12808  users:(("xray",pid=978,fd=9))
ESTAB  0  0  127.0.0.1:50882  127.0.0.1:12808  users:(("xray",pid=978,fd=11))
```

### 3.5 `--status`

```
Режим: standalone
Ядро Xray: /tmp/_MEI.../bin/xray/xray
Ядро запущено (pid): /home/tester/fpu-sandbox/state/core.pid -> да
Серверов в пуле: 1
Системный прокси: выключен
Связь: есть (rtt=28.7 мс)
config: /home/tester/fpu-sandbox/config.json
root:   /home/tester/fpu-sandbox
state:  /home/tester/fpu-sandbox/state
logs:   /home/tester/fpu-sandbox/logs
systemd: forest-proxy-updater: active / enabled; таймер forest-proxy-updater.timer: active
indicator: /home/tester/fpu-sandbox/state/tray_status.json
notify-send: недоступен — уведомления только в лог (мягкая деградация)
```

### 3.6 Самовосстановление

```console
ядро до убийства: pid=978
$ pkill -f "/home/tester/fpu-sandbox/state/xray_config.json"
ядро после kill: pid=1047 (прежний 978 снят, супервизор поднял новое)
связь восстановлена через 2 с
--- что писал сторож ---
WARN  Watch: связь не отвечает (удар 1/2, rtt=0)
WARN  Watch: обрыв — пересобираю балансировщик
INFO  Балансировщик поднят: 1 серверов (rtt=28.9 мс, разрыв 72 мс)
INFO  Индикация: связь через прокси восстановлена
INFO  Watch: связь восстановлена по пульсу (rtt=29.0)
--- служба всё ещё активна? ---
active
```

### 3.7 Удаление

```console
$ /tmp/fpu-demo/forest-proxy-updater --uninstall
INFO    systemctl --user disable --now forest-proxy-updater.service: OK
INFO    systemctl --user disable --now forest-proxy-updater.timer: OK
INFO    systemctl --user disable --now forest-proxy-updater-refresh.service: OK
INFO    юнит удалён: /home/tester/.config/systemd/user/forest-proxy-updater.service
INFO    юнит удалён: /home/tester/.config/systemd/user/forest-proxy-updater-refresh.service
INFO    юнит удалён: /home/tester/.config/systemd/user/forest-proxy-updater.timer
INFO    конфиг удалён: /home/tester/fpu-sandbox/config.json
INFO    данные программы удалён: /home/tester/fpu-sandbox
INFO    состояние/логи удалён: /home/tester/.local/state/forest-proxy-updater
Удаление завершено: юниты сняты, ядро остановлено, файлы удалены.
--- rc=0 ---

--- проверка, что всё убрано ---
служба: inactive
юнитов forest-*: 0
каталог песочницы: удалён
конфиг в песочнице: удалён
наших ядер xray: 0
слушателей на 11808: 0
таймер: inactive

$ systemctl --user list-units "forest*"
  UNIT LOAD ACTIVE SUB DESCRIPTION

0 loaded units listed.
```

## 4. Автотесты

| Что | Команда | Результат |
| --- | --- | --- |
| Общие + POSIX (в исходниках, Linux) | `python3 src/v2ray_updater.py --selftest` | 12 разделов + P1…P8, без FAIL |
| То же в собранном ELF | `/tmp/fpu-demo/forest-proxy-updater --selftest` | **158 OK, 0 FAIL**, rc=0 |
| Регрессия Windows (общие тесты) | `python.exe D:\ForestProxyUpdater\src\selftest.py` | **ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ**, 110 OK, 0 FAIL |
| Регрессия Windows (пути/диспетчер) | отдельный набор из 31 проверки | все OK |

Разделы общих тестов: API-поверхность, `server_to_row↔row_to_server`,
стор и `[AUTO]`, конфиг ядра, конфиг балансировщика, диспетчер режимов, первый запуск конфига, поиск ядра,
бесшовность (хэш конфига + проверка до остановки ядра), установщик, StateStore.
Разделы POSIX: подмена примитивов, XDG-пути, `/proc`+`os.kill`, поиск гео-баз,
рендер юнитов systemd, индикация и мягкая деградация `notify-send`, проверка
конфига ядром, доступность systemd.

## 5. Ограничения и что осталось непроверенным

1. **Гейт YouTube в песочнице.** В финальной проверке участвует доступ к
   `https://www.youtube.com`. Из этой сети YouTube недоступен **и напрямую**
   (проверено: `curl` без прокси → `code=000`, таймаут 15 с), поэтому в
   песочнице «строгий отбор» пуст и узел подхватывается встроенной страховкой
   «резерв по RTT» (`WARN Строгий отбор пуст — резерв по RTT`). Механику это не
   ломает: пул поднимается, связь есть. На реальных серверах гейт проходили
   14 узлов из 16 — то есть проблема среды, а не продукта.
2. **Разнообразные окружения.** Проверено только в WSL2 Ubuntu (systemd 259,
   ядро 6.18). Arch/Fedora/openSUSE/KDE не проверялись; системный прокси
   правится только через GNOME `gsettings` (в WSL его нет — программа этого и
   не делает).
3. **Долгий прогон.** Супервизор проверялся минутами (два цикла + восстановление),
   а не сутками: утечки и накопление подпроцессов на длинном горизонте не
   измерялись (zombie-репы закрыты, но статистику не собирали).
4. **`--run` после перезагрузки системы.** `enable` + `linger` настроены и
   проверены (`is-enabled: enabled`, `Linger=yes`), но фактический автозапуск
   после `wsl --shutdown` в этом прогоне не воспроизводился.
5. **Сборка на другой архитектуре.** Только x86_64; aarch64 не собирался.
6. **`linux/tests/`** — каталог с матрицей пакетов (.deb/.rpm/Arch) в этом
   репозитории создан не мной; к результатам выше он отношения не имеет.
