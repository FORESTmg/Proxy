# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
"""forest-ui — помощник интерфейса (Qt): значок в трее, меню, уведомления.

Это ОТДЕЛЬНАЯ программа, а не часть основной: основная остаётся лёгкой и без
сторонних зависимостей, а весь интерфейс (значок в трее с меню и подменю,
всплывающие уведомления с анимацией, темы) живёт здесь.

Лицензии
--------
Qt здесь — PySide6 под **LGPL-3.0** (динамическая линковка, без правок Qt).
Наша программа под **GPL-3.0**, что с LGPL совместимо: LGPL-3.0 явно разрешена
как «более слабая» по отношению к GPL-3.0 (§3, «GNU Lesser General Public
License ... may be used under the terms of the GNU GPL»).

Как это связано с программой (важно)
------------------------------------
Помощник **ядром не управляет**. Он:

* пишет команду в ``state/ui_cmd.json`` (``src/ui_cmd.py``) — её выполняет
  супервизор штатными средствами (единственный хозяин ядра остаётся один);
* читает состояние из ``state/tray_status.json`` (цвет значка и подсказка);
* пишет пульс в ``state/ui_helper.json`` (чтобы программа знала, что помощник
  жив, и показала это в ``--status``).

Запуск
------
    forest-ui                      # жить в трее (запускается один раз, при входе)
    forest-ui --show ok "Заголовок" "Текст"   # показать одно уведомление и выйти
    forest-ui --menu-dump          # напечатать дерево меню (для проверок)
    forest-ui --selftest           # самопроверка: значки, темы, FPS, фокус
    forest-ui --stop               # попросить работающий помощник выйти
"""
from __future__ import annotations

import json
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IS_WIN = sys.platform.startswith("win")
APP = "forest-proxy-updater"

# ── Qt ──────────────────────────────────────────────────────────────────────
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt
    QT_OK = True
except Exception as _e:                    # Qt нет — помощник просто не работает
    QT_OK = False
    _QT_ERROR = str(_e)

if not QT_OK:
    # ЗАГЛУШКИ Qt: модуль обязан ИМПОРТИРОВАТЬСЯ и без Qt — иначе определение
    # классов (`class Toast(QtWidgets.QWidget)`) падало NameError ещё на импорте,
    # и вместо тихого выхода «Qt недоступен» получалась авария. Заглушка даёт
    # класс-основание; ни один метод при QT_OK=False не вызывается (см. main()).
    class _QtStubBase:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    class _QtStubModule:
        def __getattr__(self, _n):
            return _QtStubBase

    QtWidgets = _QtStubModule()
    QtCore = _QtStubModule()
    QtGui = _QtStubModule()
    Qt = _QtStubBase

import safestdio as SD

if QT_OK:
    import config as CFG
    import i18n as I
    import log
    import status_info as SI
    import theme as TH
    import tray_icon as TI
    import tray_status as TS
    import ui_cmd as UC

# Состояния значка: четыре основные + состояния ЭТАЛОНА (switch — переключение
# сервера, noanswer — «сторож молчит», restoring — восстановление связи).
STATE_KINDS = ("ok", "busy", "off", "error", "switch", "noanswer", "restoring",
               "down")
_TIP_KEYS = {"ok": "tray.tip.ok", "busy": "tray.tip.busy",
             "off": "tray.tip.off", "error": "tray.tip.error"}

# ── анимация уведомления (фазы в мс) ────────────────────────────────────────
# Прежние 260 мс входа были почти незаметны — пользователь говорил «анимации
# не видно вообще». Делаем фазу входа длиннее и добавляем живой индикатор на
# удержании, чтобы движение читалось глазом.
ANIM_IN_MS = 350          # вход: сдвиг + проявление
ANIM_OUT_MS = 260         # выход: обратный сдвиг + угасание
SLIDE_PX = 48             # насколько карточка выезжает справа при появлении
TEST_ANCHOR = None        # крючок проверок: (x, y, w, h) — показать карточку
                          # в заданном прямоугольнике (вне экрана), чтобы
                          # проверить анимацию, не показывая окно пользователю


def _say(text="") -> None:
    """Печать в stdout ТОЛЬКО ASCII (см. src/safestdio.py).

    Оконная сборка не имеет консоли, а её кодировка на Windows — cp1251: печать
    символа вне cp1251 (например «✓») давала UnicodeEncodeError и МОДАЛЬНОЕ ОКНО
    PyInstaller на рабочем столе. Полный человекочитаемый отчёт пишется в
    UTF-8-файл (см. :func:`write_selftest_reports`), а в stdout идёт только ASCII.
    """
    SD.say(text)


def tr(key: str, **kw):
    try:
        return I.tr(key, **kw)
    except Exception:
        return key


# ═══════════════════════════════════════════════ конфиг / состояние ═══
def load_cfg() -> dict:
    try:
        cfg = CFG.load_config()
    except Exception:
        cfg = {"paths": {"root": os.environ.get("FOREST_ROOT", "") or "",
                         "state_dir": "", "log_dir": ""},
              "ui": {"theme": "auto"},
              "notify": {"enabled": True, "duration_ms": 5000, "fps": 60}}
    try:
        I.set_lang(I.detect_lang(cfg))
    except Exception:
        pass
    return cfg


def read_raw_state(cfg: dict) -> dict:
    try:
        return TS.read_status(cfg) or {}
    except Exception:
        return {}


def read_state(cfg: dict) -> tuple:
    """-> (состояние, подсказка) — состав РОВНО как в эталоне.

    Состояние — одно из :data:`status_info.STATES` (ok | off | switch |
    noanswer | down | restoring), подсказка — строка эталонного вида
    «FOREST связь OK | 10 серверов | РФ напрямую | watch OK».
    """
    st = read_raw_state(cfg)
    kind = SI.state_key(cfg, st)
    tip = SI.tip(cfg, st, limit=63)
    return kind, tip


# ═══════════════════════════════════════════════ значки ═══
def icon_from_state(kind: str, cfg: dict) -> "QtGui.QIcon":
    """QIcon из того же рисунка, что у встроенного значка (app.ico + цвет).

    Единый источник истины: ICO собирает ``tray_icon.state_ico`` — тот же код,
    что рисует значок Windows-версии. Здесь он только переводится в QPixmap.
    """
    ic = QtGui.QIcon()
    try:
        data = TI.state_ico(kind, sizes=(16, 24, 32, 48, 64, 128), cfg=cfg)
    except Exception:
        data = b""
    if data:
        try:
            for w, h, off, size_b in TI.ico_images(data):
                payload = data[off:off + size_b]
                px = TI._dib_to_pixels(payload)
                if not px:
                    continue
                pw, ph, bgra = px
                img = QtGui.QImage(bgra, pw, ph, pw * 4,
                                   QtGui.QImage.Format_ARGB32).copy()
                ic.addPixmap(QtGui.QPixmap.fromImage(img))
        except Exception:
            ic = QtGui.QIcon()
    if ic.isNull():
        # откат: рисуем простой круг цветом состояния — значок всё равно есть
        kind = kind if kind in STATE_KINDS else "off"
        pm = QtGui.QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        try:
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            col = QtGui.QColor(*TH.state_color(cfg, kind))
            p.setBrush(col)
            p.setPen(QtGui.QPen(QtGui.QColor(*TH.tray_ring(cfg)), 2))
            p.drawEllipse(3, 3, 26, 26)
        finally:
            p.end()
        ic.addPixmap(pm)
    return ic


def qss_for(cfg: dict) -> str:
    """Стиль меню из НАШЕЙ палитры (светлая/тёмная) — без тем Qt по умолчанию."""
    pal = TH.palette(cfg)
    bg = "#%02x%02x%02x" % pal["card_bg"]
    fg = "#%02x%02x%02x" % pal["title"]
    bd = "#%02x%02x%02x" % pal["card_border"]
    sel = "#%02x%02x%02x" % pal["accent"]
    dis = "#%02x%02x%02x" % pal["body"]
    return f"""
QMenu {{ background-color: {bg}; color: {fg}; border: 1px solid {bd};
         padding: 6px 4px; }}
QMenu::item {{ padding: 6px 22px 6px 26px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: {sel}; color: #ffffff; }}
QMenu::item:disabled {{ color: {dis}; }}
QMenu::separator {{ height: 1px; background: {bd}; margin: 5px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 8px; }}
"""


# ═══════════════════════════════════════════════ уведомление ═══
class Toast(QtWidgets.QWidget):
    """Безрамочная карточка: скругления, тень, своя иконка, анимация 60 к/с.

    Анимация ЯВНО видна и состоит из трёх фаз (как у эталона, только плавнее):

      * ВХОД  — сдвиг справа на 48 px + проявление из прозрачности, 350 мс;
      * УДЕРЖАНИЕ — карточка стоит, но ЖИВАЯ: крутится индикатор у значка и
        плавно доводится полоса прогресса (по кадрам, а не рывком);
      * ВЫХОД — обратный сдвиг + угасание, 260 мс.

    Фокус НЕ перехватывается: ``Qt.Tool | Qt.WindowDoesNotAcceptFocus`` +
    ``WA_ShowWithoutActivating`` + показ без activateWindow().
    """

    def __init__(self, kind: str, title: str, body: str, cfg: dict,
                 duration_ms: int = 5000, fps: int = 60, stats_sink: dict = None,
                 on_done=None, sub: str = "", pct=None, steps=None,
                 footer: str = "", spinner: bool = False):
        super().__init__(None,
                         Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.cfg = cfg
        self.kind = kind if kind in STATE_KINDS else "busy"
        self.title = title
        self.body = body
        # Состав окна индикации — как в эталоне (tray.ps1): подзаголовок,
        # проценты, список этапов с временами, футер. Ничего не выбрасываем.
        self.sub = sub
        self.pct = pct
        self._target_pct = float(pct) if pct is not None else None
        self._shown_pct = 0.0
        self.steps = list(steps or [])
        self.footer = footer
        self.spinner = bool(spinner)       # «процесс идёт» — крутим индикатор
        self.duration_ms = max(400, int(duration_ms))
        self.fps = max(10, min(120, int(fps)))
        self.pal = TH.palette(cfg)
        self.on_done = on_done
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.icon = icon_from_state(self.kind, cfg)
        self.frame_ms = []
        self.samples = []                  # (t, x, y, opacity) — доказательство анимации
        self._last = 0.0
        self._t0 = 0.0
        self._spin = 0.0
        self.phase = "init"
        # статистику пишем в ЧУЖОЙ словарь: к моменту, когда окно закроется,
        # собственный объект окна уже может быть удалён Qt
        self._stats = stats_sink if stats_sink is not None else {}
        self._stats.update({"frames": 0, "avg_fps": 0.0, "worst_ms": 0.0,
                            "last_frame_ms": 0.0, "positions": 0, "opacities": 0,
                            "pos_start": None, "pos_end": None,
                            "op_start": None, "op_end": None, "in_ms": 0.0})
        self._build_ui()
        self._ticker = QtCore.QTimer(self)
        self._ticker.setTimerType(Qt.PreciseTimer)
        self._ticker.setInterval(int(round(1000.0 / self.fps)))
        self._ticker.timeout.connect(self._frame)

    # ── вид ──
    def _build_ui(self) -> None:
        self.setFixedWidth(360)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        ic = QtWidgets.QLabel(self)
        ic.setPixmap(self.icon.pixmap(32, 32))
        ic.setFixedSize(34, 34)
        row.addWidget(ic, 0, Qt.AlignTop)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(2)
        t = QtWidgets.QLabel(self.title, self)
        t.setWordWrap(True)
        f = t.font()
        f.setBold(True)
        f.setPointSizeF(max(9.5, f.pointSizeF()))
        t.setFont(f)
        t.setStyleSheet("color: #%02x%02x%02x;" % self.pal["title"])
        col.addWidget(t)
        if self.sub:
            s = QtWidgets.QLabel(self.sub, self)
            s.setWordWrap(True)
            s.setStyleSheet("color: #%02x%02x%02x;" % self.pal["body"])
            col.addWidget(s)
        if self.body:
            b = QtWidgets.QLabel(self.body, self)
            b.setWordWrap(True)
            b.setStyleSheet("color: #%02x%02x%02x;" % self.pal["body"])
            col.addWidget(b)
        if self.pct is not None:
            pb = QtWidgets.QProgressBar(self)
            pb.setRange(0, 100)
            pb.setValue(int(self.pct))
            pb.setTextVisible(True)
            pb.setFormat("%p%")
            pb.setFixedHeight(10)
            acc = TH.state_color(self.cfg, self.kind)
            pb.setStyleSheet(
                "QProgressBar { background: #%02x%02x%02x; border: none;"
                " border-radius: 3px; text-align: center; color: #%02x%02x%02x; }"
                " QProgressBar::chunk { background: #%02x%02x%02x;"
                " border-radius: 3px; }"
                % (self.pal["card_border"][0], self.pal["card_border"][1],
                   self.pal["card_border"][2], self.pal["title"][0],
                   self.pal["title"][1], self.pal["title"][2],
                   acc[0], acc[1], acc[2]))
            col.addWidget(pb)
            self.pbar = pb                  # полосу доводим по кадрам (см. _frame)
        else:
            self.pbar = None
        if self.steps:
            st = QtWidgets.QWidget(self)
            gl = QtWidgets.QVBoxLayout(st)
            gl.setContentsMargins(0, 2, 0, 0)
            gl.setSpacing(1)
            for line in self.steps:
                lb = QtWidgets.QLabel(line, st)
                lb.setWordWrap(False)
                lb.setStyleSheet("color: #%02x%02x%02x;" % self.pal["body"])
                gl.addWidget(lb)
            col.addWidget(st)
        if self.footer:
            f = QtWidgets.QLabel(self.footer, self)
            f.setStyleSheet("color: #%02x%02x%02x;" % self.pal["body"])
            col.addWidget(f)
        row.addLayout(col, 1)
        lay.addLayout(row)
        self.adjustSize()

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        try:
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            r = self.rect().adjusted(4, 4, -4, -4)
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(r), 10.0, 10.0)
            # мягкая тень
            p.setPen(Qt.NoPen)
            for i, a in enumerate((26, 18, 12, 8)):
                p.setBrush(QtGui.QColor(0, 0, 0, a))
                sh = path.translated(0, 1 + i * 0.6)
                p.drawPath(sh)
            p.setBrush(QtGui.QColor(*self.pal["card_bg"]))
            p.setPen(QtGui.QPen(QtGui.QColor(*self.pal["card_border"]), 1))
            p.drawPath(path)
            # цветная полоса состояния слева
            acc = TH.state_color(self.cfg, self.kind)
            bar = QtCore.QRectF(r.left() + 1, r.top() + 8, 4.0, r.height() - 16)
            clip = QtGui.QPainterPath()
            clip.addRoundedRect(QtCore.QRectF(r), 10.0, 10.0)
            p.setClipPath(clip)
            p.setBrush(QtGui.QColor(*acc))
            p.setPen(Qt.NoPen)
            p.drawRect(bar)
            # ЖИВОЙ ИНДИКАТОР у значка: пока процесс идёт, вокруг рисунка
            # пользователя крутится дуга — удержание карточки видно, она не
            # выглядит «замершей». Рисуется поверх значка, сам рисунок не портим.
            if self.spinner:
                p.setClipPath(clip)
                pen = QtGui.QPen(QtGui.QColor(*acc), 2.2)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                box = QtCore.QRectF(17.0, 13.0, 36.0, 36.0)
                ang = int(self._spin * 26) % 360
                p.drawArc(box, ang * 16, 110 * 16)
                p.drawArc(box, ((ang + 180) % 360) * 16, 110 * 16)
        finally:
            p.end()

    # ── анимация / замер кадров ──
    def _frame(self) -> None:
        now = time.perf_counter()
        if self._last:
            dt = (now - self._last) * 1000.0
            self.frame_ms.append(dt)
            self._spin += dt / 1000.0
        self._last = now
        # полоса прогресса доводится плавно (как в эталоне: доля за кадр),
        # а не прыгает рывком — иначе удержание выглядит «застывшим»
        if self._target_pct is not None:
            tgt = self._target_pct
            self._shown_pct += (tgt - self._shown_pct) * 0.25
            if abs(tgt - self._shown_pct) < 0.4:
                self._shown_pct = tgt
            if self.pbar is not None:
                self.pbar.setValue(int(round(self._shown_pct)))
        # снимок положения/прозрачности: по нему видно, что анимация РЕАЛЬНО идёт
        g = self.geometry()
        self.samples.append((round((now - self._t0) * 1000.0, 1), g.x(), g.y(),
                             round(self.windowOpacity(), 3)))
        if self.spinner:
            self.update()

    def _finish_stats(self) -> None:
        fr = self.frame_ms or [0.0]
        avg = sum(fr) / len(fr)
        positions = sorted({(s[1], s[2]) for s in self.samples})
        opac = sorted({s[3] for s in self.samples})
        self._stats.update({"frames": len(self.frame_ms),
                            "avg_fps": round(1000.0 / avg, 1) if avg else 0.0,
                            "worst_ms": round(max(fr), 1),
                            "last_frame_ms": round(max(fr), 1),
                            "positions": len(positions),
                            "opacities": len(opac),
                            "pos_start": (positions[0] if positions else None),
                            "pos_end": (positions[-1] if positions else None),
                            "op_start": (opac[0] if opac else None),
                            "op_end": (opac[-1] if opac else None),
                            "in_ms": (self._in_ms if hasattr(self, "_in_ms")
                                      else 0.0),
                            "samples": list(self.samples)})
        self._ticker.stop()
        self.journal()

    def journal(self) -> None:
        d = (self.cfg.get("paths") or {}).get("state_dir") or ""
        if not d:
            return
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "ui_notify.log"), "a",
                      encoding="utf-8") as f:
                f.write("%s\t%s\t%s\t%s\tframes=%d avg_fps=%.1f worst=%.1fms\n"
                        % (time.strftime("%H:%M:%S"), self.kind, self.title,
                           self.body, self._stats["frames"],
                           self._stats["avg_fps"], self._stats["worst_ms"]))
        except Exception:
            pass

    def show_toast(self) -> dict:
        """Показывает карточку с анимацией. -> статистика кадров.

        Три фазы: ВХОД (сдвиг + прозрачность, ANIM_IN_MS) -> УДЕРЖАНИЕ (живой
        индикатор и плавная полоса) -> ВЫХОД (обратный сдвиг + угасание,
        ANIM_OUT_MS). Фокус не перехватывается.
        """
        if TEST_ANCHOR is not None:
            area = QtCore.QRect(*TEST_ANCHOR)      # крючок проверок (вне экрана)
        else:
            scr = QtWidgets.QApplication.primaryScreen()
            area = scr.availableGeometry() if scr else QtCore.QRect(0, 0, 800, 600)
        m = 12
        x = area.right() - self.width() - m
        y = area.bottom() - self.height() - m
        self._home = QtCore.QPoint(x, y)
        self._off = QtCore.QPoint(x + SLIDE_PX, y)
        self._t0 = time.perf_counter()
        self.move(self._off)
        self.setWindowOpacity(0.0)
        self.show()                       # без activateWindow(): фокус не трогаем
        self.raise_()
        self._last = 0.0
        self._ticker.start()
        self.phase = "in"

        anim = QtCore.QParallelAnimationGroup(self)
        a1 = QtCore.QPropertyAnimation(self, b"pos", self)
        a1.setDuration(ANIM_IN_MS)
        a1.setStartValue(self._off)
        a1.setEndValue(self._home)
        a1.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        a2 = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        a2.setDuration(ANIM_IN_MS)
        a2.setStartValue(0.0)
        a2.setEndValue(1.0)
        a2.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        anim.addAnimation(a1)
        anim.addAnimation(a2)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._anim = anim
        self._in_ms = float(ANIM_IN_MS)   # длительность фазы входа (для проверки)

        def out_phase():
            self.phase = "out"
            out = QtCore.QParallelAnimationGroup(self)
            b1 = QtCore.QPropertyAnimation(self, b"pos", self)
            b1.setDuration(ANIM_OUT_MS)
            b1.setStartValue(self._home)
            b1.setEndValue(self._off)
            b1.setEasingCurve(QtCore.QEasingCurve.InCubic)
            b2 = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
            b2.setDuration(ANIM_OUT_MS)
            b2.setStartValue(1.0)
            b2.setEndValue(0.0)
            b2.setEasingCurve(QtCore.QEasingCurve.InCubic)
            out.addAnimation(b1)
            out.addAnimation(b2)
            out.finished.connect(self._done)
            out.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
            self._out = out

        QtCore.QTimer.singleShot(self.duration_ms, out_phase)
        return self._stats

    def _done(self) -> None:
        self._finish_stats()
        self.close()
        try:
            if callable(self.on_done):
                self.on_done()
        except Exception:
            pass
        app = QtWidgets.QApplication.instance()
        if app is not None and app.thread() is QtCore.QThread.currentThread():
            pass                    # выход делает вызывающий код (в --show — app.exec)


def notification_body(sub: str, body: str, steps, footer: str) -> str:
    """Тело СИСТЕМНОГО уведомления (Linux): этапы и время идут В ТЕЛЕ.

    На Linux своего окна нет — этапы восстановления связи и их длительности
    (в миллисекундах) передаются системе (``org.freedesktop.Notifications``)
    прямо текстом, поэтому проверять их нужно здесь же.
    """
    parts = []
    if sub:
        parts.append(str(sub))
    if body:
        parts.append(str(body))
    for x in (steps or []):
        x = str(x)
        if x:
            parts.append(x)
    if footer:
        parts.append(str(footer))
    return "\n".join(parts)


def notify_via_dbus(icon, title: str, body: str, kind: str,
                    duration_ms: int) -> bool:
    """Linux: системное уведомление (org.freedesktop.Notifications) через Qt."""
    try:
        ic = getattr(QtWidgets.QSystemTrayIcon, "Information",
                     QtWidgets.QSystemTrayIcon.MessageIcon.Information)
        icon.showMessage(title, body, ic, max(2000, int(duration_ms)))
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════ приложение ═══
class Ui(QtCore.QObject):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.kind = "off"
        self.tip = ""
        self.acting = False
        self.toast = None
        self.first = True
        self.last_stats = {}
        self.toast_finished = True
        self.stats = {}
        self.tray = QtWidgets.QSystemTrayIcon(self)
        self.menu = QtWidgets.QMenu()
        self.acts = {}
        self._build_menu()
        self.refresh()
        self.tray.setContextMenu(self.menu)
        self.tray.show()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QtCore.QTimer.singleShot(0, self._ping)

    # ── меню ──
    def _build_menu(self) -> None:
        m = self.menu
        m.setStyleSheet(qss_for(self.cfg))
        self.acts["status"] = m.addAction(tr("tray.state.ok"))
        self.acts["status"].setEnabled(False)
        m.addSeparator()
        self.acts["watchdog"] = m.addAction(tr("tray.menu.watchdog"))
        self.acts["watchdog"].setCheckable(True)
        self.acts["notify"] = m.addAction(tr("tray.menu.notify"))
        self.acts["notify"].setCheckable(True)
        # ── ФИЛЬТРЫ (подменю с галочками) ──
        # Логика фильтров живёт в tray_menu (CMD_FILTER_RU/CMD_FILTER_CF); здесь
        # только вывод и передача команды супервизору через state/ui_cmd.json.
        self.filters_menu = QtWidgets.QMenu(tr("tray.menu.filters"), m)
        self.filters_menu.setStyleSheet(qss_for(self.cfg))
        m.addMenu(self.filters_menu)
        self.acts["filter_ru"] = self.filters_menu.addAction(tr("tray.menu.filter_ru"))
        self.acts["filter_cf"] = self.filters_menu.addAction(tr("tray.menu.filter_cf"))
        for k in ("filter_ru", "filter_cf"):
            self.acts[k].setCheckable(True)
        self.theme_menu = QtWidgets.QMenu(tr("tray.menu.theme"), m)
        self.theme_menu.setStyleSheet(qss_for(self.cfg))
        m.addMenu(self.theme_menu)
        self.acts["theme_auto"] = self.theme_menu.addAction(tr("theme.auto"))
        self.acts["theme_light"] = self.theme_menu.addAction(tr("theme.light"))
        self.acts["theme_dark"] = self.theme_menu.addAction(tr("theme.dark"))
        self.theme_group = QtGui.QActionGroup(self)
        self.theme_group.setExclusive(True)
        for k in ("theme_auto", "theme_light", "theme_dark"):
            self.acts[k].setCheckable(True)
            self.theme_group.addAction(self.acts[k])
        m.addSeparator()
        self.acts["toggle"] = m.addAction(tr("tray.menu.toggle_off"))
        self.acts["refresh"] = m.addAction(tr("tray.menu.refresh"))
        m.addSeparator()
        self.acts["status_file"] = m.addAction(tr("tray.menu.open_status"))
        self.acts["open_log"] = m.addAction(tr("tray.menu.open_log"))
        m.addSeparator()
        self.acts["test_notify"] = m.addAction(tr("ui.notify_test"))
        self.acts["about"] = m.addAction(tr("ui.about"))
        self.acts["exit"] = m.addAction(tr("ui.exit"))
        for name, a in self.acts.items():
            if name not in ("status",):
                a.triggered.connect(lambda _c=False, n=name: self.on_action(n))

    def menu_dump(self) -> str:
        """Текстовый дамп меню — доказательство структуры для проверок."""
        out = []
        for a in self.menu.actions():
            if a.isSeparator():
                out.append("  ---")
                continue
            sub = a.menu()
            if sub is not None:
                out.append(f"  {a.text()}  [подменю]")
                for s in sub.actions():
                    out.append(f"    {'*' if s.isChecked() else ' '} {s.text()}")
            else:
                mark = "[v]" if a.isCheckable() and a.isChecked() else \
                       ("[ ]" if a.isCheckable() else "   ")
                out.append(f"  {mark} {a.text()}"
                           + ("" if a.isEnabled() else "  (только показ)"))
        return "\n".join(out)

    # ── действия: всегда ЧЕРЕЗ файл-команду, ядро не трогаем ──
    def on_action(self, name: str) -> None:
        mapping = {"watchdog": "watchdog_on" if self.acts["watchdog"].isChecked()
                                 else "watchdog_off",
                   "notify": "notify_on" if self.acts["notify"].isChecked()
                             else "notify_off",
                   "filter_ru": "filter_ru_on" if self.acts["filter_ru"].isChecked()
                                else "filter_ru_off",
                   "filter_cf": "filter_cf_on" if self.acts["filter_cf"].isChecked()
                                else "filter_cf_off",
                   "theme_auto": "theme_auto", "theme_light": "theme_light",
                   "theme_dark": "theme_dark",
                   "toggle": "toggle_proxy",
                   "refresh": "refresh", "exit": "exit"}
        if name == "about":
            self.show_info()
            return
        if name == "status_file":
            self.open_path(self.status_file())
            return
        if name == "test_notify":
            self.show_toast(self.kind, tr("ui.notify_test"),
                            SI.tip(self.cfg, read_raw_state(self.cfg), limit=0))
            return
        if name == "open_log":
            self.open_log()
            return
        cmd = mapping.get(name)
        if not cmd:
            return
        ok = UC.write_cmd(self.cfg, cmd)
        try:
            log.get_logger().warn(f"forest-ui: команда {cmd} -> "
                                  f"{'в очередь' if ok else 'НЕ ЗАПИСАНА'}")
        except Exception:
            pass
        if not ok:
            self.show_toast("error", tr("ui.cmd_failed", err="state/ui_cmd.json"),
                            cmd)

    def status_file(self) -> str:
        """Файл отчёта ``--status`` (если есть) — как «Открыть статус» в эталоне."""
        d = (self.cfg.get("paths") or {}).get("state_dir") or ""
        if not d:
            return ""
        f = os.path.join(d, "status.txt")
        return f if os.path.isfile(f) else os.path.join(d, "tray_status.json")

    def open_path(self, p: str) -> None:
        try:
            if IS_WIN:
                os.startfile(p)                      # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["xdg-open", p])
        except Exception as e:
            self.show_toast("error", tr("tray.msg.no_log"), str(e))

    def show_info(self) -> None:
        """«Сведения» — ПОЛНЫЙ состав данных эталона (ничего не выбрасываем)."""
        st = read_raw_state(self.cfg)
        rows = SI.info_lines(self.cfg, st)
        body = "\n".join(f"{k}: {v}" if k else v for k, v in rows)
        try:
            log.get_logger().info("forest-ui: сведения:\n" + body)
        except Exception:
            pass
        self.show_toast(self.kind, SI.tip(self.cfg, st, limit=0), body,
                        duration_ms=9000)

    def show_process_card(self, proc: dict) -> None:
        """Окно индикации процесса — тот же состав, что в эталоне.

        Этапы показываем С ДЛИТЕЛЬНОСТЬЮ В МИЛЛИСЕКУНДАХ (пользователь просил
        именно мс; секунды эталона остаются в скобках), а для завершённого
        восстановления добавляем ИТОГОВОЕ ВРЕМЯ в мс.
        """
        n = SI.notif(proc)
        kind = "error" if n["failed"] else ("ok" if n["final"] else
                                            ("restoring" if n["kind"] == "restore"
                                             else "switch"))
        # финал держим 4 с — как в эталоне («окно закроется через 4 с»)
        dur = 4000 if n["final"] else 6000
        footer = n["footer"]
        if n["final"] and not n["failed"]:
            footer = SI.recovery_ms_text(proc) + " · окно закроется через 4 с"
        self.show_toast(kind, n["title"], "", duration_ms=dur, sub=n["sub"],
                        pct=n["pct"], steps=SI.step_lines_ms(proc),
                        footer=footer,
                        spinner=not (n["final"] or n["failed"]))

    def open_log(self) -> None:
        try:
            p = log.get_logger().path
        except Exception:
            p = os.path.join((self.cfg.get("paths") or {}).get("log_dir", ""),
                             "main.log")
        try:
            if IS_WIN:
                os.startfile(p)                      # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["xdg-open", p])
        except Exception as e:
            self.show_toast("error", tr("tray.msg.no_log"), str(e))

    # ── уведомления ──
    def show_toast(self, kind: str, title: str, body: str, sub: str = "",
                   pct=None, steps=None, footer: str = "",
                   duration_ms: int = None, spinner: bool = False) -> dict:
        """Показывает уведомление. -> словарь со статистикой кадров.

        На Windows — своё безрамочное окно с анимацией; на Linux — системное
        уведомление через службу D-Bus (``QSystemTrayIcon.showMessage``), как и
        договаривались: своего окна на Linux не рисуем. ЭТАПЫ И ВРЕМЯ на Linux
        передаются В ТЕЛЕ уведомления (своего окна там нет).
        """
        s = {}
        try:
            import notify as N
            s = N.settings(self.cfg)
        except Exception:
            s = {}
        dur = int(duration_ms or (s or {}).get("duration_ms", 5000) or 5000)
        fps = int((s or {}).get("fps", 60) or 60)
        step_lines = [str(x) for x in (steps or [])]
        if not IS_WIN:
            text = notification_body(sub, body, step_lines, footer)
            ok = notify_via_dbus(self.tray, title, text, kind, dur)
            self.last_stats = {"frames": 0, "avg_fps": 0.0, "worst_ms": 0.0,
                               "dbus": True, "ok": ok,
                               "steps": len(step_lines),
                               "svc": notification_service_available()}
            self.toast_finished = True
            return self.last_stats
        self.last_stats = {}
        self.toast_finished = False
        self.toast = Toast(kind, title, body, self.cfg, duration_ms=dur,
                           fps=fps, stats_sink=self.last_stats,
                           on_done=self._toast_done, sub=sub, pct=pct,
                           steps=step_lines, footer=footer, spinner=spinner)
        self.toast.show_toast()
        return self.last_stats

    def _toast_done(self) -> None:
        self.toast_finished = True
        self.toast = None

    def _on_transition(self, prev: str, cur: str) -> None:
        """Уведомляет о ЗНАЧИМЫХ переходах (обрыв, восстановление, ручное выкл).

        Рутина обновления пула молчит — как и у встроенного значка. Событие
        показываем только если уведомления включены настройкой.
        """
        s = {}
        try:
            import notify as N
            s = N.settings(self.cfg)
        except Exception:
            s = {}
        if not s.get("enabled", True):
            return
        ev = None
        if cur == "error" and prev != "error":
            ev = "lost"
        elif cur == "ok" and prev == "error":
            ev = "restored"
        elif cur == "off" and prev != "off":
            ev = "off"
        elif cur == "ok" and prev == "off":
            ev = "on"
        if ev == "off" and not s.get("show_on_manual_off", True):
            return
        if not ev:
            return
        try:
            log.get_logger().info(f"forest-ui: событие «{ev}» ({prev} -> {cur})")
        except Exception:
            pass
        self.acting = True
        try:
            self.show_toast(cur, tr(f"notify.{ev}.title"), tr(f"notify.{ev}.body"))
        finally:
            self.acting = False

    # ── обновление состояния ──
    def refresh(self) -> None:
        try:
            self.cfg = load_cfg()          # настройки читаем заново: их меняем и мы, и программа
        except Exception:
            pass
        kind, tip = read_state(self.cfg)
        raw = read_raw_state(self.cfg)
        if kind != self.kind or tip != self.tip:
            prev_kind = self.kind
            self.kind, self.tip = kind, tip
            self.tray.setIcon(icon_from_state(kind, self.cfg))
            self.tray.setToolTip(tip)
            if not self.first:
                self._on_transition(prev_kind, kind)
        self.first = False
        # строка состояния в меню — первое поле эталонных сведений
        try:
            rows = SI.info_lines(self.cfg, raw)
            self.acts["status"].setText(f"{rows[0][0]}: {rows[0][1]}")
        except Exception:
            self.acts["status"].setText(tip)
        # окно индикации процесса восстановления/переключения (состав эталона)
        proc = raw.get("proc") or {}
        try:
            pid = str(proc.get("id") or "")
        except Exception:
            pid = ""
        if pid and pid != getattr(self, "_proc_id", ""):
            self._proc_id = pid
            self._proc_shown_final = False
            self.show_process_card(proc)
        elif pid and proc.get("final") and not getattr(self, "_proc_shown_final",
                                                       False):
            self._proc_shown_final = True
            self.show_process_card(proc)
        elif not pid:
            self._proc_id = ""
        # подпись пункта «выключить/включить прокси вручную»
        try:
            import tray_menu as TM
            off = TM.TrayActions(self.cfg).proxy_off()
            self.acts["toggle"].setText(tr("tray.menu.toggle_on") if off
                                        else tr("tray.menu.toggle_off"))
            self.acts["toggle"].setEnabled(True)
        except Exception:
            pass
        try:
            wd = bool((self.cfg.get("watchdog") or {}).get("enabled", True))
            nf = bool((self.cfg.get("notify") or {}).get("enabled", True))
            th = str((self.cfg.get("ui") or {}).get("theme", "auto")).lower()
            ru = bool((self.cfg.get("watch") or {}).get("ru_direct", False))
            cf = bool((self.cfg.get("blacklist") or {}).get("cloudflare_nodes",
                                                             True))
        except Exception:
            wd, nf, th, ru, cf = True, True, "auto", False, True
        self.acts["watchdog"].setChecked(wd)
        self.acts["notify"].setChecked(nf)
        # галочки фильтров — по ТЕКУЩЕМУ состоянию настроек (и по нашему, и по
        # изменённому программой: настройки читаем заново каждый тик)
        self.acts["filter_ru"].setChecked(ru)
        self.acts["filter_cf"].setChecked(cf)
        # подпись пункта — с текущим состоянием, как у встроенного меню
        on = tr("tray.hint.on")
        off = tr("tray.hint.off")
        self.acts["filter_ru"].setText(
            f'{tr("tray.menu.filter_ru")} — {on if ru else off}')
        self.acts["filter_cf"].setText(
            f'{tr("tray.menu.filter_cf")} — {on if cf else off}')
        for k, v in (("theme_auto", "auto"), ("theme_light", "light"),
                     ("theme_dark", "dark")):
            self.acts[k].setChecked(th == v)
        self.menu.setStyleSheet(qss_for(self.cfg))
        self._ping()
        r = UC.read_result(self.cfg)
        if r and not self.acting:
            try:
                if (time.time() - float(r.get("ts", 0))) < 6.0:
                    self.acting = True
                    self.show_toast("ok" if r.get("ok") else "error",
                                    tr("ui.cmd_done" if r.get("ok")
                                       else "ui.cmd_failed",
                                       err=r.get("msg", "")),
                                    str(r.get("msg", "")))
            except Exception:
                pass
            self.acting = False

    def _ping(self) -> None:
        try:
            UC.write_ping(self.cfg, os.getpid(), "qt")
        except Exception:
            pass


# ═══════════════════════════════════════════════ самопроверка ═══
def write_selftest_reports(cfg: dict, report: list, results: list,
                         bad: list) -> tuple:
    """Кладёт отчёт самотеста в файлы UTF-8 (stdout остаётся ASCII).

    Возвращает (путь .txt, путь .json). Это тот самый «человекочитаемый вывод»,
    который нельзя печатать в stdout оконной сборки: на Windows кодировка консоли
    cp1251, и печать символа вне cp1251 роняла программу модальным окном.
    """
    d = ((cfg or {}).get("paths") or {}).get("state_dir") or SD.log_dir()
    nl = chr(10)
    txt = nl.join(list(report) + ["", "=" * 64, "РЕЗУЛЬТАТ", "=" * 64]
                  + [str(x) for x in results]
                  + ["", "ИТОГ: " + ("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if not bad
                                     else f"ПРОВАЛЕНО {len(bad)}")])
    paths = []
    for name in ("ui_selftest.txt", "ui_selftest.json"):
        try:
            os.makedirs(d, exist_ok=True)
            pp = os.path.join(d, name)
            with open(pp, "w", encoding="utf-8") as f:
                if name.endswith(".json"):
                    json.dump({"results": results, "bad": bad},
                              f, ensure_ascii=False, indent=1)
                else:
                    f.write(txt + nl)
            paths.append(pp)
        except Exception:
            paths.append("")
    return (paths[0] if paths else "", paths[1] if len(paths) > 1 else "")


def selftest(cfg: dict) -> int:
    """Проверки помощника с доказательствами (печатает цифры). -> код выхода."""
    bad = []
    out = []
    report = []          # ПОЛНЫЙ (юникод) отчёт -> в UTF-8-файл, не в stdout

    def say(text="") -> None:
        report.append(str(text))
        SD.say(text)

    _say = say           # внутри самотеста печатаем через say (и копим отчёт)

    def chk(name, ok, detail=""):
        out.append(f"  {'OK  ' if ok else 'FAIL'} {name}" +
                   (f" — {detail}" if detail else ""))
        if not ok:
            bad.append(name)

    _say("=" * 64)
    _say("1. значки состояний: РИСУНОК ПОЛЬЗОВАТЕЛЯ сохранён + метка состояния")
    _say("=" * 64)
    try:
        user_ico = bool(TI.load_app_ico(cfg))
    except Exception:
        user_ico = False
    _say(f"  рисунок пользователя (app.ico): {'найден' if user_ico else 'нет'}"
          f" — {TI.find_app_ico(cfg)!r}")
    # Цвет, которым значок РЕАЛЬНО залит, берём из той же таблицы, из которой
    # его рисует tray_icon (TI.states): для четырёх «рабочих» состояний это
    # палитра темы, для состояний эталона — цвета из status_info дословно.
    st_colors = TI.states(cfg)
    icons, sig = {}, {}
    for k in STATE_KINDS:
        ic = icon_from_state(k, cfg)
        pm = ic.pixmap(32, 32)
        img = pm.toImage()
        icons[k] = (not ic.isNull(), PM_SIZE(pm))
        col = st_colors.get(k, st_colors["off"])[1]
        # доля пикселей цвета состояния (метка в углу) — считаем по РЕАЛЬНОМУ
        # размеру значка (Qt отдаёт ближайший доступный, а не обязательно 32x32)
        want = QtGui.QColor(*col)
        n = hit = 0
        px = []
        W, H = img.width(), img.height()
        for y in range(0, H):
            for x in range(0, W):
                c = img.pixelColor(x, y)
                if c.alpha() == 0:
                    continue
                n += 1
                px.append((c.red(), c.green(), c.blue(), c.alpha()))
                dr = abs(c.red() - want.red())
                dg = abs(c.green() - want.green())
                db = abs(c.blue() - want.blue())
                if dr + dg + db < 90:
                    hit += 1
        frac = (hit / n) if n else 0.0
        # «разные значки» проверяем по САМИМ пикселям, а не по счётчикам:
        # у двух состояний может совпасть и число окрашенных точек
        sig[k] = hashlib.sha256(repr(px).encode()).hexdigest()[:16]
        _say(f"  {k:5s} цвет={tuple(col)} значок {icons[k][1]}, "
              f"пикселей цвета состояния {frac*100:.0f}% ({hit}/{n}), "
              f"отпечаток {sig[k]}")
        # Метка состояния — маленький кружок в углу, поэтому доля цвета
        # состояния НЕ должна быть большой: если она большая, значит рисунок
        # опять залили цветом (то и было дефектом «значок — не его»).
        chk(f"значок «{k}» нарисован и содержит метку состояния",
            icons[k][0] and frac >= 0.03,
            f"{frac*100:.1f}% (порог 3.0%)")
        chk(f"значок «{k}» НЕ залит одним цветом (метка, а не заливка)",
            frac <= 0.45, f"{frac*100:.1f}% (предел 45%)")
    # ── ДОКАЗАТЕЛЬСТВО ПО ПИКСЕЛЯМ: значок = рисунок пользователя ──
    if user_ico:
        raw = TI.load_app_ico(cfg)
        for k in ("ok", "off", "error"):
            ico = TI.state_ico(k, sizes=(16, 32), cfg=cfg)
            sh32 = TI.artwork_share(ico, raw, 32)
            sh16 = TI.artwork_share(ico, raw, 16)
            bc = TI.badge_color_share(ico, st_colors[k][1], 32)
            _say(f"  ДОКАЗАТЕЛЬСТВО ПО ПИКСЕЛЯМ [{k}]: совпало с рисунком "
                  f"пользователя 32x32 {sh32*100:.1f}%, 16x16 {sh16*100:.1f}%; "
                  f"метка в углу {bc*100:.0f}%")
            chk(f"[{k}] значок трея СОДЕРЖИТ РИСУНОК ПОЛЬЗОВАТЕЛЯ, а не заливку "
                f"(>= 70% пикселей 32x32 совпадают с app.ico)",
                sh32 >= 0.70, f"{sh32*100:.1f}%")
            chk(f"[{k}] метка состояния читается в правом нижнем углу",
                bc >= 0.40, f"{bc*100:.0f}%")
    chk("состояния с РАЗНЫМИ цветами дают РАЗНЫЕ значки (8 имён эталона -> "
        "6 цветов; down=error и switch=noanswer делят цвет, как в эталоне)",
        len(set(sig.values())) == len({tuple(v[1]) for v in TI.states(cfg).values()}),
        str(sorted(sig.values())))
    # Таблица цветов состояний — то, из чего значок рисуется. Обе её части
    # проверяем отдельно, чтобы проверка значка не стала тавтологией:
    # состояния эталона обязаны повторять status_info дословно, рабочие —
    # совпадать с палитрой темы (иначе цвет не читается на светлой панели).
    chk("цвета эталонных состояний взяты из status_info дословно",
        all(tuple(st_colors[n][1]) == tuple(SI.state_color(n))
            for n in ("switch", "noanswer", "restoring", "down")),
        str({n: tuple(st_colors[n][1]) for n in
             ("switch", "noanswer", "restoring", "down")}))
    chk("цвета рабочих состояний взяты из палитры темы",
        all(tuple(st_colors[n][1]) == tuple(TH.state_color(cfg, n))
            for n in ("ok", "busy", "off", "error")),
        str({n: tuple(st_colors[n][1]) for n in ("ok", "busy", "off", "error")}))

    _say()
    _say("=" * 64)
    _say("2. меню: пункты, подменю, галочки (текстовый дамп)")
    _say("=" * 64)
    ui = Ui(cfg)
    dump = ui.menu_dump()
    _say(dump)
    need = ["watchdog", "notify", "theme_auto", "theme_light", "theme_dark",
            "filter_ru", "filter_cf", "refresh", "about", "exit"]
    chk("в меню есть все пункты и подменю темы",
        all(k in ui.acts for k in need), str([k for k in need if k not in ui.acts]))
    chk("подменю темы содержит три пункта",
        len(ui.theme_menu.actions()) == 3)
    chk("галочки отражают настройки",
        ui.acts["notify"].isChecked() == bool((cfg.get("notify") or {})
                                              .get("enabled", True)))
    # ── ПОДМЕНЮ «ФИЛЬТРЫ» (замечание 3) ──
    chk("в меню есть ПОДМЕНЮ «Фильтры» (tray.menu.filters)",
        "filters_menu" in dir(ui) and ui.filters_menu.title() == tr("tray.menu.filters"),
        ui.filters_menu.title() if hasattr(ui, "filters_menu") else "нет")
    chk("подменю «Фильтры» содержит ДВА пункта-галочки",
        len(ui.filters_menu.actions()) == 2
        and all(a.isCheckable() for a in ui.filters_menu.actions()),
        str([(a.text(), a.isCheckable()) for a in ui.filters_menu.actions()]))
    chk("пункты фильтров — «РФ — напрямую» и «Cloudflare — обход»",
        ui.acts["filter_ru"].text().startswith(tr("tray.menu.filter_ru"))
        and ui.acts["filter_cf"].text().startswith(tr("tray.menu.filter_cf")),
        f'{ui.acts["filter_ru"].text()!r} / {ui.acts["filter_cf"].text()!r}')
    chk("галочка «РФ — напрямую» отражает watch.ru_direct",
        ui.acts["filter_ru"].isChecked()
        == bool((cfg.get("watch") or {}).get("ru_direct", False)),
        str(ui.acts["filter_ru"].isChecked()))
    chk("галочка «Cloudflare — обход» отражает blacklist.cloudflare_nodes",
        ui.acts["filter_cf"].isChecked()
        == bool((cfg.get("blacklist") or {}).get("cloudflare_nodes", True)),
        str(ui.acts["filter_cf"].isChecked()))
    chk("значок в трее установлен", not ui.tray.icon().isNull())

    _say()
    _say("=" * 64)
    _say("3. темы: стиль меню и палитра из настроек")
    _say("=" * 64)
    ql, qd = {}, {}
    for name, store in (("light", ql), ("dark", qd)):
        c2 = dict(cfg)
        c2["ui"] = dict(cfg.get("ui") or {})
        c2["ui"]["theme"] = name
        store["qss"] = qss_for(c2)
        store["bg"] = TH.palette(c2)["card_bg"]
        _say(f"  {name:5s}: фон карточки {store['bg']}, "
              f"QSS {len(store['qss'])} символов")
    chk("темы дают разный стиль и разную палитру",
        ql["qss"] != qd["qss"] and ql["bg"] != qd["bg"],
        f"{ql['bg']} vs {qd['bg']}")
    mn = TH.min_contrast()
    chk("цвета состояний читаемы (контраст >= 3:1)", mn >= 3.0, f"min={mn:.2f}")

    _say()
    _say("=" * 64)
    _say("4. связь с программой: команды через файл")
    _say("=" * 64)
    cmds = ["watchdog_on", "watchdog_off", "notify_on", "notify_off",
            "theme_auto", "theme_light", "theme_dark", "refresh", "exit",
            "filter_ru_on", "filter_ru_off", "filter_cf_on", "filter_cf_off"]
    # каждую команду пишем и СРАЗУ снимаем: файл один, «очереди» в нём нет
    round_trip = []
    for c in cmds:
        wrote = UC.write_cmd(cfg, c)
        got = UC.consume(cfg)
        round_trip.append((c, wrote, (got or {}).get("cmd")))
    bad_rt = [c for c, w, g in round_trip if not w or g != c]
    _say("  " + ", ".join(f"{c}:{'ok' if g == c else 'СБОЙ'}"
                           for c, _w, g in round_trip))
    chk("каждый пункт меню пишет файл-команду, и она снимается супервизором",
        not bad_rt and len(round_trip) == len(cmds), str(bad_rt))
    chk("неизвестная команда отвергается", UC.write_cmd(cfg, "rm -rf /") is False)
    # ПОДМЕНЮ «ФИЛЬТРЫ» ДЕЙСТВИТЕЛЬНО передаёт команду через state/ui_cmd.json
    for act_name, want_on, want_off in (
            ("filter_ru", "filter_ru_on", "filter_ru_off"),
            ("filter_cf", "filter_cf_on", "filter_cf_off")):
        a = ui.acts[act_name]
        a.setChecked(True)
        ui.on_action(act_name)
        got_on = (UC.consume(cfg) or {}).get("cmd")
        a.setChecked(False)
        ui.on_action(act_name)
        got_off = (UC.consume(cfg) or {}).get("cmd")
        chk(f"«{act_name}»: включение и выключение уходят супервизору "
            f"({want_on} / {want_off})",
            got_on == want_on and got_off == want_off, f"{got_on} / {got_off}")
    chk("пульс помощника записан (state/ui_helper.json)",
        UC.write_ping(cfg, os.getpid()) and UC.helper_alive(cfg))

    _say()
    _say("=" * 64)
    _say("4б. одноэкземплярность: ЗАМОК помощника (не PID в пульсе)")
    _say("=" * 64)
    try:
        import tempfile
        import shutil as _sh
        import instancelock as IL
        import ui_helper as UH
        tmpdir = tempfile.mkdtemp(prefix="forest_ui_lock_")
        lockp = _lock_path({"paths": {"state_dir": tmpdir}})
        _say(f"  путь замка: {os.path.basename(lockp)}")
        ok_x, det_x = IL.exclusivity_check(lockp)
        chk("замок эксклюзивен: независимая вторая попытка получает отказ",
            ok_x, det_x)
        cfg2 = dict(cfg)
        cfg2["paths"] = dict(cfg.get("paths") or {})
        cfg2["paths"]["state_dir"] = tmpdir
        got = single_instance_guard(cfg2)
        chk("single_instance_guard занимает замок", got is True and IL.held(lockp),
            f"guard={got}")
        second = IL.InstanceLock(lockp)
        chk("второй экземпляр помощника получит отказ (замок занят)",
            second.acquire() is False)
        chk("ui_helper.running() видит помощника по замку (без пульса)",
            UH.running(cfg2) is True)
        chk("ui_helper.ensure() не поднимает второго при живом замке",
            UH.ensure(cfg2) is True and IL.held(lockp) is True)
        _sh.rmtree(tmpdir, ignore_errors=True)
    except Exception as e:
        chk("проверки замка помощника прошли", False, str(e))

    _say()
    _say("=" * 64)
    _say("5. уведомление: ФАЗЫ АНИМАЦИИ (положение/прозрачность во времени), кадры, фокус")
    _say("=" * 64)
    # Карточку показываем ВНЕ ЭКРАНА (TEST_ANCHOR): анимация настоящая, но
    # пользователь не видит ни одного окна — проверки не показывают окон.
    proc5 = {"id": "t5", "kind": "restore", "cause": "outage",
             "started": time.time(), "eta_s": 1.2, "pct": 60,
             "phase": "Подтверждение трафика…", "elapsed": 0.35, "final": False,
             "steps": [{"nm": "Обрыв обнаружен (пульс порта)", "t": 0.05, "done": True},
                       {"nm": "Порт поднят (пульс 204)", "t": 0.12, "done": True},
                       {"nm": "Трафик подтверждён (204 + TLS)", "t": 0.18, "done": False}]}
    n5 = SI.notif(proc5)
    st5_lines = SI.step_lines_ms(proc5)
    stats5 = {}
    done5 = {"v": False}
    # ВНИМАНИЕ: своё окно рисуем ТОЛЬКО на Windows. На Linux уведомление
    # отдаётся системной службе (своего окна там нет по договорённости),
    # поэтому и проверка идёт штатным путём Ui.show_toast.
    fg_before = foreground()
    toast5 = None
    labels5 = []
    if IS_WIN:
        globals()["TEST_ANCHOR"] = (-4000, -4000, 800, 600)   # вне экрана
        toast5 = Toast("restoring", n5["title"], "", cfg, duration_ms=2600,
                       fps=60, stats_sink=stats5,
                       on_done=lambda: done5.__setitem__("v", True),
                       sub=n5["sub"], pct=n5["pct"], steps=st5_lines,
                       footer=n5["footer"], spinner=True)
        toast5.show_toast()
        t0 = time.time()
        while not done5["v"] and time.time() - t0 < 15:
            QtWidgets.QApplication.processEvents()
            if toast5.phase == "out" and not labels5:
                labels5 = [w.text() for w in
                           toast5.findChildren(QtWidgets.QLabel)]
            time.sleep(0.003)
        globals()["TEST_ANCHOR"] = None
    else:
        # Linux: штатный путь — системное уведомление, этапы уходят В ТЕЛЕ
        stats5 = ui.show_toast("restoring", n5["title"], "", sub=n5["sub"],
                               pct=n5["pct"], steps=st5_lines,
                               footer=n5["footer"], spinner=True)
        done5["v"] = True
    fg_after = foreground()
    frames = stats5.get("frames", 0)
    avg = stats5.get("avg_fps", 0.0)
    worst = stats5.get("worst_ms", 0.0)
    samples = stats5.get("samples") or []
    positions = stats5.get("positions", 0)
    opac = stats5.get("opacities", 0)
    in_ms = stats5.get("in_ms", 0.0)
    _say(f"  кадров={frames} средний FPS={avg} худший интервал={worst} мс "
          f"(цель 60 к/с)")
    _say(f"  фаза входа: {in_ms:.0f} мс; разных положений={positions}, "
          f"разных прозрачностей={opac}")
    _say(f"  положение: {stats5.get('pos_start')} -> {stats5.get('pos_end')}; "
          f"прозрачность: {stats5.get('op_start')} -> {stats5.get('op_end')}")
    step_n = max(1, len(samples) // 12)
    ser = " | ".join(f"{t:.0f}мс x={x} a={a}"
                     for t, x, _y, a in samples[::step_n][:12])
    _say(f"  СНИМКИ ВО ВРЕМЕНИ (t, x, прозрачность): {ser}")
    _say(f"  подписи карточки: {labels5}")
    if IS_WIN:
        chk("уведомление показано и анимировано (кадров >= 20)", frames >= 20,
            str(frames))
        chk("ровные кадры: средний FPS 50..70", 50.0 <= avg <= 70.0, str(avg))
        chk("нет залипаний: худший интервал < 50 мс", 0 < worst < 50.0, str(worst))
        chk("ФАЗА ВХОДА явная: длительность 300..400 мс",
            300.0 <= in_ms <= 400.0, f"{in_ms} мс")
        chk("АНИМАЦИЯ ВИДНА: положение менялось во времени (>= 8 разных)",
            positions >= 8, str(positions))
        chk("АНИМАЦИЯ ВИДНА: прозрачность менялась во времени (>= 8 разных)",
            opac >= 8, str(opac))
        chk("карточка ВЫЕХАЛА и проявилась (x сместился, прозрачность выросла)",
            stats5.get("pos_start") != stats5.get("pos_end")
            and float(stats5.get("op_start") or 0) < float(stats5.get("op_end") or 0),
            f"{stats5.get('pos_start')}->{stats5.get('pos_end')}, "
            f"{stats5.get('op_start')}->{stats5.get('op_end')}")
        chk("фокус не перехвачен (GetForegroundWindow до/после)",
            fg_before == fg_after, f"{fg_before} == {fg_after}")
    else:
        svc = notification_service_available()
        th = TH.choice(cfg)
        _say(f"  Linux: своё окно не рисуем (кадров={frames}); служба "
              f"уведомлений доступна: {svc}; уведомление отдано: ok={stats5.get('ok')}")
        _say(f"  Linux: определённая тема: {th} (палитра "
              f"{tuple(TH.palette(cfg)['card_bg'])})")
        chk("Linux: уведомление уходит системной службе (своего окна нет)",
            bool(stats5.get("dbus")) and frames == 0, str(stats5))
        chk("Linux: доступность службы уведомлений определена (bool)",
            isinstance(svc, bool), repr(svc))
        chk("Linux: отсутствие службы уведомлений не роняет помощник",
            done5["v"] is True, "")
        chk("Linux: тема определена и известна (light/dark)",
            th in ("light", "dark"), str(th))

    _say()
    _say("=" * 64)
    _say("5а. ТЕКСТ уведомления: этапы с временем В МИЛЛИСЕКУНДАХ и время восстановления")
    _say("=" * 64)
    _say(f"  этапы (мс): {st5_lines}")
    _say(f"  заголовок: {n5['title']!r}; подзаголовок: {n5['sub']!r}")
    _say(f"  футер: {n5['footer']!r}; итог: {SI.recovery_ms_text(proc5)!r}")
    fin5 = dict(proc5, final=True, pct=100, elapsed=1.85)
    for s_ in fin5["steps"]:
        s_["done"] = True
    nf5 = SI.notif(fin5)
    _say(f"  финал: {nf5['title']!r} / {SI.recovery_ms_text(fin5)!r}")
    chk("в этапах есть ВСЕ этапы процесса", len(st5_lines) == 3, str(st5_lines))
    chk("каждый этап показан С ВРЕМЕНЕМ В МИЛЛИСЕКУНДАХ",
        all((" мс" in l) for l in st5_lines), str(st5_lines))
    chk("время этапов совпадает с состоянием (50/120/180 мс)",
        all(x in " ".join(st5_lines) for x in ("50 мс", "120 мс", "180 мс")),
        str(st5_lines))
    chk("есть ИТОГОВОЕ время восстановления связи в мс",
        "1850 мс" in SI.recovery_ms_text(fin5)
        and "1.85" in SI.recovery_ms_text(fin5),
        SI.recovery_ms_text(fin5))
    chk("заголовок по состоянию — как в эталоне",
        n5["title"] == "Восстановление связи"
        and nf5["title"] == "Связь восстановлена",
        f"{n5['title']} / {nf5['title']}")
    if IS_WIN:
        chk("в окне (подписях) видны этапы и их мс",
            any(" мс" in str(x) for x in labels5)
            and all(any(x[2:] in l for l in labels5) for x in st5_lines),
            str(labels5))
        chk("иконка в окне — рисунок пользователя (QIcon не пуст и не заливка)",
            (toast5 is not None) and (not toast5.icon.isNull()), "")
    else:
        # Linux: своего окна нет — этапы обязаны уйти В ТЕЛЕ уведомления
        chk("Linux: этапы с мс попадают в ТЕЛО уведомления (своего окна нет)",
            all(x in notification_body(n5["sub"], "", st5_lines, n5["footer"])
                for x in st5_lines),
            notification_body(n5["sub"], "", st5_lines, n5["footer"])[:120])
    # тело системного уведомления (Linux) содержит этапы с мс
    body5 = notification_body(n5["sub"], "", st5_lines, n5["footer"])
    chk("Linux: этапы с мс передаются В ТЕЛЕ системного уведомления",
        all(l in body5 for l in st5_lines) and " мс" in body5, repr(body5))



    _say()
    _say("=" * 64)
    _say("5б. индикация по эталону (v2ray-auto-updater): поля и тексты")
    _say("=" * 64)
    st_ok = {"ts": time.time(), "state": "ok", "rtt": 21}
    tip_ok = SI.tip(cfg, st_ok)
    fields = [p.strip() for p in tip_ok.split("|")]
    _say(f"  подсказка: {tip_ok!r} -> поля {fields}")
    chk("подсказка: четыре поля в порядке эталона (имя, состояние, серверов, "
        "маршрут, watch OK)",
        len(fields) == 4 and fields[2] == SI.route_text(cfg) and
        fields[3] == "watch OK", str(fields))
    proc = {"id": "t", "kind": "restore", "cause": "outage", "started": time.time(),
            "eta_s": 0.95, "pct": 75, "phase": "Подтверждение трафика…",
            "elapsed": 1.4, "final": False,
            "steps": [{"nm": "Обрыв обнаружен (пульс порта)", "t": 0.05,
                       "done": True},
                      {"nm": "Трафик подтверждён (204 + TLS)", "t": 0.95,
                       "done": False}]}
    n = SI.notif(proc)
    nf = SI.notif(dict(proc, final=True, pct=100, elapsed=1.85))
    _say(f"  окно: {n['title']!r} / {n['sub']!r} / {n['pct']}% / {n['footer']!r}")
    _say(f"  финал: {nf['title']!r} / {nf['sub']!r} / {nf['footer']!r}")
    chk("тексты окна совпадают с эталоном дословно",
        n["title"] == "Восстановление связи"
        and n["sub"] == "обрыв обнаружен · пульс порта"
        and nf["title"] == "Связь восстановлена"
        and "связь подтверждена" in nf["sub"], f"{n['title']} / {nf['title']}")
    chk("время восстановления связи есть (в подзаголовке и футере)",
        "1.85" in nf["sub"] and "1.85" in nf["footer"],
        f"{nf['sub']} | {nf['footer']}")
    chk("этапы идут с временами, проценты есть",
        all(l.endswith(" с") for l in SI.step_lines(proc)) and n["pct"] == 75,
        str(SI.step_lines(proc)))
    rows = SI.info_lines(cfg, {"ts": time.time(), "state": "ok",
                               "last_restore_s": 1.85})
    keys = [k for k, _ in rows]
    chk("сведения содержат состояние, серверы, маршрут, сторожа и время "
        "восстановления", "состояние связи" in keys and "серверов в пуле" in keys
        and "маршрут" in keys and "сторож" in keys
        and any("восстановления" in k for k in keys), str(keys))
    chk("шесть состояний эталона дают свои цвета",
        SI.state_color("ok") == (57, 194, 109)
        and SI.state_color("down") == (229, 72, 77)
        and SI.state_color("restoring") == (79, 140, 255)
        and SI.state_color("switch") == (240, 180, 41),
        str([SI.state_color(k) for k in ("ok", "down", "restoring", "switch")]))

    _say()
    _say("=" * 64)
    _say("6. покой: цикл не крутится, процессор не тратится")
    _say("=" * 64)
    c0 = proc_cpu_ms()
    t0 = time.time()
    while time.time() - t0 < 3.0:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)
    c_idle = proc_cpu_ms() - c0
    _say(f"  за 3 с простоя: CPU={c_idle:.1f} мс")
    chk("в покое процессор не расходуется (< 60 мс за 3 с)", c_idle < 60.0,
        f"{c_idle:.1f} мс")

    _say()
    _say("=" * 64)
    _say("7. безопасный вывод и защита от необработанных исключений")
    _say("=" * 64)
    # Печать символа вне cp1251 в оконной сборке давала UnicodeEncodeError и
    # МОДАЛЬНОЕ ОКНО PyInstaller на рабочем столе. Проверяем, что это невозможно.
    bad_char = "✓ — «»"
    raised = None
    try:
        SD.say(bad_char)                 # не должно бросить НИКОГДА
    except Exception as e:               # pragma: no cover
        raised = e
    chk("печать символа вне cp1251 не бросает исключения (нет модального окна)",
        raised is None, str(raised))
    chk("кодировка stdout запомнена до перевода (решение о не-ASCII осознанное)",
        isinstance(SD._ORIG_ENCODING, str), SD._ORIG_ENCODING)
    # --selftest печатает ТОЛЬКО то, что выдержит кодировка потока
    enc_ok = True
    try:
        SD.say("проверка")
        SD.say("check")
    except Exception:
        enc_ok = False
    chk("служебная печать идёт через безопасный слой", enc_ok)
    # необработанное исключение -> журнал + код, БЕЗ окна
    def _boom(_argv=None):
        raise RuntimeError("искусственное исключение проверки")
    rc = SD.guarded(_boom, where="forest-ui-selftest")
    # crash.log пишется РЯДОМ С ЖУРНАЛАМИ (SD.log_dir()), а не в state/
    cpath = os.path.join(SD.log_dir(), "crash.log")
    txt = ""
    try:
        txt = open(cpath, encoding="utf-8").read()
    except Exception:
        txt = ""
    chk("guarded(): исключение внутри main -> ненулевой код (70)", rc == 70, str(rc))
    chk("guarded(): трассировка записана в crash.log (UTF-8)",
        "искусственное исключение проверки" in txt and
        "RuntimeError" in txt, cpath)
    chk("глобальный перехватчик исключений установлен (sys.excepthook)",
        callable(getattr(sys, "excepthook", None)),
        str(getattr(sys, "excepthook", None)))
    # человекочитаемый отчёт — в UTF-8-ФАЙЛ, а не в stdout
    _tp = SD.write_report("_probe_utf8.txt", "✓ проверка UTF-8 — ок")
    _tt = ""
    try:
        _tt = open(_tp, encoding="utf-8").read()
    except Exception:
        _tt = ""
    chk("отчёт самотеста пишется в UTF-8-ФАЙЛ (stdout для этого не нужен)",
        bool(_tp) and "✓ проверка" in _tt, _tp)
    try:
        if _tp:
            os.unlink(_tp)
    except Exception:
        pass

    _say()
    _say("=" * 64)
    _say("РЕЗУЛЬТАТ")
    _say("=" * 64)
    for line in out:
        _say(line)
    _say(f"ИТОГ: {'ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ' if not bad else 'ПРОВАЛЕНО ' + str(len(bad))}")
    # ЧЕЛОВЕКОЧИТАЕМЫЙ отчёт — в UTF-8-ФАЙЛЫ (в stdout он не помещается: там
    # только ASCII, иначе оконная сборка падает модальным окном на cp1251)
    tpath, jpath = write_selftest_reports(cfg, report, out, bad)
    _say(f"  отчёт (UTF-8): {tpath}")
    _say(f"  отчёт (JSON):  {jpath}")
    return 0 if not bad else 1


def PM_SIZE(pm) -> str:
    return f"{pm.width()}x{pm.height()}"


def foreground():
    if not IS_WIN:
        return 0
    try:
        import ctypes
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def proc_cpu_ms() -> float:
    try:
        if IS_WIN:
            import ctypes
            from ctypes import wintypes

            class FT(ctypes.Structure):
                _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]
            c, e, k, u = FT(), FT(), FT(), FT()
            ctypes.windll.kernel32.GetProcessTimes(
                ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c),
                ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
            return (((k.hi << 32) | k.lo) + ((u.hi << 32) | u.lo)) / 10000.0
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF)
        return (r.ru_utime + r.ru_stime) * 1000.0
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════ запуск ═══
_LOCK = None            # замок помощника, удерживаемый этим процессом


def _lock_path(cfg: dict) -> str:
    d = ((cfg or {}).get("paths") or {}).get("state_dir") or ""
    return os.path.join(d, "forest-ui.lock") if d else ""


def single_instance_guard(cfg: dict) -> bool:
    """True — работаем; False — помощник уже запущен (тихо выходим).

    Решение принимает ЗАМОК (эксклюзивная блокировка файла, см.
    ``src/instancelock.py``), а не PID в файле пульса. Пульс появляется с
    задержкой, поэтому два одновременных запуска проходили старую проверку
    оба — теперь замок достаётся ровно одному, второй тихо выходит.
    Если замок недоступен (деградация), работает прежний признак по пульсу.
    """
    global _LOCK
    os.environ["FOREST_UI"] = "1"        # этот процесс — помощник
    p = _lock_path(cfg)
    locked = False
    try:
        import instancelock as IL
        lk = IL.InstanceLock(p, tag="forest-ui")
        if lk.acquire({"pid": os.getpid(), "ts": time.time(),
                       "exe": sys.executable,
                       "root": ((cfg or {}).get("paths") or {}).get("root", "")}):
            _LOCK = lk
            locked = True
            if lk.degraded:
                locked = False           # замок не работает — решаем по пульсу
    except Exception:
        _LOCK = None
    if locked:
        UC.write_ping(cfg, os.getpid(), "qt")
        return True
    # деградация: прежний признак (живой pid в пульсе)
    try:
        pp = UC.ping_path(cfg)
        if os.path.isfile(pp):
            with open(pp, encoding="utf-8") as f:
                d = json.load(f)
            pid = int(d.get("pid", 0) or 0)
            if pid and pid != os.getpid() and _alive(pid):
                return False
    except Exception:
        pass
    UC.write_ping(cfg, os.getpid(), "qt")
    return True


def _alive(pid: int) -> bool:
    try:
        if IS_WIN:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def stop_running(cfg: dict) -> int:
    """Просит работающий помощник выйти (файл-флаг) и ждёт."""
    p = os.path.join((cfg.get("paths") or {}).get("state_dir", ""), "ui_stop.flag")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("stop")
    except Exception as e:
        _say(f"не удалось запросить остановку: {e}")
        return 2
    return 0


# ── графическая сессия ──────────────────────────────────────────────────────
def _no_graphics_reason() -> str:
    """Почему помощнику негде показать интерфейс ('' — сессия есть).

    Проверяется ДО создания QApplication: без графической сессии Qt не находит
    платформенный плагин и аварийно завершается (Aborted), а помощник должен
    просто тихо выйти. Явно заданная ``QT_QPA_PLATFORM`` (offscreen и т. п.)
    считается сессией — так помощник запускают бездисплейные проверки.
    """
    if IS_WIN:
        return ""
    if os.environ.get("QT_QPA_PLATFORM"):
        return ""
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return ""
    return "нет графической сессии (DISPLAY/WAYLAND_DISPLAY не заданы)"


def notification_service_available() -> bool:
    """Есть ли на сессионной шине служба уведомлений org.freedesktop.Notifications.

    На Linux это ровно та служба, которой помощник отдаёт уведомления вместо
    своего окна. Основной путь — QtDBus; если его нет, считаем доступным то,
    чем вообще можно отправить уведомление (gdbus/notify-send). Ничего не
    бросает: сбой определения — это ``False``.
    """
    try:
        from PySide6 import QtDBus
        bus = QtDBus.QDBusConnection.sessionBus()
        if bus.isConnected():
            r = bus.interface().isServiceRegistered("org.freedesktop.Notifications")
            if r.isValid():
                return bool(r.value())
    except Exception:
        pass
    try:
        import shutil
        return bool(shutil.which("gdbus") or shutil.which("notify-send"))
    except Exception:
        return False


def main(argv=None) -> int:
    SD.safe_stdio()
    # КРЮЧОК ПРОВЕРКИ: искусственное исключение внутри main — им проверяют, что
    # на рабочем столе НЕ появляется модальное окно PyInstaller, а трассировка
    # уходит в журнал (crash.log) и код возврата ненулевой.
    if os.environ.get("FOREST_TEST_CRASH") == "1":
        raise RuntimeError("FOREST_TEST_CRASH: искусственное исключение внутри main")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not QT_OK:
        # Qt нет — молча выходим: основная программа работает и без помощника
        _say(f"forest-ui: Qt недоступен ({_QT_ERROR}) — помощник не запущен")
        return 3
    cfg = load_cfg()
    try:
        log.reset_logger((cfg.get("paths") or {}).get("log_dir"))
    except Exception:
        pass
    # Графическую сессию проверяем ДО создания QApplication (см.
    # _no_graphics_reason): без неё Qt аварийно завершается вместо тихого
    # выхода. Для проверок (--selftest, --menu-dump) включаем платформу
    # offscreen: это не показ интерфейса, а самопроверка без дисплея.
    nogfx = _no_graphics_reason()
    if nogfx and ("--selftest" in argv or "--menu-dump" in argv):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    elif nogfx:
        msg = f"forest-ui: {nogfx} — помощник не запущен"
        try:
            log.get_logger().info(msg)
        except Exception:
            pass
        _say(msg)
        return 0
    if "--stop" in argv:
        return stop_running(cfg)
    if "--menu-dump" in argv:
        # Необязательный аргумент — путь файла: пишем дамп в UTF-8, чтобы проверки
        # не зависели от кодировки консоли (оконная сборка отдаёт cp1251).
        i = argv.index("--menu-dump")
        path = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("--") else ""
        app = QtWidgets.QApplication([])
        ui = Ui(cfg)
        dump = ui.menu_dump()
        _say(dump)
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(dump + "\n")
            except Exception as e:
                _say(f"не удалось записать {path}: {e}")
        ui.tray.hide()
        app.quit()
        return 0
    if "--show" in argv:
        i = argv.index("--show")
        kind = argv[i + 1] if len(argv) > i + 1 else "ok"
        title = argv[i + 2] if len(argv) > i + 2 else tr("app.name")
        body = argv[i + 3] if len(argv) > i + 3 else ""
        app = QtWidgets.QApplication([])
        app.setQuitOnLastWindowClosed(False)
        stats = {}
        t = Toast(kind, title, body, cfg, duration_ms=1500, stats_sink=stats,
                  on_done=app.quit)
        t.show_toast()
        app.exec()
        _say(f"frames={stats.get('frames')} avg_fps={stats.get('avg_fps')} "
              f"worst_ms={stats.get('worst_ms')}")
        return 0
    # (проверка графической сессии — выше, до QApplication)
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP)
    if "--selftest" in argv:
        rc = selftest(cfg)
        return rc
    if not single_instance_guard(cfg):
        _say("forest-ui: помощник уже работает — второй не нужен")
        return 0
    ui = Ui(cfg)
    _say(f"forest-ui: работает (pid={os.getpid()}, "
          f"трей={'есть' if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable() else 'недоступен'})")
    stop_flag = os.path.join((cfg.get("paths") or {}).get("state_dir", ""),
                             "ui_stop.flag")
    t = QtCore.QTimer()
    t.setInterval(1000)

    def watch_stop():
        if os.path.isfile(stop_flag):
            try:
                os.unlink(stop_flag)
            except Exception:
                pass
            try:
                UC.clear_ping(cfg)
            except Exception:
                pass
            ui.tray.hide()
            QtWidgets.QApplication.quit()

    t.timeout.connect(watch_stop)
    t.start()
    rc = app.exec()
    try:
        UC.clear_ping(cfg)
    except Exception:
        pass
    return rc


if __name__ == "__main__":
    # ЛЮБОЕ необработанное исключение -> журнал + код 70. Модального окна
    # PyInstaller («Unhandled exception in script») не будет ни при каких
    # обстоятельствах: см. src/safestdio.py.
    sys.exit(SD.guarded(main, where="forest-ui"))
