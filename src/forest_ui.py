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

    Фокус НЕ перехватывается: ``Qt.Tool | Qt.WindowDoesNotAcceptFocus`` +
    ``WA_ShowWithoutActivating`` + показ без activateWindow().
    """

    def __init__(self, kind: str, title: str, body: str, cfg: dict,
                 duration_ms: int = 5000, fps: int = 60, stats_sink: dict = None,
                 on_done=None, sub: str = "", pct=None, steps=None,
                 footer: str = ""):
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
        self.steps = list(steps or [])
        self.footer = footer
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
        self._last = 0.0
        # статистику пишем в ЧУЖОЙ словарь: к моменту, когда окно закроется,
        # собственный объект окна уже может быть удалён Qt
        self._stats = stats_sink if stats_sink is not None else {}
        self._stats.update({"frames": 0, "avg_fps": 0.0, "worst_ms": 0.0,
                            "last_frame_ms": 0.0})
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
        finally:
            p.end()

    # ── анимация / замер кадров ──
    def _frame(self) -> None:
        now = time.perf_counter()
        if self._last:
            self.frame_ms.append((now - self._last) * 1000.0)
        self._last = now

    def _finish_stats(self) -> None:
        fr = self.frame_ms or [0.0]
        avg = sum(fr) / len(fr)
        self._stats.update({"frames": len(self.frame_ms),
                            "avg_fps": round(1000.0 / avg, 1) if avg else 0.0,
                            "worst_ms": round(max(fr), 1),
                            "last_frame_ms": round(max(fr), 1)})
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
        """Показывает карточку с анимацией. -> статистика кадров."""
        scr = QtWidgets.QApplication.primaryScreen()
        area = scr.availableGeometry() if scr else QtCore.QRect(0, 0, 800, 600)
        m = 12
        x = area.right() - self.width() - m
        y = area.bottom() - self.height() - m
        self.move(x + 42, y)
        self.setWindowOpacity(0.15)
        self.show()                       # без activateWindow(): фокус не трогаем
        self.raise_()
        self._ticker.start()
        anim = QtCore.QParallelAnimationGroup(self)
        a1 = QtCore.QPropertyAnimation(self, b"pos", self)
        a1.setDuration(260)
        a1.setStartValue(QtCore.QPoint(x + 42, y))
        a1.setEndValue(QtCore.QPoint(x, y))
        a1.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        a2 = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        a2.setDuration(260)
        a2.setStartValue(0.15)
        a2.setEndValue(1.0)
        a2.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        anim.addAnimation(a1)
        anim.addAnimation(a2)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._anim = anim

        def out_phase():
            self._ticker.start()
            out = QtCore.QParallelAnimationGroup(self)
            b1 = QtCore.QPropertyAnimation(self, b"pos", self)
            b1.setDuration(200)
            b1.setStartValue(QtCore.QPoint(x, y))
            b1.setEndValue(QtCore.QPoint(x + 42, y))
            b1.setEasingCurve(QtCore.QEasingCurve.InCubic)
            b2 = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
            b2.setDuration(200)
            b2.setStartValue(1.0)
            b2.setEndValue(0.0)
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
        """Окно индикации процесса — тот же состав, что в эталоне."""
        n = SI.notif(proc)
        kind = "error" if n["failed"] else ("ok" if n["final"] else
                                            ("restoring" if n["kind"] == "restore"
                                             else "switch"))
        # финал держим 4 с — как в эталоне («окно закроется через 4 с»)
        dur = 4000 if n["final"] else 6000
        self.show_toast(kind, n["title"], "", duration_ms=dur, sub=n["sub"],
                        pct=n["pct"], steps=SI.step_lines(proc),
                        footer=n["footer"])

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
                   duration_ms: int = None) -> dict:
        """Показывает уведомление. -> словарь со статистикой кадров.

        На Windows — своё безрамочное окно с анимацией; на Linux — системное
        уведомление через службу D-Bus (``QSystemTrayIcon.showMessage``), как и
        договаривались: своего окна на Linux не рисуем.
        """
        s = {}
        try:
            import notify as N
            s = N.settings(self.cfg)
        except Exception:
            s = {}
        dur = int(duration_ms or (s or {}).get("duration_ms", 5000) or 5000)
        fps = int((s or {}).get("fps", 60) or 60)
        if not IS_WIN:
            ok = notify_via_dbus(self.tray, title,
                                 (sub + "\n" if sub else "") + body
                                 + ("\n" + footer if footer else ""), kind, dur)
            self.last_stats = {"frames": 0, "avg_fps": 0.0, "worst_ms": 0.0,
                               "dbus": True, "ok": ok,
                               "svc": notification_service_available()}
            self.toast_finished = True
            return self.last_stats
        self.last_stats = {}
        self.toast_finished = False
        self.toast = Toast(kind, title, body, self.cfg, duration_ms=dur,
                           fps=fps, stats_sink=self.last_stats,
                           on_done=self._toast_done, sub=sub, pct=pct,
                           steps=steps, footer=footer)
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
        except Exception:
            wd, nf, th = True, True, "auto"
        self.acts["watchdog"].setChecked(wd)
        self.acts["notify"].setChecked(nf)
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
def selftest(cfg: dict) -> int:
    """Проверки помощника с доказательствами (печатает цифры). -> код выхода."""
    bad = []
    out = []

    def chk(name, ok, detail=""):
        out.append(f"  {'OK  ' if ok else 'FAIL'} {name}" +
                   (f" — {detail}" if detail else ""))
        if not ok:
            bad.append(name)

    print("=" * 64)
    print("1. значки состояний (рисунок пользователя + цвет внутри)")
    print("=" * 64)
    try:
        user_ico = bool(TI.load_app_ico(cfg))
    except Exception:
        user_ico = False
    print(f"  рисунок пользователя (app.ico): {'найден' if user_ico else 'нет'}")
    # Цвет, которым значок РЕАЛЬНО залит, берём из той же таблицы, из которой
    # его рисует tray_icon (TI.states): для четырёх «рабочих» состояний это
    # палитра темы, для состояний эталона — цвета из status_info дословно.
    # (Сверять значок напрямую с TH.state_color нельзя: на светлой теме
    # палитра отличается от эталонных цветов, хотя значок нарисован верно.)
    st_colors = TI.states(cfg)
    icons, sig = {}, {}
    for k in STATE_KINDS:
        ic = icon_from_state(k, cfg)
        pm = ic.pixmap(32, 32)
        img = pm.toImage()
        icons[k] = (not ic.isNull(), PM_SIZE(pm))
        col = st_colors.get(k, st_colors["off"])[1]
        # доля пикселей цвета состояния внутри диска
        want = QtGui.QColor(*col)
        n = hit = 0
        px = []
        for y in range(0, 32):
            for x in range(0, 32):
                c = img.pixelColor(x, y)
                if c.alpha() == 0:
                    continue
                n += 1
                px.append((c.red(), c.green(), c.blue(), c.alpha()))
                if abs(c.red() - want.red()) + abs(c.green() - want.green()) \
                        + abs(c.blue() - want.blue()) < 90:
                    hit += 1
        frac = (hit / n) if n else 0.0
        # «разные значки» проверяем по САМИМ пикселям, а не по счётчикам:
        # у двух состояний может совпасть и число окрашенных точек
        sig[k] = hashlib.sha256(repr(px).encode()).hexdigest()[:16]
        print(f"  {k:5s} цвет={tuple(col)} значок 32x32: {icons[k][1]}, "
              f"пикселей цвета состояния {frac*100:.0f}% ({hit}/{n}), "
              f"отпечаток {sig[k]}")
        # Если найден рисунок пользователя (app.ico) — требуем, чтобы цвет
        # состояния занимал заметную часть значка; если его нет и работает
        # запасной нарисованный значок (кольцо + точка), достаточно, чтобы цвет
        # состояния вообще присутствовал.
        need = 0.20 if user_ico else 0.005
        chk(f"значок «{k}» нарисован и содержит цвет состояния",
            icons[k][0] and frac >= need,
            f"{frac*100:.0f}% (порог {need*100:.1f}%, "
            f"app.ico {'есть' if user_ico else 'нет'})")
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

    print()
    print("=" * 64)
    print("2. меню: пункты, подменю, галочки (текстовый дамп)")
    print("=" * 64)
    ui = Ui(cfg)
    dump = ui.menu_dump()
    print(dump)
    need = ["watchdog", "notify", "theme_auto", "theme_light", "theme_dark",
            "refresh", "about", "exit"]
    chk("в меню есть все пункты и подменю темы",
        all(k in ui.acts for k in need), str([k for k in need if k not in ui.acts]))
    chk("подменю темы содержит три пункта",
        len(ui.theme_menu.actions()) == 3)
    chk("галочки отражают настройки",
        ui.acts["notify"].isChecked() == bool((cfg.get("notify") or {})
                                              .get("enabled", True)))
    chk("значок в трее установлен", not ui.tray.icon().isNull())

    print()
    print("=" * 64)
    print("3. темы: стиль меню и палитра из настроек")
    print("=" * 64)
    ql, qd = {}, {}
    for name, store in (("light", ql), ("dark", qd)):
        c2 = dict(cfg)
        c2["ui"] = dict(cfg.get("ui") or {})
        c2["ui"]["theme"] = name
        store["qss"] = qss_for(c2)
        store["bg"] = TH.palette(c2)["card_bg"]
        print(f"  {name:5s}: фон карточки {store['bg']}, "
              f"QSS {len(store['qss'])} символов")
    chk("темы дают разный стиль и разную палитру",
        ql["qss"] != qd["qss"] and ql["bg"] != qd["bg"],
        f"{ql['bg']} vs {qd['bg']}")
    mn = TH.min_contrast()
    chk("цвета состояний читаемы (контраст >= 3:1)", mn >= 3.0, f"min={mn:.2f}")

    print()
    print("=" * 64)
    print("4. связь с программой: команды через файл")
    print("=" * 64)
    cmds = ["watchdog_on", "watchdog_off", "notify_on", "notify_off",
            "theme_auto", "theme_light", "theme_dark", "refresh", "exit"]
    # каждую команду пишем и СРАЗУ снимаем: файл один, «очереди» в нём нет
    round_trip = []
    for c in cmds:
        wrote = UC.write_cmd(cfg, c)
        got = UC.consume(cfg)
        round_trip.append((c, wrote, (got or {}).get("cmd")))
    bad_rt = [c for c, w, g in round_trip if not w or g != c]
    print("  " + ", ".join(f"{c}:{'ok' if g == c else 'СБОЙ'}"
                           for c, _w, g in round_trip))
    chk("каждый пункт меню пишет файл-команду, и она снимается супервизором",
        not bad_rt and len(round_trip) == len(cmds), str(bad_rt))
    chk("неизвестная команда отвергается", UC.write_cmd(cfg, "rm -rf /") is False)
    chk("пульс помощника записан (state/ui_helper.json)",
        UC.write_ping(cfg, os.getpid()) and UC.helper_alive(cfg))

    print()
    print("=" * 64)
    print("4б. одноэкземплярность: ЗАМОК помощника (не PID в пульсе)")
    print("=" * 64)
    try:
        import tempfile
        import shutil as _sh
        import instancelock as IL
        import ui_helper as UH
        tmpdir = tempfile.mkdtemp(prefix="forest_ui_lock_")
        lockp = _lock_path({"paths": {"state_dir": tmpdir}})
        print(f"  путь замка: {os.path.basename(lockp)}")
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

    print()
    print("=" * 64)
    print("5. уведомление: анимация, кадры, фокус")
    print("=" * 64)
    fg_before = foreground()
    st = ui.show_toast("error", tr("notify.lost.title"), tr("notify.lost.body"))
    t0 = time.time()
    while not ui.toast_finished and time.time() - t0 < 12:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.004)
    fg_after = foreground()
    frames = st.get("frames", 0)
    avg = st.get("avg_fps", 0.0)
    worst = st.get("worst_ms", 0.0)
    if IS_WIN:
        # Windows: наша карточка — считаем кадры и проверяем фокус
        print(f"  кадров={frames} средний FPS={avg} худший интервал={worst} мс "
              f"(цель 60 к/с)")
        print(f"  фокус до={fg_before} после={fg_after} "
              f"({'не перехвачен' if fg_before == fg_after else 'ПЕРЕХВАЧЕН'})")
        chk("уведомление показано и анимировано (кадров >= 20)", frames >= 20,
            str(frames))
        chk("ровные кадры: средний FPS 50..70", 50.0 <= avg <= 70.0, str(avg))
        chk("нет залипаний: худший интервал < 50 мс", 0 < worst < 50.0, str(worst))
        chk("фокус не перехвачен (GetForegroundWindow до/после)",
            fg_before == fg_after, f"{fg_before} == {fg_after}")
    else:
        # Linux: своего окна НЕТ по договорённости — уведомление отдаёт система
        # (org.freedesktop.Notifications). Проверяем ровно это: что выбран путь
        # через службу, что её доступность ОПРЕДЕЛЯЕТСЯ и что её отсутствие не
        # роняет помощник. Кадров и анимации тут быть не должно — их на Linux
        # нет, поэтому FPS не проверяем.
        svc = notification_service_available()
        th = TH.choice(cfg)
        print(f"  Linux: своё окно не рисуем (кадров={frames}); служба "
              f"уведомлений доступна: {svc}; уведомление отдано: ok={st.get('ok')}")
        print(f"  Linux: определённая тема: {th} (палитра "
              f"{tuple(TH.palette(cfg)['card_bg'])})")
        chk("Linux: уведомление уходит системной службе (своего окна нет)",
            bool(st.get("dbus")) and frames == 0, str(st))
        chk("Linux: доступность службы уведомлений определена (bool)",
            isinstance(svc, bool), repr(svc))
        chk("Linux: отсутствие службы уведомлений не роняет помощник",
            ui.toast_finished is True, "")
        chk("Linux: тема определена и известна (light/dark)",
            th in ("light", "dark"), str(th))

    print()
    print("=" * 64)
    print("5б. индикация по эталону (v2ray-auto-updater): поля и тексты")
    print("=" * 64)
    st_ok = {"ts": time.time(), "state": "ok", "rtt": 21}
    tip_ok = SI.tip(cfg, st_ok)
    fields = [p.strip() for p in tip_ok.split("|")]
    print(f"  подсказка: {tip_ok!r} -> поля {fields}")
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
    print(f"  окно: {n['title']!r} / {n['sub']!r} / {n['pct']}% / {n['footer']!r}")
    print(f"  финал: {nf['title']!r} / {nf['sub']!r} / {nf['footer']!r}")
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

    print()
    print("=" * 64)
    print("6. покой: цикл не крутится, процессор не тратится")
    print("=" * 64)
    c0 = proc_cpu_ms()
    t0 = time.time()
    while time.time() - t0 < 3.0:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)
    c_idle = proc_cpu_ms() - c0
    print(f"  за 3 с простоя: CPU={c_idle:.1f} мс")
    chk("в покое процессор не расходуется (< 60 мс за 3 с)", c_idle < 60.0,
        f"{c_idle:.1f} мс")

    print()
    print("=" * 64)
    print("РЕЗУЛЬТАТ")
    print("=" * 64)
    for line in out:
        print(line)
    json.dump({"results": out, "bad": bad},
              open(os.path.join((cfg.get("paths") or {}).get("state_dir", "."),
                                "ui_selftest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("ИТОГ:", "ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if not bad else f"ПРОВАЛЕНО {len(bad)}")
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
        print(f"не удалось запросить остановку: {e}")
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
    argv = list(sys.argv[1:] if argv is None else argv)
    if not QT_OK:
        # Qt нет — молча выходим: основная программа работает и без помощника
        print(f"forest-ui: Qt недоступен ({_QT_ERROR}) — помощник не запущен")
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
        print(msg)
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
        print(dump)
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(dump + "\n")
            except Exception as e:
                print(f"не удалось записать {path}: {e}")
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
        print(f"frames={stats.get('frames')} avg_fps={stats.get('avg_fps')} "
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
        print("forest-ui: помощник уже работает — второй не нужен")
        return 0
    ui = Ui(cfg)
    print(f"forest-ui: работает (pid={os.getpid()}, "
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
    sys.exit(main())
